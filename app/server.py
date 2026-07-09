"""API do buscador de peças (FastAPI) + serve o front (SPA/PWA).

Rotas /api/* devolvem JSON; o resto serve os estáticos do SPA (com fallback
para index.html, para funcionar como app de página única).
"""

import csv
import hmac
import io
import os
import re
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import db
from . import affiliate
from . import leads

app = FastAPI(title="acha_peça API", version="1.0")

STATIC = Path(__file__).resolve().parent / "static"

leads.init()


def _env_val(key, default=""):
    """Lê uma chave do .env (o app não usa os.environ do systemd) c/ fallback."""
    envf = Path(__file__).resolve().parent.parent / ".env"
    if envf.exists():
        m = re.search(rf'^{key}\s*=\s*"?([^"\n]*)"?', envf.read_text(), re.M)
        if m:
            return m.group(1).strip()
    return os.getenv(key, default)


ADMIN_TOKEN = _env_val("ACHAPECA_ADMIN_TOKEN", "")


def _check_admin(token: str):
    if not ADMIN_TOKEN:
        raise HTTPException(503, "Painel admin desativado (defina ACHAPECA_ADMIN_TOKEN no .env).")
    if not token or not hmac.compare_digest(token, ADMIN_TOKEN):
        raise HTTPException(401, "não autorizado")


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


# ---- painel de leads (admin, protegido por token) ----------------------
class StatusIn(BaseModel):
    status: str


@app.get("/api/admin/leads")
def api_admin_leads(token: str = "", status: str = None):
    _check_admin(token)
    return {"leads": leads.list_leads(status=status), "counts": leads.counts_by_status()}


@app.post("/api/admin/leads/{lead_id}/status")
def api_admin_lead_status(lead_id: int, payload: StatusIn, token: str = ""):
    _check_admin(token)
    if not leads.set_status(lead_id, payload.status):
        raise HTTPException(400, "lead ou status inválido")
    return {"ok": True}


@app.get("/api/admin/leads.csv")
def api_admin_leads_csv(token: str = ""):
    _check_admin(token)
    cols = ["id", "created_at", "status", "part_number", "brand", "product_group",
            "name", "whatsapp", "city", "quantity", "note"]
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(cols)
    for r in leads.list_leads():
        w.writerow([r.get(c, "") for c in cols])
    return PlainTextResponse(buf.getvalue(), media_type="text/csv",
                             headers={"Content-Disposition": "attachment; filename=leads.csv"})


@app.get("/admin")
def admin_page():
    return FileResponse(STATIC / "admin.html")


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
