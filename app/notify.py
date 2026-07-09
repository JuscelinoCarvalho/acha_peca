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


def _whatsapp_cloud(text, lead):
    tok, phone_id = _env("WHATSAPP_TOKEN"), _env("WHATSAPP_PHONE_ID")
    to = _env("WHATSAPP_NOTIFY_TO")
    if not (tok and phone_id and to):
        return
    url = f"https://graph.facebook.com/v20.0/{phone_id}/messages"
    body = json.dumps({"messaging_product": "whatsapp", "to": to,
                       "type": "text", "text": {"body": text}}).encode()
    req = urllib.request.Request(url, data=body, headers={
        "Authorization": f"Bearer {tok}", "content-type": "application/json"})
    urllib.request.urlopen(req, timeout=_TIMEOUT).read()


def _telegram(text, lead):
    tok, chat = _env("TELEGRAM_BOT_TOKEN"), _env("TELEGRAM_CHAT_ID")
    if not (tok and chat):
        return
    url = f"https://api.telegram.org/bot{tok}/sendMessage"
    data = urllib.parse.urlencode({"chat_id": chat, "text": text,
                                   "disable_web_page_preview": "true"}).encode()
    urllib.request.urlopen(url, data=data, timeout=_TIMEOUT).read()


def _email(text, lead):
    host, user, pw = _env("SMTP_HOST"), _env("SMTP_USER"), _env("SMTP_PASS")
    to = _env("NOTIFY_EMAIL") or user
    if not (host and user and pw and to):
        return
    msg = EmailMessage()
    msg["Subject"] = f"Nova cotação: {lead.get('part_number') or ''} {lead.get('brand') or ''}".strip()
    msg["From"], msg["To"] = user, to
    msg.set_content(text)
    with smtplib.SMTP(host, int(_env("SMTP_PORT", "587")), timeout=15) as s:
        s.starttls(context=ssl.create_default_context())
        s.login(user, pw)
        s.send_message(msg)


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
