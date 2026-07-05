"""Prova 2b — dirige uma busca no catálogo Sabó/Fraga e captura a API de resultados.

Descobre o endpoint da BFF do Fraga que devolve produtos + aplicações (a lista de
veículos que cada peça atende) como JSON. Uma vez conhecido o endpoint, dá para
chamá-lo direto (sem automação de UI), que é a base do motor de dados.
"""

import json
import sys
from pathlib import Path
from playwright.sync_api import sync_playwright

TAB = sys.argv[1] if len(sys.argv) > 1 else "BUSCA GERAL"
TERM = sys.argv[2] if len(sys.argv) > 2 else "junta cabecote"
URL = "https://catalogo.sabo.com.br/"
OUT = Path(__file__).resolve().parent / "capture"
OUT.mkdir(exist_ok=True)

hits = []


def on_response(resp):
    u = resp.url
    if "catalogofraga.com.br" in u and ("catalog/url" not in u):
        rec = {"url": u, "status": resp.status, "method": resp.request.method}
        try:
            if "application/json" in resp.headers.get("content-type", ""):
                rec["json"] = resp.json()
        except Exception:
            pass
        hits.append(rec)


with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(user_agent=(
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"))
    page.on("response", on_response)
    page.goto(URL, wait_until="networkidle", timeout=60000)
    page.wait_for_timeout(2500)

    # Fecha popup de marketing (RD Station), se houver.
    for sel in ["button[id*='rd-close']", ".bricks--close", "[aria-label*='close']"]:
        try:
            page.click(sel, timeout=1500)
        except Exception:
            pass

    # Seleciona a aba de busca desejada.
    try:
        page.click(f"text={TAB}", timeout=5000)
        page.wait_for_timeout(800)
    except Exception as e:
        print(f"(aviso: não cliquei na aba {TAB!r}: {e})")

    # Digita o termo no primeiro input de texto visível da área de busca.
    filled = False
    for inp in page.query_selector_all("input[type='text'], input:not([type])"):
        try:
            if inp.is_visible():
                inp.click()
                inp.fill(TERM)
                filled = True
                break
        except Exception:
            continue
    print(f"→ aba={TAB!r} termo={TERM!r} preenchido={filled}")

    # Clica em Buscar.
    try:
        page.click("text=Buscar", timeout=5000)
    except Exception:
        try:
            page.keyboard.press("Enter")
        except Exception:
            pass
    page.wait_for_timeout(6000)  # espera resultados/API

    page.screenshot(path=str(OUT / "sabo_search.png"), full_page=True)
    (OUT / "search_hits.json").write_text(json.dumps(hits, ensure_ascii=False, indent=2))

    print(f"→ {len(hits)} chamadas à BFF do Fraga capturadas:")
    for h in hits:
        j = h.get("json")
        info = ""
        if isinstance(j, dict):
            info = " keys=" + ",".join(list(j.keys())[:8])
        elif isinstance(j, list):
            info = f" list[{len(j)}]"
        print(f"   [{h['status']}] {h['method']} {h['url'][:120]}{info}")
    browser.close()

print("\nSalvo: prova2/capture/search_hits.json + sabo_search.png")
