from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import get_close_matches
from pathlib import Path

from codemem.models import Edge, Entity, FocusFile, QueryPacket, RepositoryMemory, SearchHit

STOPWORDS = {
    "a",
    "an",
    "and",
    "be",
    "code",
    "for",
    "from",
    "how",
    "in",
    "is",
    "it",
    "me",
    "need",
    "of",
    "on",
    "part",
    "please",
    "show",
    "the",
    "this",
    "to",
    "where",
    "with",
}

INTENT_PATTERNS = {
    "flow_migration": {"migrate", "replace", "switch", "convert", "move"},
    "feature": {"add", "create", "implement", "support", "introduce"},
    "cleanup": {"remove", "delete", "cleanup", "clean", "unused", "dead"},
    "bugfix": {"fix", "broken", "error", "crash", "bug"},
    "refactor": {"refactor", "simplify", "restructure", "rename"},
}

MODE_PATTERNS = {
    "dead_code": {"dead", "unused", "orphan"},
    "impact": {"impact", "affect", "blast", "radius"},
    "architecture": {"architecture", "flow", "map", "system"},
    "explain": {"how", "why", "explain"},
    "locate": {"where", "find", "locate"},
    "modify": {"change", "replace", "update", "modify", "refactor", "fix", "implement", "add"},
}

SEMANTIC_GROUPS = {
    "dimension": {
        "dimension",
        "dimensions",
        "width",
        "height",
        "size",
        "sizes",
        "resize",
        "resizing",
        "scale",
        "aspect",
        "ratio",
        "canvas",
        "crop",
    },
    "billing": {
        "billing",
        "subscription",
        "subscriptions",
        "checkout",
        "payment",
        "payments",
        "plan",
        "plans",
        "pricing",
        "purchase",
        "purchases",
    },
    "auth": {
        "auth",
        "authentication",
        "authorize",
        "login",
        "logout",
        "signup",
        "session",
        "token",
        "user",
        "users",
    },
    "upload": {
        "upload",
        "uploads",
        "file",
        "files",
        "image",
        "images",
        "asset",
        "assets",
    },
}

TERM_TO_CANONICAL = {
    term: canonical
    for canonical, terms in SEMANTIC_GROUPS.items()
    for term in terms
}

LOW_SIGNAL_TERMS = {"change", "changes", "handle", "handler", "part", "save", "section", "set", "update", "updates"}

MODE_CONFIG = {
    "locate": {
        "neighbors": 6,
        "file_budget": 2,
        "symbols_per_file": 2,
        "spill_limit": 1,
        "spill_threshold": 0.78,
        "edge_weight": {"CONTAINS": 2.0, "EXPORTS": 1.5, "CALLS": 1.0, "IMPORTS": 0.8},
    },
    "explain": {
        "neighbors": 10,
        "file_budget": 3,
        "symbols_per_file": 2,
        "spill_limit": 2,
        "spill_threshold": 0.72,
        "edge_weight": {"CONTAINS": 1.5, "EXPORTS": 1.2, "CALLS": 1.6, "IMPORTS": 1.2},
    },
    "impact": {
        "neighbors": 14,
        "file_budget": 4,
        "symbols_per_file": 3,
        "spill_limit": 3,
        "spill_threshold": 0.55,
        "edge_weight": {"CONTAINS": 1.2, "EXPORTS": 1.2, "CALLS": 1.7, "IMPORTS": 1.7},
    },
    "modify": {
        "neighbors": 14,
        "file_budget": 4,
        "symbols_per_file": 3,
        "spill_limit": 3,
        "spill_threshold": 0.55,
        "edge_weight": {"CONTAINS": 1.3, "EXPORTS": 1.3, "CALLS": 1.8, "IMPORTS": 1.6},
    },
    "dead_code": {
        "neighbors": 8,
        "file_budget": 3,
        "symbols_per_file": 3,
        "spill_limit": 2,
        "spill_threshold": 0.65,
        "edge_weight": {"CONTAINS": 1.0, "EXPORTS": 1.5, "CALLS": 2.0, "IMPORTS": 0.5},
    },
    "architecture": {
        "neighbors": 18,
        "file_budget": 4,
        "symbols_per_file": 2,
        "spill_limit": 3,
        "spill_threshold": 0.68,
        "edge_weight": {"CONTAINS": 1.3, "EXPORTS": 1.1, "CALLS": 1.3, "IMPORTS": 1.8},
    },
}


@dataclass(slots=True)
class QueryUnderstanding:
    intent_category: str
    retrieval_mode: str
    raw_keywords: list[str]
    normalized_keywords: list[str]
    corrections: dict[str, str]
    expanded_terms: list[str]


@dataclass(slots=True)
class TokenFeatures:
    raw_name: set[str]
    canonical_name: set[str]
    raw_path: set[str]
    canonical_path: set[str]
    raw_meta: set[str]
    canonical_meta: set[str]


def classify_intent(prompt: str, vocabulary: set[str] | None = None) -> tuple[str, list[str]]:
    understanding = understand_query(prompt, vocabulary=vocabulary)
    return understanding.intent_category, understanding.normalized_keywords


def understand_query(prompt: str, vocabulary: set[str] | None = None, forced_mode: str | None = None) -> QueryUnderstanding:
    raw_keywords = _extract_keywords(prompt)
    normalized_keywords, corrections = _normalize_keywords(raw_keywords, vocabulary or set())
    expanded_terms = _expand_terms(normalized_keywords)
    intent_category = _classify_intent(normalized_keywords)
    retrieval_mode = forced_mode or _classify_mode(prompt, normalized_keywords)
    return QueryUnderstanding(
        intent_category=intent_category,
        retrieval_mode=retrieval_mode,
        raw_keywords=raw_keywords,
        normalized_keywords=normalized_keywords,
        corrections=corrections,
        expanded_terms=expanded_terms,
    )


def build_query_packet(
    memory: RepositoryMemory,
    prompt: str,
    limit: int = 12,
    forced_mode: str | None = None,
) -> QueryPacket:
    vocabulary = _build_vocabulary(memory.entities)
    understanding = understand_query(prompt, vocabulary=vocabulary, forced_mode=forced_mode)
    entities_by_id = {entity.id: entity for entity in memory.entities}
    files_by_path = {entity.path: entity for entity in memory.entities if entity.kind == "File"}
    reverse_contains = {edge.target: edge.source for edge in memory.edges if edge.kind == "CONTAINS"}
    features_by_id = {entity.id: _token_features(entity) for entity in memory.entities}

    raw_hits: list[SearchHit] = []
    for entity in memory.entities:
        hit = _score_entity(entity, features_by_id[entity.id], understanding, memory.root_path)
        if hit.score > 0:
            raw_hits.append(hit)
    raw_hits.sort(key=lambda hit: (-hit.score, hit.entity.kind, hit.entity.path, hit.entity.name))

    hits, focus_files, omitted_hits = _focus_hits(
        raw_hits=raw_hits,
        limit=limit,
        files_by_path=files_by_path,
        retrieval_mode=understanding.retrieval_mode,
    )

    neighbors, selected_ids = _expand_neighbors(
        hits=hits,
        entities_by_id=entities_by_id,
        edges=memory.edges,
        reverse_contains=reverse_contains,
        retrieval_mode=understanding.retrieval_mode,
    )
    included_edges = [edge for edge in memory.edges if edge.source in selected_ids and edge.target in selected_ids]
    coverage = _coverage(hits, focus_files, neighbors, included_edges, omitted_hits)
    confidence, confidence_reasons = _confidence(hits, coverage, understanding.retrieval_mode)
    relationship_summary = _relationship_summary(included_edges, entities_by_id, hits)
    unresolved_questions = _unresolved_questions(coverage, understanding.retrieval_mode)
    context_summary = _context_summary(understanding, hits, focus_files, neighbors, coverage, confidence)

    reasoning = [
        f"Intent classified as `{understanding.intent_category}`.",
        f"Retrieval mode selected as `{understanding.retrieval_mode}`.",
        f"Normalized keywords: {', '.join(understanding.normalized_keywords) or 'none'}.",
        f"Expanded terms: {', '.join(understanding.expanded_terms[:12]) or 'none'}.",
        f"Focused the packet into {len(focus_files)} primary files, {len(hits)} direct hits, and {len(neighbors)} neighbors with coverage {coverage}.",
    ]
    if understanding.corrections:
        reasoning.append(
            "Applied corrections: "
            + ", ".join(f"`{raw}` -> `{corrected}`" for raw, corrected in understanding.corrections.items())
            + "."
        )

    return QueryPacket(
        prompt=prompt,
        intent_category=understanding.intent_category,
        retrieval_mode=understanding.retrieval_mode,
        raw_keywords=understanding.raw_keywords,
        keywords=understanding.normalized_keywords,
        expanded_terms=understanding.expanded_terms,
        hits=hits,
        focus_files=focus_files,
        omitted_hits=omitted_hits,
        neighbors=neighbors,
        edges=included_edges,
        coverage=coverage,
        confidence=confidence,
        confidence_reasons=confidence_reasons,
        context_summary=context_summary,
        relationship_summary=relationship_summary,
        unresolved_questions=unresolved_questions,
        reasoning=reasoning,
    )


def _focus_hits(
    raw_hits: list[SearchHit],
    limit: int,
    files_by_path: dict[str, Entity],
    retrieval_mode: str,
) -> tuple[list[SearchHit], list[FocusFile], int]:
    if not raw_hits or limit <= 0:
        return [], [], 0

    config = MODE_CONFIG[retrieval_mode]
    symbols_per_file = config["symbols_per_file"]
    file_budget = min(config["file_budget"], max(1, limit))
    file_hits: dict[str, SearchHit] = {}
    symbol_hits_by_path: dict[str, list[SearchHit]] = {}
    file_scores: dict[str, float] = {}

    for hit in raw_hits:
        path = hit.entity.path
        file_scores[path] = max(file_scores.get(path, 0.0), hit.score)
        if hit.entity.kind == "File":
            existing = file_hits.get(path)
            if existing is None or hit.score > existing.score:
                file_hits[path] = hit
        else:
            symbol_hits_by_path.setdefault(path, []).append(hit)

    ordered_paths = sorted(
        file_scores,
        key=lambda path: (
            -file_scores[path],
            0 if any(hit.entity.exported for hit in symbol_hits_by_path.get(path, [])) else 1,
            path,
        ),
    )[:file_budget]

    selected: list[SearchHit] = []
    selected_ids: set[str] = set()
    focus_files: list[FocusFile] = []
    remaining = limit
    top_score = raw_hits[0].score

    for path in ordered_paths:
        if remaining <= 0:
            break
        anchor = _build_file_anchor(path, file_hits.get(path), symbol_hits_by_path.get(path, []), files_by_path)
        primary_symbols = _select_primary_symbols(symbol_hits_by_path.get(path, []), retrieval_mode)[:symbols_per_file]

        primary_names = [hit.entity.name for hit in primary_symbols]
        supporting_names = [hit.entity.name for hit in symbol_hits_by_path.get(path, []) if hit.entity.name not in primary_names]
        focus_files.append(
            FocusFile(
                path=path,
                language=files_by_path[path].language if path in files_by_path else (primary_symbols[0].entity.language if primary_symbols else "unknown"),
                score=round(file_scores[path], 2),
                primary_symbols=primary_names,
                supporting_symbols=supporting_names[:3],
                reasons=_focus_file_reasons(path, file_scores[path], primary_names, len(supporting_names)),
            )
        )

        if anchor and anchor.entity.id not in selected_ids and remaining > 0:
            selected.append(anchor)
            selected_ids.add(anchor.entity.id)
            remaining -= 1

        for index, hit in enumerate(primary_symbols):
            if remaining <= 0 or hit.entity.id in selected_ids:
                continue
            role = "primary" if index == 0 else "supporting"
            selected.append(_clone_hit(hit, selection_role=role))
            selected_ids.add(hit.entity.id)
            remaining -= 1

    if remaining > 0:
        non_focus_paths = set(file_scores) - set(ordered_paths)
        spill_limit = config["spill_limit"]
        spill_threshold = top_score * config["spill_threshold"]
        spill_count = 0
        for hit in raw_hits:
            if remaining <= 0:
                break
            if hit.entity.id in selected_ids or hit.entity.path not in non_focus_paths:
                continue
            if spill_count >= spill_limit or hit.score < spill_threshold:
                continue
            selected.append(_clone_hit(hit, selection_role="supporting"))
            selected_ids.add(hit.entity.id)
            remaining -= 1
            spill_count += 1

    omitted_hits = max(len(raw_hits) - len(selected), 0)
    selected.sort(key=lambda hit: (-hit.score, _role_rank(hit.selection_role), hit.entity.kind, hit.entity.path, hit.entity.name))
    return selected, focus_files, omitted_hits


def _select_primary_symbols(hits: list[SearchHit], retrieval_mode: str) -> list[SearchHit]:
    return sorted(
        hits,
        key=lambda hit: (
            -_symbol_priority(hit, retrieval_mode),
            -hit.score,
            hit.entity.path,
            hit.entity.name,
        ),
    )


def _symbol_priority(hit: SearchHit, retrieval_mode: str) -> float:
    entity = hit.entity
    priority = 0.0
    if entity.kind == "Component":
        priority += 1.1
    if entity.kind in {"Function", "Class"}:
        priority += 0.7
    if entity.exported:
        priority += 0.8
    if entity.visibility == "public":
        priority += 0.4
    if retrieval_mode in {"locate", "explain"} and entity.name.lower().startswith(("handle", "on")):
        priority -= 0.35
    if retrieval_mode in {"locate", "explain"} and entity.name.lower().startswith("update"):
        priority += 0.35
    return round(priority, 2)


def _build_file_anchor(
    path: str,
    file_hit: SearchHit | None,
    symbol_hits: list[SearchHit],
    files_by_path: dict[str, Entity],
) -> SearchHit | None:
    file_entity = files_by_path.get(path)
    if file_entity is None:
        return None
    top_symbol = symbol_hits[0] if symbol_hits else None
    if file_hit is not None:
        snippet = file_hit.snippet or (top_symbol.snippet if top_symbol else "")
        reasons = list(file_hit.reasons)
        reasons.append("selected as the primary file anchor for the focused packet")
        return _clone_hit(file_hit, snippet=snippet, reasons=list(dict.fromkeys(reasons)), selection_role="file_anchor")

    synthesized_score = round((top_symbol.score * 0.82) if top_symbol else 0.5, 2)
    return SearchHit(
        entity=file_entity,
        score=synthesized_score,
        reasons=["selected as the primary file anchor from matching symbols"],
        channels=["file_anchor"],
        signal_scores={"file_rollup": synthesized_score},
        snippet=top_symbol.snippet if top_symbol else "",
        selection_role="file_anchor",
    )


def _focus_file_reasons(path: str, score: float, primary_symbols: list[str], supporting_count: int) -> list[str]:
    reasons = [f"`{path}` had a top aggregated file score of {score:.2f}."]
    if primary_symbols:
        reasons.append(f"Primary symbols: {', '.join(primary_symbols[:3])}.")
    if supporting_count:
        reasons.append(f"{supporting_count} additional lower-priority sibling symbols were deferred.")
    return reasons


def _clone_hit(hit: SearchHit, **updates: object) -> SearchHit:
    payload = {
        "entity": hit.entity,
        "score": hit.score,
        "reasons": list(hit.reasons),
        "channels": list(hit.channels),
        "signal_scores": dict(hit.signal_scores),
        "snippet": hit.snippet,
        "selection_role": hit.selection_role,
    }
    payload.update(updates)
    return SearchHit(**payload)


def _role_rank(selection_role: str) -> int:
    order = {"primary": 0, "file_anchor": 1, "supporting": 2, "direct": 3}
    return order.get(selection_role, 4)


def _classify_intent(keywords: list[str]) -> str:
    lowered = set(keywords)
    for category, triggers in INTENT_PATTERNS.items():
        if lowered.intersection(triggers):
            return category
    return "change"


def _classify_mode(prompt: str, keywords: list[str]) -> str:
    prompt_text = prompt.lower()
    lowered = set(keywords) | set(re.findall(r"[a-z_]+", prompt_text))
    for mode in ("dead_code", "impact", "architecture", "explain", "locate", "modify"):
        if lowered.intersection(MODE_PATTERNS[mode]):
            return mode
    return "locate"


def _extract_keywords(prompt: str) -> list[str]:
    words = re.findall(r"[A-Za-z0-9_-]+", prompt.lower())
    keywords: list[str] = []
    for word in words:
        for part in word.replace("-", "_").split("_"):
            if len(part) <= 2 or part in STOPWORDS:
                continue
            keywords.append(part)
    return list(dict.fromkeys(keywords))


def _normalize_keywords(raw_keywords: list[str], vocabulary: set[str]) -> tuple[list[str], dict[str, str]]:
    corrections: dict[str, str] = {}
    normalized: list[str] = []
    lookup = vocabulary | set(TERM_TO_CANONICAL)

    for keyword in raw_keywords:
        corrected = keyword
        if keyword not in lookup:
            matches = get_close_matches(keyword, sorted(lookup), n=1, cutoff=0.82)
            if matches:
                corrected = matches[0]
        canonical = TERM_TO_CANONICAL.get(corrected, corrected)
        if canonical != keyword:
            corrections[keyword] = canonical
        normalized.append(canonical)
    return list(dict.fromkeys(normalized)), corrections


def _expand_terms(keywords: list[str]) -> list[str]:
    expanded: list[str] = []
    for keyword in keywords:
        canonical = TERM_TO_CANONICAL.get(keyword, keyword)
        expanded.append(canonical)
        if canonical in SEMANTIC_GROUPS:
            expanded.extend(sorted(SEMANTIC_GROUPS[canonical]))
        if canonical.endswith("s"):
            expanded.append(canonical[:-1])
        else:
            expanded.append(f"{canonical}s")
    return list(dict.fromkeys(expanded))


def _build_vocabulary(entities: list[Entity]) -> set[str]:
    vocabulary: set[str] = set(TERM_TO_CANONICAL)
    for entity in entities:
        features = _token_features(entity)
        vocabulary.update(features.raw_name)
        vocabulary.update(features.raw_path)
        vocabulary.update(features.raw_meta)
    return vocabulary


def _token_features(entity: Entity) -> TokenFeatures:
    raw_name = set(_tokenize(entity.name))
    raw_path = set(_tokenize(entity.path))
    raw_meta = set()
    for tag in entity.tags:
        raw_meta.update(_tokenize(tag))
    raw_meta.update(_tokenize(entity.summary))
    return TokenFeatures(
        raw_name=raw_name,
        canonical_name=_canonicalize(raw_name),
        raw_path=raw_path,
        canonical_path=_canonicalize(raw_path),
        raw_meta=raw_meta,
        canonical_meta=_canonicalize(raw_meta),
    )


def _score_entity(
    entity: Entity,
    features: TokenFeatures,
    understanding: QueryUnderstanding,
    repo_root: str,
) -> SearchHit:
    score = 0.0
    reasons: list[str] = []
    channels: list[str] = []
    signal_scores: dict[str, float] = {}
    semantic_matches = 0
    snippet = _extract_snippet(Path(repo_root), entity)

    for keyword in understanding.normalized_keywords:
        weight = 0.35 if keyword in LOW_SIGNAL_TERMS else 1.0
        if keyword in features.raw_name:
            score += 4.0 * weight
            signal_scores["exact_name"] = signal_scores.get("exact_name", 0.0) + 4.0 * weight
            reasons.append(f"exact name match on `{keyword}`")
            channels.append("exact_name")
        elif keyword in features.canonical_name:
            score += 3.0 * weight
            signal_scores["canonical_name"] = signal_scores.get("canonical_name", 0.0) + 3.0 * weight
            reasons.append(f"concept match in symbol name for `{keyword}`")
            channels.append("canonical_name")
        elif keyword in features.raw_path:
            score += 3.0 * weight
            signal_scores["exact_path"] = signal_scores.get("exact_path", 0.0) + 3.0 * weight
            reasons.append(f"exact path match on `{keyword}`")
            channels.append("exact_path")
        elif keyword in features.canonical_path:
            score += 2.0 * weight
            signal_scores["canonical_path"] = signal_scores.get("canonical_path", 0.0) + 2.0 * weight
            reasons.append(f"concept match in path for `{keyword}`")
            channels.append("canonical_path")
        elif keyword in features.raw_meta:
            score += 2.0 * weight
            signal_scores["exact_meta"] = signal_scores.get("exact_meta", 0.0) + 2.0 * weight
            reasons.append(f"exact summary/tag match on `{keyword}`")
            channels.append("exact_meta")
        elif keyword in features.canonical_meta:
            score += 1.5 * weight
            signal_scores["canonical_meta"] = signal_scores.get("canonical_meta", 0.0) + 1.5 * weight
            reasons.append(f"concept match in summary/tags for `{keyword}`")
            channels.append("canonical_meta")

    canonical_queries = {TERM_TO_CANONICAL.get(keyword, keyword) for keyword in understanding.normalized_keywords}
    combined_tokens = features.raw_name | features.raw_path | features.raw_meta | features.canonical_meta | features.canonical_name
    for term in understanding.expanded_terms:
        if term in understanding.normalized_keywords:
            continue
        if term in combined_tokens:
            semantic_weight = 1.25 if TERM_TO_CANONICAL.get(term, term) in canonical_queries else 0.9
            score += semantic_weight
            signal_scores["semantic"] = signal_scores.get("semantic", 0.0) + semantic_weight
            reasons.append(f"semantic alias `{term}` supported the match")
            channels.append("semantic")
            semantic_matches += 1

    if semantic_matches >= 2:
        reinforcement = min(1.25, semantic_matches * 0.35)
        score += reinforcement
        signal_scores["semantic_reinforcement"] = reinforcement
        reasons.append("multiple semantic aliases reinforced the match")

    task_bias = _task_bias(entity, understanding.retrieval_mode)
    score += task_bias
    if task_bias:
        signal_scores["task_bias"] = task_bias
        reasons.append(f"mode-specific bias applied for `{understanding.retrieval_mode}`")

    test_penalty = _test_penalty(entity.path, understanding.retrieval_mode, understanding.normalized_keywords)
    if test_penalty:
        score += test_penalty
        signal_scores["test_penalty"] = test_penalty
        reasons.append("test path penalty applied")

    if entity.kind == "File" and score > 0:
        score += 0.25
        signal_scores["file_context"] = 0.25
        channels.append("file_context")

    return SearchHit(
        entity=entity,
        score=max(round(score, 2), 0.0),
        reasons=list(dict.fromkeys(reasons)),
        channels=list(dict.fromkeys(channels)),
        signal_scores=signal_scores,
        snippet=snippet,
    )


def _task_bias(entity: Entity, retrieval_mode: str) -> float:
    path = entity.path.lower()
    if retrieval_mode in {"impact", "modify"}:
        if entity.kind in {"Function", "Class", "Component"}:
            return 0.5
        if not _is_test_path(path) and any(segment in path for segment in ("src/", "app/", "components/", "routes", "api/")):
            return 0.45
        if any(segment in path for segment in ("app/", "pages/", "components/", "routes", "api/")):
            return 0.3
    if retrieval_mode == "architecture" and entity.kind == "File":
        return 0.4
    if retrieval_mode == "dead_code" and entity.kind in {"Function", "Class"}:
        return 0.4
    return 0.0


def _test_penalty(path: str, retrieval_mode: str, keywords: list[str]) -> float:
    if not _is_test_path(path) or "test" in keywords or "tests" in keywords:
        return 0.0
    if retrieval_mode in {"impact", "modify", "architecture"}:
        return -4.0
    if retrieval_mode == "locate":
        return -2.0
    if retrieval_mode == "explain":
        return -1.5
    return -1.0


def _expand_neighbors(
    hits: list[SearchHit],
    entities_by_id: dict[str, Entity],
    edges: list[Edge],
    reverse_contains: dict[str, str],
    retrieval_mode: str,
) -> tuple[list[Entity], set[str]]:
    selected_ids = {hit.entity.id for hit in hits}
    role_by_id = {hit.entity.id: hit.selection_role for hit in hits}
    candidate_scores: dict[str, float] = {}
    edge_weights = MODE_CONFIG[retrieval_mode]["edge_weight"]

    for hit in hits:
        parent_file_id = reverse_contains.get(hit.entity.id)
        if parent_file_id and parent_file_id not in selected_ids:
            candidate_scores[parent_file_id] = candidate_scores.get(parent_file_id, 0.0) + 3.0

    for edge in edges:
        if edge.source not in selected_ids and edge.target not in selected_ids:
            continue
        source_hit = next((hit for hit in hits if hit.entity.id == edge.source), None)
        target_hit = next((hit for hit in hits if hit.entity.id == edge.target), None)
        if source_hit and edge.target not in selected_ids:
            if role_by_id.get(edge.source) == "file_anchor" and edge.kind == "CONTAINS":
                continue
            candidate_scores[edge.target] = candidate_scores.get(edge.target, 0.0) + max(
                source_hit.score * 0.3, edge_weights.get(edge.kind, 1.0)
            )
        if target_hit and edge.source not in selected_ids:
            if role_by_id.get(edge.target) == "file_anchor" and edge.kind == "CONTAINS":
                continue
            candidate_scores[edge.source] = candidate_scores.get(edge.source, 0.0) + max(
                target_hit.score * 0.3, edge_weights.get(edge.kind, 1.0)
            )

    ordered_neighbor_ids = sorted(
        candidate_scores,
        key=lambda entity_id: (-candidate_scores[entity_id], entities_by_id[entity_id].kind, entities_by_id[entity_id].path),
    )[: MODE_CONFIG[retrieval_mode]["neighbors"]]

    neighbors = [entities_by_id[entity_id] for entity_id in ordered_neighbor_ids if entity_id in entities_by_id]
    selected_ids.update(ordered_neighbor_ids)
    return neighbors, selected_ids


def _coverage(
    hits: list[SearchHit],
    focus_files: list[FocusFile],
    neighbors: list[Entity],
    edges: list[Edge],
    omitted_hits: int,
) -> dict[str, Any]:
    entities = [hit.entity for hit in hits] + neighbors
    files = sum(1 for entity in entities if entity.kind == "File")
    symbols = sum(1 for entity in entities if entity.kind != "File")
    tests = sum(1 for entity in entities if _is_test_path(entity.path))
    exported = sum(1 for entity in entities if entity.exported)
    return {
        "files": files,
        "focus_files": len(focus_files),
        "symbols": symbols,
        "tests": tests,
        "links": len(edges),
        "exported_symbols": exported,
        "omitted_hits": omitted_hits,
    }


def _confidence(hits: list[SearchHit], coverage: dict[str, Any], retrieval_mode: str) -> tuple[float, list[str]]:
    if not hits:
        return 0.0, ["No hits were retrieved."]
    reasons: list[str] = []
    top_score = hits[0].score
    confidence = min(top_score / 10.0, 0.65)
    reasons.append(f"Top hit score was {top_score:.2f}.")

    if coverage["files"]:
        confidence += 0.1
        reasons.append("At least one file entity was included.")
    if coverage["symbols"] >= 2:
        confidence += 0.1
        reasons.append("Multiple symbol-level entities were retrieved.")
    if coverage["links"]:
        confidence += 0.1
        reasons.append("The packet contains structural relationships.")
    if coverage["omitted_hits"]:
        confidence += 0.05
        reasons.append("Lower-priority matches were intentionally deferred to keep the packet focused.")
    if retrieval_mode in {"impact", "modify"} and coverage["tests"] == 0:
        confidence -= 0.05
        reasons.append("No tests were included for a change-oriented request.")

    return round(max(min(confidence, 1.0), 0.0), 2), reasons


def _relationship_summary(edges: list[Edge], entities_by_id: dict[str, Entity], hits: list[SearchHit]) -> list[str]:
    summaries: list[str] = []
    role_by_id = {hit.entity.id: hit.selection_role for hit in hits}
    prioritized_edges = sorted(
        edges,
        key=lambda edge: (
            -_edge_priority(edge, role_by_id),
            edge.source,
            edge.target,
        ),
    )
    for edge in prioritized_edges[:8]:
        source = entities_by_id.get(edge.source)
        target = entities_by_id.get(edge.target)
        if source and target:
            summaries.append(f"{source.name} {edge.kind.lower()} {target.name}")
    return summaries


def _edge_priority(edge: Edge, role_by_id: dict[str, str]) -> float:
    kind_weight = {"CALLS": 3.0, "EXPORTS": 2.0, "IMPORTS": 1.8, "CONTAINS": 1.0}
    role_weight = {
        "primary": 1.0,
        "file_anchor": 0.8,
        "supporting": 0.5,
        "direct": 0.2,
    }
    return (
        kind_weight.get(edge.kind, 0.5)
        + role_weight.get(role_by_id.get(edge.source, ""), 0.0)
        + role_weight.get(role_by_id.get(edge.target, ""), 0.0)
        + edge.confidence
    )


def _unresolved_questions(coverage: dict[str, Any], retrieval_mode: str) -> list[str]:
    questions: list[str] = []
    if coverage["files"] == 0:
        questions.append("No file-level anchor was retrieved.")
    if retrieval_mode in {"impact", "modify"} and coverage["tests"] == 0:
        questions.append("No tests were retrieved for validation of the change.")
    if coverage["links"] == 0:
        questions.append("No structural links were present in the selected packet.")
    return questions


def _context_summary(
    understanding: QueryUnderstanding,
    hits: list[SearchHit],
    focus_files: list[FocusFile],
    neighbors: list[Entity],
    coverage: dict[str, Any],
    confidence: float,
) -> str:
    targets = ", ".join(f"{hit.entity.kind}:{hit.entity.name}" for hit in hits[:4]) or "no direct targets"
    return (
        f"Mode `{understanding.retrieval_mode}` focused on {len(focus_files)} files, "
        f"{len(hits)} direct hits, and {len(neighbors)} neighbors. Top targets: {targets}. "
        f"Coverage files={coverage['files']}, symbols={coverage['symbols']}, links={coverage['links']}. "
        f"Deferred={coverage['omitted_hits']}. Confidence={confidence:.2f}."
    )


def _extract_snippet(repo_root: Path, entity: Entity, padding: int = 2) -> str:
    if entity.span is None:
        return ""
    path = repo_root / entity.path
    if not path.exists():
        return ""
    lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    start = max(entity.span.start_line - 1 - padding, 0)
    end = min(entity.span.end_line + padding, len(lines))
    snippet_lines = [f"{index + 1}: {lines[index]}" for index in range(start, end)]
    return "\n".join(snippet_lines)


def _tokenize(value: str) -> list[str]:
    normalized = value.replace("/", " ").replace("_", " ").replace("-", " ")
    pieces: list[str] = []
    for chunk in normalized.split():
        parts = re.findall(r"[A-Z]+(?=[A-Z][a-z]|\d|$)|[A-Z]?[a-z]+|\d+", chunk)
        pieces.extend(part.lower() for part in parts if part)
    return pieces


def _canonicalize(tokens: set[str]) -> set[str]:
    return {TERM_TO_CANONICAL.get(token, token) for token in tokens}


def _is_test_path(path: str) -> bool:
    normalized = f"/{path.lower()}"
    return "/tests/" in normalized or normalized.startswith("/tests/")
