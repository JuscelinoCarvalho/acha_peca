"""Armazenamento consultável (SQLite) do motor de dados.

Modelo em torno da peça-âncora e seus 3 pilares:
  product          — a peça (número + marca + grupo + aplicação-resumo)
  cross_reference  — equivalentes OEM/outras marcas (intercâmbio por código)
  specification    — dimensões e características técnicas
  vehicle          — veículos atendidos (intercâmbio por aplicação)
  ingest_log       — trilha de cada ingestão (termo, catálogo, contagem)

Chave estável do produto = id (UUID do Fraga). Re-ingerir uma peça substitui
seus filhos (idempotente): sem duplicatas ao rodar de novo.
"""

import json
import sqlite3
import unicodedata
from datetime import datetime, timezone
from pathlib import Path


def _norm(s):
    """minúsculas + sem acento — usado nas colunas *_n de busca."""
    if s is None:
        return None
    return "".join(c for c in unicodedata.normalize("NFD", str(s))
                   if unicodedata.category(c) != "Mn").lower()

DEFAULT_DB = Path(__file__).resolve().parent.parent / "acha_peca.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS product (
  id            TEXT PRIMARY KEY,
  part_number   TEXT NOT NULL,
  brand         TEXT,
  product_group TEXT,
  status        TEXT,
  application   TEXT,
  universal     INTEGER,
  old_codes     TEXT,          -- JSON array
  catalog       TEXT,          -- realm/host de onde veio
  updated_at    TEXT
);
CREATE INDEX IF NOT EXISTS ix_product_part ON product(part_number);
CREATE INDEX IF NOT EXISTS ix_product_brand ON product(brand);

CREATE TABLE IF NOT EXISTS cross_reference (
  product_id  TEXT NOT NULL REFERENCES product(id) ON DELETE CASCADE,
  brand       TEXT,
  part_number TEXT
);
CREATE INDEX IF NOT EXISTS ix_xref_pid  ON cross_reference(product_id);
CREATE INDEX IF NOT EXISTS ix_xref_part ON cross_reference(part_number);

CREATE TABLE IF NOT EXISTS specification (
  product_id  TEXT NOT NULL REFERENCES product(id) ON DELETE CASCADE,
  category    TEXT,
  description TEXT,
  value       TEXT,
  important   INTEGER
);
CREATE INDEX IF NOT EXISTS ix_spec_pid ON specification(product_id);

CREATE TABLE IF NOT EXISTS vehicle (
  product_id    TEXT NOT NULL REFERENCES product(id) ON DELETE CASCADE,
  brand         TEXT,
  name          TEXT,
  model         TEXT,
  engine_name   TEXT,
  engine_config TEXT,
  brand_n       TEXT,   -- normalizado (sem acento) p/ busca
  name_n        TEXT,
  model_n       TEXT
);
CREATE INDEX IF NOT EXISTS ix_veh_pid   ON vehicle(product_id);
CREATE INDEX IF NOT EXISTS ix_veh_brand ON vehicle(brand);

CREATE TABLE IF NOT EXISTS ingest_log (
  id      INTEGER PRIMARY KEY AUTOINCREMENT,
  term    TEXT,
  catalog TEXT,
  count   INTEGER,
  ts      TEXT
);
"""


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Store:
    def __init__(self, path=DEFAULT_DB):
        self.path = str(path)
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def close(self):
        self.conn.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    # -- escrita -----------------------------------------------------------
    def upsert_product(self, p, catalog):
        """Grava uma peça e SUBSTITUI seus filhos. Devolve o id do produto."""
        pid = p.get("id")
        if not pid:
            # sem id do Fraga: sintetiza chave a partir de marca+número
            pid = f"{(p.get('brand') or {}).get('name')}::{p.get('partNumber')}"
        cur = self.conn.cursor()
        cur.execute(
            """INSERT INTO product
                 (id, part_number, brand, product_group, status, application,
                  universal, old_codes, catalog, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(id) DO UPDATE SET
                 part_number=excluded.part_number, brand=excluded.brand,
                 product_group=excluded.product_group, status=excluded.status,
                 application=excluded.application, universal=excluded.universal,
                 old_codes=excluded.old_codes, catalog=excluded.catalog,
                 updated_at=excluded.updated_at""",
            (
                pid,
                p.get("partNumber"),
                (p.get("brand") or {}).get("name"),
                (p.get("productGroup") or {}).get("name"),
                p.get("status"),
                p.get("summaryApplication"),
                1 if p.get("containsUniversalApplication") else 0,
                json.dumps(p.get("oldCodes") or [], ensure_ascii=False),
                catalog,
                _now(),
            ),
        )
        # filhos: apaga e reinsere (idempotente)
        for tbl in ("cross_reference", "specification", "vehicle"):
            cur.execute(f"DELETE FROM {tbl} WHERE product_id=?", (pid,))

        cur.executemany(
            "INSERT INTO cross_reference (product_id, brand, part_number) VALUES (?,?,?)",
            [(pid, _brand_name(c.get("brand")), c.get("partNumber"))
             for c in (p.get("crossReferences") or [])],
        )
        cur.executemany(
            "INSERT INTO specification (product_id, category, description, value, important) VALUES (?,?,?,?,?)",
            [(pid, s.get("category"), s.get("description"), s.get("value"),
              1 if s.get("important") else 0)
             for s in (p.get("specifications") or [])],
        )
        cur.executemany(
            "INSERT INTO vehicle (product_id, brand, name, model, engine_name, engine_config, brand_n, name_n, model_n) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            [(pid, v.get("brand"), v.get("name"), v.get("model"),
              v.get("engineName"), v.get("engineConfiguration"),
              _norm(v.get("brand")), _norm(v.get("name")), _norm(v.get("model")))
             for v in (p.get("vehicles") or [])],
        )
        return pid

    def log_ingest(self, term, catalog, count):
        self.conn.execute(
            "INSERT INTO ingest_log (term, catalog, count, ts) VALUES (?,?,?,?)",
            (term, catalog, count, _now()),
        )

    def commit(self):
        self.conn.commit()

    # -- leitura -----------------------------------------------------------
    def get_product(self, part_number):
        """Peça(s) por número exato, com filhos agregados."""
        rows = self.conn.execute(
            "SELECT * FROM product WHERE part_number = ? COLLATE NOCASE", (part_number,)
        ).fetchall()
        out = []
        for r in rows:
            pid = r["id"]
            out.append({
                "product": dict(r),
                "cross_references": [dict(x) for x in self.conn.execute(
                    "SELECT brand, part_number FROM cross_reference WHERE product_id=?", (pid,))],
                "specifications": [dict(x) for x in self.conn.execute(
                    "SELECT category, description, value, important FROM specification WHERE product_id=?", (pid,))],
                "vehicles": [dict(x) for x in self.conn.execute(
                    "SELECT brand, name, model, engine_name, engine_config FROM vehicle WHERE product_id=?", (pid,))],
            })
        return out

    def stats(self):
        c = self.conn
        one = lambda q: c.execute(q).fetchone()[0]
        return {
            "products": one("SELECT COUNT(*) FROM product"),
            "cross_refs": one("SELECT COUNT(*) FROM cross_reference"),
            "specs": one("SELECT COUNT(*) FROM specification"),
            "vehicles": one("SELECT COUNT(*) FROM vehicle"),
            "distinct_vehicle_brands": one("SELECT COUNT(DISTINCT brand) FROM vehicle"),
            "top_source_brands": [dict(r) for r in c.execute(
                "SELECT brand, COUNT(*) n FROM product GROUP BY brand ORDER BY n DESC LIMIT 8")],
            "ingests": [dict(r) for r in c.execute(
                "SELECT term, catalog, count, ts FROM ingest_log ORDER BY id DESC LIMIT 10")],
        }


def _brand_name(b):
    if isinstance(b, dict):
        return b.get("name")
    return b
