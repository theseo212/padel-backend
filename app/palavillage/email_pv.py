"""
Invio email con allegato alla segreteria di Palavillage, tramite Resend
(stessa API HTTPS del sistema generico - vedi app/services/email_service.py).
Estende quel pattern con il supporto agli allegati (Resend li accetta in
base64), che il servizio generico non usa ancora perché finora bastava
testo semplice.
"""

import json
import base64
import urllib.request
import urllib.error

from app.config import RESEND_API_KEY, EMAIL_MITTENTE
from app.palavillage.config import EMAIL_SEGRETERIA_PALAVILLAGE, NOME_CIRCOLO

_RESEND_CONFIGURATO = bool(RESEND_API_KEY)


def invia_pdf_torneo_segreteria(pdf_bytes: bytes, nome_file: str, oggetto: str, corpo_testo: str) -> bool:
    """
    Ritorna True se l'invio è riuscito (o siamo in simulazione locale),
    False se l'invio reale è fallito sul serio.
    """
    if not _RESEND_CONFIGURATO:
        print(f"[SIMULAZIONE EMAIL PALAVILLAGE] A: {EMAIL_SEGRETERIA_PALAVILLAGE}\nOggetto: {oggetto}\n{corpo_testo}\n(allegato: {nome_file}, {len(pdf_bytes)} byte)")
        return True

    corpo_richiesta = {
        "from": f"{NOME_CIRCOLO} <{EMAIL_MITTENTE}>",
        "to": [EMAIL_SEGRETERIA_PALAVILLAGE],
        "subject": oggetto,
        "text": corpo_testo,
        "attachments": [{
            "filename": nome_file,
            "content": base64.b64encode(pdf_bytes).decode("ascii"),
        }],
    }

    try:
        richiesta = urllib.request.Request(
            "https://api.resend.com/emails",
            data=json.dumps(corpo_richiesta).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {RESEND_API_KEY}",
                "Content-Type": "application/json",
                "User-Agent": "AnnaPadel-Palavillage/1.0",
            },
            method="POST",
        )
        with urllib.request.urlopen(richiesta, timeout=15) as risposta:
            if risposta.status in (200, 201):
                return True
            print(f"[EMAIL PALAVILLAGE][ERRORE INVIO] status inatteso {risposta.status}")
            return False
    except urllib.error.HTTPError as errore_http:
        corpo_errore = errore_http.read().decode("utf-8", errors="replace")
        print(f"[EMAIL PALAVILLAGE][ERRORE INVIO] {errore_http.code}: {corpo_errore}")
        return False
    except Exception as errore:
        print(f"[EMAIL PALAVILLAGE][ERRORE INVIO] {errore}")
        return False
