#!/usr/bin/env python3
"""Parse a Chittorgarh IPO detail HTML page into structured JSON."""

from __future__ import annotations

import re
from html import unescape
from html.parser import HTMLParser
from typing import Any


def clean_text(value: str | None) -> str:
    if not value:
        return ""
    text = unescape(value)
    text = re.sub(r"<[^>]+>", " ", text)
    text = text.replace("\xa0", " ").replace("\u200b", "")
    text = re.sub(r"\s+", " ", text).strip()
    return text


def parse_number(text: str) -> float | None:
    text = clean_text(text)
    if not text or text in {"-", "NA", "N/A", "—"}:
        return None
    m = re.search(r"-?\d+(?:,\d+)*(?:\.\d+)?", text.replace("₹", ""))
    if not m:
        return None
    try:
        return float(m.group(0).replace(",", ""))
    except ValueError:
        return None


class _TableCollector(HTMLParser):
    """Collect HTML tables as list of rows (each row = list of cell texts)."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tables: list[dict[str, Any]] = []
        self._in_table = False
        self._in_row = False
        self._in_cell = False
        self._cell_tag = ""
        self._cell_parts: list[str] = []
        self._row: list[str] = []
        self._rows: list[list[str]] = []
        self._table_id = ""
        self._table_classes = ""
        self._depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        ad = {k: (v or "") for k, v in attrs}
        if tag == "table":
            if not self._in_table:
                self._in_table = True
                self._depth = 1
                self._rows = []
                self._table_id = ad.get("id", "")
                self._table_classes = ad.get("class", "")
            else:
                self._depth += 1
            return
        if not self._in_table:
            return
        if tag == "tr" and self._depth == 1:
            self._in_row = True
            self._row = []
        elif tag in {"td", "th"} and self._in_row and self._depth == 1:
            self._in_cell = True
            self._cell_tag = tag
            self._cell_parts = []
        elif tag == "br" and self._in_cell:
            self._cell_parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag == "table" and self._in_table:
            self._depth -= 1
            if self._depth == 0:
                self.tables.append(
                    {
                        "id": self._table_id,
                        "class": self._table_classes,
                        "rows": self._rows,
                    }
                )
                self._in_table = False
            return
        if not self._in_table:
            return
        if tag in {"td", "th"} and self._in_cell:
            text = clean_text("".join(self._cell_parts))
            self._row.append(text)
            self._in_cell = False
        elif tag == "tr" and self._in_row:
            if self._row:
                self._rows.append(self._row)
            self._in_row = False

    def handle_data(self, data: str) -> None:
        if self._in_cell:
            self._cell_parts.append(data)


def extract_tables(html: str) -> list[dict[str, Any]]:
    parser = _TableCollector()
    parser.feed(html)
    return parser.tables


def table_to_records(rows: list[list[str]]) -> list[dict[str, str]]:
    if not rows:
        return []
    headers = [h or f"col_{i}" for i, h in enumerate(rows[0])]
    records = []
    for row in rows[1:]:
        if not any(row):
            continue
        rec = {}
        for i, h in enumerate(headers):
            rec[h] = row[i] if i < len(row) else ""
        records.append(rec)
    return records


def find_heading_positions(html: str, heading: str) -> list[int]:
    """Return start indexes for heading text, preferring section-title matches."""
    flex = re.sub(r"\\\s", r"(?:\\s|<[^>]+>)*", re.escape(heading))
    positions: list[int] = []
    preferred: list[int] = []
    for m in re.finditer(flex, html, flags=re.I):
        window = html[max(0, m.start() - 120) : m.start()]
        if "section-title" in window:
            preferred.append(m.start())
        else:
            positions.append(m.start())
    return preferred or positions


def find_table_near(html: str, heading: str, window: int = 20000) -> list[list[str]] | None:
    """Find first table after a heading substring."""
    for start in find_heading_positions(html, heading):
        snippet = html[start : start + window]
        tm = re.search(r"<table[\s\S]*?</table>", snippet, re.I)
        if not tm:
            continue
        tables = extract_tables(tm.group(0))
        if tables and tables[0]["rows"]:
            return tables[0]["rows"]
    return None


def find_table_by_first_cell(html: str, first_cell: str) -> list[list[str]] | None:
    tables = extract_tables(html)
    needle = first_cell.lower()
    for table in tables:
        rows = table["rows"]
        if rows and rows[0] and clean_text(rows[0][0]).lower() == needle:
            return rows
    return None


def extract_summary_cards(html: str) -> dict[str, str]:
    cards: dict[str, str] = {}
    for m in re.finditer(
        r'card-ipo[\s\S]*?<p[^>]*text-muted[^>]*>([\s\S]*?)</p>\s*<p[^>]*>([\s\S]*?)</p>',
        html,
        re.I,
    ):
        label = clean_text(m.group(1))
        value = clean_text(m.group(2))
        if label and value:
            cards[label] = value
    return cards


def extract_intro(html: str) -> str:
    m = re.search(
        r'class="[^"]*ipo-dynamic-content[^"]*"[^>]*>([\s\S]*?)</div>',
        html,
        re.I,
    )
    if not m:
        return ""
    paras = extract_paragraphs(m.group(1), min_len=40)
    return "\n\n".join(paras[:5])


def kv_from_two_col_table(rows: list[list[str]] | None) -> dict[str, str]:
    out: dict[str, str] = {}
    if not rows:
        return out
    for row in rows:
        if len(row) >= 2 and row[0]:
            key = clean_text(row[0]).rstrip(":")
            if key and key not in out:
                out[key] = clean_text(row[1])
    return out


def extract_section_html(html: str, heading: str, stop_headings: list[str]) -> str:
    flex = re.sub(r"\\\s", r"(?:\\s|<[^>]+>)*", re.escape(heading))
    m = re.search(flex, html, flags=re.I)
    if not m:
        m = re.search(heading, html, flags=re.I)
    if not m:
        return ""
    start = m.start()
    end = len(html)
    for stop in stop_headings:
        sm = re.search(stop, html[m.end() :], flags=re.I)
        if sm:
            end = min(end, m.end() + sm.start())
    return html[start:end]


def extract_list_items(html_chunk: str) -> list[str]:
    items = []
    for m in re.finditer(r"<li[^>]*>([\s\S]*?)</li>", html_chunk, re.I):
        text = clean_text(m.group(1))
        if text:
            items.append(text)
    return items


def extract_paragraphs(html_chunk: str, min_len: int = 40) -> list[str]:
    paras = []
    for m in re.finditer(r"<p[^>]*>([\s\S]*?)</p>", html_chunk, re.I):
        text = clean_text(m.group(1))
        if len(text) >= min_len:
            paras.append(text)
    return paras


def extract_faqs(html: str) -> list[dict[str, str]]:
    faqs: list[dict[str, str]] = []
    # accordion buttons + collapse bodies common on the site
    pattern = re.compile(
        r"<button[^>]*>([\s\S]*?)</button>[\s\S]{0,400}?"
        r'<div[^>]*class="[^"]*accordion-body[^"]*"[^>]*>([\s\S]*?)</div>',
        re.I,
    )
    for m in pattern.finditer(html):
        q = clean_text(m.group(1))
        a = clean_text(m.group(2))
        if q and a and ("?" in q or "faq" in q.lower()):
            faqs.append({"question": q, "answer": a})

    if faqs:
        # dedupe
        seen = set()
        out = []
        for f in faqs:
            if f["question"] in seen:
                continue
            seen.add(f["question"])
            out.append(f)
        return out

    # fallback: FAQ heading then dt/dd or strong+p
    chunk = extract_section_html(
        html,
        "IPO FAQs",
        ["IPO Message Board", "Compare:", "Disclaimer"],
    )
    for m in re.finditer(
        r"<strong[^>]*>([\s\S]*?\?)</strong>\s*(?:</[^>]+>\s*)*(?:<p[^>]*>)?([\s\S]*?)(?:</p>|<strong)",
        chunk,
        re.I,
    ):
        q, a = clean_text(m.group(1)), clean_text(m.group(2))
        if q and a:
            faqs.append({"question": q, "answer": a})
    return faqs


def extract_review(html: str) -> dict[str, Any] | None:
    chunk = extract_section_html(
        html,
        "IPO Review",
        ["IPO Registrar", "IPO Lead Manager", "IPO FAQs", "Contact Details"],
    )
    if not chunk:
        return None
    author = None
    am = re.search(r"\[([^\]]+)\]", chunk)
    if am:
        author = clean_text(am.group(1))
    paras = extract_paragraphs(chunk, min_len=30)
    text = clean_text(chunk)
    # strip heading noise
    text = re.sub(r"^IPO\s*Review", "", text, flags=re.I).strip()
    if author:
        text = re.sub(rf"^\[?{re.escape(author)}\]?", "", text).strip()
    if not text and not paras:
        return None
    return {
        "author": author,
        "summary": paras[0] if paras else text[:500],
        "body": "\n\n".join(paras) if paras else text,
    }


def extract_about(html: str) -> dict[str, Any]:
    chunk = extract_section_html(
        html,
        r"About .+?",
        [
            "Company Financials",
            "IPO Objects",
            "Key Performance",
            "IPO Valuation",
            "Recently Listed",
        ],
    )
    # Prefer the About Company section more specifically
    m = re.search(
        r'<h2[^>]*>\s*About[\s\S]*?</h2>([\s\S]*?)(?:<h2|Company Financials)',
        html,
        re.I,
    )
    body = m.group(1) if m else chunk
    paras = extract_paragraphs(body, min_len=50)
    strengths = []
    sm = re.search(r"(?:Strengths|Competitive Strengths)([\s\S]{0,2500})", body, re.I)
    if sm:
        strengths = extract_list_items(sm.group(1))
    return {
        "paragraphs": paras[:8],
        "strengths": strengths[:12],
        "text": "\n\n".join(paras[:4]),
    }


def extract_promoters(html: str) -> list[str]:
    m = re.search(
        r"Company Promoters?:?\s*</[^>]+>\s*<ul[^>]*>([\s\S]*?)</ul>",
        html,
        re.I,
    )
    if not m:
        m = re.search(r"Company Promoters?:([\s\S]{0,800})", html, re.I)
        if not m:
            return []
        return extract_list_items(m.group(0))
    return extract_list_items(m.group(1))


def extract_related_ipos(html: str) -> list[dict[str, str]]:
    m = re.search(
        r"(Recently Listed IPOs[\s\S]*?)</(?:div|section|table)>",
        html,
        re.I,
    )
    if not m:
        return []
    chunk = m.group(0)
    related = []
    for link in re.finditer(
        r'href="(https://www\.chittorgarh\.com/ipo/([^/]+)/(\d+)/?)"[^>]*>([\s\S]*?)</a>',
        chunk,
        re.I,
    ):
        name = clean_text(link.group(4))
        if name:
            related.append(
                {
                    "name": name,
                    "slug": link.group(2),
                    "ipoId": link.group(3),
                    "url": link.group(1),
                }
            )
    # dedupe by slug
    seen = set()
    out = []
    for r in related:
        if r["slug"] in seen:
            continue
        seen.add(r["slug"])
        out.append(r)
    return out[:15]


def extract_contact(html: str) -> dict[str, str]:
    chunk = extract_section_html(
        html,
        "Contact Details",
        ["IPO FAQs", "IPO Message Board", "Compare:"],
    )
    out: dict[str, str] = {}
    for label in ("Phone", "Email", "Website", "Address"):
        m = re.search(rf"{label}\s*[:\-]?\s*([^<\n]+)", chunk, re.I)
        if m:
            out[label.lower()] = clean_text(m.group(1))
    # mailto / http links
    em = re.search(r'mailto:([^"\']+)', chunk, re.I)
    if em:
        out["email"] = clean_text(em.group(1))
    wm = re.search(r'href="(https?://[^"]+)"[^>]*>\s*[^<]*website', chunk, re.I)
    if not wm:
        wm = re.search(r'href="(https?://(?!www\.chittorgarh)[^"]+)"', chunk, re.I)
    if wm and "website" not in out:
        out["website"] = wm.group(1)
    text = clean_text(chunk)
    if text and "text" not in out:
        out["raw"] = text[:500]
    return out


def extract_registrar(html: str) -> dict[str, str]:
    chunk = extract_section_html(
        html,
        "IPO Registrar",
        ["IPO Lead Manager", "Contact Details", "IPO FAQs"],
    )
    name = None
    nm = re.search(r"<a[^>]*>([\s\S]*?)</a>", chunk, re.I)
    if nm:
        name = clean_text(nm.group(1))
    out = {"name": name or "", "raw": clean_text(chunk)[:400]}
    for label in ("Phone", "Email", "Website"):
        m = re.search(rf"{label}\s*[:\-]?\s*([^<\n]+)", chunk, re.I)
        if m:
            out[label.lower()] = clean_text(m.group(1))
    allot = re.search(r'href="(https?://[^"]+ipo[^"]*status[^"]*)"', chunk, re.I)
    if allot:
        out["allotmentUrl"] = allot.group(1)
    return out


def extract_lead_managers(html: str) -> list[str]:
    chunk = extract_section_html(
        html,
        "IPO Lead Manager",
        ["Contact Details", "IPO Registrar", "IPO FAQs"],
    )
    names = []
    for m in re.finditer(r"<a[^>]*>([\s\S]*?)</a>", chunk, re.I):
        name = clean_text(m.group(1))
        if name and len(name) > 2 and name not in names:
            names.append(name)
    if not names:
        names = [t for t in extract_list_items(chunk) if t]
    return names


def parse_financials_table(rows: list[list[str]] | None) -> dict[str, Any]:
    if not rows or len(rows) < 2:
        return {"periods": [], "rows": []}
    headers = rows[0]
    periods = [h for h in headers[1:] if h]
    metrics = []
    for row in rows[1:]:
        if not row or not row[0]:
            continue
        values = {}
        for i, period in enumerate(periods):
            values[period] = row[i + 1] if i + 1 < len(row) else ""
        metrics.append({"metric": row[0], "values": values})
    return {"periods": periods, "rows": metrics}


def parse_subscription_html(html: str) -> dict[str, Any]:
    tables = extract_tables(html)
    summary = ""
    pm = re.search(r"<p>([\s\S]*?)</p>", html, re.I)
    if pm:
        summary = clean_text(pm.group(1))
    apps = None
    am = re.search(r"Total Applications:\s*([\d,]+)", html, re.I)
    if am:
        apps = parse_number(am.group(1))

    by_category = []
    day_wise = []
    if tables:
        by_category = table_to_records(tables[0]["rows"])
    if len(tables) > 1:
        day_wise = table_to_records(tables[1]["rows"])

    total = None
    for row in by_category:
        cat = (row.get("Category") or "").lower()
        if cat.startswith("total"):
            total = parse_number(row.get("Subscription (x)") or "")
            break

    return {
        "summary": summary,
        "total": total,
        "applications": apps,
        "byCategory": by_category,
        "dayWise": day_wise,
    }


def parse_detail_html(
    html: str,
    *,
    slug: str,
    ipo_id: int | None,
    url: str,
) -> dict[str, Any]:
    details_rows = find_table_near(html, "IPO Details") or find_table_by_first_cell(
        html, "IPO Date"
    )
    timetable_rows = find_table_near(html, "IPO Timetable")
    reservation_rows = find_table_near(html, "Issue Reservation")
    lot_rows = find_table_near(html, "IPO Lot Size")
    financial_rows = None
    for label in (
        "Company Financials (Restated Consolidated)",
        "Company Financials (Restated)",
        "Company Financials",
    ):
        financial_rows = find_table_near(html, label)
        if financial_rows:
            break

    objectives_rows = find_table_near(html, "Objects of the Issue")
    if not objectives_rows:
        obj_chunk = extract_section_html(
            html,
            "Objects of the Issue",
            ["Key Performance", "IPO Valuation", "Shareholding"],
        )
        objectives_list = extract_list_items(obj_chunk)
    else:
        objectives_list = []
        for row in objectives_rows[1:] if len(objectives_rows) > 1 else objectives_rows:
            if row and row[0] and not row[0].lower().startswith("object"):
                if len(row) > 1 and row[1]:
                    objectives_list.append(f"{row[0]} — {row[1]}")
                else:
                    objectives_list.append(row[0])

    kpi_rows = find_table_near(html, "Key Performance Indicator")
    valuation_rows = find_table_near(html, "IPO Valuation")
    shareholding_rows = find_table_near(html, "Shareholding Structure")
    anchor_rows = find_table_near(html, "IPO Anchor Investors")

    issue_details = kv_from_two_col_table(details_rows)
    timetable = kv_from_two_col_table(timetable_rows)
    valuation = kv_from_two_col_table(valuation_rows)
    summary_cards = extract_summary_cards(html)
    intro = extract_intro(html)

    anchor_chunk = extract_section_html(
        html,
        "IPO Anchor Investors",
        ["About ", "Company Financials", "IPO Objects"],
    )
    anchor_summary = extract_paragraphs(anchor_chunk, min_len=20)
    anchor_pdf = None
    pm = re.search(r'href="(https?://[^"]+anchor[^"]+\.pdf)"', anchor_chunk, re.I)
    if pm:
        anchor_pdf = pm.group(1)

    title = None
    tm = re.search(r"<h1[^>]*>([\s\S]*?)</h1>", html, re.I)
    if tm:
        title = clean_text(tm.group(1))

    rhp = None
    rm = re.search(
        r'href="(https?://[^"]+)"[^>]*>[\s\S]*?\bRHP\b',
        html,
        re.I,
    )
    if rm:
        rhp = rm.group(1)

    return {
        "slug": slug,
        "ipoId": ipo_id,
        "url": url,
        "title": title,
        "intro": intro,
        "summaryCards": summary_cards,
        "issueDetails": issue_details,
        "timetable": timetable,
        "reservation": table_to_records(reservation_rows) if reservation_rows else [],
        "lotSizeTable": table_to_records(lot_rows) if lot_rows else [],
        "anchor": {
            "summary": anchor_summary[0] if anchor_summary else None,
            "table": table_to_records(anchor_rows) if anchor_rows else [],
            "letterPdf": anchor_pdf,
        },
        "about": extract_about(html),
        "financials": parse_financials_table(financial_rows),
        "objectives": objectives_list,
        "kpi": table_to_records(kpi_rows) if kpi_rows else [],
        "valuation": valuation,
        "shareholding": table_to_records(shareholding_rows) if shareholding_rows else [],
        "promoters": extract_promoters(html),
        "review": extract_review(html),
        "registrar": extract_registrar(html),
        "leadManagers": extract_lead_managers(html),
        "contact": extract_contact(html),
        "faqs": extract_faqs(html),
        "relatedIpos": extract_related_ipos(html),
        "links": {
            "subscriptionPage": f"https://www.chittorgarh.com/ipo_subscription/{slug}/{ipo_id}/"
            if ipo_id
            else None,
            "gmpPage": f"https://www.investorgain.com/chr-gmp/{slug}/{ipo_id}"
            if ipo_id
            else None,
            "rhp": rhp,
            "source": url,
        },
    }
