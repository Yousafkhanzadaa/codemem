from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from codemem.models import Edge, Entity, RepositoryMemory

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

JS_IMPORT_RE = re.compile(
    r"""^\s*(?:import|export)\s+(?P<clause>.+?)\s+from\s+['"](?P<module>[^'"]+)['"]""",
    re.MULTILINE,
)
JS_REQUIRE_RE = re.compile(
    r"""^\s*(?:const|let|var)\s+(?P<name>[A-Za-z_$][\w$]*)\s*=\s*require\(['"](?P<module>[^'"]+)['"]\)""",
    re.MULTILINE,
)
PY_IMPORT_RE = re.compile(r"""^\s*import\s+(?P<module>[A-Za-z0-9_.,\s]+)""", re.MULTILINE)
PY_FROM_IMPORT_RE = re.compile(
    r"""^\s*from\s+(?P<module>[A-Za-z0-9_.]+)\s+import\s+(?P<names>[A-Za-z0-9_*,\s]+)""",
    re.MULTILINE,
)

JS_FUNCTION_RE = re.compile(
    r"""^\s*(?:export\s+)?(?:async\s+)?function\s+(?P<name>[A-Za-z_$][\w$]*)\s*\((?P<signature>[^)]*)\)""",
    re.MULTILINE,
)
JS_ARROW_RE = re.compile(
    r"""^\s*(?:export\s+)?(?:const|let|var)\s+(?P<name>[A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?(?P<signature>\([^)]*\)|[A-Za-z_$][\w$]*)\s*=>""",
    re.MULTILINE,
)
JS_FUNCTION_EXPR_RE = re.compile(
    r"""^\s*(?:export\s+)?(?:const|let|var)\s+(?P<name>[A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?function\s*\((?P<signature>[^)]*)\)""",
    re.MULTILINE,
)
JS_CLASS_RE = re.compile(
    r"""^\s*(?:export\s+)?class\s+(?P<name>[A-Za-z_$][\w$]*)""",
    re.MULTILINE,
)
PY_FUNCTION_RE = re.compile(
    r"""^\s*(?:async\s+)?def\s+(?P<name>[A-Za-z_]\w*)\s*\((?P<signature>[^)]*)\)""",
    re.MULTILINE,
)
PY_CLASS_RE = re.compile(r"""^\s*class\s+(?P<name>[A-Za-z_]\w*)""", re.MULTILINE)
CALL_RE_TEMPLATE = r"""\b{symbol}\s*\("""


@dataclass(slots=True)
class ImportReference:
    specifier: str
    names: list[str]
    resolved_path: str | None = None


@dataclass(slots=True)
class RawSymbol:
    kind: str
    name: str
    signature: str
    start_offset: int
    end_offset: int = 0
    start_line: int = 0
    end_line: int = 0
    body: str = ""


@dataclass(slots=True)
class IndexedFile:
    entity: Entity
    text: str
    imports: list[ImportReference] = field(default_factory=list)
    symbols: list[RawSymbol] = field(default_factory=list)


def index_repository(repo_root: str | Path) -> RepositoryMemory:
    root = Path(repo_root).resolve()
    indexed_files: list[IndexedFile] = []

    for file_path in _discover_files(root):
        relative_path = file_path.relative_to(root).as_posix()
        language = SUPPORTED_EXTENSIONS[file_path.suffix]
        text = file_path.read_text(encoding="utf-8", errors="ignore")
        file_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
        file_entity = Entity(
            id=f"file:{relative_path}",
            kind="File",
            name=file_path.name,
            path=relative_path,
            language=language,
            summary=_summarize_file(relative_path, language, text),
            tags=_derive_tags(relative_path, file_path.stem),
            hash=file_hash,
            metadata={"size": len(text), "suffix": file_path.suffix},
        )
        indexed_files.append(
            IndexedFile(
                entity=file_entity,
                text=text,
                imports=_extract_imports(text, language),
                symbols=_extract_symbols(text, language),
            )
        )

    entities: list[Entity] = []
    edges: list[Edge] = []
    entities_by_path: dict[str, Entity] = {}
    symbols_by_file: dict[str, list[Entity]] = {}

    for indexed_file in indexed_files:
        entities.append(indexed_file.entity)
        entities_by_path[indexed_file.entity.path] = indexed_file.entity

        raw_symbols = sorted(indexed_file.symbols, key=lambda symbol: symbol.start_offset)
        for position, symbol in enumerate(raw_symbols):
            next_offset = len(indexed_file.text)
            if position + 1 < len(raw_symbols):
                next_offset = raw_symbols[position + 1].start_offset
            end_offset = min(next_offset, len(indexed_file.text))
            if symbol.end_offset:
                end_offset = min(symbol.end_offset, end_offset)
            symbol.end_offset = max(end_offset, symbol.start_offset)
            symbol.body = indexed_file.text[symbol.start_offset : symbol.end_offset]
            symbol.start_line = _line_number(indexed_file.text, symbol.start_offset)
            symbol.end_line = _line_number(indexed_file.text, symbol.end_offset)

            entity = Entity(
                id=f"{symbol.kind.lower()}:{indexed_file.entity.path}:{symbol.name}:{symbol.start_line}",
                kind=symbol.kind,
                name=symbol.name,
                path=indexed_file.entity.path,
                language=indexed_file.entity.language,
                start_line=symbol.start_line,
                end_line=symbol.end_line,
                signature=symbol.signature,
                summary=_summarize_symbol(symbol, indexed_file.entity.path),
                tags=_derive_tags(indexed_file.entity.path, symbol.name),
                hash=hashlib.sha256(symbol.body.encode("utf-8")).hexdigest(),
                metadata={"parent_file": indexed_file.entity.id},
            )
            entities.append(entity)
            symbols_by_file.setdefault(indexed_file.entity.path, []).append(entity)
            edges.append(
                Edge(
                    source=indexed_file.entity.id,
                    target=entity.id,
                    kind="CONTAINS",
                )
            )

    symbol_names_by_file: dict[str, dict[str, Entity]] = {
        path: {entity.name: entity for entity in file_symbols}
        for path, file_symbols in symbols_by_file.items()
    }

    for indexed_file in indexed_files:
        for import_ref in indexed_file.imports:
            resolved_path = _resolve_import(indexed_file.entity.path, import_ref.specifier, root)
            import_ref.resolved_path = resolved_path
            if resolved_path and resolved_path in entities_by_path:
                edges.append(
                    Edge(
                        source=indexed_file.entity.id,
                        target=entities_by_path[resolved_path].id,
                        kind="IMPORTS",
                        metadata={"specifier": import_ref.specifier},
                    )
                )

        local_symbols = symbol_names_by_file.get(indexed_file.entity.path, {})
        related_symbols = dict(local_symbols)

        for import_ref in indexed_file.imports:
            if not import_ref.resolved_path:
                continue
            imported_entities = symbol_names_by_file.get(import_ref.resolved_path, {})
            for name in import_ref.names:
                if name in imported_entities:
                    related_symbols[name] = imported_entities[name]

        for raw_symbol in indexed_file.symbols:
            source_entity_id = f"{raw_symbol.kind.lower()}:{indexed_file.entity.path}:{raw_symbol.name}:{_line_number(indexed_file.text, raw_symbol.start_offset)}"
            for candidate_name, target_entity in related_symbols.items():
                if candidate_name == raw_symbol.name:
                    continue
                call_re = re.compile(CALL_RE_TEMPLATE.format(symbol=re.escape(candidate_name)))
                if call_re.search(raw_symbol.body):
                    edges.append(
                        Edge(
                            source=source_entity_id,
                            target=target_entity.id,
                            kind="CALLS",
                        )
                    )

    deduped_edges = _dedupe_edges(edges)
    stats = {
        "files_indexed": len(indexed_files),
        "entities": len(entities),
        "edges": len(deduped_edges),
    }
    return RepositoryMemory(
        root_path=str(root),
        indexed_at=datetime.now(UTC).isoformat(),
        entities=entities,
        edges=deduped_edges,
        stats=stats,
    )


def _discover_files(root: Path) -> list[Path]:
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


def _extract_imports(text: str, language: str) -> list[ImportReference]:
    imports: list[ImportReference] = []
    if language in {"typescript", "javascript"}:
        for match in JS_IMPORT_RE.finditer(text):
            clause = match.group("clause").strip()
            imports.append(
                ImportReference(
                    specifier=match.group("module"),
                    names=_extract_js_import_names(clause),
                )
            )
        for match in JS_REQUIRE_RE.finditer(text):
            imports.append(
                ImportReference(specifier=match.group("module"), names=[match.group("name")])
            )
        return imports

    for match in PY_IMPORT_RE.finditer(text):
        modules = [item.strip() for item in match.group("module").split(",")]
        for module_name in modules:
            if not module_name:
                continue
            imports.append(ImportReference(specifier=module_name, names=[module_name.split(".")[-1]]))
    for match in PY_FROM_IMPORT_RE.finditer(text):
        names = [item.strip().split(" as ")[-1] for item in match.group("names").split(",")]
        imports.append(ImportReference(specifier=match.group("module"), names=[name for name in names if name]))
    return imports


def _extract_js_import_names(clause: str) -> list[str]:
    clause = clause.strip()
    names: list[str] = []
    if clause.startswith("{") and clause.endswith("}"):
        items = clause[1:-1].split(",")
        for item in items:
            local = item.strip().split(" as ")[-1].strip()
            if local:
                names.append(local)
        return names

    if "," in clause:
        default_name, named = clause.split(",", 1)
        if default_name.strip():
            names.append(default_name.strip())
        names.extend(_extract_js_import_names(named.strip()))
        return names

    cleaned = clause.replace("* as ", "").strip()
    if cleaned:
        names.append(cleaned)
    return names


def _extract_symbols(text: str, language: str) -> list[RawSymbol]:
    patterns: list[tuple[re.Pattern[str], str]]
    if language in {"typescript", "javascript"}:
        patterns = [
            (JS_FUNCTION_RE, "Function"),
            (JS_ARROW_RE, "Function"),
            (JS_FUNCTION_EXPR_RE, "Function"),
            (JS_CLASS_RE, "Class"),
        ]
    else:
        patterns = [
            (PY_FUNCTION_RE, "Function"),
            (PY_CLASS_RE, "Class"),
        ]

    symbols: list[RawSymbol] = []
    seen: set[tuple[str, int]] = set()
    for pattern, kind in patterns:
        for match in pattern.finditer(text):
            name = match.group("name")
            start_offset = match.start()
            key = (name, start_offset)
            if key in seen:
                continue
            seen.add(key)
            signature = match.groupdict().get("signature", "").strip()
            symbols.append(
                RawSymbol(
                    kind=kind,
                    name=name,
                    signature=signature,
                    start_offset=start_offset,
                    end_offset=_estimate_end_offset(text, start_offset, language),
                )
            )
    return symbols


def _estimate_end_offset(text: str, start_offset: int, language: str) -> int:
    if language in {"typescript", "javascript"}:
        brace_index = text.find("{", start_offset)
        if brace_index == -1:
            line_end = text.find("\n", start_offset)
            return len(text) if line_end == -1 else line_end
        depth = 0
        for offset in range(brace_index, len(text)):
            char = text[offset]
            if char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    return offset + 1
        return len(text)

    lines = text.splitlines(keepends=True)
    start_line = _line_number(text, start_offset) - 1
    base_indent = None
    offset = 0
    for line_index, line in enumerate(lines):
        if line_index < start_line:
            offset += len(line)
            continue
        stripped = line.strip()
        if line_index == start_line:
            base_indent = len(line) - len(line.lstrip(" "))
            offset += len(line)
            continue
        if stripped and (len(line) - len(line.lstrip(" "))) <= base_indent:
            return offset
        offset += len(line)
    return len(text)


def _resolve_import(current_path: str, specifier: str, root: Path) -> str | None:
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


def _summarize_file(relative_path: str, language: str, text: str) -> str:
    line_count = text.count("\n") + 1 if text else 0
    parts = relative_path.split("/")
    area = " / ".join(parts[:-1]) if len(parts) > 1 else "repository root"
    return f"{language.title()} source file in {area} with approximately {line_count} lines."


def _summarize_symbol(symbol: RawSymbol, relative_path: str) -> str:
    readable_name = " ".join(_split_words(symbol.name))
    return f"{symbol.kind} `{symbol.name}` in {relative_path} related to {readable_name.lower()}."


def _derive_tags(relative_path: str, name: str) -> list[str]:
    tokens = {token for token in _split_words(relative_path) + _split_words(name) if token not in STOPWORDS}
    return sorted(tokens)[:8]


def _split_words(value: str) -> list[str]:
    normalized = value.replace("/", " ").replace("_", " ").replace("-", " ")
    pieces: list[str] = []
    for chunk in normalized.split():
        parts = re.findall(r"[A-Z]+(?=[A-Z][a-z]|\d|$)|[A-Z]?[a-z]+|\d+", chunk)
        pieces.extend(part.lower() for part in parts if part)
    return pieces


def _line_number(text: str, offset: int) -> int:
    return text.count("\n", 0, max(offset, 0)) + 1


def _dedupe_edges(edges: list[Edge]) -> list[Edge]:
    unique: dict[tuple[str, str, str], Edge] = {}
    for edge in edges:
        key = (edge.source, edge.target, edge.kind)
        unique.setdefault(key, edge)
    return list(unique.values())
