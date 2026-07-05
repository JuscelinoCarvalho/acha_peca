"""Raspagem de anúncios ativos do Mercado Livre via navegador (Playwright).

A API oficial não expõe anúncios ativos (/sites/search = 403) nem preço com token
de app. Mas um navegador real fura a parede anti-bot e a página pública de busca
(lista.mercadolivre.com.br/<termo>) devolve anúncios ativos com preço. Este módulo
carrega essa página e extrai os itens.

Uso pesado (por request) é inviável (~3-5s/busca + ToS) → a camada de app deve
CACHEAR o resultado no banco e raspar em background/sob demanda, não ao vivo.
"""

import asyncio
import re
from urllib.parse import quote

from playwright.async_api import async_playwright

_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")

_ITEM_SEL = "li.ui-search-layout__item, .ui-search-result__wrapper"

# JS que roda na página e extrai os campos de cada card de anúncio.
_EXTRACT_JS = r"""() => {
  const clean = u => { try { const x = new URL(u); return x.origin + x.pathname; } catch(e){ return u; } };
  const out = [];
  document.querySelectorAll('li.ui-search-layout__item, .ui-search-result__wrapper').forEach(li => {
    const a = li.querySelector('a.poly-component__title, a.ui-search-link, a[href*="/MLB"], a[href*="mercadolivre"]');
    const t = li.querySelector('.poly-component__title, .ui-search-item__title, h2, h3');
    const frac = li.querySelector('.andes-money-amount__fraction');
    const cents = li.querySelector('.andes-money-amount__cents');
    const img = li.querySelector('img');
    const sponsored = !!li.querySelector('.ui-search-item__ad-label, [class*="ad-label"]');
    if (!a || !frac) return;
    let price = parseFloat(frac.textContent.replace(/\./g, ''));
    if (cents) price += parseFloat('0.' + cents.textContent.replace(/\D/g,''));
    out.push({
      url: clean(a.href),
      title: (t ? t.textContent : a.textContent).trim().slice(0, 120),
      price: price,
      thumbnail: img ? (img.getAttribute('src') || img.getAttribute('data-src')) : null,
      sponsored: sponsored,
    });
  });
  return out;
}"""

_MLB_RE = re.compile(r"/(MLB-?\d+)", re.I)


def _item_id(url: str):
    m = _MLB_RE.search(url or "")
    return m.group(1).replace("-", "") if m else None


def search_url(query: str) -> str:
    slug = quote((query or "").strip().replace(" ", "-"))
    return f"https://lista.mercadolivre.com.br/{slug}"


_WALL_RE = re.compile(r"(seguridad|security|captcha|no eres un rob|não é um rob)", re.I)


_CLASSIFY_JS = r"""() => {
  const q = s => document.querySelector(s);
  const body = document.body ? document.body.innerText.slice(0, 4000) : '';
  return {
    items: document.querySelectorAll('li.ui-search-layout__item, .ui-search-result__wrapper').length,
    hasSearch: !!q('.ui-search-main, .ui-search-results, [class*="ui-search"]'),
    noResults: !!q('.ui-search-rescue, .ui-search-no-results') ||
      /não encontramos|no encontramos|nenhum (anúncio|resultado)|não há (anúncios|publicaç)/i.test(body),
  };
}"""


async def classify(page) -> str:
    """Classifica a página: ok | empty | blocked (robusto contra re-desafio).

    'empty' EXIGE marca explícita de "sem resultado". 0 itens sem essa marca (ou
    sem a UI de busca, ou com título de parede) = blocked — nunca falso-vazio.
    """
    try:
        title = await page.title()
    except Exception:
        title = ""
    if _WALL_RE.search(title or ""):
        return "blocked"
    try:
        info = await page.evaluate(_CLASSIFY_JS)
    except Exception:
        return "blocked"
    if info["items"] > 0:
        return "ok"
    if not info["hasSearch"]:
        return "blocked"
    return "empty" if info["noResults"] else "blocked"


async def _scrape_one(page, query: str, limit: int):
    """Devolve (status, items). status ∈ ok|empty|blocked."""
    await page.goto(search_url(query), wait_until="domcontentloaded", timeout=45000)
    try:
        await page.wait_for_selector(_ITEM_SEL, timeout=12000)
    except Exception:
        pass
    status = await classify(page)
    if status != "ok":
        return status, []
    out = await extract_items(page, limit)
    return ("empty" if not out else "ok"), out


async def extract_items(page, limit: int = 6):
    """Extrai/dedup os anúncios da página de busca já carregada (usado no harvest)."""
    raw = await page.evaluate(_EXTRACT_JS)
    out, seen = [], set()
    for r in raw:
        iid = _item_id(r.get("url"))
        key = iid or r.get("url")
        if not key or key in seen:
            continue
        seen.add(key)
        r["item_id"] = iid
        out.append(r)
        if len(out) >= limit:
            break
    return out


async def search_many(queries, limit: int = 6, headless: bool = True, on_result=None,
                      min_delay: float = 0, max_delay: float = 0, max_blocks: int = 0):
    """Raspa várias queries reusando um só navegador (perfil persistente p/ herdar
    cookies e parecer usuário recorrente). Devolve {query: (status, items)}.

    - on_result(query, status, items): chamado após cada query (persistência).
    - min_delay/max_delay: pausa aleatória ENTRE requisições (ritmo humano).
    - max_blocks>0: para cedo após esse nº de 'blocked' consecutivos (cooldown).
    """
    import os
    import random
    results = {}
    profile = os.path.join(os.path.dirname(__file__), "..", ".ml_profile")
    queries = list(queries)
    consec_block = 0
    p = await async_playwright().start()
    ctx = await p.chromium.launch_persistent_context(
        profile, headless=headless, user_agent=_UA, locale="pt-BR",
        viewport={"width": 1280, "height": 900})
    try:
        page = ctx.pages[0] if ctx.pages else await ctx.new_page()
        await page.route(re.compile(r"\.(png|jpg|jpeg|webp|gif|woff2?|mp4)$"),
                         lambda route: route.abort())
        for i, q in enumerate(queries):
            try:
                status, items = await _scrape_one(page, q, limit)
            except Exception as e:
                status, items = "error", repr(e)[:120]
            results[q] = (status, items)
            if on_result:
                maybe = on_result(q, status, items)
                if asyncio.iscoroutine(maybe):
                    await maybe
            consec_block = consec_block + 1 if status == "blocked" else 0
            if max_blocks and consec_block >= max_blocks:
                results["__stopped__"] = ("blocked", consec_block)
                break
            if (min_delay or max_delay) and i < len(queries) - 1:
                await asyncio.sleep(random.uniform(min_delay, max_delay))
    finally:
        await ctx.close()
        await p.stop()
    return results


async def search(query: str, limit: int = 6):
    return (await search_many([query], limit=limit)).get(query, ("empty", []))
