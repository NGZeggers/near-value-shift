import numpy as np
import pandas as pd

from near_thesis import features


def test_monthly_sums_and_means():
    idx = pd.date_range("2025-01-01", "2025-02-28", freq="D")
    daily = pd.DataFrame({"date": idx})
    for c in ["txns", "new_accounts", "tx_fee_usd", "tx_volume_usd", "intents_volume_usd", "intents_fees_usd",
              "near_dex_volume_usd", "near_app_fees_usd", "tx_fee_near"]:
        daily[c] = 1.0
    for c in ["active_accounts", "active_contracts", "near_price", "market_cap_usd", "tvl_usd", "stablecoins_usd",
              "usd_per_txn", "price_near", "price_bitcoin", "price_ethereum"]:
        daily[c] = 10.0
    m = features.build_monthly(daily)
    assert list(m["days"]) == [31, 28]
    assert m.loc[0, "txns"] == 31 and m.loc[1, "txns"] == 28
    assert np.isclose(m.loc[0, "active_accounts"], 10.0)
