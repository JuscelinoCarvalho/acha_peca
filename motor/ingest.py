"""Orquestração: busca (via sessão) -> SQLite.

Dois modos:
  ingest_terms   — por termo(s) de busca (ex.: "retentor")
  sweep_catalogs — CATÁLOGO INTEIRO (query vazia) por N catálogos do motor Fraga

O intercâmbio real do banco vem de somar muitos catálogos ("1 motor, N catálogos"):
cada catálogo é de um fabricante (Sabó ~5k peças), então 100k+ = dezenas deles.
"""

import time

from .session import FragaSession, DEFAULT_CATALOG
from .store import Store

# Catálogos Fraga ABERTOS confirmados (sondados em 2026-07-09: GET no front + POST
# GraphQL público retornam a peça completa sem login). Cada marca é um tenant
# white-label em <slug>.catalogofraga.com.br (Sabó usa domínio próprio).
KNOWN_CATALOGS = [
    "https://catalogo.sabo.com.br/",        # Sabó    ~5.025
    "https://mahle.catalogofraga.com.br/",  # MAHLE   ~11.995
    "https://dana.catalogofraga.com.br/",   # Dana    ~7.416
    "https://willtec.catalogofraga.com.br/",# Willtec ~7.582
    "https://delphi.catalogofraga.com.br/", # Delphi  ~6.257
    "https://spicer.catalogofraga.com.br/", # Spicer  ~5.457
    "https://bosch.catalogofraga.com.br/",  # Bosch   ~3.338
    "https://axios.catalogofraga.com.br/",  # Axios   ~2.819
    "https://indisa.catalogofraga.com.br/", # Indisa  ~2.656
    "https://corteco.catalogofraga.com.br/",# Corteco ~1.684
    "https://monroe.catalogofraga.com.br/", # Monroe  ~1.304
    "https://kyb.catalogofraga.com.br/",    # KYB     ~1.299
    "https://victorreinz.catalogofraga.com.br/", # Victor Reinz ~1.564 (juntas 2026-07-10)
    "https://ferodo.catalogofraga.com.br/", # Ferodo    ~346
    "https://albarus.catalogofraga.com.br/",# Albarus    ~379 (2026-07-10)
    "https://champion.catalogofraga.com.br/",# Champion   ~268 (2026-07-10)
]  # Grandes exigem login (cofap/skf/marelli/wega/nakata/taranto/viemar/...) — TODO.
# Sondagem 2026-07-10: além destes, só victorreinz/albarus/champion estavam abertos.
# ATUALIZAÇÃO 2026-07-12: a Fraga FECHOU (401) a maioria — hoje só continuam
# ABERTOS mahle, bosch e champion. Os outros 12 (sabo/willtec/delphi/spicer/axios/
# indisa/corteco/monroe/kyb/victorreinz/ferodo/albarus) pedem login. Os dados que já
# temos deles seguem válidos, mas não dá pra re-coletar/atualizar sem credenciais.
# Ver [[achapeca-oem-enrich]].


def _open_store(db_path):
    return Store(db_path) if db_path else Store()


def _ingest_stream(sess, store, term, catalog_label, max_items, page_size, on_progress):
    """Pagina o catálogo e grava PÁGINA A PÁGINA. Devolve a contagem.

    Crítico p/ não derrubar o site: a rede (buscar página) acontece FORA de qualquer
    transação; cada página é gravada e commitada de imediato, então o lock de escrita
    do SQLite fica preso só por milissegundos (não atravessa o I/O de rede, que antes
    travava os leitores read-only do app → HTTP 500).
    """
    n = 0
    skip = 0
    page_size = min(page_size, 50)
    while True:
        products, total = sess.search_page(term, take=page_size, skip=skip)  # rede, sem txn
        if not products:
            break
        for p in products:
            store.upsert_product(p, catalog_label)
            n += 1
            if max_items and n >= max_items:
                break
        store.commit()  # solta o lock imediatamente (janela de ms)
        on_progress(f"  ... {n} peças gravadas")
        skip += len(products)
        if (max_items and n >= max_items) or skip >= total:
            break
        time.sleep(sess.delay)  # pausa gentil FORA de qualquer transação
    store.log_ingest(term or "(catálogo completo)", catalog_label, n)
    store.commit()
    return n


def ingest_terms(terms, db_path=None, catalog_url=DEFAULT_CATALOG,
                 max_items=None, page_size=50, headless=True, on_progress=print,
                 session_cls=FragaSession):
    """Ingere uma lista de termos num único catálogo. Devolve {termo: qtd}."""
    catalog_label = catalog_url.replace("https://", "").strip("/")
    results = {}
    store = _open_store(db_path)
    try:
        with session_cls(catalog_url=catalog_url, headless=headless) as sess:
            for term in terms:
                on_progress(f"» buscando {term!r} em {catalog_label} ...")
                n = _ingest_stream(sess, store, term, catalog_label,
                                   max_items, page_size, on_progress)
                results[term] = n
                on_progress(f"✓ {term!r}: {n} peças")
    finally:
        store.close()
    return results


def sweep_catalogs(catalog_urls=None, db_path=None, max_items=None,
                   page_size=50, headless=True, on_progress=print,
                   session_cls=FragaSession):
    """Varre o CATÁLOGO INTEIRO (query vazia) de cada catálogo. Devolve {catálogo: qtd}."""
    catalog_urls = catalog_urls or KNOWN_CATALOGS
    results = {}
    store = _open_store(db_path)
    try:
        for url in catalog_urls:
            label = url.replace("https://", "").strip("/")
            on_progress(f"\n═══ varredura completa: {label} ═══")
            try:
                with session_cls(catalog_url=url, headless=headless) as sess:
                    n = _ingest_stream(sess, store, "", label,
                                       max_items, page_size, on_progress)
                results[label] = n
                on_progress(f"✓ {label}: {n} peças")
            except Exception as e:  # um catálogo fora do ar não derruba a varredura
                results[label] = f"ERRO: {e}"
                on_progress(f"✗ {label}: {e}")
    finally:
        store.close()
    return results
