from __future__ import annotations

import re
from difflib import get_close_matches

from codemem.models import Edge, Entity, QueryPacket, RepositoryMemory, SearchHit

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

LOW_SIGNAL_TERMS = {
    "change",
    "changes",
    "handle",
    "handler",
    "part",
    "save",
    "section",
    "set",
    "update",
    "updates",
}

EDGE_WEIGHTS = {
    "CONTAINS": 2.0,
    "CALLS": 1.5,
    "IMPORTS": 1.25,
}


def classify_intent(prompt: str, vocabulary: set[str] | None = None) -> tuple[str, list[str], list[str], dict[str, str], list[str]]:
    raw_keywords = _extract_keywords(prompt)
    normalized_keywords, corrections = _normalize_keywords(raw_keywords, vocabulary or set())
    expanded_terms = _expand_terms(normalized_keywords)
    lowered = set(normalized_keywords)
    for category, triggers in INTENT_PATTERNS.items():
        if lowered.intersection(triggers):
            return category, raw_keywords, normalized_keywords, corrections, expanded_terms
    return "change", raw_keywords, normalized_keywords, corrections, expanded_terms


def build_query_packet(memory: RepositoryMemory, prompt: str, limit: int = 12) -> QueryPacket:
    vocabulary = _build_vocabulary(memory.entities)
    (
        intent_category,
        raw_keywords,
        normalized_keywords,
        corrections,
        expanded_terms,
    ) = classify_intent(prompt, vocabulary=vocabulary)

    entities_by_id = {entity.id: entity for entity in memory.entities}
    adjacency = _adjacency(memory.edges)
    reverse_contains = _reverse_contains(memory.edges)

    hits: list[SearchHit] = []
    for entity in memory.entities:
        score, reasons, channels = _score_entity(
            entity=entity,
            normalized_keywords=normalized_keywords,
            expanded_terms=expanded_terms,
            intent_category=intent_category,
        )
        if score > 0:
            hits.append(SearchHit(entity=entity, score=score, reasons=reasons, channels=channels))
    hits.sort(key=lambda hit: (-hit.score, hit.entity.kind, hit.entity.path, hit.entity.name))
    hits = hits[:limit]

    neighbors, selected_ids = _expand_neighbors(
        hits=hits,
        entities_by_id=entities_by_id,
        adjacency=adjacency,
        reverse_contains=reverse_contains,
        limit=max(limit * 2, 8),
    )
    included_edges = [
        edge
        for edge in memory.edges
        if edge.source in selected_ids and edge.target in selected_ids
    ]
    coverage = _coverage(hits, neighbors, included_edges)
    confidence = _confidence(hits, coverage)
    context_summary = _context_summary(intent_category, hits, neighbors, coverage, confidence)

    reasoning = [
        f"Intent classified as `{intent_category}` from normalized keywords: {', '.join(normalized_keywords) or 'none'}.",
        f"Expanded retrieval terms: {', '.join(expanded_terms[:12]) or 'none'}.",
        f"Selected {len(hits)} direct hits and {len(neighbors)} neighboring entities from repository memory.",
        f"Coverage: files={coverage['files']}, symbols={coverage['symbols']}, tests={coverage['tests']}, links={coverage['links']}.",
    ]
    if corrections:
        reasoning.append(
            "Applied keyword corrections: "
            + ", ".join(f"`{original}` -> `{corrected}`" for original, corrected in corrections.items())
            + "."
        )

    return QueryPacket(
        prompt=prompt,
        intent_category=intent_category,
        raw_keywords=raw_keywords,
        keywords=normalized_keywords,
        expanded_terms=expanded_terms,
        hits=hits,
        neighbors=neighbors,
        edges=included_edges,
        coverage=coverage,
        confidence=confidence,
        context_summary=context_summary,
        reasoning=reasoning,
    )


def _extract_keywords(prompt: str) -> list[str]:
    words = re.findall(r"[A-Za-z0-9_-]+", prompt.lower())
    keywords: list[str] = []
    for word in words:
        parts = word.replace("-", "_").split("_")
        for part in parts:
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
        corrections.setdefault(keyword, canonical) if canonical != keyword else None
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
        vocabulary.update(_entity_tokens(entity))
    return vocabulary


def _score_entity(
    entity: Entity,
    normalized_keywords: list[str],
    expanded_terms: list[str],
    intent_category: str,
) -> tuple[float, list[str], list[str]]:
    if not normalized_keywords:
        return 0.0, [], []

    tokens = _entity_tokens(entity)
    score = 0.0
    reasons: list[str] = []
    channels: list[str] = []
    matched = False
    canonical_queries = {TERM_TO_CANONICAL.get(keyword, keyword) for keyword in normalized_keywords}
    semantic_matches = 0

    for keyword in normalized_keywords:
        weight = _keyword_weight(keyword)
        if keyword in _entity_name_tokens(entity):
            score += 4.0 * weight
            reasons.append(f"name matched `{keyword}`")
            channels.append("symbol_name")
            matched = True
        elif keyword in _path_tokens(entity.path):
            score += 3.0 * weight
            reasons.append(f"path matched `{keyword}`")
            channels.append("path")
            matched = True
        elif keyword in tokens:
            score += 2.0 * weight
            reasons.append(f"tag or summary matched `{keyword}`")
            channels.append("lexical")
            matched = True

    for term in expanded_terms:
        if term in normalized_keywords:
            continue
        if term in tokens:
            semantic_weight = 1.25 if TERM_TO_CANONICAL.get(term, term) in canonical_queries else 0.9
            score += semantic_weight
            reasons.append(f"semantic expansion matched `{term}`")
            channels.append("semantic")
            matched = True
            semantic_matches += 1

    if semantic_matches >= 2:
        score += min(1.25, semantic_matches * 0.35)
        reasons.append("multiple semantic terms reinforced the match")

    score += _task_bias(entity, intent_category)

    is_test_path = _is_test_path(entity.path)
    if is_test_path and "test" not in normalized_keywords and "tests" not in normalized_keywords:
        score -= 2.0
        reasons.append("down-ranked test path")

    if entity.kind == "File" and matched:
        score += 0.25
        channels.append("file_context")

    return max(score, 0.0), reasons, list(dict.fromkeys(channels))


def _task_bias(entity: Entity, intent_category: str) -> float:
    path = entity.path.lower()
    if intent_category == "flow_migration":
        if any(segment in path for segment in ("app/", "pages/", "components/", "routes", "api/")):
            return 0.6
        return 0.0
    if intent_category == "bugfix":
        if _is_test_path(path):
            return 0.75
        if entity.kind in {"Function", "Class"}:
            return 0.35
        return 0.0
    if intent_category == "cleanup":
        if entity.kind in {"Function", "Class"}:
            return 0.5
        return -0.1
    return 0.0


def _expand_neighbors(
    hits: list[SearchHit],
    entities_by_id: dict[str, Entity],
    adjacency: dict[str, set[str]],
    reverse_contains: dict[str, str],
    limit: int,
) -> tuple[list[Entity], set[str]]:
    selected_ids = {hit.entity.id for hit in hits}
    candidate_scores: dict[str, float] = {}

    for hit in hits:
        parent_file_id = reverse_contains.get(hit.entity.id)
        if parent_file_id and parent_file_id not in selected_ids:
            candidate_scores[parent_file_id] = candidate_scores.get(parent_file_id, 0.0) + 3.0

        for neighbor_id in adjacency.get(hit.entity.id, set()):
            if neighbor_id in selected_ids:
                continue
            weight = 1.0
            for edge_kind, edge_weight in EDGE_WEIGHTS.items():
                if edge_kind in hit.channels:
                    weight += edge_weight * 0.1
            candidate_scores[neighbor_id] = candidate_scores.get(neighbor_id, 0.0) + max(hit.score * 0.35, weight)

    ordered_neighbor_ids = sorted(
        candidate_scores,
        key=lambda entity_id: (-candidate_scores[entity_id], entities_by_id[entity_id].kind, entities_by_id[entity_id].path),
    )[:limit]

    neighbors = [entities_by_id[entity_id] for entity_id in ordered_neighbor_ids]
    selected_ids.update(ordered_neighbor_ids)
    return neighbors, selected_ids


def _coverage(hits: list[SearchHit], neighbors: list[Entity], edges: list[Edge]) -> dict[str, int]:
    all_entities = [hit.entity for hit in hits] + neighbors
    file_count = sum(1 for entity in all_entities if entity.kind == "File")
    symbol_count = sum(1 for entity in all_entities if entity.kind != "File")
    test_count = sum(1 for entity in all_entities if _is_test_path(entity.path))
    link_count = len(edges)
    return {
        "files": file_count,
        "symbols": symbol_count,
        "tests": test_count,
        "links": link_count,
    }


def _confidence(hits: list[SearchHit], coverage: dict[str, int]) -> float:
    if not hits:
        return 0.0
    top_score = hits[0].score
    signal = min(top_score / 8.0, 1.0)
    coverage_bonus = 0.0
    if coverage["files"]:
        coverage_bonus += 0.1
    if coverage["symbols"]:
        coverage_bonus += 0.1
    if coverage["links"]:
        coverage_bonus += 0.1
    if len(hits) >= 3:
        coverage_bonus += 0.1
    return round(min(signal + coverage_bonus, 1.0), 2)


def _context_summary(
    intent_category: str,
    hits: list[SearchHit],
    neighbors: list[Entity],
    coverage: dict[str, int],
    confidence: float,
) -> str:
    top_targets = ", ".join(f"{hit.entity.kind}:{hit.entity.name}" for hit in hits[:4]) or "no direct targets"
    return (
        f"Intent `{intent_category}` selected {len(hits)} direct hits and {len(neighbors)} neighbors. "
        f"Top targets: {top_targets}. "
        f"Coverage files={coverage['files']}, symbols={coverage['symbols']}, links={coverage['links']}. "
        f"Confidence={confidence:.2f}."
    )


def _entity_tokens(entity: Entity) -> set[str]:
    tokens = set(_entity_name_tokens(entity))
    tokens.update(_path_tokens(entity.path))
    for tag in entity.tags:
        tokens.update(_expand_token_set(_tokenize(tag)))
    tokens.update(_expand_token_set(_tokenize(entity.summary)))
    return tokens


def _entity_name_tokens(entity: Entity) -> set[str]:
    return _expand_token_set(_tokenize(entity.name))


def _path_tokens(path: str) -> set[str]:
    return _expand_token_set(_tokenize(path))


def _tokenize(value: str) -> list[str]:
    normalized = value.replace("/", " ").replace("_", " ").replace("-", " ")
    pieces: list[str] = []
    for chunk in normalized.split():
        parts = re.findall(r"[A-Z]+(?=[A-Z][a-z]|\d|$)|[A-Z]?[a-z]+|\d+", chunk)
        pieces.extend(part.lower() for part in parts if part)
    return pieces


def _keyword_weight(keyword: str) -> float:
    if keyword in LOW_SIGNAL_TERMS:
        return 0.35
    return 1.0


def _expand_token_set(tokens: list[str]) -> set[str]:
    expanded = set(tokens)
    expanded.update(TERM_TO_CANONICAL.get(token, token) for token in tokens)
    return expanded


def _is_test_path(path: str) -> bool:
    normalized = f"/{path.lower()}"
    return "/tests/" in normalized or normalized.startswith("/tests/")


def _adjacency(edges: list[Edge]) -> dict[str, set[str]]:
    adjacency: dict[str, set[str]] = {}
    for edge in edges:
        adjacency.setdefault(edge.source, set()).add(edge.target)
        adjacency.setdefault(edge.target, set()).add(edge.source)
    return adjacency


def _reverse_contains(edges: list[Edge]) -> dict[str, str]:
    parents: dict[str, str] = {}
    for edge in edges:
        if edge.kind == "CONTAINS":
            parents[edge.target] = edge.source
    return parents
