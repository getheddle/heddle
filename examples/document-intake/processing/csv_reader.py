"""
CSV Reader — Custom ProcessingBackend for the Document Intake example.

Reads a CSV file and yields individual rows as structured records.
This demonstrates how to write a custom non-LLM processing backend
for Loom — any Python code that transforms data can be a backend.

The process_sync() method runs in a thread pool automatically (via
SyncProcessingBackend), so it won't block the async event loop even
with large files.

Usage:
    # In a worker config (YAML):
    worker_kind: "processor"
    processing_backend: "examples.document_intake.processing.csv_reader.CsvReaderBackend"

Tutorial: docs/tutorials/document-intake.md (Phase 2)
"""

from __future__ import annotations

import csv
import io
from pathlib import Path
from typing import Any

from loom.worker.processor import BackendError, SyncProcessingBackend


class CsvReadError(BackendError):
    """Raised when CSV reading or parsing fails."""


class CsvReaderBackend(SyncProcessingBackend):
    """Read a CSV file and return rows as structured records.

    Input payload:
        source_path (str): Path to the CSV file.
        text_column (str): Name of the column containing the text to process.
        id_column (str, optional): Column to use as record ID. Default: "id".
        max_rows (int, optional): Maximum rows to read. Default: all.

    Output:
        records (list[dict]): Each row as a dict with all CSV columns.
        total_count (int): Number of records returned.
        columns (list[str]): Column names found in the CSV.
    """

    def process_sync(self, payload: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
        source_path = payload.get("source_path")
        text_column = payload.get("text_column")
        id_column = payload.get("id_column", "id")
        max_rows = payload.get("max_rows")

        if not source_path:
            raise CsvReadError("source_path is required")
        if not text_column:
            raise CsvReadError("text_column is required")

        path = Path(source_path)
        if not path.exists():
            raise CsvReadError(f"File not found: {source_path}")
        if not path.suffix.lower() == ".csv":
            raise CsvReadError(f"Expected .csv file, got: {path.suffix}")

        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            # Fall back to latin-1 for files with non-UTF-8 characters
            try:
                content = path.read_text(encoding="latin-1")
            except Exception as exc:
                raise CsvReadError(f"Cannot read file: {exc}") from exc

        try:
            reader = csv.DictReader(io.StringIO(content))
            columns = reader.fieldnames or []

            if text_column not in columns:
                raise CsvReadError(
                    f"Column '{text_column}' not found. "
                    f"Available columns: {columns}"
                )

            records = []
            for i, row in enumerate(reader):
                if max_rows and i >= max_rows:
                    break
                # Skip rows where the text column is empty
                if not row.get(text_column, "").strip():
                    continue
                records.append(dict(row))

        except CsvReadError:
            raise
        except Exception as exc:
            raise CsvReadError(f"CSV parsing failed: {exc}") from exc

        return {
            "output": {
                "records": records,
                "total_count": len(records),
                "columns": list(columns),
            },
            "model_used": "csv-reader",
        }
