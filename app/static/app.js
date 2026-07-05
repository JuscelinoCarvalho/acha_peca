"use strict";
const $ = s => document.querySelector(s);
const main = $("#main"), input = $("#q"), suggestBox = $("#suggest"), hint = $("#hint");
let mode = "peca";
const esc = s => (s == null ? "" : String(s)).replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const api = async u => (await fetch(u)).json();

/* ---------- roteamento por hash ---------- */
window.addEventListener("hashchange", route);
window.addEventListener("DOMContentLoaded", () => { loadStats(); route(); });

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
function wireCards() {
  main.querySelectorAll(".card[data-id]").forEach(c =>
    c.onclick = () => location.hash = "id/" + encodeURIComponent(c.dataset.id));
}

async function showSearch(q) {
  input.value = q; spin();
  const { results } = await api("/api/search?q=" + encodeURIComponent(q));
  if (!results.length) return void (main.innerHTML = `<div class="empty"><div class="big">🔍</div><p>Nada encontrado para <b>${esc(q)}</b>.</p></div>`);
  main.innerHTML = `<div class="status">${results.length} resultado(s) para <b>${esc(q)}</b></div>` + results.map(cardHTML).join("");
  wireCards();
}

async function showVehicle(name) {
  input.value = name; spin();
  const { results } = await api("/api/vehicle/parts?name=" + encodeURIComponent(name));
  if (!results.length) return void (main.innerHTML = `<div class="empty"><div class="big">🚗</div><p>Nenhuma peça achada para <b>${esc(name)}</b>.</p></div>`);
  main.innerHTML = `<div class="status">${results.length} peça(s) que atendem <b>${esc(name)}</b></div>` + results.map(cardHTML).join("");
  wireCards();
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
    xr.map(c => `<div class="xref"><span class="brand">${esc(c.brand || "OEM")}</span><span class="code">${esc(c.part_number)}</span></div>`).join("") + `</div>`;

  if (sp.length) html += `<div class="section"><h3>Dimensões &amp; técnicas <span class="n">${sp.length}</span></h3><div class="grid">` +
    sp.map(s => `<div class="spec"><div class="k">${esc(s.description || s.category)}</div><div class="v">${esc(s.value)}</div></div>`).join("") + `</div></div>`;

  if (vs.length) {
    html += `<div class="section"><h3>Veículos atendidos <span class="n">${vs.length}</span></h3>`;
    for (const b of Object.keys(byBrand).sort()) {
      const list = byBrand[b];
      html += `<div class="vehbrand"><div class="bname">${esc(b)} <span class="n">${list.length}</span></div>` +
        list.slice(0, 40).map(v => `<div class="veh"><span class="m">${esc(v.name || "")} ${esc(v.model || "")}</span>
          ${(v.engine_name || v.engine_config) ? `<div class="e">${esc([v.engine_name, v.engine_config].filter(Boolean).join(" · "))}</div>` : ""}</div>`).join("") +
        (list.length > 40 ? `<div class="e" style="margin:2px">+${list.length - 40} outros</div>` : "") + `</div>`;
    }
    html += `</div>`;
  }
  main.innerHTML = html;
  window.scrollTo(0, 0);
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
