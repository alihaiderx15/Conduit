
from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any
import xml.etree.ElementTree as ET

from .common import FileProcessingError, file_basic_info, safe_output_path
from .models import FileInput, FileKind, ProcessingResult


def _json_load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _xml_load(path: Path):
    return ET.parse(path)


def process(file: FileInput, action: str, params: dict[str, Any]) -> ProcessingResult:
    action = action.casefold().strip()
    path = file.path

    if file.kind is FileKind.JSON:
        try:
            data_obj = _json_load(path)
            valid = True
            error = ""
        except Exception as exc:
            data_obj = None
            valid = False
            error = str(exc)

        if action == "validate":
            return ProcessingResult(valid, action,
                "JSON is valid." if valid else f"JSON is invalid: {error}", file,
                data={"valid": valid, "error": error})

        if not valid:
            raise FileProcessingError(f"Invalid JSON: {error}")

        if action == "inspect":
            data = file_basic_info(path)
            data.update({"root_type": type(data_obj).__name__,
                         "length": len(data_obj) if hasattr(data_obj, "__len__") else None})
            return ProcessingResult(True, action, "Inspected JSON file.", file, data=data)

        if action == "format":
            target = safe_output_path(path, "formatted", ".json")
            target.write_text(json.dumps(data_obj, indent=2, ensure_ascii=False), encoding="utf-8")
            return ProcessingResult(True, action, "Formatted JSON.", file, output_path=target)

        if action == "analyze":
            preview = json.dumps(data_obj, ensure_ascii=False, indent=2)
            if len(preview) > 30000:
                preview = preview[:30000] + "\n...[truncated]"
            return ProcessingResult(True, action, "Prepared JSON for analysis.", file,
                semantic_text=preview,
                semantic_instruction=str(params.get("instruction") or
                    "Analyze this JSON structure and explain its important fields and patterns."))

        if action in {"convert_csv", "convert"}:
            rows = data_obj if isinstance(data_obj, list) else [data_obj]
            if not rows or not all(isinstance(x, dict) for x in rows):
                raise FileProcessingError("JSON to CSV requires an object or list of objects.")
            keys = sorted({str(k) for row in rows for k in row.keys()})
            target = safe_output_path(path, "converted", ".csv")
            with target.open("w", newline="", encoding="utf-8") as fh:
                writer = csv.DictWriter(fh, fieldnames=keys)
                writer.writeheader()
                writer.writerows(rows)
            return ProcessingResult(True, action, "Converted JSON to CSV.", file, output_path=target)

    if file.kind is FileKind.XML:
        try:
            tree = _xml_load(path)
            root = tree.getroot()
            valid = True
            error = ""
        except Exception as exc:
            tree = root = None
            valid = False
            error = str(exc)

        if action == "validate":
            return ProcessingResult(valid, action,
                "XML is valid." if valid else f"XML is invalid: {error}", file,
                data={"valid": valid, "error": error})

        if not valid:
            raise FileProcessingError(f"Invalid XML: {error}")

        if action == "inspect":
            data = file_basic_info(path)
            data.update({"root_tag": root.tag, "element_count": sum(1 for _ in root.iter())})
            return ProcessingResult(True, action, "Inspected XML file.", file, data=data)

        if action == "format":
            ET.indent(tree, space="  ")
            target = safe_output_path(path, "formatted", ".xml")
            tree.write(target, encoding="utf-8", xml_declaration=True)
            return ProcessingResult(True, action, "Formatted XML.", file, output_path=target)

        if action == "analyze":
            xml_text = ET.tostring(root, encoding="unicode")
            return ProcessingResult(True, action, "Prepared XML for analysis.", file,
                semantic_text=xml_text[:30000],
                semantic_instruction=str(params.get("instruction") or
                    "Analyze this XML structure and explain its important elements and data."))

        if action in {"convert_csv", "convert"}:
            children = list(root)
            if not children:
                raise FileProcessingError("XML root has no child records to convert.")
            rows = []
            keys = set()
            for child in children:
                row = {grand.tag: (grand.text or "") for grand in list(child)}
                if not row:
                    row = {"tag": child.tag, "text": child.text or ""}
                keys.update(row)
                rows.append(row)
            target = safe_output_path(path, "converted", ".csv")
            fieldnames = sorted(keys)
            with target.open("w", newline="", encoding="utf-8") as fh:
                writer = csv.DictWriter(fh, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(rows)
            return ProcessingResult(True, action, "Converted XML records to CSV.", file, output_path=target)

    raise FileProcessingError(f"Unsupported structured-data action: {action}")
