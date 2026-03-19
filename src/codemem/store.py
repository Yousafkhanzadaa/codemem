from __future__ import annotations

import hashlib
import json
import tempfile
from pathlib import Path

from codemem.models import RepositoryMemory, SCHEMA_VERSION


class MemoryStore:
    def __init__(self, repo_root: str | Path) -> None:
        self.repo_root = Path(repo_root).resolve()
        self.memory_dir = self.repo_root / ".codemem"
        self.memory_path = self.memory_dir / "repository_memory.json"
        self.fallback_dir = Path(tempfile.gettempdir()) / "codemem-cache" / hashlib.sha1(
            str(self.repo_root).encode("utf-8")
        ).hexdigest()
        self.fallback_path = self.fallback_dir / "repository_memory.json"

    def exists(self) -> bool:
        return self.memory_path.exists() or self.fallback_path.exists()

    def load(self) -> RepositoryMemory | None:
        if not self.exists():
            return None
        source_path = self.memory_path if self.memory_path.exists() else self.fallback_path
        payload = json.loads(source_path.read_text(encoding="utf-8"))
        return RepositoryMemory.from_dict(payload)

    def save(self, memory: RepositoryMemory) -> Path:
        payload = json.dumps(memory.to_dict(), indent=2, sort_keys=True)
        try:
            self._write_payload(self.memory_dir, self.memory_path, payload)
            return self.memory_path
        except PermissionError:
            self._write_payload(self.fallback_dir, self.fallback_path, payload)
            return self.fallback_path

    def needs_refresh(self, memory: RepositoryMemory | None) -> bool:
        if memory is None:
            return True
        return memory.schema_version != SCHEMA_VERSION

    def _write_payload(self, directory: Path, path: Path, payload: str) -> None:
        directory.mkdir(parents=True, exist_ok=True)
        temp_path = path.with_suffix(".tmp")
        temp_path.write_text(payload, encoding="utf-8")
        temp_path.replace(path)
