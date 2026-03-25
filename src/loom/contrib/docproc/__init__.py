"""Document processing backends for Loom.

Provides three document extraction backends (all producing the same output
contract) and Pydantic I/O models for document processing pipelines:

- :class:`MarkItDownBackend` — fast, lightweight (no ML models)
- :class:`DoclingBackend` — deep extraction with OCR and table analysis
- :class:`SmartExtractorBackend` — MarkItDown-first with Docling fallback

Install::

    uv sync --extra docproc      # Docling (requires torch)
    pip install markitdown        # MarkItDown (lightweight, no torch)
"""

from loom.contrib.docproc.contracts import ExtractorInput, ExtractorOutput

__all__ = ["ExtractorInput", "ExtractorOutput"]
