"""API do buscador de peças (FastAPI) + serve o front (SPA/PWA).

Rotas /api/* devolvem JSON; o resto serve os estáticos do SPA (com fallback
para index.html, para funcionar como app de página única).
"""

import re
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import db
from . import affiliate
from . import leads

app = FastAPI(title="acha_peça API", version="1.0")

STATIC = Path(__file__).resolve().parent / "static"

leads.init()


@app.get("/api/health")
def health():
    return {"ok": True}


@app.get("/api/stats")
def api_stats():
    return db.stats()


@app.get("/api/search")
def api_search(q: str = Query(..., min_length=1), limit: int = 40):
    return {"query": q, "results": db.search(q, limit=min(limit, 100))}


@app.get("/api/part/{pid}")
def api_part(pid: str):
    d = db.part_detail(pid)
    if not d:
        raise HTTPException(404, "peça não encontrada")
    d["buy"] = affiliate.buy_section(d)
    return d


@app.get("/api/vehicle/parts")
def api_vehicle_parts(name: str = Query(..., min_length=2), brand: str = None, limit: int = 60):
    return {"vehicle": name, "brand": brand,
            "results": db.parts_for_vehicle(name, brand=brand, limit=min(limit, 120))}


@app.get("/api/vehicle/suggest")
def api_vehicle_suggest(q: str = Query(..., min_length=2)):
    return {"suggestions": db.vehicle_suggest(q)}


# ---- cotação (lead) ----------------------------------------------------
class QuoteIn(BaseModel):
    part_id: str | None = None
    part_number: str | None = None
    brand: str | None = None
    product_group: str | None = None
    name: str | None = None
    whatsapp: str
    city: str | None = None
    quantity: int | None = None
    note: str | None = None


def _clean(s, n=200):
    return (s or "").strip()[:n] or None


@app.post("/api/quote")
def api_quote(q: QuoteIn, request: Request):
    digits = re.sub(r"\D", "", q.whatsapp or "")
    if not (10 <= len(digits) <= 13):
        raise HTTPException(400, "Informe um WhatsApp válido com DDD.")
    qid = leads.add_quote({
        "part_id": _clean(q.part_id, 80),
        "part_number": _clean(q.part_number, 80),
        "brand": _clean(q.brand, 80),
        "product_group": _clean(q.product_group, 120),
        "name": _clean(q.name, 120),
        "whatsapp": digits,
        "city": _clean(q.city, 80),
        "quantity": q.quantity if (q.quantity and 0 < q.quantity < 100000) else None,
        "note": _clean(q.note, 500),
        "user_agent": _clean(request.headers.get("user-agent"), 300),
    })
    return {"ok": True, "id": qid}


# ---- estáticos / SPA ---------------------------------------------------
if STATIC.exists():
    app.mount("/assets", StaticFiles(directory=STATIC), name="assets")


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


@app.get("/sw.js")
def sw():
    return FileResponse(STATIC / "sw.js", media_type="application/javascript")


@app.get("/manifest.json")
def manifest():
    return FileResponse(STATIC / "manifest.json", media_type="application/manifest+json")


@app.get("/{path:path}")
def spa_fallback(path: str):
    f = STATIC / path
    if f.is_file():
        return FileResponse(f)
    return FileResponse(STATIC / "index.html")
