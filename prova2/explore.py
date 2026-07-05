"""Prova 2 — exploração do catálogo Sabó (plataforma Fraga, SPA JS).

Objetivo: descobrir COMO o SPA busca os dados. Em vez de raspar o DOM
renderizado (frágil), capturamos as chamadas de rede (XHR/fetch) que o app faz
— normalmente há uma API JSON por trás que devolve peças e suas APLICAÇÕES
(lista de veículos). Salva: as respostas JSON, um screenshot e o texto da página.
"""

import json
import sys
from pathlib import Path
from playwright.sync_api import sync_playwright

URL = sys.argv[1] if len(sys.argv) > 1 else "https://catalogo.sabo.com.br/"
OUT = Path(__file__).resolve().parent / "capture"
OUT.mkdir(exist_ok=True)

api_hits = []  # (url, status, content_type, sample)


def on_response(resp):
    try:
        ct = resp.headers.get("content-type", "")
        url = resp.url
        # Interessa: JSON e endpoints que cheirem a API (não imagens/css/js).
        if "application/json" in ct or "/api" in url.lower() or "consulta" in url.lower():
            body = None
            try:
                body = resp.json()
            except Exception:
                try:
                    body = resp.text()[:2000]
                except Exception:
                    body = "<sem corpo>"
            api_hits.append({"url": url, "status": resp.status, "ct": ct, "sample": body})
    except Exception as e:
        api_hits.append({"url": getattr(resp, "url", "?"), "error": str(e)})


with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(user_agent=(
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"))
    page.on("response", on_response)
    print(f"→ abrindo {URL}")
    page.goto(URL, wait_until="networkidle", timeout=60000)
    page.wait_for_timeout(4000)  # deixa o SPA assentar

    title = page.title()
    text = page.inner_text("body")[:3000]
    page.screenshot(path=str(OUT / "sabo_home.png"), full_page=True)

    # Dump das chamadas de API capturadas
    (OUT / "api_hits.json").write_text(json.dumps(api_hits, ensure_ascii=False, indent=2))
    (OUT / "page_text.txt").write_text(f"TITLE: {title}\n\n{text}")

    print(f"→ título: {title!r}")
    print(f"→ {len(api_hits)} chamadas de API/JSON capturadas")
    for h in api_hits[:20]:
        print(f"   [{h.get('status','?')}] {h['url'][:110]}")
    # procura por campos de busca / inputs para entender o fluxo
    inputs = page.eval_on_selector_all(
        "input, select, button",
        "els => els.slice(0,25).map(e => (e.tagName+':'+(e.name||e.id||e.placeholder||e.type||e.innerText||'').slice(0,40)))")
    print("→ controles na página (amostra):")
    for c in inputs:
        print("   ", c)
    browser.close()

print("\nArquivos salvos em prova2/capture/  (api_hits.json, page_text.txt, sabo_home.png)")
