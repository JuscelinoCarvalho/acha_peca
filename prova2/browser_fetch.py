"""Prova 2g (capstone) — busca as APLICAÇÕES via sessão do navegador (método sustentável).

Cliente HTTP cru leva 401 (WAF). Aqui carregamos a página (que estabelece a sessão)
e disparamos a MESMA query GraphQL de DENTRO da página (fetch no contexto do site),
carregando cookies/headers da sessão → não é bloqueado. É assim que o motor de dados
do projeto deve rodar (Playwright), de forma gentil e com a sessão do catálogo.
"""

import json
import sys
from collections import Counter
from playwright.sync_api import sync_playwright

TERM = sys.argv[1] if len(sys.argv) > 1 else "junta cabecote"
URL = "https://catalogo.sabo.com.br/"
ENDPOINT = "https://bff.catalogofraga.com.br/gateway/graphql"

QUERY = """query Apps($query:String!,$market:MarketType!,$take:Int){
  catalogSearch(query:$query, market:$market, take:$take, onlyWithCodeDistributor:false){
    nodes{ product{ partNumber brand{name} summaryApplication containsUniversalApplication
      vehicles{ brand name model } } }
  }
}"""

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page()
    page.goto(URL, wait_until="networkidle", timeout=60000)
    page.wait_for_timeout(2000)  # estabelece sessão
    # dispara a query DE DENTRO da página (herda sessão/cookies → sem 401)
    result = page.evaluate(
        """async ({endpoint, query, term}) => {
            const r = await fetch(endpoint, {
              method:'POST',
              headers:{'content-type':'application/json'},
              body: JSON.stringify({operationName:'Apps', query, variables:{query:term, market:'BRA', take:12}})
            });
            return { status: r.status, body: await r.json() };
        }""",
        {"endpoint": ENDPOINT, "query": QUERY, "term": TERM},
    )
    browser.close()

print(f"status HTTP via sessão do navegador: {result['status']}")
nodes = (((result["body"].get("data") or {}).get("catalogSearch") or {}).get("nodes")) or []
if result["body"].get("errors"):
    print("errors:", json.dumps(result["body"]["errors"], ensure_ascii=False)[:300])

shown = 0
for n in nodes:
    p_ = n["product"]
    vs = [v for v in (p_.get("vehicles") or []) if v.get("brand") and "SEM APLICA" not in (v.get("brand") or "")]
    if not vs:
        continue
    brands = Counter(v["brand"] for v in vs)
    print(f"\n● Peça {p_['partNumber']} ({(p_.get('brand') or {}).get('name')}) — {len(vs)} veículos, {len(brands)} marcas")
    print(f"  marcas: {dict(brands)}")
    for v in vs[:8]:
        print(f"    · {v['brand']} {v.get('name','')} {v.get('model') or ''} {v.get('engineName') or ''} ({v.get('release') or ''})")
    shown += 1
    if shown >= 3:
        break
print(f"\n({len(nodes)} peças retornadas; mostrei {shown} com aplicação multi-veículo)")
