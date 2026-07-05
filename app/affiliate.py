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
    """Monta a seção de compra: links de busca no ML com atribuição de afiliado.

    Não exibimos cards de "produto de catálogo" do ML: medimos que, para
    autopeças, o catálogo do ML é quase sempre inativo (link /p/{id} morto) ou
    devolve produtos irrelevantes de outras categorias (casamento por palavra
    solta). O sinal confiável é o link de BUSCA por CÓDIGO OEM — que cai em
    anúncios ativos reais casando com aquele código, independente da marca (o
    próprio valor do intercâmbio). O comprador vê preço/estoque no navegador
    dele; a comissão viaja nos parâmetros matt_* da URL.
    """
    brand = part.get("brand") or ""
    grp = part.get("product_group") or ""

    # códigos OEM/cross-ref: o sinal mais preciso para busca no ML.
    codes, seen = [], set()
    for code in [part.get("part_number")] + [c.get("part_number")
                                             for c in (part.get("cross_references") or [])]:
        code = (code or "").strip()
        if code and code.lower() not in seen:
            seen.add(code.lower()); codes.append(code)

    links = []
    for code in codes[:3]:
        links.append({"kind": "codigo", "label": f"Código {code}",
                      "url": ml_search(code)})
    if grp:
        links.append({"kind": "descricao", "label": f"{grp} {brand}".strip(),
                      "url": ml_search(f"{grp} {brand}".strip())})

    return {"products": [], "search_links": links}
