"""Mapeia a plataforma de cada catálogo: quais hosts de API ele chama.

Confirma se vários catálogos rodam no MESMO Fraga (bff.catalogofraga.com.br) —
'1 motor, N catálogos' — e identifica catálogos em outras plataformas (ex. Frasle).
"""

import sys
from collections import Counter
from playwright.sync_api import sync_playwright

SITES = sys.argv[1:] or [
    "https://delphi.catalogofraga.com.br/",
    "https://catalogonakata.com.br/",
    "https://catalogo.sabo.com.br/",
]

with sync_playwright() as p:
    b = p.chromium.launch(headless=True)
    for site in SITES:
        hosts = Counter()
        fraga_catalog = []

        def on_req(req):
            try:
                from urllib.parse import urlparse
                h = urlparse(req.url).hostname or ""
                if any(k in h for k in ("api", "bff", "catalog", "graphql", "gateway")):
                    hosts[h] += 1
                if "catalog/url" in req.url:
                    fraga_catalog.append(req.url)
            except Exception:
                pass

        pg = b.new_page()
        pg.on("request", on_req)
        try:
            pg.goto(site, wait_until="networkidle", timeout=45000)
            pg.wait_for_timeout(3000)
            title = pg.title()
        except Exception as e:
            title = f"(erro: {str(e)[:60]})"
        is_fraga = any("catalogofraga" in h for h in hosts)
        print(f"\n■ {site}")
        print(f"   título: {title[:60]}")
        print(f"   plataforma: {'FRAGA ✓' if is_fraga else 'OUTRA'}")
        print(f"   hosts de API: {dict(hosts)}")
        pg.close()
    b.close()
