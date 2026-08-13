"""
cf_store.py — persistence layer for a manually-pasted cf_clearance cookie.

Holds the cookie in memory + writes it to disk so it survives a server
restart. This is the FALLBACK path — the primary CF bypass is handled
automatically by ViperTLS. This store only matters if the user manually
pastes a cookie via the homepage panel or /cf/manual endpoint.
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
from dataclasses import dataclass
from typing import Optional

# cf_clearance cookies typically last ~30 min on Cloudflare's default config.
# We use 25 min as a conservative TTL for manually-pasted cookies.
COOKIE_TTL_SECONDS = 25 * 60

_STORE_PATH = os.path.join(os.path.dirname(__file__), ".cf_clearance.json")


@dataclass
class CFCookie:
    """A cf_clearance cookie + the UA / client hints that earned it."""
    value: str
    user_agent: str
    captured_at: float
    expires_at: float
    sec_ch_ua: str = ""
    sec_ch_ua_platform: str = ""


class CFStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._cookie: Optional[CFCookie] = None
        self._load_from_disk()

    # ------------------------------------------------------------------ #

    def set(self, cookie: CFCookie) -> None:
        with self._lock:
            self._cookie = cookie
            self._save_to_disk()

    def get(self) -> Optional[CFCookie]:
        with self._lock:
            if self._cookie and time.time() > self._cookie.expires_at:
                self._cookie = None
                self._save_to_disk()
            return self._cookie

    def clear(self) -> None:
        with self._lock:
            self._cookie = None
            self._save_to_disk()

    def set_manual(
        self,
        value: str,
        user_agent: str = "",
        sec_ch_ua: str = "",
        sec_ch_ua_platform: str = "",
    ) -> None:
        """Allow a user to paste a cf_clearance they captured in their own browser."""
        # If user_agent contains Chrome/<version>, derive sec_ch_ua from it
        # so the user doesn't have to paste it manually.
        derived_sec_ch_ua = sec_ch_ua
        derived_platform = sec_ch_ua_platform
        if not derived_sec_ch_ua and user_agent:
            m = re.search(r"Chrome/(\d+)", user_agent)
            if m:
                v = m.group(1)
                derived_sec_ch_ua = (
                    f'"Chromium";v="{v}", "Not_A Brand";v="24", '
                    f'"Google Chrome";v="{v}"'
                )
        if not derived_platform and user_agent:
            ua_l = user_agent.lower()
            if "windows" in ua_l:
                derived_platform = "Windows"
            elif "mac" in ua_l or "darwin" in ua_l:
                derived_platform = "macOS"
            else:
                derived_platform = "Linux"
        cookie = CFCookie(
            value=value.strip(),
            user_agent=user_agent.strip() or (
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36"
            ),
            captured_at=time.time(),
            expires_at=time.time() + COOKIE_TTL_SECONDS,
            sec_ch_ua=derived_sec_ch_ua,
            sec_ch_ua_platform=derived_platform,
        )
        self.set(cookie)

    def status(self) -> dict:
        c = self.get()
        if not c:
            return {"has_cookie": False}
        return {
            "has_cookie": True,
            "value_preview": c.value[:24] + "…" if len(c.value) > 24 else c.value,
            "value_length": len(c.value),
            "user_agent": c.user_agent,
            "sec_ch_ua": c.sec_ch_ua,
            "sec_ch_ua_platform": c.sec_ch_ua_platform,
            "captured_at": c.captured_at,
            "expires_at": c.expires_at,
            "is_expired": time.time() > c.expires_at,
            "seconds_remaining": max(0, int(c.expires_at - time.time())),
        }

    # ------------------------------------------------------------------ #

    def _save_to_disk(self) -> None:
        try:
            if self._cookie:
                with open(_STORE_PATH, "w") as f:
                    json.dump({
                        "value": self._cookie.value,
                        "user_agent": self._cookie.user_agent,
                        "captured_at": self._cookie.captured_at,
                        "expires_at": self._cookie.expires_at,
                        "sec_ch_ua": self._cookie.sec_ch_ua,
                        "sec_ch_ua_platform": self._cookie.sec_ch_ua_platform,
                    }, f)
            else:
                if os.path.exists(_STORE_PATH):
                    os.remove(_STORE_PATH)
        except Exception:
            pass

    def _load_from_disk(self) -> None:
        try:
            if not os.path.exists(_STORE_PATH):
                return
            with open(_STORE_PATH) as f:
                data = json.load(f)
            self._cookie = CFCookie(
                value=data["value"],
                user_agent=data["user_agent"],
                captured_at=data["captured_at"],
                expires_at=data["expires_at"],
                sec_ch_ua=data.get("sec_ch_ua", ""),
                sec_ch_ua_platform=data.get("sec_ch_ua_platform", ""),
            )
        except Exception:
            self._cookie = None


store = CFStore()
