const DATA_URL = "./data/ipos.json";

const state = {
  status: "all",
  type: "all",
  query: "",
  payload: null,
};

const els = {
  list: document.getElementById("list"),
  empty: document.getElementById("empty"),
  scrapedAt: document.getElementById("scrapedAt"),
  counts: document.getElementById("counts"),
  search: document.getElementById("search"),
};

function formatDate(iso) {
  if (!iso) return "—";
  const d = new Date(`${iso}T00:00:00`);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString("en-IN", {
    day: "2-digit",
    month: "short",
  });
}

function formatScraped(iso) {
  if (!iso) return "Updated —";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return `Updated ${iso}`;
  return `Updated ${d.toLocaleString("en-IN", {
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  })}`;
}

function rupee(n) {
  if (n == null || Number.isNaN(Number(n))) return "—";
  const num = Number(n);
  const abs = Math.abs(num);
  const body = abs % 1 === 0 ? String(Math.trunc(abs)) : abs.toLocaleString("en-IN");
  return `${num < 0 ? "−" : ""}₹${body}`;
}

function gmpClass(value) {
  if (value == null) return "flat";
  if (value > 0) return "pos";
  if (value < 0) return "neg";
  return "flat";
}

function filteredIpos() {
  const ipos = state.payload?.ipos ?? [];
  const q = state.query.trim().toLowerCase();

  return ipos.filter((ipo) => {
    if (state.status !== "all" && ipo.status !== state.status) return false;
    if (state.type !== "all" && ipo.type !== state.type) return false;
    if (!q) return true;
    const hay = [
      ipo.name,
      ipo.exchange,
      ipo.leadManager,
      ipo.type,
      ipo.status,
      ipo.slug,
    ]
      .filter(Boolean)
      .join(" ")
      .toLowerCase();
    return hay.includes(q);
  });
}

function logoHtml(ipo) {
  const initial = escapeHtml((ipo.name || "?").slice(0, 1).toUpperCase());
  if (!ipo.logo) {
    return `<div class="logo logo-fallback">${initial}</div>`;
  }
  return `<img class="logo" src="${escapeHtml(ipo.logo)}" alt="" loading="lazy" data-fallback="${initial}" />`;
}

function rowHtml(ipo, index) {
  const href = escapeHtml(ipo.urls?.local || `./ipo.html?slug=${encodeURIComponent(ipo.slug || "")}`);
  const gmp = ipo.gmp ?? {};
  const hasGmp = gmp.value != null;
  const sub =
    ipo.subscription?.total != null ? `${ipo.subscription.total}×` : "—";

  return `
    <a class="row" href="${href}" style="animation-delay:${Math.min(
      index * 35,
      280
    )}ms">
      <div class="company">
        ${logoHtml(ipo)}
        <div class="company-copy">
          <p class="company-name">${escapeHtml(ipo.name || "—")}</p>
          <p class="company-meta">
            <span class="badge badge-${escapeHtml(ipo.status || "open")}">${escapeHtml(
              ipo.status || "—"
            )}</span>
            <span class="badge badge-type">${escapeHtml(ipo.type || "—")}</span>
            <span>${escapeHtml(ipo.exchange || "")}</span>
          </p>
        </div>
      </div>
      <div class="price">${escapeHtml(ipo.priceBand?.display || "—")}</div>
      <div class="gmp">
        <span class="gmp-main ${gmpClass(gmp.value)}">
          ${hasGmp ? `${rupee(gmp.value)}${gmp.percent != null ? ` (${gmp.percent}%)` : ""}` : "Not quoted"}
        </span>
        <span class="gmp-sub">${gmp.xLot != null ? `× lot ${rupee(gmp.xLot)}` : escapeHtml(gmp.updatedOn || "")}</span>
      </div>
      <div class="sub">${escapeHtml(sub)}</div>
      <div class="lot">${ipo.lotSize ?? "—"}</div>
      <div class="timeline">
        <span><strong>${formatDate(ipo.dates?.open)}</strong> → ${formatDate(ipo.dates?.close)}</span>
        <span>Allot ${formatDate(ipo.dates?.allotment)} · List ${formatDate(ipo.dates?.listing)}</span>
      </div>
      <span class="open-link">View →</span>
    </a>
  `;
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function render() {
  const rows = filteredIpos();
  const summary = state.payload?.summary ?? {};

  els.counts.textContent = `${rows.length} shown · ${summary.open ?? 0} open · ${
    summary.upcoming ?? 0
  } upcoming`;
  els.list.innerHTML = rows.map(rowHtml).join("");
  els.empty.classList.toggle("hidden", rows.length > 0);

  els.list.querySelectorAll("img.logo").forEach((img) => {
    img.addEventListener("error", () => {
      const fallback = document.createElement("div");
      fallback.className = "logo logo-fallback";
      fallback.textContent = img.dataset.fallback || "?";
      img.replaceWith(fallback);
    });
  });
}

function bindFilters() {
  document.querySelectorAll("[data-status]").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll("[data-status]").forEach((b) => b.classList.remove("is-active"));
      btn.classList.add("is-active");
      state.status = btn.dataset.status;
      render();
    });
  });

  document.querySelectorAll("[data-type]").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll("[data-type]").forEach((b) => b.classList.remove("is-active"));
      btn.classList.add("is-active");
      state.type = btn.dataset.type;
      render();
    });
  });

  els.search.addEventListener("input", () => {
    state.query = els.search.value;
    render();
  });
}

async function boot() {
  bindFilters();
  try {
    const res = await fetch(DATA_URL, { cache: "no-store" });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    state.payload = await res.json();
    els.scrapedAt.textContent = formatScraped(state.payload.scrapedAt);
    render();
  } catch (err) {
    els.scrapedAt.textContent = "Failed to load data";
    els.list.innerHTML = "";
    els.empty.textContent =
      "Could not load ./data/ipos.json. Run the scraper, then open via python serve.py.";
    els.empty.classList.remove("hidden");
    console.error(err);
  }
}

boot();
