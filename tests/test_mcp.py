from __future__ import annotations

import json
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from codemem.mcp import MCPServer


class MCPServerTests(unittest.TestCase):
    def test_tools_list_and_tool_call(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "src").mkdir()
            (root / "src" / "billing.ts").write_text(
                textwrap.dedent(
                    """
                    export function createSubscriptionCheckout(planId: string) {
                      return planId.trim();
                    }
                    """
                ).strip()
                + "\n",
                encoding="utf-8",
            )

            server = MCPServer(root)
            server.engine.index_repo()

            tools_response = server._handle_request(  # noqa: SLF001
                {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}
            )
            self.assertIsNotNone(tools_response)
            tools = tools_response["result"]["tools"]
            tool_names = {tool["name"] for tool in tools}
            self.assertIn("memory.plan_change", tool_names)

            plan_response = server._handle_request(  # noqa: SLF001
                {
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "tools/call",
                    "params": {
                        "name": "memory.plan_change",
                        "arguments": {"request": "replace checkout with subscriptions"},
                    },
                }
            )
            self.assertIsNotNone(plan_response)
            payload = plan_response["result"]["structuredContent"]
            self.assertEqual(payload["intent_category"], "flow_migration")
            self.assertIn("src/billing.ts", payload["impacted_files"])
            self.assertIn("content", plan_response["result"])
            json.loads(plan_response["result"]["content"][0]["text"])


if __name__ == "__main__":
    unittest.main()
