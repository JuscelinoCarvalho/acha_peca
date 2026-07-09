"""Roteamento/notificação de leads — avisa quando chega uma cotação.

Multi-canal e best-effort: cada canal ativa só se suas variáveis existirem no .env,
e qualquer falha é engolida (nunca quebra/atrasa o POST /api/quote). Lê o .env a
cada envio, então basta preencher as credenciais e o próximo lead já dispara (o
restart só é necessário se este módulo mudar).

Canais (defina no .env):
  CallMeBot (WhatsApp, fácil): CALLMEBOT_PHONE, CALLMEBOT_APIKEY
  WhatsApp Cloud API (Meta):   WHATSAPP_TOKEN, WHATSAPP_PHONE_ID, WHATSAPP_NOTIFY_TO
  Telegram:                    TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
  E-mail (SMTP):               SMTP_HOST, SMTP_USER, SMTP_PASS, NOTIFY_EMAIL[, SMTP_PORT]
"""

import json
import os
import re
import smtplib
import ssl
import urllib.parse
import urllib.request
from email.message import EmailMessage
from pathlib import Path

_ENV_FILE = Path(__file__).resolve().parent.parent / ".env"
_TIMEOUT = 12


def _env(key, default=""):
    if _ENV_FILE.exists():
        m = re.search(rf'^{key}\s*=\s*"?([^"\n]*)"?', _ENV_FILE.read_text(), re.M)
        if m:
            return m.group(1).strip()
    return os.getenv(key, default)


def _wa_digits(whatsapp):
    d = re.sub(r"\D", "", whatsapp or "")
    return d if len(d) > 11 else "55" + d  # DDI Brasil


def reply_link(lead):
    """Link wa.me para o dono responder o cliente (um toque)."""
    d = _wa_digits(lead.get("whatsapp"))
    msg = (f"Olá{(' ' + lead['name']) if lead.get('name') else ''}! "
           f"Sobre sua cotação da peça {lead.get('part_number') or ''} "
           f"{lead.get('brand') or ''} no acha peça — temos uma oferta pra você.")
    return f"https://wa.me/{d}?text={urllib.parse.quote(msg)}"


def _format(lead):
    L = [
        "🔧 Nova cotação — acha peça",
        "",
        f"Peça: {lead.get('part_number') or '—'}"
        + (f" · {lead['brand']}" if lead.get("brand") else ""),
    ]
    if lead.get("product_group"):
        L.append(f"Grupo: {lead['product_group']}")
    L.append("")
    if lead.get("name"):
        L.append(f"Cliente: {lead['name']}")
    L.append(f"WhatsApp: {lead.get('whatsapp') or '—'}")
    if lead.get("city"):
        L.append(f"Cidade: {lead['city']}")
    if lead.get("quantity"):
        L.append(f"Qtde: {lead['quantity']}")
    if lead.get("note"):
        L.append(f"Obs: {lead['note']}")
    L += ["", f"Responder: {reply_link(lead)}"]
    return "\n".join(L)


# ---- canais ------------------------------------------------------------
def _callmebot(text, lead):
    phone, key = _env("CALLMEBOT_PHONE"), _env("CALLMEBOT_APIKEY")
    if not (phone and key):
        return
    url = ("https://api.callmebot.com/whatsapp.php?"
           + urllib.parse.urlencode({"phone": phone, "text": text, "apikey": key}))
    urllib.request.urlopen(url, timeout=_TIMEOUT).read()


def _wa_cloud_send(number, text):
    """Envia via Meta Cloud API para um número qualquer (levanta se falhar)."""
    tok, phone_id = _env("WHATSAPP_TOKEN"), _env("WHATSAPP_PHONE_ID")
    if not (tok and phone_id and number):
        raise RuntimeError("WhatsApp Cloud API não configurada")
    num = re.sub(r"\D", "", number)
    if len(num) <= 11:
        num = "55" + num
    url = f"https://graph.facebook.com/v20.0/{phone_id}/messages"
    body = json.dumps({"messaging_product": "whatsapp", "to": num,
                       "type": "text", "text": {"body": text}}).encode()
    req = urllib.request.Request(url, data=body, headers={
        "Authorization": f"Bearer {tok}", "content-type": "application/json"})
    urllib.request.urlopen(req, timeout=_TIMEOUT).read()


def _whatsapp_cloud(text, lead):
    to = _env("WHATSAPP_NOTIFY_TO")
    if not to:
        return
    _wa_cloud_send(to, text)


def _telegram(text, lead):
    tok, chat = _env("TELEGRAM_BOT_TOKEN"), _env("TELEGRAM_CHAT_ID")
    if not (tok and chat):
        return
    url = f"https://api.telegram.org/bot{tok}/sendMessage"
    data = urllib.parse.urlencode({"chat_id": chat, "text": text,
                                   "disable_web_page_preview": "true"}).encode()
    urllib.request.urlopen(url, data=data, timeout=_TIMEOUT).read()


def _smtp_send(to, subject, text):
    """Envia e-mail para um destinatário qualquer (levanta se falhar)."""
    host, user, pw = _env("SMTP_HOST"), _env("SMTP_USER"), _env("SMTP_PASS")
    if not (host and user and pw and to):
        raise RuntimeError("SMTP não configurado")
    msg = EmailMessage()
    msg["Subject"], msg["From"], msg["To"] = subject, user, to
    msg.set_content(text)
    with smtplib.SMTP(host, int(_env("SMTP_PORT", "587")), timeout=15) as s:
        s.starttls(context=ssl.create_default_context())
        s.login(user, pw)
        s.send_message(msg)


def _email(text, lead):
    to = _env("NOTIFY_EMAIL") or _env("SMTP_USER")
    if not to:
        return
    _smtp_send(to, f"Nova cotação: {lead.get('part_number') or ''} {lead.get('brand') or ''}".strip(), text)


_CHANNELS = (_callmebot, _whatsapp_cloud, _telegram, _email)


def notify_new_lead(lead: dict):
    """Dispara todos os canais configurados. Best-effort — nunca levanta exceção."""
    try:
        text = _format(lead)
    except Exception:
        return
    for ch in _CHANNELS:
        try:
            ch(text, lead)
        except Exception:
            pass  # canal fora do ar / mal configurado não afeta os demais nem o lead


# ---- distribuição para lojas parceiras ---------------------------------
def _uf_from_city(city):
    m = re.search(r"[/\-]\s*([A-Za-z]{2})\s*$", city or "")
    return m.group(1).upper() if m else ""


def _partner_text(lead):
    L = ["🔔 Novo pedido de cotação — acha peça", "",
         f"Peça: {lead.get('part_number') or '—'}"
         + (f" · {lead['brand']}" if lead.get("brand") else "")]
    if lead.get("product_group"):
        L.append(f"Grupo: {lead['product_group']}")
    if lead.get("quantity"):
        L.append(f"Qtde: {lead['quantity']}")
    L.append("")
    L.append(f"Cliente: {lead.get('name') or '—'}"
             + (f" — {lead['city']}" if lead.get("city") else ""))
    L.append(f"WhatsApp do cliente: {lead.get('whatsapp') or '—'}")
    if lead.get("note"):
        L.append(f"Obs: {lead['note']}")
    L += ["", f"Responder o cliente: {reply_link(lead)}"]
    return "\n".join(L)


def _send_to_partner(partner, lead):
    """Envia o lead ao parceiro (e-mail e/ou WhatsApp Cloud). (canal, ok, detalhe)."""
    text = _partner_text(lead)
    tried = []
    if partner.get("email"):
        try:
            _smtp_send(partner["email"],
                       f"[acha peça] Pedido de cotação: {lead.get('part_number') or ''}", text)
            return ("email", True, partner["email"])
        except Exception as e:
            tried.append(f"email:{e}")
    if partner.get("whatsapp") and _env("WHATSAPP_TOKEN"):
        try:
            _wa_cloud_send(partner["whatsapp"], text)
            return ("whatsapp_cloud", True, partner["whatsapp"])
        except Exception as e:
            tried.append(f"wa:{e}")
    return ("nenhum", False, "; ".join(tried) or "parceiro sem canal / não configurado")


def distribute_to_partners(lead: dict):
    """Casa o lead com parceiros ativos e envia; registra cada tentativa."""
    from . import leads
    uf = _uf_from_city(lead.get("city"))
    matched = leads.match_partners(uf, lead.get("product_group"))
    for p in matched:
        ch, ok, detail = _send_to_partner(p, lead)
        leads.log_distribution(lead.get("id"), p["id"], ch, ok, str(detail)[:300])
    return len(matched)


def on_new_lead(lead: dict):
    """Chamado no fluxo do /api/quote (em background): avisa o dono e distribui."""
    notify_new_lead(lead)
    try:
        distribute_to_partners(lead)
    except Exception:
        pass


def enabled_channels():
    """Nomes dos canais atualmente configurados (para diagnóstico)."""
    names = []
    if _env("CALLMEBOT_PHONE") and _env("CALLMEBOT_APIKEY"):
        names.append("callmebot")
    if _env("WHATSAPP_TOKEN") and _env("WHATSAPP_PHONE_ID") and _env("WHATSAPP_NOTIFY_TO"):
        names.append("whatsapp_cloud")
    if _env("TELEGRAM_BOT_TOKEN") and _env("TELEGRAM_CHAT_ID"):
        names.append("telegram")
    if _env("SMTP_HOST") and _env("SMTP_USER") and _env("SMTP_PASS"):
        names.append("email")
    return names
