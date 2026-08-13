"""
cf_store.py — persistence layer for the captured cf_clearance cookie.

Holds the cookie in memory + writes it to disk so it survives a server
restart. The API reads it back through `get_active_cookie()` which returns
None if no cookie or if it's expired.
"""
from __future__ import annotations

import json
import os
import threading
import time
from typing import Optional

from cf_solver import CFCookie

_STORE_PATH = os.path.join(os.path.dirname(__file__), ".cf_clearance.json")


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
                # Expired — clear and persist removal
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
        from cf_solver import CFSolver
        # If user_agent contains Chrome/<version>, derive sec_ch_ua from it
        # so the user doesn't have to paste it manually.
        derived_sec_ch_ua = sec_ch_ua
        derived_platform = sec_ch_ua_platform
        if not derived_sec_ch_ua and user_agent:
            import re
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
            expires_at=time.time() + CFSolver.COOKIE_TTL_SECONDS,
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
