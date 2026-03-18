from __future__ import annotations

from codemem.intent import build_query_packet
from codemem.models import ChangePlan, QueryPacket, RepositoryMemory


def build_change_plan(memory: RepositoryMemory, request: str, limit: int = 10) -> ChangePlan:
    packet = build_query_packet(memory, request, limit=limit)
    impacted_files = _collect_impacted_files(packet)
    plan_steps = _plan_steps(packet)
    validation_steps = _validation_steps(packet)
    risks = _risks(packet)
    context_summary = _context_summary(packet, impacted_files)

    return ChangePlan(
        request=request,
        intent_category=packet.intent_category,
        keywords=packet.keywords,
        impacted_files=impacted_files,
        targets=packet.hits,
        plan_steps=plan_steps,
        validation_steps=validation_steps,
        risks=risks,
        context_summary=context_summary,
    )


def _collect_impacted_files(packet: QueryPacket) -> list[str]:
    files = {hit.entity.path for hit in packet.hits if hit.entity.kind == "File"}
    files.update(hit.entity.path for hit in packet.hits if hit.entity.kind != "File")
    files.update(entity.path for entity in packet.neighbors if entity.kind == "File")
    files.update(entity.path for entity in packet.neighbors if entity.kind != "File")
    return sorted(files)


def _plan_steps(packet: QueryPacket) -> list[str]:
    targets = ", ".join(hit.entity.name for hit in packet.hits[:5]) or "the selected memory slice"

    if packet.intent_category == "flow_migration":
        return [
            f"Confirm the current and target product flows around {targets}.",
            "Update domain logic before surface-level UI changes so behavior and state stay aligned.",
            "Adjust files that coordinate imports, routes, and shared helpers within the impacted slice.",
            "Refresh repository memory after the edit so downstream planning uses the new structure.",
        ]
    if packet.intent_category == "cleanup":
        return [
            f"Verify that {targets} are genuinely redundant before removal.",
            "Delete or consolidate low-usage symbols starting from leaf files and helpers.",
            "Re-check imports and call sites to avoid leaving orphaned references.",
            "Refresh repository memory so dead-code candidates are recalculated from the new graph.",
        ]
    if packet.intent_category == "bugfix":
        return [
            f"Reproduce the bug inside the slice anchored by {targets}.",
            "Patch the smallest behavior boundary that explains the failing flow.",
            "Inspect neighboring callers and containers for regression risk.",
            "Refresh repository memory after the fix so later plans see the corrected structure.",
        ]
    return [
        f"Review the selected entities around {targets}.",
        "Update the highest-leverage files first, then reconcile dependent files and imports.",
        "Re-run validation against the impacted area before widening the change.",
        "Refresh repository memory after the edit so the graph stays current.",
    ]


def _validation_steps(packet: QueryPacket) -> list[str]:
    languages = {hit.entity.language for hit in packet.hits}
    languages.update(entity.language for entity in packet.neighbors)
    has_typescript = "typescript" in languages
    steps = ["Re-index the repository memory after the code change."]
    if has_typescript:
        steps.insert(0, "Run the TypeScript typecheck for the impacted package or app.")
    steps.append("Run focused tests that cover the impacted files and their entry points.")
    return steps


def _risks(packet: QueryPacket) -> list[str]:
    risks = [
        "The current graph is structural and heuristic; dynamic runtime flows will need runtime or test feedback.",
        "Call edges are conservative and may miss indirection through framework wiring or generated code.",
    ]
    if packet.intent_category == "flow_migration":
        risks.append("Product-flow migrations often require coordinated changes across UI, server, and state boundaries.")
    if packet.intent_category == "cleanup":
        risks.append("Unused-code detection is low confidence until test and runtime usage confirm the candidate list.")
    return risks


def _context_summary(packet: QueryPacket, impacted_files: list[str]) -> str:
    direct_targets = ", ".join(f"{hit.entity.kind}:{hit.entity.name}" for hit in packet.hits[:5]) or "no direct targets"
    file_summary = ", ".join(impacted_files[:6]) or "no impacted files"
    return (
        f"Intent `{packet.intent_category}` selected {len(packet.hits)} direct targets "
        f"and {len(packet.neighbors)} neighboring entities. "
        f"Primary targets: {direct_targets}. Impacted files: {file_summary}."
    )
