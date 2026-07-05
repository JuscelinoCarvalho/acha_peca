"""Prova 2e — chama a API GraphQL do Fraga DIRETO (sem navegador) e introspecta.

1) Replica a query GetProducts capturada -> prova acesso programático puro.
2) Introspecção do schema -> acha o campo/consulta de APLICAÇÕES (veículos por peça).
"""

import json
import urllib.request
from pathlib import Path

ENDPOINT = "https://bff.catalogofraga.com.br/gateway/graphql"
CAP = Path(__file__).resolve().parent / "capture" / "gql_calls.json"
HEADERS = {
    "content-type": "application/json",
    "origin": "https://catalogo.sabo.com.br",
    "referer": "https://catalogo.sabo.com.br/",
    "user-agent": "Mozilla/5.0 (X11; Linux x86_64) Chrome/120.0 Safari/537.36",
}


def gql(payload: dict) -> dict:
    data = json.dumps(payload).encode()
    req = urllib.request.Request(ENDPOINT, data=data, headers=HEADERS, method="POST")
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


# 1) Replica GetProducts capturada, chamando direto.
calls = json.loads(CAP.read_text())
getprod = None
for c in calls:
    try:
        rq = json.loads(c.get("request") or "{}")
        rq = rq[0] if isinstance(rq, list) else rq
        if rq.get("operationName") == "GetProducts":
            getprod = rq
            break
    except Exception:
        continue

print("== 1) Chamada direta GetProducts (query='junta cabecote') ==")
res = gql(getprod)
nodes = (((res.get("data") or {}).get("catalogSearch") or {}).get("nodes")) or []
print(f"  OK — {len(nodes)} produtos retornados via API direta (sem navegador)")
if nodes:
    p = nodes[0]["product"]
    print(f"  ex.: {p.get('partNumber')} / {(p.get('brand') or {}).get('name')} / id={p.get('id')}")

# 2) Introspecção: acha tipos/campos mencionando vehicle/application/aplic.
print("\n== 2) Introspecção: campos com vehicle/application ==")
introspection = {
    "query": "{ __schema { types { name kind fields { name } } } }"
}
schema = gql(introspection)
types = (((schema.get("data") or {}).get("__schema") or {}).get("types")) or []
kw = ("application", "vehicle", "veicul", "aplic", "fitment", "catalogsearch")
for t in types:
    name = (t.get("name") or "")
    fields = t.get("fields") or []
    fnames = [f["name"] for f in fields]
    hit_type = any(k in name.lower() for k in kw)
    hit_fields = [fn for fn in fnames if any(k in fn.lower() for k in kw)]
    if hit_type or hit_fields:
        print(f"  TYPE {name}: " + (", ".join(fnames)[:200] if hit_type else "campos→ " + ", ".join(hit_fields)))
