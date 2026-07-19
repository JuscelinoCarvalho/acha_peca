"""Ingestão de peças genuínas do Amayama (catálogo OEM japonês).

A árvore EPC do Amayama (/genuine-catalogs/epc/...) fica atrás do desafio
gerenciado do Cloudflare — não é raspável de forma automatizada (headless e
headful foram bloqueados). Já as **páginas de peça** (`/en/part/<marca>/<código>`)
abrem em HTTP simples com User-Agent de navegador.

Fluxo (semi-manual, opção acordada): o operador navega o EPC do modelo no próprio
navegador (que passa o Cloudflare) e salva o HTML da página do chassi. Deste HTML
extraímos os códigos das peças (`extract_part_codes`); depois puxamos cada página
de peça por HTTP e parseamos (`parse_part_page`):

  - ld+json Product  -> código OEM (mpn), nome, marca
  - bloco fitness    -> aplicações (marca/modelo + chassi no data-content)
  - part-table_nested-> replacements (cross-refs OEM), quando houver

Cada peça vira um dict no shape da Fraga e entra via Store.upsert_product.

Uso:
  python -m motor amayama --html BP9.html --make subaru        # ingere
  python -m motor amayama --html BP9.html --dump-codes         # só lista códigos
  python -m motor amayama --part mitsubishi/mb344789           # uma peça
"""

import html as _html
import json
import re
import time
import urllib.request

from .store import Store

BASE = "https://www.amayama.com"
UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/126.0 Safari/537.36")

_PART_LINK = re.compile(r"/en/part/([a-z0-9-]+)/([a-z0-9]+)", re.I)


# ---- rede ------------------------------------------------------------------
def fetch(url, timeout=30):
    """GET simples com UA de navegador. Ergue em desafio Cloudflare / não-200."""
    req = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    })
    with urllib.request.urlopen(req, timeout=timeout) as r:
        body = r.read().decode("utf-8", "replace")
    if "Just a moment" in body or "cf-challenge" in body:
        raise RuntimeError("Cloudflare challenge (página bloqueada)")
    return body


# ---- extração de códigos de uma página de chassi/diagrama ------------------
def extract_part_codes(html_text, make=None):
    """Todos os (marca, código) de peça linkados no HTML. Se `make` for dado,
    filtra por ela. Devolve lista ordenada e sem repetição."""
    seen = []
    for mk, code in _PART_LINK.findall(html_text):
        mk = mk.lower()
        if make and mk != make.lower():
            continue
        pair = (mk, code.lower())
        if pair not in seen:
            seen.append(pair)
    return seen


# ---- parsing de uma página de peça -----------------------------------------
def _ldjson_product(t):
    for m in re.finditer(r'<script[^>]*application/ld\+json[^>]*>(.*?)</script>', t, re.S):
        try:
            d = json.loads(m.group(1))
        except json.JSONDecodeError:
            continue
        if isinstance(d, dict) and d.get("@type") == "Product":
            return d
    return {}


def _applications(t):
    """Bloco fitness (linha 'Model') -> lista de veículos.
    Cada item: <a href=.../genuine-catalogs/<make>/<model> data-content="Make Model: CH1, CH2">Make Model</a>
    """
    block = re.search(r"row-content models(.*?)</div>\s*</div>\s*</div>", t, re.S)
    scope = block.group(1) if block else ""
    out = []
    for m in re.finditer(
            r'genuine-catalogs/([a-z0-9-]+)/([^"]+)"[^>]*data-content="([^"]*)"[^>]*>\s*([^<]+?)\s*</a>',
            scope):
        mk_slug, _model_slug, dc, label = m.groups()
        make = mk_slug.replace("-", " ").upper()
        label = _html.unescape(label).strip()
        # nome do modelo = rótulo sem a marca à frente
        name = re.sub(rf"^{re.escape(mk_slug.replace('-', ' '))}\s+", "", label, flags=re.I).strip() or label
        chassis = _html.unescape(dc).split(":", 1)[-1].strip() if ":" in dc else None
        out.append({"brand": make, "name": name, "model": chassis,
                    "engineName": None, "engineConfiguration": None,
                    "fuel": None, "startYear": None, "endYear": None})
    return out


def _replacements(t, self_code):
    """Números OEM equivalentes (superseded/replacements) linkados na página."""
    codes = []
    for _mk, code in _PART_LINK.findall(t):
        c = code.upper()
        if c != self_code.upper() and c not in codes:
            codes.append(c)
    return codes


def parse_part_page(html_text):
    """HTML de /en/part/<marca>/<código> -> dict de produto (shape Fraga) ou None."""
    prod = _ldjson_product(html_text)
    mpn = (prod.get("mpn") or "").strip()
    if not mpn:
        return None
    make = (prod.get("brand") or {}).get("name", "").upper() if isinstance(prod.get("brand"), dict) else ""
    desc = (prod.get("description") or prod.get("name") or "").strip()
    xrefs = _replacements(html_text, mpn)
    return {
        "partNumber": mpn,
        "brand": {"name": make or None},
        "productGroup": {"name": desc or None},
        "status": "ACTIVE",
        "summaryApplication": None,
        "containsUniversalApplication": False,
        "oldCodes": xrefs,
        "crossReferences": [{"brand": {"name": "ORIGINAL OEM"}, "partNumber": c} for c in xrefs],
        "specifications": ([{"category": "peso", "description": "Peso",
                             "value": str(prod["weight"].get("value")), "important": False}]
                           if isinstance(prod.get("weight"), dict) and prod["weight"].get("value") else []),
        "vehicles": _applications(html_text),
    }


# ---- ingestão --------------------------------------------------------------
def ingest_amayama(codes, catalog_label="amayama", db_path=None,
                   delay=2.5, on_progress=print):
    """Puxa e grava cada (marca, código). `codes`: lista de (make, code).
    Ritmo gentil (delay entre requests) p/ não provocar o Cloudflare."""
    store = Store(db_path) if db_path else Store()
    ok = skip = 0
    try:
        for i, (mk, code) in enumerate(codes, 1):
            url = f"{BASE}/en/part/{mk}/{code}"
            try:
                p = parse_part_page(fetch(url))
            except Exception as e:
                on_progress(f"  ! {mk}/{code}: {e}")
                p = None
            if not p:
                skip += 1
            else:
                store.upsert_product(p, catalog_label)
                ok += 1
                if i % 10 == 0 or i == len(codes):
                    store.commit()
                    on_progress(f"  … {i}/{len(codes)}  ({p['partNumber']}: "
                                f"{len(p['vehicles'])} veíc, {len(p['crossReferences'])} cross)")
            if i < len(codes):
                time.sleep(delay)
        store.log_ingest("(AMAYAMA)", catalog_label, ok)
        store.commit()
    finally:
        store.close()
    on_progress(f"✓ {ok} peça(s) gravada(s), {skip} pulada(s) em {catalog_label!r}")
    return ok
