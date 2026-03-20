"""Sphinx configuration for Loom API documentation."""

project = "Loom"
copyright = "2024, Loom Contributors"
author = "Loom Contributors"
release = "0.4.0"

# -- Extensions ---------------------------------------------------------------

extensions = [
    "myst_parser",          # Markdown source support
    "autodoc2",             # AST-based autodoc (no imports needed)
    "sphinx.ext.viewcode",  # Add [source] links to generated docs
    "sphinx.ext.intersphinx",
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

# -- autodoc2 settings --------------------------------------------------------
# AST-based: parses source files without importing them.
# This means docs build without NATS, Redis, Ollama, or any other infra.

autodoc2_packages = [
    {
        "path": "../src/loom",
        "module": "loom",
        "exclude_dirs": ["__pycache__"],
    },
]

autodoc2_render_plugin = "myst"
autodoc2_hidden_objects = ["private", "dunder"]
autodoc2_module_all_regexes = []  # Don't require __all__; document all public names

# -- Theme --------------------------------------------------------------------

html_theme = "sphinx_rtd_theme"
html_theme_options = {
    "navigation_depth": 4,
    "collapse_navigation": False,
    "sticky_navigation": True,
    "style_external_links": True,
}

html_static_path = []
templates_path = []

# -- Intersphinx (cross-link to Python docs) ----------------------------------

intersphinx_mapping = {
    "python": ("https://docs.python.org/3", None),
    "pydantic": ("https://docs.pydantic.dev/latest/", None),
}

# -- General ------------------------------------------------------------------

exclude_patterns = ["_build", "api/.autodoc2"]
html_title = "Loom Documentation"
html_short_title = "Loom"
