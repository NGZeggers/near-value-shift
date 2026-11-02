from __future__ import annotations

import argparse


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="near-thesis", description="Reproducible NEAR investment-thesis pipeline")
    sub = p.add_subparsers(dest="cmd", required=True)

    f = sub.add_parser("fetch", help="L0: pull public sources into data/raw/")
    f.add_argument("--only", nargs="*", help="subset: nearblocks defillama rpc prices github intents")

    b = sub.add_parser("bq", help="run BigQuery SQL with a dry-run cost gate")
    b.add_argument("names", nargs="*", help="sql file stems to run (default: all)")
    b.add_argument("--dry", action="store_true", help="only print estimated GB per query")
    b.add_argument("--force", action="store_true", help="ignore BQ_MAX_GB_PER_QUERY")

    bl = sub.add_parser("blocks", help="sample full blocks from FastNear neardata (no credentials) into data/blocks/")
    bl.add_argument("--day-step", type=int, default=15)
    bl.add_argument("--blocks", type=int, default=50, help="blocks per window")
    bl.add_argument("--offline", action="store_true", help="rebuild data/blocks/*.csv and the manifest from the cache only (no network)")
    bl.add_argument("--workers", type=int, default=2)

    oc = sub.add_parser("onchain", help="publish the index to NEAR Social (dry run unless --send)")
    oc.add_argument("--send", action="store_true", help="actually sign and send (requires NEAR_ACCOUNT_ID/NEAR_PRIVATE_KEY in .env)")

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
    elif a.cmd == "onchain":
        from . import onchain
        onchain.run(dry_run=not a.send)
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
