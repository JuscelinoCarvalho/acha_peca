"""Ingestão de tabelas de intercâmbio (cross-reference) em planilha.

Alguns fornecedores de reposição (555, HDK, ...) não têm catálogo Fraga aberto,
mas publicam tabelas de equivalência ``código-da-marca ↔ código-OEM``. Este
módulo lê essas planilhas e converte cada peça da marca num dict no MESMO formato
que o ``Store.upsert_product`` espera (o shape do GraphQL da Fraga), de modo que
o intercâmbio entra no banco lado a lado com os dados coletados da API.

Diferente do catálogo em PDF, uma tabela pura de cross NÃO traz aplicação de
veículo (modelo/ano) — traz só o par de códigos. O elo modelo/ano para esses
códigos vem do cruzamento com as peças já existentes (mesmo OEM) e dos catálogos
de fornecedor em PDF (ver ``pdf_catalog.py``).

Uso:  python -m motor cross "catalog_pdf/jdmfsm/.../kross 555-oem.xls" --brand 555
"""

import re

from .store import Store


def _norm(v):
    """Normaliza uma célula de código: tira espaços, o '.0' que o xlrd põe em
    números inteiros, e uniformiza maiúsculas."""
    s = str(v).strip()
    if s.endswith(".0") and s[:-2].isdigit():   # xlrd lê inteiros como float
        s = s[:-2]
    s = re.sub(r"\s+", "", s)
    return s.upper()


def parse_cross_xls(path, brand="555", oem_col=0, part_col=1, oem_brand="ORIGINAL OEM"):
    """Planilha de 2 colunas ``OEM | código-da-marca`` -> dicts de produto.

    Agrupa por código da marca: cada peça vira um produto com todos os seus
    equivalentes OEM em ``crossReferences`` (e também em ``oldCodes``).
    """
    import xlrd  # dependência só deste caminho (planilhas .xls)

    wb = xlrd.open_workbook(path)
    by_part = {}   # código da marca -> lista de OEMs (preserva ordem, sem repetir)
    for sh in wb.sheets():
        for r in range(sh.nrows):
            if r == 0 and not _norm(sh.cell_value(r, part_col)).startswith(
                    tuple("ABCDEFGHIJKLMNOPQRSTUVWXYZ")):
                pass  # linha 0 pode ser cabeçalho; o filtro abaixo já a descarta
            try:
                oem = _norm(sh.cell_value(r, oem_col))
                part = _norm(sh.cell_value(r, part_col))
            except IndexError:
                continue
            # descarta cabeçalho/linhas vazias: peça precisa de código plausível
            if not oem or not part or part in ("555", "OEM", "NONE"):
                continue
            if not re.match(r"^[A-Z]{1,3}-?\d", part):   # ex.: SE-7301, SB5154
                continue
            oems = by_part.setdefault(part, [])
            if oem not in oems:
                oems.append(oem)

    products = []
    for part, oems in by_part.items():
        products.append({
            "partNumber": part,
            "brand": {"name": brand},
            "productGroup": {"name": None},
            "status": "ACTIVE",
            "summaryApplication": None,
            "containsUniversalApplication": False,
            "oldCodes": oems,
            "crossReferences": [{"brand": {"name": oem_brand}, "partNumber": o}
                                for o in oems],
            "specifications": [],
            "vehicles": [],
        })
    return products


def _year4(v):
    """Célula de data no formato YYYYMM(.0) do catálogo HDK -> ano (int) ou None."""
    s = _norm(v)
    return int(s[:4]) if len(s) >= 4 and s[:4].isdigit() else None


def parse_hdk_xls(path, brand="HDK", **_):
    """Catálogo HDK (juntas homocinéticas): abas por montadora com colunas
    ``MODEL | ENGINE | CC | YEAR | YEAR | HDK R | OE R | HDK L | OE L``.

    Ancora cada peça no **código OE** (marca ``<MONTADORA> ORIGINAL``) carregando
    a aplicação (modelo/motor/ano); o código HDK entra como equivalente. Assim a
    busca por OE traz modelo/ano, e a busca por HDK acha o OE via cross_reference.
    """
    import xlrd

    wb = xlrd.open_workbook(path)
    prods = {}   # (make, oe) -> product dict acumulando veículos/cross
    for sh in wb.sheets():
        make = sh.name.strip()
        # aba de dimensões (cabeçalho 'HDK No.' na coluna 0) não tem aplicação
        if _norm(sh.cell_value(0, 0)).startswith("ПРИМ") or "HDK NO" in _norm(sh.cell_value(1, 0)):
            continue
        current_model = None
        for r in range(2, sh.nrows):
            row = [sh.cell_value(r, c) if c < sh.ncols else "" for c in range(9)]
            col0 = str(row[0]).strip()
            rest = [str(row[c]).strip() for c in range(1, 9)]
            if not col0 and not any(rest):
                continue
            if col0 and not any(rest):          # linha-cabeçalho de modelo
                current_model = col0
                continue
            chassis, engine, cc = col0, str(row[1]).strip(), _norm(row[2])
            ys, ye = _year4(row[3]), _year4(row[4])
            ye = ye or ys
            for hdk, oe in ((row[5], row[6]), (row[7], row[8])):   # lado R e L
                oe = _norm(oe)
                if not oe:
                    continue
                key = (make, oe)
                p = prods.get(key)
                if not p:
                    p = prods[key] = {
                        "partNumber": oe,
                        "brand": {"name": f"{make} ORIGINAL"},
                        "productGroup": {"name": "JUNTA HOMOCINÉTICA"},
                        "status": "ACTIVE",
                        "summaryApplication": f"{make} {current_model or ''}".strip(),
                        "containsUniversalApplication": False,
                        "oldCodes": [],
                        "crossReferences": [],
                        "specifications": [],
                        "vehicles": [],
                        "_xkeys": set(), "_vkeys": set(),
                    }
                hdkc = _norm(hdk)
                if hdkc and hdkc not in p["_xkeys"]:
                    p["_xkeys"].add(hdkc)
                    p["crossReferences"].append({"brand": {"name": brand}, "partNumber": hdkc})
                vkey = (current_model, chassis, engine, ys, ye)
                if vkey not in p["_vkeys"]:
                    p["_vkeys"].add(vkey)
                    p["vehicles"].append({
                        "brand": make, "name": current_model, "model": chassis,
                        "engineName": engine or None,
                        "engineConfiguration": (cc + "cc") if cc else None,
                        "fuel": None, "startYear": ys, "endYear": ye})
    for p in prods.values():
        p.pop("_xkeys", None); p.pop("_vkeys", None)
    return list(prods.values())


PARSERS = {"cross-xls": parse_cross_xls, "hdk-xls": parse_hdk_xls}


def ingest_cross(path, catalog_label, brand="555", fmt="cross-xls",
                 db_path=None, on_progress=print):
    """Parseia a planilha de cross e grava as peças no banco. Devolve a quantidade."""
    products = PARSERS[fmt](path, brand=brand)
    n_xref = sum(len(p["crossReferences"]) for p in products)
    on_progress(f"» {len(products)} peça(s) / {n_xref} equivalência(s) de {path}")
    store = Store(db_path) if db_path else Store()
    try:
        for p in products:
            store.upsert_product(p, catalog_label)
        store.log_ingest("(CROSS)", catalog_label, len(products))
        store.commit()
    finally:
        store.close()
    on_progress(f"✓ {len(products)} peça(s) gravada(s) em {catalog_label!r}")
    return len(products)
