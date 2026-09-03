
from __future__ import annotations

from pathlib import Path
from typing import Any

from .common import DependencyUnavailable, FileProcessingError, file_basic_info, safe_output_path
from .models import FileInput, ProcessingResult


def _pd():
    try:
        import pandas as pd
        return pd
    except Exception as exc:
        raise DependencyUnavailable("Spreadsheet processing requires pandas.") from exc


def _read(path: Path):
    pd = _pd()
    ext = path.suffix.casefold()
    if ext == ".csv":
        return pd.read_csv(path)
    if ext == ".tsv":
        return pd.read_csv(path, sep="\t")
    if ext in {".xlsx", ".xls"}:
        return pd.read_excel(path)
    raise FileProcessingError(f"Unsupported spreadsheet format: {ext}")


def process(file: FileInput, action: str, params: dict[str, Any]) -> ProcessingResult:
    pd = _pd()
    df = _read(file.path)
    action = action.casefold().strip()

    if action == "inspect":
        data = file_basic_info(file.path)
        data.update({
            "rows": int(len(df)),
            "columns": [str(c) for c in df.columns],
            "column_count": int(len(df.columns)),
            "dtypes": {str(c): str(t) for c, t in df.dtypes.items()},
            "preview": df.head(10).where(pd.notna(df), None).to_dict(orient="records"),
        })
        return ProcessingResult(True, action, f"Inspected spreadsheet {file.path.name}.", file, data=data)

    if action in {"analyze", "statistics"}:
        numeric = df.select_dtypes(include="number")
        stats = numeric.describe().where(pd.notna(numeric.describe()), None).to_dict() if len(numeric.columns) else {}
        data = {
            "rows": int(len(df)),
            "columns": [str(c) for c in df.columns],
            "missing_values": {str(c): int(v) for c, v in df.isna().sum().items()},
            "statistics": stats,
            "preview": df.head(12).where(pd.notna(df), None).to_dict(orient="records"),
        }
        if action == "statistics":
            return ProcessingResult(True, action, "Calculated spreadsheet statistics.", file, data=data)
        semantic = (
            f"Spreadsheet columns: {data['columns']}\n"
            f"Rows: {data['rows']}\n"
            f"Missing values: {data['missing_values']}\n"
            f"Numeric statistics: {stats}\n"
            f"Preview: {data['preview']}"
        )
        return ProcessingResult(
            True, action, "Prepared spreadsheet data for analysis.", file,
            data=data, semantic_text=semantic,
            semantic_instruction=str(params.get("instruction") or
                "Analyze this spreadsheet, identify important patterns, anomalies, and useful conclusions."),
        )

    if action == "filter":
        column = str(params.get("column", ""))
        operator = str(params.get("operator", "eq")).casefold()
        value = params.get("value")
        if column not in df.columns:
            raise FileProcessingError(f"Spreadsheet column not found: {column}")
        series = df[column]
        ops = {
            "eq": series == value,
            "ne": series != value,
            "gt": series > value,
            "gte": series >= value,
            "lt": series < value,
            "lte": series <= value,
            "contains": series.astype(str).str.contains(str(value), case=False, na=False),
        }
        if operator not in ops:
            raise FileProcessingError("Filter operator must be eq, ne, gt, gte, lt, lte, or contains.")
        result = df[ops[operator]]
        target = safe_output_path(file.path, "filtered", file.path.suffix)
        _save(result, target)
        return ProcessingResult(True, action, f"Filtered spreadsheet to {len(result)} row(s).", file,
                                output_path=target, data={"rows": int(len(result))})

    if action == "sort":
        column = str(params.get("column", ""))
        ascending = bool(params.get("ascending", True))
        if column not in df.columns:
            raise FileProcessingError(f"Spreadsheet column not found: {column}")
        result = df.sort_values(by=column, ascending=ascending)
        target = safe_output_path(file.path, "sorted", file.path.suffix)
        _save(result, target)
        return ProcessingResult(True, action, f"Sorted spreadsheet by {column}.", file,
                                output_path=target, data={"column": column, "ascending": ascending})

    if action == "convert":
        fmt = str(params.get("format", "")).casefold().lstrip(".")
        if fmt not in {"csv", "xlsx", "json"}:
            raise FileProcessingError("Spreadsheet conversion supports csv, xlsx, and json.")
        target = safe_output_path(file.path, "converted", "." + fmt)
        if fmt == "csv":
            df.to_csv(target, index=False)
        elif fmt == "xlsx":
            df.to_excel(target, index=False)
        else:
            df.to_json(target, orient="records", indent=2, force_ascii=False)
        return ProcessingResult(True, action, f"Converted spreadsheet to {fmt.upper()}.", file,
                                output_path=target)

    raise FileProcessingError(f"Unsupported spreadsheet action: {action}")


def _save(df, target: Path) -> None:
    ext = target.suffix.casefold()
    if ext == ".csv":
        df.to_csv(target, index=False)
    elif ext == ".tsv":
        df.to_csv(target, sep="\t", index=False)
    elif ext in {".xlsx", ".xls"}:
        df.to_excel(target, index=False)
    else:
        df.to_csv(target, index=False)
