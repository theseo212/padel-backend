"""
ATTENZIONE: questo file è un "segnaposto" (stub).
Per ora le funzioni non inviano davvero messaggi WhatsApp: si limitano
a stampare cosa invierebbero, così possiamo testare tutta la logica
del sistema prima di collegare Twilio (lo faremo in un passo dedicato).

Quando integreremo Twilio, cambieremo SOLO il contenuto di queste funzioni:
il resto del codice che le chiama non dovrà cambiare.
"""

import random
import string
from app.config import OTP_LUNGHEZZA


def genera_otp() -> str:
    """Genera un codice numerico casuale, es. '482913'."""
    return "".join(random.choices(string.digits, k=OTP_LUNGHEZZA))


def invia_otp_whatsapp(numero_whatsapp: str, codice_otp: str):
    print(f"[SIMULAZIONE WHATSAPP] Invio a {numero_whatsapp}: "
          f"il tuo codice di verifica è {codice_otp}, valido 10 minuti.")


def invia_riepilogo_richiesta(numero_whatsapp: str, riepilogo: str):
    print(f"[SIMULAZIONE WHATSAPP] Invio a {numero_whatsapp}:\n{riepilogo}")


def invia_proposta_gruppo(numero_whatsapp: str, testo_proposta: str):
    print(f"[SIMULAZIONE WHATSAPP - PROPOSTA con bottoni Conferma/Rifiuto] "
          f"Invio a {numero_whatsapp}:\n{testo_proposta}")


def invia_annullamento_gruppo(numero_whatsapp: str, motivo: str):
    print(f"[SIMULAZIONE WHATSAPP] Invio a {numero_whatsapp}: "
          f"Partita annullata. Motivo: {motivo}")


def invia_gruppo_confermato(numero_whatsapp: str, testo: str):
    print(f"[SIMULAZIONE WHATSAPP] Invio a {numero_whatsapp}:\n{testo}")


def invia_sospensione_account(numero_whatsapp: str, giorni: int):
    print(f"[SIMULAZIONE WHATSAPP] Invio a {numero_whatsapp}: "
          f"Il tuo account è stato sospeso per {giorni} giorni per mancate conferme ripetute.")


def invia_prenotazione_confermata(numero_whatsapp: str, testo: str):
    print(f"[SIMULAZIONE WHATSAPP] Invio a {numero_whatsapp}:\n{testo}")


def invia_prenotazione_fallita(numero_whatsapp: str, testo: str):
    print(f"[SIMULAZIONE WHATSAPP] Invio a {numero_whatsapp}:\n{testo}")


def invia_richiesta_feedback(numero_whatsapp: str, testo: str):
    print(f"[SIMULAZIONE WHATSAPP - RICHIESTA FEEDBACK] Invio a {numero_whatsapp}:\n{testo}")


def invia_promemoria_feedback(numero_whatsapp: str):
    print(f"[SIMULAZIONE WHATSAPP] Invio a {numero_whatsapp}: "
          f"Promemoria: non hai ancora valutato i tuoi compagni dell'ultima partita.")


def invia_promemoria_mancata_partita(numero_whatsapp: str, testo: str):
    print(f"[SIMULAZIONE WHATSAPP - PROMEMORIA] Invio a {numero_whatsapp}:\n{testo}")
