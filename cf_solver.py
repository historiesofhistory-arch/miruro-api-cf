"""
cf_solver.py — Cloudflare cf_clearance cookie fetcher.

Uses botasaurus (which bundles a patched ChromeDriver + real Chrome) to
launch a real browser, navigate to miruro.tv, and capture the cf_clearance
cookie after Cloudflare's challenge resolves.

The solver is designed to be:
  - Async: runs in a background thread so the API stays responsive
  - Stoppable: stop() kills the browser process tree
  - Lightweight after capture: once we have the cookie, the browser is
    closed and the API uses curl_cffi for all subsequent pipe requests
  - Real Chrome preferred: looks for a real Google Chrome install first
    (Cloudflare is much more lenient on real Chrome than Chrome-for-Testing)

On a residential IP or clean VPS, Cloudflare's "managed challenge" resolves
naturally in 5-15 seconds with no interaction needed. On datacenter IPs
that are on Cloudflare's blocklist, even botasaurus's bypass may produce
a "tainted" cookie that the pipe endpoint rejects — in that case, use the
manual paste option in the homepage panel.
"""
from __future__ import annotations

import logging
import os
import signal
import subprocess
import threading
import time
from dataclasses import dataclass
from typing import Optional

log = logging.getLogger("cf_solver")

# Real Google Chrome is preferred over Chrome-for-Testing.
# CF detects Chrome-for-Testing's automation flags.
_CHROME_CANDIDATES = [
    "/usr/bin/google-chrome",
    "/usr/bin/google-chrome-stable",
    "/usr/bin/chromium",
    "/usr/bin/chromium-browser",
    "/home/z/.local/bin/google-chrome",
    "/home/z/.local/bin/chrome",
    "/home/z/.local/bin/chromium",
    "/home/z/project/tools/chrome-extract/opt/google/chrome/chrome",
    "/home/z/my-project/tools/chrome-extract/opt/google/chrome/chrome",
    # Fallback to Playwright's Chrome-for-Testing (last resort)
    "/home/z/.cache/ms-playwright/chromium-1200/chrome-linux64/chrome",
    "/home/z/.cache/ms-playwright/chromium-1228/chrome-linux64/chrome",
]


def _find_chrome() -> Optional[str]:
    env_path = os.environ.get("CHROME_PATH")
    if env_path and os.path.exists(env_path):
        return env_path
    for p in _CHROME_CANDIDATES:
        if os.path.exists(p):
            return p
    return None


@dataclass
class CFCookie:
    """A captured cf_clearance cookie + the UA that earned it."""
    value: str
    user_agent: str
    captured_at: float
    expires_at: float  # cf_clearance typically lasts ~30 min

    def to_dict(self) -> dict:
        return {
            "value": self.value,
            "user_agent": self.user_agent,
            "captured_at": self.captured_at,
            "expires_at": self.expires_at,
            "is_expired": time.time() > self.expires_at,
        }


class CFSolver:
    """
    Manages a single background browser session that solves Cloudflare's
    challenge. Thread-safe; only one fetch runs at a time.
    """

    TARGET_URL = "https://www.miruro.tv/"
    # cf_clearance has a ~30 min TTL; refresh a bit before that.
    COOKIE_TTL_SECONDS = 25 * 60

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._task = None
        self._browser_pid: Optional[int] = None
        self._status: str = "idle"  # idle | running | success | failed | stopped
        self._message: str = ""
        self._started_at: float = 0.0
        self._progress_log: list[str] = []

    # ------------------------------------------------------------------ #
    # Public API (sync, callable from FastAPI background thread)         #
    # ------------------------------------------------------------------ #

    def status(self) -> dict:
        return {
            "status": self._status,
            "message": self._message,
            "started_at": self._started_at,
            "elapsed": (time.time() - self._started_at) if self._started_at else 0,
            "log": list(self._progress_log[-20:]),
        }

    def is_running(self) -> bool:
        return self._status == "running"

    def start(self, on_complete=None) -> bool:
        """
        Launch the browser in a background thread. Returns True if started,
        False if another run is already in progress.
        """
        with self._lock:
            if self._status == "running":
                return False
            self._status = "running"
            self._message = "Starting browser…"
            self._started_at = time.time()
            self._progress_log = []

            def _run():
                try:
                    cookie = self._fetch_sync()
                    if cookie:
                        self._status = "success"
                        self._message = "cf_clearance captured"
                        if on_complete:
                            on_complete(cookie)
                    else:
                        self._status = "failed"
                        self._message = "Cloudflare did not issue cf_clearance"
                except Exception as e:
                    log.exception("cf_solver failed")
                    self._status = "failed"
                    self._message = f"Error: {e}"
                finally:
                    self._browser_pid = None

            t = threading.Thread(target=_run, daemon=True, name="cf-solver")
            t.start()
            return True

    def stop(self) -> bool:
        """Kill any running browser process. Safe to call repeatedly."""
        killed_any = False
        with self._lock:
            if self._status != "running":
                return False
            self._status = "stopped"
            self._message = "Stopped by user"
            if self._browser_pid:
                try:
                    os.kill(self._browser_pid, signal.SIGTERM)
                    killed_any = True
                except ProcessLookupError:
                    pass
                except Exception as e:
                    log.warning("kill failed: %s", e)
                self._browser_pid = None
        # Kill any straggler chrome processes spawned by the solver
        try:
            subprocess.run(
                ["pkill", "-u", str(os.getuid()), "-f", "chrome-linux64/chrome"],
                check=False, capture_output=True, timeout=5,
            )
            subprocess.run(
                ["pkill", "-u", str(os.getuid()), "-f", "google-chrome"],
                check=False, capture_output=True, timeout=5,
            )
            subprocess.run(
                ["pkill", "-u", str(os.getuid()), "-f", "chromedriver"],
                check=False, capture_output=True, timeout=5,
            )
        except Exception:
            pass
        return killed_any

    # ------------------------------------------------------------------ #
    # Internal: botasaurus-based browser automation                      #
    # ------------------------------------------------------------------ #

    def _fetch_sync(self) -> Optional[CFCookie]:
        # Ensure DISPLAY is set for headed Chromium on Linux
        if not os.environ.get("DISPLAY"):
            os.environ["DISPLAY"] = ":99"

        chrome_path = _find_chrome()
        if not chrome_path:
            raise RuntimeError(
                "No Chrome/Chromium binary found. Install one or set CHROME_PATH."
            )

        self._log(f"Using chrome: {chrome_path}")
        self._log(f"DISPLAY={os.environ.get('DISPLAY')}")

        # Use botasaurus - it has the best CF bypass track record
        try:
            from botasaurus.browser import browser, Driver
        except ImportError:
            raise RuntimeError(
                "botasaurus is not installed. Run: pip install botasaurus"
            )

        # botasaurus uses a decorator pattern; wrap a function we can call
        captured = {"cookie": None, "ua": None}

        @browser(headless=False, profile="cf-solver", close_on_crash=False, block_images=True)
        def _solve(driver: Driver, url: str):
            driver.get(url)
            self._log(f"Loaded: {driver.title}")

            # Try botasaurus's built-in CF bypass
            try:
                driver.detect_and_bypass_cloudflare()
                self._log("Bypass attempt completed")
            except Exception as e:
                self._log(f"Bypass: {e}")

            # Wait for the cookie to appear
            for i in range(90):
                if self._status == "stopped":
                    self._log("Stopped by user")
                    return
                cookies = driver.get_cookies()
                cf = [c for c in cookies if c.get("name") == "cf_clearance"]
                if cf:
                    self._log(f"cf_clearance captured after {i+1}s")
                    captured["cookie"] = cf[0]["value"]
                    try:
                        captured["ua"] = driver.run_js("return navigator.userAgent;")
                    except Exception:
                        captured["ua"] = (
                            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                            "(KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36"
                        )
                    return
                if i % 5 == 0:
                    try:
                        title = driver.title
                    except Exception:
                        title = "?"
                    self._log(f"{i}s: title={title!r}")
                time.sleep(1)

            self._log("No cf_clearance after 90s")

        # botasaurus needs a profile dir; ensure it exists
        profile_dir = "/tmp/cf-solver-profile"
        os.makedirs(profile_dir, exist_ok=True)

        # Run the decorated function — botasaurus handles browser lifecycle
        try:
            _solve(self.TARGET_URL)
        except Exception as e:
            self._log(f"botasaurus error: {e}")
            return None

        if not captured["cookie"]:
            return None

        return CFCookie(
            value=captured["cookie"],
            user_agent=captured["ua"] or (
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36"
            ),
            captured_at=time.time(),
            expires_at=time.time() + self.COOKIE_TTL_SECONDS,
        )

    def _log(self, msg: str) -> None:
        ts = time.strftime("%H:%M:%S")
        line = f"[{ts}] {msg}"
        self._progress_log.append(line)
        log.info(msg)


# Singleton — the whole API shares one solver
solver = CFSolver()
