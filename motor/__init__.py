"""Motor de dados de peças — coleta sustentável (Fraga) + armazenamento consultável.

Saiu da fase de provas (prova2/) para o coletor real:
  session.py  — sessão de navegador que dispara GraphQL sem WAF (paginado)
  queries.py  — a query da peça completa (cross-ref OEM + dimensões + veículos)
  store.py    — SQLite consultável (produto e os 3 pilares)
  ingest.py   — orquestra termo -> API -> banco
  cli.py      — `python -m motor {ingest,show,stats}`
"""

from .session import FragaSession
from .store import Store
from .ingest import ingest_terms

__all__ = ["FragaSession", "Store", "ingest_terms"]
