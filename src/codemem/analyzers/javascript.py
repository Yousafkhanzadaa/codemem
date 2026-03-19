from __future__ import annotations

import hashlib
import re

from codemem.analyzers.base import FileAnalysis, ImportReference, LanguageAnalyzer, SymbolRecord
from codemem.models import SourceSpan

JS_IMPORT_RE = re.compile(
    r"""^\s*(?:import|export)\s+(?P<clause>.+?)\s+from\s+['"](?P<module>[^'"]+)['"]""",
    re.MULTILINE,
)
JS_REQUIRE_RE = re.compile(
    r"""^\s*(?:const|let|var)\s+(?P<name>[A-Za-z_$][\w$]*)\s*=\s*require\(['"](?P<module>[^'"]+)['"]\)""",
    re.MULTILINE,
)
JS_FUNCTION_RE = re.compile(
    r"""^\s*(?P<export>export\s+)?(?:async\s+)?function\s+(?P<name>[A-Za-z_$][\w$]*)\s*\((?P<signature>[^)]*)\)""",
    re.MULTILINE,
)
JS_ARROW_RE = re.compile(
    r"""^\s*(?P<export>export\s+)?(?:const|let|var)\s+(?P<name>[A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?(?P<signature>\([^)]*\)|[A-Za-z_$][\w$]*)\s*=>""",
    re.MULTILINE,
)
JS_FUNCTION_EXPR_RE = re.compile(
    r"""^\s*(?P<export>export\s+)?(?:const|let|var)\s+(?P<name>[A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?function\s*\((?P<signature>[^)]*)\)""",
    re.MULTILINE,
)
JS_CLASS_RE = re.compile(
    r"""^\s*(?P<export>export\s+)?class\s+(?P<name>[A-Za-z_$][\w$]*)""",
    re.MULTILINE,
)


class JavaScriptAnalyzer(LanguageAnalyzer):
    name = "javascript_regex"
    version = "0.2.0"

    def analyze(self, relative_path: str, text: str) -> FileAnalysis:
        language = "typescript" if relative_path.endswith((".ts", ".tsx")) else "javascript"
        imports = self._extract_imports(text)
        symbols = self._extract_symbols(relative_path, text, language)
        return FileAnalysis(
            relative_path=relative_path,
            language=language,
            file_hash=hashlib.sha256(text.encode("utf-8")).hexdigest(),
            line_count=text.count("\n") + 1 if text else 0,
            byte_size=len(text.encode("utf-8")),
            imports=imports,
            symbols=symbols,
        )

    def _extract_imports(self, text: str) -> list[ImportReference]:
        imports: list[ImportReference] = []
        for match in JS_IMPORT_RE.finditer(text):
            clause = match.group("clause").strip()
            imports.append(
                ImportReference(
                    specifier=match.group("module"),
                    names=self._extract_import_names(clause),
                    import_kind="relative" if match.group("module").startswith(".") else "external",
                )
            )
        for match in JS_REQUIRE_RE.finditer(text):
            imports.append(
                ImportReference(
                    specifier=match.group("module"),
                    names=[match.group("name")],
                    import_kind="relative" if match.group("module").startswith(".") else "external",
                )
            )
        return imports

    def _extract_import_names(self, clause: str) -> list[str]:
        clause = clause.strip()
        names: list[str] = []
        if clause.startswith("{") and clause.endswith("}"):
            for item in clause[1:-1].split(","):
                local = item.strip().split(" as ")[-1].strip()
                if local:
                    names.append(local)
            return names
        if "," in clause:
            default_name, named = clause.split(",", 1)
            if default_name.strip():
                names.append(default_name.strip())
            names.extend(self._extract_import_names(named.strip()))
            return names
        cleaned = clause.replace("* as ", "").strip()
        if cleaned:
            names.append(cleaned)
        return names

    def _extract_symbols(self, relative_path: str, text: str, language: str) -> list[SymbolRecord]:
        patterns = [
            (JS_FUNCTION_RE, "Function"),
            (JS_ARROW_RE, "Function"),
            (JS_FUNCTION_EXPR_RE, "Function"),
            (JS_CLASS_RE, "Class"),
        ]
        records: list[SymbolRecord] = []
        seen: set[tuple[str, int]] = set()

        for pattern, default_kind in patterns:
            for match in pattern.finditer(text):
                name = match.group("name")
                offset = match.start()
                if (name, offset) in seen:
                    continue
                seen.add((name, offset))
                span = self._build_span(text, offset)
                end_offset = self._estimate_end_offset(text, offset)
                body = text[offset:end_offset]
                kind = default_kind
                if default_kind == "Function" and relative_path.endswith((".tsx", ".jsx")) and name[:1].isupper():
                    kind = "Component"
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
                        exported=bool(match.groupdict().get("export")),
                        visibility="public" if bool(match.groupdict().get("export")) else "local",
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

    def _line_number(self, text: str, offset: int) -> int:
        return text.count("\n", 0, max(offset, 0)) + 1
