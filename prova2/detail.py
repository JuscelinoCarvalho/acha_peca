"""Prova 2d — busca por código exato e captura a query de APLICAÇÕES (veículos).

Ao abrir um produto, o SPA busca a lista de veículos que a peça atende. Capturamos
essa operação GraphQL (nome, variáveis, resposta) + os headers do request, para
depois chamar a API direto. É o dado central do projeto (intercâmbio por veículo).
"""

import json
import sys
from pathlib import Path
from playwright.sync_api import sync_playwright

CODE = sys.argv[1] if len(sys.argv) > 1 else "82401"
URL = "https://catalogo.sabo.com.br/"
OUT = Path(__file__).resolve().parent / "capture"
OUT.mkdir(exist_ok=True)
calls = []


def on_response(resp):
    if "graphql" not in resp.url:
        return
    rec = {"status": resp.status}
    try:
        rec["headers"] = dict(resp.request.headers)
    except Exception:
        pass
    try:
        rec["request"] = resp.request.post_data
    except Exception:
        pass
    try:
        rec["response"] = resp.text()
    except Exception:
        pass
    calls.append(rec)


with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page()
    page.on("response", on_response)
    page.goto(URL, wait_until="networkidle", timeout=60000)
    page.wait_for_timeout(2500)
    for sel in ["button[id*='rd-close']", "[aria-label*='close']"]:
        try:
            page.click(sel, timeout=1200)
        except Exception:
            pass
    # aba CÓDIGO DA PEÇA
    try:
        page.click("text=CÓDIGO DA PEÇA", timeout=5000)
        page.wait_for_timeout(700)
    except Exception:
        pass
    for inp in page.query_selector_all("input[type='text'], input:not([type])"):
        try:
            if inp.is_visible():
                inp.click(); inp.fill(CODE); break
        except Exception:
            continue
    try:
        page.click("text=Buscar", timeout=5000)
    except Exception:
        page.keyboard.press("Enter")
    page.wait_for_timeout(5000)
    # tenta clicar no primeiro resultado/produto para abrir o detalhe (aplicações)
    for sel in ["text=" + CODE, "[class*='product']", "[class*='card']", "a[href*='produto']"]:
        try:
            el = page.query_selector(sel)
            if el and el.is_visible():
                el.click(); break
        except Exception:
            continue
    page.wait_for_timeout(6000)
    page.screenshot(path=str(OUT / "sabo_detail.png"), full_page=True)
    browser.close()

(OUT / "detail_calls.json").write_text(json.dumps(calls, ensure_ascii=False, indent=2))
print(f"{len(calls)} chamadas GraphQL:\n")
for i, c in enumerate(calls):
    op = "?"
    try:
        rq = json.loads(c.get("request") or "{}")
        op = (rq[0] if isinstance(rq, list) else rq).get("operationName", "?")
    except Exception:
        pass
    print(f"#{i} op={op} status={c['status']} resp_len={len(c.get('response') or '')}")
# imprime headers de um request (para chamar a API direto depois)
if calls:
    print("\nHEADERS de exemplo (para chamada direta):")
    h = calls[-1].get("headers", {})
    for k in ("content-type", "origin", "referer", "authorization", "apollographql-client-name", "x-catalog-id"):
        if k in h:
            print(f"  {k}: {h[k]}")
print("\nSalvo: prova2/capture/detail_calls.json + sabo_detail.png")
