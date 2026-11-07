from __future__ import annotations

import argparse


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="near-thesis", description="Reproducible NEAR investment-thesis pipeline")
    sub = p.add_subparsers(dest="cmd", required=True)

    f = sub.add_parser("fetch", help="L0: pull public sources into data/raw/")
    f.add_argument("--only", nargs="*", help="subset: nearblocks defillama rpc prices tokens github buybacks intents")

    b = sub.add_parser("bq", help="run BigQuery SQL with a dry-run cost gate")
    b.add_argument("names", nargs="*", help="sql file stems to run (default: all)")
    b.add_argument("--dry", action="store_true", help="only print estimated GB per query")
    b.add_argument("--force", action="store_true", help="override the per-query estimate gate (the run budget still applies)")

    bl = sub.add_parser("blocks", help="sample full blocks from FastNear neardata (no credentials) into data/blocks/")
    bl.add_argument("--day-step", type=int, default=15)
    bl.add_argument("--blocks", type=int, default=50, help="blocks per window")
    bl.add_argument("--offline", action="store_true", help="rebuild data/blocks/*.csv and the manifest from the cache only (no network)")
    bl.add_argument("--workers", type=int, default=2)

    bi = sub.add_parser("blocks-intraday", help="fetch every hourly window of selected sampled days (reconciliation of the fixed-window expansion)")
    bi.add_argument("--days", nargs="*", help="YYYY-MM-DD days; default: days already in data/blocks/intraday_plan.json")
    bi.add_argument("--blocks", type=int, default=50, help="blocks per hourly window")
    bi.add_argument("--workers", type=int, default=2)
    bi.add_argument("--offline", action="store_true", help="rebuild the intraday extract from cached blocks only")
    bi.add_argument("--validation", action="store_true", help="fetch the pre-declared validation days instead (separate files; selection by position, not volume)")
    bt = sub.add_parser("blocks-buyback-trace", help="read the execution block of a pre-declared sample of buyback-wallet receipts and match the Intents withdraw events")
    bt.add_argument("--offline", action="store_true", help="cached blocks only")

    of = sub.add_parser("oos-freeze", help="persist the prospective out-of-sample plan once (data/prospective/oos_freeze.json); refuses to overwrite")
    of.add_argument("--frozen-on", default=None, help="effective freeze date (default: today, UTC)")
    of.add_argument("--force", action="store_true", help="replace an existing frozen plan deliberately")
    sub.add_parser("qaa-refits", help="refit the QAA clustering under other hyper-parameters and an alternative algorithm; writes a committed sensitivity artifact")
    ve = sub.add_parser("verify-events", help="revalidate saved event receipts against full blocks; resumable and atomic")
    ve.add_argument("--offline", action="store_true", help="use only full verification blocks already cached")

    oc = sub.add_parser("onchain", help="publish the index to NEAR Social (dry run unless --send); --verify reads it back and compares hashes")
    mode = oc.add_mutually_exclusive_group()
    mode.add_argument("--verify", action="store_true", help="read <account>/near_thesis/index from NEAR Social and compare with this checkout")
    oc.add_argument("--account", help="account to publish or verify (overrides NEAR_ACCOUNT_ID)")
    oc.add_argument("--network", choices=["testnet", "mainnet"], help="default NEAR_NETWORK or testnet")
    mode.add_argument("--send", action="store_true", help="actually sign and send (requires an account and NEAR_PRIVATE_KEY)")

    for name, helptext in [("features", "derive metric tables into data/derived/"),
                           ("models", "L1 clustering, L3 econometrics, L4 signal tests"),
                           ("charts", "render charts and manifest"),
                           ("thesis", "generate THESIS.md from outputs"),
                           ("site", "assemble static dashboard in site/")]:
        sub.add_parser(name, help=helptext)

    a = p.parse_args(argv)
    if a.cmd == "fetch":
        from . import fetch
        fetch.run(a.only)
    elif a.cmd == "bq":
        from . import bq
        bq.run(a.names or None, dry=a.dry, force=a.force)
    elif a.cmd == "blocks":
        from . import blocks
        blocks.run(day_step=a.day_step, blocks_per_window=a.blocks, workers=a.workers, offline=a.offline)
    elif a.cmd == "blocks-intraday":
        from . import blocks
        if a.validation:
            blocks.run_intraday_validation(blocks_per_window=a.blocks, workers=a.workers, offline=a.offline)
        else:
            blocks.run_intraday(days=a.days or None, blocks_per_window=a.blocks, workers=a.workers, offline=a.offline)
    elif a.cmd == "blocks-buyback-trace":
        from . import blocks
        blocks.run_buyback_trace(offline=a.offline)
    elif a.cmd == "oos-freeze":
        import datetime as _dt
        from . import signal
        plan = signal.freeze_prospective_plan(signal._weekly(), a.frozen_on or _dt.datetime.now(_dt.timezone.utc).date().isoformat(), force=a.force)
        print(f"oos-freeze: {len(plan['tests'])} tests frozen on {plan['frozen_on']} at data cutoff {plan['data_cutoff']} -> {signal.PROSPECTIVE_FREEZE}")
    elif a.cmd == "qaa-refits":
        from . import qaa
        qaa.run_refits()
    elif a.cmd == "verify-events":
        from . import blocks
        blocks.verify_events(offline=a.offline)
    elif a.cmd == "onchain":
        from . import onchain
        if a.verify:
            raise SystemExit(0 if onchain.verify(a.account, a.network) else 1)
        onchain.run(dry_run=not a.send, account_id=a.account, network=a.network)
    elif a.cmd == "features":
        from . import features
        features.run()
    elif a.cmd == "models":
        from . import models
        models.run()
    elif a.cmd == "charts":
        from . import charts
        charts.run()
    elif a.cmd == "thesis":
        from . import thesis
        thesis.run()
    elif a.cmd == "site":
        from . import site
        site.run()


if __name__ == "__main__":
    main()
