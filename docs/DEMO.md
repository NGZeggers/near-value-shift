# Demo storyboard and X draft

## Two-minute storyboard

1. Problem: "NEAR's account counts and cross-chain settlement tell different stories. Which claims survive a reproducible test?"
2. Run `uv sync --all-extras`, `make build`, `make test`; show the generated files and passing test count.
3. Open the dashboard; compare account activity, Intents volume and the separate gross-fee/net-revenue/buyback-labelled series. Open Source and query.
4. Show the on-chain/reference reconciliation when verified data exists, or the explicit unavailable status until receipt revalidation completes. Explain that fixed windows cannot validate full-market totals by themselves.
5. Show retrospective QAA next to the past-only model's training end and release dates. Labels describe behavior, not verified humans.
6. Show statistical diagnostics, exploratory IC and the generated current verdict. Emphasize the evidence against the claim as well as the descriptive shift.
7. Close with NEAR's concrete role: its blocks, receipt logs and Intents events are the evidence. BigQuery and the on-chain index are optional paths, not claimed deployed results.

A hosted demo plus screenshots is allowed. If only a local demo is available, record video: the official rule says screenshots alone are insufficient in that case. The human publishes the demo on X.

## Draft

Built at NEAR HACKATHON: From clicks to settlement.

Do falling account counts tell the whole story of @NEARProtocol? We built a reproducible thesis comparing raw activity, behavioral proxies, Intents settlement and net fee capture—with past-only features, statistical diagnostics and the evidence against our own hypothesis.

Repo: https://github.com/NGZeggers/near-value-shift
Dashboard: https://ngzeggers.github.io/near-value-shift/

Every chart has its source. One command rebuilds the results. Demo attached. #NEARHackathon

## Final submission information still supplied by the team

Project and lead names, contact email, team-size category, mainnet payout account, actual X demo-post URL, and agreement to the official contact notice. Never put keys or personal submission payloads in Git. The final payload must be reviewed before it is submitted; a submission cannot be edited afterward.
