
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .common import DependencyUnavailable, FileProcessingError, ffmpeg_executable, run_process, safe_output_path
from .models import FileInput, FileKind, ProcessingResult


def _probe(path: Path) -> dict[str, Any]:
    ffprobe = ffmpeg_executable("ffprobe")
    result = run_process([
        ffprobe, "-v", "quiet", "-print_format", "json",
        "-show_format", "-show_streams", str(path),
    ], timeout=30)
    try:
        return json.loads(result.stdout)
    except Exception:
        return {"raw": result.stdout}


def _time_arg(value: Any) -> str:
    if value is None or value == "":
        raise FileProcessingError("This action requires a start/end time.")
    return str(value)


def _transcribe(path: Path, model_size: str = "small") -> str:
    try:
        from faster_whisper import WhisperModel
    except Exception as exc:
        raise DependencyUnavailable(
            "Transcription requires the optional faster-whisper package."
        ) from exc

    model = WhisperModel(model_size, device="cpu", compute_type="int8")
    segments, _info = model.transcribe(str(path))
    return " ".join(segment.text.strip() for segment in segments if segment.text.strip())


def process(file: FileInput, action: str, params: dict[str, Any]) -> ProcessingResult:
    action = action.casefold().strip()
    path = file.path

    if action == "inspect":
        data = _probe(path)
        return ProcessingResult(True, action, f"Inspected media file {path.name}.", file, data=data)

    if action == "convert":
        fmt = str(params.get("format", "")).casefold().lstrip(".")
        if not fmt:
            raise FileProcessingError("Media conversion requires a target format.")
        target = safe_output_path(path, "converted", "." + fmt)
        ffmpeg = ffmpeg_executable()
        run_process([ffmpeg, "-y", "-i", str(path), str(target)], timeout=600)
        return ProcessingResult(True, action, f"Converted media to {fmt.upper()}.", file, output_path=target)

    if action == "trim":
        start = _time_arg(params.get("start", "0"))
        end = params.get("end")
        duration = params.get("duration")
        target = safe_output_path(path, "trimmed")
        ffmpeg = ffmpeg_executable()
        cmd = [ffmpeg, "-y", "-ss", start, "-i", str(path)]
        if duration not in {None, ""}:
            cmd += ["-t", str(duration)]
        elif end not in {None, ""}:
            cmd += ["-to", str(end)]
        else:
            raise FileProcessingError("Trim requires end or duration.")
        cmd += ["-c", "copy", str(target)]
        run_process(cmd, timeout=600)
        return ProcessingResult(True, action, "Trimmed media file.", file, output_path=target,
                                data={"start": start, "end": end, "duration": duration})

    if action == "transcribe":
        model = str(params.get("model", "small"))
        if file.kind is FileKind.VIDEO:
            ffmpeg = ffmpeg_executable()
            temp = safe_output_path(path, "transcription_audio", ".wav")
            run_process([
                ffmpeg, "-y", "-i", str(path), "-vn", "-ac", "1", "-ar", "16000", str(temp)
            ], timeout=600)
            try:
                text = _transcribe(temp, model)
            finally:
                try:
                    temp.unlink()
                except Exception:
                    pass
        else:
            text = _transcribe(path, model)
        target = safe_output_path(path, "transcript", ".txt")
        target.write_text(text, encoding="utf-8")
        return ProcessingResult(True, action, "Transcribed media file.", file, output_path=target,
                                data={"text": text, "characters": len(text)})

    if file.kind is FileKind.VIDEO and action == "extract_audio":
        fmt = str(params.get("format", "mp3")).casefold().lstrip(".")
        target = safe_output_path(path, "audio", "." + fmt)
        ffmpeg = ffmpeg_executable()
        run_process([ffmpeg, "-y", "-i", str(path), "-vn", str(target)], timeout=600)
        return ProcessingResult(True, action, f"Extracted video audio as {fmt.upper()}.", file,
                                output_path=target)

    if file.kind is FileKind.VIDEO and action == "extract_frame":
        timestamp = str(params.get("time", params.get("timestamp", "0")))
        fmt = str(params.get("format", "jpg")).casefold().lstrip(".")
        target = safe_output_path(path, "frame", "." + fmt)
        ffmpeg = ffmpeg_executable()
        run_process([
            ffmpeg, "-y", "-ss", timestamp, "-i", str(path), "-frames:v", "1", str(target)
        ], timeout=180)
        return ProcessingResult(True, action, f"Extracted video frame at {timestamp}.", file,
                                output_path=target, data={"timestamp": timestamp})

    if file.kind is FileKind.VIDEO and action == "compress":
        crf = max(18, min(int(params.get("crf", 28)), 40))
        target = safe_output_path(path, "compressed", ".mp4")
        ffmpeg = ffmpeg_executable()
        run_process([
            ffmpeg, "-y", "-i", str(path),
            "-c:v", "libx264", "-crf", str(crf), "-preset", str(params.get("preset", "medium")),
            "-c:a", "aac", "-b:a", "128k", str(target),
        ], timeout=1200)
        return ProcessingResult(True, action, f"Compressed video using CRF {crf}.", file,
                                output_path=target, data={"crf": crf})

    raise FileProcessingError(f"Unsupported media action: {action}")
