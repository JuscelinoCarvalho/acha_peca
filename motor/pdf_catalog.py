"""Ingestão de catálogos em PDF (fallback p/ marcas sem API).

Vários fabricantes grandes (Nakata, ...) não têm catálogo Fraga aberto, mas
publicam tabelas de peças em PDF. Este módulo extrai o texto com `pdftotext
-layout` (poppler) e converte cada linha de produto num dict no MESMO formato
que o `Store.upsert_product` espera (o shape do GraphQL da Fraga), de modo que
os dados de PDF entram no banco lado a lado com os coletados da API.

Formato suportado: "tabela de lançamentos" Nakata —
  DESCRIÇÃO | APLICAÇÃO GENÉRICA | CÓDIGO | OE
onde APLICAÇÃO é "MARCA - Modelo - 01/AAAA - 12/AAAA - detalhes" e OE é
"MARCA : código[/ código2]". As colunas do -layout ficam separadas por 2+
espaços, então o parser fatia por isso e localiza o campo do código Nakata.

Uso:  python -m motor pdf catalog_pdf/lancamentos.pdf --brand NAKATA
"""

import re
import subprocess

from .store import Store

# código do fabricante: 2 letras + 3-6 dígitos (NB19012, DM129, PM121, ...)
_CODE = re.compile(r"^[A-Z]{2}\d{3,6}$")
_YEAR = re.compile(r"\d{2}/(\d{4})")


def _pdftotext(pdf_path):
    """Extrai o texto preservando o layout em colunas (precisa do poppler)."""
    out = subprocess.run(
        ["pdftotext", "-layout", pdf_path, "-"],
        capture_output=True, text=True, check=True,
    )
    return out.stdout


def _years(app):
    yrs = [int(y) for y in _YEAR.findall(app)]
    return (min(yrs), max(yrs)) if yrs else (None, None)


def _vehicles(app):
    """APLICAÇÃO 'MARCA - Modelo - datas - detalhes' -> lista de veículos.

    Uma marca pode vir composta ('HYUNDAI / KIA MOTORS'); geramos um veículo por
    marca, mantendo o segmento de modelo inteiro como `name`.
    """
    parts = [p.strip() for p in app.split(" - ") if p.strip()]
    if not parts:
        return []
    brands = [b.strip() for b in parts[0].split("/") if b.strip()]
    name = parts[1] if len(parts) > 1 else None
    ys, ye = _years(app)
    return [{"brand": b, "name": name, "model": None, "engineName": None,
             "engineConfiguration": None, "fuel": None,
             "startYear": ys, "endYear": ye} for b in (brands or [None])]


def _oe(oe):
    """'MARCA : cód[/ cód2]' -> (crossReferences, oldCodes)."""
    if ":" not in oe:
        return [], []
    brand, codes = oe.split(":", 1)
    brand = brand.strip()
    codes = [c.strip() for c in re.split(r"[/,]", codes) if c.strip()]
    xrefs = [{"brand": {"name": brand}, "partNumber": c} for c in codes]
    return xrefs, codes


def parse_nakata_table(pdf_path, brand="NAKATA"):
    """Devolve dicts de produto (shape Fraga) da tabela de lançamentos Nakata."""
    products, seen = [], set()
    for raw in _pdftotext(pdf_path).splitlines():
        line = raw.strip()
        if not line:
            continue
        fields = re.split(r"\s{2,}", line)
        if len(fields) < 4:
            continue
        ci = next((i for i, f in enumerate(fields) if _CODE.match(f)), None)
        if not ci:  # None ou 0 (código nunca é a 1ª coluna, que é a DESCRIÇÃO)
            continue
        code = fields[ci]
        if code in seen:
            continue
        desc = fields[0]
        app = " ".join(fields[1:ci])
        oe = " ".join(fields[ci + 1:])
        if ":" not in oe:  # linha sem OE não é linha de produto da tabela
            continue
        seen.add(code)
        xrefs, oldcodes = _oe(oe)
        products.append({
            "partNumber": code,
            "brand": {"name": brand},
            "productGroup": {"name": desc},
            "status": "ACTIVE",
            "summaryApplication": app,
            "containsUniversalApplication": False,
            "oldCodes": oldcodes,
            "crossReferences": xrefs,
            "specifications": [],
            "vehicles": _vehicles(app),
        })
    return products


PARSERS = {"nakata-table": parse_nakata_table}


def ingest_pdf(pdf_path, catalog_label, brand="NAKATA",
               fmt="nakata-table", db_path=None, on_progress=print):
    """Parseia o PDF e grava as peças no banco. Devolve a quantidade."""
    products = PARSERS[fmt](pdf_path, brand=brand)
    on_progress(f"» {len(products)} peça(s) extraída(s) de {pdf_path}")
    store = Store(db_path) if db_path else Store()
    try:
        for p in products:
            store.upsert_product(p, catalog_label)
        store.log_ingest("(PDF)", catalog_label, len(products))
        store.commit()
    finally:
        store.close()
    on_progress(f"✓ {len(products)} peça(s) gravada(s) em {catalog_label!r}")
    return len(products)
