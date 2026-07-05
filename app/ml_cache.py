"""Cache de anúncios raspados do Mercado Livre + fila de raspagem.

Fica num SQLite PRÓPRIO (ml_cache.db, read-write, WAL) — separado do acha_peca.db
(que o app abre read-only e tem 361MB). Assim o app e o worker de raspagem
escrevem aqui sem contenção com o banco grande.

- listing_cache: resultado por query (código OEM). status = ok|empty|blocked.
- scrape_queue: queries que o app pediu (cache-miss) e o worker ainda vai raspar.
"""

import json
import sqlite3
import time
from pathlib import Path

CACHE_DB = Path(__file__).resolve().parent.parent / "ml_cache.db"
TTL = 7 * 24 * 3600          # anúncios válidos por 7 dias
EMPTY_TTL = 2 * 24 * 3600    # "sem resultado" revalida a cada 2 dias

_DDL = """
CREATE TABLE IF NOT EXISTS listing_cache(
  query      TEXT PRIMARY KEY,
  items_json TEXT NOT NULL DEFAULT '[]',
  status     TEXT NOT NULL,          -- ok | empty | blocked
  fetched_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS scrape_queue(
  query        TEXT PRIMARY KEY,
  requested_at REAL NOT NULL,
  tries        INTEGER NOT NULL DEFAULT 0
);
"""

_conn = None


def conn():
    global _conn
    if _conn is None:
        c = sqlite3.connect(CACHE_DB, timeout=15, check_same_thread=False)
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA busy_timeout=8000")
        c.row_factory = sqlite3.Row
        c.executescript(_DDL)
        c.commit()
        _conn = c
    return _conn


def norm_query(q: str) -> str:
    """Chave canônica da query (case/space-insensível)."""
    return " ".join((q or "").strip().lower().split())


def get_cached(query: str):
    """Devolve dict {status, items, age_s} se houver entrada FRESCA; senão None."""
    k = norm_query(query)
    row = conn().execute(
        "SELECT items_json, status, fetched_at FROM listing_cache WHERE query=?", (k,)
    ).fetchone()
    if not row:
        return None
    age = time.time() - row["fetched_at"]
    ttl = TTL if row["status"] == "ok" else EMPTY_TTL
    if age > ttl:
        return None
    return {"status": row["status"], "age_s": age,
            "items": json.loads(row["items_json"]) if row["status"] == "ok" else []}


def put_cache(query: str, items, status: str):
    k = norm_query(query)
    conn().execute(
        "INSERT INTO listing_cache(query, items_json, status, fetched_at) VALUES(?,?,?,?) "
        "ON CONFLICT(query) DO UPDATE SET items_json=excluded.items_json, "
        "status=excluded.status, fetched_at=excluded.fetched_at",
        (k, json.dumps(items or [], ensure_ascii=False), status, time.time()))
    conn().commit()


def enqueue(query: str):
    """App registra um cache-miss para o worker raspar depois (best-effort)."""
    k = norm_query(query)
    if not k:
        return
    try:
        conn().execute(
            "INSERT INTO scrape_queue(query, requested_at) VALUES(?,?) "
            "ON CONFLICT(query) DO NOTHING", (k, time.time()))
        conn().commit()
    except Exception:
        pass


def pop_batch(n: int = 1):
    """Retorna as N queries mais antigas da fila (sem removê-las)."""
    rows = conn().execute(
        "SELECT query, tries FROM scrape_queue ORDER BY requested_at ASC LIMIT ?", (n,)
    ).fetchall()
    return [(r["query"], r["tries"]) for r in rows]


def dequeue(query: str):
    conn().execute("DELETE FROM scrape_queue WHERE query=?", (norm_query(query),))
    conn().commit()


def bump_tries(query: str):
    conn().execute("UPDATE scrape_queue SET tries=tries+1 WHERE query=?", (norm_query(query),))
    conn().commit()


def stats():
    c = conn()
    return {
        "cached_ok": c.execute("SELECT COUNT(*) FROM listing_cache WHERE status='ok'").fetchone()[0],
        "cached_empty": c.execute("SELECT COUNT(*) FROM listing_cache WHERE status='empty'").fetchone()[0],
        "queue": c.execute("SELECT COUNT(*) FROM scrape_queue").fetchone()[0],
    }
