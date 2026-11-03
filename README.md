# From clicks to settlement: a reproducible investment thesis on NEAR

Built for NEAR Hackathon 2026, track **Investment Thesis** (`thesis`).

**Question:** do falling account counts obscure a shift toward cross-chain settlement, and does the evidence support a token investment case? The project compares activity, behavioral proxies, Intents flows, net captured fees and forward associations. It reports failed cross-checks and inconclusive statistical tests. Settlement growth alone does not establish undervaluation.

[Dashboard](https://ngzeggers.github.io/near-value-shift/) · [Generated argument](THESIS.md) · [Sampling and limits](docs/SAMPLING.md) · [Audit and corrections](docs/VALIDACION_HACKATHON.md)

## What is implemented

| Layer | Behavior | Code |
|---|---|---|
| L0 | Hashed public snapshots, including gross Intents fees, net captured receipts and buyback-labelled revenue | `near_thesis/fetch.py`, `data/raw/` |
| L1 | Retrospective HDBSCAN; separate frozen past-only GMM for predictive QAA, with next-month availability | `near_thesis/qaa.py` |
| L2 | Multi-participant token-diff flow estimate, zero-event days, observed user counts, heuristic solver sensitivity | `near_thesis/intents.py`, `data/blocks/` |
| L3 | Breaks, correlations, stationarity-gated VAR, stability/residual checks, explicit Johansen ranks | `near_thesis/econ.py` |
| L4 | Forward associations with block-bootstrap and familywise intervals; descriptive peer panel; capture-based scenarios | `near_thesis/signal.py` |
| Output | Generated thesis, static dashboard, executed notebook, complete input hashes, regression tests | `THESIS.md`, `site/`, `tests/` |

QAA labels are behavioral assumptions, not verified human identities. The Intents sample is not a validated total or guaranteed lower bound. Buyback-labelled receipts are not proof of burning or holder dividends. The generated argument names the current consistency-test result and remaining limitations.

## Reproduce: do X, see Y

Requirements: [uv](https://docs.astral.sh/uv/); Python 3.12 is configured by CI. No Google account or wallet keys are needed.

1. `uv sync --all-extras` → installs the locked dependencies.
2. `make build` → rebuilds tables, models, chart data, `THESIS.md`, `site/index.html`, `site/walkthrough.html` and the local index from committed inputs. It uses no external HTTP requests. Jupyter opens localhost ports for its kernel, so environments must permit that. The build reuses matching fitted descriptive assignments and the serialized past-only model. `QAA_REFIT=1 make models` explicitly retrains them.
3. `make test` → runs metric, causal-availability, pricing, solver-mode, freshness, index-verification and regression tests.
4. `make check-generated` → exits successfully with no analytical changes against the committed artifacts. Run this after a build; a changed raw snapshot requires regenerating and committing its outputs.
5. `make serve` → open http://localhost:8080. Each chart provides its source/query, a table view and a short explanation. Theme and date-range controls are available.
6. Open http://localhost:8080/walkthrough.html → see the executed model walkthrough, diagnostics and revenue definitions.

Generated text and source hashes are compared exactly. Numerical arrays allow only `rtol=1e-9`, `atol=1e-11` for machine precision; stale market caps and changed methods still fail the check.

Build time varies by machine; price tables are loaded once and bootstrap correlations are batched. Retraining clustering costs more than a normal cached build. Snapshot acquisition is separate from build time.

## Refreshing data and optional integrations

`make fetch` refreshes public APIs. `make blocks BLOCKS=100` tops up the cached FastNear block plan; acquiring thousands of public blocks can take hours under rate limits. Rebuild afterward. Snapshot acquisition timestamps and complete SHA-256 hashes are generated into `docs/REPRODUCIBILITY.md`.

`make bq` is optional. It checks dataset freshness **before** L1/L2, estimates query size, sets a server-side byte ceiling and limits each run. See `docs/SETUP_BIGQUERY.md`; actual Google query/schema execution is not claimed for the block-sample build. Q0–Q3 auxiliary extracts are available for manual cross-checks; QAA and Intents consume L1/L2 extracts when present.

`make onchain` prints a dry-run NEAR Social payload. `make onchain SEND=1` signs only with an explicitly configured account/key. `make onchain-verify` compares all local index fields against the published record, including hashes. The index is **not claimed published** without a transaction reference. Keys belong only in `.env`, which is ignored.

## NEAR's concrete role

NEAR is both the subject and the evidence layer: FastNear supplies NEAR blocks and receipts, and `intents.near` logs expose settlement activity. NearBlocks supplies daily activity; DefiLlama/Dune supplies reported settlement and revenue-wallet series. NEAR Social publication is an optional stretch. BigQuery, Explorer JWT and a deployed contract are not mandatory integrations for this track.

## Submission

Official rules: [HACKATHON.md](https://nearhackathon.com/HACKATHON.md). Deadline: 14 November 2026, 23:59 UTC. The public repository and an actual demo post on X are both required. `docs/DEMO.md` contains a storyboard and draft; the team supplies identity/contact details, mainnet payout address, demo-post link and consent before reviewing the final submission payload.

## Disclosure and license

Libraries and locked versions: `pyproject.toml` and `uv.lock`. Parts of the original implementation used Claude Code; the correction pass and regression checks used Codex. No pre-existing product is declared reused. This is research software; its statistical and sampling limits are part of the deliverable. MIT; see `LICENSE`.
