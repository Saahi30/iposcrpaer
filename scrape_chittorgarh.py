#!/usr/bin/env python3
"""
Scrape IPO data from Chittorgarh (and their Live GMP feed) into website-ready JSON.

Sources:
  List:  https://webnodejs.chittorgarh.com/cloud/report/data-read/82/...
  GMP:   https://webnodejs.investorgain.com/cloud/v2/report/data-read/331/...
         (same feed linked from https://www.chittorgarh.com/report/live-ipo-gmp/331/)
  Detail pages (optional): https://www.chittorgarh.com/ipo/{slug}/{id}/

Examples:
  python scrape_chittorgarh.py
  python scrape_chittorgarh.py --status open,upcoming --out output/ipos.json
  python scrape_chittorgarh.py --details --status open --out output/open-detailed.json
  python scrape_chittorgarh.py --split --out-dir output
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timezone
from html import unescape
from pathlib import Path
from typing import Any

SITE = "https://www.chittorgarh.com"
LIST_HOST = "https://webnodejs.chittorgarh.com"
GMP_HOST = "https://webnodejs.investorgain.com"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
REQUEST_PAUSE_S = 0.2


class ScrapeError(RuntimeError):
    pass


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def indian_fy(d: date | None = None) -> tuple[int, int, str]:
    """Return (calendar_year, month, fy_label) for Chittorgarh URL segments."""
    d = d or date.today()
    if d.month >= 4:
        fy = f"{d.year}-{str(d.year + 1)[-2:]}"
    else:
        fy = f"{d.year - 1}-{str(d.year)[-2:]}"
    return d.year, d.month, fy


def http_get(url: str, *, accept: str = "application/json, text/plain, */*") -> str:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": accept,
            "Origin": SITE,
            "Referer": SITE + "/",
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=45) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")
        raise ScrapeError(f"HTTP {e.code} for {url}: {detail[:300]}") from e
    except urllib.error.URLError as e:
        raise ScrapeError(f"Network error for {url}: {e.reason}") from e


def http_get_json(url: str) -> Any:
    return json.loads(http_get(url))


def strip_html(value: Any) -> str:
    if value is None:
        return ""
    text = unescape(str(value))
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def parse_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = strip_html(value)
    text = (
        text.replace("₹", "")
        .replace(",", "")
        .replace("Cr", "")
        .replace("cr", "")
        .replace("%", "")
        .replace("x", "")
        .replace("X", "")
        .strip()
    )
    # First number in string
    m = re.search(r"-?\d+(?:\.\d+)?", text)
    if not m:
        return None
    try:
        return float(m.group(0))
    except ValueError:
        return None


def parse_int(value: Any) -> int | None:
    n = parse_float(value)
    if n is None:
        return None
    return int(n)


def parse_date(value: Any) -> str | None:
    """Normalize to YYYY-MM-DD when possible."""
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return None
    text = strip_html(value)
    if not text or text in {"-", "NA", "N/A"}:
        return None
    m = re.match(r"^(\d{4}-\d{2}-\d{2})", text)
    if m:
        return m.group(1)
    for fmt in ("%d-%b-%Y", "%d-%B-%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(text, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        return None


def slug_key(folder: str) -> str:
    """Normalize folder/slug for joining list + GMP rows."""
    text = folder.strip().strip("/")
    text = text.split("/")[-1] if "/" in text else text
    # gmp path: gmp/lapl-automotive-ipo/1713 -> lapl-automotive-ipo
    parts = [p for p in folder.strip("/").split("/") if p and p != "gmp"]
    if parts:
        # drop trailing numeric id
        if parts[-1].isdigit() and len(parts) >= 2:
            text = parts[-2]
        else:
            text = parts[-1]
    text = text.lower()
    text = re.sub(r"-ipo$", "", text)
    text = re.sub(r"[^a-z0-9]+", "", text)
    return text


def extract_href_id(company_html: str) -> tuple[str | None, int | None, str | None]:
    """From Company cell HTML -> (url, ipo_id, folder_slug)."""
    m = re.search(
        r'href="([^"]+/ipo/([^/]+)/(\d+)/?)"',
        company_html or "",
        flags=re.I,
    )
    if not m:
        return None, None, None
    return m.group(1), int(m.group(3)), m.group(2)


def extract_lead_manager(html: str) -> str | None:
    text = strip_html(html)
    return text or None


def parse_price_band(raw: Any) -> tuple[float | None, float | None]:
    text = strip_html(raw)
    nums = re.findall(r"\d+(?:\.\d+)?", text.replace(",", ""))
    if not nums:
        return None, None
    if len(nums) == 1:
        v = float(nums[0])
        return v, v
    return float(nums[0]), float(nums[1])


def fmt_money(value: float | None) -> str | None:
    if value is None:
        return None
    if float(value).is_integer():
        return str(int(value))
    return f"{value:g}"


def price_display(price_min: float | None, price_max: float | None) -> str | None:
    if price_min is None or price_max is None:
        return None
    a, b = fmt_money(price_min), fmt_money(price_max)
    if a == b:
        return f"₹{a}"
    return f"₹{a}–{b}"


def parse_gmp_cell(raw: Any) -> tuple[float | None, float | None]:
    """Parse GMP HTML like '₹7 (7.45%)'."""
    text = strip_html(raw)
    if not text or text in {"-", "NA", "N/A", "Not quoted"}:
        return None, None
    # value then optional percent in parentheses
    m = re.search(r"(-?\d+(?:\.\d+)?)\s*\(\s*(-?\d+(?:\.\d+)?)\s*%?\s*\)", text)
    if m:
        return float(m.group(1)), float(m.group(2))
    v = parse_float(text)
    return v, None


def badge_status(name_html: str) -> str | None:
    """GMP feed badges: U upcoming, O open, CT closing today, LT listing today, P closed/pending."""
    badges = re.findall(
        r'badge[^>]*>\s*([A-Z]{1,3})\s*<',
        name_html or "",
        flags=re.I,
    )
    mapping = {
        "U": "upcoming",
        "O": "open",
        "CT": "open",
        "LT": "listed",
        "P": "closed",
        "L": "listed",
    }
    for b in badges:
        key = b.upper()
        if key in mapping:
            return mapping[key]
    return None


def derive_status(
    *,
    open_d: str | None,
    close_d: str | None,
    listing_d: str | None,
    hint: str | None = None,
    today: date | None = None,
) -> str:
    today = today or date.today()

    def to_date(s: str | None) -> date | None:
        if not s:
            return None
        try:
            return date.fromisoformat(s[:10])
        except ValueError:
            return None

    o, c, l = to_date(open_d), to_date(close_d), to_date(listing_d)
    if l and today >= l:
        return "listed"
    if o and today < o:
        return "upcoming"
    if o and c and o <= today <= c:
        return "open"
    if c and today > c and (not l or today < l):
        return "closed"
    if hint:
        return hint
    return "upcoming"


def list_url(year: int, month: int, fy: str, category: str = "all") -> str:
    # category: all | mainboard | sme
    return (
        f"{LIST_HOST}/cloud/report/data-read/82/1/{month}/{year}/{fy}/0/"
        f"{category}/0?search=&v=14-08"
    )


def gmp_url(year: int, month: int, fy: str, category: str = "all") -> str:
    # category: all | ipo | sme
    return (
        f"{GMP_HOST}/cloud/v2/report/data-read/331/1/{month}/{year}/{fy}/0/"
        f"{category}?search="
    )


def fetch_ipo_list(category: str = "all") -> list[dict[str, Any]]:
    year, month, fy = indian_fy()
    url = list_url(year, month, fy, category=category)
    sys.stderr.write(f"Fetching IPO list: {url}\n")
    data = http_get_json(url)
    rows = data.get("reportTableData") or []
    if not rows:
        raise ScrapeError(f"Empty IPO list from {url}")
    return rows


def fetch_gmp_rows(category: str = "all") -> list[dict[str, Any]]:
    year, month, fy = indian_fy()
    url = gmp_url(year, month, fy, category=category)
    sys.stderr.write(f"Fetching GMP feed: {url}\n")
    data = http_get_json(url)
    return data.get("reportTableData") or []


def build_gmp_index(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    for row in rows:
        folder = row.get("~urlrewrite_folder_name") or ""
        name = row.get("~ipo_name") or strip_html(row.get("Name"))
        keys = {slug_key(folder), slug_key(name)}
        # also key without spaces/punctuation from display name
        for k in keys:
            if k:
                index[k] = row
    return index


from detail_parser import parse_detail_html, parse_subscription_html

DETAILS_DIR = Path("output/details")


def fetch_subscription(ipo_id: int) -> dict[str, Any] | None:
    url = (
        f"https://www.chittorgarh.net/documents/subscription/{ipo_id}/"
        f"subscriptions.html?abc=470"
    )
    try:
        html = http_get(url, accept="text/html,application/xhtml+xml,*/*")
        return parse_subscription_html(html)
    except ScrapeError:
        return None


def scrape_full_detail(ipo: dict[str, Any]) -> dict[str, Any] | None:
    """Fetch Chittorgarh detail page + live subscription for one IPO."""
    url = (ipo.get("urls") or {}).get("chittorgarh")
    ipo_id = ipo.get("ipoId")
    slug = ipo.get("slug")
    if not url or not slug:
        return None

    html = http_get(url, accept="text/html,application/xhtml+xml")
    detail = parse_detail_html(html, slug=slug, ipo_id=ipo_id, url=url)

    subscription = None
    if ipo_id:
        time.sleep(REQUEST_PAUSE_S)
        subscription = fetch_subscription(int(ipo_id))

    # Prefer live subscription totals when available
    if subscription:
        detail["subscription"] = subscription
    else:
        detail["subscription"] = {
            "summary": None,
            "total": (ipo.get("subscription") or {}).get("total"),
            "applications": None,
            "byCategory": (ipo.get("subscription") or {}).get("byCategory") or [],
            "dayWise": [],
        }

    # Attach list/GMP overview for a single self-contained detail file
    detail["overview"] = {
        "name": ipo.get("name"),
        "type": ipo.get("type"),
        "status": ipo.get("status"),
        "exchange": ipo.get("exchange"),
        "priceBand": ipo.get("priceBand"),
        "lotSize": ipo.get("lotSize"),
        "issueSize": ipo.get("issueSize"),
        "dates": ipo.get("dates"),
        "gmp": ipo.get("gmp"),
        "leadManager": ipo.get("leadManager"),
        "logo": ipo.get("logo"),
        "symbols": ipo.get("symbols"),
    }
    detail["scrapedAt"] = utc_now_iso()
    return detail


def enrich_list_item_from_detail(ipo: dict[str, Any], detail: dict[str, Any]) -> None:
    """Lift a few detail fields onto the list card."""
    issue = detail.get("issueDetails") or {}
    if issue.get("Lot Size"):
        lot = parse_int(issue["Lot Size"])
        if lot is not None:
            ipo["lotSize"] = lot
    if issue.get("Price Band"):
        dmin, dmax = parse_price_band(issue["Price Band"])
        if dmin is not None:
            ipo["priceBand"]["min"] = dmin
            ipo["priceBand"]["max"] = dmax or dmin
            ipo["priceBand"]["display"] = price_display(dmin, dmax or dmin)
    if issue.get("Listing At"):
        ipo["exchange"] = issue["Listing At"]
    if issue.get("Face Value"):
        ipo["faceValue"] = issue["Face Value"]
    if issue.get("Issue Type"):
        ipo["issueType"] = issue["Issue Type"]
    if issue.get("Sale Type"):
        ipo["saleType"] = issue["Sale Type"]

    about = (detail.get("about") or {}).get("text") or detail.get("intro")
    if about:
        ipo["about"] = about[:500]

    registrar = detail.get("registrar") or {}
    if registrar.get("name"):
        ipo["registrar"] = registrar["name"]

    sub = detail.get("subscription") or {}
    if sub.get("total") is not None:
        ipo.setdefault("subscription", {})
        ipo["subscription"]["total"] = sub["total"]
        ipo["subscription"]["applications"] = sub.get("applications")
        ipo["subscription"]["byCategory"] = sub.get("byCategory") or []

    if ipo.get("gmp", {}).get("value") is not None and ipo.get("lotSize"):
        ipo["gmp"]["xLot"] = round(float(ipo["gmp"]["value"]) * float(ipo["lotSize"]), 2)

    ipo["hasDetail"] = True
    ipo["detailPath"] = f"details/{ipo.get('slug')}.json"
    ipo["urls"]["local"] = f"./ipo.html?slug={urllib.parse.quote(str(ipo.get('slug')))}"


def normalize_row(
    list_row: dict[str, Any],
    gmp_row: dict[str, Any] | None,
    *,
    include_raw: bool = False,
) -> dict[str, Any]:
    url, ipo_id, folder = extract_href_id(list_row.get('Company') or '')
    folder = folder or list_row.get('~URLRewrite_Folder_Name')
    name = (
        (gmp_row or {}).get('~ipo_name')
        or strip_html(list_row.get('~compare_name') or '')
        .replace(' IPO', '')
        .strip()
        or strip_html(list_row.get('Company'))
    )

    price_min, price_max = parse_price_band(list_row.get('Issue Price (Rs.)'))

    open_d = parse_date(list_row.get('~Issue_Open_Date') or list_row.get('Opening Date'))
    close_d = parse_date(list_row.get('~IssueCloseDate') or list_row.get('Closing Date'))
    listing_d = parse_date(list_row.get('~ListingDate') or list_row.get('Listing Date'))
    allotment_d = None
    lot_size = None
    gmp_val = None
    gmp_pct = None
    gmp_updated = None
    subscription_total = None
    category_hint = None

    if gmp_row:
        allotment_d = parse_date(gmp_row.get('~Srt_BoA_Dt') or gmp_row.get('BoA Dt'))
        listing_d = parse_date(gmp_row.get('~Str_Listing')) or listing_d
        open_d = parse_date(gmp_row.get('~Srt_Open')) or open_d
        close_d = parse_date(gmp_row.get('~Srt_Close')) or close_d
        lot_size = parse_int(gmp_row.get('Lot'))
        gmp_val, gmp_pct_from_cell = parse_gmp_cell(gmp_row.get('GMP'))
        gmp_pct = parse_float(gmp_row.get('~gmp_percent_calc'))
        if gmp_pct is None:
            gmp_pct = gmp_pct_from_cell
        gmp_updated = strip_html(gmp_row.get('Updated-On')) or None
        subscription_total = parse_float(gmp_row.get('Sub'))
        category_hint = badge_status(gmp_row.get('Name') or '')
        if price_max is None:
            price_max = parse_float(gmp_row.get('Price (\u20b9)'))
            price_min = price_min or price_max

    issue_cat = (list_row.get('Issue Category') or '').strip().lower()
    ipo_type = 'sme' if 'sme' in issue_cat else 'mainboard'
    if gmp_row and (gmp_row.get('~IPO_Category') or '').upper() == 'SME':
        ipo_type = 'sme'

    status = derive_status(
        open_d=open_d,
        close_d=close_d,
        listing_d=listing_d,
        hint=category_hint,
    )

    issue_size_cr = parse_float(
        list_row.get('Total Issue Amount (Incl.Firm reservations) (Rs.cr.)')
        or list_row.get('Issue Amount (Rs.cr.)')
    )
    issue_size = f'\u20b9{issue_size_cr} Cr' if issue_size_cr is not None else None
    if gmp_row and gmp_row.get('IPO Size'):
        issue_size = strip_html(gmp_row.get('IPO Size')) or issue_size

    gmp_x_lot = None
    if gmp_val is not None and lot_size is not None:
        gmp_x_lot = round(float(gmp_val) * float(lot_size), 2)

    exchange = strip_html(list_row.get('Listing at'))

    out: dict[str, Any] = {
        'slug': folder,
        'ipoId': ipo_id,
        'name': name,
        'type': ipo_type,
        'status': status,
        'exchange': exchange,
        'pricingMethod': strip_html(list_row.get('Pricing Method')) or None,
        'priceBand': {
            'min': price_min,
            'max': price_max,
            'display': price_display(price_min, price_max),
        },
        'lotSize': lot_size,
        'issueSize': issue_size,
        'issueSizeCr': issue_size_cr,
        'freshIssueCr': parse_float(list_row.get('Fresh Capital (Rs.cr.)')),
        'ofsCr': parse_float(list_row.get('Offer for sale (Rs.cr.)')),
        'dates': {
            'open': open_d,
            'close': close_d,
            'allotment': allotment_d,
            'listing': listing_d,
        },
        'gmp': {
            'value': gmp_val,
            'percent': gmp_pct,
            'xLot': gmp_x_lot,
            'updatedOn': gmp_updated,
        },
        'subscription': {
            'total': subscription_total,
            'byCategory': [],
        },
        'leadManager': extract_lead_manager(list_row.get('Left Lead Manager') or ''),
        'symbols': {
            'isin': list_row.get('~isin') or None,
            'bse': list_row.get('~bse_script_code') or None,
            'nse': list_row.get('~nse_symbol') or None,
        },
        'logo': list_row.get('~compare_image') or None,
        'hasDetail': False,
        'detailPath': f'details/{folder}.json' if folder else None,
        'urls': {
            'local': f'./ipo.html?slug={urllib.parse.quote(str(folder))}' if folder else None,
            'chittorgarh': url or (f'{SITE}/ipo/{folder}/{ipo_id}/' if folder and ipo_id else None),
            'gmp': None,
        },
    }

    if gmp_row and gmp_row.get('~urlrewrite_folder_name'):
        gmp_path = gmp_row['~urlrewrite_folder_name']
        out['urls']['gmp'] = (
            f'https://www.investorgain.com{gmp_path}'
            if str(gmp_path).startswith('/')
            else gmp_path
        )
        out['gmpId'] = gmp_row.get('~id')

    if include_raw:
        out['_raw'] = {'list': list_row, 'gmp': gmp_row}

    return out



def summarize(ipos: list[dict[str, Any]]) -> dict[str, int]:
    counts = {"open": 0, "upcoming": 0, "closed": 0, "listed": 0, "other": 0}
    for ipo in ipos:
        status = (ipo.get("status") or "other").lower()
        if status in counts:
            counts[status] += 1
        else:
            counts["other"] += 1
    counts["total"] = len(ipos)
    return counts


def order_ipos(ipos: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_status: dict[str, list[dict[str, Any]]] = {}
    for ipo in ipos:
        by_status.setdefault(ipo.get("status") or "other", []).append(ipo)
    for group in by_status.values():
        group.sort(key=lambda x: x.get("dates", {}).get("open") or "", reverse=True)
    ordered: list[dict[str, Any]] = []
    for key in ("open", "upcoming", "closed", "listed"):
        ordered.extend(by_status.get(key, []))
    for key, group in by_status.items():
        if key not in ("open", "upcoming", "closed", "listed"):
            ordered.extend(group)
    return ordered


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def parse_csv_arg(value: str | None) -> list[str] | None:
    if not value:
        return None
    parts = [p.strip().lower() for p in value.split(",") if p.strip()]
    return parts or None


def sync_web_data(out_path: Path, details_dir: Path = DETAILS_DIR) -> None:
    """Mirror scraped JSON into web/data for the static frontend / GitHub Pages."""
    web_data = Path("web/data")
    web_data.mkdir(parents=True, exist_ok=True)
    if out_path.exists():
        (web_data / "ipos.json").write_bytes(out_path.read_bytes())
    dest_details = web_data / "details"
    if dest_details.exists():
        for old in dest_details.glob("*.json"):
            old.unlink()
    else:
        dest_details.mkdir(parents=True, exist_ok=True)
    if details_dir.exists():
        for src in details_dir.glob("*.json"):
            (dest_details / src.name).write_bytes(src.read_bytes())
    sys.stderr.write(f"Synced site data -> {web_data}/\n")


def build_payload(
    ipos: list[dict[str, Any]],
    *,
    filters: dict[str, Any],
) -> dict[str, Any]:
    year, month, fy = indian_fy()
    return {
        "scrapedAt": utc_now_iso(),
        "source": SITE + "/",
        "feeds": {
            "list": list_url(year, month, fy, "all"),
            "gmp": gmp_url(year, month, fy, "all"),
        },
        "filters": filters,
        "summary": summarize(ipos),
        "ipos": ipos,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Scrape Chittorgarh IPO + GMP data into website-ready JSON."
    )
    parser.add_argument(
        "--status",
        help="Comma-separated: open,upcoming,closed,listed (default: all)",
    )
    parser.add_argument(
        "--type",
        dest="ipo_type",
        choices=["mainboard", "sme"],
        help="Filter by IPO type",
    )
    parser.add_argument(
        "--details",
        action="store_true",
        help="Scrape full IPO pages (financials, FAQs, review, subscription) into output/details/",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Max IPOs after filters (0 = no limit). Useful with --details.",
    )
    parser.add_argument("--out", default="output/ipos.json", help="Output JSON path")
    parser.add_argument(
        "--split",
        action="store_true",
        help="Also write open/upcoming/closed/listed.json under --out-dir",
    )
    parser.add_argument("--out-dir", default="output", help="Directory for --split files")
    parser.add_argument("--stdout", action="store_true", help="Print JSON to stdout")
    parser.add_argument("--raw", action="store_true", help="Include raw source rows under _raw")
    args = parser.parse_args(argv)

    statuses = parse_csv_arg(args.status)
    allowed = {"open", "upcoming", "closed", "listed"}
    if statuses:
        bad = [s for s in statuses if s not in allowed]
        if bad:
            parser.error(f"Invalid status values: {', '.join(bad)}")

    list_category = "all"
    if args.ipo_type == "mainboard":
        list_category = "mainboard"
    elif args.ipo_type == "sme":
        list_category = "sme"

    list_rows = fetch_ipo_list(list_category)
    time.sleep(REQUEST_PAUSE_S)
    gmp_rows = fetch_gmp_rows("all")
    gmp_index = build_gmp_index(gmp_rows)
    sys.stderr.write(f"List rows={len(list_rows)} GMP rows={len(gmp_rows)}\n")

    merged: list[dict[str, Any]] = []
    for row in list_rows:
        folder = row.get("~URLRewrite_Folder_Name") or ""
        name = strip_html(row.get("~compare_name") or row.get("Company") or "")
        gmp = gmp_index.get(slug_key(folder)) or gmp_index.get(slug_key(name))
        merged.append(normalize_row(row, gmp, include_raw=args.raw))

    if args.ipo_type:
        merged = [i for i in merged if i.get("type") == args.ipo_type]
    if statuses:
        merged = [i for i in merged if i.get("status") in statuses]

    merged = order_ipos(merged)
    if args.limit and args.limit > 0:
        merged = merged[: args.limit]

    if args.details:
        DETAILS_DIR.mkdir(parents=True, exist_ok=True)
        sys.stderr.write(f"Fetching full details for {len(merged)} IPO(s)...\n")
        for i, ipo in enumerate(merged, start=1):
            slug = ipo.get("slug")
            sys.stderr.write(f"  detail {i}/{len(merged)}: {slug}\n")
            try:
                detail = scrape_full_detail(ipo)
            except ScrapeError as exc:
                sys.stderr.write(f"    warn: {exc}\n")
                detail = None
            if detail:
                write_json(DETAILS_DIR / f"{slug}.json", detail)
                enrich_list_item_from_detail(ipo, detail)
            time.sleep(REQUEST_PAUSE_S)
        merged = order_ipos(merged)

    filters = {
        "status": statuses,
        "type": args.ipo_type,
        "details": args.details,
        "limit": args.limit or None,
    }
    payload = build_payload(merged, filters=filters)
    text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"

    if args.stdout:
        sys.stdout.write(text)
    else:
        out_path = Path(args.out)
        write_json(out_path, payload)
        sys.stderr.write(f"Wrote {out_path} ({payload['summary']})\n")
        sync_web_data(out_path)

    if args.split:
        out_dir = Path(args.out_dir)
        for status in ("open", "upcoming", "closed", "listed"):
            subset = [i for i in merged if i.get("status") == status]
            split_payload = build_payload(
                subset, filters={**filters, "status": [status]}
            )
            path = out_dir / f"{status}.json"
            write_json(path, split_payload)
            sys.stderr.write(f"Wrote {path} ({len(subset)} IPOs)\n")

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
