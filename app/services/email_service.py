"""
Gestisce l'invio delle email del form Contatti, tramite la casella email
reale su Aruba (SMTP). Se le credenziali non sono configurate, il sistema
stampa nei log invece di inviare (stessa logica di "riserva" già usata
per WhatsApp) - il messaggio viene comunque sempre salvato nel database
da chi chiama questa funzione, quindi non si perde mai nulla.
"""

import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from app.config import SMTP_HOST, SMTP_PORT, SMTP_USERNAME, SMTP_PASSWORD, EMAIL_DESTINATARIO_CONTATTI, NOME_BRAND

_SMTP_CONFIGURATO = bool(SMTP_USERNAME and SMTP_PASSWORD)


def invia_email_contatto(nome: str, email_mittente: str, messaggio: str) -> bool:
    """
    Invia l'email del form Contatti alla casella di destinazione.
    Restituisce True se l'invio è riuscito (o siamo in modalità
    simulazione locale), False se l'invio reale è fallito sul serio.
    """
    oggetto = f"Nuovo messaggio da {NOME_BRAND} - {nome}"
    corpo = (
        f"Hai ricevuto un nuovo messaggio dal form Contatti di {NOME_BRAND}.\n\n"
        f"Nome: {nome}\n"
        f"Email: {email_mittente}\n\n"
        f"Messaggio:\n{messaggio}\n\n"
        f"---\nPuoi rispondere direttamente a questa email, arriverà a {email_mittente}."
    )

    if not _SMTP_CONFIGURATO:
        print(f"[SIMULAZIONE EMAIL] Da: {nome} <{email_mittente}>\nOggetto: {oggetto}\n{corpo}")
        return True

    try:
        email = MIMEMultipart()
        email["From"] = SMTP_USERNAME
        email["To"] = EMAIL_DESTINATARIO_CONTATTI
        email["Reply-To"] = email_mittente  # rispondendo, si scrive direttamente al mittente
        email["Subject"] = oggetto
        email.attach(MIMEText(corpo, "plain", "utf-8"))

        with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT) as server:
            server.login(SMTP_USERNAME, SMTP_PASSWORD)
            server.sendmail(SMTP_USERNAME, [EMAIL_DESTINATARIO_CONTATTI], email.as_string())

        return True
    except Exception as errore:
        print(f"[EMAIL][ERRORE INVIO] messaggio di {nome} <{email_mittente}>: {errore}")
        return False
