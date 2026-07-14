"""Sessão AUTENTICADA com a Fraga (catálogos que exigem login via Keycloak).

Vários catálogos (cofap, nakata, ...) fecharam a API pública em 2026-07 e agora
pedem login. O fluxo (descoberto no bundle Angular do catálogo):

  1. GET  {gateway}/api/v1/catalog/url/{urlenc(origin)}     -> { id, realm, ... }
  2. POST {keycloak}/realms/{realm}/protocol/openid-connect/token
         grant_type=password, client_id=catalog-user, username, password
     -> access_token (JWT, ~30min) + refresh_token
  3. POST {gateway}/graphql  com  Authorization: Bearer <token>

O PLANO da conta limita quais subcampos de Vehicle vêm (conta básica: só
brand/name/startYear/endYear/note; motor/modelo/combustível pedem plano pago).
Por isso a sessão SONDA os campos liberados no __enter__ e monta a query com o
que a conta permite — assim funciona para qualquer login que o usuário criar.

Mesma interface de HttpFragaSession (search_page/search_all) p/ plugar no ingest.
"""

import json
import time
import urllib.error
import urllib.request as U
from urllib.parse import quote, urlencode, urlsplit

from .session import ENDPOINT, FragaError  # ENDPOINT = gateway/graphql

_UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
_KEYCLOAK = "https://accounts.fraga.com.br"
_GATEWAY = "https://bff.catalogofraga.com.br/gateway"
_CLIENT_ID = "catalog-user"

# Subcampos de Vehicle candidatos (sondados 1 a 1 contra a conta). brand/name
# entram sempre. Os nomes GraphQL -> as chaves que o Store.upsert espera já batem
# (o Store lê v.get("engineName"), v.get("startYear") etc.).
_VEHICLE_FIELDS = ["model", "engineName", "engineConfiguration", "fuel",
                   "startYear", "endYear", "note"]


class AuthFragaSession:
    def __init__(self, catalog_url, username, password, delay=0.8,
                 vehicle_fields=None, headless=True):
        # `headless` é aceito só por compatibilidade de interface (não há browser).
        self.catalog_url = catalog_url.rstrip("/") + "/"
        s = urlsplit(self.catalog_url)
        self._origin = f"{s.scheme}://{s.netloc}"
        self.username = username
        self.password = password
        self.delay = delay
        # se o chamador já sabe os campos liberados, passa aqui e pula a sonda
        # (evita que um 429 na sonda degrade o conjunto de campos coletados).
        self._forced_fields = vehicle_fields
        self._token = None
        self._token_exp = 0.0
        self._realm = None
        self._vehicle_sel = "brand name"
        self._query = None

    # -- ciclo de vida -----------------------------------------------------
    def __enter__(self):
        self._resolve_realm()
        self._login()
        if self._forced_fields:
            fs = ["brand", "name"] + [f for f in self._forced_fields if f not in ("brand", "name")]
            self._vehicle_sel = " ".join(fs)
        else:
            self._probe_fields()
        self._build_query()
        return self

    def __exit__(self, *exc):
        self._token = None

    # -- auth --------------------------------------------------------------
    def _http(self, req, timeout=45):
        try:
            return U.urlopen(req, timeout=timeout)
        except urllib.error.HTTPError as e:
            raise FragaError(f"HTTP {e.code}: {e.read()[:200]!r}")

    def _resolve_realm(self):
        key = quote(self._origin, safe="")
        req = U.Request(f"{_GATEWAY}/api/v1/catalog/url/{key}",
                        headers={"User-Agent": _UA, "Accept": "application/json",
                                 "origin": self._origin, "referer": self.catalog_url})
        d = json.load(self._http(req, timeout=25))
        self._realm = d.get("realm")
        self.catalog_id = d.get("id")
        if not self._realm:
            raise FragaError(f"realm não resolvido para {self._origin}")

    def _login(self):
        data = urlencode({"grant_type": "password", "client_id": _CLIENT_ID,
                          "username": self.username, "password": self.password,
                          "scope": "openid"}).encode()
        req = U.Request(f"{_KEYCLOAK}/realms/{self._realm}/protocol/openid-connect/token",
                        data=data, headers={"Content-Type": "application/x-www-form-urlencoded",
                                            "User-Agent": _UA, "origin": self._origin,
                                            "referer": self.catalog_url})
        try:
            d = json.load(U.urlopen(req, timeout=25))
        except urllib.error.HTTPError as e:
            raise FragaError(f"login falhou (HTTP {e.code}): {e.read()[:150]!r}")
        self._token = d["access_token"]
        self._token_exp = time.time() + int(d.get("expires_in", 300))

    def _auth_headers(self):
        if time.time() > self._token_exp - 60:  # renova antes de expirar
            self._login()
        return {"content-type": "application/json", "User-Agent": _UA,
                "authorization": "Bearer " + self._token,
                "origin": self._origin, "referer": self.catalog_url}

    # -- descobre campos liberados pela conta ------------------------------
    def _gql(self, query, variables):
        body = json.dumps({"query": query, "variables": variables}).encode()
        req = U.Request(ENDPOINT, data=body, headers=self._auth_headers())
        return json.load(self._http(req))

    def _probe_fields(self):
        allowed = ["brand", "name"]
        for f in _VEHICLE_FIELDS:
            q = ('query{ catalogSearch(query:"", market:BRA, take:5, skip:0, '
                 'onlyWithCodeDistributor:false){ nodes{ product{ vehicles{ ' + f + ' } } } } }')
            # 429 (rate-limit) NÃO é "campo negado": faz backoff e re-tenta o mesmo campo.
            wait = 30
            while True:
                try:
                    d = self._gql(q, {})
                except FragaError as e:
                    if "429" in str(e) and wait <= 240:
                        time.sleep(wait); wait *= 2; continue
                    d = {"errors": [{"extensions": {"code": "PROBE_ERROR"}}]}
                break
            errs = d.get("errors") or []
            code = " ".join((e.get("extensions") or {}).get("code", "") for e in errs)
            if "AUTH_NOT_AUTHORIZED" in code or "PROBE_ERROR" in code:
                continue
            allowed.append(f)
        self._vehicle_sel = " ".join(allowed)

    def _build_query(self):
        self._query = (
            "query($q:String!,$take:Int,$skip:Int){ "
            "catalogSearch(query:$q, market:BRA, take:$take, skip:$skip, onlyWithCodeDistributor:false){ "
            "pageInfo{ total } "
            "nodes{ product{ id partNumber brand{ name } productGroup{ name } status "
            "summaryApplication containsUniversalApplication oldCodes "
            "crossReferences{ brand{ name } partNumber } "
            "specifications{ category important description value } "
            "vehicles{ " + self._vehicle_sel + " } } } } }")

    # -- consulta (mesma interface das outras sessões) ---------------------
    def _fetch(self, variables):
        d = self._gql(self._query, variables)
        if d.get("errors"):
            raise FragaError(f"GraphQL: {str(d['errors'])[:200]}")
        return (d.get("data") or {}).get("catalogSearch") or {}

    def search_page(self, term, take=50, skip=0):
        cs = self._fetch({"q": term, "take": min(take, 50), "skip": skip})
        nodes = cs.get("nodes") or []
        total = (cs.get("pageInfo") or {}).get("total") or 0
        return [n["product"] for n in nodes if n.get("product")], total

    def search_all(self, term="", page_size=50, max_items=None):
        skip = 0
        yielded = 0
        while True:
            products, total = self.search_page(term, take=page_size, skip=skip)
            if not products:
                break
            for p in products:
                yield p
                yielded += 1
                if max_items and yielded >= max_items:
                    return
            skip += len(products)
            if skip >= total:
                break
            time.sleep(self.delay)
