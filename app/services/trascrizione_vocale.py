"""
Trascrive un messaggio vocale WhatsApp e ne interpreta il contenuto,
estraendo giorno e fascia oraria in modo strutturato - usato per
permettere agli utenti già verificati di fare una richiesta parlando,
invece di compilare il form (miglioramento richiesto da un circolo).
"""

import io
import json
from datetime import date, datetime
from zoneinfo import ZoneInfo

import requests

from app import config

_client = None


def _ottieni_client():
    """Crea il client OpenAI solo alla prima chiamata vera (non a ogni avvio dell'app)."""
    global _client
    if _client is None:
        from openai import OpenAI
        _client = OpenAI(api_key=config.OPENAI_API_KEY)
    return _client


def _giorno_settimana_italiano(data: date) -> str:
    giorni = ["lunedì", "martedì", "mercoledì", "giovedì", "venerdì", "sabato", "domenica"]
    return giorni[data.weekday()]


def _scarica_audio(media_url: str) -> io.BytesIO:
    """
    Gli indirizzi media di Twilio richiedono le stesse credenziali usate
    per inviare messaggi (Account SID + Auth Token come autenticazione
    HTTP di base) - senza queste, il download darebbe 401.
    """
    risposta = requests.get(
        media_url,
        auth=(config.TWILIO_ACCOUNT_SID, config.TWILIO_AUTH_TOKEN),
        timeout=30,
    )
    risposta.raise_for_status()
    file_audio = io.BytesIO(risposta.content)
    file_audio.name = "vocale.ogg"  # Whisper si aspetta un nome file con estensione riconoscibile
    return file_audio


def trascrivi_e_interpreta_vocale(media_url: str) -> dict | None:
    """
    Scarica l'audio, lo trascrive con Whisper, poi interpreta il testo per
    estrarne giorno/orario in modo strutturato. Restituisce None se non è
    stato possibile capire nulla di utile (audio non pertinente, giorno
    passato, dati mancanti, ecc.) - il chiamante decide cosa dire
    all'utente in quel caso.
    """
    if not config.OPENAI_API_KEY:
        print("[VOCALE] OPENAI_API_KEY non configurata, impossibile interpretare il vocale.")
        return None

    try:
        file_audio = _scarica_audio(media_url)
    except Exception as errore:
        print(f"[VOCALE] Errore scaricando l'audio da Twilio: {errore}")
        return None

    client = _ottieni_client()

    try:
        trascrizione = client.audio.transcriptions.create(
            model="whisper-1", file=file_audio, language="it",
        )
    except Exception as errore:
        print(f"[VOCALE] Errore nella trascrizione (Whisper): {errore}")
        return None

    testo_trascritto = trascrizione.text
    oggi_italia = datetime.now(ZoneInfo("Europe/Rome")).date()

    prompt_sistema = (
        f"Oggi è {oggi_italia.isoformat()} ({_giorno_settimana_italiano(oggi_italia)}). "
        "L'utente ha registrato un messaggio vocale per prenotare una partita di padel, "
        "indicando un giorno e una fascia oraria in cui è disponibile a giocare. "
        "Estrai queste informazioni e rispondi SOLO con un oggetto JSON con questa forma esatta:\n"
        '{"giorno": "YYYY-MM-DD", "ora_inizio": "HH:MM", "ora_fine": "HH:MM", "capito": true}\n'
        "Se non riesci a capire con sufficiente chiarezza sia il giorno sia la fascia oraria, "
        'rispondi invece con {"capito": false}. '
        "Interpreta espressioni relative (\"sabato prossimo\", \"dopodomani\", \"tra due settimane\") "
        "in base alla data di oggi indicata sopra. "
        "Se l'utente dice un solo orario senza una vera fascia (es. \"verso le 18\"), "
        "usa una finestra di due ore centrata su quell'orario."
    )

    try:
        risposta = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": prompt_sistema},
                {"role": "user", "content": testo_trascritto},
            ],
            response_format={"type": "json_object"},
        )
        dati = json.loads(risposta.choices[0].message.content)
    except Exception as errore:
        print(f"[VOCALE] Errore nell'interpretazione del testo: {errore}")
        return None

    if not dati.get("capito"):
        print(f"[VOCALE] Non interpretato con sufficiente chiarezza. Trascrizione: '{testo_trascritto}'")
        return None

    try:
        giorno_estratto = date.fromisoformat(dati["giorno"])
    except (ValueError, KeyError):
        return None

    # Un giorno nel passato è quasi certamente un errore di interpretazione
    # (o un audio non pertinente) - meglio chiedere di riprovare che creare
    # una richiesta palesemente sbagliata.
    if giorno_estratto < oggi_italia:
        print(f"[VOCALE] Giorno estratto nel passato ({giorno_estratto}), scartato.")
        return None

    return {
        "giorno": dati["giorno"],
        "ora_inizio": dati["ora_inizio"],
        "ora_fine": dati["ora_fine"],
        "testo_trascritto": testo_trascritto,
    }
