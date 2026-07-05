"""API do buscador de peças (FastAPI) + serve o front (SPA/PWA).

Rotas /api/* devolvem JSON; o resto serve os estáticos do SPA (com fallback
para index.html, para funcionar como app de página única).
"""

from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import db
from . import affiliate

app = FastAPI(title="acha_peça API", version="1.0")

STATIC = Path(__file__).resolve().parent / "static"


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
