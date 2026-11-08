# Demo storyboard and X draft

## Two-minute storyboard

1. Problem: "NEAR's account counts and cross-chain settlement tell different stories. Which claims survive a reproducible test?"
2. Run `uv sync --locked --all-extras`, `make build`, `make test`, `make check-generated`; show the generated files and passing test count. Prepare the environment before recording and trim long-running output to fit two minutes.
3. Open the current dashboard's verdict and five-step argument; compare account activity, Intents volume and the separate gross-fee/net-revenue/buyback-labelled series. Open Source and query on one chart.
4. Show the failing on-chain/reference reconciliation and expand “What would change the verdict”: the conditional ratio interval must include 1.0. The current 49 sampled days are fixed intraday windows, not complete-day extracts. Receipt revalidation is complete; volume validation is unresolved.
5. Show retrospective QAA next to the past-only model's training end and release dates. Labels describe behavior, not verified humans.
6. Show statistical diagnostics, exploratory IC and the explicit evidence-against block. Transaction counts precede price in one eligible model; Intents and QAA remain inconclusive. These results do not establish a return signal.
7. Close with NEAR's concrete role: its blocks, receipt logs and Intents events are the evidence. BigQuery and the on-chain index are optional paths, not claimed deployed results.

A hosted demo plus screenshots is allowed. If only a local demo is available, record video: the official rule says screenshots alone are insufficient in that case. The human publishes the demo on X.

Record the video requested by the completion plan even when the dashboard is hosted. Before recording the public site, verify its verdict and build footer after the approved push. Review the recording for readable numbers, visible interactions and any private terminal content; publish the video with the draft below. Keep the dashboard online through judging (at least 18 November, ideally 25 November).

## Draft

Built at NEAR HACKATHON: From clicks to settlement.

Do falling account counts tell the whole story of @NEARProtocol? We built a reproducible thesis comparing raw activity, behavioral proxies, Intents settlement and net fee capture—with past-only features, statistical diagnostics and the evidence against our own hypothesis.

Repo: https://github.com/NGZeggers/near-value-shift
Dashboard: https://ngzeggers.github.io/near-value-shift/

Every chart has its source. One command rebuilds the results. Demo attached. #NEARHackathon

## Final submission information still supplied by the team

Project and lead names, contact email, team-size category, mainnet payout account, actual X demo-post URL, and agreement to the official contact notice. Never put keys or personal submission payloads in Git. The final payload must be reviewed before it is submitted; a submission cannot be edited directly afterward; corrections require the human-reviewed [change request](https://nearhackathon.com/request-changes), not a second submission.

## Publication and submission handoff

After reviewing the local changes, explicitly approve `git push origin main` (this publishes all local commits and triggers Pages). Inspect the separate build and deploy jobs, then check the public page for `id="verdict"` and the current build date. Repository topics to apply after approval: `near`, `near-protocol`, `hackathon`, `investment-thesis`, `onchain-analytics`.

The human creates or supplies an existing mainnet payout account and publishes the actual demo post on X. Add its real URL to README's Submission section when available. Team size must be exactly one of `1`, `2 - 4`, `4 - 6`, `6 - 8`, `8+`.

Re-read [the official rules](https://nearhackathon.com/HACKATHON.md) on submission day and first confirm the project has not already been submitted. Read the contact notice verbatim and obtain agreement: “I agree that the organizers may use these details to review our submission and contact us about this hackathon.” Prepare a private payload outside Git containing only `requestId`, `projectName`, `leadName`, `email`, `size`, `tracks: ["thesis"]`, `nearAddress`, `projectUrl`, `demoUrl`, `idea` and `consent: true`. Generate the UUID once and retain it for retries; validate all fields and the 12,000-byte body ceiling. Do not add `website`.

Display the complete payload for explicit human confirmation before `POST https://nearhackathon.com/api/applications`. A 201 confirms submission. Reuse the UUID after network errors or a 503; stop on 403 or 409. Never send this repository a second time; corrections go through the human's [change request](https://nearhackathon.com/request-changes).
