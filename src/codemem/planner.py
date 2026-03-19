from __future__ import annotations

from pathlib import Path

from codemem.models import ChangePlan, ImpactGroup, QueryPacket, RepositoryMemory
from codemem.retrieval import build_query_packet


def build_change_plan(memory: RepositoryMemory, request: str, limit: int = 10) -> ChangePlan:
    packet = build_query_packet(memory, request, limit=limit, forced_mode="modify")
    likely_files, possible_files, unverified_files = _partition_files(packet)
    impact_groups = _impact_groups(packet, likely_files, possible_files)
    plan_steps = _plan_steps(packet, impact_groups)
    validation_steps = _validation_steps(packet)
    risks = _risks(packet)
    assumptions = _assumptions(packet)
    unknowns = _unknowns(packet, unverified_files)
    blast_radius = _blast_radius(packet, likely_files, possible_files, unverified_files)

    return ChangePlan(
        request=request,
        intent_category=packet.intent_category,
        retrieval_mode=packet.retrieval_mode,
        keywords=packet.keywords,
        targets=packet.hits,
        likely_affected_files=likely_files,
        possibly_affected_files=possible_files,
        unverified_files=unverified_files,
        impact_groups=impact_groups,
        plan_steps=plan_steps,
        validation_steps=validation_steps,
        risks=risks,
        assumptions=assumptions,
        unknowns=unknowns,
        confidence=packet.confidence,
        blast_radius=blast_radius,
        context_summary=packet.context_summary,
    )


def _partition_files(packet: QueryPacket) -> tuple[list[str], list[str], list[str]]:
    focus_files = {focus.path for focus in packet.focus_files}
    hit_files = {hit.entity.path for hit in packet.hits}
    neighbor_files = {entity.path for entity in packet.neighbors}
    likely = sorted(focus_files or hit_files)
    possible = sorted((neighbor_files | hit_files) - set(likely))
    unverified: set[str] = set()
    if packet.coverage["tests"] == 0:
        unverified.update(path for path in likely if not path.startswith("tests/"))
    return likely, possible, sorted(unverified - set(likely))


def _impact_groups(packet: QueryPacket, likely_files: list[str], possible_files: list[str]) -> list[ImpactGroup]:
    grouped: dict[str, dict[str, list[str]]] = {}
    for hit in packet.hits:
        label = _group_label(hit.entity.path)
        grouped.setdefault(label, {"files": [], "entities": []})
        grouped[label]["files"].append(hit.entity.path)
        grouped[label]["entities"].append(hit.entity.name)
    for file_path in possible_files:
        label = _group_label(file_path)
        grouped.setdefault(label, {"files": [], "entities": []})
        grouped[label]["files"].append(file_path)

    focus_by_label = {_group_label(focus.path): focus for focus in packet.focus_files}
    impact_groups = []
    for label, data in sorted(grouped.items()):
        focus = focus_by_label.get(label)
        rationale = f"Retrieved entities and neighboring files concentrated in `{label}`."
        if focus:
            rationale = " ".join(focus.reasons)
        impact_groups.append(
            ImpactGroup(
                label=label,
                files=sorted(dict.fromkeys(data["files"])),
                entities=sorted(dict.fromkeys(data["entities"])),
                rationale=rationale,
            )
        )
    return impact_groups


def _group_label(path: str) -> str:
    parent = Path(path).parent.as_posix()
    if not parent or parent == ".":
        return "root"
    parts = parent.split("/")
    return "/".join(parts[: min(3, len(parts))])


def _plan_steps(packet: QueryPacket, impact_groups: list[ImpactGroup]) -> list[str]:
    steps = []
    if packet.focus_files:
        primary_focus = packet.focus_files[0]
        primary_symbols = ", ".join(primary_focus.primary_symbols[:2]) or "the primary exported symbols"
        steps.append(f"Start in `{primary_focus.path}` around {primary_symbols} before widening the edit.")
    elif impact_groups:
        steps.append(f"Confirm the primary change surface in `{impact_groups[0].label}` before editing.")
    if packet.intent_category == "flow_migration":
        steps.extend(
            [
                "Update core domain and state transitions before UI affordances so the new flow stays internally consistent.",
                "Propagate the change through dependent files in the retrieved impact groups.",
            ]
        )
    elif packet.intent_category == "bugfix":
        steps.extend(
            [
                "Reproduce the failing behavior inside the retrieved packet before editing.",
                "Patch the narrowest symbol or file that explains the failure, then re-run impacted callers.",
            ]
        )
    else:
        steps.extend(
            [
                "Edit the highest-confidence files first, then reconcile dependent symbols and imports.",
                "Use the neighboring entities as verification targets rather than editing them blindly.",
            ]
        )
    steps.append("Refresh repository memory after the change so the next task uses the updated graph.")
    return steps


def _validation_steps(packet: QueryPacket) -> list[str]:
    languages = {hit.entity.language for hit in packet.hits}
    languages.update(entity.language for entity in packet.neighbors)
    steps = []
    if "typescript" in languages:
        steps.append("Run the TypeScript typecheck for the affected workspace.")
    if "python" in languages:
        steps.append("Run the relevant Python test or lint command for the affected package.")
    steps.append("Run focused tests that cover the likely affected files.")
    steps.append("Refresh repository memory and inspect the updated packet for drift.")
    return steps


def _risks(packet: QueryPacket) -> list[str]:
    risks = [
        "Static retrieval cannot fully capture dynamic runtime wiring or framework conventions.",
    ]
    if packet.omitted_hits:
        risks.append("The packet intentionally deferred lower-priority sibling matches; re-query if the change expands beyond the focused files.")
    if packet.coverage["tests"] == 0:
        risks.append("No tests were retrieved, so behavioral validation is weaker than ideal.")
    if packet.coverage["links"] == 0:
        risks.append("The retrieved packet has no structural links, which lowers trust in impact analysis.")
    return risks


def _assumptions(packet: QueryPacket) -> list[str]:
    assumptions = [
        "The focused files and primary symbols represent the primary static surface for the requested change.",
        "The repository memory is up to date with the current checkout.",
    ]
    if packet.retrieval_mode == "modify":
        assumptions.append("The change can be planned from static structure before runtime validation.")
    return assumptions


def _unknowns(packet: QueryPacket, unverified_files: list[str]) -> list[str]:
    unknowns = list(packet.unresolved_questions)
    if unverified_files:
        unknowns.append("No tests were retrieved for some likely affected files.")
    return unknowns


def _blast_radius(packet: QueryPacket, likely_files: list[str], possible_files: list[str], unverified_files: list[str]) -> str:
    return (
        f"Likely affected files: {len(likely_files)}. "
        f"Possibly affected files: {len(possible_files)}. "
        f"Unverified files: {len(unverified_files)}. "
        f"Retrieved structural links: {packet.coverage['links']}. "
        f"Deferred lower-priority hits: {packet.omitted_hits}."
    )
