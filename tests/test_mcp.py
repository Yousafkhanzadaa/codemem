from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests"))

from codemem.mcp import MCPServer
from support import write_repo


class MCPServerTests(unittest.TestCase):
    def test_tools_list_includes_mode_aware_query_contract(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            write_repo(root, {"src/billing.ts": "export function createSubscriptionCheckout() { return 'ok'; }"})

            server = MCPServer(root)
            init_response = server._handle_request(  # noqa: SLF001
                {"jsonrpc": "2.0", "id": 0, "method": "initialize", "params": {}}
            )
            self.assertIsNotNone(init_response)
            self.assertEqual(init_response["result"]["serverInfo"]["version"], "0.2.0")
            tools_response = server._handle_request(  # noqa: SLF001
                {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}
            )
            self.assertIsNotNone(tools_response)
            tools = {tool["name"]: tool for tool in tools_response["result"]["tools"]}
            self.assertIn("memory.query", tools)
            self.assertIn("mode", tools["memory.query"]["inputSchema"]["properties"])

    def test_query_tool_returns_packet_with_mode_and_snippet(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            write_repo(
                root,
                {
                    "src/customize.tsx": """
                    export function handleDimensionsChange(width: number, height: number) {
                      return { width, height };
                    }
                    """,
                },
            )

            server = MCPServer(root)
            server.engine.index_repo()
            response = server._handle_request(  # noqa: SLF001
                {
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "tools/call",
                    "params": {
                        "name": "memory.query",
                        "arguments": {
                            "prompt": "where is the dimention logic?",
                            "mode": "locate",
                        },
                    },
                }
            )
            self.assertIsNotNone(response)
            payload = response["result"]["structuredContent"]
            self.assertEqual(payload["retrieval_mode"], "locate")
            self.assertEqual(payload["hits"][0]["entity"]["name"], "handleDimensionsChange")
            self.assertIn("handleDimensionsChange", payload["hits"][0]["snippet"])
            self.assertEqual(payload["focus_files"][0]["path"], "src/customize.tsx")
            json.loads(response["result"]["content"][0]["text"])


if __name__ == "__main__":
    unittest.main()
