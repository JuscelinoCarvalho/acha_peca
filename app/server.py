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

from fastapi import BackgroundTasks, FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import db
from . import affiliate
from . import leads
from . import notify

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

# Cotação (botão "Pedir cotação" no site) DESLIGADA por padrão — fica oculta
# enquanto não há canal de entrega/atendimento funcionando. Ligue com
# ACHAPECA_QUOTE=1 no .env quando o WhatsApp/roteamento estiver ativo.
QUOTE_ENABLED = _env_val("ACHAPECA_QUOTE", "") == "1"

# AdSense (monetização passiva). Preencha no .env quando aprovado no Google:
#   ADS_CLIENT="ca-pub-XXXXXXXXXXXXXXXX"  -> carrega o script (Auto Ads já funciona)
#   ADS_SLOT_RESULTS / ADS_SLOT_DETAIL    -> IDs de blocos manuais (opcional)
ADS_CLIENT = _env_val("ADS_CLIENT", "")
ADS_SLOT_RESULTS = _env_val("ADS_SLOT_RESULTS", "")
ADS_SLOT_DETAIL = _env_val("ADS_SLOT_DETAIL", "")


def _check_admin(token: str):
    if not ADMIN_TOKEN:
        raise HTTPException(503, "Painel admin desativado (defina ACHAPECA_ADMIN_TOKEN no .env).")
    if not token or not hmac.compare_digest(token, ADMIN_TOKEN):
        raise HTTPException(401, "não autorizado")


@app.get("/api/health")
def health():
    return {"ok": True}


@app.get("/api/config")
def api_config():
    """Config pública para o front (ex.: AdSense). Sem segredos."""
    ads = None
    if ADS_CLIENT:
        ads = {"client": ADS_CLIENT,
               "slot_results": ADS_SLOT_RESULTS or None,
               "slot_detail": ADS_SLOT_DETAIL or None}
    return {"ads": ads}


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
    d["quote_enabled"] = QUOTE_ENABLED
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
    website: str | None = None  # honeypot: humano deixa vazio; bot preenche


def _clean(s, n=200):
    return (s or "").strip()[:n] or None


def _client_ip(request: Request) -> str:
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    return request.headers.get("x-real-ip") or (request.client.host if request.client else "?")


# rate-limit por IP, baseado no leads.db (compartilhado entre workers).
# Camadas: rajada (5 em 5 min) e teto (20 em 1 h).
_RL_WINDOW, _RL_MAX = 3600, 20
_RL_BURST_WIN, _RL_BURST_MAX = 300, 5


def _rate_ok(ip: str) -> bool:
    if leads.recent_count_by_ip(ip, _RL_BURST_WIN) >= _RL_BURST_MAX:
        return False
    if leads.recent_count_by_ip(ip, _RL_WINDOW) >= _RL_MAX:
        return False
    return True


@app.post("/api/quote")
def api_quote(q: QuoteIn, request: Request, background: BackgroundTasks):
    if not QUOTE_ENABLED:
        raise HTTPException(404, "cotação indisponível")
    # honeypot: se veio preenchido, é bot — falso sucesso, não grava nem gasta rate.
    if (q.website or "").strip():
        return {"ok": True, "id": 0}
    digits = re.sub(r"\D", "", q.whatsapp or "")
    if not (10 <= len(digits) <= 13):
        raise HTTPException(400, "Informe um WhatsApp válido com DDD.")
    ip = _client_ip(request)
    if not _rate_ok(ip):
        raise HTTPException(429, "Muitos pedidos deste dispositivo. Tente novamente em alguns minutos.")
    lead = {
        "ip": ip,
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
    }
    qid = leads.add_quote(lead)
    # roteamento: avisa o dono + distribui p/ parceiros APÓS responder (não bloqueia).
    background.add_task(notify.on_new_lead, dict(lead, id=qid))
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


# ---- parceiros (admin) ----
class PartnerIn(BaseModel):
    id: int | None = None
    name: str
    whatsapp: str | None = None
    email: str | None = None
    ufs: str | None = "*"
    groups: str | None = "*"
    active: bool = True


@app.get("/api/admin/partners")
def api_admin_partners(token: str = ""):
    _check_admin(token)
    return {"partners": leads.list_partners(), "counts": leads.partner_counts()}


@app.post("/api/admin/partners")
def api_admin_partner_save(p: PartnerIn, token: str = ""):
    _check_admin(token)
    if not (p.name or "").strip():
        raise HTTPException(400, "nome é obrigatório")
    if not (p.email or p.whatsapp):
        raise HTTPException(400, "informe e-mail ou WhatsApp do parceiro")
    d = p.model_dump()
    if p.id:
        if not leads.update_partner(p.id, d):
            raise HTTPException(404, "parceiro não encontrado")
        return {"ok": True, "id": p.id}
    return {"ok": True, "id": leads.add_partner(d)}


@app.post("/api/admin/partners/{pid}/toggle")
def api_admin_partner_toggle(pid: int, token: str = ""):
    _check_admin(token)
    cur = {p["id"]: p for p in leads.list_partners()}.get(pid)
    if not cur:
        raise HTTPException(404, "parceiro não encontrado")
    leads.set_partner_active(pid, not cur["active"])
    return {"ok": True}


@app.delete("/api/admin/partners/{pid}")
def api_admin_partner_delete(pid: int, token: str = ""):
    _check_admin(token)
    if not leads.delete_partner(pid):
        raise HTTPException(404, "parceiro não encontrado")
    return {"ok": True}


@app.get("/api/admin/leads/{lead_id}/distributions")
def api_admin_lead_dists(lead_id: int, token: str = ""):
    _check_admin(token)
    return {"distributions": leads.distributions_for_lead(lead_id)}


@app.get("/api/admin/notify-status")
def api_admin_notify_status(token: str = ""):
    _check_admin(token)
    return {"channels": notify.enabled_channels()}


@app.get("/api/admin/notify-test")
def api_admin_notify_test(token: str = ""):
    """Dispara uma notificação de teste pelos canais ativos."""
    _check_admin(token)
    chans = notify.enabled_channels()
    if not chans:
        raise HTTPException(400, "Nenhum canal configurado no .env.")
    notify.notify_new_lead({
        "part_number": "TESTE-NOTIFY", "brand": "acha peça", "product_group": "teste de roteamento",
        "name": "Teste", "whatsapp": "11999999999", "city": "—", "quantity": 1,
        "note": "Notificação de teste do painel.",
    })
    return {"ok": True, "channels": chans}


@app.get("/admin")
def admin_page():
    return FileResponse(STATIC / "admin.html")


# ---- estáticos / SPA ---------------------------------------------------
if STATIC.exists():
    app.mount("/assets", StaticFiles(directory=STATIC), name="assets")


def _index_html():
    """index.html com o loader do AdSense injetado (quando ADS_CLIENT definido).
    Injetar no HTML servido deixa o script visível ao crawler do Google (validação
    da conta) e habilita Auto Ads sem depender de JS."""
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    if ADS_CLIENT:
        tag = ('<script async src="https://pagead2.googlesyndication.com/pagead/js/'
               f'adsbygoogle.js?client={ADS_CLIENT}" crossorigin="anonymous"></script>\n')
        html = html.replace('<link rel="stylesheet"', tag + '<link rel="stylesheet"', 1)
    return HTMLResponse(html)


@app.get("/")
def index():
    return _index_html()


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
    return _index_html()
