"""Camada de consulta do buscador de peças (SQLite acha_peca.db).

Foco no valor do produto: intercâmbio. As buscas resolvem
  - código próprio da peça,
  - código OEM/concorrente (via cross_reference) -> a peça equivalente,
  - texto (grupo/aplicação),
e os reversos (peças que atendem um veículo; peças que cruzam um código).
"""

import json
import sqlite3
import unicodedata
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "acha_peca.db"


def _unaccent(s):
    """minúsculas + sem acento — para busca acento-insensível (cabeçote≡cabecote)."""
    if s is None:
        return ""
    return "".join(c for c in unicodedata.normalize("NFD", str(s))
                   if unicodedata.category(c) != "Mn").lower()


def _conn():
    c = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True, check_same_thread=False)
    c.row_factory = sqlite3.Row
    c.create_function("norm", 1, _unaccent, deterministic=True)
    return c


# uma conexão read-only compartilhada (SQLite lida bem com leitura concorrente)
_C = _conn()


def _norm(q: str) -> str:
    return (q or "").strip()


def search(q: str, limit: int = 40):
    """Busca unificada. Devolve lista de peças com o tipo de correspondência."""
    q = _norm(q)
    if not q:
        return []
    up = q.upper()
    like = f"%{up}%"
    prefix = f"{up}%"
    found = {}  # id -> registro (preserva o 1º match_type, mais forte)

    def add(rows, match_type, matched=None):
        for r in rows:
            if r["id"] not in found:
                d = dict(r)
                d["match_type"] = match_type
                if matched:
                    d["matched_code"] = matched
                found[r["id"]] = d

    # 1) código próprio da peça (prefixo) — match mais forte
    add(_C.execute(
        "SELECT id, part_number, brand, product_group, application, catalog "
        "FROM product WHERE part_number LIKE ? COLLATE NOCASE ORDER BY part_number LIMIT ?",
        (prefix, limit)), "codigo")

    # 2) código OEM/concorrente -> peça que o cruza (INTERCÂMBIO)
    if len(found) < limit:
        rows = _C.execute(
            "SELECT p.id, p.part_number, p.brand, p.product_group, p.application, p.catalog, "
            "       x.part_number AS xref FROM cross_reference x "
            "JOIN product p ON p.id = x.product_id "
            "WHERE x.part_number LIKE ? COLLATE NOCASE LIMIT ?",
            (prefix, limit)).fetchall()
        for r in rows:
            if r["id"] not in found:
                d = {k: r[k] for k in ("id", "part_number", "brand", "product_group", "application", "catalog")}
                d["match_type"] = "oem"
                d["matched_code"] = r["xref"]
                found[r["id"]] = d

    # 3) texto — acento-insensível, tokenizado, casando grupo/aplicação/MARCA e
    #    também as ESPECIFICAÇÕES (descrição/valor, ex.: Posição=DIANTEIRO).
    #    cada palavra precisa aparecer em algum desses campos (norm = sem acento).
    words = [_unaccent(w) for w in q.split() if w]
    if len(found) < limit and words:
        one = ("(norm(product_group) LIKE ? OR norm(application) LIKE ? OR norm(brand) LIKE ? "
               "OR EXISTS (SELECT 1 FROM specification s WHERE s.product_id = product.id "
               "AND (norm(s.description) LIKE ? OR norm(s.value) LIKE ?)))")
        clause = " AND ".join([one] * len(words))
        params = []
        for w in words:
            params += [f"%{w}%"] * 5
        params.append(limit)
        add(_C.execute(
            "SELECT id, part_number, brand, product_group, application, catalog FROM product "
            f"WHERE {clause} LIMIT ?", params), "descricao")

    return list(found.values())[:limit]


# Marcas "genéricas" de cross-reference: o fornecedor (ex.: catálogo MAHLE) joga
# os códigos de fábrica num balde sem nomear a montadora. Não são marca de verdade.
_GENERIC_XREF_BRANDS = ("ORIGINAL OEM", "REFERÊNCIA")


def _resolve_automakers(codes):
    """Para códigos OE genéricos, descobre a(s) montadora(s) cruzando o MESMO
    part_number em outros catálogos do banco, onde ele vem sob a marca real
    (ex.: '2564093' -> 'SCANIA ORIGINAL'). Devolve {code: [marcas...]}.

    Uma única query para todos os códigos da peça (barato p/ página de detalhe)."""
    codes = [c for c in set(codes) if c]
    if not codes:
        return {}
    ph = ",".join("?" * len(codes))
    gen = ",".join("?" * len(_GENERIC_XREF_BRANDS))
    rows = _C.execute(
        f"SELECT DISTINCT part_number, brand FROM cross_reference "
        f"WHERE part_number IN ({ph}) AND brand NOT IN ({gen})",
        (*codes, *_GENERIC_XREF_BRANDS)).fetchall()
    out = {}
    for r in rows:
        out.setdefault(r["part_number"], []).append(r["brand"])
    for v in out.values():
        v.sort()
    return out


def part_detail(pid: str):
    """Peça completa por id: dados + cross-refs + especificações + veículos."""
    p = _C.execute("SELECT * FROM product WHERE id = ?", (pid,)).fetchone()
    if not p:
        return None
    d = dict(p)
    d["old_codes"] = json.loads(d.get("old_codes") or "[]")
    d["vehicles"] = [dict(r) for r in _C.execute(
        "SELECT brand, name, model, engine_name, engine_config FROM vehicle "
        "WHERE product_id = ? ORDER BY brand, name", (pid,))]
    # inferência por aplicação: peça NÃO-universal que atende UMA só montadora ->
    # os códigos OE genéricos são (com alta probabilidade) dessa montadora.
    veh_brands = {(v.get("brand") or "").strip() for v in d["vehicles"] if (v.get("brand") or "").strip()}
    single_veh_brand = next(iter(veh_brands)) if (len(veh_brands) == 1 and not d.get("universal")) else None

    xr = [dict(r) for r in _C.execute(
        "SELECT brand, part_number FROM cross_reference WHERE product_id = ? ORDER BY brand", (pid,))]
    # enriquecimento: para os OE genéricos, nomeia a montadora. Duas fontes, por confiança:
    #   1) 'xref' (autoritativo): o mesmo código aparece sob a marca real em outro catálogo;
    #   2) 'veiculo' (inferido): a peça só serve uma montadora.
    generic_codes = [c["part_number"] for c in xr if (c["brand"] or "").upper() in _GENERIC_XREF_BRANDS]
    resolved = _resolve_automakers(generic_codes) if generic_codes else {}
    for c in xr:
        is_generic = (c["brand"] or "").upper() in _GENERIC_XREF_BRANDS
        c["oem_generic"] = is_generic
        c["automakers"], c["automaker_source"] = [], None
        if is_generic:
            ams = resolved.get(c["part_number"], [])
            if ams:
                c["automakers"], c["automaker_source"] = ams, "xref"
            elif single_veh_brand:
                c["automakers"], c["automaker_source"] = [single_veh_brand], "veiculo"
    d["cross_references"] = xr
    d["specifications"] = [dict(r) for r in _C.execute(
        "SELECT category, description, value, important FROM specification "
        "WHERE product_id = ? AND value IS NOT NULL AND value <> '' ORDER BY important DESC", (pid,))]
    return d


def parts_for_vehicle(name: str, brand: str = None, limit: int = 60):
    """Reverso: peças que atendem um veículo. Casa MARCA + modelo + versão,
    tokenizado e sem acento (ex.: 'subaru', 'outback', 'subaru outback')."""
    words = [_unaccent(w) for w in _norm(name).split() if w]
    if not words:
        return []
    conds, params = [], []
    for w in words:
        conds.append("(v.brand_n LIKE ? OR v.name_n LIKE ? OR v.model_n LIKE ?)")
        params += [f"%{w}%"] * 3
    if brand:
        conds.append("v.brand_n LIKE ?")
        params.append(f"%{_unaccent(brand)}%")
    params.append(limit)
    sql = ("SELECT DISTINCT p.id, p.part_number, p.brand, p.product_group, p.application, p.catalog "
           "FROM vehicle v JOIN product p ON p.id = v.product_id "
           f"WHERE {' AND '.join(conds)} ORDER BY p.brand, p.product_group LIMIT ?")
    return [dict(r) for r in _C.execute(sql, params)]


def vehicle_suggest(q: str, limit: int = 15):
    """Autocomplete de veículos: casa MARCA ou modelo (sem acento)."""
    words = [_unaccent(w) for w in _norm(q).split() if w]
    if not words:
        return []
    conds, params = [], []
    for w in words:
        conds.append("(brand_n LIKE ? OR name_n LIKE ?)")
        params += [f"%{w}%"] * 2
    params.append(limit)
    rows = _C.execute(
        "SELECT brand, name, COUNT(DISTINCT product_id) AS parts FROM vehicle "
        f"WHERE {' AND '.join(conds)} GROUP BY brand, name ORDER BY parts DESC LIMIT ?",
        params).fetchall()
    return [dict(r) for r in rows]


def stats():
    one = lambda sql: _C.execute(sql).fetchone()[0]
    return {
        "products": one("SELECT COUNT(*) FROM product"),
        "cross_refs": one("SELECT COUNT(*) FROM cross_reference"),
        "specs": one("SELECT COUNT(*) FROM specification"),
        "vehicles": one("SELECT COUNT(*) FROM vehicle"),
        "vehicle_brands": one("SELECT COUNT(DISTINCT brand) FROM vehicle"),
        "catalogs": [dict(r) for r in _C.execute(
            "SELECT catalog, COUNT(*) AS parts FROM product GROUP BY catalog ORDER BY parts DESC")],
    }
