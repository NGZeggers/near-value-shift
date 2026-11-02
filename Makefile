# One command rebuilds everything from raw data: `make all`
# Requires: uv (https://docs.astral.sh/uv/). Google credentials are optional (see docs/SETUP_BIGQUERY.md).
PY := uv run

.PHONY: all build setup fetch bq blocks onchain features models charts thesis site notebook test clean

all: fetch build

build: features models charts thesis site notebook   ## offline rebuild from the committed snapshots (what judges run)

setup:
	uv sync --all-extras

fetch:            ## L0: pull public, key-less sources into data/raw/*.json
	$(PY) near-thesis fetch

bq:               ## L1/L2: run BigQuery SQL (dry-run cost gate first), cache results in data/bigquery/
	$(PY) near-thesis bq

features:         ## derive daily/monthly metric tables into data/derived/
	$(PY) near-thesis features

models:           ## L1 clustering, L3 econometrics, L4 signal tests -> data/derived/models/
	$(PY) near-thesis models

charts:           ## render every chart (SVG) + chart manifest
	$(PY) near-thesis charts

thesis:           ## generate THESIS.md from pipeline outputs (no hand-typed numbers)
	$(PY) near-thesis thesis

site:             ## assemble the static dashboard in site/
	$(PY) near-thesis site

notebook:         ## regenerate notebooks/walkthrough.ipynb and execute it to site/walkthrough.html
	$(PY) python -c "from near_thesis import notebook; notebook.run()"
	$(PY) jupyter nbconvert --to html --execute --ExecutePreprocessor.timeout=600 --output-dir site notebooks/walkthrough.ipynb

blocks:           ## sample full blocks from FastNear (no credentials) for L1/L2 without BigQuery
	$(PY) near-thesis blocks

onchain:          ## dry-run of the on-chain index publication (add SEND=1 to sign; needs keys in .env)
	$(PY) near-thesis onchain $(if $(SEND),--send,)

test:
	$(PY) pytest -q

serve:
	cd site && python3 -m http.server 8080

clean:
	rm -rf data/derived/* site/*.html
