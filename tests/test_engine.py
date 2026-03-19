from __future__ import annotations

import sys
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests"))

from codemem.engine import CodeMemEngine
from codemem.models import SCHEMA_VERSION
from support import write_repo


class CodeMemEngineTests(unittest.TestCase):
    def test_index_repo_builds_schema_versioned_memory_with_language_stats(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            write_repo(
                root,
                {
                    "src/billing.ts": """
                    export function createSubscriptionCheckout(planId: string) {
                      return normalizePlan(planId);
                    }

                    function normalizePlan(planId: string) {
                      return planId.trim();
                    }
                    """,
                    "app/worker.py": """
                    def run_job(task_name: str) -> str:
                        return task_name.upper()
                    """,
                },
            )

            engine = CodeMemEngine(root)
            memory = engine.index_repo()

            self.assertEqual(memory.schema_version, SCHEMA_VERSION)
            self.assertIn("typescript", memory.stats["by_language"])
            self.assertIn("python", memory.stats["by_language"])
            self.assertTrue(memory.repository_fingerprint)
            self.assertTrue(memory.analyzers["typescript"].startswith("javascript_regex"))
            self.assertTrue(any(edge.provenance == "analyzer.calls" for edge in memory.edges if edge.kind == "CALLS"))

    def test_query_memory_returns_locate_mode_snippets_and_confidence_reasons(self) -> None:
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

            engine = CodeMemEngine(root)
            engine.index_repo()
            packet = engine.query_memory("where is the change dimention part?", limit=5)

            self.assertEqual(packet.retrieval_mode, "locate")
            self.assertIn("dimension", packet.keywords)
            self.assertIn("width", packet.expanded_terms)
            self.assertEqual(packet.hits[0].entity.name, "handleDimensionsChange")
            self.assertIn("handleDimensionsChange", packet.hits[0].snippet)
            self.assertEqual(packet.focus_files[0].path, "src/customize.tsx")
            self.assertIn("handleDimensionsChange", packet.focus_files[0].primary_symbols)
            self.assertTrue(packet.confidence_reasons)
            self.assertFalse(packet.unresolved_questions)
            self.assertEqual(packet.omitted_hits, 0)

    def test_query_memory_focuses_packet_and_defers_low_value_siblings(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            write_repo(
                root,
                {
                    "src/components/crop/crop-canvas.tsx": """
                    export function updateCropBoxByAspectRatio() {
                      return drawCanvas();
                    }

                    function drawCanvas() {
                      return "canvas";
                    }

                    function handleResizeStart() {
                      return "start";
                    }

                    function handleResizeMove() {
                      return "move";
                    }

                    function handleResizeEnd() {
                      return "end";
                    }

                    function handlePointerDown() {
                      return "down";
                    }

                    function handlePointerMove() {
                      return handleResizeMove();
                    }
                    """,
                    "src/components/crop/aspect-ratio-selector.tsx": """
                    export function AspectRatioSelector() {
                      return updateRatio("16:9");
                    }

                    function updateRatio(value: string) {
                      return value;
                    }
                    """,
                },
            )

            engine = CodeMemEngine(root)
            engine.index_repo()
            packet = engine.query_memory("where is the change dimention part?", limit=12)

            hit_names = [hit.entity.name for hit in packet.hits if hit.entity.kind != "File"]
            self.assertIn("updateCropBoxByAspectRatio", hit_names)
            self.assertIn("AspectRatioSelector", hit_names)
            self.assertNotIn("handlePointerDown", hit_names)
            self.assertGreater(packet.omitted_hits, 0)
            self.assertLessEqual(len(packet.focus_files), 2)
            self.assertIn("updateCropBoxByAspectRatio", packet.focus_files[0].primary_symbols)

    def test_plan_change_groups_files_and_surfaces_unknowns(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            write_repo(
                root,
                {
                    "src/billing.ts": """
                    export function createSubscriptionCheckout(planId: string) {
                      return planId.trim();
                    }
                    """,
                    "src/PricingCard.tsx": """
                    import { createSubscriptionCheckout } from "./billing";

                    export const PricingCard = () => {
                      return createSubscriptionCheckout("starter");
                    };
                    """,
                },
            )

            engine = CodeMemEngine(root)
            engine.index_repo()
            plan = engine.plan_change("replace one-time purchases with subscription billing")

            self.assertEqual(plan.retrieval_mode, "modify")
            self.assertIn("src/billing.ts", plan.likely_affected_files)
            self.assertIn("src/PricingCard.tsx", plan.likely_affected_files)
            self.assertTrue(plan.impact_groups)
            self.assertGreater(plan.confidence, 0.0)
            self.assertTrue(plan.unknowns)
            self.assertIn("Likely affected files", plan.blast_radius)
            self.assertIn("Start in `src/billing.ts`", plan.plan_steps[0])

    def test_plan_change_prefers_implementation_files_over_tests(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            write_repo(
                root,
                {
                    "src/mcp.py": """
                    class MCPServer:
                        def serve_query_mode(self):
                            return "ok"
                    """,
                    "tests/test_mcp.py": """
                    def test_query_mode_support():
                        return "ok"
                    """,
                },
            )

            engine = CodeMemEngine(root)
            engine.index_repo()
            plan = engine.plan_change("improve mcp server query mode support")

            self.assertEqual(plan.likely_affected_files[0], "src/mcp.py")
            self.assertTrue(all(not path.startswith("tests/") for path in plan.likely_affected_files[:1]))
            self.assertIn("Start in `src/mcp.py`", plan.plan_steps[0])

    def test_dead_code_analysis_reports_evidence_and_confidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            write_repo(
                root,
                {
                    "src/helpers.ts": """
                    export function liveEntry() {
                      return usedHelper();
                    }

                    function usedHelper() {
                      return "ok";
                    }

                    function unusedHelper() {
                      return "dead";
                    }
                    """,
                },
            )

            engine = CodeMemEngine(root)
            engine.index_repo()
            report = engine.find_dead_code()

            candidate_names = {candidate["entity"]["name"] for candidate in report["candidates"]}
            self.assertIn("unusedHelper", candidate_names)
            unused = next(candidate for candidate in report["candidates"] if candidate["entity"]["name"] == "unusedHelper")
            self.assertTrue(unused["evidence"])
            self.assertIn(unused["confidence"], {"high", "medium", "low"})

    def test_store_falls_back_to_temp_cache_when_repo_write_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            write_repo(
                root,
                {
                    "src/sample.ts": """
                    export function sample() {
                      return "ok";
                    }
                    """,
                },
            )

            engine = CodeMemEngine(root)
            original_write = engine.store._write_payload  # noqa: SLF001
            calls = {"count": 0}

            def flaky_write(directory, path, payload):
                calls["count"] += 1
                if calls["count"] == 1:
                    raise PermissionError("read-only repo cache")
                return original_write(directory, path, payload)

            with patch.object(engine.store, "_write_payload", side_effect=flaky_write):  # noqa: SLF001
                memory = engine.index_repo()

            self.assertTrue(memory.repository_fingerprint)
            self.assertTrue(engine.store.fallback_path.exists())


if __name__ == "__main__":
    unittest.main()
