from __future__ import annotations

from codemem.models import Entity, RepositoryMemory


def analyze_dead_code(memory: RepositoryMemory) -> dict[str, object]:
    incoming_calls = {edge.target for edge in memory.edges if edge.kind == "CALLS"}
    export_targets = {edge.target for edge in memory.edges if edge.kind == "EXPORTS"}
    candidates = []

    for entity in memory.entities:
        if entity.kind not in {"Function", "Class", "Component"}:
            continue
        if entity.name in {"main"}:
            continue

        evidence: list[str] = []
        warnings: list[str] = []
        confidence = "medium"

        if entity.id not in incoming_calls:
            evidence.append("No incoming CALLS edges were found.")
        else:
            continue

        if entity.id not in export_targets and not entity.exported:
            evidence.append("The symbol is not marked as exported.")
        else:
            warnings.append("The symbol appears exported and may be used indirectly.")
            confidence = "low"

        if entity.kind == "Component":
            warnings.append("Component usage can be hidden by framework wiring or JSX composition.")
            confidence = "low"

        if any(segment in entity.path.lower() for segment in ("app/", "pages/", "routes/", "api/")):
            warnings.append("Entry-point or framework directories may contain implicit references.")
            confidence = "low"

        if entity.path.lower().startswith("tests/"):
            warnings.append("Test code is often invoked indirectly by the test runner.")
            confidence = "low"

        if confidence == "medium" and entity.kind == "Function" and not warnings:
            confidence = "high"

        candidates.append(
            {
                "entity": entity.to_dict(),
                "confidence": confidence,
                "evidence": evidence,
                "warnings": warnings,
            }
        )

    counts = {"high": 0, "medium": 0, "low": 0}
    for candidate in candidates:
        counts[candidate["confidence"]] += 1
    candidates.sort(
        key=lambda item: (
            {"high": 0, "medium": 1, "low": 2}[item["confidence"]],
            item["entity"]["path"],
            item["entity"]["start_line"] or 0,
        )
    )
    return {
        "schema_version": memory.schema_version,
        "candidate_count": len(candidates),
        "by_confidence": counts,
        "candidates": candidates[:50],
        "warning": "Dead-code analysis is structural and should be confirmed with tests or runtime evidence.",
    }
