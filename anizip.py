"""
anizip.py — Lightweight AniZip client for TVDB episode metadata.

AniZip (api.ani.zip) is a free public service that maps AniList IDs to
TheTVDB series IDs and returns:
  - Episode titles (multi-language: en, ja, de, fr, x-jat, etc.)
  - Episode thumbnails (TVDB CDN URLs — no auth needed)
  - Episode summaries (overview)
  - Air dates + runtime
  - TVDB series artwork (banners, posters, fanart, clearlogo)
  - Cross-references (MAL, Kitsu, AniDB, IMDB, TVDB IDs, etc.)

No API key required. No rate limit documented (just4anime.online uses
this same endpoint in production for millions of requests).

We add a simple in-memory TTL cache so repeat requests for the same
anime are instant (no network call). Cache lives for the process
lifetime — no external database, no disk persistence. If the process
restarts, the cache rebuilds naturally.
"""
from __future__ import annotations

import asyncio
import time
from typing import Optional

import httpx

ANIZIP_API = "https://api.ani.zip/mappings"
ANIZIP_TIMEOUT = 15.0
ANIZIP_TTL = 7 * 24 * 3600  # 7 days (same as just4anime)

# Simple in-memory TTL cache: {anilist_id: (expires_monotonic, data)}
_cache: dict[int, tuple[float, dict]] = {}
_locks: dict[int, asyncio.Lock] = {}


def _cache_get(anilist_id: int) -> Optional[dict]:
    entry = _cache.get(anilist_id)
    if entry and time.monotonic() < entry[0]:
        return entry[1]
    if entry:
        _cache.pop(anilist_id, None)
    return None


def _cache_set(anilist_id: int, data: dict) -> None:
    _cache[anilist_id] = (time.monotonic() + ANIZIP_TTL, data)


def _normalize_anizip_response(raw: dict, anilist_id: int) -> dict:
    """
    Convert AniZip's raw response into the same shape as just4anime's API
    so the frontend can consume both interchangeably.

    Output:
    {
      "id": "154587",
      "malId": 52991,
      "title": "Frieren: Beyond Journey's End",
      "titleJa": "葬送のフリーレン",
      "totalEpisodes": 28,
      "currentEpisode": 28,
      "nextAiringEpisode": null,
      "nextAiringDate": null,
      "images": [{coverType, url}, ...],
      "episodes": [
        {
          "id": "154587-1",
          "number": 1,
          "title": "The Journey's End",
          "titleJa": "冒険の終わり",
          "description": "...",
          "image": "https://artworks.thetvdb.com/...",
          "airDate": "2023-09-29",
          "duration": 26,
          "isFiller": false,
          "rating": null,
          "hasAired": true
        },
        ...
      ],
      "mappings": {anilist_id, mal_id, thetvdb_id, ...}
    }
    """
    titles = raw.get("titles", {}) or {}
    episodes_map = raw.get("episodes", {}) or {}
    images = raw.get("images", []) or []
    mappings = raw.get("mappings", {}) or {}

    # Build episodes list (only S01E* — skip specials)
    episodes = []
    for ep_key in sorted(episodes_map.keys(), key=lambda k: int(k) if k.isdigit() else 99999):
        ep = episodes_map[ep_key]
        # Only include S01E* episodes (skip S00 specials)
        if ep.get("seasonNumber", 1) != 1:
            continue
        num = ep.get("absoluteEpisodeNumber") or ep.get("episodeNumber")
        if num is None:
            continue
        ep_titles = ep.get("title", {}) or {}
        # Determine if aired
        air_date = ep.get("airDate", "")
        has_aired = bool(air_date) and air_date <= time.strftime("%Y-%m-%d")
        episodes.append({
            "id": f"{anilist_id}-{num}",
            "number": num,
            "title": ep_titles.get("en") or ep_titles.get("x-jat") or "",
            "titleJa": ep_titles.get("ja") or "",
            "description": ep.get("overview", "") or "",
            "image": ep.get("image", "") or "",
            "airDate": air_date or "",
            "duration": ep.get("runtime", 0) or 0,
            "isFiller": bool(ep.get("filler", False)),
            "rating": str(ep.get("rating")) if ep.get("rating") else None,
            "hasAired": has_aired,
            "tvdbEpisodeId": ep.get("tvdbId"),
        })

    total = len(episodes)
    # Determine current episode (last aired)
    current_ep = None
    next_airing_ep = None
    next_airing_date = None
    today = time.strftime("%Y-%m-%d")
    for ep in episodes:
        if ep["hasAired"]:
            current_ep = ep["number"]
        else:
            next_airing_ep = ep["number"]
            next_airing_date = ep["airDate"]
            break

    return {
        "id": str(anilist_id),
        "malId": mappings.get("mal_id"),
        "title": titles.get("en") or titles.get("x-jat") or "",
        "titleJa": titles.get("ja") or "",
        "totalEpisodes": total,
        "currentEpisode": current_ep,
        "nextAiringEpisode": next_airing_ep,
        "nextAiringDate": next_airing_date,
        "images": images,
        "episodes": episodes,
        "mappings": mappings,
    }


async def fetch_anizip(anilist_id: int, client: Optional[httpx.AsyncClient] = None) -> dict:
    """
    Fetch AniZip mappings for an AniList ID.
    Uses in-memory cache + per-id lock to dedupe concurrent requests.

    Returns a normalized dict (see _normalize_anizip_response).
    On failure, returns {"id": str(anilist_id), "episodes": [], "images": [],
    "error": "..."} — never raises so callers can use it as enrichment.
    """
    # Cache hit
    cached = _cache_get(anilist_id)
    if cached is not None:
        return cached

    # Per-id lock so concurrent requests for the same ID only hit AniZip once
    if anilist_id not in _locks:
        _locks[anilist_id] = asyncio.Lock()
    async with _locks[anilist_id]:
        # Check cache again inside the lock (another request may have populated it)
        cached = _cache_get(anilist_id)
        if cached is not None:
            return cached

        # Fetch from AniZip
        try:
            close_client = False
            if client is None:
                client = httpx.AsyncClient(timeout=ANIZIP_TIMEOUT)
                close_client = True
            try:
                res = await client.get(
                    ANIZIP_API,
                    params={"anilist_id": anilist_id},
                    headers={"Accept": "application/json", "User-Agent": "miruro-api-cf/3.2"},
                )
                if res.status_code != 200:
                    result = {
                        "id": str(anilist_id),
                        "malId": None,
                        "title": "",
                        "titleJa": "",
                        "totalEpisodes": 0,
                        "currentEpisode": None,
                        "nextAiringEpisode": None,
                        "nextAiringDate": None,
                        "images": [],
                        "episodes": [],
                        "mappings": {},
                        "error": f"AniZip returned HTTP {res.status_code}",
                    }
                else:
                    raw = res.json()
                    if not raw or "episodes" not in raw:
                        result = {
                            "id": str(anilist_id),
                            "malId": None,
                            "title": "",
                            "titleJa": "",
                            "totalEpisodes": 0,
                            "currentEpisode": None,
                            "nextAiringEpisode": None,
                            "nextAiringDate": None,
                            "images": [],
                            "episodes": [],
                            "mappings": {},
                            "error": "AniZip returned empty/invalid response",
                        }
                    else:
                        result = _normalize_anizip_response(raw, anilist_id)
            finally:
                if close_client:
                    await client.aclose()
        except Exception as e:
            result = {
                "id": str(anilist_id),
                "malId": None,
                "title": "",
                "titleJa": "",
                "totalEpisodes": 0,
                "currentEpisode": None,
                "nextAiringEpisode": None,
                "nextAiringDate": None,
                "images": [],
                "episodes": [],
                "mappings": {},
                "error": f"AniZip fetch failed: {e}",
            }

        # Cache even errors for a short time (60s) to avoid hammering on failure
        if "error" in result:
            _cache[anilist_id] = (time.monotonic() + 60, result)
        else:
            _cache_set(anilist_id, result)
        return result


def cache_stats() -> dict:
    """Return cache stats for /cf/status or debugging."""
    now = time.monotonic()
    valid = sum(1 for exp, _ in _cache.values() if exp > now)
    return {
        "entries": valid,
        "ttl_seconds": ANIZIP_TTL,
    }
