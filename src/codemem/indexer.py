from __future__ import annotations

import hashlib
import re
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from codemem.analyzers import ANALYZERS, SUPPORTED_EXTENSIONS, discover_source_files
from codemem.analyzers.base import FileAnalysis
from codemem.models import Edge, Entity, RepositoryMemory

STOPWORDS = {
    "and",
    "app",
    "code",
    "component",
    "const",
    "data",
    "default",
    "export",
    "file",
    "function",
    "helper",
    "import",
    "index",
    "module",
    "return",
    "src",
    "test",
    "tmp",
    "type",
    "utils",
}

CALL_RE_TEMPLATE = r"""\b{symbol}\s*\("""


def index_repository(repo_root: str | Path) -> RepositoryMemory:
    root = Path(repo_root).resolve()
    file_paths = discover_source_files(root)
    analyses = [_analyze_file(root, file_path) for file_path in file_paths]

    entities: list[Entity] = []
    edges: list[Edge] = []
    file_entities_by_path: dict[str, Entity] = {}
    symbol_entities_by_file: dict[str, list[Entity]] = {}
    analysis_by_path = {analysis.relative_path: analysis for analysis in analyses}

    for analysis in analyses:
        file_entity = _build_file_entity(analysis)
        file_entities_by_path[analysis.relative_path] = file_entity
        entities.append(file_entity)

    for analysis in analyses:
        file_entity = file_entities_by_path[analysis.relative_path]
        for symbol in analysis.symbols:
            entity = _build_symbol_entity(file_entity, symbol)
            entities.append(entity)
            symbol_entities_by_file.setdefault(analysis.relative_path, []).append(entity)
            edges.append(
                Edge(
                    source=file_entity.id,
                    target=entity.id,
                    kind="CONTAINS",
                    provenance="analyzer.contains",
                )
            )
            if entity.exported:
                edges.append(
                    Edge(
                        source=file_entity.id,
                        target=entity.id,
                        kind="EXPORTS",
                        provenance="analyzer.exports",
                    )
                )

    symbol_names_by_file = {
        path: {entity.name: entity for entity in file_symbols}
        for path, file_symbols in symbol_entities_by_file.items()
    }

    for analysis in analyses:
        file_entity = file_entities_by_path[analysis.relative_path]
        for import_ref in analysis.imports:
            resolved_path = _resolve_import(analysis.relative_path, import_ref.specifier, root, analysis.language)
            import_ref.resolved_path = resolved_path
            if resolved_path and resolved_path in file_entities_by_path:
                edges.append(
                    Edge(
                        source=file_entity.id,
                        target=file_entities_by_path[resolved_path].id,
                        kind="IMPORTS",
                        provenance="analyzer.imports",
                        metadata={
                            "specifier": import_ref.specifier,
                            "names": import_ref.names,
                            "import_kind": import_ref.import_kind,
                        },
                    )
                )

        local_symbols = symbol_names_by_file.get(analysis.relative_path, {})
        related_symbols = dict(local_symbols)
        for import_ref in analysis.imports:
            if not import_ref.resolved_path:
                continue
            imported_symbols = symbol_names_by_file.get(import_ref.resolved_path, {})
            for name in import_ref.names:
                if name in imported_symbols:
                    related_symbols[name] = imported_symbols[name]

        for symbol in analysis.symbols:
            source_entity_id = _entity_id(symbol.kind, analysis.relative_path, symbol.name, symbol.span.start_line)
            for candidate_name, target_entity in related_symbols.items():
                if candidate_name == symbol.name:
                    continue
                if re.search(CALL_RE_TEMPLATE.format(symbol=re.escape(candidate_name)), symbol.body):
                    edges.append(
                        Edge(
                            source=source_entity_id,
                            target=target_entity.id,
                            kind="CALLS",
                            provenance="analyzer.calls",
                            confidence=0.7,
                            metadata={"via": candidate_name},
                        )
                    )

    deduped_edges = _dedupe_edges(edges)
    language_counts = Counter(analysis.language for analysis in analyses)
    diagnostics_count = sum(len(analysis.diagnostics) for analysis in analyses)
    analyzers = {
        analysis.language: f"{ANALYZERS[analysis.language].name}@{ANALYZERS[analysis.language].version}"
        for analysis in analyses
    }
    stats = {
        "files_indexed": len(analyses),
        "entities": len(entities),
        "edges": len(deduped_edges),
        "by_language": dict(language_counts),
        "diagnostics": diagnostics_count,
    }

    return RepositoryMemory(
        root_path=str(root),
        indexed_at=datetime.now(UTC).isoformat(),
        repository_fingerprint=_repository_fingerprint(analyses),
        analyzers=analyzers,
        entities=entities,
        edges=deduped_edges,
        stats=stats,
    )


def _analyze_file(root: Path, file_path: Path) -> FileAnalysis:
    relative_path = file_path.relative_to(root).as_posix()
    language = SUPPORTED_EXTENSIONS[file_path.suffix]
    analyzer = ANALYZERS[language]
    text = file_path.read_text(encoding="utf-8", errors="ignore")
    return analyzer.analyze(relative_path, text)


def _build_file_entity(analysis: FileAnalysis) -> Entity:
    return Entity(
        id=f"file:{analysis.relative_path}",
        kind="File",
        name=Path(analysis.relative_path).name,
        path=analysis.relative_path,
        language=analysis.language,
        summary=_summarize_file(analysis),
        tags=_derive_tags(analysis.relative_path, Path(analysis.relative_path).stem),
        hash=analysis.file_hash,
        qualified_name=analysis.relative_path,
        module_path=Path(analysis.relative_path).parent.as_posix(),
        visibility="public",
        exported=True,
        metadata={
            "line_count": analysis.line_count,
            "byte_size": analysis.byte_size,
            "diagnostics": analysis.diagnostics,
        },
    )


def _build_symbol_entity(file_entity: Entity, symbol) -> Entity:
    return Entity(
        id=_entity_id(symbol.kind, file_entity.path, symbol.name, symbol.span.start_line),
        kind=symbol.kind,
        name=symbol.name,
        path=file_entity.path,
        language=file_entity.language,
        span=symbol.span,
        signature=symbol.signature,
        summary=_summarize_symbol(symbol.kind, symbol.name, file_entity.path),
        tags=_derive_tags(file_entity.path, symbol.name),
        hash=hashlib.sha256(symbol.body.encode("utf-8")).hexdigest(),
        qualified_name=f"{file_entity.path}:{symbol.name}",
        module_path=file_entity.module_path,
        visibility=symbol.visibility,
        exported=symbol.exported,
        metadata={"parent_file": file_entity.id, **symbol.metadata},
    )


def _resolve_import(current_path: str, specifier: str, root: Path, language: str) -> str | None:
    if language == "python":
        return None
    if not specifier.startswith("."):
        return None

    base = Path(current_path).parent
    try:
        unresolved = (root / base / specifier).resolve().relative_to(root)
    except ValueError:
        return None
    candidates = [root / unresolved]
    for suffix in SUPPORTED_EXTENSIONS:
        candidates.append(root / f"{unresolved}{suffix}")
        candidates.append(root / unresolved / f"index{suffix}")
    for candidate in candidates:
        if candidate.exists() and candidate.is_file():
            return candidate.relative_to(root).as_posix()
    return None


def _repository_fingerprint(analyses: list[FileAnalysis]) -> str:
    digest = hashlib.sha256()
    for analysis in sorted(analyses, key=lambda item: item.relative_path):
        digest.update(f"{analysis.relative_path}:{analysis.file_hash}".encode("utf-8"))
    return digest.hexdigest()


def _summarize_file(analysis: FileAnalysis) -> str:
    area = Path(analysis.relative_path).parent.as_posix() or "repository root"
    return (
        f"{analysis.language.title()} source file in {area} with approximately "
        f"{analysis.line_count} lines and {len(analysis.symbols)} indexed symbols."
    )


def _summarize_symbol(kind: str, name: str, relative_path: str) -> str:
    readable_name = " ".join(_split_words(name))
    return f"{kind} `{name}` in {relative_path} related to {readable_name.lower()}."


def _derive_tags(relative_path: str, name: str) -> list[str]:
    tokens = {token for token in _split_words(relative_path) + _split_words(name) if token not in STOPWORDS}
    return sorted(tokens)[:10]


def _split_words(value: str) -> list[str]:
    normalized = value.replace("/", " ").replace("_", " ").replace("-", " ")
    pieces: list[str] = []
    for chunk in normalized.split():
        parts = re.findall(r"[A-Z]+(?=[A-Z][a-z]|\d|$)|[A-Z]?[a-z]+|\d+", chunk)
        pieces.extend(part.lower() for part in parts if part)
    return pieces


def _entity_id(kind: str, path: str, name: str, start_line: int) -> str:
    return f"{kind.lower()}:{path}:{name}:{start_line}"


def _dedupe_edges(edges: list[Edge]) -> list[Edge]:
    unique: dict[tuple[str, str, str], Edge] = {}
    for edge in edges:
        key = (edge.source, edge.target, edge.kind)
        unique.setdefault(key, edge)
    return list(unique.values())
