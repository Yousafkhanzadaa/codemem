from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

SCHEMA_VERSION = "2.0"
ENGINE_VERSION = "0.2.0"


@dataclass(slots=True)
class SourceSpan:
    start_line: int
    end_line: int
    start_column: int = 1
    end_column: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "start_line": self.start_line,
            "end_line": self.end_line,
            "start_column": self.start_column,
            "end_column": self.end_column,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "SourceSpan":
        return cls(
            start_line=payload["start_line"],
            end_line=payload["end_line"],
            start_column=payload.get("start_column", 1),
            end_column=payload.get("end_column"),
        )


@dataclass(slots=True)
class Entity:
    id: str
    kind: str
    name: str
    path: str
    language: str
    span: SourceSpan | None = None
    signature: str = ""
    summary: str = ""
    tags: list[str] = field(default_factory=list)
    hash: str = ""
    qualified_name: str = ""
    module_path: str = ""
    visibility: str = "unknown"
    exported: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def start_line(self) -> int | None:
        return self.span.start_line if self.span else None

    @property
    def end_line(self) -> int | None:
        return self.span.end_line if self.span else None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "name": self.name,
            "path": self.path,
            "language": self.language,
            "span": self.span.to_dict() if self.span else None,
            "start_line": self.start_line,
            "end_line": self.end_line,
            "signature": self.signature,
            "summary": self.summary,
            "tags": self.tags,
            "hash": self.hash,
            "qualified_name": self.qualified_name,
            "module_path": self.module_path,
            "visibility": self.visibility,
            "exported": self.exported,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "Entity":
        span = payload.get("span")
        if span is None and payload.get("start_line") is not None:
            span = {
                "start_line": payload["start_line"],
                "end_line": payload.get("end_line", payload["start_line"]),
                "start_column": 1,
                "end_column": None,
            }
        return cls(
            id=payload["id"],
            kind=payload["kind"],
            name=payload["name"],
            path=payload["path"],
            language=payload["language"],
            span=SourceSpan.from_dict(span) if span else None,
            signature=payload.get("signature", ""),
            summary=payload.get("summary", ""),
            tags=list(payload.get("tags", [])),
            hash=payload.get("hash", ""),
            qualified_name=payload.get("qualified_name", payload.get("name", "")),
            module_path=payload.get("module_path", payload.get("path", "")),
            visibility=payload.get("visibility", "unknown"),
            exported=payload.get("exported", False),
            metadata=dict(payload.get("metadata", {})),
        )


@dataclass(slots=True)
class Edge:
    source: str
    target: str
    kind: str
    confidence: float = 1.0
    provenance: str = "analyzer"
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "target": self.target,
            "kind": self.kind,
            "confidence": self.confidence,
            "provenance": self.provenance,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "Edge":
        return cls(
            source=payload["source"],
            target=payload["target"],
            kind=payload["kind"],
            confidence=payload.get("confidence", 1.0),
            provenance=payload.get("provenance", "analyzer"),
            metadata=dict(payload.get("metadata", {})),
        )


@dataclass(slots=True)
class RepositoryMemory:
    root_path: str
    indexed_at: str
    entities: list[Entity]
    edges: list[Edge]
    stats: dict[str, Any] = field(default_factory=dict)
    schema_version: str = SCHEMA_VERSION
    engine_version: str = ENGINE_VERSION
    repository_fingerprint: str = ""
    analyzers: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "engine_version": self.engine_version,
            "root_path": self.root_path,
            "indexed_at": self.indexed_at,
            "repository_fingerprint": self.repository_fingerprint,
            "analyzers": self.analyzers,
            "entities": [entity.to_dict() for entity in self.entities],
            "edges": [edge.to_dict() for edge in self.edges],
            "stats": self.stats,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "RepositoryMemory":
        return cls(
            root_path=payload["root_path"],
            indexed_at=payload["indexed_at"],
            entities=[Entity.from_dict(item) for item in payload.get("entities", [])],
            edges=[Edge.from_dict(item) for item in payload.get("edges", [])],
            stats=dict(payload.get("stats", {})),
            schema_version=payload.get("schema_version", "1.0"),
            engine_version=payload.get("engine_version", "0.1.0"),
            repository_fingerprint=payload.get("repository_fingerprint", ""),
            analyzers=dict(payload.get("analyzers", {})),
        )


@dataclass(slots=True)
class SearchHit:
    entity: Entity
    score: float
    reasons: list[str] = field(default_factory=list)
    channels: list[str] = field(default_factory=list)
    signal_scores: dict[str, float] = field(default_factory=dict)
    snippet: str = ""
    selection_role: str = "direct"

    def to_dict(self) -> dict[str, Any]:
        return {
            "entity": self.entity.to_dict(),
            "score": self.score,
            "reasons": self.reasons,
            "channels": self.channels,
            "signal_scores": self.signal_scores,
            "snippet": self.snippet,
            "selection_role": self.selection_role,
        }


@dataclass(slots=True)
class FocusFile:
    path: str
    language: str
    score: float
    primary_symbols: list[str] = field(default_factory=list)
    supporting_symbols: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "language": self.language,
            "score": self.score,
            "primary_symbols": self.primary_symbols,
            "supporting_symbols": self.supporting_symbols,
            "reasons": self.reasons,
        }


@dataclass(slots=True)
class QueryPacket:
    prompt: str
    intent_category: str
    retrieval_mode: str
    raw_keywords: list[str]
    keywords: list[str]
    expanded_terms: list[str]
    hits: list[SearchHit]
    focus_files: list[FocusFile]
    omitted_hits: int
    neighbors: list[Entity]
    edges: list[Edge]
    coverage: dict[str, Any]
    confidence: float
    confidence_reasons: list[str]
    context_summary: str
    relationship_summary: list[str]
    unresolved_questions: list[str]
    reasoning: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "prompt": self.prompt,
            "intent_category": self.intent_category,
            "retrieval_mode": self.retrieval_mode,
            "raw_keywords": self.raw_keywords,
            "keywords": self.keywords,
            "expanded_terms": self.expanded_terms,
            "hits": [hit.to_dict() for hit in self.hits],
            "focus_files": [file.to_dict() for file in self.focus_files],
            "omitted_hits": self.omitted_hits,
            "neighbors": [entity.to_dict() for entity in self.neighbors],
            "edges": [edge.to_dict() for edge in self.edges],
            "coverage": self.coverage,
            "confidence": self.confidence,
            "confidence_reasons": self.confidence_reasons,
            "context_summary": self.context_summary,
            "relationship_summary": self.relationship_summary,
            "unresolved_questions": self.unresolved_questions,
            "reasoning": self.reasoning,
        }


@dataclass(slots=True)
class ImpactGroup:
    label: str
    files: list[str]
    entities: list[str]
    rationale: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "files": self.files,
            "entities": self.entities,
            "rationale": self.rationale,
        }


@dataclass(slots=True)
class ChangePlan:
    request: str
    intent_category: str
    retrieval_mode: str
    keywords: list[str]
    targets: list[SearchHit]
    likely_affected_files: list[str]
    possibly_affected_files: list[str]
    unverified_files: list[str]
    impact_groups: list[ImpactGroup]
    plan_steps: list[str]
    validation_steps: list[str]
    risks: list[str]
    assumptions: list[str]
    unknowns: list[str]
    confidence: float
    blast_radius: str
    context_summary: str

    @property
    def impacted_files(self) -> list[str]:
        files = self.likely_affected_files + self.possibly_affected_files + self.unverified_files
        return list(dict.fromkeys(files))

    def to_dict(self) -> dict[str, Any]:
        return {
            "request": self.request,
            "intent_category": self.intent_category,
            "retrieval_mode": self.retrieval_mode,
            "keywords": self.keywords,
            "impacted_files": self.impacted_files,
            "likely_affected_files": self.likely_affected_files,
            "possibly_affected_files": self.possibly_affected_files,
            "unverified_files": self.unverified_files,
            "targets": [target.to_dict() for target in self.targets],
            "impact_groups": [group.to_dict() for group in self.impact_groups],
            "plan_steps": self.plan_steps,
            "validation_steps": self.validation_steps,
            "risks": self.risks,
            "assumptions": self.assumptions,
            "unknowns": self.unknowns,
            "confidence": self.confidence,
            "blast_radius": self.blast_radius,
            "context_summary": self.context_summary,
        }
