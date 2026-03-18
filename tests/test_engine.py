from __future__ import annotations

import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from codemem.engine import CodeMemEngine


class CodeMemEngineTests(unittest.TestCase):
    def test_index_repo_extracts_entities_and_edges(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "src").mkdir()
            (root / "src" / "billing.ts").write_text(
                textwrap.dedent(
                    """
                    export function createSubscriptionCheckout(planId: string) {
                      return normalizePlan(planId);
                    }

                    function normalizePlan(planId: string) {
                      return planId.trim();
                    }
                    """
                ).strip()
                + "\n",
                encoding="utf-8",
            )
            engine = CodeMemEngine(root)
            memory = engine.index_repo()

            self.assertEqual(memory.stats["files_indexed"], 1)
            function_names = {entity.name for entity in memory.entities if entity.kind == "Function"}
            self.assertIn("createSubscriptionCheckout", function_names)
            self.assertIn("normalizePlan", function_names)
            call_edges = [edge for edge in memory.edges if edge.kind == "CALLS"]
            self.assertEqual(len(call_edges), 1)

    def test_plan_change_selects_billing_slice(self) -> None:
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
            (root / "src" / "PricingCard.tsx").write_text(
                textwrap.dedent(
                    """
                    import { createSubscriptionCheckout } from "./billing";

                    export const PricingCard = () => {
                      return createSubscriptionCheckout("starter");
                    };
                    """
                ).strip()
                + "\n",
                encoding="utf-8",
            )

            engine = CodeMemEngine(root)
            engine.index_repo()
            plan = engine.plan_change("replace one-time purchases with subscription billing")

            impacted = set(plan.impacted_files)
            self.assertIn("src/billing.ts", impacted)
            self.assertIn("src/PricingCard.tsx", impacted)
            self.assertTrue(any("flow" in step.lower() or "domain logic" in step.lower() for step in plan.plan_steps))

    def test_query_memory_corrects_typos_and_expands_dimension_terms(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "src").mkdir()
            (root / "src" / "customize.tsx").write_text(
                textwrap.dedent(
                    """
                    export function handleDimensionsChange(width: number, height: number) {
                      return { width, height };
                    }
                    """
                ).strip()
                + "\n",
                encoding="utf-8",
            )

            engine = CodeMemEngine(root)
            engine.index_repo()
            packet = engine.query_memory("where is the change dimention part?", limit=5)

            self.assertIn("dimension", packet.keywords)
            self.assertIn("width", packet.expanded_terms)
            self.assertEqual(packet.hits[0].entity.name, "handleDimensionsChange")
            self.assertGreater(packet.confidence, 0.0)


if __name__ == "__main__":
    unittest.main()
