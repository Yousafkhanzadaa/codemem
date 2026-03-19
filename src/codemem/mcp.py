from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from codemem.engine import CodeMemEngine
from codemem.models import ENGINE_VERSION

PROTOCOL_VERSION = "2025-11-25"


class MCPServer:
    def __init__(self, repo_root: str | Path) -> None:
        self.engine = CodeMemEngine(repo_root)

    def serve(self) -> None:
        while True:
            message = self._read_message()
            if message is None:
                return
            if isinstance(message, list):
                responses = [self._handle_request(item) for item in message]
                payload = [response for response in responses if response is not None]
                if payload:
                    self._write_message(payload)
                continue
            response = self._handle_request(message)
            if response is not None:
                self._write_message(response)

    def _handle_request(self, message: dict[str, Any]) -> dict[str, Any] | None:
        method = message.get("method")
        request_id = message.get("id")
        params = message.get("params", {})

        try:
            if method == "initialize":
                result = {
                    "protocolVersion": PROTOCOL_VERSION,
                    "capabilities": {"tools": {"listChanged": False}},
                    "serverInfo": {"name": "codemem", "version": ENGINE_VERSION},
                }
                return self._response(request_id, result)
            if method == "notifications/initialized":
                return None
            if method == "ping":
                return self._response(request_id, {})
            if method == "tools/list":
                return self._response(request_id, {"tools": self._tool_definitions()})
            if method == "tools/call":
                result = self._call_tool(params.get("name"), params.get("arguments", {}))
                return self._response(request_id, result)
            if request_id is None:
                return None
            return self._error(request_id, -32601, f"Unknown method: {method}")
        except Exception as exc:  # pragma: no cover
            if request_id is None:
                return None
            return self._error(request_id, -32000, str(exc))

    def _call_tool(self, name: str | None, arguments: dict[str, Any]) -> dict[str, Any]:
        if name == "memory.index_repo":
            payload = self.engine.index_repo().to_dict()
        elif name == "memory.query":
            payload = self.engine.query_memory(
                arguments["prompt"],
                limit=arguments.get("limit", 12),
                mode=arguments.get("mode"),
            ).to_dict()
        elif name == "memory.impact_analysis":
            payload = self.engine.impact_analysis(arguments["request"], limit=arguments.get("limit", 12)).to_dict()
        elif name == "memory.plan_change":
            payload = self.engine.plan_change(arguments["request"], limit=arguments.get("limit", 10)).to_dict()
        elif name == "memory.get_entity":
            entity = self.engine.get_entity(arguments["entity_id"])
            payload = {"entity": entity.to_dict() if entity else None}
        elif name == "memory.get_neighbors":
            payload = self.engine.get_neighbors(arguments["entity_id"])
        elif name == "memory.find_dead_code":
            payload = self.engine.find_dead_code()
        elif name == "memory.refresh":
            payload = self.engine.refresh_memory().to_dict()
        else:
            raise ValueError(f"Unknown tool: {name}")

        return {
            "content": [{"type": "text", "text": json.dumps(payload, indent=2, sort_keys=True)}],
            "structuredContent": payload,
            "isError": False,
        }

    def _tool_definitions(self) -> list[dict[str, Any]]:
        return [
            {
                "name": "memory.index_repo",
                "description": "Build or rebuild repository memory for the configured repository.",
                "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
                "annotations": {"readOnlyHint": False},
            },
            {
                "name": "memory.query",
                "description": "Select a focused memory slice for a natural-language prompt.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "prompt": {"type": "string"},
                        "limit": {"type": "integer", "minimum": 1, "maximum": 50},
                        "mode": {
                            "type": "string",
                            "enum": ["locate", "explain", "impact", "modify", "dead_code", "architecture"],
                        },
                    },
                    "required": ["prompt"],
                    "additionalProperties": False,
                },
                "annotations": {"readOnlyHint": True},
            },
            {
                "name": "memory.impact_analysis",
                "description": "Return the entities and files most likely affected by a requested change.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "request": {"type": "string"},
                        "limit": {"type": "integer", "minimum": 1, "maximum": 50},
                    },
                    "required": ["request"],
                    "additionalProperties": False,
                },
                "annotations": {"readOnlyHint": True},
            },
            {
                "name": "memory.plan_change",
                "description": "Build a constrained change plan from repository memory.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "request": {"type": "string"},
                        "limit": {"type": "integer", "minimum": 1, "maximum": 50},
                    },
                    "required": ["request"],
                    "additionalProperties": False,
                },
                "annotations": {"readOnlyHint": True},
            },
            {
                "name": "memory.get_entity",
                "description": "Fetch a single entity from repository memory by id.",
                "inputSchema": {
                    "type": "object",
                    "properties": {"entity_id": {"type": "string"}},
                    "required": ["entity_id"],
                    "additionalProperties": False,
                },
                "annotations": {"readOnlyHint": True},
            },
            {
                "name": "memory.get_neighbors",
                "description": "Fetch the immediate graph neighborhood for an entity id.",
                "inputSchema": {
                    "type": "object",
                    "properties": {"entity_id": {"type": "string"}},
                    "required": ["entity_id"],
                    "additionalProperties": False,
                },
                "annotations": {"readOnlyHint": True},
            },
            {
                "name": "memory.find_dead_code",
                "description": "List low-confidence dead-code candidates from repository memory.",
                "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
                "annotations": {"readOnlyHint": True},
            },
            {
                "name": "memory.refresh",
                "description": "Rebuild repository memory after code changes.",
                "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
                "annotations": {"readOnlyHint": False},
            },
        ]

    def _read_message(self) -> dict[str, Any] | list[dict[str, Any]] | None:
        headers: dict[str, str] = {}
        while True:
            line = sys.stdin.buffer.readline()
            if not line:
                return None
            decoded = line.decode("utf-8").strip()
            if not decoded:
                break
            name, value = decoded.split(":", 1)
            headers[name.strip().lower()] = value.strip()

        content_length = int(headers.get("content-length", "0"))
        if content_length <= 0:
            return None
        body = sys.stdin.buffer.read(content_length)
        return json.loads(body.decode("utf-8"))

    def _write_message(self, payload: dict[str, Any] | list[dict[str, Any]]) -> None:
        body = json.dumps(payload).encode("utf-8")
        header = f"Content-Length: {len(body)}\r\n\r\n".encode("utf-8")
        sys.stdout.buffer.write(header)
        sys.stdout.buffer.write(body)
        sys.stdout.buffer.flush()

    @staticmethod
    def _response(request_id: Any, result: dict[str, Any]) -> dict[str, Any]:
        return {"jsonrpc": "2.0", "id": request_id, "result": result}

    @staticmethod
    def _error(request_id: Any, code: int, message: str) -> dict[str, Any]:
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {"code": code, "message": message},
        }


def serve_stdio(repo_root: str | Path) -> None:
    MCPServer(repo_root).serve()
