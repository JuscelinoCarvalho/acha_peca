"""Orquestração: busca (via sessão) -> SQLite.

Dois modos:
  ingest_terms   — por termo(s) de busca (ex.: "retentor")
  sweep_catalogs — CATÁLOGO INTEIRO (query vazia) por N catálogos do motor Fraga

O intercâmbio real do banco vem de somar muitos catálogos ("1 motor, N catálogos"):
cada catálogo é de um fabricante (Sabó ~5k peças), então 100k+ = dezenas deles.
"""

from .session import FragaSession, DEFAULT_CATALOG
from .store import Store

# Catálogos Fraga confirmados (varrem limpo e o total foi medido em 2026-07-04).
# Muitas marcas existem no Fraga mas com domínio próprio (white-label) e precisam
# da URL real do front-end — descobrir mais é o caminho para 100k+ peças.
KNOWN_CATALOGS = [
    "https://catalogo.sabo.com.br/",        # Sabó    ~5.025
    "https://mahle.catalogofraga.com.br/",  # MAHLE   ~11.023
    "https://dana.catalogofraga.com.br/",   # Dana    ~7.400
    "https://delphi.catalogofraga.com.br/", # Delphi  ~6.257
    "https://spicer.catalogofraga.com.br/", # Spicer  ~5.457
    "https://bosch.catalogofraga.com.br/",  # Bosch   ~3.338
    "https://axios.catalogofraga.com.br/",  # Axios   ~2.819
    "https://corteco.catalogofraga.com.br/",# Corteco ~1.684
    "https://monroe.catalogofraga.com.br/", # Monroe  ~1.304
    "https://kyb.catalogofraga.com.br/",    # KYB     ~1.299
]  # ~45,6k peças. Catálogos grandes (cofap/skf/marelli/valeo/tecfil...) exigem login.


def _open_store(db_path):
    return Store(db_path) if db_path else Store()


def _ingest_stream(sess, store, term, catalog_label, max_items, page_size, on_progress):
    """Consome search_all(term) gravando cada peça. Devolve a contagem."""
    n = 0
    for product in sess.search_all(term, page_size=page_size, max_items=max_items):
        store.upsert_product(product, catalog_label)
        n += 1
        if n % 100 == 0:
            store.commit()
            on_progress(f"  ... {n} peças gravadas")
    store.log_ingest(term or "(catálogo completo)", catalog_label, n)
    store.commit()
    return n


def ingest_terms(terms, db_path=None, catalog_url=DEFAULT_CATALOG,
                 max_items=None, page_size=50, headless=True, on_progress=print):
    """Ingere uma lista de termos num único catálogo. Devolve {termo: qtd}."""
    catalog_label = catalog_url.replace("https://", "").strip("/")
    results = {}
    store = _open_store(db_path)
    try:
        with FragaSession(catalog_url=catalog_url, headless=headless) as sess:
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
                   page_size=50, headless=True, on_progress=print):
    """Varre o CATÁLOGO INTEIRO (query vazia) de cada catálogo. Devolve {catálogo: qtd}."""
    catalog_urls = catalog_urls or KNOWN_CATALOGS
    results = {}
    store = _open_store(db_path)
    try:
        for url in catalog_urls:
            label = url.replace("https://", "").strip("/")
            on_progress(f"\n═══ varredura completa: {label} ═══")
            try:
                with FragaSession(catalog_url=url, headless=headless) as sess:
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
