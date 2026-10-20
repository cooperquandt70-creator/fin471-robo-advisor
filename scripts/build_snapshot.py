"""
Regenerate the bundled educational sample files used when every live source fails:

    data/snapshot_prices.csv   month-end adjusted closes for the ETF universe
    data/snapshot_dtb3.csv     monthly average 3-month T-bill rate (needs FRED_API_KEY)

    python scripts/build_snapshot.py
"""

import logging
import sys
from datetime import date
from pathlib import Path

import streamlit  # noqa: F401  (imported first so its cache warning can be silenced below)

logging.getLogger("streamlit.runtime.caching.cache_data_api").setLevel(logging.ERROR)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import data  # noqa: E402
from profiles import TICKERS  # noqa: E402

HEADER = (
    "# EDUCATIONAL SAMPLE - FIN471 robo-advisor fallback data. Not for investment decisions.\n"
    "# Source: {source}. Generated {today} by scripts/build_snapshot.py. May be stale.\n"
)


def write(df, path, source):
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(HEADER.format(source=source, today=date.today().isoformat()))
        df.to_csv(f, float_format="%.4f")
    print(f"Wrote {path.relative_to(data.ROOT)} ({len(df)} rows, through {df.index[-1]:%Y-%m})")


def main():
    try:
        prices = data.fetch_prices_yfinance(TICKERS)
        source = "Yahoo Finance via yfinance, dividend-adjusted month-end closes"
    except data.ApiError as e:
        print(f"yfinance failed ({e}); trying Tiingo...")
        prices = data.fetch_prices_tiingo(TICKERS, data.get_key("TIINGO_API_KEY"))
        source = "Tiingo, adjusted month-end closes"
    prices.index.name = "Date"
    write(prices, data.SNAPSHOT_PRICES, source)

    try:
        dtb3 = data.fetch_dtb3(data.get_key("FRED_API_KEY")).to_frame("DTB3")
        dtb3.index.name = "Date"
        write(dtb3, data.SNAPSHOT_DTB3, "FRED series DTB3, monthly average, percent")
    except data.ApiError as e:
        print(f"Skipped DTB3 snapshot: {e}")


if __name__ == "__main__":
    main()
