"""Sessão HTTP leve com o Fraga (sem navegador).

Alternativa à FragaSession (Playwright): o probe mostrou que o WAF/BFF libera a
query pública quando (1) faz-se um GET na página do catálogo para assentar cookies
e (2) dispara-se o POST GraphQL com Origin/Referer da marca. Isto replica o que a
sessão do navegador faz, mas com `urllib` (stdlib) — muito mais leve, sem depender
do Chromium (que come memória e trava em ambientes enxutos).

Mesma interface de FragaSession: context manager + search_page/search_all, para
ser plugável no ingest sem mudar o resto.
"""

import http.cookiejar as CJ
import json
import time
import urllib.error
import urllib.request as U
from urllib.parse import urlsplit

from .queries import OPERATION_NAME, PRODUCT_QUERY
from .session import DEFAULT_CATALOG, ENDPOINT, FragaError

_UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")


class HttpFragaSession:
    """Sessão via urllib: GET no catálogo (cookies) + POST GraphQL com Origin."""

    def __init__(self, catalog_url=DEFAULT_CATALOG, headless=True, delay=0.8):
        self.catalog_url = catalog_url.rstrip("/") + "/"
        self.delay = delay  # pausa entre chamadas (gentileza com o servidor)
        # `headless` é aceito só por compatibilidade de interface (não há browser).
        self._opener = None
        self._origin = None

    # -- ciclo de vida -----------------------------------------------------
    def __enter__(self):
        cj = CJ.CookieJar()
        op = U.build_opener(U.HTTPCookieProcessor(cj))
        op.addheaders = [("User-Agent", _UA), ("Accept", "*/*")]
        op.open(self.catalog_url, timeout=30).read()  # assenta sessão/cookies
        self._opener = op
        s = urlsplit(self.catalog_url)
        self._origin = f"{s.scheme}://{s.netloc}"
        return self

    def __exit__(self, *exc):
        self._opener = None

    # -- consulta ----------------------------------------------------------
    def _fetch(self, variables):
        body = json.dumps({"operationName": OPERATION_NAME, "query": PRODUCT_QUERY,
                           "variables": variables}).encode()
        req = U.Request(ENDPOINT, data=body, headers={
            "content-type": "application/json",
            "origin": self._origin, "referer": self.catalog_url,
            "User-Agent": _UA})
        try:
            r = self._opener.open(req, timeout=45)
        except urllib.error.HTTPError as e:
            raise FragaError(f"HTTP {e.code} (WAF/servidor)")
        body = json.load(r)
        if body.get("errors"):
            raise FragaError(f"GraphQL: {body['errors']}")
        return ((body.get("data") or {}).get("catalogSearch") or {})

    # search_page/search_all: mesma lógica de paginação da FragaSession.
    def search_page(self, term, take=50, skip=0):
        cs = self._fetch({
            "query": term, "market": "BRA",
            "take": take, "skip": skip, "onlyWithCodeDistributor": False,
        })
        nodes = cs.get("nodes") or []
        total = (cs.get("pageInfo") or {}).get("total") or 0
        return [n["product"] for n in nodes if n.get("product")], total

    def search_all(self, term, page_size=50, max_items=None):
        page_size = min(page_size, 50)
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
