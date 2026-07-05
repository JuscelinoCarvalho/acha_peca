"""Passo 0 (capstone) — peça com os 3 pilares: cross-ref OEM + dimensões + veículos.

Confirma que crossReferences (Produtos Similares) vem pela API. É o dado-âncora
do banco: número da peça -> equivalentes OEM de várias marcas.
"""

import json
import sys
from playwright.sync_api import sync_playwright

TERM = sys.argv[1] if len(sys.argv) > 1 else "retentor"
URL = "https://catalogo.sabo.com.br/"
ENDPOINT = "https://bff.catalogofraga.com.br/gateway/graphql"

QUERY = """query Full($query:String!,$market:MarketType!,$take:Int){
  catalogSearch(query:$query, market:$market, take:$take, onlyWithCodeDistributor:false){
    nodes{ product{
      partNumber brand{name} summaryApplication
      crossReferences{ brand{ name } partNumber }
      specifications{ category description value }
      vehicles{ brand name model }
      oldCodes
    }}
  }
}"""

with sync_playwright() as p:
    b = p.chromium.launch(headless=True)
    pg = b.new_page()
    pg.goto(URL, wait_until="networkidle", timeout=60000)
    pg.wait_for_timeout(2000)
    res = pg.evaluate(
        """async ({e,q,term}) => {
            const r = await fetch(e,{method:'POST',headers:{'content-type':'application/json'},
              body: JSON.stringify({operationName:'Full', query:q, variables:{query:term, market:'BRA', take:12}})});
            return await r.json();
        }""", {"e": ENDPOINT, "q": QUERY, "term": TERM})
    b.close()

if res.get("errors"):
    print("errors:", json.dumps(res["errors"], ensure_ascii=False)[:300])
nodes = (((res.get("data") or {}).get("catalogSearch") or {}).get("nodes")) or []

shown = 0
for n in nodes:
    p_ = n["product"]
    xr = p_.get("crossReferences") or []
    if not xr:
        continue
    dims = [s for s in (p_.get("specifications") or []) if "dimens" in (s.get("category") or "").lower()
            or any(w in (s.get("description") or "").lower() for w in ("diâmetro", "diametro", "largura", "altura", "espessura"))]
    vs = p_.get("vehicles") or []
    print(f"\n══ Peça SABÓ {p_['partNumber']} — {(p_.get('summaryApplication') or '')[:70]}")
    print(f"   OEM equivalentes ({len(xr)}):")
    for c in xr[:12]:
        bn = (c.get("brand") or {}).get("name") if isinstance(c.get("brand"), dict) else c.get("brand")
        print(f"      {str(bn):22} {c.get('partNumber')}")
    if dims:
        print("   dimensões:")
        for s in dims[:6]:
            print(f"      {s.get('description')}: {s.get('value')}")
    print(f"   veículos atendidos: {len(vs)}")
    shown += 1
    if shown >= 3:
        break
print(f"\n({len(nodes)} peças; mostrei {shown} com cross-reference OEM)")
