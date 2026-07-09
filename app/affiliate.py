"""Links de compra comissionados (afiliado).

Mercado Livre: a atribuição de comissão vai nos parâmetros matt_word (etiqueta/
canal) + matt_tool (ID do afiliado), anexados a QUALQUER URL de busca/produto do
ML. Assim geramos links para as milhares de peças sem depender da API (que hoje
exige OAuth). Config abaixo é do afiliado JAYMAN.
"""

import os
from urllib.parse import quote

from . import ml_api, ml_cache

# Seção "Comprar" (afiliado Mercado Livre) DESLIGADA por padrão: o programa de
# afiliados do ML não atribui comissão para links de busca — a estrutura atual não
# monetiza, e mandar tráfego de graça pro ML trabalha contra o produto (o caminho é
# reter o usuário para cotação/lead-gen e B2B). O código fica intacto para religar
# em uma linha quando houver monetização real (API oficial de Afiliados, multi-loja
# ou cotação). Religue com a variável de ambiente ACHAPECA_BUY=1.
BUY_ENABLED = os.getenv("ACHAPECA_BUY", "0") == "1"

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
    """Monta a seção de compra: links de busca por código OEM (+ cards com preço
    se houver cache).

    O CTA robusto é o link de busca por CÓDIGO OEM — cai em anúncios ativos reais
    e o comprador vê preço/estoque no navegador dele. Raspar preço do ML por conta
    própria foi abandonado: o anti-bot (DataDome) loga, detecta a automação e
    derruba a sessão. Se um dia um ACESSO PAGO (proxy/anti-bot ou API de dados)
    popular ml_cache por grupo, os cards com preço aparecem aqui automaticamente.

    Desligada por padrão (BUY_ENABLED) — ver comentário no topo do módulo.
    """
    if not BUY_ENABLED:
        return {"products": [], "search_links": []}

    brand = part.get("brand") or ""
    grp = part.get("product_group") or ""

    codes, seen = [], set()
    for code in [part.get("part_number")] + [c.get("part_number")
                                             for c in (part.get("cross_references") or [])]:
        code = (code or "").strip()
        if code and code.lower() not in seen:
            seen.add(code.lower()); codes.append(code)

    # 1) cards com preço SE o cache (por grupo) estiver populado por fonte externa.
    #    Sem cache → lista vazia; a seção fica só com os links de busca.
    products = []
    cached = ml_cache.get_cached(grp) if grp else None
    if cached:
        for it in cached["items"][:6]:
            products.append({
                "id": it.get("item_id") or it.get("url"),
                "name": it.get("title") or "",
                "price": it.get("price"),
                "thumbnail": it.get("thumbnail"),
                "url": ml_item_url(it["url"]),
            })

    # 2) links de busca por código OEM (sempre — precisos, funcionam sem cache).
    links = []
    for code in codes[:3]:
        links.append({"kind": "codigo", "label": f"Código {code}",
                      "url": ml_search(code)})
    if grp:
        links.append({"kind": "descricao", "label": f"{grp} {brand}".strip(),
                      "url": ml_search(f"{grp} {brand}".strip())})

    return {"products": products[:6], "search_links": links}
