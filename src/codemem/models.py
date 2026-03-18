from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class Entity:
    id: str
    kind: str
    name: str
    path: str
    language: str
    start_line: int | None = None
    end_line: int | None = None
    signature: str = ""
    summary: str = ""
    tags: list[str] = field(default_factory=list)
    hash: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "name": self.name,
            "path": self.path,
            "language": self.language,
            "start_line": self.start_line,
            "end_line": self.end_line,
            "signature": self.signature,
            "summary": self.summary,
            "tags": self.tags,
            "hash": self.hash,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "Entity":
        return cls(
            id=payload["id"],
            kind=payload["kind"],
            name=payload["name"],
            path=payload["path"],
            language=payload["language"],
            start_line=payload.get("start_line"),
            end_line=payload.get("end_line"),
            signature=payload.get("signature", ""),
            summary=payload.get("summary", ""),
            tags=list(payload.get("tags", [])),
            hash=payload.get("hash", ""),
            metadata=dict(payload.get("metadata", {})),
        )


@dataclass(slots=True)
class Edge:
    source: str
    target: str
    kind: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "target": self.target,
            "kind": self.kind,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "Edge":
        return cls(
            source=payload["source"],
            target=payload["target"],
            kind=payload["kind"],
            metadata=dict(payload.get("metadata", {})),
        )


@dataclass(slots=True)
class RepositoryMemory:
    root_path: str
    indexed_at: str
    entities: list[Entity]
    edges: list[Edge]
    stats: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "root_path": self.root_path,
            "indexed_at": self.indexed_at,
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
        )


@dataclass(slots=True)
class SearchHit:
    entity: Entity
    score: float
    reasons: list[str] = field(default_factory=list)
    channels: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "entity": self.entity.to_dict(),
            "score": self.score,
            "reasons": self.reasons,
            "channels": self.channels,
        }


@dataclass(slots=True)
class QueryPacket:
    prompt: str
    intent_category: str
    raw_keywords: list[str]
    keywords: list[str]
    expanded_terms: list[str]
    hits: list[SearchHit]
    neighbors: list[Entity]
    edges: list[Edge]
    coverage: dict[str, Any]
    confidence: float
    context_summary: str
    reasoning: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "prompt": self.prompt,
            "intent_category": self.intent_category,
            "raw_keywords": self.raw_keywords,
            "keywords": self.keywords,
            "expanded_terms": self.expanded_terms,
            "hits": [hit.to_dict() for hit in self.hits],
            "neighbors": [entity.to_dict() for entity in self.neighbors],
            "edges": [edge.to_dict() for edge in self.edges],
            "coverage": self.coverage,
            "confidence": self.confidence,
            "context_summary": self.context_summary,
            "reasoning": self.reasoning,
        }


@dataclass(slots=True)
class ChangePlan:
    request: str
    intent_category: str
    keywords: list[str]
    impacted_files: list[str]
    targets: list[SearchHit]
    plan_steps: list[str]
    validation_steps: list[str]
    risks: list[str]
    context_summary: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "request": self.request,
            "intent_category": self.intent_category,
            "keywords": self.keywords,
            "impacted_files": self.impacted_files,
            "targets": [target.to_dict() for target in self.targets],
            "plan_steps": self.plan_steps,
            "validation_steps": self.validation_steps,
            "risks": self.risks,
            "context_summary": self.context_summary,
        }
