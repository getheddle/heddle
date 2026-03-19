# Sphinx documentation Makefile
SPHINXBUILD   ?= uv run sphinx-build
SOURCEDIR     = .
BUILDDIR      = _build

.PHONY: help html clean

help:
	@echo "  html    Build HTML documentation"
	@echo "  clean   Remove built documentation"

html:
	$(SPHINXBUILD) -b html "$(SOURCEDIR)" "$(BUILDDIR)/html"
	@echo "Build finished. Open $(BUILDDIR)/html/index.html to view."

clean:
	rm -rf "$(BUILDDIR)"
