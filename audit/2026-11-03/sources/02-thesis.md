# 02. Investment Thesis

**Track id:** `thesis` · **Tagline:** Make the long-term case

Build a long-term investment thesis for NEAR and back it with onchain analytics, live dashboards and models anyone can re-run. The score depends on evidence someone else can reproduce.

**Lean on:** Onchain data, dashboards, research

## Start here

- [NEAR BigQuery public dataset](https://docs.near.org/data-infrastructure/big-query)
- [NEAR data infrastructure overview](https://docs.near.org/data-infrastructure/what-is)
- [NEAR Intents Explorer API](https://docs.near-intents.org/integration/distribution-channels/1click-api/explorer/introduction)

## Prompt

```text
Track: Investment Thesis (id: thesis).

Help me build an evidence-first thesis on NEAR. My working hypothesis: [cross-chain volume through NEAR Intents is a better leading indicator of real network usage than token price]. Your job is to test it and report what the data says, including anything that cuts against me.

Build:
- SQL queries against the NEAR BigQuery public dataset (bigquery-public-data.crypto_near_mainnet_us) for daily active accounts, transaction counts and contract usage. Always filter on block_date to keep query costs down.
- A pull from the NEAR Intents Explorer API for swap volume. It needs a JWT from the partner dashboard; I'll put it in .env.
- One command that rebuilds every chart from raw data.
- A static dashboard page: each chart, the query behind it, and one plain sentence on what it shows.
- THESIS.md with the claim, the evidence for it, the evidence against it, and what result would change my mind.

Never invent numbers. If a metric can't be computed from these sources, write that in THESIS.md. Start by listing the tables you plan to use plus one sample query, then wait.
```

## Note

NEAR pays to store the BigQuery dataset, but you pay normal BigQuery costs for the queries you run. Filtering on `block_date` keeps the bill small.
