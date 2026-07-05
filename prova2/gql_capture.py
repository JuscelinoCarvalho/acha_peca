"""Prova 2c — captura as queries GraphQL (request) e respostas (body) do Fraga.

Salva cada par request/response para entendermos a query de busca e o formato
dos dados de produto + aplicação (veículos que a peça atende).
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

calls = []


def on_response(resp):
    u = resp.url
    if "graphql" not in u:
        return
    rec = {"url": u, "status": resp.status}
    try:
        rec["request"] = resp.request.post_data
    except Exception as e:
        rec["request_err"] = str(e)
    try:
        rec["response"] = resp.text()
    except Exception as e:
        rec["response_err"] = str(e)
    calls.append(rec)


with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(user_agent=(
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"))
    page.on("response", on_response)
    page.goto(URL, wait_until="networkidle", timeout=60000)
    page.wait_for_timeout(2500)
    for sel in ["button[id*='rd-close']", ".bricks--close", "[aria-label*='close']"]:
        try:
            page.click(sel, timeout=1200)
        except Exception:
            pass
    try:
        page.click(f"text={TAB}", timeout=5000)
        page.wait_for_timeout(700)
    except Exception:
        pass
    for inp in page.query_selector_all("input[type='text'], input:not([type])"):
        try:
            if inp.is_visible():
                inp.click(); inp.fill(TERM); break
        except Exception:
            continue
    try:
        page.click("text=Buscar", timeout=5000)
    except Exception:
        page.keyboard.press("Enter")
    page.wait_for_timeout(7000)
    browser.close()

# Salva cada chamada e imprime um resumo (operationName + tamanho da resposta).
(OUT / "gql_calls.json").write_text(json.dumps(calls, ensure_ascii=False, indent=2))
print(f"{len(calls)} chamadas GraphQL capturadas:\n")
for i, c in enumerate(calls):
    op = "?"
    try:
        rq = json.loads(c.get("request") or "{}")
        if isinstance(rq, list):
            rq = rq[0]
        op = rq.get("operationName") or "?"
    except Exception:
        pass
    resp = c.get("response") or ""
    print(f"#{i} op={op} status={c['status']} resp_len={len(resp)}")
print("\nSalvo: prova2/capture/gql_calls.json")
