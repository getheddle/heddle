"""
MarkItDown-based document extraction backend.

Wraps Microsoft MarkItDown to convert PDF, DOCX, PPTX, XLSX, HTML, and
other formats to Markdown.  Much faster than Docling (no ML models, no
torch) but cannot OCR scanned PDFs or extract complex table structures.

This backend produces the same output schema as DoclingBackend so it
can be used as a drop-in replacement in the pipeline.

Input:  {"file_ref": "filename.pdf"}  (relative to workspace_dir)
Output: {"file_ref": "filename_extracted.json", "page_count": N,
         "has_tables": bool, "sections": [...], "text_preview": "..."}

MarkItDown does not provide structural metadata (page count, tables,
sections), so these are derived from the Markdown output:

    page_count  — Estimated from form-feed characters or defaults to 1.
    has_tables  — Detected via Markdown table syntax (| --- |).
    sections    — Parsed from Markdown heading lines (# / ## / ###).

See Also:
    configs/workers/doc_extractor_smart.yaml -- smart extractor config
    docman.backends.smart_extractor -- composite backend with fallback
    loom.worker.processor.SyncProcessingBackend -- base class
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

from loom.core.workspace import WorkspaceManager
from loom.worker.processor import BackendError, SyncProcessingBackend

logger = logging.getLogger(__name__)

# Regex for Markdown table separator rows:  | --- | --- |
_TABLE_SEPARATOR_RE = re.compile(r"^\|[\s:]*-{3,}[\s:]*\|", re.MULTILINE)

# Regex for Markdown headings:  # Title  or  ## Section
_HEADING_RE = re.compile(r"^#{1,6}\s+(.+)$", re.MULTILINE)


class MarkItDownConversionError(BackendError):
    """Raised when MarkItDown fails to convert a document.

    Wraps underlying MarkItDown exceptions with a descriptive message
    and the original cause attached via ``__cause__``.
    """


class MarkItDownBackend(SyncProcessingBackend):
    """SyncProcessingBackend that uses Microsoft MarkItDown for extraction.

    Fast, lightweight document-to-Markdown conversion without ML models.
    Suitable for well-structured digital PDFs, DOCX, PPTX, XLSX, HTML,
    and other text-based formats.  Not suitable for scanned/image-based
    PDFs that require OCR.

    Produces the same output contract as DoclingBackend so downstream
    pipeline stages (classifier, summarizer, ingest) work unchanged.
    """

    def __init__(self, workspace_dir: str = "/tmp/docman-workspace") -> None:
        self.workspace_dir = Path(workspace_dir)

    def process_sync(self, payload: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
        """Extract text from a document using MarkItDown.

        Args:
            payload: Must contain ``file_ref`` (str) -- the filename of the
                source document, relative to the workspace directory.
            config: Worker config dict.  May include ``workspace_dir`` to
                override the constructor default.

        Returns:
            ``{"output": {...}, "model_used": "markitdown"}``

        Raises:
            ValueError: If file_ref attempts path traversal.
            FileNotFoundError: If the source file does not exist.
            MarkItDownConversionError: If MarkItDown fails to convert.
        """
        file_ref = payload["file_ref"]
        ws_dir = config.get("workspace_dir", str(self.workspace_dir))
        ws = WorkspaceManager(ws_dir)

        source_path = ws.resolve(file_ref)

        try:
            result = self._extract(source_path, ws, config)
        except MarkItDownConversionError:
            raise
        except Exception as exc:
            raise MarkItDownConversionError(f"Failed to extract '{file_ref}': {exc}") from exc

        return {"output": result, "model_used": "markitdown"}

    def _extract(
        self, source_path: Path, ws: WorkspaceManager, config: dict[str, Any]
    ) -> dict[str, Any]:
        """Run MarkItDown conversion and derive metadata from the Markdown.

        Args:
            source_path: Absolute, resolved path to the source document.
            ws: WorkspaceManager for writing the extracted JSON.
            config: Backend config dict.

        Returns:
            Dict with file_ref, page_count, has_tables, sections, text_preview.

        Raises:
            MarkItDownConversionError: If conversion or output write fails.
        """
        # Lazy import to avoid pulling in markitdown at module import time.
        try:
            from markitdown import MarkItDown
        except ImportError as exc:
            raise MarkItDownConversionError(
                "markitdown package is not installed. Install with: pip install markitdown"
            ) from exc

        try:
            md = MarkItDown()
            result = md.convert(str(source_path))
            text = result.text_content or ""
        except Exception as exc:
            raise MarkItDownConversionError(
                f"MarkItDown conversion failed for '{source_path.name}': {exc}"
            ) from exc

        # --- Derive structural metadata from Markdown ---
        sections = [m.group(1).strip() for m in _HEADING_RE.finditer(text)]
        has_tables = bool(_TABLE_SEPARATOR_RE.search(text))

        # Page count: MarkItDown doesn't track pages.
        # Use form-feed characters if present (common in PDF→text), else 1.
        ff_count = text.count("\f")
        page_count = max(ff_count, 1)

        # Text preview: first ~500 words.
        words = text.split()
        text_preview = " ".join(words[:500])

        # --- Write full extracted content to workspace ---
        output_name = f"{source_path.stem}_extracted.json"

        extracted = {
            "text": text,
            "sections": sections,
            "has_tables": has_tables,
            "page_count": page_count,
        }
        try:
            ws.write_json(output_name, extracted)
        except OSError as exc:
            raise MarkItDownConversionError(
                f"Failed to write extracted output to '{output_name}': {exc}"
            ) from exc

        logger.info(
            "markitdown.extraction_complete",
            extra={
                "source": source_path.name,
                "output": output_name,
                "page_count": page_count,
                "has_tables": has_tables,
                "section_count": len(sections),
                "text_length": len(text),
            },
        )

        return {
            "file_ref": output_name,
            "page_count": page_count,
            "has_tables": has_tables,
            "sections": sections[:20],
            "text_preview": text_preview,
        }
