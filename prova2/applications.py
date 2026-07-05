"""Prova 2f (final) — mostra o INTERCÂMBIO: uma peça -> os veículos que ela atende.

Chama a API direto e pede o campo Product.vehicles. Demonstra que uma única peça
de reposição atende vários veículos/marcas (nacional + importado) = intercâmbio.
"""

import json
import sys
import urllib.request
from collections import Counter

ENDPOINT = "https://bff.catalogofraga.com.br/gateway/graphql"
HEADERS = {
    "content-type": "application/json",
    "origin": "https://catalogo.sabo.com.br",
    "referer": "https://catalogo.sabo.com.br/",
    "user-agent": "Mozilla/5.0 (X11; Linux x86_64) Chrome/120.0 Safari/537.36",
}
TERM = sys.argv[1] if len(sys.argv) > 1 else "retentor virabrequim"

QUERY = """
query Apps($query:String!,$market:MarketType!,$take:Int){
  catalogSearch(query:$query, market:$market, take:$take, onlyWithCodeDistributor:false){
    nodes{ product{
      partNumber
      brand{ name }
      summaryApplication
      containsUniversalApplication
      vehicles{ brand name model release engineName fuel }
    }}
  }
}
"""


def gql(query, variables):
    data = json.dumps({"operationName": "Apps", "query": query, "variables": variables}).encode()
    req = urllib.request.Request(ENDPOINT, data=data, headers=HEADERS, method="POST")
    with urllib.request.urlopen(req, timeout=40) as r:
        return json.loads(r.read())


res = gql(QUERY, {"query": TERM, "market": "BRA", "take": 5})
if res.get("errors"):
    print("ERROS:", json.dumps(res["errors"], ensure_ascii=False)[:800])
data = ((res.get("data") or {}).get("catalogSearch") or {})
nodes = data.get("nodes") or []
print(f"Busca: {TERM!r} — mostrando {len(nodes)}:\n")
for n in nodes:
    p = n["product"]
    vs = p.get("vehicles") or []
    brands = Counter(v.get("brand") for v in vs)
    print(f"● Peça {p['partNumber']} ({(p.get('brand') or {}).get('name')}) — atende {len(vs)} veículos")
    print(f"  resumo: {(p.get('summaryApplication') or '')[:90]}")
    print(f"  marcas atendidas: {dict(brands)}")
    for v in vs[:6]:
        print(f"    · {v.get('brand')} {v.get('name')} {v.get('model') or ''} {v.get('engineName') or ''} ({v.get('release') or ''})")
    print()
