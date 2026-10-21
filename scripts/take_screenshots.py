"""
Capture clean README screenshots of the app with Playwright's headless Chromium.

    pip install -r requirements-dev.txt
    python -m playwright install chromium
    python scripts/take_screenshots.py

Starts its own headless Streamlit server on a free port (so it doesn't clash
with one you have open), sets each preset's inputs like a user would, and
saves PNGs to screenshots/. No Windows watermark, no browser chrome.
"""

import socket
import subprocess
import sys
import time
from pathlib import Path

import requests
from playwright.sync_api import Page, sync_playwright

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "screenshots"
VIEWPORT = {"width": 1440, "height": 1000}

# Each preset: filename prefix and the inputs to set. Answers left alone stay at
# the default middle option ("Hold and wait", "Balance growth and stability", ...).
PRESETS = [
    {"name": "age25", "age": 25, "quotes": True},  # quotes are the same 7 ETFs for both, so capture once
    {"name": "age60", "age": 60},
]
# Charts in page order (index of st.plotly_chart on the page).
CHARTS = {0: "allocation_donut", 1: "backtest", 2: "monte_carlo", 3: "risk_return"}


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def start_server(port: int) -> subprocess.Popen:
    cmd = [sys.executable, "-m", "streamlit", "run", str(ROOT / "app.py"),
           "--server.headless", "true", "--server.port", str(port),
           "--client.toolbarMode", "viewer"]  # hide the Deploy button / dev menu
    proc = subprocess.Popen(cmd, cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(60):
        try:
            if requests.get(f"http://127.0.0.1:{port}/_stcore/health", timeout=1).ok:
                return proc
        except requests.RequestException:
            pass
        time.sleep(0.5)
    proc.kill()
    raise RuntimeError("Streamlit did not start within 30 seconds.")


def wait_until_idle(page: Page) -> None:
    """Wait for Streamlit to finish re-running the script and for all 4 charts to draw."""
    page.wait_for_timeout(500)
    page.wait_for_selector('[data-testid="stStatusWidget"]', state="detached", timeout=90_000)
    page.wait_for_function("document.querySelectorAll('[data-testid=\"stPlotlyChart\"] .main-svg').length >= 4",
                           timeout=90_000)
    page.wait_for_timeout(1_000)  # let Plotly finish its transitions


def set_age(page: Page, age: int) -> None:
    box = page.get_by_label("Age", exact=True)
    box.fill(str(age))
    box.press("Enter")
    wait_until_idle(page)


def capture(page: Page, preset: dict) -> list[Path]:
    saved = []
    set_age(page, preset["age"])
    # Streamlit scrolls an inner container, not the window: reset every scrolled element.
    page.evaluate("document.querySelectorAll('*').forEach(el => { if (el.scrollTop > 0) el.scrollTop = 0; })")
    page.wait_for_timeout(300)
    path = OUT / f"{preset['name']}_overview.png"
    page.screenshot(path=path)
    saved.append(path)

    charts = page.locator('[data-testid="stPlotlyChart"]')
    for i, label in CHARTS.items():
        chart = charts.nth(i)
        chart.scroll_into_view_if_needed()
        page.wait_for_timeout(300)
        path = OUT / f"{preset['name']}_{label}.png"
        chart.screenshot(path=path)
        saved.append(path)

    if preset.get("quotes"):
        saved.extend(capture_quotes(page))
    return saved


def capture_quotes(page: Page) -> list[Path]:
    """Crop from the 'Live market quotes' heading down to its 'Fetched ...' caption."""
    heading = page.get_by_text("Live market quotes (Finnhub)", exact=True)
    if heading.count() == 0:
        print("Quote panel not shown (no FINNHUB_API_KEY?) - skipped quotes screenshot.")
        return []
    heading.scroll_into_view_if_needed()
    page.wait_for_timeout(300)
    top = heading.bounding_box()
    caption = page.get_by_text("Fetched", exact=False).first.bounding_box()
    if not top or not caption:
        return []
    path = OUT / "live_quotes.png"
    width = max(720, caption["x"] + caption["width"] - top["x"] + 32)  # wide enough for the caption
    page.screenshot(path=path, clip={"x": top["x"] - 16, "y": top["y"] - 16, "width": width,
                                     "height": caption["y"] + caption["height"] - top["y"] + 32})
    return [path]


def main() -> None:
    OUT.mkdir(exist_ok=True)
    port = free_port()
    print(f"Starting Streamlit on port {port}...")
    server = start_server(port)
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(viewport=VIEWPORT, device_scale_factor=2, color_scheme="light")
            page.goto(f"http://127.0.0.1:{port}")
            wait_until_idle(page)  # first load fetches price data
            for preset in PRESETS:
                for path in capture(page, preset):
                    print(f"Saved {path.relative_to(ROOT)}")
            browser.close()
    finally:
        server.terminate()
        server.wait(timeout=10)


if __name__ == "__main__":
    main()
