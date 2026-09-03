
from __future__ import annotations

from dataclasses import dataclass
import re


@dataclass(frozen=True)
class ModelProfile:
    name: str
    label: str
    description: str
    specialties: tuple[str, ...]


CURATED_OLLAMA_MODELS: tuple[ModelProfile, ...] = (
    ModelProfile(
        "devstral-small-2",
        "Devstral Small 2",
        "Coding • Agentic",
        ("coding",),
    ),
    ModelProfile(
        "qwen3-coder:30b",
        "Qwen3 Coder 30B",
        "Coding • Long context",
        ("coding",),
    ),
    ModelProfile(
        "qwen2.5-coder:14b",
        "Qwen2.5 Coder 14B",
        "Coding • Strong",
        ("coding",),
    ),
    ModelProfile(
        "qwen2.5-coder:7b",
        "Qwen2.5 Coder 7B",
        "Coding • Lightweight",
        ("coding",),
    ),
    ModelProfile(
        "qwen2.5vl:7b",
        "Qwen2.5 VL 7B",
        "Vision • Desktop",
        ("vision",),
    ),
)

_PROFILE_BY_NAME = {item.name.casefold(): item for item in CURATED_OLLAMA_MODELS}


def normalized_model_name(name: str) -> str:
    return str(name or "").casefold().strip()


def describe_ollama_model(name: str) -> str:
    normalized = normalized_model_name(name)
    exact = _PROFILE_BY_NAME.get(normalized)
    if exact:
        return exact.description

    if "devstral" in normalized:
        return "Coding • Agentic"
    if "coder" in normalized or "codestral" in normalized:
        return "Coding • Developer"
    if any(token in normalized for token in ("vl", "vision", "llava", "minicpm-v")):
        return "Vision • Images"
    if any(token in normalized for token in ("reason", "r1", "qwq")):
        return "Reasoning • Logic"
    if any(token in normalized for token in ("qwen", "llama", "mistral", "gemma", "phi")):
        return "Chat • General"
    return "General • Local"


def model_specialties(name: str) -> set[str]:
    normalized = normalized_model_name(name)
    exact = _PROFILE_BY_NAME.get(normalized)
    if exact:
        return set(exact.specialties)

    result: set[str] = set()
    if "devstral" in normalized or "coder" in normalized or "codestral" in normalized:
        result.add("coding")
    if any(token in normalized for token in ("vl", "vision", "llava", "minicpm-v")):
        result.add("vision")
    if not result:
        result.add("general")
    return result


def classify_task(text: str, *, active_file_kind: str = "") -> str | None:
    prompt = " ".join(str(text or "").casefold().split())
    kind = str(active_file_kind or "").casefold().strip()

    code_terms = (
        "code", "python", "javascript", "typescript", "java", "c++", "cpp",
        "c#", "csharp", "debug", "compile", "program", "script", "function",
        "class", "syntax error", "fix the error", "optimize this code",
        "review this code", "edit this code", "run this", "test this code",
    )
    code_verbs = ("generate", "create", "write", "edit", "fix", "debug", "optimize", "review", "run", "test")
    if kind == "code" and any(word in prompt for word in code_verbs):
        return "coding"
    if any(term in prompt for term in code_terms):
        return "coding"

    vision_terms = (
        "describe this image", "describe the image", "look at this image",
        "what is in this image", "what's in this image", "read this image",
        "ocr this", "look at my screen", "what is on my screen",
        "what's on my screen", "analyze this screenshot", "analyse this screenshot",
        "screen visually", "vision",
    )
    if any(term in prompt for term in vision_terms):
        return "vision"
    if kind == "image" and any(term in prompt for term in ("describe", "ocr", "read", "analyze", "analyse")):
        return "vision"
    return None


def recommended_model(task: str) -> ModelProfile | None:
    if task == "coding":
        return _PROFILE_BY_NAME["devstral-small-2"]
    if task == "vision":
        return _PROFILE_BY_NAME["qwen2.5vl:7b"]
    return None


def current_model_is_suitable(model: str, task: str) -> bool:
    if not task:
        return True
    return task in model_specialties(model)


def ollama_catalog(installed_models: list[str]) -> list[dict[str, object]]:
    """Installed local models plus a small curated specialist download list."""
    installed = {normalized_model_name(name): name for name in installed_models}
    rows: list[dict[str, object]] = []

    for name in installed_models:
        rows.append({
            "name": name,
            "installed": True,
            "description": describe_ollama_model(name),
        })

    for profile in CURATED_OLLAMA_MODELS:
        if normalized_model_name(profile.name) not in installed:
            rows.append({
                "name": profile.name,
                "installed": False,
                "description": profile.description,
            })
    return rows


def valid_ollama_model_name(name: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}", str(name or "").strip()))
