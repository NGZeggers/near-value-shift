# Demo script (video, 2-3 minutes) and X post draft

## Video storyboard
1. (0:00) The user problem, one sentence: "NEAR's headline activity fell 90%. Is the network dying, or are we reading the wrong metric?"
2. (0:15) Terminal: `git clone ... && uv sync --all-extras && make features models charts thesis site test`. Show the pipeline finishing and `3+ tests passed`.
3. (0:45) Open `site/index.html`. Hero: Intents monthly volume. KPI row. Toggle range "Since Intents" and dark mode.
4. (1:10) Section 1 vs Section 2: active accounts down, Intents volume up, USD per transaction up. Hover a chart: crosshair tooltip. Open "Source and query".
5. (1:40) Section 4: the honest part. Rolling correlation chart, Granger table, the negative information coefficient for Intents volume. "The data does not say usage leads price."
6. (2:05) Section 3: QAA clustering and solver concentration from raw on-chain events (BigQuery). Show one SQL file and the cluster profile table.
7. (2:30) THESIS.md: claim, for, against, what would change our mind. "Every number is generated; nothing is typed by hand."
8. (2:50) What NEAR does in the product: the public BigQuery dataset, NEAR RPC and the Intents contract events are the data layer; the thesis is about NEAR itself.

## X post draft (to be posted by a human; tag @NEARProtocol and #NEARHackathon)
Built at NEAR HACKATHON: "From clicks to settlement", a reproducible investment thesis on @NEARProtocol.

NEAR's active accounts fell ~90% from the 2024 peak. Intents volume went from $3M/month to ~$4B/month. We asked which metric the market should price, and tested it: structural breaks, Granger/VAR, cointegration, forward-return signals, and behavioral clustering of accounts from the public BigQuery dataset.

Every chart shows its query. Every number in THESIS.md is generated. One command rebuilds it all.

Repo: <link> · Dashboard: <link> · Video below. #NEARHackathon
