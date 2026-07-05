"""Worker de raspagem gentil do Mercado Livre.

Roda a partir do IP RESIDENCIAL (esta máquina). Drena a fila de cache-miss
(scrape_queue) que o app foi enchendo, raspa cada query com ritmo humano e grava
em listing_cache. Ao detectar a parede anti-bot ('blocked'), recua e para o lote
para não aprofundar o bloqueio.

Uso:
  python -m app.scrape_worker                 # drena a fila (padrão 15 itens)
  python -m app.scrape_worker --batch 30 --min 25 --max 55
  python -m app.scrape_worker --seed 200      # semeia a fila com códigos OEM do DB
  python -m app.scrape_worker --once "04C103085A"   # raspa 1 query e mostra
"""

import argparse
import asyncio
import sqlite3
import time

from . import ml_cache, ml_scrape
from .db import DB_PATH


def seed_from_db(n: int):
    """Enfileira os N códigos OEM/cross-ref mais comuns ainda sem cache."""
    con = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    rows = con.execute(
        "SELECT part_number FROM cross_reference "
        "WHERE part_number IS NOT NULL AND length(part_number) >= 4 "
        "GROUP BY part_number ORDER BY COUNT(*) DESC LIMIT ?", (n,)).fetchall()
    con.close()
    added = 0
    for (code,) in rows:
        if not ml_cache.get_cached(code):
            ml_cache.enqueue(code)
            added += 1
    print(f"semeados {added} códigos na fila (de {len(rows)} candidatos)")


async def run(batch, min_d, max_d, max_blocks, limit):
    pend = ml_cache.pop_batch(batch)
    if not pend:
        print("fila vazia — nada a raspar. (use --seed N ou deixe o app enfileirar)")
        return
    queries = [q for q, _ in pend]
    print(f"raspando {len(queries)} queries | ritmo {min_d}-{max_d}s | parada após "
          f"{max_blocks} bloqueios consecutivos")

    counts = {"ok": 0, "empty": 0, "blocked": 0, "error": 0}

    def persist(q, status, items):
        counts[status] = counts.get(status, 0) + 1
        if status == "ok":
            ml_cache.put_cache(q, items, "ok")
            ml_cache.dequeue(q)
            print(f"  ✓ {q[:32]:32s} {len(items)} itens  ex: R${items[0]['price']}")
        elif status == "empty":
            ml_cache.put_cache(q, [], "empty")
            ml_cache.dequeue(q)
            print(f"  · {q[:32]:32s} sem anúncio")
        else:  # blocked / error
            ml_cache.bump_tries(q)
            print(f"  ✗ {q[:32]:32s} {status}")

    t0 = time.time()
    res = await ml_scrape.search_many(
        queries, limit=limit, on_result=persist,
        min_delay=min_d, max_delay=max_d, max_blocks=max_blocks)
    dt = time.time() - t0
    stopped = res.get("__stopped__")
    print(f"\nfim em {dt:.0f}s | {counts} | {'PAROU por bloqueio' if stopped else 'lote completo'}")
    print("cache agora:", ml_cache.stats())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--batch", type=int, default=15)
    ap.add_argument("--min", dest="min_d", type=float, default=22)
    ap.add_argument("--max", dest="max_d", type=float, default=48)
    ap.add_argument("--max-blocks", type=int, default=3)
    ap.add_argument("--limit", type=int, default=6)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--once", type=str, default=None)
    a = ap.parse_args()

    if a.seed:
        seed_from_db(a.seed)
    if a.once:
        ml_cache.enqueue(a.once)
        asyncio.run(run(1, 0, 0, 0, a.limit))
        return
    asyncio.run(run(a.batch, a.min_d, a.max_d, a.max_blocks, a.limit))


if __name__ == "__main__":
    main()
