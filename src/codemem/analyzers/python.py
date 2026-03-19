from __future__ import annotations

import hashlib
import re

from codemem.analyzers.base import FileAnalysis, ImportReference, LanguageAnalyzer, SymbolRecord
from codemem.models import SourceSpan

PY_IMPORT_RE = re.compile(r"""^\s*import\s+(?P<module>[A-Za-z0-9_.,\s]+)""", re.MULTILINE)
PY_FROM_IMPORT_RE = re.compile(
    r"""^\s*from\s+(?P<module>[A-Za-z0-9_.]+)\s+import\s+(?P<names>[A-Za-z0-9_*,\s]+)""",
    re.MULTILINE,
)
PY_FUNCTION_RE = re.compile(
    r"""^\s*(?:async\s+)?def\s+(?P<name>[A-Za-z_]\w*)\s*\((?P<signature>[^)]*)\)""",
    re.MULTILINE,
)
PY_CLASS_RE = re.compile(r"""^\s*class\s+(?P<name>[A-Za-z_]\w*)""", re.MULTILINE)


class PythonAnalyzer(LanguageAnalyzer):
    name = "python_regex"
    version = "0.2.0"

    def analyze(self, relative_path: str, text: str) -> FileAnalysis:
        imports = self._extract_imports(text)
        symbols = self._extract_symbols(text)
        return FileAnalysis(
            relative_path=relative_path,
            language="python",
            file_hash=hashlib.sha256(text.encode("utf-8")).hexdigest(),
            line_count=text.count("\n") + 1 if text else 0,
            byte_size=len(text.encode("utf-8")),
            imports=imports,
            symbols=symbols,
        )

    def _extract_imports(self, text: str) -> list[ImportReference]:
        imports: list[ImportReference] = []
        for match in PY_IMPORT_RE.finditer(text):
            for module_name in [item.strip() for item in match.group("module").split(",")]:
                if module_name:
                    imports.append(
                        ImportReference(
                            specifier=module_name,
                            names=[module_name.split(".")[-1]],
                            import_kind="python",
                        )
                    )
        for match in PY_FROM_IMPORT_RE.finditer(text):
            names = [item.strip().split(" as ")[-1] for item in match.group("names").split(",")]
            imports.append(
                ImportReference(
                    specifier=match.group("module"),
                    names=[name for name in names if name],
                    import_kind="python",
                )
            )
        return imports

    def _extract_symbols(self, text: str) -> list[SymbolRecord]:
        patterns = [
            (PY_FUNCTION_RE, "Function"),
            (PY_CLASS_RE, "Class"),
        ]
        records: list[SymbolRecord] = []
        seen: set[tuple[str, int]] = set()
        for pattern, kind in patterns:
            for match in pattern.finditer(text):
                name = match.group("name")
                offset = match.start()
                if (name, offset) in seen:
                    continue
                seen.add((name, offset))
                span = self._build_span(text, offset)
                end_offset = self._estimate_end_offset(text, offset)
                body = text[offset:end_offset]
                exported = not name.startswith("_")
                records.append(
                    SymbolRecord(
                        kind=kind,
                        name=name,
                        signature=(match.groupdict().get("signature") or "").strip(),
                        span=SourceSpan(
                            start_line=span.start_line,
                            end_line=self._line_number(text, end_offset),
                            start_column=span.start_column,
                            end_column=span.end_column,
                        ),
                        body=body,
                        exported=exported,
                        visibility="public" if exported else "private",
                    )
                )
        records.sort(key=lambda record: (record.span.start_line, record.name))
        return records

    def _build_span(self, text: str, start_offset: int) -> SourceSpan:
        start_line = self._line_number(text, start_offset)
        line_start = text.rfind("\n", 0, start_offset) + 1
        column = start_offset - line_start + 1
        return SourceSpan(start_line=start_line, end_line=start_line, start_column=column)

    def _estimate_end_offset(self, text: str, start_offset: int) -> int:
        lines = text.splitlines(keepends=True)
        start_line = self._line_number(text, start_offset) - 1
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

    def _line_number(self, text: str, offset: int) -> int:
        return text.count("\n", 0, max(offset, 0)) + 1
