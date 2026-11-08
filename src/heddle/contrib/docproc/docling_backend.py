"""
Docling-based document extraction backend.

Wraps IBM Docling to extract text, tables, and structure from PDF/DOCX files.
Extends SyncProcessingBackend so the synchronous Docling work is automatically
offloaded to a thread pool, keeping the async event loop responsive.

This is the first stage in DocMan's document processing pipeline:
    doc_extractor (this) -> doc_classifier -> doc_summarizer

Input:  {"file_ref": "filename.pdf"}  (relative to workspace_dir)
Output: {"file_ref": "filename_extracted.json", "page_count": N,
         "has_tables": bool, "sections": [...], "text_preview": "..."}

The extracted JSON is written to workspace_dir and contains the full
document text. Subsequent stages reference it via file_ref to avoid
passing large text through NATS messages.

Docling tuning options can be passed via backend_config in the worker YAML:
    device:            "mps" | "cpu" | "cuda" | "auto" (default: "auto")
    num_threads:       int (default: 8 on Apple Silicon, 4 elsewhere)
    ocr_engine:        "auto" | "ocrmac" | "rapidocr" | "easyocr" | "tesseract"
                       (default: "auto" -- Docling picks the first installed
                       engine; the docproc extra ships RapidOCR)
    layout_batch_size: int (default: 4)
    ocr_batch_size:    int (default: 4)
    do_ocr:            bool (default: true)
    do_table_structure: bool (default: true)

See Also:
    configs/workers/doc_extractor.yaml -- worker config with I/O schemas
    docs/workers-reference.md -- DoclingBackend configuration options
    heddle.worker.processor.SyncProcessingBackend -- base class for sync backends
    heddle.core.workspace.WorkspaceManager -- file-ref resolution with path safety
"""

from __future__ import annotations

import logging
import platform
from pathlib import Path
from typing import Any

from heddle.core.workspace import WorkspaceManager
from heddle.worker.processor import BackendError, SyncProcessingBackend

logger = logging.getLogger(__name__)

#: Accepted ``ocr_engine`` values. "auto" lets Docling choose the first engine
#: that is installed (OcrMac on macOS, then RapidOCR / EasyOCR); the others pin
#: one engine, which must then be installed. Tesseract is never auto-selected.
OCR_ENGINES = ("auto", "ocrmac", "rapidocr", "easyocr", "tesseract")


class DoclingConversionError(BackendError):
    """Raised when Docling fails to convert a document.

    Wraps underlying Docling exceptions (corrupt PDFs, unsupported formats,
    out-of-memory conditions) with a descriptive message and the original
    cause attached via ``__cause__``.
    """


class DoclingBackend(SyncProcessingBackend):
    """SyncProcessingBackend that uses IBM Docling for document extraction.

    Reads a source document (PDF or DOCX) from the workspace directory,
    runs Docling's DocumentConverter to extract text, tables, and structural
    metadata, then writes the full extracted content as JSON back to the
    workspace. Returns a lightweight summary (file_ref, page_count,
    has_tables, sections, text_preview) suitable for passing through NATS
    messages to downstream pipeline stages.

    Because Docling is synchronous and CPU-bound, this backend extends
    SyncProcessingBackend which automatically offloads process_sync()
    to a thread pool via run_in_executor.

    Attributes:
        workspace_dir: Default workspace path. Can be overridden per-call
            via the ``workspace_dir`` key in the config dict.
    """

    def __init__(self, workspace_dir: str = "/tmp/docman-workspace") -> None:
        self.workspace_dir = Path(workspace_dir)

    def process_sync(self, payload: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
        """Extract text and structure from a document using Docling.

        Validates the input file_ref for path traversal and existence, then
        runs Docling's DocumentConverter synchronously (the parent class
        handles thread pool offloading).

        Args:
            payload: Must contain ``file_ref`` (str) -- the filename of the
                source document, relative to the workspace directory.
            config: Worker config dict (from the YAML's ``backend_config``
                section). May include ``workspace_dir`` to override the
                constructor default, plus Docling tuning options such as
                ``device``, ``ocr_engine``, ``num_threads``, etc.

        Returns:
            A dict with ``"output"`` (the extraction result dict) and
            ``"model_used"`` (always ``"docling"``). The ProcessorWorker
            unpacks this and publishes the TaskResult to NATS.

        Raises:
            ValueError: If file_ref attempts to escape the workspace
                directory (path traversal attack).
            FileNotFoundError: If the source file does not exist in the
                workspace.
            DoclingConversionError: If Docling fails to convert the
                document (corrupt file, unsupported format, OOM, etc.).
        """
        file_ref = payload["file_ref"]
        ws_dir = config.get("workspace_dir", str(self.workspace_dir))
        ws = WorkspaceManager(ws_dir)

        # Validate path traversal and existence via WorkspaceManager.
        source_path = ws.resolve(file_ref)

        try:
            result = self._extract(source_path, ws, config)
        except DoclingConversionError:
            raise
        except Exception as exc:
            raise DoclingConversionError(f"Failed to extract '{file_ref}': {exc}") from exc

        return {"output": result, "model_used": "docling"}

    def _build_converter(self, config: dict[str, Any]) -> Any:  # pragma: no cover
        """Build a Docling DocumentConverter with settings from backend_config.

        Constructs the converter with accelerator, OCR, and table structure
        options pulled from the config dict. Defaults: ``device="auto"``,
        ``ocr_engine="auto"``, 8 threads on Apple Silicon (4 elsewhere).

        Docling imports are done lazily here to avoid pulling in torch and
        torchvision at module import time.

        Args:
            config: Backend config dict from the worker YAML. Recognised keys:
                ``device``, ``num_threads``, ``do_ocr``, ``ocr_engine``,
                ``do_table_structure``, ``layout_batch_size``, ``ocr_batch_size``.

        Returns:
            A configured ``docling.document_converter.DocumentConverter``
            instance ready to process PDF and DOCX files.

        Raises:
            ValueError: If ``ocr_engine`` is not one of :data:`OCR_ENGINES`.

        See Also:
            docs/workers-reference.md -- DoclingBackend configuration options.
        """
        from docling.datamodel.base_models import InputFormat
        from docling.datamodel.pipeline_options import (
            AcceleratorOptions,
            PdfPipelineOptions,
            TableStructureOptions,
        )
        from docling.document_converter import DocumentConverter, PdfFormatOption

        # --- Accelerator options ---
        device = config.get("device", "auto")
        num_threads = config.get("num_threads", 8 if platform.machine() == "arm64" else 4)

        accel = AcceleratorOptions(
            device=device,
            num_threads=num_threads,
        )

        # --- OCR options ---
        do_ocr = config.get("do_ocr", True)
        ocr_options = _ocr_options(config.get("ocr_engine", "auto")) if do_ocr else None

        # --- Table structure ---
        do_table_structure = config.get("do_table_structure", True)
        table_options = TableStructureOptions(do_cell_matching=True) if do_table_structure else None

        # --- Pipeline options ---
        pipeline_kwargs = {
            "accelerator_options": accel,
            "do_ocr": do_ocr,
            "do_table_structure": do_table_structure,
            "layout_batch_size": config.get("layout_batch_size", 4),
            "ocr_batch_size": config.get("ocr_batch_size", 4),
        }
        if ocr_options:
            pipeline_kwargs["ocr_options"] = ocr_options
        if table_options:
            pipeline_kwargs["table_structure_options"] = table_options

        pipeline_options = PdfPipelineOptions(**pipeline_kwargs)

        return DocumentConverter(
            allowed_formats=[InputFormat.PDF, InputFormat.DOCX],
            format_options={
                InputFormat.PDF: PdfFormatOption(
                    pipeline_options=pipeline_options,
                ),
            },
        )

    def _extract(  # pragma: no cover
        self, source_path: Path, ws: WorkspaceManager, config: dict[str, Any]
    ) -> dict[str, Any]:
        """Run synchronous Docling extraction.

        Docling and its heavy dependencies (torch, torchvision) are imported
        lazily inside ``_build_converter`` to avoid loading them at module
        import time -- this keeps ``import docman`` fast.

        Args:
            source_path: Absolute, resolved path to the source document.
            ws: WorkspaceManager for writing the extracted JSON.
            config: Backend config dict from the worker YAML -- supplies
                Docling tuning options (device, OCR engine, batch sizes).

        Returns:
            A dict containing:
                - ``file_ref``: Filename of the extracted JSON in workspace.
                - ``page_count``: Number of pages detected.
                - ``has_tables``: Whether any tables were found.
                - ``sections``: Up to 20 section/title headers.
                - ``text_preview``: First ~500 words for downstream preview.

        Raises:
            DoclingConversionError: If Docling conversion or the output
                write fails (corrupt file, disk full, permissions, etc.).
        """
        # --- Convert document ---
        try:
            converter = self._build_converter(config)
            doc_result = converter.convert(str(source_path))
            doc = doc_result.document
        except Exception as exc:
            raise DoclingConversionError(
                f"Docling conversion failed for '{source_path.name}': {exc}"
            ) from exc

        # --- Extract text content as Markdown ---
        text = doc.export_to_markdown()

        # --- Gather structural metadata ---
        sections, has_tables, page_count = summarize_document(doc)

        # Text preview: first ~500 words, included inline in the NATS message
        # so the classifier stage can work without reading the full JSON.
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
            raise DoclingConversionError(
                f"Failed to write extracted output to '{output_name}': {exc}"
            ) from exc

        logger.info(
            "docling.extraction_complete",
            extra={
                "source": source_path.name,
                "output": output_name,
                "page_count": page_count,
                "has_tables": has_tables,
                "section_count": len(sections),
            },
        )

        return {
            "file_ref": output_name,
            "page_count": page_count,
            "has_tables": has_tables,
            "sections": sections[:20],  # Cap at 20 to keep NATS messages small.
            "text_preview": text_preview,
        }


def _ocr_options(engine: str) -> Any:
    """Return the Docling OCR options object for an ``ocr_engine`` value.

    Docling is imported lazily, as in ``_build_converter``.

    Args:
        engine: One of :data:`OCR_ENGINES`.

    Returns:
        A ``docling.datamodel.pipeline_options.OcrOptions`` subclass instance.

    Raises:
        ValueError: If ``engine`` is not one of :data:`OCR_ENGINES`. An unknown
            name used to fall through silently to Docling's own default.
    """
    from docling.datamodel import pipeline_options as po

    if engine == "auto":
        return po.OcrAutoOptions()
    if engine == "ocrmac":
        return po.OcrMacOptions(recognition="accurate")
    if engine == "rapidocr":
        return po.RapidOcrOptions()
    if engine == "easyocr":
        return po.EasyOcrOptions()
    if engine == "tesseract":
        return po.TesseractOcrOptions()
    raise ValueError(f"unknown ocr_engine {engine!r}; expected one of {', '.join(OCR_ENGINES)}")


def summarize_document(doc: Any) -> tuple[list[str], bool, int]:
    """Collect section headings, table presence, and page count from a document.

    Args:
        doc: A ``docling_core`` ``DoclingDocument``.

    Returns:
        ``(sections, has_tables, page_count)``. ``sections`` holds the text of
        every title and section header in reading order (uncapped).
        ``page_count`` is the number of laid-out pages, or 1 for formats
        Docling does not paginate (DOCX, HTML, Markdown), matching the
        MarkItDown backend's floor of 1.
    """
    sections: list[str] = []
    has_tables = False
    # iterate_items() yields (item, level) pairs, not bare items.
    for item, _level in doc.iterate_items():
        label = getattr(item, "label", None)
        if label in ("title", "section_header"):
            sections.append(getattr(item, "text", "") or "")
        elif label == "table":
            has_tables = True
    page_count = len(doc.pages) or 1
    return sections, has_tables, page_count
