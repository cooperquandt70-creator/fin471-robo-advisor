"""
Live smoke test for every external API the app uses.

    python scripts/check_apis.py            # test with the keys in .env
    python scripts/check_apis.py --bad-key  # same calls with fake keys (error handling)

Prints OK / FAIL per check. Never prints key values.
"""

import argparse
import logging
import sys
from pathlib import Path

import streamlit  # noqa: F401  (imported first so its cache warning can be silenced below)

# data.py's st.cache_data wrappers warn "No runtime found" outside `streamlit run`; harmless here.
logging.getLogger("streamlit.runtime.caching.cache_data_api").setLevel(logging.ERROR)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import data  # noqa: E402
from profiles import TICKERS  # noqa: E402


def report(name, ok, detail):
    print(f"[{'OK  ' if ok else 'FAIL'}] {name}: {detail}")


def skip(name, key_name):
    """A missing key isn't a failure (all keys are optional), so say so plainly."""
    print(f"[SKIP] {name}: no {key_name} in .env (optional; the app works without it)")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--bad-key", action="store_true", help="use deliberately invalid keys")
    args = parser.parse_args()

    if args.bad_key:
        keys = {k: "invalid_key_for_testing_0000000" for k in ("FINNHUB_API_KEY", "FRED_API_KEY", "TIINGO_API_KEY")}
        print("Using deliberately INVALID keys: every keyed check below should FAIL with a clear message.\n")
    else:
        keys = {k: data.get_key(k) for k in ("FINNHUB_API_KEY", "FRED_API_KEY", "TIINGO_API_KEY")}
        for k, v in keys.items():
            print(f"{k}: {'set' if v else 'MISSING'}")
        print()

    # Finnhub /quote (free)
    if not keys["FINNHUB_API_KEY"]:
        skip("Finnhub /quote VTI", "FINNHUB_API_KEY")
    else:
        try:
            q = data.fetch_quote("VTI", keys["FINNHUB_API_KEY"])
            report("Finnhub /quote VTI", True, f"price {q['c']}, change {q.get('dp')}%")
        except data.ApiError as e:
            report("Finnhub /quote VTI", False, e)

    # Finnhub premium endpoints: expected to be refused on the free tier (Step 0 check)
    for path, params in (("/etf/profile", {"symbol": "VTI"}),
                         ("/stock/candle", {"symbol": "VTI", "resolution": "D", "from": 1700000000, "to": 1700600000})):
        if not keys["FINNHUB_API_KEY"]:
            skip(f"Finnhub {path} (expected premium)", "FINNHUB_API_KEY")
            continue
        try:
            data._get_json(data.FINNHUB_URL + path, "Finnhub", params=params,
                           headers={"X-Finnhub-Token": keys["FINNHUB_API_KEY"] or ""})
            report(f"Finnhub {path} (expected premium)", True, "unexpectedly AVAILABLE on this key")
        except data.ApiError as e:
            # A 403 with a valid key confirms the Step 0 finding that this endpoint is premium-only.
            confirmed = "403" in str(e) and not args.bad_key
            report(f"Finnhub {path} (expected premium)", confirmed,
                   "HTTP 403: confirmed premium-only, as documented" if confirmed else e)

    # FRED DTB3
    if not keys["FRED_API_KEY"]:
        skip("FRED DTB3", "FRED_API_KEY")
    else:
        try:
            s = data.fetch_dtb3(keys["FRED_API_KEY"])
            report("FRED DTB3", True, f"{len(s)} months, latest {s.index[-1]:%Y-%m} = {s.iloc[-1]:.2f}%")
        except data.ApiError as e:
            report("FRED DTB3", False, e)

    # Prices: yfinance (no key; unaffected by --bad-key)
    try:
        p = data.fetch_prices_yfinance(TICKERS)
        report("yfinance prices", True, f"{len(p)} months x {p.shape[1]} ETFs, {p.index[0]:%Y-%m} to {p.index[-1]:%Y-%m}")
    except data.ApiError as e:
        report("yfinance prices", False, e)

    # Prices: Tiingo (one ticker only, to save the 50/hour free quota)
    if not keys["TIINGO_API_KEY"]:
        skip("Tiingo prices VTI", "TIINGO_API_KEY")
    else:
        try:
            p = data.fetch_prices_tiingo(["VTI"], keys["TIINGO_API_KEY"])
            report("Tiingo prices VTI", True, f"{len(p)} months, {p.index[0]:%Y-%m} to {p.index[-1]:%Y-%m}")
        except data.ApiError as e:
            report("Tiingo prices VTI", False, e)

    # Bundled sample
    try:
        p = data.load_snapshot_prices(TICKERS)
        report("Bundled snapshot", True, f"{len(p)} months through {p.index[-1]:%Y-%m}")
    except (data.ApiError, ValueError) as e:
        report("Bundled snapshot", False, e)


if __name__ == "__main__":
    main()
