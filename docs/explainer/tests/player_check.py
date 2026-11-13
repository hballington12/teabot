"""Drive the published player in real Chrome, served by a static server that ignores Range requests.

Usage: uv run python tests/player_check.py

Some hosts serve media without Range support, which breaks seeking a streamed video. This
server imitates them. For a desktop and a phone-sized touch viewport, the check presses Start,
then Next four times, and asserts that each slide stops on the frame where the next one begins.
"""

import functools
import http.server
import json
import re
import threading
from pathlib import Path

from playwright.sync_api import Page, sync_playwright

HERE = Path(__file__).parent.parent
PAGE = HERE / "out" / "artifact" / "index.html"
MP4 = HERE / "out" / "teapot-walkthrough.mp4"
STEPS = 5


class NoRange(http.server.SimpleHTTPRequestHandler):
    """Serves the player and the film, always whole: no Range support, as on some hosts."""

    extensions_map = {**http.server.SimpleHTTPRequestHandler.extensions_map, ".html": "text/html; charset=utf-8"}

    def translate_path(self, path: str) -> str:
        return str(MP4) if path.endswith(".mp4") else super().translate_path(path)

    def do_GET(self) -> None:
        if not self.path.endswith(".html"):
            return super().do_GET()
        # wrap the page as the Artifact host does: doctype, charset and a phone viewport
        head = '<!doctype html><html><head><meta charset="utf-8">'
        head += '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover"></head><body>'
        body = (head + PAGE.read_text(encoding="utf-8") + "</body></html>").encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        pass

    def handle(self) -> None:
        try:
            super().handle()
        except ConnectionResetError:
            pass  # the browser hung up mid-file, which is normal for media


def expected_stops() -> list[float]:
    """The time each slide should stop at: the middle of the next slide's first frame."""
    deck = json.loads(re.search(r"const deck = (\{.*?\});\n", PAGE.read_text()).group(1))
    return [(s["frame"] + 0.5) / deck["fps"] for s in deck["sections"][1 : STEPS + 1]]


def wait_paused(page: Page) -> tuple[float, str]:
    page.wait_for_function("() => { const f = document.getElementById('film'); return f.paused && !playing; }")
    return page.evaluate("[document.getElementById('film').currentTime, document.getElementById('where').textContent]")


def run(page: Page, url: str, tap: bool) -> bool:
    page.goto(url)
    page.wait_for_selector("#start:not([hidden])", timeout=60000)
    ok = True
    press = page.tap if tap else page.click
    press("#start")
    for i, want in enumerate(expected_stops()):
        t, where = wait_paused(page)
        good = abs(t - want) < 0.05
        ok &= good
        print(f"  slide {i + 1} stopped at {t:6.2f}s, want {want:6.2f}s  {'ok' if good else 'WRONG'}  [{where}]")
        press("#next")
    wait_paused(page)
    page.screenshot(path=HERE / "tmp" / f"player-{page.viewport_size['width']}.png")
    return ok


def main() -> None:
    handler = functools.partial(NoRange, directory=str(PAGE.parent))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_port}/{PAGE.name}"
    results = []
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome")
        no_frame_callback = "delete HTMLVideoElement.prototype.requestVideoFrameCallback"
        for name, options, tap, init in [
            ("desktop", {"viewport": {"width": 1280, "height": 720}}, False, None),
            ("phone", {"viewport": {"width": 390, "height": 844}, "has_touch": True, "is_mobile": True}, True, None),
            ("no frame callbacks", {"viewport": {"width": 1280, "height": 720}}, False, no_frame_callback),
        ]:
            print(name)
            context = browser.new_context(**options)
            if init:
                context.add_init_script(init)
            results.append(run(context.new_page(), url, tap))
            context.close()
        browser.close()
    server.shutdown()
    print("all ok" if all(results) else "FAILED")


if __name__ == "__main__":
    main()
