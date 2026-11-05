"""Read-only access to the participant-provided CSV and evidence files."""

import csv
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
DATASET = (ROOT / "dataset").resolve()
OUTPUT_CSV = (ROOT / "output.csv").resolve()


def _read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    if not path.is_file():
        raise FileNotFoundError(str(path))
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        return list(reader.fieldnames or []), list(reader)


def _inside_dataset(relative_path: str) -> Path:
    candidate = (DATASET / relative_path).resolve()
    if candidate != DATASET and DATASET not in candidate.parents:
        raise ValueError("Requested path is outside dataset/.")
    return candidate


def list_dataset_files() -> list[dict[str, Any]]:
    items = []
    for path in sorted(DATASET.rglob("*.csv")):
        if not path.is_file():
            continue
        relative = path.relative_to(DATASET).as_posix()
        headers, rows = _read_csv(path)
        items.append({
            "path": relative,
            "name": path.name,
            "rows": len(rows),
            "columns": headers,
            "size_bytes": path.stat().st_size,
            "modified_at": datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat(),
        })
    return items


def get_csv_table(relative_path: str, page: int = 1, page_size: int = 100, search: str = "") -> dict[str, Any]:
    path = _inside_dataset(relative_path)
    if path.suffix.lower() != ".csv":
        raise ValueError("Only CSV files in dataset/ can be viewed as tables.")
    headers, rows = _read_csv(path)
    if search.strip():
        needle = search.strip().casefold()
        rows = [row for row in rows if any(needle in str(value).casefold() for value in row.values())]
    start = (page - 1) * page_size
    return {
        "path": path.relative_to(DATASET).as_posix(),
        "columns": headers,
        "rows": rows[start:start + page_size],
        "total_rows": len(rows),
        "page": page,
        "page_size": page_size,
        "total_pages": max(1, (len(rows) + page_size - 1) // page_size),
    }


def get_output_table(page: int = 1, page_size: int = 100) -> dict[str, Any]:
    if not OUTPUT_CSV.is_file():
        raise FileNotFoundError(str(OUTPUT_CSV))
    headers, rows = _read_csv(OUTPUT_CSV)
    start = (page - 1) * page_size
    return {
        "path": "output.csv",
        "columns": headers,
        "rows": rows[start:start + page_size],
        "total_rows": len(rows),
        "page": page,
        "page_size": page_size,
        "total_pages": max(1, (len(rows) + page_size - 1) // page_size),
        "validation": validate_output(headers, rows),
        "modified_at": datetime.fromtimestamp(OUTPUT_CSV.stat().st_mtime, timezone.utc).isoformat(),
    }


def validate_output(headers: list[str], rows: list[dict[str, str]]) -> dict[str, Any]:
    errors = []
    expected_headers = ["case_id", "deletion_status", "steps_json"]
    if headers != expected_headers:
        errors.append(f"Expected columns {expected_headers}; found {headers}.")
    request_rows = get_csv_table("deletion_requests.csv", 1, 1000)["rows"]
    request_ids = [row.get("case_id", "") for row in request_rows]
    output_ids = [row.get("case_id", "") for row in rows]
    if len(rows) != len(request_rows):
        errors.append(f"Expected {len(request_rows)} output rows; found {len(rows)}.")
    if output_ids != sorted(output_ids, key=lambda cid: int(cid.split("_")[-1]) if cid.startswith("case_") and cid.split("_")[-1].isdigit() else cid):
        errors.append("Rows are not sorted by case_id.")
    missing = sorted(set(request_ids) - set(output_ids))
    extra = sorted(set(output_ids) - set(request_ids))
    if missing:
        errors.append(f"Missing case IDs: {', '.join(missing[:20])}.")
    if extra:
        errors.append(f"Unexpected case IDs: {', '.join(extra[:20])}.")
    for row in rows:
        cid = row.get("case_id", "")
        if row.get("deletion_status") not in {"COMPLETE", "INCOMPLETE", "NOT_APPLICABLE"}:
            errors.append(f"{cid}: invalid deletion_status.")
        try:
            steps = json.loads(row.get("steps_json", ""))
            if not isinstance(steps, list):
                raise ValueError("steps_json is not an array")
            if row.get("deletion_status") == "NOT_APPLICABLE" and steps:
                errors.append(f"{cid}: NOT_APPLICABLE must have an empty steps_json array.")
            if row.get("deletion_status") != "NOT_APPLICABLE" and not steps:
                errors.append(f"{cid}: missing evidence-backed steps.")
            for index, step in enumerate(steps, 1):
                if step.get("step_no") != index:
                    errors.append(f"{cid}: step numbers are not consecutive.")
                    break
                if row.get("deletion_status") == "COMPLETE" and (step.get("phase") != "VERIFICATION" or not step.get("evidence_id")):
                    errors.append(f"{cid}: COMPLETE requires evidence-cited VERIFICATION steps.")
                    break
        except (ValueError, TypeError, AttributeError):
            errors.append(f"{cid}: steps_json is not a valid JSON array.")
        if len(errors) >= 100:
            break
    return {"valid": not errors, "errors": errors, "error_count_at_least": len(errors)}


def list_evidence() -> list[dict[str, Any]]:
    _, manifest = _read_csv(DATASET / "evidence_files.csv")
    results = []
    for row in manifest:
        path = _inside_dataset(row["file_path"])
        results.append({
            **row,
            "available": path.is_file(),
            "size_bytes": path.stat().st_size if path.is_file() else 0,
            "file_type": path.suffix.lower().lstrip("."),
        })
    return results


def get_evidence(file_id: str) -> dict[str, Any] | None:
    _, manifest = _read_csv(DATASET / "evidence_files.csv")
    metadata = next((row for row in manifest if row.get("file_id") == file_id), None)
    if metadata is None:
        return None
    path = _inside_dataset(metadata["file_path"])
    if not path.is_file():
        raise FileNotFoundError(str(path))
    suffix = path.suffix.lower()
    if suffix in {".txt", ".log", ".sql", ".json", ".csv"}:
        content = path.read_text(encoding="utf-8", errors="replace")
    elif suffix == ".pdf":
        from pypdf import PdfReader
        content = "\n\n".join(page.extract_text() or "" for page in PdfReader(str(path)).pages)
    elif suffix in {".png", ".jpg", ".jpeg"}:
        extracted = _inside_dataset(f"evidence/images_extracted/{path.name}.json")
        content = json.loads(extracted.read_text(encoding="utf-8")).get("extracted_text", "") if extracted.is_file() else "No extracted OCR text is available."
    else:
        content = f"Text extraction is not configured for {suffix or 'this file type'}."
    return {**metadata, "content": content, "file_type": suffix.lstrip("."), "download_url": f"/api/evidence/{file_id}/file"}


def get_case(case_id: str) -> dict[str, Any] | None:
    _, requests = _read_csv(DATASET / "deletion_requests.csv")
    request = next((row for row in requests if row.get("case_id") == case_id), None)
    if request is None:
        return None
    output_rows = []
    if OUTPUT_CSV.is_file():
        _, output_rows = _read_csv(OUTPUT_CSV)
    output = next((row for row in output_rows if row.get("case_id") == case_id), None)
    return {"request": request, "output": output}
