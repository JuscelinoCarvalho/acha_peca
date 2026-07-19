"use strict";
const $ = s => document.querySelector(s);
const main = $("#main"), input = $("#q"), suggestBox = $("#suggest");
let CFG = { ads: null };
const esc = s => (s == null ? "" : String(s)).replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
/* minúsculas sem acento — filtro acento-insensível no cliente */
const ua = s => (s == null ? "" : String(s)).normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase();
const api = async u => (await fetch(u)).json();
/* tamanho de arquivo legível (KB/MB) */
const fmtSize = n => n >= 1048576 ? (n / 1048576).toFixed(1) + " MB"
  : n >= 1024 ? Math.round(n / 1024) + " KB" : n + " B";

/* ---------- roteamento por hash ---------- */
window.addEventListener("hashchange", route);
window.addEventListener("DOMContentLoaded", () => {
  loadStats();
  loadConfig();
  // ao (re)carregar a página, começa sempre na home — não restaura a busca/filtro
  // anterior. A navegação por hash segue funcionando dentro da sessão (hashchange).
  if (location.hash) history.replaceState(null, "", location.pathname + location.search);
  showHome();
});

/* ---------- config / anúncios (AdSense) ---------- */
async function loadConfig() {
  try { CFG = await api("/api/config"); } catch (e) { }
  mountAds();  // caso um render tenha ocorrido antes da config chegar
}
function adUnit(slot) {
  if (!(CFG.ads && CFG.ads.client && slot)) return "";
  return `<ins class="adsbygoogle adslot" style="display:block" data-ad-client="${esc(CFG.ads.client)}"`
    + ` data-ad-slot="${esc(slot)}" data-ad-format="auto" data-full-width-responsive="true"></ins>`;
}
function mountAds() {
  if (!(CFG.ads && CFG.ads.client)) return;
  document.querySelectorAll("ins.adsbygoogle:not([data-done])").forEach(el => {
    el.setAttribute("data-done", "1");
    try { (window.adsbygoogle = window.adsbygoogle || []).push({}); } catch (e) { }
  });
}

function route() {
  const h = decodeURIComponent(location.hash.slice(1));
  if (h.startsWith("peca/")) return showSearch(h.slice(5));
  if (h.startsWith("veic/")) return showVehicle(h.slice(5));
  if (h.startsWith("id/")) return showDetail(h.slice(3));
  showHome();
}

/* ---------- busca unificada (caixa única) ---------- */
const goSearch  = q    => location.hash = "peca/" + encodeURIComponent(q);
const goVehicle = name => location.hash = "veic/" + encodeURIComponent(name);
const goDetail  = id   => location.hash = "id/"   + encodeURIComponent(id);

$("#go").onclick = submit;
input.addEventListener("keydown", e => { if (e.key === "Enter") submit(); });

/* Enter / botão: melhor palpite. Código (tem dígito) -> busca de peça;
   texto que casa um veículo -> veículo; senão -> busca de peça/descrição. */
async function submit() {
  const q = input.value.trim();
  if (!q) return;
  suggestBox.hidden = true;
  if (/\d/.test(q)) return goSearch(q);
  spin();
  try {
    const { vehicles } = await api("/api/suggest?q=" + encodeURIComponent(q));
    if (vehicles && vehicles.length) return goVehicle(vehicles[0].name);
  } catch (_) {}
  goSearch(q);
}

/* autocomplete unificado: veículos + peças/códigos num dropdown só */
let sugT;
input.addEventListener("input", () => {
  clearTimeout(sugT);
  const q = input.value.trim();
  if (q.length < 2) { suggestBox.hidden = true; return; }
  sugT = setTimeout(() => loadSuggest(q), 160);
});

async function loadSuggest(q) {
  let data;
  try { data = await api("/api/suggest?q=" + encodeURIComponent(q)); }
  catch (_) { suggestBox.hidden = true; return; }
  if (input.value.trim() !== q) return;              // descarta resposta obsoleta
  const vs = data.vehicles || [], ps = data.parts || [];
  let html = "";
  if (vs.length) html += `<div class="sgroup">Veículos</div>` + vs.map(s =>
    `<div class="sitem" data-veh="${esc(s.name)}"><span>🚗 ${esc(s.brand)} <b>${esc(s.name)}</b></span><span class="b">${s.parts} peças</span></div>`).join("");
  if (ps.length) html += `<div class="sgroup">Peças / códigos</div>` + ps.map(p =>
    `<div class="sitem" data-id="${esc(p.id)}"><span>🔩 <b>${esc(p.part_number)}</b> · ${esc(p.brand || "")}</span><span class="b">${esc(p.product_group || "")}</span></div>`).join("");
  html += `<div class="sitem saction" data-search="1"><span>🔍 Buscar “${esc(q)}” em peças e códigos</span></div>`;
  suggestBox.innerHTML = html;
  suggestBox.hidden = false;
  suggestBox.querySelectorAll("[data-veh]").forEach(d => d.onclick = () => { suggestBox.hidden = true; goVehicle(d.dataset.veh); });
  suggestBox.querySelectorAll("[data-id]").forEach(d => d.onclick = () => { suggestBox.hidden = true; goDetail(d.dataset.id); });
  suggestBox.querySelectorAll("[data-search]").forEach(d => d.onclick = () => { suggestBox.hidden = true; goSearch(q); });
}
document.addEventListener("click", e => { if (!e.target.closest(".searchbox")) suggestBox.hidden = true; });

/* ---------- telas ---------- */
function showHome() {
  main.innerHTML = `<div class="hero">
    <div class="hero-ico">🔧</div>
    <h2>Ache a peça — e o equivalente de qualquer marca</h2>
    <p>Digite um <b>veículo</b>, um <b>código</b> (próprio ou OEM) ou o <b>nome da peça</b>.
       O intercâmbio cruza marcas e catálogos pra você.</p>
    <div class="hero-eg">
      <span class="eglbl">Experimente</span>
      <button class="egchip" data-veh="OUTBACK">🚗 Outback</button>
      <button class="egchip" data-veh="CIVIC">🚗 Civic</button>
      <button class="egchip" data-veh="HILUX">🚗 Hilux</button>
      <button class="egchip" data-code="04C103085A">🔩 04C103085A</button>
    </div>
  </div>`;
  main.querySelectorAll("[data-veh]").forEach(c => c.onclick = () => { input.value = c.textContent.replace(/^\S+\s/, ""); goVehicle(c.dataset.veh); });
  main.querySelectorAll("[data-code]").forEach(c => c.onclick = () => { input.value = c.dataset.code; goSearch(c.dataset.code); });
}

const spin = () => main.innerHTML = `<div class="spinner">buscando…</div>`;

function cardHTML(r) {
  const via = r.match_type === "oem" && r.matched_code
    ? `<span class="via">↔ equivale a ${esc(r.matched_code)}</span>` : "";
  const label = { codigo: "código", oem: "OEM", descricao: "descrição" }[r.match_type] || "";
  const badge = label ? `<span class="badge ${esc(r.match_type)}">${label}</span>` : "";
  return `<div class="card" data-id="${esc(r.id)}">
    <div class="top"><span class="pn">${esc(r.part_number)}</span>${badge}</div>
    <div class="grp">${esc(r.product_group || "—")}</div>
    <div class="meta"><span><b>${esc(r.brand||"")}</b></span>${via}
      <span>${esc((r.catalog||"").split(".")[0])}</span></div>
  </div>`;
}
function wireCards(root) {
  (root || main).querySelectorAll(".card[data-id]").forEach(c =>
    c.onclick = () => location.hash = "id/" + encodeURIComponent(c.dataset.id));
}

/* lista de resultados com filtros (texto + marca) e barra de rolagem.
   os dados vêm inteiros do servidor; a filtragem é feita no cliente. */
function renderResults(results, statusText, filterPlaceholder) {
  const brands = [...new Set(results.map(r => r.brand).filter(Boolean))].sort();
  const brandOpts = brands.map(b => `<option value="${esc(b)}">${esc(b)}</option>`).join("");
  main.innerHTML = `
    <div class="status">${statusText}</div>
    <div class="resbar">
      <input class="resfilter" id="resfilter" autocomplete="off" placeholder="${esc(filterPlaceholder || "filtrar nestes resultados…")}">
      <select class="selbox" id="resbrand">
        <option value="">Todas as marcas (${brands.length})</option>${brandOpts}
      </select>
    </div>
    <div class="reslist" id="reslist"></div>
    <div class="status subcount" id="rescount"></div>
    ${adUnit(CFG.ads && CFG.ads.slot_results)}`;

  const listEl = $("#reslist"), countEl = $("#rescount");
  const fInput = $("#resfilter"), bSel = $("#resbrand");
  function apply() {
    const term = ua(fInput.value.trim());
    const brand = bSel.value;
    const filtered = results.filter(r => {
      if (brand && r.brand !== brand) return false;
      if (term) {
        const hay = ua([r.part_number, r.product_group, r.brand, r.application, r.matched_code, r.catalog].filter(Boolean).join(" "));
        if (!hay.includes(term)) return false;
      }
      return true;
    });
    listEl.innerHTML = filtered.length
      ? filtered.map(cardHTML).join("")
      : `<div class="empty small"><div class="big">🔍</div><p>Nenhum resultado com esses filtros.</p></div>`;
    countEl.textContent = filtered.length === results.length
      ? `${results.length} resultado(s)`
      : `${filtered.length} de ${results.length} resultado(s)`;
    wireCards(listEl);
  }
  fInput.addEventListener("input", apply);
  bSel.addEventListener("change", apply);
  apply();
  mountAds();
}

// links de busca por número em catálogos OEM globais (cauda-longa OEM-only)
function oemCatalogHtml(links, code) {
  if (!links || !links.length) return "";
  const items = links.map(l =>
    `<a class="oemcat" href="${esc(l.url)}" target="_blank" rel="noopener sponsored">${esc(l.store)} ↗</a>`).join("");
  return `<div class="oemwrap"><div class="oemhint">Buscar o código <b>${esc(code)}</b> nos catálogos OEM:</div>`
    + `<div class="oemlinks">${items}</div></div>`;
}

async function showSearch(q) {
  input.value = q; spin();
  const res = await api("/api/search?q=" + encodeURIComponent(q));
  const results = res.results || [];
  if (!results.length) return void (main.innerHTML = `<div class="empty"><div class="big">🔍</div>`
    + `<p>Nada no nosso banco para <b>${esc(q)}</b>.</p>`
    + oemCatalogHtml(res.oem_links, q.trim()) + `</div>`);
  renderResults(results, `${results.length} resultado(s) para <b>${esc(q)}</b>`);
}

async function showVehicle(name) {
  input.value = name; spin();
  const { results } = await api("/api/vehicle/parts?name=" + encodeURIComponent(name));
  if (!results.length) return void (main.innerHTML = `<div class="empty"><div class="big">🚗</div><p>Nenhuma peça achada para <b>${esc(name)}</b>.</p></div>`);
  renderResults(results, `${results.length} peça(s) que atendem <b>${esc(name)}</b>`, "Filtrar peça: nome ou código (ex.: corrente, rolamento)…");
}

async function showDetail(id) {
  spin();
  const d = await api("/api/part/" + encodeURIComponent(id));
  if (d.detail) return void (main.innerHTML = `<div class="empty"><p>Peça não encontrada.</p></div>`);

  const chips = [];
  if (d.status) chips.push(d.status);
  if (d.catalog) chips.push(d.catalog.split(".")[0]);
  if (d.universal) chips.push("aplicação universal");
  (d.old_codes || []).slice(0, 6).forEach(c => chips.push("ex-código " + c));

  const xr = d.cross_references || [], sp = d.specifications || [], vs = d.vehicles || [];
  // agrupa veículos por marca
  const byBrand = {};
  vs.forEach(v => { (byBrand[v.brand || "—"] = byBrand[v.brand || "—"] || []).push(v); });

  let html = `<button class="back" onclick="history.back()">← voltar</button>
    <div class="detail-head">
      <div class="top"><span class="pn">${esc(d.part_number)}</span></div>
      <div class="grp">${esc(d.product_group || "")} · <b>${esc(d.brand || "")}</b></div>
      ${d.application ? `<p style="color:var(--muted);margin:8px 0 0">${esc(d.application)}</p>` : ""}
      <div class="chips">${chips.map(c => `<span class="chip">${esc(c)}</span>`).join("")}</div>
    </div>`;

  // ---- cotação (lead) — só quando habilitada (ACHAPECA_QUOTE=1) ----
  if (d.quote_enabled) html += `<div class="cotacao" id="cotacao">
    <button class="cta-cot" id="cotBtn">💬 Pedir cotação<span>receba preços de lojas — sem compromisso</span></button>
    <form class="cotform" id="cotForm" hidden>
      <input id="cotHp" class="hp" name="website" tabindex="-1" autocomplete="off" aria-hidden="true" placeholder="Deixe em branco">
      <input id="cotZap" inputmode="tel" autocomplete="tel" placeholder="WhatsApp com DDD *">
      <input id="cotNome" autocomplete="name" placeholder="Seu nome">
      <div class="cotrow2">
        <input id="cotCidade" placeholder="Cidade / UF">
        <input id="cotQtd" inputmode="numeric" placeholder="Qtde">
      </div>
      <textarea id="cotObs" rows="2" placeholder="Observação (opcional)"></textarea>
      <button type="submit" class="cotsend">Enviar pedido de cotação</button>
      <div class="cotmsg" id="cotMsg"></div>
    </form>
  </div>`;

  const buy = d.buy || {};
  const prods = buy.products || [], slinks = buy.search_links || [], oemLinks = buy.oem_links || [];
  if (prods.length || slinks.length || oemLinks.length) {
    html += `<div class="section"><h3>Comprar 🛒</h3>`;
    if (prods.length) {
      html += `<div class="prodgrid">` + prods.map(p => `
        <a class="prod" href="${esc(p.url)}" target="_blank" rel="noopener sponsored">
          ${p.thumbnail ? `<img loading="lazy" src="${esc(p.thumbnail)}" alt="">` : `<div class="noimg">🔩</div>`}
          <div class="pn2">${esc(p.name)}</div>
          ${p.price ? `<div class="price">R$ ${p.price.toLocaleString("pt-BR", {minimumFractionDigits: 2})}</div>` : ""}
          <span class="ml">Mercado Livre ↗</span>
        </a>`).join("") + `</div>`;
    }
    if (slinks.length) {
      html += `<div class="buybox">` + slinks.map(b => `
        <a class="buy ${esc(b.kind)}" href="${esc(b.url)}" target="_blank" rel="noopener sponsored">
          <span class="store">Mercado Livre</span><span class="lbl">Buscar: ${esc(b.label)}</span></a>`).join("") + `</div>`;
    }
    if (oemLinks.length) html += oemCatalogHtml(oemLinks, buy.oem_code || d.part_number);
    html += `<div class="buynote">Links patrocinados — comprando por aqui você apoia o acha peça.</div></div>`;
  }

  if (xr.length) html += `<div class="section"><h3>Equivalentes / OEM <span class="n">${xr.length}</span></h3>` +
    xr.map(c => {
      // marca a exibir, por confiança: marca real > montadora confirmada (xref) >
      // montadora provável (por aplicação) > rótulo genérico honesto.
      let label = c.brand || "OEM", cls = "";
      if (c.oem_generic) {
        const am = c.automakers || [];
        if (am.length && c.automaker_source === "xref") { label = am.join(" / ") + " · original"; }
        else if (am.length && c.automaker_source === "veiculo") { label = am.join(" / ") + " · por aplicação"; cls = " infer"; }
        else { label = "Código original (OEM)"; cls = " gen"; }
      }
      return `<div class="xref"><span class="brand${cls}">${esc(label)}</span><span class="code">${esc(c.part_number)}</span></div>`;
    }).join("") + `</div>`;

  if (sp.length) html += `<div class="section"><h3>Dimensões &amp; técnicas <span class="n">${sp.length}</span></h3><div class="grid">` +
    sp.map(s => `<div class="spec"><div class="k">${esc(s.description || s.category)}</div><div class="v">${esc(s.value)}</div></div>`).join("") + `</div></div>`;

  const brandNames = Object.keys(byBrand).sort();
  if (vs.length) {
    html += `<div class="section">
      <h3>Veículos atendidos <span class="n">${vs.length}</span></h3>
      <div class="vehmeta"><b>${brandNames.length}</b> marca(s) de veículos atendida(s)</div>
      <div class="resbar">
        <select class="selbox" id="vehbrandsel">
          ${brandNames.map(b => `<option value="${esc(b)}">${esc(b)} (${byBrand[b].length})</option>`).join("")}
        </select>
      </div>
      <div class="vehscroll" id="vehscroll"></div>
      <div class="status subcount" id="vehcount"></div>
    </div>`;
  }
  const mans = d.manuals || [];
  if (mans.length) {
    html += `<div class="section"><h3>Manuais de fábrica <span class="n">${mans.length}</span></h3>` +
      mans.map(m => {
        const files = (m.files || []).map(f =>
          `<a class="manual" href="${esc(f.url)}" target="_blank" rel="noopener">
             <span class="mext">${esc((f.ext || "").toUpperCase())}</span>
             <span class="mtitle">${esc(f.title)}</span>
             ${f.size ? `<span class="msize">${fmtSize(f.size)}</span>` : ""}</a>`).join("");
        const more = m.count > (m.files || []).length
          ? `<div class="mmore">+${m.count - m.files.length} outro(s) arquivo(s)</div>` : "";
        return `<details class="mgroup"><summary>${esc(m.brand)} · ${esc(m.model)} <span class="n">${m.count}</span></summary>${files}${more}</details>`;
      }).join("") +
      `<div class="buynote">Manuais de fábrica (jdmfsm.info) — para consulta técnica da montadora/modelo.</div></div>`;
  }

  html += adUnit(CFG.ads && CFG.ads.slot_detail);
  main.innerHTML = html;
  window.scrollTo(0, 0);
  mountAds();

  // cotação: abre o form e envia o lead (POST /api/quote)
  const cotBtn = $("#cotBtn"), cotForm = $("#cotForm");
  if (cotBtn && cotForm) {
    cotBtn.onclick = () => {
      cotForm.hidden = !cotForm.hidden;
      cotBtn.classList.toggle("open", !cotForm.hidden);
      if (!cotForm.hidden) $("#cotZap").focus();
    };
    cotForm.onsubmit = async e => {
      e.preventDefault();
      const msg = $("#cotMsg"), zap = $("#cotZap").value.trim();
      if (zap.replace(/\D/g, "").length < 10) {
        msg.className = "cotmsg err"; msg.textContent = "Informe um WhatsApp válido com DDD."; return;
      }
      const send = cotForm.querySelector(".cotsend");
      send.disabled = true; send.textContent = "Enviando…"; msg.textContent = "";
      try {
        const r = await fetch("/api/quote", {
          method: "POST", headers: { "content-type": "application/json" },
          body: JSON.stringify({
            part_id: d.id, part_number: d.part_number, brand: d.brand,
            product_group: d.product_group, name: $("#cotNome").value,
            whatsapp: zap, city: $("#cotCidade").value,
            quantity: parseInt($("#cotQtd").value) || null, note: $("#cotObs").value,
            website: $("#cotHp").value
          })
        });
        const j = await r.json().catch(() => ({}));
        if (!r.ok || !j.ok) throw new Error(j.detail || "Não deu para enviar agora. Tente de novo.");
        cotForm.innerHTML = `<div class="cotok">✅ Pedido recebido!<br>Em breve entramos em contato pelo WhatsApp com as melhores ofertas para <b>${esc(d.part_number)}</b>.</div>`;
      } catch (err) {
        msg.className = "cotmsg err"; msg.textContent = err.message || "Não deu para enviar agora. Tente de novo.";
        send.disabled = false; send.textContent = "Enviar pedido de cotação";
      }
    };
  }

  // combo de marca de veículo: mostra a lista da marca escolhida (1ª pré-selecionada),
  // com limite e barra de rolagem.
  const vsel = $("#vehbrandsel");
  if (vsel) {
    const MODEL_LIMIT = 80;
    const box = $("#vehscroll"), vc = $("#vehcount");
    // agrupa por MODELO (name) -> MOTORIZAÇÃO (engine_config), somando versões e
    // códigos de motor. Some as duplicatas gigantes da fonte (mesmo carro repetido).
    const renderVeh = () => {
      const b = vsel.value, list = byBrand[b] || [];
      const models = {};
      list.forEach(v => {
        const name = (v.name || "—").trim() || "—";
        const cfg = (v.engine_config || "").trim();
        const en = (v.engine_name || "").trim();
        const ver = (v.model || "").trim();
        const ys = v.year_start, ye = v.year_end;
        const yr = ys ? (ye && ye !== ys ? ys + "–" + ye : ys + "+") : "";
        // motorização = engine_config; sem motor (ex.: Cofap), usa motor/versão/anos como chave
        const key = cfg || en || ver || yr || "—";
        const m = models[name] || (models[name] = {});
        const g = m[key] || (m[key] = { label: cfg, versions: new Set(), engines: new Set(), fuels: new Set(), yMin: null, yMax: null });
        if (ver && ver !== "-") g.versions.add(ver);
        if (en && en !== cfg) g.engines.add(en);
        const fu = (v.fuel || "").trim().toUpperCase();
        if (fu && fu !== "-" && fu !== "N/A") g.fuels.add(fu);
        if (ys) { g.yMin = g.yMin == null ? ys : Math.min(g.yMin, ys); g.yMax = Math.max(g.yMax || 0, ye || ys); }
      });
      const names = Object.keys(models).sort((a, b) => a.localeCompare(b, "pt-BR"));
      let totalMot = 0;
      names.forEach(n => totalMot += Object.keys(models[n]).length);
      box.innerHTML = names.slice(0, MODEL_LIMIT).map(name => {
        const mots = Object.values(models[name]).sort((a, b) => (a.label || "").localeCompare(b.label || "", "pt-BR"));
        const rows = mots.map(g => {
          const primary = g.label || [...g.versions].sort().join(", ") || "—";
          const subParts = g.label ? [[...g.versions].sort().join(", "), [...g.engines].sort().join(", ")] : [[...g.engines].sort().join(", ")];
          const sub = subParts.filter(Boolean).join(" · ");
          const year = g.yMin ? (g.yMax && g.yMax !== g.yMin ? g.yMin + "–" + g.yMax : g.yMin + "+") : "";
          const fuels = [...g.fuels].sort().map(f =>
            `<span class="fuel f-${esc(f.split("/")[0].toLowerCase())}">${esc(f)}</span>`).join("");
          return `<div class="vmmot"><span class="vmcfg">${esc(primary)}</span>${fuels}` +
            `${year ? `<span class="vmyear">${esc(year)}</span>` : ""}` +
            `${sub ? `<span class="vmsub">${esc(sub)}</span>` : ""}</div>`;
        }).join("");
        return `<div class="vehmodel"><div class="vmname">${esc(name)} <span class="vmn">${mots.length}</span></div>${rows}</div>`;
      }).join("");
      vc.textContent = `${names.length} modelo(s) · ${totalMot} motorização(ões) — ${b}` +
        (names.length > MODEL_LIMIT ? ` (mostrando ${MODEL_LIMIT} modelos)` : "");
    };
    vsel.addEventListener("change", renderVeh);
    renderVeh();
  }
}

/* ---------- stats no rodapé ---------- */
async function loadStats() {
  try {
    const s = await api("/api/stats");
    $("#foot").innerHTML = `<b>${s.products.toLocaleString("pt-BR")}</b> peças · ` +
      `<b>${s.cross_refs.toLocaleString("pt-BR")}</b> equivalências · ` +
      `<b>${s.vehicles.toLocaleString("pt-BR")}</b> aplicações · ${s.catalogs.length} catálogos`;
  } catch (e) { }
}

/* ---------- service worker (PWA) ---------- */
if ("serviceWorker" in navigator) navigator.serviceWorker.register("/sw.js").catch(() => { });
