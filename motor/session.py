"""Sessão sustentável com o Fraga (Playwright).

Cliente HTTP cru toma 401 (WAF). A prova 2g mostrou o caminho: carregar a página
do catálogo (estabelece cookies/sessão) e disparar a MESMA query GraphQL de DENTRO
da página (fetch no contexto do site) → herda a sessão → não é bloqueado.

Esta classe encapsula esse padrão como um recurso reutilizável: abre o navegador
uma vez, estabelece a sessão e serve N consultas com delays gentis entre elas.
"""

import time
from playwright.sync_api import sync_playwright

from .queries import PRODUCT_QUERY, OPERATION_NAME

ENDPOINT = "https://bff.catalogofraga.com.br/gateway/graphql"
DEFAULT_CATALOG = "https://catalogo.sabo.com.br/"


class FragaError(RuntimeError):
    """Falha ao consultar a BFF do Fraga (status != 200 ou erros GraphQL)."""


class FragaSession:
    """Sessão de navegador que dispara GraphQL de dentro do catálogo.

    Uso:
        with FragaSession() as s:
            for prod in s.search_all("retentor"):
                ...
    """

    def __init__(self, catalog_url=DEFAULT_CATALOG, headless=True, delay=0.8):
        self.catalog_url = catalog_url
        self.headless = headless
        self.delay = delay  # pausa entre chamadas (gentileza com o servidor)
        self._pw = None
        self._browser = None
        self._page = None

    # -- ciclo de vida -----------------------------------------------------
    def __enter__(self):
        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(headless=self.headless)
        self._page = self._browser.new_page()
        self._page.goto(self.catalog_url, wait_until="networkidle", timeout=60000)
        self._page.wait_for_timeout(2000)  # deixa a sessão assentar
        return self

    def __exit__(self, *exc):
        try:
            if self._browser:
                self._browser.close()
        finally:
            if self._pw:
                self._pw.stop()

    # -- consulta ----------------------------------------------------------
    def _fetch(self, variables):
        """Dispara a query de dentro da página e devolve o bloco catalogSearch."""
        result = self._page.evaluate(
            """async ({endpoint, op, query, variables}) => {
                const r = await fetch(endpoint, {
                  method: 'POST',
                  headers: {'content-type': 'application/json'},
                  body: JSON.stringify({operationName: op, query, variables})
                });
                return { status: r.status, body: await r.json() };
            }""",
            {"endpoint": ENDPOINT, "op": OPERATION_NAME,
             "query": PRODUCT_QUERY, "variables": variables},
        )
        if result["status"] != 200:
            raise FragaError(f"HTTP {result['status']} (WAF/servidor)")
        body = result["body"]
        if body.get("errors"):
            raise FragaError(f"GraphQL: {body['errors']}")
        return ((body.get("data") or {}).get("catalogSearch") or {})

    def search_page(self, term, take=50, skip=0):
        """Uma página de resultados. Devolve (produtos, total)."""
        cs = self._fetch({
            "query": term, "market": "BRA",
            "take": take, "skip": skip, "onlyWithCodeDistributor": False,
        })
        nodes = cs.get("nodes") or []
        total = (cs.get("pageInfo") or {}).get("total") or 0
        return [n["product"] for n in nodes if n.get("product")], total

    def search_all(self, term, page_size=50, max_items=None):
        """Itera TODAS as páginas de um termo (paginação via skip/take).

        Gera produtos um a um. Respeita `max_items` e `pageInfo.total`, com
        pausa entre páginas. `term=""` devolve o CATÁLOGO INTEIRO. O servidor
        limita `take` a 50 (acima disso responde 400).
        """
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
