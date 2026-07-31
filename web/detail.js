const params = new URLSearchParams(location.search);
const slug = params.get("slug");

const els = {
  app: document.getElementById("app"),
  name: document.getElementById("name"),
  tagline: document.getElementById("tagline"),
  scrapedAt: document.getElementById("scrapedAt"),
  error: document.getElementById("error"),
};

function esc(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function formatDate(iso) {
  if (!iso) return "—";
  const d = new Date(`${iso}T00:00:00`);
  if (Number.isNaN(d.getTime())) return esc(iso);
  return d.toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "numeric" });
}

function rupee(n) {
  if (n == null || Number.isNaN(Number(n))) return "—";
  const num = Number(n);
  const abs = Math.abs(num);
  const body = abs % 1 === 0 ? String(Math.trunc(abs)) : abs.toLocaleString("en-IN");
  return `${num < 0 ? "−" : ""}₹${body}`;
}

function gmpClass(value) {
  if (value == null) return "";
  if (value > 0) return "pos";
  if (value < 0) return "neg";
  return "";
}

function kvHtml(obj) {
  const entries = Object.entries(obj || {}).filter(([, v]) => v != null && String(v).trim());
  if (!entries.length) return `<p class="muted">No data.</p>`;
  return `<div class="kv-grid">${entries
    .map(
      ([k, v]) => `
      <div class="kv">
        <p class="kv-label">${esc(k)}</p>
        <p class="kv-value">${esc(v)}</p>
      </div>`
    )
    .join("")}</div>`;
}

function tableHtml(rows, { numericTail = true } = {}) {
  if (!rows?.length) return `<p>No data.</p>`;
  const keys = Object.keys(rows[0]);
  const head = keys
    .map((k, i) => `<th class="${numericTail && i > 0 ? "num" : ""}">${esc(k)}</th>`)
    .join("");
  const body = rows
    .map((row) => {
      const cells = keys
        .map((k, i) => {
          const cls = numericTail && i > 0 ? "num" : "";
          return `<td class="${cls}">${esc(row[k])}</td>`;
        })
        .join("");
      return `<tr>${cells}</tr>`;
    })
    .join("");
  return `<div class="table-wrap"><table class="data"><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table></div>`;
}

function financialsHtml(financials) {
  const periods = financials?.periods || [];
  const rows = financials?.rows || [];
  if (!rows.length) return `<p>No financials available.</p>`;
  const head = `<th>Metric</th>${periods.map((p) => `<th class="num">${esc(p)}</th>`).join("")}`;
  const body = rows
    .map((row) => {
      const cells = periods
        .map((p) => `<td class="num">${esc(row.values?.[p] ?? "—")}</td>`)
        .join("");
      return `<tr><td>${esc(row.metric)}</td>${cells}</tr>`;
    })
    .join("");
  return `<div class="table-wrap"><table class="data"><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table></div>`;
}

function panel(id, title, body, delay = 0) {
  if (!body) return "";
  return `<section class="panel" id="${id}" style="animation-delay:${delay}ms"><h2>${title}</h2>${body}</section>`;
}

function render(data) {
  const o = data.overview || {};
  const gmp = o.gmp || {};
  const dates = o.dates || {};
  const sub = data.subscription || {};

  document.title = `${o.name || data.title || "IPO"} — IPO Desk`;
  els.name.textContent = o.name || data.title || slug;
  els.tagline.textContent = [
    o.status,
    o.type,
    o.exchange,
    o.issueSize,
  ]
    .filter(Boolean)
    .join(" · ");
  els.scrapedAt.textContent = data.scrapedAt
    ? `Updated ${new Date(data.scrapedAt).toLocaleString("en-IN")}`
    : "Updated —";

  const gmpText =
    gmp.value != null
      ? `${rupee(gmp.value)}${gmp.percent != null ? ` (${gmp.percent}%)` : ""}`
      : "Not quoted";

  const hero = `
    <div class="hero-strip">
      <div class="stat">
        <p class="stat-label">Price band</p>
        <p class="stat-value">${esc(o.priceBand?.display || "—")}</p>
      </div>
      <div class="stat">
        <p class="stat-label">GMP</p>
        <p class="stat-value ${gmpClass(gmp.value)}">${esc(gmpText)}</p>
      </div>
      <div class="stat">
        <p class="stat-label">Subscription</p>
        <p class="stat-value">${sub.total != null ? `${esc(sub.total)}×` : "—"}</p>
      </div>
      <div class="stat">
        <p class="stat-label">Lot size</p>
        <p class="stat-value">${esc(o.lotSize ?? "—")}</p>
      </div>
    </div>
    <div class="pill-row">
      <span class="badge badge-${esc(o.status || "open")}">${esc(o.status || "—")}</span>
      <span class="badge badge-type">${esc(o.type || "—")}</span>
      ${o.leadManager ? `<span class="badge badge-type">${esc(o.leadManager)}</span>` : ""}
    </div>
  `;

  const tocItems = [
    ["overview", "Overview"],
    ["dates", "Dates"],
    ["subscription", "Subscription"],
    ["issue", "Issue details"],
    ["lots", "Lot size"],
    ["reservation", "Reservation"],
    ["about", "About"],
    ["objectives", "Objectives"],
    ["financials", "Financials"],
    ["kpi", "KPI"],
    ["valuation", "Valuation"],
    ["review", "Analysis"],
    ["faqs", "FAQs"],
    ["related", "Related"],
  ];

  const toc = `<nav class="toc">${tocItems
    .map(([id, label]) => `<a href="#${id}">${label}</a>`)
    .join("")}</nav>`;

  const overviewBody = `
    ${data.intro ? `<p>${esc(data.intro).replaceAll("\n\n", "</p><p>")}</p>` : ""}
    ${kvHtml(data.summaryCards)}
    <div class="side-links">
      ${data.links?.rhp ? `<a href="${esc(data.links.rhp)}" target="_blank" rel="noopener">RHP ↗</a>` : ""}
      ${data.links?.source ? `<a href="${esc(data.links.source)}" target="_blank" rel="noopener">Source on Chittorgarh ↗</a>` : ""}
      ${data.links?.gmpPage ? `<a href="${esc(data.links.gmpPage)}" target="_blank" rel="noopener">GMP page ↗</a>` : ""}
    </div>
  `;

  const datesBody = kvHtml({
    Open: formatDate(dates.open),
    Close: formatDate(dates.close),
    Allotment: formatDate(dates.allotment),
    Listing: formatDate(dates.listing),
    ...data.timetable,
  });

  const subBody = `
    ${sub.summary ? `<p>${esc(sub.summary)}</p>` : ""}
    ${sub.applications != null ? `<p><strong>Applications:</strong> ${esc(Number(sub.applications).toLocaleString("en-IN"))}</p>` : ""}
    ${tableHtml(sub.byCategory || [])}
    ${sub.dayWise?.length ? `<h2 style="margin-top:1.2rem;font-size:1.05rem">Day-wise</h2>${tableHtml(sub.dayWise)}` : ""}
  `;

  const about = data.about || {};
  const aboutBody = `
    ${about.text ? `<p>${esc(about.text).replaceAll("\n\n", "</p><p>")}</p>` : "<p>No company profile.</p>"}
    ${about.strengths?.length ? `<p><strong>Strengths</strong></p><ul class="objectives">${about.strengths.map((s) => `<li>${esc(s)}</li>`).join("")}</ul>` : ""}
    ${data.promoters?.length ? `<p><strong>Promoters</strong></p><ul class="promoters">${data.promoters.map((p) => `<li>${esc(p)}</li>`).join("")}</ul>` : ""}
  `;

  const objectivesBody = data.objectives?.length
    ? `<ul class="objectives">${data.objectives.map((o) => `<li>${esc(o)}</li>`).join("")}</ul>`
    : "";

  const review = data.review;
  const reviewBody = review
    ? `${review.author ? `<p class="review-author">${esc(review.author)}</p>` : ""}<p>${esc(review.body || review.summary || "").replaceAll("\n\n", "</p><p>")}</p>`
    : "";

  const faqsBody = data.faqs?.length
    ? `<div class="faq">${data.faqs
        .map(
          (f) => `<details><summary>${esc(f.question)}</summary><p class="faq-body">${esc(f.answer)}</p></details>`
        )
        .join("")}</div>`
    : "";

  const relatedBody = data.relatedIpos?.length
    ? `<div class="related">${data.relatedIpos
        .map(
          (r) =>
            `<a href="./ipo.html?slug=${encodeURIComponent(r.slug)}">${esc(r.name)}</a>`
        )
        .join("")}</div>`
    : "";

  const registrarBody = data.registrar?.name
    ? kvHtml(data.registrar)
    : "";

  const peopleBody = `
    ${data.leadManagers?.length ? `<p><strong>Lead managers</strong></p><ul class="promoters">${data.leadManagers.map((m) => `<li>${esc(m)}</li>`).join("")}</ul>` : ""}
    ${Object.keys(data.contact || {}).length ? `<p><strong>Company contact</strong></p>${kvHtml(data.contact)}` : ""}
  `;

  els.app.innerHTML = [
    hero,
    toc,
    panel("overview", "Overview", overviewBody, 40),
    panel("dates", "Key dates", datesBody, 70),
    panel("subscription", "Subscription status", subBody, 100),
    panel("issue", "Issue details", kvHtml(data.issueDetails), 130),
    panel("lots", "IPO lot size", tableHtml(data.lotSizeTable || []), 160),
    panel("reservation", "Issue reservation", tableHtml(data.reservation || []), 180),
    panel("anchor", "Anchor investors", `${data.anchor?.summary ? `<p>${esc(data.anchor.summary)}</p>` : ""}${tableHtml(data.anchor?.table || [])}${data.anchor?.letterPdf ? `<div class="side-links"><a href="${esc(data.anchor.letterPdf)}" target="_blank" rel="noopener">Anchor letter PDF ↗</a></div>` : ""}`, 200),
    panel("about", "About the company", aboutBody, 220),
    panel("objectives", "Objects of the issue", objectivesBody, 240),
    panel("financials", "Financials", financialsHtml(data.financials), 260),
    panel("kpi", "Key performance indicators", tableHtml(data.kpi || []), 280),
    panel("valuation", "Valuation", kvHtml(data.valuation), 300),
    panel("shareholding", "Shareholding", tableHtml(data.shareholding || []), 320),
    panel("review", "Analysis & review", reviewBody, 340),
    panel("people", "Registrar, managers & contact", peopleBody, 360),
    panel("faqs", "FAQs", faqsBody, 380),
    panel("related", "Related / peer IPOs", relatedBody, 400),
  ]
    .filter(Boolean)
    .join("");
}

async function boot() {
  if (!slug) {
    els.error.textContent = "Missing ?slug= in the URL.";
    return;
  }
  try {
    const res = await fetch(`./data/details/${encodeURIComponent(slug)}.json`, {
      cache: "no-store",
    });
    if (!res.ok) {
      throw new Error(
        `Detail JSON not found (${res.status}). Run: python scrape_chittorgarh.py --status open,upcoming --details`
      );
    }
    const data = await res.json();
    els.error?.remove();
    render(data);
  } catch (err) {
    els.error.textContent = String(err.message || err);
    console.error(err);
  }
}

boot();
