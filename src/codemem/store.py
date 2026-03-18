from __future__ import annotations

import json
from pathlib import Path

from codemem.models import RepositoryMemory


class MemoryStore:
    def __init__(self, repo_root: str | Path) -> None:
        self.repo_root = Path(repo_root).resolve()
        self.memory_dir = self.repo_root / ".codemem"
        self.memory_path = self.memory_dir / "repository_memory.json"

    def exists(self) -> bool:
        return self.memory_path.exists()

    def load(self) -> RepositoryMemory | None:
        if not self.exists():
            return None
        payload = json.loads(self.memory_path.read_text(encoding="utf-8"))
        return RepositoryMemory.from_dict(payload)

    def save(self, memory: RepositoryMemory) -> Path:
        self.memory_dir.mkdir(parents=True, exist_ok=True)
        self.memory_path.write_text(
            json.dumps(memory.to_dict(), indent=2, sort_keys=True),
            encoding="utf-8",
        )
        return self.memory_path
