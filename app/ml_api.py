"""Integração com a API oficial do Mercado Livre (busca de catálogo).

A busca de anúncios (/sites/MLB/search) foi fechada pelo ML (403 até com token).
Mas a busca de PRODUTOS do catálogo (/products/search) funciona com token de app
(client_credentials). Dá o produto oficial (id, nome, foto) → montamos o link de
compra /p/{id} com os parâmetros de afiliado. Preço/buy-box exigiria token de
usuário (OAuth) — fica como upgrade.

Config lida do .env (ML_CLIENT_ID, ML_CLIENT_SECRET, ML_MATT_WORD, ML_MATT_TOOL).
"""

import json
import re
import time
import urllib.parse
import urllib.request
from pathlib import Path

_ENV = {}
_env_file = Path(__file__).resolve().parent.parent / ".env"
if _env_file.exists():
    for _k, _v in re.findall(r'([A-Za-z_]+)\s*=\s*"?([^"\n]*)"?', _env_file.read_text()):
        _ENV[_k] = _v

CLIENT_ID = _ENV.get("ML_CLIENT_ID")
CLIENT_SECRET = _ENV.get("ML_CLIENT_SECRET")
SITE = _ENV.get("ML_SITE_ID", "MLB")
MATT_WORD = _ENV.get("ML_MATT_WORD", "jayman")
MATT_TOOL = _ENV.get("ML_MATT_TOOL", "")

_API = "https://api.mercadolibre.com"
_AFF = f"matt_word={MATT_WORD}&matt_tool={MATT_TOOL}"

# --- token de app (client_credentials), cacheado em memória ---
_token = {"value": None, "exp": 0}


def _get_token():
    if _token["value"] and time.time() < _token["exp"] - 120:
        return _token["value"]
    if not (CLIENT_ID and CLIENT_SECRET):
        return None
    data = urllib.parse.urlencode({
        "grant_type": "client_credentials",
        "client_id": CLIENT_ID, "client_secret": CLIENT_SECRET,
    }).encode()
    req = urllib.request.Request(_API + "/oauth/token", data=data,
                                 headers={"content-type": "application/x-www-form-urlencoded"})
    with urllib.request.urlopen(req, timeout=15) as r:
        tok = json.load(r)
    _token["value"] = tok.get("access_token")
    _token["exp"] = time.time() + (tok.get("expires_in") or 21600)
    return _token["value"]


def _api_get(path):
    tok = _get_token()
    if not tok:
        return None
    req = urllib.request.Request(_API + path, headers={"Authorization": "Bearer " + tok})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.load(r)


def buy_url(product_id: str) -> str:
    """Link de compra (página de catálogo) com atribuição de afiliado."""
    return f"https://www.mercadolivre.com.br/p/{product_id}?{_AFF}"


# --- cache de busca (query -> resultados) com TTL ---
_cache = {}
_TTL = 6 * 3600


def products_search(query: str, limit: int = 6):
    """Busca produtos do catálogo. Devolve [{id,name,thumbnail,url}]."""
    query = (query or "").strip()
    if not query:
        return []
    key = query.lower()
    hit = _cache.get(key)
    if hit and time.time() < hit[0]:
        return hit[1][:limit]
    try:
        qs = urllib.parse.urlencode({"status": "active", "site_id": SITE, "q": query})
        d = _api_get(f"/products/search?{qs}") or {}
    except Exception:
        return []
    out = []
    for r in (d.get("results") or []):
        if not isinstance(r, dict) or not r.get("id"):
            continue
        # Só produtos com oferta ativa. O catálogo do ML tem muitos produtos
        # "inactive" (sem vendedor) — sobretudo em autopeças — cujo /p/{id}
        # abre uma página morta. O param status=active da busca é ignorado
        # pela API, então filtramos aqui pelo status de cada produto.
        if r.get("status") != "active":
            continue
        pics = r.get("pictures") or []
        out.append({
            "id": r["id"],
            "name": r.get("name") or "",
            "thumbnail": (pics[0].get("url") if pics else None),
            "url": buy_url(r["id"]),
        })
    _cache[key] = (time.time() + _TTL, out)
    return out[:limit]
