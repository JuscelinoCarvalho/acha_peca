"""Captura de leads de cotação.

Banco gravável PRÓPRIO (leads.db) — separado do catálogo `acha_peca.db`, que o app
abre em modo somente-leitura. WAL + conexão por chamada (baixo volume) para ser
seguro entre os workers/threads do uvicorn.
"""

import re
import sqlite3
import time
import unicodedata
from pathlib import Path

LEADS_DB = Path(__file__).resolve().parent.parent / "leads.db"


def _now():
    return time.strftime("%Y-%m-%d %H:%M:%S")


def _ua(s):
    """minúsculas sem acento (para casar grupos: 'Freio' ~ 'freio')."""
    return "".join(c for c in unicodedata.normalize("NFD", str(s or ""))
                   if unicodedata.category(c) != "Mn").lower()

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

CREATE TABLE IF NOT EXISTS partner(
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  created_at TEXT NOT NULL,
  name       TEXT NOT NULL,
  whatsapp   TEXT,
  email      TEXT,
  ufs        TEXT DEFAULT '*',     -- '*' (todas) ou 'SP,RJ,MG'
  groups     TEXT DEFAULT '*',     -- '*' (todas) ou 'freio,filtro,suspensao'
  active     INTEGER DEFAULT 1
);
CREATE TABLE IF NOT EXISTS lead_distribution(
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  lead_id    INTEGER,
  partner_id INTEGER,
  sent_at    TEXT NOT NULL,
  channel    TEXT,
  ok         INTEGER,
  detail     TEXT
);
CREATE INDEX IF NOT EXISTS ix_dist_lead ON lead_distribution(lead_id);
CREATE INDEX IF NOT EXISTS ix_dist_partner ON lead_distribution(partner_id);
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


# ---- parceiros (lojas/distribuidores) ----------------------------------
def add_partner(d: dict) -> int:
    c = _conn()
    try:
        cur = c.execute(
            "INSERT INTO partner(created_at,name,whatsapp,email,ufs,groups,active) "
            "VALUES (?,?,?,?,?,?,?)",
            (_now(), (d.get("name") or "").strip(), (d.get("whatsapp") or "").strip() or None,
             (d.get("email") or "").strip() or None, (d.get("ufs") or "*").strip() or "*",
             (d.get("groups") or "*").strip() or "*", 1 if d.get("active", True) else 0))
        c.commit()
        return cur.lastrowid
    finally:
        c.close()


def update_partner(pid: int, d: dict) -> bool:
    c = _conn()
    try:
        cur = c.execute(
            "UPDATE partner SET name=?,whatsapp=?,email=?,ufs=?,groups=?,active=? WHERE id=?",
            ((d.get("name") or "").strip(), (d.get("whatsapp") or "").strip() or None,
             (d.get("email") or "").strip() or None, (d.get("ufs") or "*").strip() or "*",
             (d.get("groups") or "*").strip() or "*", 1 if d.get("active", True) else 0, pid))
        c.commit()
        return cur.rowcount > 0
    finally:
        c.close()


def set_partner_active(pid: int, active: bool) -> bool:
    c = _conn()
    try:
        cur = c.execute("UPDATE partner SET active=? WHERE id=?", (1 if active else 0, pid))
        c.commit()
        return cur.rowcount > 0
    finally:
        c.close()


def delete_partner(pid: int) -> bool:
    c = _conn()
    try:
        cur = c.execute("DELETE FROM partner WHERE id=?", (pid,))
        c.commit()
        return cur.rowcount > 0
    finally:
        c.close()


def list_partners(active_only: bool = False) -> list:
    c = _conn()
    try:
        sql = "SELECT * FROM partner"
        if active_only:
            sql += " WHERE active=1"
        sql += " ORDER BY name COLLATE NOCASE"
        return [dict(r) for r in c.execute(sql)]
    finally:
        c.close()


def _covers(cover: str, value: str, accent_insensitive: bool = False) -> bool:
    """Cobertura por lista separada por vírgula. '*' = tudo."""
    cover = (cover or "*").strip()
    if cover == "*" or not cover:
        return True
    if not value:
        return False           # restrito e sem info do lead -> não casa
    toks = [t for t in re.split(r"[,\s;/]+", cover) if t]
    if accent_insensitive:
        v = _ua(value)
        return any(_ua(t) in v for t in toks)
    v = value.upper()
    return any(t.upper() == v or t.upper() in v for t in toks)


def match_partners(uf: str, product_group: str) -> list:
    """Parceiros ATIVOS cuja cobertura casa a UF e o grupo do lead."""
    return [p for p in list_partners(active_only=True)
            if _covers(p.get("ufs"), uf) and _covers(p.get("groups"), product_group, True)]


def log_distribution(lead_id, partner_id, channel, ok, detail=None) -> int:
    c = _conn()
    try:
        cur = c.execute(
            "INSERT INTO lead_distribution(lead_id,partner_id,sent_at,channel,ok,detail) "
            "VALUES (?,?,?,?,?,?)",
            (lead_id, partner_id, _now(), channel, 1 if ok else 0, detail))
        c.commit()
        return cur.lastrowid
    finally:
        c.close()


def distributions_for_lead(lead_id) -> list:
    c = _conn()
    try:
        return [dict(r) for r in c.execute(
            "SELECT d.*, p.name AS partner_name FROM lead_distribution d "
            "LEFT JOIN partner p ON p.id=d.partner_id WHERE d.lead_id=? ORDER BY d.id", (lead_id,))]
    finally:
        c.close()


def partner_counts() -> dict:
    c = _conn()
    try:
        return {"total": c.execute("SELECT COUNT(*) FROM partner").fetchone()[0],
                "active": c.execute("SELECT COUNT(*) FROM partner WHERE active=1").fetchone()[0],
                "distributions": c.execute("SELECT COUNT(*) FROM lead_distribution").fetchone()[0]}
    finally:
        c.close()
