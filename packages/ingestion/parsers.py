import csv
import hashlib
import io
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

MAX_UPLOAD_SIZE = 50 * 1024 * 1024  # 50 MB
MAX_ROW_SIZE = 64 * 1024  # 64 KB


class FileTooLargeError(Exception):
    pass


class InvalidFileFormatError(Exception):
    pass


@dataclass
class ParsedRawItem:
    row_locator: str
    sha256_hash: str
    raw_payload: dict[str, Any]
    raw_str: str


def sanitize_filename(filename: str) -> str:
    # Strip any directory path components to prevent path traversal
    pure_name = Path(filename).name
    # Keep only alphanumeric and safe punctuation
    safe_name = "".join(c for c in pure_name if c.isalnum() or c in (".", "_", "-")).strip()
    return safe_name or "evidence_file.dat"


def compute_bytes_sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def compute_text_sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def parse_csv_content(
    content_bytes: bytes, max_row_size: int = MAX_ROW_SIZE
) -> list[ParsedRawItem]:
    # Decode text, handling UTF-8 with or without BOM
    try:
        text = content_bytes.decode("utf-8-sig")
    except UnicodeDecodeError:
        try:
            text = content_bytes.decode("latin-1")
        except Exception as e:
            raise InvalidFileFormatError(f"Cannot decode CSV file: {e}")

    lines = text.splitlines(keepends=True)
    if not lines:
        return []

    # Check header size
    if len(lines[0].encode("utf-8")) > max_row_size:
        raise InvalidFileFormatError("CSV header row exceeds maximum allowable size")

    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        return []

    # Sanitize fieldnames: strip whitespace and BOM remnants
    clean_fieldnames = [f.strip() if isinstance(f, str) else f for f in reader.fieldnames]
    reader.fieldnames = clean_fieldnames

    items: list[ParsedRawItem] = []
    for idx, row in enumerate(reader, start=1):
        # Serialize raw row to json
        row_str = json.dumps(row, sort_keys=True, ensure_ascii=False)
        if len(row_str.encode("utf-8")) > max_row_size:
            raise InvalidFileFormatError(
                f"Row {idx} exceeds maximum row size of {max_row_size} bytes"
            )

        item_hash = compute_text_sha256(row_str)
        items.append(
            ParsedRawItem(
                row_locator=f"row:{idx}",
                sha256_hash=item_hash,
                raw_payload=row,
                raw_str=row_str,
            )
        )

    return items


def parse_json_content(
    content_bytes: bytes, max_row_size: int = MAX_ROW_SIZE
) -> list[ParsedRawItem]:
    try:
        text = content_bytes.decode("utf-8-sig")
    except UnicodeDecodeError as e:
        raise InvalidFileFormatError(f"Cannot decode JSON file as UTF-8: {e}")

    stripped = text.strip()
    if not stripped:
        return []

    items: list[ParsedRawItem] = []

    if stripped.startswith("["):
        # JSON Array
        try:
            data = json.loads(stripped)
        except json.JSONDecodeError as e:
            raise InvalidFileFormatError(f"Malformed JSON document: {e}")

        if not isinstance(data, list):
            raise InvalidFileFormatError("Root JSON structure must be a list of records")

        for idx, entry in enumerate(data):
            if not isinstance(entry, dict):
                raise InvalidFileFormatError(f"Element at index {idx} is not a JSON object")
            entry_str = json.dumps(entry, sort_keys=True, ensure_ascii=False)
            if len(entry_str.encode("utf-8")) > max_row_size:
                raise InvalidFileFormatError(
                    f"Element at index {idx} exceeds maximum row size of {max_row_size} bytes"
                )
            items.append(
                ParsedRawItem(
                    row_locator=f"index:{idx}",
                    sha256_hash=compute_text_sha256(entry_str),
                    raw_payload=entry,
                    raw_str=entry_str,
                )
            )
    else:
        # Check if NDJSON (newline-delimited JSON)
        lines = stripped.splitlines()
        for idx, line in enumerate(lines, start=1):
            line_str = line.strip()
            if not line_str:
                continue
            if len(line_str.encode("utf-8")) > max_row_size:
                raise InvalidFileFormatError(
                    f"Line {idx} exceeds maximum row size of {max_row_size} bytes"
                )
            try:
                entry = json.loads(line_str)
            except json.JSONDecodeError as e:
                raise InvalidFileFormatError(f"Malformed JSON at line {idx}: {e}")

            if not isinstance(entry, dict):
                raise InvalidFileFormatError(f"Line {idx} is not a JSON object")

            norm_entry_str = json.dumps(entry, sort_keys=True, ensure_ascii=False)
            items.append(
                ParsedRawItem(
                    row_locator=f"line:{idx}",
                    sha256_hash=compute_text_sha256(norm_entry_str),
                    raw_payload=entry,
                    raw_str=norm_entry_str,
                )
            )

    return items


def parse_source_file(
    content_bytes: bytes,
    filename: str,
    max_upload_size: int = MAX_UPLOAD_SIZE,
    max_row_size: int = MAX_ROW_SIZE,
) -> tuple[str, list[ParsedRawItem]]:
    if len(content_bytes) > max_upload_size:
        raise FileTooLargeError(
            f"File size {len(content_bytes)} bytes exceeds limit of {max_upload_size} bytes"
        )

    file_sha256 = compute_bytes_sha256(content_bytes)
    lower_name = filename.lower()

    if lower_name.endswith(".csv"):
        items = parse_csv_content(content_bytes, max_row_size=max_row_size)
    elif (
        lower_name.endswith(".json")
        or lower_name.endswith(".jsonl")
        or lower_name.endswith(".ndjson")
    ):
        items = parse_json_content(content_bytes, max_row_size=max_row_size)
    else:
        # Try JSON first, then CSV
        try:
            items = parse_json_content(content_bytes, max_row_size=max_row_size)
        except Exception:
            try:
                items = parse_csv_content(content_bytes, max_row_size=max_row_size)
            except Exception:
                raise InvalidFileFormatError(
                    f"Unsupported file format for '{filename}'. Only CSV and JSON/NDJSON are supported."
                )

    return file_sha256, items
