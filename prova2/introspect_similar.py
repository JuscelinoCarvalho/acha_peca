"""Passo 0 do retorno — acha o campo/operação de "Produtos Similares" (cross-ref OEM).

Introspecta o schema GraphQL do Fraga pela sessão do navegador (sem WAF), procurando
tipos/campos ligados a similar/cross/oem/reference/equivalência, e lista TODOS os
campos do tipo Product (antes só imprimi um subconjunto filtrado).
"""

import json
from playwright.sync_api import sync_playwright

URL = "https://catalogo.sabo.com.br/"
ENDPOINT = "https://bff.catalogofraga.com.br/gateway/graphql"
KW = ("similar", "cross", "oem", "referenc", "equival", "aftermarket", "concorr", "interchang")

SCHEMA_Q = "{ __schema { types { name kind fields { name } } } }"
PRODUCT_Q = ("{ __type(name:\"Product\"){ fields { name args{name} "
             "type{ name kind ofType{ name kind ofType{name kind} } } } } }")

with sync_playwright() as p:
    b = p.chromium.launch(headless=True)
    pg = b.new_page()
    pg.goto(URL, wait_until="networkidle", timeout=60000)
    pg.wait_for_timeout(2000)

    def run(q):
        return pg.evaluate(
            """async ({e,q}) => {
                const r = await fetch(e,{method:'POST',headers:{'content-type':'application/json'},
                  body: JSON.stringify({query:q})});
                return await r.json();
            }""", {"e": ENDPOINT, "q": q})

    schema = run(SCHEMA_Q)
    product = run(PRODUCT_Q)
    b.close()

types = (((schema.get("data") or {}).get("__schema") or {}).get("types")) or []
print("== tipos/campos que casam com similar/cross/oem/reference ==")
for t in types:
    name = (t.get("name") or "")
    fields = [f["name"] for f in (t.get("fields") or [])]
    if any(k in name.lower() for k in KW):
        print(f"  TYPE {name}: {', '.join(fields)[:220]}")
    else:
        hits = [fn for fn in fields if any(k in fn.lower() for k in KW)]
        if hits:
            print(f"  {name} -> campos: {hits}")

print("\n== TODOS os campos do tipo Product ==")
for f in (((product.get("data") or {}).get("__type") or {}).get("fields") or []):
    t = f["type"]
    tn = t.get("name") or (t.get("ofType") or {}).get("name") or (((t.get("ofType") or {}).get("ofType")) or {}).get("name")
    args = [a["name"] for a in (f.get("args") or [])]
    print(f"  {f['name']:30} {t.get('kind'):10} -> {tn}   args={args}")
