"""Sphinx configuration for Loom API documentation."""

import os
import sys

# -- Path setup ---------------------------------------------------------------
# Add src/ to sys.path so autodoc can import loom modules.
sys.path.insert(0, os.path.abspath("../src"))

project = "Loom"
copyright = "2024, Loom Contributors"
author = "Loom Contributors"
release = "0.8.0"

# -- Extensions ---------------------------------------------------------------

extensions = [
    "sphinx.ext.autodoc",
    "sphinx.ext.napoleon",       # Google/NumPy docstring support
    "sphinx.ext.viewcode",       # Source code links
    "sphinx.ext.intersphinx",    # Cross-project links
    "myst_parser",               # Markdown support for existing .md docs
]

# -- MyST (Markdown) settings -------------------------------------------------

myst_enable_extensions = [
    "colon_fence",      # ::: directives
    "fieldlist",        # :param x: style
    "deflist",          # definition lists
]

# Recognize both .md and .rst
source_suffix = {
    ".rst": "restructuredtext",
    ".md": "markdown",
}

# -- Autodoc settings ---------------------------------------------------------

autodoc_default_options = {
    "members": True,
    "undoc-members": False,
    "show-inheritance": True,
    "member-order": "bysource",
}
autodoc_typehints = "signature"

# Mock imports for optional dependencies that may not be installed during
# docs build.  This prevents ImportError when autodoc tries to import modules
# that depend on these packages.
autodoc_mock_imports = [
    "nats",
    "redis",
    "ollama",
    "duckdb",
    "croniter",
    "mcp",
    "fastapi",
    "uvicorn",
    "jinja2",
    "starlette",
    "multipart",
    "zeroconf",
    "opentelemetry",
    "textual",
    "deepeval",
    "docling",
    "tiktoken",
    "httpx",
    "click",
    "structlog",
    "pydantic",
    "yaml",
    "pydantic_settings",
]

# -- Napoleon settings (Google-style docstrings) ------------------------------

napoleon_google_docstrings = True
napoleon_numpy_docstrings = True

# -- Intersphinx (cross-link to Python docs) ----------------------------------

intersphinx_mapping = {
    "python": ("https://docs.python.org/3", None),
    "pydantic": ("https://docs.pydantic.dev/latest/", None),
}

# -- Theme --------------------------------------------------------------------

html_theme = "furo"
html_theme_options = {
    "source_repository": "https://github.com/IranTransitionProject/loom",
    "source_branch": "main",
    "source_directory": "docs/",
}

html_static_path = []
templates_path = []

# -- General ------------------------------------------------------------------

exclude_patterns = ["_build"]
html_title = "Loom Documentation"
html_short_title = "Loom"

# Suppress warnings that are expected and non-critical:
# - "duplicate object description" from autodoc processing dataclass attributes
#   that appear in both module-level and class-level documentation
# - myst cross-reference warnings for internal markdown anchor links
suppress_warnings = [
    "myst.xref_missing",
]

# Filter out duplicate object warnings from dataclass attributes.
# Sphinx's autodoc + napoleon generate attribute entries from BOTH the
# ``Attributes:`` docstring section AND the class body annotations,
# producing harmless duplicates that can't be suppressed via
# suppress_warnings.
import logging as _logging
import warnings as _warnings


class _SphinxWarningFilter(_logging.Filter):
    """Filter out known harmless Sphinx warnings that can't be suppressed."""

    _SUPPRESSED = (
        "duplicate object description",
        "Failed to get a method signature for",
    )

    def filter(self, record: _logging.LogRecord) -> bool:
        msg = record.getMessage()
        return not any(s in msg for s in self._SUPPRESSED)


for _logger_name in (
    "sphinx.sphinx.domains.python",
    "sphinx.sphinx.ext.autodoc",
):
    _logging.getLogger(_logger_name).addFilter(_SphinxWarningFilter())
