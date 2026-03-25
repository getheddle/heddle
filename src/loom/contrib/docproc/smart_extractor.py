"""
Smart document extraction backend with MarkItDown-first, Docling fallback.

Tries Microsoft MarkItDown first (fast, no ML models) and evaluates the
extraction quality.  Falls back to IBM Docling (slower, ML-powered) only
when MarkItDown produces insufficient results — typically scanned PDFs
that need OCR, or documents where very little text was extracted.

Fallback is triggered when:
    1. MarkItDown raises an error.
    2. Extracted text is shorter than ``min_text_length`` (default: 50
       characters), suggesting a scanned or image-heavy document.
    3. The file extension is in ``force_docling_extensions`` (default:
       empty), allowing explicit per-format routing.

Produces the same output schema as DoclingBackend and MarkItDownBackend
so downstream pipeline stages work unchanged.

Configuration (via backend_config in worker YAML):
    workspace_dir:             str  — shared workspace path
    min_text_length:           int  — fallback threshold (default: 50)
    force_docling_extensions:  list — always use Docling for these (e.g., [".tiff"])

See Also:
    loom.contrib.docproc.markitdown_backend.MarkItDownBackend -- fast path
    loom.contrib.docproc.docling_backend.DoclingBackend -- fallback path
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from loom.contrib.docproc.docling_backend import DoclingBackend
from loom.contrib.docproc.markitdown_backend import MarkItDownBackend
from loom.worker.processor import SyncProcessingBackend

logger = logging.getLogger(__name__)

# Default minimum text length to accept a MarkItDown extraction.
_DEFAULT_MIN_TEXT_LENGTH = 50


class SmartExtractorBackend(SyncProcessingBackend):
    """Composite extraction backend: MarkItDown-first, Docling fallback.

    Optimises for speed by using MarkItDown for the common case of
    well-structured digital documents, and only loading the heavy Docling
    pipeline (torch, OCR models) when the fast path proves insufficient.

    Both inner backends are created lazily on first use so importing this
    module does not pull in torch or markitdown.
    """

    def __init__(self, workspace_dir: str = "/tmp/docproc-workspace") -> None:
        self.workspace_dir = workspace_dir
        self._markitdown: MarkItDownBackend | None = None
        self._docling: DoclingBackend | None = None

    @property
    def markitdown(self) -> MarkItDownBackend:
        """Lazy-init MarkItDownBackend."""
        if self._markitdown is None:
            self._markitdown = MarkItDownBackend(workspace_dir=self.workspace_dir)
        return self._markitdown

    @property
    def docling(self) -> DoclingBackend:
        """Lazy-init DoclingBackend."""
        if self._docling is None:
            self._docling = DoclingBackend(workspace_dir=self.workspace_dir)
        return self._docling

    def process_sync(self, payload: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
        """Extract a document, choosing the best backend automatically.

        Args:
            payload: Must contain ``file_ref`` (str).
            config: Backend config dict.  Recognised keys:
                ``min_text_length`` (int), ``force_docling_extensions``
                (list[str]), plus all Docling tuning options.

        Returns:
            ``{"output": {...}, "model_used": "markitdown" | "docling"}``
        """
        file_ref = payload["file_ref"]
        suffix = Path(file_ref).suffix.lower()

        force_docling = config.get("force_docling_extensions", [])
        min_text_length = config.get("min_text_length", _DEFAULT_MIN_TEXT_LENGTH)

        # --- Check if this extension should always use Docling ---
        if suffix in force_docling:
            logger.info(
                "smart_extractor.force_docling",
                extra={
                    "file_ref": file_ref,
                    "reason": f"extension {suffix} in force list",
                },
            )
            return self.docling.process_sync(payload, config)

        # --- Try MarkItDown first ---
        try:
            result = self.markitdown.process_sync(payload, config)
        except Exception:
            logger.info(
                "smart_extractor.markitdown_failed",
                extra={"file_ref": file_ref},
                exc_info=True,
            )
            return self._fallback_to_docling(payload, config, reason="markitdown error")

        # --- Evaluate extraction quality ---
        text_preview = result.get("output", {}).get("text_preview", "")
        if len(text_preview.strip()) < min_text_length:
            text_len = len(text_preview.strip())
            logger.info(
                "smart_extractor.insufficient_text",
                extra={
                    "file_ref": file_ref,
                    "text_length": text_len,
                    "threshold": min_text_length,
                },
            )
            return self._fallback_to_docling(
                payload,
                config,
                reason=f"text too short ({text_len} < {min_text_length})",
            )

        logger.info(
            "smart_extractor.markitdown_accepted",
            extra={
                "file_ref": file_ref,
                "text_length": len(text_preview.strip()),
            },
        )
        return result

    def _fallback_to_docling(
        self,
        payload: dict[str, Any],
        config: dict[str, Any],
        *,
        reason: str,
    ) -> dict[str, Any]:
        """Fall back to DoclingBackend for extraction."""
        logger.info(
            "smart_extractor.fallback_to_docling",
            extra={"file_ref": payload.get("file_ref"), "reason": reason},
        )
        return self.docling.process_sync(payload, config)
