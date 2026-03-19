from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from codemem.models import SourceSpan

SUPPORTED_EXTENSIONS = {
    ".ts": "typescript",
    ".tsx": "typescript",
    ".js": "javascript",
    ".jsx": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".py": "python",
}

IGNORED_DIRS = {
    ".codemem",
    ".git",
    ".next",
    ".nuxt",
    ".venv",
    ".yarn",
    ".turbo",
    "__pycache__",
    "build",
    "coverage",
    "dist",
    "node_modules",
    "out",
    "target",
}


@dataclass(slots=True)
class ImportReference:
    specifier: str
    names: list[str] = field(default_factory=list)
    import_kind: str = "module"
    resolved_path: str | None = None
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass(slots=True)
class SymbolRecord:
    kind: str
    name: str
    signature: str
    span: SourceSpan
    body: str
    exported: bool = False
    visibility: str = "local"
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass(slots=True)
class FileAnalysis:
    relative_path: str
    language: str
    file_hash: str
    line_count: int
    byte_size: int
    imports: list[ImportReference] = field(default_factory=list)
    symbols: list[SymbolRecord] = field(default_factory=list)
    diagnostics: list[str] = field(default_factory=list)


class LanguageAnalyzer:
    name = "base"
    version = "0.2.0"

    def analyze(self, relative_path: str, text: str) -> FileAnalysis:
        raise NotImplementedError


def discover_source_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for file_path in root.rglob("*"):
        if not file_path.is_file():
            continue
        if file_path.suffix not in SUPPORTED_EXTENSIONS:
            continue
        if any(part in IGNORED_DIRS for part in file_path.parts):
            continue
        files.append(file_path)
    return sorted(files)
