"""Strict parsing and validation for model-produced screen JSON."""
from __future__ import annotations

import ast
import json
import re
from typing import Any

from conduit.observer.models import Rectangle, ScreenCapture, ScreenElement, StructuredScreenAnalysis


class ScreenAnalysisParseError(ValueError):
    """Raised when vision output cannot be converted into safe structured data."""


def _repair_json_syntax(text: str) -> str:
    """Repair narrow serialization mistakes without changing screen semantics.

    This only touches JSON syntax: smart quotes, unquoted object keys, Python
    booleans/None, and trailing commas. It does not add elements, coordinates,
    labels, or any other visual claims.
    """
    repaired = text
    repaired = repaired.replace("“", '"').replace("”", '"').replace("‘", "'").replace("’", "'")

    # Quote bare object keys: {x: 1, width: 20} -> {"x": 1, "width": 20}
    repaired = re.sub(
        r'(?P<prefix>[\{,]\s*)(?P<key>[A-Za-z_][A-Za-z0-9_-]*)(?P<colon>\s*:)',
        lambda m: f'{m.group("prefix")}"{m.group("key")}"{m.group("colon")}',
        repaired,
    )

    # Python literals occasionally appear in otherwise JSON-like output.
    repaired = re.sub(r"\bTrue\b", "true", repaired)
    repaired = re.sub(r"\bFalse\b", "false", repaired)
    repaired = re.sub(r"\bNone\b", "null", repaired)

    # Remove trailing commas before closing arrays/objects.
    repaired = re.sub(r",\s*([}\]])", r"\1", repaired)
    return repaired


def _extract_json(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", cleaned, re.DOTALL | re.IGNORECASE)
    if fenced:
        cleaned = fenced.group(1)
    else:
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start >= 0 and end > start:
            cleaned = cleaned[start : end + 1]
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as json_exc:
        repaired = _repair_json_syntax(cleaned)
        try:
            data = json.loads(repaired)
        except json.JSONDecodeError:
            # Some local vision models return a Python-style dict with single
            # quotes and Python literals. Parse the ORIGINAL text here because
            # JSON-oriented repair converts True/False/None to JSON literals.
            try:
                data = ast.literal_eval(cleaned)
            except (ValueError, SyntaxError) as exc:
                raise ScreenAnalysisParseError(
                    f"Vision model did not return valid JSON: {json_exc}"
                ) from exc
    if not isinstance(data, dict):
        raise ScreenAnalysisParseError("Screen analysis must be a JSON object.")
    return data


def parse_structured_screen_analysis(
    text: str,
    *,
    capture: ScreenCapture,
    provider_id: str,
    model: str,
) -> StructuredScreenAnalysis:
    """Parse model JSON and reject unsafe/out-of-bounds coordinates."""
    data = _extract_json(text)
    application = str(data.get("application") or data.get("screen", {}).get("application") or "Unknown")
    summary = str(data.get("summary") or "")
    raw_elements = data.get("elements", [])
    if not isinstance(raw_elements, list):
        raise ScreenAnalysisParseError("'elements' must be an array.")

    elements: list[ScreenElement] = []
    seen_ids: set[str] = set()
    for index, item in enumerate(raw_elements):
        if not isinstance(item, dict):
            continue
        bounds_data = item.get("bounds")
        if not isinstance(bounds_data, dict):
            continue
        try:
            bounds = Rectangle(
                x=int(bounds_data["x"]),
                y=int(bounds_data["y"]),
                width=int(bounds_data["width"]),
                height=int(bounds_data["height"]),
            )
        except (KeyError, TypeError, ValueError):
            continue
        if not bounds.is_within(capture.width, capture.height):
            continue

        raw_id = str(item.get("id") or item.get("element_id") or f"element_{index}")
        element_id = re.sub(r"[^a-zA-Z0-9_-]+", "_", raw_id).strip("_") or f"element_{index}"
        if element_id in seen_ids:
            element_id = f"{element_id}_{index}"
        seen_ids.add(element_id)

        try:
            confidence = float(item.get("confidence", 0.5))
        except (TypeError, ValueError):
            confidence = 0.5
        confidence = max(0.0, min(confidence, 1.0))

        elements.append(
            ScreenElement(
                element_id=element_id,
                label=str(item.get("label") or item.get("text") or element_id),
                role=str(item.get("role") or "unknown").casefold(),
                bounds=bounds,
                confidence=confidence,
                text=str(item.get("text") or ""),
                enabled=bool(item.get("enabled", True)),
                visible=bool(item.get("visible", True)),
            )
        )

    return StructuredScreenAnalysis(
        capture=capture,
        application=application,
        summary=summary,
        elements=tuple(elements),
        provider_id=provider_id,
        model=model,
        raw_text=text,
    )
