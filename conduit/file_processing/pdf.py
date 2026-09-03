
from __future__ import annotations

from pathlib import Path
from typing import Any

from .common import DependencyUnavailable, FileProcessingError, file_basic_info, safe_output_path
from .models import FileInput, ProcessingResult


def extract_text(path: Path) -> tuple[str, int]:
    try:
        from pypdf import PdfReader
    except Exception as exc:
        raise DependencyUnavailable("PDF processing requires pypdf.") from exc

    reader = PdfReader(str(path))
    pages = []
    for page in reader.pages:
        try:
            pages.append(page.extract_text() or "")
        except Exception:
            pages.append("")
    return "\n\n".join(pages), len(reader.pages)


def process(file: FileInput, action: str, params: dict[str, Any]) -> ProcessingResult:
    path = file.path
    action = action.casefold().strip()

    if action == "inspect":
        text, pages = extract_text(path)
        data = file_basic_info(path)
        data.update({"pages": pages, "characters": len(text), "has_extractable_text": bool(text.strip())})
        return ProcessingResult(True, action, f"Inspected PDF {path.name}.", file, data=data)

    if action == "extract_text":
        text, pages = extract_text(path)
        target = safe_output_path(path, "extracted_text", ".txt")
        target.write_text(text, encoding="utf-8")
        return ProcessingResult(
            True, action, f"Extracted text from {pages} PDF page(s).", file,
            output_path=target, data={"pages": pages, "text": text, "characters": len(text)},
        )

    if action in {"summarize", "analyze"}:
        text, pages = extract_text(path)
        if not text.strip():
            raise FileProcessingError(
                "This PDF has no extractable text. It may be scanned and require OCR first."
            )
        instruction = str(params.get("instruction") or (
            "Summarize this PDF clearly and preserve its important facts."
            if action == "summarize"
            else "Analyze this PDF and identify its key information, structure, and notable findings."
        ))
        return ProcessingResult(
            True, action, f"Prepared {pages} PDF page(s) for {action}.", file,
            data={"pages": pages, "characters": len(text)},
            semantic_text=text, semantic_instruction=instruction,
        )

    if action in {"to_word", "convert"}:
        text, pages = extract_text(path)
        try:
            from docx import Document
        except Exception as exc:
            raise DependencyUnavailable("PDF to Word conversion requires python-docx.") from exc
        target = safe_output_path(path, "converted", ".docx")
        doc = Document()
        for index, page_text in enumerate(text.split("\n\n"), start=1):
            if index > 1:
                doc.add_page_break()
            for paragraph in page_text.splitlines():
                if paragraph.strip():
                    doc.add_paragraph(paragraph)
        doc.save(target)
        return ProcessingResult(
            True, action,
            "Converted PDF text into an editable Word document. Complex original layout may not be preserved.",
            file, output_path=target, data={"pages": pages},
        )

    raise FileProcessingError(f"Unsupported PDF action: {action}")
