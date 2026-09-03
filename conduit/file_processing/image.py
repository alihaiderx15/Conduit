
from __future__ import annotations

from pathlib import Path
from typing import Any

from PIL import Image

from .common import DependencyUnavailable, FileProcessingError, file_basic_info, safe_output_path
from .models import FileInput, ProcessingResult


def process(file: FileInput, action: str, params: dict[str, Any]) -> ProcessingResult:
    path = file.path
    action = action.casefold().strip()

    if action == "inspect":
        with Image.open(path) as img:
            data = file_basic_info(path)
            data.update({
                "format": img.format,
                "mode": img.mode,
                "width": img.width,
                "height": img.height,
                "frames": getattr(img, "n_frames", 1),
            })
        return ProcessingResult(True, action, f"Inspected image {path.name}.", file, data=data)

    if action == "resize":
        width = int(params.get("width", 0) or 0)
        height = int(params.get("height", 0) or 0)
        keep_aspect = bool(params.get("keep_aspect", True))
        if width <= 0 and height <= 0:
            raise FileProcessingError("Resize requires width and/or height.")

        with Image.open(path) as img:
            original_w, original_h = img.size
            if keep_aspect:
                if width <= 0:
                    width = max(1, round(original_w * (height / original_h)))
                elif height <= 0:
                    height = max(1, round(original_h * (width / original_w)))
                else:
                    ratio = min(width / original_w, height / original_h)
                    width = max(1, round(original_w * ratio))
                    height = max(1, round(original_h * ratio))
            else:
                width = width or original_w
                height = height or original_h

            target = safe_output_path(path, f"resized_{width}x{height}")
            resized = img.resize((width, height), Image.Resampling.LANCZOS)
            resized.save(target)

        return ProcessingResult(
            True, action, f"Resized image to {width}x{height}.", file,
            output_path=target, data={"width": width, "height": height},
        )

    if action == "compress":
        quality = max(1, min(int(params.get("quality", 80)), 100))
        with Image.open(path) as img:
            ext = path.suffix.casefold()
            target = safe_output_path(path, "compressed")
            save_params: dict[str, Any] = {"optimize": True}
            if ext in {".jpg", ".jpeg", ".webp"}:
                save_params["quality"] = quality
            img.save(target, **save_params)
        return ProcessingResult(
            True, action, f"Compressed image at quality {quality}.", file,
            output_path=target,
            data={"quality": quality, "size_bytes": target.stat().st_size},
        )

    if action == "convert":
        fmt = str(params.get("format", "")).strip().casefold().lstrip(".")
        if not fmt:
            raise FileProcessingError("Image conversion requires a target format.")
        fmt_alias = {"jpg": "JPEG", "jpeg": "JPEG", "png": "PNG", "webp": "WEBP",
                     "bmp": "BMP", "tif": "TIFF", "tiff": "TIFF"}
        if fmt not in fmt_alias:
            raise FileProcessingError(f"Unsupported image format: {fmt}")
        target = safe_output_path(path, "converted", "." + ("jpg" if fmt == "jpeg" else fmt))
        with Image.open(path) as img:
            if fmt in {"jpg", "jpeg"} and img.mode not in {"RGB", "L"}:
                img = img.convert("RGB")
            img.save(target, format=fmt_alias[fmt])
        return ProcessingResult(True, action, f"Converted image to {fmt.upper()}.", file, output_path=target)

    if action == "ocr":
        try:
            import pytesseract
        except Exception as exc:
            raise DependencyUnavailable(
                "OCR requires pytesseract and the Tesseract OCR engine."
            ) from exc
        with Image.open(path) as img:
            text = pytesseract.image_to_string(img)
        return ProcessingResult(
            True, action, "Extracted text from image.", file,
            data={"text": text, "characters": len(text)},
        )

    if action == "describe":
        # Vision is intentionally performed by Conduit's provider layer rather
        # than hard-coding Gemini/OpenAI inside this adapter.
        return ProcessingResult(
            True, action, "Image is ready for vision description.", file,
            semantic_instruction=str(params.get("instruction") or "Describe this image clearly."),
        )

    raise FileProcessingError(f"Unsupported image action: {action}")
