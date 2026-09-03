
from __future__ import annotations

from pathlib import Path
import shutil
import tarfile
from typing import Any
import zipfile

from .common import FileProcessingError, file_basic_info, safe_output_path
from .models import FileInput, ProcessingResult


def _safe_target(base: Path, member: str) -> Path:
    target = (base / member).resolve()
    if base.resolve() not in target.parents and target != base.resolve():
        raise FileProcessingError(f"Unsafe archive path blocked: {member}")
    return target


def _members(path: Path) -> list[dict[str, Any]]:
    ext = path.suffix.casefold()
    if ext == ".zip":
        with zipfile.ZipFile(path) as zf:
            return [{"name": i.filename, "size": i.file_size, "compressed_size": i.compress_size}
                    for i in zf.infolist()]
    if tarfile.is_tarfile(path):
        with tarfile.open(path) as tf:
            return [{"name": m.name, "size": m.size, "is_dir": m.isdir()} for m in tf.getmembers()]
    raise FileProcessingError("Archive listing currently supports ZIP and TAR-family archives.")


def process(file: FileInput, action: str, params: dict[str, Any]) -> ProcessingResult:
    action = action.casefold().strip()
    path = file.path

    if action in {"inspect", "list"}:
        items = _members(path)
        data = file_basic_info(path)
        data.update({"entries": items, "entry_count": len(items)})
        return ProcessingResult(True, action, f"Archive contains {len(items)} item(s).", file, data=data)

    if action == "extract":
        destination = params.get("destination")
        if destination:
            target_dir = Path(str(destination)).expanduser().resolve()
            target_dir.mkdir(parents=True, exist_ok=True)
        else:
            target_dir = safe_output_path(path, "extracted", "")
            target_dir.mkdir(parents=True, exist_ok=False)

        if path.suffix.casefold() == ".zip":
            with zipfile.ZipFile(path) as zf:
                for info in zf.infolist():
                    _safe_target(target_dir, info.filename)
                zf.extractall(target_dir)
        elif tarfile.is_tarfile(path):
            with tarfile.open(path) as tf:
                for member in tf.getmembers():
                    _safe_target(target_dir, member.name)
                tf.extractall(target_dir)
        else:
            raise FileProcessingError("Archive extraction currently supports ZIP and TAR-family archives.")

        return ProcessingResult(True, action, f"Extracted archive to {target_dir}.", file,
                                output_path=target_dir, data={"destination": str(target_dir)})

    raise FileProcessingError(f"Unsupported archive action: {action}")
