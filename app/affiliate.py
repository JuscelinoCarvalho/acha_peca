"""Links de compra comissionados (afiliado).

Mercado Livre: a atribuição de comissão vai nos parâmetros matt_word (etiqueta/
canal) + matt_tool (ID do afiliado), anexados a QUALQUER URL de busca/produto do
ML. Assim geramos links para as milhares de peças sem depender da API (que hoje
exige OAuth). Config abaixo é do afiliado JAYMAN.
"""

from urllib.parse import quote

from . import ml_api

# credenciais de afiliado (públicas nos links; não são segredo). Fonte: .env via ml_api.
ML_MATT_TOOL = ml_api.MATT_TOOL or "47871976"
ML_MATT_WORD = ml_api.MATT_WORD or "jayman"

_ML_AFF = f"matt_word={ML_MATT_WORD}&matt_tool={ML_MATT_TOOL}"


def ml_search(query: str) -> str:
    """URL de busca no Mercado Livre com atribuição de afiliado."""
    slug = quote((query or "").strip().replace(" ", "-"))
    return f"https://lista.mercadolivre.com.br/{slug}?{_ML_AFF}"


def buy_section(part: dict) -> dict:
    """Monta a seção de compra: produtos reais do catálogo (API) + links de busca.

    Produtos: tenta primeiro os códigos OEM (precisos), depois grupo+marca.
    Links: buscas no ML (rede ampla) sempre presentes como alternativa.
    """
    brand = part.get("brand") or ""
    grp = part.get("product_group") or ""

    # 1) produtos reais do catálogo oficial (com afiliado no /p/{id})
    queries, seen_q = [], set()
    for c in (part.get("cross_references") or [])[:3]:
        code = c.get("part_number")
        if code and code.lower() not in seen_q:
            seen_q.add(code.lower()); queries.append(code)
    if grp:
        queries.append(f"{grp} {brand}".strip())

    products, seen_id = [], set()
    for q in queries:
        for p in ml_api.products_search(q, limit=6):
            if p["id"] not in seen_id:
                seen_id.add(p["id"]); products.append(p)
        if len(products) >= 8:
            break

    # 2) links de busca (fallback / rede ampla)
    links = []
    pn = part.get("part_number")
    if pn:
        links.append({"kind": "codigo", "label": f"Código {pn}",
                      "url": ml_search(f"{pn} {brand}".strip())})
    if grp:
        links.append({"kind": "descricao", "label": grp,
                      "url": ml_search(f"{grp} {brand}".strip())})

    return {"products": products[:8], "search_links": links}
