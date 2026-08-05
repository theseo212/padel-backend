"""
Gestisce l'invio delle email del form Contatti, tramite Resend (API
HTTPS) invece che SMTP diretto - Railway blocca le porte SMTP sui piani
Free/Trial/Hobby (policy fissa della piattaforma, non aggirabile), quindi
serve un servizio che invii email tramite una normale richiesta HTTPS
(porta 443, mai bloccata da nessuno).

Se RESEND_API_KEY non è configurata, il sistema stampa nei log invece di
inviare (stessa logica di riserva già usata per WhatsApp) - il messaggio
viene comunque sempre salvato nel database da chi chiama questa funzione,
quindi non si perde mai nulla.
"""

import json
import urllib.request
import urllib.error

from app.config import RESEND_API_KEY, EMAIL_MITTENTE, EMAIL_DESTINATARIO_CONTATTI, NOME_BRAND

_RESEND_CONFIGURATO = bool(RESEND_API_KEY)


def invia_email_contatto(nome: str, email_mittente: str, messaggio: str) -> bool:
    """
    Invia l'email del form Contatti alla casella di destinazione, tramite
    l'API di Resend. Restituisce True se l'invio è riuscito (o siamo in
    modalità simulazione locale), False se l'invio reale è fallito sul serio.
    """
    oggetto = f"Nuovo messaggio da {NOME_BRAND} - {nome}"
    corpo_testo = (
        f"Hai ricevuto un nuovo messaggio dal form Contatti di {NOME_BRAND}.\n\n"
        f"Nome: {nome}\n"
        f"Email: {email_mittente}\n\n"
        f"Messaggio:\n{messaggio}\n\n"
        f"---\nPuoi rispondere direttamente a questa email, arriverà a {email_mittente}."
    )

    if not _RESEND_CONFIGURATO:
        print(f"[SIMULAZIONE EMAIL] Da: {nome} <{email_mittente}>\nOggetto: {oggetto}\n{corpo_testo}")
        return True

    corpo_richiesta = {
        "from": f"{NOME_BRAND} <{EMAIL_MITTENTE}>",
        "to": [EMAIL_DESTINATARIO_CONTATTI],
        "reply_to": email_mittente,  # rispondendo, si scrive direttamente al mittente
        "subject": oggetto,
        "text": corpo_testo,
    }

    try:
        richiesta = urllib.request.Request(
            "https://api.resend.com/emails",
            data=json.dumps(corpo_richiesta).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {RESEND_API_KEY}",
                "Content-Type": "application/json",
                # Senza uno User-Agent chiaro, Cloudflare (che protegge le
                # API di Resend) a volte blocca la richiesta trattandola
                # come un bot sospetto (errore Cloudflare 1010) - questo
                # header risolve il problema, identificandoci chiaramente.
                "User-Agent": "AnnaPadel-ContactForm/1.0",
            },
            method="POST",
        )
        with urllib.request.urlopen(richiesta, timeout=10) as risposta:
            if risposta.status in (200, 201):
                return True
            print(f"[EMAIL][ERRORE INVIO] status inatteso {risposta.status} per {nome} <{email_mittente}>")
            return False
    except urllib.error.HTTPError as errore_http:
        # Leggiamo il corpo della risposta di errore: Resend di solito
        # spiega ESATTAMENTE il motivo (dominio non corrispondente,
        # chiave con permessi limitati, ecc.) - molto più utile del
        # semplice codice "403 Forbidden" da solo.
        corpo_errore = errore_http.read().decode("utf-8", errors="replace")
        print(f"[EMAIL][ERRORE INVIO] {errore_http.code} per {nome} <{email_mittente}>: {corpo_errore}")
        return False
    except Exception as errore:
        print(f"[EMAIL][ERRORE INVIO] messaggio di {nome} <{email_mittente}>: {errore}")
        return False
