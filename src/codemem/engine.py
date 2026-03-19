from __future__ import annotations

from pathlib import Path

from codemem.deadcode import analyze_dead_code
from codemem.indexer import index_repository
from codemem.models import ChangePlan, Entity, QueryPacket, RepositoryMemory
from codemem.planner import build_change_plan
from codemem.retrieval import build_query_packet
from codemem.store import MemoryStore


class CodeMemEngine:
    def __init__(self, repo_root: str | Path) -> None:
        self.repo_root = Path(repo_root).resolve()
        self.store = MemoryStore(self.repo_root)

    def load_memory(self) -> RepositoryMemory | None:
        return self.store.load()

    def ensure_memory(self) -> RepositoryMemory:
        memory = self.load_memory()
        if self.store.needs_refresh(memory):
            memory = self.index_repo()
        return memory

    def index_repo(self) -> RepositoryMemory:
        memory = index_repository(self.repo_root)
        self.store.save(memory)
        return memory

    def refresh_memory(self) -> RepositoryMemory:
        return self.index_repo()

    def query_memory(self, prompt: str, limit: int = 12, mode: str | None = None) -> QueryPacket:
        return build_query_packet(self.ensure_memory(), prompt, limit=limit, forced_mode=mode)

    def impact_analysis(self, request: str, limit: int = 12) -> QueryPacket:
        return self.query_memory(request, limit=limit, mode="impact")

    def plan_change(self, request: str, limit: int = 10) -> ChangePlan:
        return build_change_plan(self.ensure_memory(), request, limit=limit)

    def get_entity(self, entity_id: str) -> Entity | None:
        memory = self.ensure_memory()
        return next((entity for entity in memory.entities if entity.id == entity_id), None)

    def get_neighbors(self, entity_id: str) -> dict[str, object]:
        memory = self.ensure_memory()
        entity = self.get_entity(entity_id)
        if entity is None:
            return {"entity": None, "neighbors": [], "edges": []}

        neighbor_ids = {
            edge.target
            for edge in memory.edges
            if edge.source == entity_id
        } | {
            edge.source
            for edge in memory.edges
            if edge.target == entity_id
        }
        neighbors = [candidate for candidate in memory.entities if candidate.id in neighbor_ids]
        edges = [
            edge.to_dict()
            for edge in memory.edges
            if edge.source == entity_id or edge.target == entity_id
        ]
        return {
            "entity": entity.to_dict(),
            "neighbors": [neighbor.to_dict() for neighbor in sorted(neighbors, key=lambda item: (item.kind, item.path, item.name))],
            "edges": edges,
        }

    def find_dead_code(self) -> dict[str, object]:
        return analyze_dead_code(self.ensure_memory())
