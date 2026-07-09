"""Captura de leads de cotação.

Banco gravável PRÓPRIO (leads.db) — separado do catálogo `acha_peca.db`, que o app
abre em modo somente-leitura. WAL + conexão por chamada (baixo volume) para ser
seguro entre os workers/threads do uvicorn.
"""

import sqlite3
import time
from pathlib import Path

LEADS_DB = Path(__file__).resolve().parent.parent / "leads.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS quote_request(
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  created_at    TEXT NOT NULL,
  part_id       TEXT,
  part_number   TEXT,
  brand         TEXT,
  product_group TEXT,
  name          TEXT,
  whatsapp      TEXT,
  city          TEXT,
  quantity      INTEGER,
  note          TEXT,
  status        TEXT DEFAULT 'novo',
  user_agent    TEXT,
  ip            TEXT
);
CREATE INDEX IF NOT EXISTS ix_quote_created ON quote_request(created_at);
CREATE INDEX IF NOT EXISTS ix_quote_status  ON quote_request(status);
CREATE INDEX IF NOT EXISTS ix_quote_ip      ON quote_request(ip, created_at);
"""


def _conn():
    c = sqlite3.connect(str(LEADS_DB), timeout=15)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA busy_timeout=15000")
    return c


def init():
    c = _conn()
    try:
        c.executescript(_SCHEMA)
        # migração idempotente: adiciona coluna ip em bancos antigos
        cols = [r[1] for r in c.execute("PRAGMA table_info(quote_request)")]
        if "ip" not in cols:
            c.execute("ALTER TABLE quote_request ADD COLUMN ip TEXT")
        c.commit()
    finally:
        c.close()


def add_quote(data: dict) -> int:
    """Grava um pedido de cotação e devolve o id."""
    c = _conn()
    try:
        cur = c.execute(
            "INSERT INTO quote_request "
            "(created_at, part_id, part_number, brand, product_group, "
            " name, whatsapp, city, quantity, note, user_agent, ip) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (time.strftime("%Y-%m-%d %H:%M:%S"),
             data.get("part_id"), data.get("part_number"), data.get("brand"),
             data.get("product_group"), data.get("name"), data.get("whatsapp"),
             data.get("city"), data.get("quantity"), data.get("note"),
             data.get("user_agent"), data.get("ip")),
        )
        c.commit()
        return cur.lastrowid
    finally:
        c.close()


def count() -> int:
    c = _conn()
    try:
        return c.execute("SELECT COUNT(*) FROM quote_request").fetchone()[0]
    finally:
        c.close()


VALID_STATUS = ("novo", "contatado", "cotado", "fechado", "descartado")


def list_leads(status: str = None, limit: int = 2000) -> list:
    c = _conn()
    try:
        if status and status in VALID_STATUS:
            rows = c.execute("SELECT * FROM quote_request WHERE status=? "
                             "ORDER BY id DESC LIMIT ?", (status, limit))
        else:
            rows = c.execute("SELECT * FROM quote_request ORDER BY id DESC LIMIT ?", (limit,))
        return [dict(r) for r in rows]
    finally:
        c.close()


def counts_by_status() -> dict:
    c = _conn()
    try:
        out = {"total": c.execute("SELECT COUNT(*) FROM quote_request").fetchone()[0]}
        for r in c.execute("SELECT status, COUNT(*) FROM quote_request GROUP BY status"):
            out[r[0] or "novo"] = r[1]
        return out
    finally:
        c.close()


def recent_count_by_ip(ip: str, seconds: int) -> int:
    """Quantos leads deste IP nos últimos `seconds` — base do rate-limit (compartilhado
    entre workers, pois lê o mesmo leads.db)."""
    if not ip:
        return 0
    thr = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(time.time() - seconds))
    c = _conn()
    try:
        return c.execute("SELECT COUNT(*) FROM quote_request WHERE ip=? AND created_at>=?",
                         (ip, thr)).fetchone()[0]
    finally:
        c.close()


def set_status(lead_id: int, status: str) -> bool:
    if status not in VALID_STATUS:
        return False
    c = _conn()
    try:
        cur = c.execute("UPDATE quote_request SET status=? WHERE id=?", (status, lead_id))
        c.commit()
        return cur.rowcount > 0
    finally:
        c.close()
