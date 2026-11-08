"""L0: public, key-less data sources. `make fetch` refreshes every snapshot in data/raw/."""
from __future__ import annotations

import time

from .config import INTENTS_EXPLORER_JWT
from .http import fetch_json, save_raw

NEARBLOCKS = "https://api.nearblocks.io/v1"
LLAMA = "https://api.llama.fi"
STABLES = "https://stablecoins.llama.fi"
RPC = "https://rpc.mainnet.near.org"
COINGECKO = "https://api.coingecko.com/api/v3"
GITHUB = "https://api.github.com"

PEER_CHAINS = ["near", "solana", "base", "arbitrum", "polygon", "avalanche", "sui", "aptos"]
PEER_GECKO = {"near": "near", "solana": "solana", "base": None, "arbitrum": "arbitrum", "polygon": "polygon-ecosystem-token",
              "avalanche": "avalanche-2", "sui": "sui", "aptos": "aptos"}
LLAMA_CHAIN_NAME = {"near": "Near", "solana": "Solana", "base": "Base", "arbitrum": "Arbitrum", "polygon": "Polygon",
                    "avalanche": "Avalanche", "sui": "Sui", "aptos": "Aptos"}


def fetch_nearblocks() -> None:
    print("NearBlocks daily charts (txns, active/new accounts, contracts, gas, fees, price)")
    data = fetch_json(f"{NEARBLOCKS}/charts")
    save_raw("nearblocks_charts", f"{NEARBLOCKS}/charts", data["charts"])
    stats = fetch_json(f"{NEARBLOCKS}/stats")
    save_raw("nearblocks_stats", f"{NEARBLOCKS}/stats", stats["stats"][0])


def fetch_defillama() -> None:
    print("DefiLlama: NEAR Intents volume, NEAR DEX volume by protocol, TVL, fees, stablecoins, peers")
    save_raw("llama_intents_volume", f"{LLAMA}/summary/dexs/near-intents?dataType=dailyVolume",
             fetch_json(f"{LLAMA}/summary/dexs/near-intents?dataType=dailyVolume"))
    save_raw("llama_intents_fees", f"{LLAMA}/summary/fees/near-intents?dataType=dailyFees",
             fetch_json(f"{LLAMA}/summary/fees/near-intents?dataType=dailyFees"))
    for name, kind in [("revenue", "dailyRevenue"), ("holders_revenue", "dailyHoldersRevenue")]:
        url = f"{LLAMA}/summary/fees/near-intents?dataType={kind}"
        save_raw(f"llama_intents_{name}", url, fetch_json(url),
                 note="Net wallet receipts; holders revenue is adapter-classified buyback revenue, not proof of burns or holder dividends. Internal wallet transfers excluded by adapter.")
    save_raw("llama_near_dexs", f"{LLAMA}/overview/dexs/near",
             fetch_json(f"{LLAMA}/overview/dexs/near?excludeTotalDataChart=false&excludeTotalDataChartBreakdown=false&dataType=dailyVolume"))
    save_raw("llama_chains", f"{LLAMA}/v2/chains", fetch_json(f"{LLAMA}/v2/chains"))
    for c in PEER_CHAINS:
        name = LLAMA_CHAIN_NAME[c]
        save_raw(f"llama_tvl_{c}", f"{LLAMA}/v2/historicalChainTvl/{name}", fetch_json(f"{LLAMA}/v2/historicalChainTvl/{name}"))
        save_raw(f"llama_fees_{c}", f"{LLAMA}/overview/fees/{c}",
                 fetch_json(f"{LLAMA}/overview/fees/{c}?excludeTotalDataChart=false&excludeTotalDataChartBreakdown=true&dataType=dailyFees"))
        save_raw(f"llama_dexs_{c}", f"{LLAMA}/overview/dexs/{c}",
                 fetch_json(f"{LLAMA}/overview/dexs/{c}?excludeTotalDataChart=false&excludeTotalDataChartBreakdown=true&dataType=dailyVolume"))
        save_raw(f"llama_stables_{c}", f"{STABLES}/stablecoincharts/{name}", fetch_json(f"{STABLES}/stablecoincharts/{name}"))
        time.sleep(0.3)


def fetch_rpc() -> None:
    print("NEAR RPC: status + validators (stake, validator count)")
    status = fetch_json(RPC, method="POST", json_body={"jsonrpc": "2.0", "id": 1, "method": "status", "params": []})
    save_raw("rpc_status", RPC, status["result"])
    vals = fetch_json(RPC, method="POST", json_body={"jsonrpc": "2.0", "id": 1, "method": "validators", "params": [None]})
    cur = vals["result"]["current_validators"]
    save_raw("rpc_validators", RPC, {"n": len(cur), "total_stake_near": sum(int(v["stake"]) for v in cur) / 1e24,
                                     "validators": [{"account_id": v["account_id"], "stake_near": int(v["stake"]) / 1e24} for v in cur]})


LLAMA_COINS = "https://coins.llama.fi"


PRICE_COINS = ["near", "bitcoin", "ethereum"]  # benchmarks used by features/signal tests
INTENTS_PRICE_COINS = ["solana", "ripple", "dogecoin", "zcash", "litecoin", "binancecoin", "tron", "sui", "bitcoin-cash",
                       "avalanche-2", "aptos", "arbitrum", "polygon-ecosystem-token", "the-open-network", "sweatcoin", "berachain-bera", "chainlink"]  # majors seen in Intents token_diff legs (priced in L2)
ONECLICK_TOKENS = "https://1click.chaindefuser.com/v0/tokens"


def _llama_daily(cid: str) -> list[list[float]]:
    start, now, pts = 1593561600, int(time.time()), {}  # 2020-07-01
    while start < now:
        url = f"{LLAMA_COINS}/chart/coingecko:{cid}?start={start}&span=500&period=1d"
        prices = fetch_json(url).get("coins", {}).get(f"coingecko:{cid}", {}).get("prices", [])
        if not prices:
            break
        for pnt in prices:
            pts[int(pnt["timestamp"])] = float(pnt["price"])
        start = int(prices[-1]["timestamp"]) + 86400
        time.sleep(0.3)
    return [[t, p] for t, p in sorted(pts.items())]


def fetch_prices() -> None:
    """Daily USD prices since 2020 from DefiLlama's coins API (free, no key, 500 points per call): NEAR, BTC, ETH
    (benchmarks) and the majors that show up in Intents settlements (L2 pricing), plus peer market caps (CoinGecko)."""
    print("Prices: daily since 2020 (DefiLlama coins API) for benchmarks and Intents majors + peer market caps (CoinGecko)")
    for cid in PRICE_COINS + INTENTS_PRICE_COINS:
        save_raw(f"price_{cid}", f"{LLAMA_COINS}/chart/coingecko:{cid}?period=1d (paginated)", _llama_daily(cid))
    ids = ",".join(v for v in PEER_GECKO.values() if v)
    url = f"{COINGECKO}/coins/markets?vs_currency=usd&ids={ids}"
    save_raw("gecko_peer_markets", url, fetch_json(url))


def fetch_intents_tokens() -> None:
    """Token registry of NEAR Intents (1Click API, public): asset id -> symbol, decimals, CoinGecko id. Used to price
    token_diff legs in L2; the `price` field is the current quote and is not used for history."""
    print("Intents tokens: asset registry from the 1Click API (symbols, decimals, CoinGecko ids)")
    save_raw("intents_tokens", ONECLICK_TOKENS, fetch_json(ONECLICK_TOKENS), note="current prices in this file are not used; history comes from DefiLlama")


def fetch_github() -> None:
    print("GitHub: weekly commit activity for core NEAR repos (developer activity)")
    out = {}
    for repo in ["near/nearcore", "near/near-sdk-rs", "near/near-api-js", "defuse-protocol/defuse-contracts", "near/intents"]:
        try:
            d = fetch_json(f"{GITHUB}/repos/{repo}/stats/commit_activity")
            if isinstance(d, list):
                out[repo] = d
            else:
                print(f"  {repo}: stats not ready (GitHub computes them lazily); re-run fetch later")
        except Exception as e:  # noqa: BLE001
            print(f"  {repo}: skipped ({e})")
        time.sleep(1)
    save_raw("github_commit_activity", f"{GITHUB}/repos/<repo>/stats/commit_activity", out)


BUYBACK_WALLET = "buybacks.multisignature.near"   # NEAR's buyback multisig (DefiLlama fees/near-intents adapter, query 6740088)
NEARBLOCKS_SLEEP_S = 12   # the key-less NearBlocks tier allows a few requests per minute


def _nearblocks_paged(url: str, key: str) -> list:
    """Follow NearBlocks cursor pagination slowly enough for the key-less tier; back off on 429."""
    out, cursor, seen = [], None, set()
    while True:
        page = url + (f"&cursor={cursor}" if cursor else "")
        for attempt in range(8):
            try:
                d = fetch_json(page)
                if not isinstance(d, dict) or (d.get('message') and not d.get(key)):
                    raise ValueError('NearBlocks returned an error or invalid page')
                break
            except Exception as e:  # noqa: BLE001  rate-limit answers arrive as HTTP 429 or as a JSON error body
                print(f"  nearblocks: {e}; waiting 45s")
                time.sleep(45)
        else:
            raise RuntimeError(f"NearBlocks pagination failed for {url}")
        rows = d.get(key) or []
        out.extend(rows)
        cursor = d.get("cursor")
        print(f"  {len(out)} rows so far", flush=True)
        if not cursor or not rows:
            return out
        if cursor in seen:
            raise RuntimeError('NearBlocks cursor did not advance')
        seen.add(cursor)
        time.sleep(NEARBLOCKS_SLEEP_S)


def fetch_buybacks() -> None:
    """Receipts of the buyback multisig and its current balance (NearBlocks, key-less). Inbound NEAR transfers from
    intents.near are executed purchases arriving as NEAR; the balance shows what is still held (not burned)."""
    print("NearBlocks: buyback multisig receipts and balance (executed purchases and held tokens)")
    acct = fetch_json(f"{NEARBLOCKS}/account/{BUYBACK_WALLET}")
    save_raw("nearblocks_buybacks_account", f"{NEARBLOCKS}/account/{BUYBACK_WALLET}", acct["account"][0],
             note="current balance of the buyback multisig in yoctoNEAR; held tokens, not a burn")
    time.sleep(NEARBLOCKS_SLEEP_S)
    txns = _nearblocks_paged(f"{NEARBLOCKS}/account/{BUYBACK_WALLET}/txns?per_page=250", "txns")
    save_raw("nearblocks_buybacks_txns", f"{NEARBLOCKS}/account/{BUYBACK_WALLET}/txns?per_page=250 (paginated)",
             {"wallet": BUYBACK_WALLET, "txns": txns},
             note="all receipts involving the buyback multisig; inbound TRANSFER actions with predecessor intents.near are executed buybacks settled as NEAR")


def fetch_intents_explorer() -> None:
    """Reserved integration; explicit requests must fail rather than claim a pull."""
    raise NotImplementedError("Intents Explorer is not supported; use block extraction or optional BigQuery")


def run(only: list[str] | None = None) -> None:
    steps = {"nearblocks": fetch_nearblocks, "defillama": fetch_defillama, "rpc": fetch_rpc,
             "prices": fetch_prices, "tokens": fetch_intents_tokens, "github": fetch_github, "buybacks": fetch_buybacks,
             "intents": fetch_intents_explorer}
    if only is not None and (not only or set(only) - steps.keys()):
        raise ValueError(f"Unknown or empty fetch selection: {only}")
    failed: list[str] = []
    for name, fn in steps.items():
        if only and name not in only:
            continue
        if name == 'intents' and not only:
            print('Intents Explorer: optional integration unsupported; skipped in default fetch')
            continue
        try:
            fn()
        except NotImplementedError as e:
            print(f"  {name}: {e}")
            failed.append(name)
        except Exception as e:  # noqa: BLE001  one failing source must not block the others
            print(f"  {name}: FAILED ({e}). Re-run with --only {name} later.")
            failed.append(name)
    if failed:
        raise SystemExit(f"fetch finished with failures: {', '.join(failed)}")
