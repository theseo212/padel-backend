"""
Gestisce l'invio dei messaggi WhatsApp.

Se le credenziali Twilio (TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN,
TWILIO_WHATSAPP_NUMBER) e almeno il template generico non sono
configurati, il sistema resta in modalità "simulazione": stampa nei log
cosa invierebbe, senza contattare davvero Twilio. Questo è il
comportamento usato durante tutto lo sviluppo, e resta il comportamento
di riserva finché non si configurano le variabili su Railway - così non
si rischia di rompere nulla del già costruito e testato.
"""

import random
import string
from app.config import (
    OTP_LUNGHEZZA, TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_WHATSAPP_NUMBER,
    TEMPLATE_OTP, TEMPLATE_GENERICO, TEMPLATE_PROPOSTA_GRUPPO,
)

_TWILIO_CONFIGURATO = bool(TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN and TWILIO_WHATSAPP_NUMBER)

_client = None
if _TWILIO_CONFIGURATO:
    from twilio.rest import Client
    _client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)


def genera_otp() -> str:
    """Genera un codice numerico casuale, es. '482913'."""
    return "".join(random.choices(string.digits, k=OTP_LUNGHEZZA))


def _invia_via_twilio(numero_whatsapp: str, content_sid: str, content_variables: dict) -> bool:
    """
    Funzione centrale di invio reale. Restituisce True se l'invio è
    riuscito, False in caso di errore (loggato ma non bloccante: un
    problema di invio non deve far crashare il resto della logica).
    """
    import json
    try:
        _client.messages.create(
            from_=TWILIO_WHATSAPP_NUMBER,
            to=f"whatsapp:{numero_whatsapp}",
            content_sid=content_sid,
            content_variables=json.dumps(content_variables),
        )
        return True
    except Exception as errore:
        print(f"[TWILIO][ERRORE INVIO] a {numero_whatsapp}: {errore}")
        return False


def _invia_generico(numero_whatsapp: str, testo: str, etichetta_simulazione: str = ""):
    """
    Punto unico usato da tutti i messaggi "informativi" (non OTP, non
    proposta con bottoni). In modalità reale usa il template generico
    con il testo intero come unica variabile; in simulazione stampa
    semplicemente il testo, come già facevamo.
    """
    if _TWILIO_CONFIGURATO and TEMPLATE_GENERICO:
        inviato = _invia_via_twilio(numero_whatsapp, TEMPLATE_GENERICO, {"1": testo})
        if inviato:
            return
        # se l'invio reale fallisce, cade comunque nel log qui sotto per non perdere traccia

    prefisso = f"[SIMULAZIONE WHATSAPP{etichetta_simulazione}]"
    print(f"{prefisso} Invio a {numero_whatsapp}:\n{testo}")


def invia_otp_whatsapp(numero_whatsapp: str, codice_otp: str):
    if _TWILIO_CONFIGURATO and TEMPLATE_OTP:
        from app.config import OTP_DURATA_VALIDITA_MINUTI
        inviato = _invia_via_twilio(
            numero_whatsapp, TEMPLATE_OTP,
            {"1": codice_otp, "2": str(OTP_DURATA_VALIDITA_MINUTI)},
        )
        if inviato:
            return

    print(f"[SIMULAZIONE WHATSAPP] Invio a {numero_whatsapp}: "
          f"il tuo codice di verifica è {codice_otp}, valido 10 minuti.")


def invia_riepilogo_richiesta(numero_whatsapp: str, riepilogo: str):
    _invia_generico(numero_whatsapp, riepilogo)


def invia_proposta_gruppo(numero_whatsapp: str, testo_proposta: str):
    """
    Unico messaggio con i bottoni Quick Reply (Conferma/Rifiuta), quindi
    usa il suo template dedicato invece di quello generico.
    """
    if _TWILIO_CONFIGURATO and TEMPLATE_PROPOSTA_GRUPPO:
        inviato = _invia_via_twilio(numero_whatsapp, TEMPLATE_PROPOSTA_GRUPPO, {"1": testo_proposta})
        if inviato:
            return

    print(f"[SIMULAZIONE WHATSAPP - PROPOSTA con bottoni Conferma/Rifiuta] "
          f"Invio a {numero_whatsapp}:\n{testo_proposta}")


def invia_annullamento_gruppo(numero_whatsapp: str, motivo: str):
    _invia_generico(numero_whatsapp, f"Partita annullata. Motivo: {motivo}")


def invia_gruppo_confermato(numero_whatsapp: str, testo: str):
    _invia_generico(numero_whatsapp, testo)


def invia_sospensione_account(numero_whatsapp: str, giorni: int):
    _invia_generico(
        numero_whatsapp,
        f"Il tuo account è stato sospeso per {giorni} giorni per mancate conferme ripetute."
    )


def invia_prenotazione_confermata(numero_whatsapp: str, testo: str):
    _invia_generico(numero_whatsapp, testo)


def invia_prenotazione_fallita(numero_whatsapp: str, testo: str):
    _invia_generico(numero_whatsapp, testo)


def invia_richiesta_feedback(numero_whatsapp: str, testo: str):
    _invia_generico(numero_whatsapp, testo, etichetta_simulazione=" - RICHIESTA FEEDBACK")


def invia_promemoria_feedback(numero_whatsapp: str):
    _invia_generico(
        numero_whatsapp,
        "Promemoria: non hai ancora valutato i tuoi compagni dell'ultima partita."
    )


def invia_promemoria_mancata_partita(numero_whatsapp: str, testo: str):
    _invia_generico(numero_whatsapp, testo, etichetta_simulazione=" - PROMEMORIA")
