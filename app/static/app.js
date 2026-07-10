"use strict";
const $ = s => document.querySelector(s);
const main = $("#main"), input = $("#q"), suggestBox = $("#suggest"), hint = $("#hint");
let mode = "peca";
let CFG = { ads: null };
const esc = s => (s == null ? "" : String(s)).replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
/* minúsculas sem acento — filtro acento-insensível no cliente */
const ua = s => (s == null ? "" : String(s)).normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase();
const api = async u => (await fetch(u)).json();

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

/* ---------- modo (tabs) ---------- */
document.querySelectorAll(".tab").forEach(t => t.onclick = () => {
  document.querySelectorAll(".tab").forEach(x => x.classList.remove("active"));
  t.classList.add("active");
  mode = t.dataset.mode;
  input.value = ""; suggestBox.hidden = true;
  input.placeholder = mode === "peca"
    ? "Código da peça, código OEM ou descrição…"
    : "Nome do veículo (ex.: GOL, CIVIC, HILUX)…";
  hint.innerHTML = mode === "peca"
    ? "Digite um código (ex.: <b>04C103085A</b>) e ache a peça equivalente de qualquer marca."
    : "Digite um veículo e veja todas as peças do catálogo que o atendem.";
  input.focus();
});

/* ---------- busca ---------- */
$("#go").onclick = submit;
input.addEventListener("keydown", e => { if (e.key === "Enter") submit(); });
function submit() {
  const q = input.value.trim();
  if (!q) return;
  suggestBox.hidden = true;
  location.hash = (mode === "peca" ? "peca/" : "veic/") + encodeURIComponent(q);
}

/* autocomplete de veículo */
let sugT;
input.addEventListener("input", () => {
  if (mode !== "veiculo") { suggestBox.hidden = true; return; }
  clearTimeout(sugT);
  const q = input.value.trim();
  if (q.length < 2) { suggestBox.hidden = true; return; }
  sugT = setTimeout(async () => {
    const { suggestions } = await api("/api/vehicle/suggest?q=" + encodeURIComponent(q));
    if (!suggestions.length) { suggestBox.hidden = true; return; }
    suggestBox.innerHTML = suggestions.map(s =>
      `<div data-v="${esc(s.name)}"><span>${esc(s.brand)} <b>${esc(s.name)}</b></span><span class="b">${s.parts} peças</span></div>`).join("");
    suggestBox.hidden = false;
    suggestBox.querySelectorAll("div[data-v]").forEach(d => d.onclick = () => {
      input.value = d.dataset.v; suggestBox.hidden = true; submit();
    });
  }, 180);
});
document.addEventListener("click", e => { if (!e.target.closest(".searchbox")) suggestBox.hidden = true; });

/* ---------- telas ---------- */
function showHome() {
  main.innerHTML = `<div class="empty"><div class="big">🔧</div>
    <p>Busque por <b>código</b>, <b>código OEM</b>, <b>descrição</b> ou <b>veículo</b>.<br>
    O intercâmbio cruza marcas e catálogos automaticamente.</p></div>`;
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
function renderResults(results, statusText) {
  const brands = [...new Set(results.map(r => r.brand).filter(Boolean))].sort();
  const brandOpts = brands.map(b => `<option value="${esc(b)}">${esc(b)}</option>`).join("");
  main.innerHTML = `
    <div class="status">${statusText}</div>
    <div class="resbar">
      <input class="resfilter" id="resfilter" autocomplete="off" placeholder="filtrar nestes resultados…">
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

async function showSearch(q) {
  input.value = q; spin();
  const { results } = await api("/api/search?q=" + encodeURIComponent(q));
  if (!results.length) return void (main.innerHTML = `<div class="empty"><div class="big">🔍</div><p>Nada encontrado para <b>${esc(q)}</b>.</p></div>`);
  renderResults(results, `${results.length} resultado(s) para <b>${esc(q)}</b>`);
}

async function showVehicle(name) {
  input.value = name; spin();
  const { results } = await api("/api/vehicle/parts?name=" + encodeURIComponent(name));
  if (!results.length) return void (main.innerHTML = `<div class="empty"><div class="big">🚗</div><p>Nenhuma peça achada para <b>${esc(name)}</b>.</p></div>`);
  renderResults(results, `${results.length} peça(s) que atendem <b>${esc(name)}</b>`);
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
  const prods = buy.products || [], slinks = buy.search_links || [];
  if (prods.length || slinks.length) {
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
    const VLIMIT = 80;
    const box = $("#vehscroll"), vc = $("#vehcount");
    const vehItem = v => `<div class="veh"><span class="m">${esc(v.name || "")} ${esc(v.model || "")}</span>
      ${(v.engine_name || v.engine_config) ? `<div class="e">${esc([v.engine_name, v.engine_config].filter(Boolean).join(" · "))}</div>` : ""}</div>`;
    const renderVeh = () => {
      const b = vsel.value, list = byBrand[b] || [];
      box.innerHTML = list.slice(0, VLIMIT).map(vehItem).join("");
      vc.textContent = list.length > VLIMIT
        ? `mostrando ${VLIMIT} de ${list.length} veículo(s) — ${b}`
        : `${list.length} veículo(s) — ${b}`;
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
