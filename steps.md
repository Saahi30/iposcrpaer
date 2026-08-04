# Steps: Use scraped IPO data on your own website

Agent instructions for wiring **this repo’s JSON output** into any website (static, Next.js, React, WordPress, etc.). Follow the steps in order. Do not invent alternate scrape pipelines unless the user asks — consume the JSON this project already produces.

---

## Goal

1. Run (or schedule) the scrapers so fresh IPO JSON lands in `output/` (and optionally `web/data/`).
2. Serve or copy that JSON into the user’s site.
3. Build UI that reads the documented schemas below (list, detail, **calendar**, **timetable** as needed).
4. Keep data fresh via cron / GitHub Actions / deploy hook.

---

## 0. Repo facts (read first)

| Item | Value |
|------|--------|
| List + detail scraper | `scrape_chittorgarh.py` (Python 3.10+, **stdlib only** — no pip deps required) |
| Calendar + timetable scraper | `scrape_calendar_timetable.py` (stdlib only; imports helpers from `scrape_chittorgarh.py`) |
| Detail page HTML parser | `detail_parser.py` (imported by the list scraper) |
| List feed output | `output/ipos.json` |
| Per-status splits (optional) | `output/open.json`, `upcoming.json`, `closed.json`, `listed.json` |
| Detail files | `output/details/{slug}.json` |
| **IPO calendar output** | `output/ipo-calendar.json` (also synced → `web/data/ipo-calendar.json`) |
| **IPO timetable output** | `output/ipo-timetable.json` (also synced → `web/data/ipo-timetable.json`) |
| Static demo site | `web/` (reads `web/data/ipos.json` + `web/data/details/`; calendar/timetable JSON available for consumers) |
| Auto-sync | After a successful scrape write, scrapers copy outputs → `web/data/` |
| Existing CI | `.github/workflows/refresh-ipos.yml` (list+details **and** calendar+timetable every 6h → commit → GitHub Pages) |
| Local preview | `python serve.py` → `http://localhost:5173/web/` |

### Data sources (do not re-scrape these from the browser)

| Feed | Upstream source | How this repo gets it |
|------|-----------------|------------------------|
| IPO list + GMP | Chittorgarh list API + InvestorGain GMP API | `scrape_chittorgarh.py` |
| IPO detail pages | `chittorgarh.com/ipo/{slug}/{id}/` | `scrape_chittorgarh.py --details` |
| **Mainboard calendar** | [ipo-calendar/1](https://www.chittorgarh.com/calendar/ipo-calendar/1/) | `scrape_calendar_timetable.py` (HTML) |
| **SME calendar** | [sme-ipo-calendar/2](https://www.chittorgarh.com/calendar/sme-ipo-calendar/2/) | same script |
| **IPO timetable** | [report 118](https://www.chittorgarh.com/report/ipo-list-by-time-table-and-lot-size/118/mainboard/) via `webnodejs.chittorgarh.com/.../data-read/118/...` | same script |

**Canonical scrape commands (recommended for a live IPO site):**

```bash
# 1) List + details (cards, GMP, subscription, detail pages)
python scrape_chittorgarh.py \
  --status open,upcoming \
  --details \
  --out output/ipos.json \
  --split \
  --out-dir output

# 2) Calendar + timetable (two separate JSON files)
python scrape_calendar_timetable.py \
  --months 2 \
  --calendar-out output/ipo-calendar.json \
  --timetable-out output/ipo-timetable.json
```

That writes list/splits/details **and** calendar/timetable JSON, and mirrors them into `web/data/` for static hosting.

Join key across all feeds: prefer `slug` (e.g. `dhoot-transmission-ipo`), fallback `ipoId`.

---

## 1. Clarify the user’s site setup

Ask or infer:

1. **Stack** — static HTML, Next.js/React/Vue, WordPress, etc.
2. **Where the scraper lives** — same repo as the site, separate data repo, or CI-only.
3. **How the site should get JSON** — one of:
   - **A. Bundled static files** (copy `output/` or `web/data/` into `public/` / `static/` at build)
   - **B. Public URL** (GitHub Pages / raw.githubusercontent / CDN / S3)
   - **C. Own API** (server reads JSON files or DB synced from scrape)
4. **Pages needed** — list only, list + detail, and/or **calendar** / **timetable**.
5. **Refresh cadence** — manual, hourly, every 6h (matches existing workflow), daily.

Default if unspecified: **A + scheduled scrape**, list + detail + calendar + timetable, open + upcoming for the list feed.

---

## 2. Produce the data

### 2.1 One-time / local

```bash
# From this repo root
python scrape_chittorgarh.py --status open,upcoming --details --out output/ipos.json --split
python scrape_calendar_timetable.py --months 2
```

Verify:

- `output/ipos.json` has `scrapedAt`, `summary`, `ipos[]`
- Each list item with details has `"hasDetail": true` and `"detailPath": "details/{slug}.json"`
- `output/details/{slug}.json` exists for those items
- `output/ipo-calendar.json` has `scrapedAt`, `summary`, `events[]` (and `calendar[]` by month)
- `output/ipo-timetable.json` has `scrapedAt`, `summary`, `ipos[]` with `dates.open/close/allotment/refunds/listing`
- `web/data/` mirrors the same files (`ipos.json`, `details/`, `ipo-calendar.json`, `ipo-timetable.json`)

Useful flags for calendar/timetable:

```bash
python scrape_calendar_timetable.py --month 8 --year 2026          # specific month
python scrape_calendar_timetable.py --months 3                     # current + next 2 months
python scrape_calendar_timetable.py --calendar-only                # only ipo-calendar.json
python scrape_calendar_timetable.py --timetable-only               # only ipo-timetable.json
python scrape_calendar_timetable.py --no-sync-web                  # skip web/data copy
```

### 2.2 Keep it fresh (pick one)

**Option A — GitHub Actions in this repo (already present)**  
Use `.github/workflows/refresh-ipos.yml`. It runs **both** scrapers (list+details, then calendar+timetable with `--months 2`). Enable Actions + Pages if deploying `web/`. Data is committed to `output/` and `web/data/`.

**Option B — Cron / scheduled job on a server**

```bash
cd /path/to/iposcrpaer
python scrape_chittorgarh.py --status open,upcoming --details --out output/ipos.json --split
python scrape_calendar_timetable.py --months 2
# then sync files to the website (rsync, S3, git push, etc.)
```

**Option C — Site build step**  
On each deploy, clone/pull this data repo (or copy artifacts) and place JSON under the site’s public data folder. Prefer a scheduled scrape *before* build if scrape is slow (`--details` hits one page per IPO).

**Do not** scrape on every visitor request. Cache files; refresh on a schedule.

---

## 3. Deliver JSON to the website

### Path A — Copy into the site (simplest)

After scrape, copy:

```
web/data/ipos.json            →  <site>/public/data/ipos.json   (or /static/data/...)
web/data/details/*.json       →  <site>/public/data/details/
web/data/ipo-calendar.json    →  <site>/public/data/ipo-calendar.json
web/data/ipo-timetable.json   →  <site>/public/data/ipo-timetable.json
```

Or copy from `output/` the same layout. Frontend fetches:

- List: `/data/ipos.json`
- Detail: `/data/details/{slug}.json`
- Calendar: `/data/ipo-calendar.json`
- Timetable: `/data/ipo-timetable.json`

### Path B — Host JSON separately

1. Deploy `web/data/` (or `output/`) to GitHub Pages, Cloudflare R2, S3+CDN, etc.
2. Site fetches absolute URLs, e.g. `https://cdn.example.com/ipos.json`.
3. If cross-origin, enable CORS on the host (`Access-Control-Allow-Origin`).
4. Handle caching: prefer short CDN TTL or cache-bust with `?t=` from `scrapedAt`.

### Path C — Backend / CMS

1. Scheduled job reads `ipos.json` (+ details) and optionally `ipo-calendar.json` / `ipo-timetable.json`.
2. Upsert into DB/CMS keyed by `slug` or `ipoId` (calendar rows also have `eventId`).
3. Expose REST/GraphQL shaped for the UI (or return the JSON as-is).
4. Store `scrapedAt` so the UI can show “Updated …”.

### Reference UI in this repo

If the user wants a working baseline UI, start from:

- List: `web/index.html` + `web/app.js` + `web/styles.css`
- Detail: `web/ipo.html` + `web/detail.js` + `web/detail.css`
- Calendar / timetable: **no dedicated demo pages yet** — wire new routes against the JSON schemas in §6–§7.

`web/app.js` loads `./data/ipos.json`.  
`web/detail.js` loads `./data/details/${slug}.json` via `?slug=...`.

Adapt styles to the user’s brand; keep the fetch + field mapping.

---

## 4. Implement the list page

### 4.1 Fetch

```js
const res = await fetch("/data/ipos.json"); // or remote URL
const data = await res.json();
const ipos = data.ipos ?? [];
```

Show `data.scrapedAt` as last-updated. Use `data.summary` for counts (`open`, `upcoming`, `closed`, `listed`, `total`).

### 4.2 Filter / sort

Useful client filters (match demo):

- `ipo.status` — `open` | `upcoming` | `closed` | `listed`
- `ipo.type` — `mainboard` | `sme`
- text search on `name`, `exchange`, `leadManager`, `slug`

Default sort in the file is already scraper-ordered (open first, then by dates). Preserve unless the product needs otherwise.

### 4.3 Card fields (list item schema)

Each `ipos[]` entry typically includes:

| Field | Type / notes |
|-------|----------------|
| `slug` | string — primary key for detail route |
| `ipoId` | number |
| `name` | string |
| `type` | `mainboard` \| `sme` |
| `status` | `open` \| `upcoming` \| `closed` \| `listed` |
| `exchange` | e.g. `BSE SME`, `NSE` |
| `pricingMethod` | e.g. Bookbuilding |
| `priceBand.min` / `.max` / `.display` | numbers + display string |
| `lotSize` | number |
| `issueSize` / `issueSizeCr` | string / number |
| `freshIssueCr` / `ofsCr` | numbers (may be null) |
| `dates.open` / `.close` / `.allotment` / `.listing` | `YYYY-MM-DD` or null |
| `gmp.value` / `.percent` / `.xLot` / `.updatedOn` | numbers / string; gmp may be sparse |
| `subscription.total` | number (times subscribed) |
| `subscription.byCategory` | array of objects (table rows) |
| `leadManager` | string |
| `logo` | absolute image URL (hotlinked; consider proxy/cache) |
| `hasDetail` | boolean |
| `detailPath` | e.g. `details/{slug}.json` |
| `urls.chittorgarh` / `urls.gmp` / `urls.local` | links |
| `about` | short company blurb (when `--details` ran) |
| `registrar` | string (when enriched) |

Link each card to the site’s detail route using `slug` (do not rely on `urls.local` — that points at this repo’s `ipo.html`).

---

## 5. Implement the detail page

### 5.1 Routing

- Static: `/ipo.html?slug={slug}` or `/ipo/{slug}.html`
- SPA/Next: `/ipo/[slug]` → fetch `/data/details/{slug}.json`

If `hasDetail` is false or the file 404s, show a soft empty state and still render list fields from `ipos.json` if available.

### 5.2 Fetch

```js
const slug = /* from route or query */;
const res = await fetch(`/data/details/${slug}.json`);
if (!res.ok) throw new Error("Detail not found");
const detail = await res.json();
```

### 5.3 Detail schema (top-level keys)

| Key | Contents |
|-----|----------|
| `slug`, `ipoId`, `url`, `title` | identity + source page |
| `intro` | long plain-text summary |
| `summaryCards` | object of label → string |
| `issueDetails` | object (dates, price band, lot, listing) |
| `timetable` | object (category → share counts) — note: key name is historical; values are allocation counts (**not** the IPO timetable feed in §7) |
| `reservation` | array of row objects |
| `lotSizeTable` | array of row objects |
| `anchor` | object / nested data |
| `about` | object (company text) |
| `financials.periods` | string[] column headers |
| `financials.rows` | array of `{ Metric, ...period columns }` |
| `objectives` | string[] |
| `kpi` | array of row objects |
| `valuation` | object |
| `shareholding` | array |
| `promoters` | array |
| `review` | object (pros/cons style fields) |
| `registrar` | object |
| `leadManagers` | array |
| `contact` | object |
| `faqs` | array of `{ q, a }` or similar Q/A objects — inspect one sample file |
| `subscription` | category table + totals |
| `overview` | flattened snapshot overlapping list fields |
| `links` | RHP / related URLs |
| `scrapedAt` | ISO timestamp |

**Implementation tip:** For unknown table-shaped arrays, render generic HTML tables from `Object.keys(rows[0])` (see `web/detail.js` `tableHtml`). For plain objects, render key–value grids (`kvHtml`).

---

## 6. Implement the IPO calendar page

Use when the product needs a month view / “what’s opening or closing this week” UI. Prefer this feed over inventing events from list dates alone — it includes allotment-status style events from Chittorgarh’s calendars.

### 6.1 Fetch

```js
const res = await fetch("/data/ipo-calendar.json");
const data = await res.json();
const events = data.events ?? [];
// Or month-scoped:
// const monthBlock = data.calendar?.[0];
// const byDate = monthBlock?.byDate ?? {};
```

Show `data.scrapedAt`. Use `data.summary` for totals (`totalEvents`, `mainboard`, `sme`, `byEventType`).

### 6.2 File shape

| Key | Contents |
|-----|----------|
| `scrapedAt` | ISO timestamp |
| `source.mainboard` / `source.sme` | Chittorgarh calendar base URLs |
| `months[]` | `{ year, month, label }` scraped month(s) |
| `summary` | counts by board + `byEventType` (`open` / `close` / `allotment` / …) |
| `calendar[]` | per-month blocks with `byDate`, `events`, `sources`, `summary` |
| `events[]` | flat list of all events (easiest for filters) |

### 6.3 Event fields

Each event in `events[]` / `calendar[].events[]` / `calendar[].byDate[YYYY-MM-DD][]`:

| Field | Type / notes |
|-------|----------------|
| `title` | e.g. `Dhoot Transmission IPO Opens on Aug 10, 2026` |
| `company` | short name derived from title |
| `eventType` | `open` \| `close` \| `allotment` \| `listing` \| `refund` \| `other` |
| `date` | `YYYY-MM-DD` (event day) |
| `dateEnd` | `YYYY-MM-DD` (usually same day) |
| `details` | short blurb (may be null) |
| `type` | `mainboard` \| `sme` |
| `slug` | join key to list/detail (`*-ipo`) |
| `ipoId` | number |
| `eventId` | Chittorgarh news/event id |
| `month` / `year` | calendar month this event was scraped under |
| `urls.news` | Chittorgarh `ipo_news/...` deep link |
| `urls.chittorgarh` | IPO detail page on Chittorgarh |
| `urls.googleCalendar` | optional Google Calendar template URL |

### 6.4 UI tips

- Month grid: use `calendar[i].byDate` (`YYYY-MM-DD` → events[]).
- Filters: `type` (mainboard/sme), `eventType`, text on `company` / `title`.
- Click-through: route to site detail via `slug` (same as list cards).
- If multiple months were scraped (`--months 2`), pick the block from `calendar[]` by `year`/`month`, or filter `events[]`.

---

## 7. Implement the IPO timetable page

Use for a table of opening / closing / allotment / listing dates (mainboard + SME). This is the structured counterpart to Chittorgarh’s [IPO Timetable report](https://www.chittorgarh.com/report/ipo-list-by-time-table-and-lot-size/118/mainboard/).

**Do not confuse** with `detail.timetable` inside detail JSON (§5) — that field is share-allocation counts, not this schedule feed.

### 7.1 Fetch

```js
const res = await fetch("/data/ipo-timetable.json");
const data = await res.json();
const rows = data.ipos ?? [];
```

Show `data.scrapedAt`, `data.year`, `data.financialYear`. Use `data.summary` (`total`, `mainboard`, `sme`).

### 7.2 Row fields

Each `ipos[]` entry:

| Field | Type / notes |
|-------|----------------|
| `ipoId` | number |
| `name` | company name |
| `slug` | join key to list/detail |
| `type` | `mainboard` \| `sme` |
| `dates.open` / `.close` / `.allotment` / `.refunds` / `.listing` | `YYYY-MM-DD` or `null` |
| `displayDates.*` | original display strings (e.g. `10-Aug-2026`) |
| `logo` | absolute image URL (may be null) |
| `urls.chittorgarh` | IPO page |
| `urls.timetablePage` | source timetable page for that board |

Rows are sorted by `dates.open` ascending, then name. `listing` is often `null` until published upstream.

### 7.3 UI tips

- Default table columns: Company, Type, Open, Close, Allotment, Refunds, Listing.
- Filters: `type`, date range on `dates.open` / `dates.close`, text search on `name` / `slug`.
- Link company → site detail via `slug`; optionally enrich with GMP/status from `ipos.json` using the same `slug`.

---

## 8. Stack-specific recipes

### Static HTML (like `web/`)

1. Copy `web/` as a starting point or rebuild pages.
2. Ensure `data/ipos.json`, `data/details/`, and (if used) `data/ipo-calendar.json` + `data/ipo-timetable.json` sit next to the HTML.
3. Deploy folder to Netlify / Cloudflare Pages / S3 / GitHub Pages.
4. Schedule scrape elsewhere; sync `data/` into the deploy on each refresh.

### Next.js / React

1. Put JSON in `public/data/` **or** fetch remote URL in `useEffect` / RSC.
2. List page: client or server component reading `ipos.json`.
3. `app/ipo/[slug]/page.tsx`: `fetch(`${origin}/data/details/${slug}.json`)` or `fs.readFile` at build time.
4. Calendar: `/calendar` → `ipo-calendar.json`. Timetable: `/timetable` → `ipo-timetable.json`.
5. If SSG: regenerate on a schedule (ISR `revalidate: 21600` for 6h) pointing at the JSON URL — do not re-scrape inside Next.

### WordPress / PHP

1. Upload JSON to the media library or `wp-content/uploads/ipo-data/`.
2. Shortcode or theme template: `file_get_contents` / HTTP get → `json_decode` → render.
3. Cron: WP-Cron or server cron that pulls latest files from the scraper host.

---

## 9. Wire refresh into the user’s project

Checklist for the agent:

1. [ ] Scrape commands documented in the site README or `package.json` script / Makefile (`scrape_chittorgarh.py` **and** `scrape_calendar_timetable.py` if calendar/timetable are used).
2. [ ] Copy/sync step: `output` or `web/data` → site public data path (include `ipo-calendar.json` / `ipo-timetable.json` when relevant).
3. [ ] CI or cron runs scrape + sync + deploy (or commit data). Existing workflow already runs both scrapers.
4. [ ] Frontend shows `scrapedAt`.
5. [ ] Detail 404 handled.
6. [ ] Images: either hotlink `logo` URLs or download/cache (hotlinks can break).
7. [ ] Attribution: data is aggregated from third-party public pages (Chittorgarh / related feeds). Add a discreet source note if the product requires it; respect site ToS / robots for production commercial use.
8. [ ] Do not commit secrets; scraper needs none today.
9. [ ] Rate limits: scraper already pauses (`REQUEST_PAUSE_S`); do not parallel-hammer detail or calendar URLs.

Optional: extend `.github/workflows/refresh-ipos.yml` to also push/sync into the user’s website repo (e.g. `repository_dispatch`, rsync SSH, or upload artifact).

---

## 10. Acceptance tests

After implementation, verify:

1. List page loads and shows at least the open/upcoming IPOs from current `ipos.json`.
2. Search / status / type filters work.
3. Clicking an IPO opens detail and shows name, price band, dates, subscription or financials when present.
4. After re-running the scrape commands, a hard refresh shows new `scrapedAt` (and changed GMP/subscription if markets moved).
5. Missing detail file does not crash the app.
6. Mobile layout is usable.
7. **If calendar is wired:** `/data/ipo-calendar.json` loads; events show correct `date` + `eventType`; clicking an event reaches detail via `slug`.
8. **If timetable is wired:** `/data/ipo-timetable.json` loads; rows show open/close/allotment; mainboard vs SME filter works; `slug` links to detail.

Quick smoke against this repo’s demo:

```bash
python scrape_chittorgarh.py --status open,upcoming --details --out output/ipos.json
python scrape_calendar_timetable.py --months 2
python serve.py
# open http://localhost:5173/web/
# JSON: http://localhost:5173/web/data/ipo-calendar.json
#       http://localhost:5173/web/data/ipo-timetable.json
```

---

## 11. What not to do

- Do not scrape Chittorgarh HTML/API from the browser on every page view.
- Do not require npm packages for the scrapers; Python stdlib is enough.
- Do not rename JSON field names in the scrapers for one site — map in the UI instead so CI/other consumers stay compatible.
- Do not treat GMP as advice; it is unofficial grey-market chatter.
- Do not confuse detail-page `timetable` (allocation counts) with `ipo-timetable.json` (schedule dates).
- Do not rebuild calendar events only from list `dates.*` if `ipo-calendar.json` exists — the calendar feed includes extra event types (e.g. allotment status).
- Do not block the user’s deploy on a full `--details` scrape if they only need the list; list-only is:

  ```bash
  python scrape_chittorgarh.py --status open,upcoming --out output/ipos.json
  ```

  Calendar/timetable-only (no list scrape):

  ```bash
  python scrape_calendar_timetable.py --months 2
  ```

---

## 12. Minimal implementation order (agent checklist)

1. Run list scrape once; confirm `output/ipos.json` + optional `output/details/`.
2. Run `python scrape_calendar_timetable.py --months 2`; confirm `output/ipo-calendar.json` + `output/ipo-timetable.json`.
3. Copy JSON into the site’s public data directory (or set remote URL).
4. Build list UI bound to `data.ipos` + `scrapedAt`.
5. Build detail route bound to `details/{slug}.json`.
6. If requested: calendar UI → `ipo-calendar.json`; timetable UI → `ipo-timetable.json` (join on `slug`).
7. Add scheduled refresh + sync/deploy (both scrapers).
8. Match acceptance tests in §10.
9. Stop — polish design only if the user asks.

When unsure about a field, open one real file under `output/ipos.json`, `output/details/*.json`, `output/ipo-calendar.json`, or `output/ipo-timetable.json` and map from the live sample rather than guessing.
