"""Pydantic I/O contracts for document processing.

These models define the typed input/output schema shared by all extraction
backends (Docling, MarkItDown, SmartExtractor).  Worker YAML configs can
reference them via ``input_schema_ref`` / ``output_schema_ref``.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class ExtractorInput(BaseModel):
    """Input for document extraction backends."""

    file_ref: str = Field(..., description="Filename relative to workspace directory")


class ExtractorOutput(BaseModel):
    """Output from document extraction (shared by all backends)."""

    file_ref: str = Field(..., description="Filename of extracted JSON in workspace")
    page_count: int = Field(..., description="Number of pages detected")
    has_tables: bool = Field(..., description="Whether tables were found")
    sections: list[str] = Field(..., description="Section headers found in document (max 20)")
    text_preview: str = Field(..., description="First ~500 words of extracted text")
