from codemem.analyzers.base import (
    IGNORED_DIRS,
    SUPPORTED_EXTENSIONS,
    FileAnalysis,
    ImportReference,
    LanguageAnalyzer,
    SymbolRecord,
    discover_source_files,
)
from codemem.analyzers.javascript import JavaScriptAnalyzer
from codemem.analyzers.python import PythonAnalyzer

ANALYZERS = {
    "typescript": JavaScriptAnalyzer(),
    "javascript": JavaScriptAnalyzer(),
    "python": PythonAnalyzer(),
}

__all__ = [
    "ANALYZERS",
    "IGNORED_DIRS",
    "SUPPORTED_EXTENSIONS",
    "FileAnalysis",
    "ImportReference",
    "LanguageAnalyzer",
    "SymbolRecord",
    "discover_source_files",
]
