SHELL := /bin/bash
UV ?= uv
VENV := .venv
PY ?= $(VENV)/bin/python

VERSION := $(shell cat VERSION 2>/dev/null || echo 0.0.0)
TAG := $(shell python3 -c "import json;print(json.load(open('upstream.lock.json'))['tag'])" 2>/dev/null)
UPSTREAM_VERSION := $(shell python3 -c "import json;print(json.load(open('upstream.lock.json'))['version'])" 2>/dev/null)

THEME := Cinnamon-Mosaic
DIST := dist
THEME_DIR := $(DIST)/$(THEME)
ARCHIVE := $(DIST)/$(THEME)-$(UPSTREAM_VERSION).tar.xz
VENDOR := vendor/vscode-material-icon-theme

.PHONY: help venv build verify verify-strict check install uninstall install-mime mime-icons dist vendor refresh-maps preview clean clean-env vendor-colloid vendor-check required

COLLOID ?= ../Colloid-icon-theme

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'
	@echo
	@echo "  upstream: $(TAG) (pinned in upstream.lock.json)"
	@echo "  colloid:  $(COLLOID) (pinned in upstream-colloid.lock.json)"
	@echo "  version:  $(VERSION)"
	@echo "  python:   $(PY) $(shell $(PY) -V 2>/dev/null || echo '(run make venv)')"

venv: ## Create or refresh the uv virtualenv (uv sync)
	$(UV) sync -q
	@echo "venv ready: $$($(PY) -V)"

build: venv ## Build the theme into dist/ (Pillow + resvg-py from the uv env)
	$(PY) scripts/build.py

verify: venv ## Validate the built theme (soft coverage check)
	$(PY) scripts/verify.py

verify-strict: venv ## Validate and require full Mint-Y coverage
	$(PY) scripts/verify.py --require-coverage

check: build verify ## Build and validate

dist: build ## Alias of build; produces the release tarball

install: ## Install into ~/.local/share/icons (add --set via ARGS)
	./scripts/install.sh $(ARGS)

uninstall: ## Remove the theme and restore the previous icon theme
	./scripts/uninstall.sh

mime-icons: ## Keep PDF/Markdown on their own icons (user MIME override)
	./scripts/install-mime-icons.sh $(ARGS)

vendor: ## Fetch the pinned upstream checkout into vendor/
	./scripts/fetch-upstream.sh

refresh-maps: venv ## Re-extract mappings/generated-file-map.json from vendor/
	$(PY) scripts/build.py --refresh-maps --upstream $(VENDOR) --dry-run

preview: ## Refresh the committed previews from the last build
	@test -f $(DIST)/preview.png || { echo "run 'make build' first" >&2; exit 1; }
	cp $(DIST)/preview.png docs/preview.png
	cp $(DIST)/ui-preview.png docs/panel-icons.png
	@echo "docs/preview.png and docs/panel-icons.png updated"

vendor-colloid: venv ## Vendor the Colloid system UI artwork and refresh colloid-auto.tsv
	$(PY) tools/vendor-colloid-icons.py --colloid-dir $(COLLOID) --from-required

vendor-check: venv ## Compare assets/colloid + colloid-index.json with the checkout
	$(PY) tools/vendor-colloid-icons.py --colloid-dir $(COLLOID) --check

required: venv ## Refresh mappings/required.tsv from this desktop's icon requests
	$(PY) tools/collect-required.py

clean: ## Remove build/ and dist/
	rm -rf build $(DIST)

clean-env: ## Remove the uv virtualenv (dependencies stay in the uv cache)
	rm -rf $(VENV)
