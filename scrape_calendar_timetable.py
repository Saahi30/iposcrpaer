#!/usr/bin/env python3
"""
Scrape Chittorgarh IPO Calendar + IPO Timetable into two JSON files.

Sources:
  Mainboard calendar:
    https://www.chittorgarh.com/calendar/ipo-calendar/1/?month=M&year=Y
  SME calendar:
    https://www.chittorgarh.com/calendar/sme-ipo-calendar/2/?month=M&year=Y
  Timetable (report 118 API):
    https://webnodejs.chittorgarh.com/cloud/report/data-read/118/...
    (page: https://www.chittorgarh.com/report/ipo-list-by-time-table-and-lot-size/118/mainboard/)

Examples:
  python scrape_calendar_timetable.py
  python scrape_calendar_timetable.py --month 8 --year 2026
  python scrape_calendar_timetable.py --months 2
  python scrape_calendar_timetable.py --calendar-only
  python scrape_calendar_timetable.py --timetable-only
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import date, datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote

from scrape_chittorgarh import (
    LIST_HOST,
    REQUEST_PAUSE_S,
    SITE,
    ScrapeError,
    http_get,
    http_get_json,
    indian_fy,
    parse_date,
    strip_html,
    utc_now_iso,
    write_json,
)

CALENDAR_PAGES = {
    "mainboard": {
        "id": 1,
        "slug": "ipo-calendar",
        "url": f"{SITE}/calendar/ipo-calendar/1/",
    },
    "sme": {
        "id": 2,
        "slug": "sme-ipo-calendar",
        "url": f"{SITE}/calendar/sme-ipo-calendar/2/",
    },
}
TIMETABLE_PAGE = f"{SITE}/report/ipo-list-by-time-table-and-lot-size/118/"
EVENT_TYPE_PATTERNS = (
    (re.compile(r"\bopens?\b", re.I), "open"),
    (re.compile(r"\bcloses?\b", re.I), "close"),
    (re.compile(r"\ballotment\b", re.I), "allotment"),
    (re.compile(r"\blisting\b", re.I), "listing"),
    (re.compile(r"\brefund", re.I), "refund"),
)


def calendar_page_url(kind: str, month: int, year: int) -> str:
    meta = CALENDAR_PAGES[kind]
    return f"{SITE}/calendar/{meta['slug']}/{meta['id']}/?month={month}&year={year}"


def timetable_url(category: str = "all") -> str:
    year, month, fy = indian_fy()
    return (
        f"{LIST_HOST}/cloud/report/data-read/118/1/{month}/{year}/{fy}/0/"
        f"{category}/0?search=&v=14-08"
    )


def infer_event_type(title: str) -> str:
    for pattern, label in EVENT_TYPE_PATTERNS:
        if pattern.search(title):
            return label
    return "other"


def parse_gcal_dates(raw: str) -> tuple[str | None, str | None]:
    """Google Calendar dates=YYYYMMDD/YYYYMMDD (end exclusive) -> ISO dates."""
    m = re.match(r"^(\d{8})(?:/(\d{8}))?$", (raw or "").strip())
    if not m:
        return None, None
    start = datetime.strptime(m.group(1), "%Y%m%d").date().isoformat()
    end = None
    if m.group(2):
        end_excl = datetime.strptime(m.group(2), "%Y%m%d").date()
        # Google end date is exclusive for all-day events
        end = date.fromordinal(end_excl.toordinal() - 1).isoformat()
        if end < start:
            end = start
    return start, end


def company_name_from_title(title: str) -> str:
    text = title.strip()
    text = re.sub(
        r"\s+IPO\s+(Opens?|Closes?|Allotment Status|Listing|Refunds?).*$",
        "",
        text,
        flags=re.I,
    )
    text = re.sub(r"\s+IPO$", "", text, flags=re.I)
    return text.strip() or title.strip()


def decode_rsc_url(raw: str) -> str:
    text = raw.replace("\\u0026", "&").replace("\\/", "/")
    return strip_html(text)


def _title_from_rsc(raw: str) -> str:
    text = strip_html(raw.replace("\\u0026", "&").replace("\\/", "/"))
    # RSC/HTML dumps sometimes leave a trailing escaped backslash on titles.
    return text.rstrip("\\").strip()


def build_title_news_index(html: str) -> dict[str, dict[str, Any]]:
    """Map event title -> {slug, ipoId, eventId} using co-located news links."""
    index: dict[str, dict[str, Any]] = {}

    def add(title: str, slug: str, ipo_id_s: str, event_id_s: str) -> None:
        title = _title_from_rsc(title)
        if not title or "IPO" not in title.upper():
            return
        if not (ipo_id_s.isdigit() and event_id_s.isdigit()):
            return
        index.setdefault(
            title,
            {
                "slug": slug,
                "ipoId": int(ipo_id_s),
                "eventId": int(event_id_s),
            },
        )

    # Live HTML: <a title="..." href="https://www.chittorgarh.com/ipo_news/slug/id/#eid">
    for m in re.finditer(
        r'title="([^"]+)"[^>]{0,240}?href="https://www\.chittorgarh\.com/ipo_news/'
        r'([a-z0-9-]+)/(\d+)/#(\d+)"',
        html,
        flags=re.I | re.S,
    ):
        add(m.group(1), m.group(2), m.group(3), m.group(4))

    # RSC payload: href then children title
    for m in re.finditer(
        r'href\\?":\\?"https://www\.chittorgarh\.com/ipo_news/'
        r'([a-z0-9-]+)/(\d+)/#(\d+)\\?"'
        r'.{0,300}?children\\?":\\?"([^"]+)\\?"',
        html,
        flags=re.I | re.S,
    ):
        add(m.group(4), m.group(1), m.group(2), m.group(3))

    return index


def date_from_title(title: str) -> str | None:
    dm = re.search(
        r"\b((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{1,2},\s+\d{4})\b",
        title,
        flags=re.I,
    )
    if not dm:
        return None
    for fmt in ("%b %d, %Y", "%B %d, %Y"):
        try:
            return datetime.strptime(dm.group(1), fmt).date().isoformat()
        except ValueError:
            continue
    return None


def parse_calendar_html(html: str, *, kind: str, month: int, year: int) -> list[dict[str, Any]]:
    """Extract calendar events from Chittorgarh Next.js calendar HTML."""
    news_by_title = build_title_news_index(html)
    events_by_key: dict[tuple[str, str], dict[str, Any]] = {}

    # Primary source: Google Calendar links (authoritative title/date/details).
    for m in re.finditer(
        r'https://www\.google\.com/calendar/render\?([^"\'\\\s]+)',
        html,
    ):
        query = decode_rsc_url(m.group(1).replace("&amp;", "&"))
        qs = parse_qs(query)
        title = unquote((qs.get("text") or [""])[0]).strip()
        if not title:
            continue
        date_start, date_end = parse_gcal_dates((qs.get("dates") or [""])[0])
        if not date_start:
            continue
        details = strip_html(unquote((qs.get("details") or [""])[0]))
        news = news_by_title.get(title) or {}
        slug = news.get("slug")
        ipo_id = news.get("ipoId")
        event_id = news.get("eventId")
        key = (title, date_start)
        # Prefer the first complete record; skip list/grid duplicates.
        if key in events_by_key:
            continue
        events_by_key[key] = {
            "title": title,
            "company": company_name_from_title(title),
            "eventType": infer_event_type(title),
            "date": date_start,
            "dateEnd": date_end,
            "details": details or None,
            "type": kind,
            "slug": slug,
            "ipoId": ipo_id,
            "eventId": event_id,
            "month": month,
            "year": year,
            "urls": {
                "news": (
                    f"{SITE}/ipo_news/{slug}/{ipo_id}/#{event_id}"
                    if slug and ipo_id and event_id
                    else None
                ),
                "chittorgarh": (
                    f"{SITE}/ipo/{slug}/{ipo_id}/" if slug and ipo_id else None
                ),
                "googleCalendar": f"https://www.google.com/calendar/render?{query}",
            },
        }

    # Fallback: titled news anchors with no Google Calendar twin.
    for title, news in news_by_title.items():
        event_date = date_from_title(title)
        key = (title, event_date or "")
        if any(t == title for t, _d in events_by_key):
            continue
        slug = news["slug"]
        ipo_id = news["ipoId"]
        event_id = news["eventId"]
        events_by_key[key] = {
            "title": title,
            "company": company_name_from_title(title),
            "eventType": infer_event_type(title),
            "date": event_date,
            "dateEnd": event_date,
            "details": None,
            "type": kind,
            "slug": slug,
            "ipoId": ipo_id,
            "eventId": event_id,
            "month": month,
            "year": year,
            "urls": {
                "news": f"{SITE}/ipo_news/{slug}/{ipo_id}/#{event_id}",
                "chittorgarh": f"{SITE}/ipo/{slug}/{ipo_id}/",
                "googleCalendar": None,
            },
        }

    events = list(events_by_key.values())
    events.sort(key=lambda e: (e.get("date") or "9999-99-99", e.get("title") or ""))
    return events


def fetch_calendar_month(kind: str, month: int, year: int) -> list[dict[str, Any]]:
    url = calendar_page_url(kind, month, year)
    sys.stderr.write(f"Fetching {kind} calendar: {url}\n")
    html = http_get(url, accept="text/html,application/xhtml+xml,*/*")
    events = parse_calendar_html(html, kind=kind, month=month, year=year)
    if not events:
        sys.stderr.write(f"  warn: no events parsed for {kind} {year}-{month:02d}\n")
    else:
        sys.stderr.write(f"  {len(events)} events\n")
    return events


def group_events_by_date(events: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for event in events:
        key = event.get("date") or "unknown"
        grouped.setdefault(key, []).append(event)
    return dict(sorted(grouped.items()))


def build_calendar_payload(
    months: list[tuple[int, int]],
    events_by_month: list[dict[str, Any]],
) -> dict[str, Any]:
    all_events: list[dict[str, Any]] = []
    for block in events_by_month:
        all_events.extend(block.get("events") or [])
    return {
        "scrapedAt": utc_now_iso(),
        "source": {
            "mainboard": CALENDAR_PAGES["mainboard"]["url"],
            "sme": CALENDAR_PAGES["sme"]["url"],
        },
        "months": [
            {
                "year": year,
                "month": month,
                "label": date(year, month, 1).strftime("%B %Y"),
            }
            for year, month in months
        ],
        "summary": {
            "totalEvents": len(all_events),
            "mainboard": sum(1 for e in all_events if e.get("type") == "mainboard"),
            "sme": sum(1 for e in all_events if e.get("type") == "sme"),
            "byEventType": _count_by(all_events, "eventType"),
        },
        "calendar": events_by_month,
        "events": all_events,
    }


def _count_by(rows: list[dict[str, Any]], key: str) -> dict[str, int]:
    out: dict[str, int] = {}
    for row in rows:
        k = str(row.get(key) or "unknown")
        out[k] = out.get(k, 0) + 1
    return dict(sorted(out.items()))


def normalize_timetable_row(row: dict[str, Any]) -> dict[str, Any]:
    slug = row.get("~urlrewrite_folder_name") or ""
    ipo_id = row.get("~id")
    issue_type = strip_html(row.get("Issue Type")).lower()
    if "sme" in issue_type:
        kind = "sme"
    elif "mainboard" in issue_type or "main board" in issue_type:
        kind = "mainboard"
    else:
        kind = issue_type or None

    name = strip_html(row.get("Company") or row.get("~compare_name"))
    logo = row.get("~compare_image")
    return {
        "ipoId": int(ipo_id) if ipo_id is not None else None,
        "name": name,
        "slug": slug or None,
        "type": kind,
        "dates": {
            "open": parse_date(row.get("~Issue_Open_Date") or row.get("Opening Date")),
            "close": parse_date(row.get("~Issue_Close_Date") or row.get("Closing Date")),
            "allotment": parse_date(
                row.get("~Timetable_BOA_dt") or row.get("Allotment Date")
            ),
            "refunds": parse_date(row.get("~Timetable_Refunds_dt")),
            "listing": parse_date(row.get("~IPO_Listing_date") or row.get("Listing Date")),
        },
        "displayDates": {
            "open": strip_html(row.get("Opening Date")) or None,
            "close": strip_html(row.get("Closing Date")) or None,
            "allotment": strip_html(row.get("Allotment Date")) or None,
            "listing": strip_html(row.get("Listing Date")) or None,
        },
        "logo": logo or None,
        "urls": {
            "chittorgarh": (
                f"{SITE}/ipo/{slug}/{ipo_id}/" if slug and ipo_id is not None else None
            ),
            "timetablePage": f"{TIMETABLE_PAGE}{kind}/" if kind else TIMETABLE_PAGE,
        },
    }


def fetch_timetable(category: str = "all") -> list[dict[str, Any]]:
    url = timetable_url(category)
    sys.stderr.write(f"Fetching IPO timetable: {url}\n")
    data = http_get_json(url)
    rows = data.get("reportTableData") or []
    if not rows:
        raise ScrapeError(f"Empty timetable from {url}")
    sys.stderr.write(f"  {len(rows)} rows\n")
    return [normalize_timetable_row(r) for r in rows]


def build_timetable_payload(ipos: list[dict[str, Any]]) -> dict[str, Any]:
    year, _month, fy = indian_fy()
    return {
        "scrapedAt": utc_now_iso(),
        "source": TIMETABLE_PAGE + "mainboard/",
        "feeds": {
            "all": timetable_url("all"),
            "mainboard": timetable_url("mainboard"),
            "sme": timetable_url("sme"),
        },
        "year": year,
        "financialYear": fy,
        "summary": {
            "total": len(ipos),
            "mainboard": sum(1 for i in ipos if i.get("type") == "mainboard"),
            "sme": sum(1 for i in ipos if i.get("type") == "sme"),
        },
        "ipos": ipos,
    }


def month_span(start: date, count: int) -> list[tuple[int, int]]:
    """Return list of (year, month) for count months starting at start."""
    out: list[tuple[int, int]] = []
    y, m = start.year, start.month
    for _ in range(max(1, count)):
        out.append((y, m))
        m += 1
        if m > 12:
            m = 1
            y += 1
    return out


def sync_extra_web_data(*paths: Path) -> None:
    web_data = Path("web/data")
    web_data.mkdir(parents=True, exist_ok=True)
    for path in paths:
        if path.exists():
            (web_data / path.name).write_bytes(path.read_bytes())
            sys.stderr.write(f"Synced {path.name} -> {web_data}/\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Scrape Chittorgarh IPO calendar + timetable into two JSON files."
    )
    parser.add_argument("--month", type=int, help="Calendar month 1-12 (default: current)")
    parser.add_argument("--year", type=int, help="Calendar year (default: current)")
    parser.add_argument(
        "--months",
        type=int,
        default=1,
        help="How many months of calendar to scrape starting from --month/--year (default: 1)",
    )
    parser.add_argument(
        "--calendar-out",
        default="output/ipo-calendar.json",
        help="Calendar JSON output path",
    )
    parser.add_argument(
        "--timetable-out",
        default="output/ipo-timetable.json",
        help="Timetable JSON output path",
    )
    parser.add_argument("--calendar-only", action="store_true")
    parser.add_argument("--timetable-only", action="store_true")
    parser.add_argument(
        "--no-sync-web",
        action="store_true",
        help="Do not copy outputs into web/data/",
    )
    args = parser.parse_args(argv)

    if args.calendar_only and args.timetable_only:
        parser.error("Use only one of --calendar-only / --timetable-only")

    today = date.today()
    month = args.month or today.month
    year = args.year or today.year
    if not 1 <= month <= 12:
        parser.error("--month must be 1-12")
    if args.months < 1:
        parser.error("--months must be >= 1")

    do_calendar = not args.timetable_only
    do_timetable = not args.calendar_only
    written: list[Path] = []

    if do_calendar:
        months = month_span(date(year, month, 1), args.months)
        calendar_blocks: list[dict[str, Any]] = []
        for y, m in months:
            mainboard = fetch_calendar_month("mainboard", m, y)
            time.sleep(REQUEST_PAUSE_S)
            sme = fetch_calendar_month("sme", m, y)
            time.sleep(REQUEST_PAUSE_S)
            month_events = mainboard + sme
            calendar_blocks.append(
                {
                    "year": y,
                    "month": m,
                    "label": date(y, m, 1).strftime("%B %Y"),
                    "sources": {
                        "mainboard": calendar_page_url("mainboard", m, y),
                        "sme": calendar_page_url("sme", m, y),
                    },
                    "summary": {
                        "total": len(month_events),
                        "mainboard": len(mainboard),
                        "sme": len(sme),
                    },
                    "byDate": group_events_by_date(month_events),
                    "events": month_events,
                }
            )
        cal_payload = build_calendar_payload(months, calendar_blocks)
        cal_path = Path(args.calendar_out)
        write_json(cal_path, cal_payload)
        written.append(cal_path)
        sys.stderr.write(
            f"Wrote {cal_path} ({cal_payload['summary']['totalEvents']} events)\n"
        )

    if do_timetable:
        ipos = fetch_timetable("all")
        # Stable order: open date asc, then name
        ipos.sort(
            key=lambda i: (
                (i.get("dates") or {}).get("open") or "9999-99-99",
                i.get("name") or "",
            )
        )
        tt_payload = build_timetable_payload(ipos)
        tt_path = Path(args.timetable_out)
        write_json(tt_path, tt_payload)
        written.append(tt_path)
        sys.stderr.write(
            f"Wrote {tt_path} ({tt_payload['summary']['total']} IPOs)\n"
        )

    if written and not args.no_sync_web:
        sync_extra_web_data(*written)

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ScrapeError as exc:
        sys.stderr.write(f"Error: {exc}\n")
        raise SystemExit(1) from exc
    except KeyboardInterrupt:
        sys.stderr.write("\nInterrupted\n")
        raise SystemExit(130) from None
