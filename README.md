<div align="center">
  <img src="https://www.miruro.to/assets/logo-Dnw3w3dS.png?v=1.12.0" alt="Miruro API" width="150" style="border-radius: 20%; box-shadow: 0 0 20px rgba(56, 189, 248, 0.5);">
  <br><br>
  
  # Miruro API v3.0
  
  **The ultimate, decrypted, and fully reverse-engineered native Python backend for Miruro.**
  
  [https://github.com/walterwhite-69/Miruro-API](https://github.com/walterwhite-69/Miruro-API)
</div>

<br>

---

## ⚠️ Cloudflare Notice (Important)

Miruro's pipe endpoint (`/api/secure/pipe`) is now protected by **Cloudflare**.

- **Do NOT host on Vercel** — Vercel uses datacenter IPs that are hard-blocked by Cloudflare's WAF. Requests to the pipe will always return `403`.
- **Do NOT host on Render free tier, Railway, or similar PaaS** — same problem; shared datacenter IPs get blocked.
- ✅ **Host on a VPS** (DigitalOcean, Hetzner, Linode, Vultr, etc.) with a clean non-datacenter IP, or run locally on your own machine.

The API uses **`curl_cffi`** with Chrome TLS fingerprinting and proper same-origin headers to bypass Cloudflare's bot detection. This works from residential and most VPS IPs, but not from known datacenter ranges.

---

## 🛡️ Cloudflare Bypass Panel (New in v3.0)

The homepage now has a **"Cloudflare Bypass"** panel with three buttons:

| Button | What it does |
|---|---|
| **▶ Get CF Cookie** | Launches a real Google Chrome (via `botasaurus`) in the background, navigates to `miruro.tv`, solves Cloudflare's challenge, and captures the `cf_clearance` cookie + the User-Agent that earned it. Saved to disk so it survives restarts. |
| **■ Stop Browser** | Kills the background browser process immediately. Use this as soon as the cookie is captured — the API stays lightweight afterwards. |
| **✕ Forget Cookie** | Clears the stored cookie (forces re-fetch on next `/episodes` call). |

### How it works

1. Click **Get CF Cookie** → a real Chrome opens in the background (uses Xvfb on Linux servers, no display needed)
2. Watch the live log on the homepage — it shows browser progress (`Loaded: Just a moment...` → `cf_clearance captured after 1s`)
3. Once captured, the cookie is used automatically for all `/episodes/{id}`, `/sources`, and `/watch/{...}` requests
4. Click **Stop Browser** to kill the browser process — the API stays lightweight, using `curl_cffi` with the saved cookie for all subsequent requests
5. The cookie lasts ~25 minutes; when it expires, just click **Get CF Cookie** again

### Manual fallback

If the auto-bypass fails in your environment (e.g. very strict CF WAF on your IP), the panel has a **"Manual paste"** section. Open `miruro.tv` in your own browser, solve the challenge, then copy the `cf_clearance` cookie value from DevTools → Application → Cookies and paste it into the panel.

### API endpoints

| Endpoint | Method | Description |
|---|---|---|
| `/cf/get` | POST | Launch the browser to fetch a fresh `cf_clearance` |
| `/cf/status` | GET | Combined view of solver state + stored cookie state |
| `/cf/stop` | POST | Kill any running browser process |
| `/cf/manual` | POST | Manually paste a `cf_clearance` value (body: `{value, user_agent?}`) |
| `/cf/token` | DELETE | Forget the stored cookie |

---

## What This Does

Miruro's frontend communicates with its backend through a `secure/pipe` tunnel that base64-encodes, gzip-compresses, and encrypts every request. This project bypasses all of that and gives you simple, direct REST endpoints to:

1. **Search & filter** anime with full AniList metadata
2. **Get complete anime info** — characters, staff, relations, recommendations, trailer, stats, and all metadata in one request
3. **Browse collections** — trending, popular, upcoming, recent, schedule, and spotlight — all paginated
4. **List episodes** with decoded episode IDs from multiple providers
5. **Get M3U8 streaming URLs** for any episode
6. **Autocomplete** search suggestions for dropdown UIs

No headless browsers, no Selenium — just lightweight async HTTP requests.

<br>

## Setup

```bash
git clone https://github.com/walterwhite-69/Miruro-API.git
cd Miruro-API
pip install -r requirements.txt
uvicorn api:app --host 0.0.0.0 --port 8000
```

Then open `http://localhost:8000/` for interactive API docs.

> **Windows users:** If you see a `RuntimeWarning` about `Proactor event loop`, that's a harmless `curl_cffi` warning — the API works fine.

<br>

## All Endpoints

### 🔍 Search & Discovery

| Endpoint | Description | Params |
|---|---|---|
| `GET /search?query={name}` | Full-text anime search with rich metadata (20+ fields per result) | `query` (required), `page`=1, `per_page`=20 |
| `GET /suggestions?query={name}` | Lightweight autocomplete for dropdowns — returns id, title, poster, format, status, year. Max 8 results. | `query` (required) |
| `GET /filter` | Advanced browse/filter by any combination of genre, tag, year, season, format, status, sort | All optional — see below |

#### Filter Parameters

| Param | Values |
|---|---|
| `genre` | Action, Romance, Comedy, Drama, Fantasy, Sci-Fi, etc. |
| `tag` | Isekai, Time Skip, Reincarnation, etc. |
| `year` | 2025, 2024, etc. |
| `season` | WINTER · SPRING · SUMMER · FALL |
| `format` | TV · MOVIE · OVA · ONA · SPECIAL |
| `status` | RELEASING · FINISHED · NOT_YET_RELEASED · CANCELLED |
| `sort` | SCORE_DESC · POPULARITY_DESC · TRENDING_DESC · START_DATE_DESC |
| `page` / `per_page` | Pagination (defaults: 1 / 20, max per_page: 50) |

---

### 📊 Collections (All Paginated)

| Endpoint | Description |
|---|---|
| `GET /trending` | Currently trending anime |
| `GET /popular` | Most popular anime of all time |
| `GET /upcoming` | Most anticipated upcoming anime |
| `GET /recent` | Currently airing / this season's anime |
| `GET /spotlight` | Curated "What's Hot" list (trending + popular) |
| `GET /schedule` | Airing schedule for the next week |

All collection endpoints accept `page` and `per_page` query params and return:

```json
{
  "page": 1,
  "perPage": 20,
  "total": 5000,
  "hasNextPage": true,
  "results": [ ... ]
}
```

Each anime in `results` includes 20+ fields: title (romaji/english/native), coverImage, bannerImage, format, season, seasonYear, episodes, duration, status, averageScore, meanScore, popularity, favourites, genres, source, countryOfOrigin, studios, nextAiringEpisode, startDate, endDate, and more.

---

### 📖 Anime Details

| Endpoint | Description |
|---|---|
| `GET /info/{anilist_id}` | **Complete anime page** — everything in one request |
| `GET /anime/{id}/characters` | Paginated character list with voice actors |
| `GET /anime/{id}/relations` | All related media (sequels, prequels, side stories, spin-offs) |
| `GET /anime/{id}/recommendations` | Community recommendations sorted by rating |

#### What `/info/{id}` Returns

Everything you need to build a full anime detail page:

- **Core**: id, idMal, title (romaji/english/native), description, coverImage, bannerImage
- **Metadata**: format, season, seasonYear, episodes, duration, status, source, countryOfOrigin
- **Scores**: averageScore, meanScore, popularity, favourites, trending
- **Taxonomy**: genres, tags (with rank & spoiler flag), synonyms, hashtag
- **People**: characters (25, with voice actors), staff (25, with roles)
- **Related**: relations (sequels/prequels/etc.), recommendations (10, with ratings)
- **Media**: trailer (YouTube/Dailymotion), streamingEpisodes, externalLinks
- **Stats**: scoreDistribution, statusDistribution
- **Studios**: name, isAnimationStudio, siteUrl
- **Dates**: startDate, endDate, nextAiringEpisode
- **Links**: siteUrl, externalLinks (MAL, official site, etc.)

---

### ▶️ Streaming (3-Step Flow)

To get a video stream, follow these 3 steps in order:

#### Step 1: Get Episodes — `GET /episodes/{anilist_id}`

Returns all episodes from multiple providers (kiwi, arc, zoro, hop, etc.) organized by audio type.

```json
{
  "mappings": { "anilistId": 178005, "malId": 56885, "kitsuId": "..." },
  "providers": {
    "kiwi": {
      "episodes": {
        "sub": [
          {
            "id": "watch/kiwi/178005/sub/animepahe-1",
            "number": 1,
            "title": "Episode Title",
            "image": "https://...",
            "airDate": "2026-01-04",
            "duration": 1420,
            "description": "...",
            "filler": false
          }
        ],
        "dub": [ ... ]
      }
    },
    "arc": { ... },
    "zoro": { ... }
  }
}
```

#### Step 2: Get Sources [SUPER SIMPLE]

Just take the direct `id` from the Step 1 response and use it as the URL. No manual parameters or complex IDs needed!

**Endpoint:** `GET /{id}`  
**Example:** `GET /watch/kiwi/178005/sub/animepahe-1`

```json
{
  "streams": [
    { "url": "https://.../master.m3u8", "type": "hls", "quality": "1080p" }
  ],
  "subtitles": [
    { "file": "https://...", "label": "English", "kind": "captions" }
  ],
  "intro": { "start": 0, "end": 90 },
  "outro": { "start": 1300, "end": 1420 }
}
```

> [!TIP]
> This endpoint automatically handles decryption, provider selection, and category matching. It returns the direct M3U8/HLS streaming URL and intro/outro timestamps.

<details>
<summary><b>Fallback / Detailed Option</b></summary>
If you need manual control, you can use the traditional endpoint:
`GET /sources?episodeId=...&provider=...&anilistId=...&category=...`
</details>

#### Step 3: Play

Feed `streams[0].url` into any HLS player (Video.js, hls.js, VLC, mpv). Subtitles are either **hard-subbed** (baked into the video for kiwi/pahe) or provided in the `subtitles` array (VTT links for zoro/arc). Use `intro`/`outro` timestamps for skip buttons.

<br>

## How Cloudflare Bypass Works

The pipe endpoint at `miruro.tv/api/secure/pipe` is behind Cloudflare. The API bypasses it by:

1. Using **`curl_cffi`** with `chrome110` impersonation — this replicates Chrome's exact TLS fingerprint (JA3/JA4) at the socket level, making the request look indistinguishable from a real browser
2. Sending the correct **same-origin headers**: `sec-fetch-site: same-origin`, `sec-fetch-mode: cors`, `sec-fetch-dest: empty`, full `sec-ch-ua` stack, matching `Referer` and `Origin`

This approach works from **residential IPs and most VPS providers**. Cloudflare's hard block only applies to known datacenter/CDN IP ranges (Vercel, Render, AWS Lambda, Cloudflare Workers, etc.).

<br>

## Disclaimer

This project is for educational purposes and API integrity research only. The author takes absolutely zero responsibility for network usage. Code contains zero skiddable artifacts.

<br>

**Author:** Walter | **GitHub:** [walterwhite-69](https://github.com/walterwhite-69)
