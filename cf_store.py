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

    def set_manual(self, value: str, user_agent: str = "") -> None:
        """Allow a user to paste a cf_clearance they captured in their own browser."""
        from cf_solver import CFSolver
        cookie = CFCookie(
            value=value.strip(),
            user_agent=user_agent.strip() or (
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36"
            ),
            captured_at=time.time(),
            expires_at=time.time() + CFSolver.COOKIE_TTL_SECONDS,
        )
        self.set(cookie)

    def status(self) -> dict:
        c = self.get()
        if not c:
            return {"has_cookie": False}
        return {
            "has_cookie": True,
            "value_preview": c.value[:24] + "…" if len(c.value) > 24 else c.value,
            "user_agent": c.user_agent,
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
            )
        except Exception:
            self._cookie = None


store = CFStore()
