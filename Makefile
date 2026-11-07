# One command rebuilds everything from raw data: `make all`
# Requires: uv (https://docs.astral.sh/uv/). Google credentials are optional (see docs/SETUP_BIGQUERY.md).
PY := uv run

BLOCKS ?= 50   # blocks per sampling window for `make blocks` (budget: ~0.35 blocks/s)
.PHONY: all build setup fetch bq blocks blocks-intraday blocks-intraday-validation blocks-buyback-trace oos-freeze onchain onchain-verify features models charts thesis site notebook index check-generated test clean
.NOTPARALLEL:

all: fetch build

build: features models charts thesis site notebook index   ## offline rebuild from committed inputs

setup:
	uv sync --locked --all-extras

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

index:            ## local index only; no RPC call, signing or keys
	$(PY) python -c "import json; from near_thesis.onchain import payload; from near_thesis.config import DERIVED; (DERIVED / 'onchain_index.json').write_text(json.dumps(payload(), indent=1))"

check-generated:  ## run after build: analytical results must match the committed snapshots
	$(PY) python -m near_thesis.check_generated

blocks:           ## sample full blocks from FastNear (no credentials) for L1/L2 without BigQuery
	$(PY) near-thesis blocks --blocks $(BLOCKS)

onchain:          ## dry-run of the on-chain index publication (add SEND=1 to sign; needs keys in .env)
ifneq ($(strip $(SEND)),)
ifneq ($(strip $(SEND)),0)
ifneq ($(strip $(SEND)),1)
	$(error SEND must be empty, 0 or 1)
endif
endif
endif
	$(PY) near-thesis onchain $(if $(filter 1,$(strip $(SEND))),--send,)

blocks-intraday:  ## hourly windows for the pre-declared reconciliation days (network; resumable through the block cache)
	$(PY) near-thesis blocks-intraday --days 2026-09-25 2026-04-13 2025-08-31 --blocks $(BLOCKS)

blocks-intraday-validation:  ## hourly windows for the pre-declared validation days (selection by position; network; resumable)
	$(PY) near-thesis blocks-intraday --validation --blocks $(BLOCKS)

blocks-buyback-trace:  ## execution blocks of a pre-declared sample of buyback-wallet receipts (network; ~50 blocks)
	$(PY) near-thesis blocks-buyback-trace

oos-freeze:       ## persist the prospective out-of-sample plan once (refuses to overwrite; FORCE=1 to replace deliberately)
	$(PY) near-thesis oos-freeze $(if $(filter 1,$(strip $(FORCE))),--force,)

verify-events:    ## verify historical event statuses from full blocks (resumable; network required)
	$(PY) near-thesis verify-events

onchain-verify:   ## read the published index back from NEAR Social and compare its THESIS.md hash with this checkout
	$(PY) near-thesis onchain --verify

test:
	$(PY) pytest -q

serve:
	cd site && python3 -m http.server 8080

clean:
	rm -rf data/derived/* site/*.html
