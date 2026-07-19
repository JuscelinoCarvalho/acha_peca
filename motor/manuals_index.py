"""Índice dos manuais de fábrica espelhados (jdmfsm.info/Auto).

Varre a árvore de manuais (``Japan/<Marca>/<Modelo>/…`` e ``Other/<Marca>/…``)
e grava um SQLite **separado** (`manuals.db`) com uma linha por arquivo de manual
(pdf/rar/zip/djvu). Fica fora do `acha_peca.db` para não se acoplar aos swaps do
banco de peças; o app abre os dois em read-only.

O modelo é o 1º diretório sob a marca (as pastas costumam misturar código de
chassi e nome — ex.: 'B13 B14 B15 B16 Sentra Sunny 200SX' — o que ajuda a casar
por nome do veículo). Pastas utilitárias (--Engines--, --Articles--) viram grupo
'(geral)'.

Uso:  python -m motor manuals            # usa o mirror padrão
      python -m motor manuals --root <dir> --db manuals.db
"""

import os
import sqlite3
import unicodedata
from pathlib import Path

# raiz padrão do espelho (mesma máquina do serviço)
DEFAULT_ROOT = (Path(__file__).resolve().parent.parent /
                "catalog_pdf/jdmfsm/www.jdmfsm.info/Auto")
DEFAULT_DB = Path(__file__).resolve().parent.parent / "manuals.db"

MANUAL_EXT = {".pdf", ".rar", ".zip", ".djvu", ".7z"}
BRAND_SECTIONS = ("Japan", "Other")


def _norm(s):
    if s is None:
        return ""
    s = "".join(c for c in unicodedata.normalize("NFD", str(s))
                if unicodedata.category(c) != "Mn").lower()
    return s


SCHEMA = """
CREATE TABLE IF NOT EXISTS manual (
  id       INTEGER PRIMARY KEY AUTOINCREMENT,
  brand    TEXT, brand_n TEXT,
  model    TEXT, model_n TEXT,
  title    TEXT,
  rel_path TEXT UNIQUE,   -- caminho relativo à raiz do mirror (para servir/estático)
  ext      TEXT,
  size     INTEGER
);
CREATE INDEX IF NOT EXISTS ix_manual_brand ON manual(brand_n);
CREATE INDEX IF NOT EXISTS ix_manual_model ON manual(brand_n, model);
"""


def build_index(root=DEFAULT_ROOT, db_path=DEFAULT_DB, on_progress=print):
    root = Path(root)
    conn = sqlite3.connect(str(db_path))
    conn.executescript(SCHEMA)
    conn.execute("DELETE FROM manual")           # reconstrói do zero (idempotente)
    rows, n = [], 0
    for section in BRAND_SECTIONS:
        sroot = root / section
        if not sroot.is_dir():
            continue
        for brand_dir in sorted(p for p in sroot.iterdir() if p.is_dir()):
            brand = brand_dir.name
            for f in brand_dir.rglob("*"):
                if not f.is_file() or f.suffix.lower() not in MANUAL_EXT:
                    continue
                rel_to_brand = f.relative_to(brand_dir).parts
                # modelo = 1º nível sob a marca; se o arquivo está direto na marca,
                # ou sob pasta utilitária '--x--', cai em '(geral)'.
                top = rel_to_brand[0] if len(rel_to_brand) > 1 else "(geral)"
                model = "(geral)" if top.startswith("--") else top
                try:
                    size = f.stat().st_size
                except OSError:
                    size = None
                rows.append((brand, _norm(brand), model, _norm(model),
                             f.stem, str(f.relative_to(root)), f.suffix.lower().lstrip("."), size))
                n += 1
                if len(rows) >= 2000:
                    conn.executemany(
                        "INSERT OR IGNORE INTO manual (brand,brand_n,model,model_n,title,rel_path,ext,size) "
                        "VALUES (?,?,?,?,?,?,?,?)", rows)
                    conn.commit(); rows = []
                    on_progress(f"  … {n} manuais")
    if rows:
        conn.executemany(
            "INSERT OR IGNORE INTO manual (brand,brand_n,model,model_n,title,rel_path,ext,size) "
            "VALUES (?,?,?,?,?,?,?,?)", rows)
    conn.commit()
    total = conn.execute("SELECT COUNT(*) FROM manual").fetchone()[0]
    brands = conn.execute("SELECT COUNT(DISTINCT brand) FROM manual").fetchone()[0]
    conn.close()
    on_progress(f"✓ {total} manuais indexados ({brands} marcas) em {db_path}")
    return total
