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
    "sphinx.ext.autosummary",
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
autodoc_typehints = "description"

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
