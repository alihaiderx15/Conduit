
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .common import FileProcessingError, require_file
from .detector import capabilities_for, detect_kind
from .models import FileInput, FileKind, FileSource, ProcessingResult
from . import image as image_adapter
from . import pdf as pdf_adapter
from . import document as document_adapter
from . import spreadsheet as spreadsheet_adapter
from . import structured as structured_adapter
from . import media as media_adapter
from . import archive as archive_adapter
from . import presentation as presentation_adapter


class FileProcessingService:
    """One backend for filesystem files, future GUI drops, and attachments."""

    def __init__(self, *, state_path: Path | None = None) -> None:
        self.state_path = state_path or (Path.home() / ".conduit" / "active_file.json")
        self._active: FileInput | None = None
        self._load_state()

    def input_from_path(
        self,
        path: str | Path,
        *,
        source: str | FileSource = FileSource.FILESYSTEM,
        temporary: bool = False,
    ) -> FileInput:
        target = Path(path).expanduser().resolve()
        require_file(target)
        source_enum = source if isinstance(source, FileSource) else FileSource(str(source))
        return FileInput(
            path=target,
            original_name=target.name,
            kind=detect_kind(target),
            source=source_enum,
            temporary=temporary,
        )

    def set_active_file(
        self,
        path: str | Path,
        *,
        source: str | FileSource = FileSource.FILESYSTEM,
        temporary: bool = False,
    ) -> FileInput:
        item = self.input_from_path(path, source=source, temporary=temporary)
        self._active = item
        self._save_state()
        return item

    def register_dropped_file(self, path: str | Path, *, temporary: bool = False) -> FileInput:
        """Future GUI hook: call this when the user drops a file onto Conduit."""
        return self.set_active_file(path, source=FileSource.GUI_DROP, temporary=temporary)

    def get_active_file(self) -> FileInput | None:
        if self._active and self._active.path.exists():
            return self._active
        self._active = None
        return None

    def capabilities(self, path: str | Path | None = None) -> dict[str, Any]:
        item = self._resolve(path)
        return {
            "file": item.data(),
            "actions": list(capabilities_for(item.kind)),
        }

    def process(
        self,
        *,
        action: str,
        path: str | Path | None = None,
        parameters: dict[str, Any] | None = None,
    ) -> ProcessingResult:
        params = dict(parameters or {})
        action = self._normalize_action(action, params)
        item = self._resolve(path)

        # Format-aware normalization. Models sometimes express a valid operation
        # using a friendly alias instead of the canonical adapter action.
        if item.kind is FileKind.VIDEO and action == "convert_to_audio":
            action = "extract_audio"
        if item.kind is FileKind.VIDEO and action == "convert" and str(params.get("format", "")).casefold() in {
            "mp3", "wav", "flac", "m4a", "aac", "ogg", "opus", "wma"
        }:
            # "convert this MP4 to MP3" means extract/convert the audio stream.
            action = "extract_audio"

        if action not in capabilities_for(item.kind):
            raise FileProcessingError(
                f"Action {action!r} is not supported for {item.kind.value} files. "
                f"Supported actions: {', '.join(capabilities_for(item.kind))}."
            )

        if item.kind is FileKind.IMAGE:
            result = image_adapter.process(item, action, params)
        elif item.kind is FileKind.PDF:
            result = pdf_adapter.process(item, action, params)
        elif item.kind in {FileKind.DOCUMENT, FileKind.TEXT, FileKind.CODE}:
            result = document_adapter.process(item, action, params)
        elif item.kind is FileKind.SPREADSHEET:
            result = spreadsheet_adapter.process(item, action, params)
        elif item.kind in {FileKind.JSON, FileKind.XML}:
            result = structured_adapter.process(item, action, params)
        elif item.kind in {FileKind.AUDIO, FileKind.VIDEO}:
            result = media_adapter.process(item, action, params)
        elif item.kind is FileKind.ARCHIVE:
            result = archive_adapter.process(item, action, params)
        elif item.kind is FileKind.PRESENTATION:
            result = presentation_adapter.process(item, action, params)
        else:
            if action == "inspect":
                result = ProcessingResult(
                    True, action, f"File exists but its type is not yet supported: {item.path.name}.",
                    item, data={"extension": item.path.suffix, "size_bytes": item.path.stat().st_size},
                )
            else:
                raise FileProcessingError(f"Unsupported file type: {item.path.suffix or 'unknown'}")

        # The last processed input becomes the active conversational file.
        self._active = item
        self._save_state(result=result)
        return result

    def complete_semantic(
        self,
        result: ProcessingResult,
        generated_text: str,
    ) -> ProcessingResult:
        """Persist AI-produced semantic output non-destructively."""
        action = result.action
        item = result.input_file

        if action in {"fix", "translate"} and item.path.suffix.casefold() == ".docx":
            target = document_adapter._write_docx_or_text(item, generated_text, action)
        else:
            suffix_map = {
                "summarize": "summary",
                "analyze": "analysis",
                "describe": "description",
                "fix": "fixed",
                "translate": "translated",
            }
            suffix = suffix_map.get(action, action or "processed")
            target = item.path.with_name(f"{item.path.stem}_{suffix}.txt")
            n = 2
            while target.exists():
                target = item.path.with_name(f"{item.path.stem}_{suffix}_{n}.txt")
                n += 1
            target.write_text(generated_text, encoding="utf-8")

        result.output_path = target
        result.data["generated_text"] = generated_text
        result.data["generated_characters"] = len(generated_text)
        result.message = f"Completed {action} for {item.original_name}."
        self._active = item
        self._save_state(result=result)
        return result

    @staticmethod
    def _normalize_action(action: str, params: dict[str, Any]) -> str:
        value = re.sub(r"[\s-]+", "_", str(action or "").casefold().strip())
        aliases = {
            "convert_to_mp3": ("extract_audio", {"format": "mp3"}),
            "convert_mp4_to_mp3": ("extract_audio", {"format": "mp3"}),
            "extract_audio_to_mp3": ("extract_audio", {"format": "mp3"}),
            "audio_to_mp3": ("extract_audio", {"format": "mp3"}),
            "convert_to_wav": ("extract_audio", {"format": "wav"}),
            "pdf_to_word": ("to_word", {}),
            "convert_to_word": ("to_word", {}),
            "convert_pdf_to_word": ("to_word", {}),
            "extract_text_from_pdf": ("extract_text", {}),
            "wordcount": ("word_count", {}),
            "count_words": ("word_count", {}),
            "make_bullets": ("bullet_points", {}),
            "bulletize": ("bullet_points", {}),
            "unzip": ("extract", {}),
            "list_contents": ("list", {}),
            "extract_archive": ("extract", {}),
        }
        mapped = aliases.get(value)
        if mapped is not None:
            canonical, defaults = mapped
            for key, val in defaults.items():
                params.setdefault(key, val)
            return canonical

        # Generic convert_to_<format> aliases.
        match = re.fullmatch(r"convert_to_([a-z0-9]+)", value)
        if match:
            fmt = match.group(1)
            if fmt in {"mp3", "wav", "flac", "m4a", "aac", "ogg", "opus", "wma"}:
                params.setdefault("format", fmt)
                return "extract_audio"
            params.setdefault("format", fmt)
            return "convert"

        return value

    @staticmethod
    def _looks_like_explicit_path(value: str) -> bool:
        text = value.strip().strip('"').strip("'")
        if not text:
            return False
        return bool(
            re.match(r"^[A-Za-z]:[\\/]", text)
            or text.startswith("\\\\")
            or text.startswith("/")
        )


    def _resolve(self, path: str | Path | None) -> FileInput:
        if path not in {None, ""}:
            candidate_text = str(path).strip()
            candidate = Path(candidate_text).expanduser()

            if candidate.exists():
                return self.input_from_path(candidate)

            active = self.get_active_file()
            if active is not None and not self._looks_like_explicit_path(candidate_text):
                # A GUI-dropped active file is authoritative unless the user
                # supplied a real absolute path. This prevents model mistakes
                # such as path="extrach the mp3 from 1.mp4".
                return active

            return self.input_from_path(candidate)

        active = self.get_active_file()
        if active is None:
            raise FileProcessingError(
                "No active file is set. Drop a file into Conduit or provide a file path."
            )
        return active

    def _save_state(self, *, result: ProcessingResult | None = None) -> None:
        try:
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
            payload: dict[str, Any] = {
                "active_file": self._active.data() if self._active else None,
            }
            if result is not None:
                payload["last_action"] = result.action
                payload["last_output_file"] = str(result.output_path) if result.output_path else None
            self.state_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        except Exception:
            # State persistence is useful context, never a reason to fail file work.
            pass

    def _load_state(self) -> None:
        try:
            if not self.state_path.exists():
                return
            payload = json.loads(self.state_path.read_text(encoding="utf-8"))
            data = payload.get("active_file")
            if not isinstance(data, dict):
                return
            path = Path(str(data.get("path", "")))
            if not path.exists():
                return
            self._active = FileInput(
                path=path,
                original_name=str(data.get("original_name") or path.name),
                kind=FileKind(str(data.get("kind") or detect_kind(path).value)),
                source=FileSource(str(data.get("source") or FileSource.FILESYSTEM.value)),
                temporary=bool(data.get("temporary", False)),
                metadata=dict(data.get("metadata") or {}),
            )
        except Exception:
            self._active = None


file_service = FileProcessingService()
