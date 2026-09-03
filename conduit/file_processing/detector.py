
from __future__ import annotations

from pathlib import Path

from .models import FileKind

IMAGE = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif", ".tif", ".tiff"}
PDF = {".pdf"}
DOCUMENT = {".docx", ".doc"}
TEXT = {".txt", ".md", ".rtf", ".log"}
SPREADSHEET = {".csv", ".xlsx", ".xls", ".tsv"}
JSON = {".json"}
XML = {".xml"}
AUDIO = {".mp3", ".wav", ".flac", ".m4a", ".aac", ".ogg", ".opus", ".wma"}
VIDEO = {".mp4", ".mkv", ".mov", ".avi", ".webm", ".m4v", ".wmv"}
ARCHIVE = {".zip", ".tar", ".gz", ".tgz", ".bz2", ".xz", ".7z"}
PRESENTATION = {".pptx", ".ppt"}
CODE = {
    ".py", ".js", ".ts", ".java", ".c", ".cpp", ".h", ".hpp", ".cs", ".go",
    ".rs", ".php", ".rb", ".swift", ".kt", ".kts", ".sql", ".html", ".css",
    ".scss", ".sh", ".ps1", ".bat", ".cmd", ".yaml", ".yml", ".toml", ".ini",
}


def detect_kind(path: str | Path) -> FileKind:
    suffix = Path(path).suffix.casefold()
    if suffix in IMAGE:
        return FileKind.IMAGE
    if suffix in PDF:
        return FileKind.PDF
    if suffix in DOCUMENT:
        return FileKind.DOCUMENT
    if suffix in TEXT:
        return FileKind.TEXT
    if suffix in SPREADSHEET:
        return FileKind.SPREADSHEET
    if suffix in JSON:
        return FileKind.JSON
    if suffix in XML:
        return FileKind.XML
    if suffix in AUDIO:
        return FileKind.AUDIO
    if suffix in VIDEO:
        return FileKind.VIDEO
    if suffix in ARCHIVE:
        return FileKind.ARCHIVE
    if suffix in PRESENTATION:
        return FileKind.PRESENTATION
    if suffix in CODE:
        return FileKind.CODE
    return FileKind.UNKNOWN


CAPABILITIES: dict[FileKind, tuple[str, ...]] = {
    FileKind.IMAGE: (
        "inspect", "describe", "ocr", "resize", "compress", "convert",
    ),
    FileKind.PDF: (
        "inspect", "extract_text", "summarize", "analyze", "to_word",
    ),
    FileKind.DOCUMENT: (
        "inspect", "extract_text", "summarize", "fix", "reformat",
        "translate", "word_count", "bullet_points", "convert",
    ),
    FileKind.TEXT: (
        "inspect", "extract_text", "summarize", "fix", "reformat",
        "translate", "word_count", "bullet_points", "convert",
    ),
    FileKind.SPREADSHEET: (
        "inspect", "analyze", "statistics", "filter", "sort", "convert",
    ),
    FileKind.JSON: (
        "inspect", "validate", "format", "analyze", "convert_csv",
    ),
    FileKind.XML: (
        "inspect", "validate", "format", "analyze", "convert_csv",
    ),
    FileKind.AUDIO: (
        "inspect", "transcribe", "trim", "convert",
    ),
    FileKind.VIDEO: (
        "inspect", "trim", "extract_audio", "extract_frame",
        "compress", "transcribe", "convert",
    ),
    FileKind.ARCHIVE: (
        "inspect", "list", "extract",
    ),
    FileKind.PRESENTATION: (
        "inspect", "extract_text", "summarize", "analyze",
    ),
    FileKind.CODE: (
        "inspect", "extract_text", "summarize", "analyze", "word_count",
    ),
    FileKind.UNKNOWN: ("inspect",),
}


def capabilities_for(kind: FileKind) -> tuple[str, ...]:
    return CAPABILITIES.get(kind, ("inspect",))
