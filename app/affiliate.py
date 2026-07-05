"""Links de compra comissionados (afiliado).

Mercado Livre: a atribuição de comissão vai nos parâmetros matt_word (etiqueta/
canal) + matt_tool (ID do afiliado), anexados a QUALQUER URL de busca/produto do
ML. Assim geramos links para as milhares de peças sem depender da API (que hoje
exige OAuth). Config abaixo é do afiliado JAYMAN.
"""

from urllib.parse import quote

from . import ml_api, ml_cache

# credenciais de afiliado (públicas nos links; não são segredo). Fonte: .env via ml_api.
ML_MATT_TOOL = ml_api.MATT_TOOL or "47871976"
ML_MATT_WORD = ml_api.MATT_WORD or "jayman"

_ML_AFF = f"matt_word={ML_MATT_WORD}&matt_tool={ML_MATT_TOOL}"


def ml_search(query: str) -> str:
    """URL de busca no Mercado Livre com atribuição de afiliado."""
    slug = quote((query or "").strip().replace(" ", "-"))
    return f"https://lista.mercadolivre.com.br/{slug}?{_ML_AFF}"


def ml_item_url(url: str) -> str:
    """Anexa a atribuição de afiliado a uma URL de anúncio raspada."""
    sep = "&" if "?" in url else "?"
    return f"{url}{sep}{_ML_AFF}"


def buy_section(part: dict) -> dict:
    """Monta a seção de compra: anúncios reais (raspados, com preço) + links de busca.

    Produtos: anúncios ativos raspados do ML por CÓDIGO OEM e cacheados em
    ml_cache (o worker enche em background a partir do IP residencial). Se a
    query ainda não tem cache, enfileira p/ o worker e cai no link de busca.
    Não usamos o "catálogo" oficial do ML: medimos que p/ autopeças ele é ~90%
    inativo (link /p/{id} morto) ou irrelevante. O código OEM é o sinal preciso
    (casa a peça equivalente independente da marca — o valor do intercâmbio).
    """
    brand = part.get("brand") or ""
    grp = part.get("product_group") or ""

    codes, seen = [], set()
    for code in [part.get("part_number")] + [c.get("part_number")
                                             for c in (part.get("cross_references") or [])]:
        code = (code or "").strip()
        if code and code.lower() not in seen:
            seen.add(code.lower()); codes.append(code)

    # 1) anúncios reais do cache (com preço). Enfileira as queries sem cache.
    products, seen_id = [], set()
    for code in codes[:3]:
        cached = ml_cache.get_cached(code)
        if cached is None:
            ml_cache.enqueue(code)      # worker raspará depois
            continue
        for it in cached["items"]:
            key = it.get("item_id") or it.get("url")
            if not key or key in seen_id:
                continue
            seen_id.add(key)
            products.append({
                "id": key,
                "name": it.get("title") or "",
                "price": it.get("price"),
                "thumbnail": it.get("thumbnail"),
                "url": ml_item_url(it["url"]),
            })
        if len(products) >= 6:
            break

    # 2) links de busca por código OEM (sempre — funcionam mesmo sem cache).
    links = []
    for code in codes[:3]:
        links.append({"kind": "codigo", "label": f"Código {code}",
                      "url": ml_search(code)})
    if grp:
        links.append({"kind": "descricao", "label": f"{grp} {brand}".strip(),
                      "url": ml_search(f"{grp} {brand}".strip())})

    return {"products": products[:6], "search_links": links}
