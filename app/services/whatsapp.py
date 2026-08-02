"""
Gestisce l'invio dei messaggi WhatsApp.

Tutti i messaggi sono scritti come se li scrivesse "Anna" in prima persona
(una specie di segretaria personale), non un "sistema" impersonale - e
portano tutti la sua firma in fondo (vedi config.FIRMA_MESSAGGIO).

Tre modalità possibili, scelte automaticamente in base a cosa è configurato:
1. NESSUNA credenziale Twilio -> simulazione (stampa nei log), comportamento
   di riserva usato durante tutto lo sviluppo.
2. Credenziali Twilio configurate MA nessun Content SID (caso tipico del
   Sandbox, dove non serve un template approvato) -> invio reale come
   testo libero.
3. Credenziali Twilio + Content SID configurati (numero Business definitivo,
   dove Meta richiede messaggi da un template approvato) -> invio reale
   tramite template.
"""

import json
import random
import string
from app.config import (
    OTP_LUNGHEZZA, OTP_DURATA_VALIDITA_MINUTI, NOME_BRAND, FIRMA_MESSAGGIO,
    TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_WHATSAPP_NUMBER,
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


def _invia_via_twilio(numero_whatsapp: str, testo: str, content_sid: str | None = None) -> bool:
    """
    Funzione centrale di invio reale.
    - Se content_sid è impostato, invia tramite template approvato (con
      il testo intero come unica variabile) - necessario per un numero
      Business reale.
    - Se content_sid è None, invia il testo libero direttamente - funziona
      nel Sandbox (o comunque dentro una finestra di conversazione aperta).
    Restituisce True se l'invio è riuscito, False in caso di errore
    (loggato ma non bloccante).
    """
    try:
        parametri = {"from_": TWILIO_WHATSAPP_NUMBER, "to": f"whatsapp:{numero_whatsapp}"}
        if content_sid:
            parametri["content_sid"] = content_sid
            parametri["content_variables"] = json.dumps({"1": testo})
        else:
            parametri["body"] = testo

        _client.messages.create(**parametri)
        return True
    except Exception as errore:
        print(f"[TWILIO][ERRORE INVIO] a {numero_whatsapp}: {errore}")
        return False


def _invia_generico(numero_whatsapp: str, testo: str, etichetta_simulazione: str = "", content_sid: str | None = None):
    """
    Punto unico usato da tutti i messaggi "informativi". Aggiunge sempre
    la firma di Anna in fondo, così non serve ricordarsene in ogni testo.
    """
    testo_firmato = testo + FIRMA_MESSAGGIO

    if _TWILIO_CONFIGURATO:
        inviato = _invia_via_twilio(numero_whatsapp, testo_firmato, content_sid=content_sid)
        if inviato:
            return

    prefisso = f"[SIMULAZIONE WHATSAPP{etichetta_simulazione}]"
    print(f"{prefisso} Invio a {numero_whatsapp}:\n{testo_firmato}")


def invia_otp_whatsapp(numero_whatsapp: str, codice_otp: str):
    testo = (
        f"Ciao! Sono Anna ߑ Il tuo codice di verifica per {NOME_BRAND} è {codice_otp}, "
        f"valido {OTP_DURATA_VALIDITA_MINUTI} minuti."
    ) + FIRMA_MESSAGGIO

    if _TWILIO_CONFIGURATO:
        inviato = _invia_via_twilio(numero_whatsapp, testo, content_sid=TEMPLATE_OTP)
        if inviato:
            return

    print(f"[SIMULAZIONE WHATSAPP] Invio a {numero_whatsapp}: {testo}")


def invia_riepilogo_richiesta(numero_whatsapp: str, riepilogo: str):
    _invia_generico(numero_whatsapp, riepilogo, content_sid=TEMPLATE_GENERICO)


def invia_proposta_gruppo(numero_whatsapp: str, testo_proposta: str):
    """
    Messaggio con richiesta di conferma. Nel Sandbox, senza template con
    bottoni veri, l'utente risponde scrivendo la parola "CONFERMA" o
    "RIFIUTA" - il webhook la riconosce comunque (vedi gestione_gruppi.py),
    quindi funziona bene anche senza bottoni cliccabili.
    """
    testo_firmato = testo_proposta + FIRMA_MESSAGGIO

    if _TWILIO_CONFIGURATO:
        inviato = _invia_via_twilio(numero_whatsapp, testo_firmato, content_sid=TEMPLATE_PROPOSTA_GRUPPO)
        if inviato:
            return

    print(f"[SIMULAZIONE WHATSAPP - PROPOSTA con bottoni Conferma/Rifiuta] "
          f"Invio a {numero_whatsapp}:\n{testo_firmato}")


def invia_annullamento_gruppo(numero_whatsapp: str, motivo: str):
    _invia_generico(
        numero_whatsapp,
        f"Ops! Ho dovuto annullare questa partita. Motivo: {motivo}\n"
        f"Non preoccuparti, continuo subito a cercarti nuovi compagni! ߎ",
        content_sid=TEMPLATE_GENERICO,
    )


def invia_gruppo_confermato(numero_whatsapp: str, testo: str):
    _invia_generico(numero_whatsapp, testo, content_sid=TEMPLATE_GENERICO)


def invia_sospensione_account(numero_whatsapp: str, giorni: int):
    _invia_generico(
        numero_whatsapp,
        f"Il tuo account è stato sospeso per {giorni} giorni per mancate conferme ripetute.",
        content_sid=TEMPLATE_GENERICO,
    )


def invia_prenotazione_confermata(numero_whatsapp: str, testo: str):
    _invia_generico(numero_whatsapp, testo, content_sid=TEMPLATE_GENERICO)


def invia_prenotazione_fallita(numero_whatsapp: str, testo: str):
    _invia_generico(numero_whatsapp, testo, content_sid=TEMPLATE_GENERICO)


def invia_richiesta_feedback(numero_whatsapp: str, testo: str):
    _invia_generico(numero_whatsapp, testo, etichetta_simulazione=" - RICHIESTA FEEDBACK", content_sid=TEMPLATE_GENERICO)


def invia_promemoria_feedback(numero_whatsapp: str):
    _invia_generico(
        numero_whatsapp,
        "Psst! Non dimenticare di valutare i tuoi compagni dell'ultima partita ߘ",
        content_sid=TEMPLATE_GENERICO,
    )


def invia_promemoria_mancata_partita(numero_whatsapp: str, testo: str):
    _invia_generico(numero_whatsapp, testo, etichetta_simulazione=" - PROMEMORIA", content_sid=TEMPLATE_GENERICO)
