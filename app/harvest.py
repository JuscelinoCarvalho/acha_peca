"""Colheita semi-manual de anúncios do ML por GRUPO (categoria).

O anti-bot do ML (DataDome) re-desafia sessões automatizadas: 1 solve manual libera
a sessão viva por ~5 buscas antes de degradar. Este módulo abre um navegador NA SUA
TELA (precisa de display), você resolve o captcha quando ele pedir, e a mesma sessão
colhe um lote de grupos, cacheando por grupo em ml_cache. O app (buy_section) lê esse
cache por grupo → 1 colheita serve todas as peças do grupo.

Uso (na máquina com tela, ou com DISPLAY=:1):
  python -m app.harvest --groups 20            # top-20 grupos sem cache fresco
  python -m app.harvest --groups 30 --min 10 --max 22
"""

import argparse
import asyncio
import os
import random
import sqlite3

from playwright.async_api import async_playwright

from . import ml_cache, ml_scrape
from .db import DB_PATH

ROOT = os.path.dirname(os.path.dirname(__file__))
PROFILE = os.path.join(ROOT, ".ml_profile")
STATE = os.path.join(ROOT, ".ml_state.json")


def top_groups(n: int):
    """Top-N grupos por nº de peças que ainda não têm cache fresco."""
    con = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    rows = con.execute(
        "SELECT product_group FROM product WHERE product_group IS NOT NULL "
        "GROUP BY product_group ORDER BY COUNT(*) DESC").fetchall()
    con.close()
    out = []
    for (g,) in rows:
        if ml_cache.get_cached(g) is None:
            out.append(g)
        if len(out) >= n:
            break
    return out


async def _wait_solved(page, secs: int = 300) -> str:
    """Espera o usuário resolver o captcha; devolve o status quando sair de 'blocked'."""
    for _ in range(secs // 2):
        st = await ml_scrape.classify(page)
        if st != "blocked":
            return st
        try:
            t = await page.title()
        except Exception:
            t = "?"
        print(f"    [solve] resolva o captcha na tela... ({t[:30]!r})", flush=True)
        await asyncio.sleep(2)
    return "blocked"


async def login_flow(timeout_s: int = 600):
    """Abre o navegador e espera (até 10 min) você fazer login COMPLETO (e-mail,
    senha, 2FA). Salva a sessão logada no perfil p/ a colheita reaproveitar."""
    print("Abrindo navegador — faça LOGIN completo na janela (e-mail, senha, código 2FA).\n"
          "Não precisa pressa: aguardo até 10 min os anúncios aparecerem.\n", flush=True)
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        ctx = await browser.new_context(user_agent=ml_scrape._UA, locale="pt-BR",
                                        viewport={"width": 1100, "height": 780})
        page = await ctx.new_page()
        await page.goto(ml_scrape.search_url("amortecedor de suspensão"),
                        wait_until="domcontentloaded", timeout=60000)
        ok = False
        for i in range(timeout_s // 3):
            if await ml_scrape.classify(page) == "ok":
                ok = True
                break
            if i % 4 == 0:
                try:
                    t = await page.title()
                except Exception:
                    t = "?"
                print(f"  [{i*3}s] aguardando login/anúncios... ({t[:42]!r})", flush=True)
            await asyncio.sleep(3)
        if ok:
            try:
                await ctx.storage_state(path=STATE)
            except Exception:
                pass
            print("\n>>> LOGIN OK — sessão logada salva. Agora rode: python -m app.harvest --groups 20 <<<", flush=True)
        else:
            print("\ntimeout — login não concluído a tempo.", flush=True)
        await asyncio.sleep(2)
        await ctx.close()
        await browser.close()


async def harvest(groups, limit, min_d, max_d):
    ok = empty = solves = 0
    for f in ("SingletonLock", "SingletonCookie", "SingletonSocket"):
        try:
            os.remove(os.path.join(PROFILE, f))
        except OSError:
            pass
    print(f"colhendo {len(groups)} grupos (você resolve o captcha quando pedir)\n", flush=True)
    async with async_playwright() as p:
        ctx = await p.chromium.launch_persistent_context(
            PROFILE, headless=False, user_agent=ml_scrape._UA, locale="pt-BR",
            viewport={"width": 1100, "height": 780})
        page = ctx.pages[0] if ctx.pages else await ctx.new_page()
        for i, g in enumerate(groups):
            try:
                await page.goto(ml_scrape.search_url(g), wait_until="domcontentloaded", timeout=60000)
                try:
                    await page.wait_for_selector(ml_scrape._ITEM_SEL, timeout=8000)
                except Exception:
                    pass
                st = await ml_scrape.classify(page)
                if st == "blocked":
                    solves += 1
                    print(f">>> CAPTCHA (#{solves}) em '{g}' — RESOLVA NA TELA <<<", flush=True)
                    st = await _wait_solved(page)
                    if st == "blocked":
                        print("timeout no solve — encerrando lote", flush=True)
                        break
                if st == "ok":
                    items = await ml_scrape.extract_items(page, limit)
                    ml_cache.put_cache(g, items, "ok"); ok += 1
                    ex = f" ex R${items[0]['price']}" if items else ""
                    print(f"  OK  {g[:34]:34s} {len(items)} itens{ex}", flush=True)
                else:  # empty confirmado (tem UI de busca + marca de 'sem resultado')
                    ml_cache.put_cache(g, [], "empty"); empty += 1
                    print(f"  --  {g[:34]:34s} sem anúncio", flush=True)
                ml_cache.dequeue(g)
            except Exception as e:
                print(f"  !!  {g[:34]:34s} erro: {repr(e)[:50]}", flush=True)
            if i < len(groups) - 1:
                await asyncio.sleep(random.uniform(min_d, max_d))
        try:
            await ctx.storage_state(path=STATE)
        except Exception:
            pass
        await ctx.close()
    print(f"\nFIM  ok={ok} empty={empty} solves_manuais={solves}", flush=True)
    print("cache:", ml_cache.stats(), flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--login", action="store_true", help="passo de login (janela de 10 min p/ 2FA)")
    ap.add_argument("--groups", type=int, default=20)
    ap.add_argument("--limit", type=int, default=6)
    ap.add_argument("--min", dest="min_d", type=float, default=9)
    ap.add_argument("--max", dest="max_d", type=float, default=18)
    a = ap.parse_args()
    if a.login:
        asyncio.run(login_flow())
        return
    groups = top_groups(a.groups)
    if not groups:
        print("nada a colher — todos os top grupos já têm cache fresco.")
        return
    asyncio.run(harvest(groups, a.limit, a.min_d, a.max_d))


if __name__ == "__main__":
    main()
