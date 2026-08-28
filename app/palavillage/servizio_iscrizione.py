"""
Logica dell'iscrizione ai tornei del mattino di Palavillage: riconoscimento
utente, fiducia OTP condivisa con il sistema generico, creazione/
aggiornamento, invio conferme.
"""

from datetime import datetime, timedelta
from sqlalchemy.orm import Session

from app import models as models_generico
from app import config as config_generico
from app.services.conversione_livello import ottieni_livello_playtomic

from app.palavillage.models import UtentePV
from app.palavillage.schemas import IscrizionePVCreate
from app.palavillage.whatsapp_pv import genera_otp, invia_otp_whatsapp, invia_riepilogo_iscrizione_pv

_NOMI_GIORNI = {"LUN": 0, "MAR": 1, "MER": 2, "GIO": 3, "VEN": 4}
_NOMI_GIORNI_LEGGIBILI = {"LUN": "lunedì", "MAR": "martedì", "MER": "mercoledì", "GIO": "giovedì", "VEN": "venerdì"}
_LATO_LEGGIBILE = {"DX": "Destra", "SX": "Sinistra", "INDIFFERENTE": "Indifferente"}


def crea_giorni_bitmask(giorni: list[str]) -> int:
    bitmask = 0
    for giorno in giorni:
        bitmask |= 1 << _NOMI_GIORNI[giorno]
    return bitmask


def giorni_bitmask_a_lista(bitmask: int) -> list[str]:
    return [nome for nome, indice in _NOMI_GIORNI.items() if bitmask & (1 << indice)]


def giorni_bitmask_a_leggibile(bitmask: int) -> str:
    nomi = [_NOMI_GIORNI_LEGGIBILI[g] for g in giorni_bitmask_a_lista(bitmask)]
    return ", ".join(nomi) if nomi else "nessuna"


def _numero_gia_verificato_nel_generico(db_generico: Session, whatsapp_numero: str) -> bool:
    """
    True se il numero risulta già validato sul sistema generico AnnaPadel.
    Sola lettura: Palavillage non scrive mai nulla nel database generico.
    """
    utente_generico = db_generico.query(models_generico.Utente).filter(
        models_generico.Utente.whatsapp_numero == whatsapp_numero
    ).first()
    return bool(utente_generico and utente_generico.whatsapp_validato)


def profilo_pv(db_pv: Session, db_generico: Session, whatsapp_numero: str) -> dict:
    """
    Mirror di /utenti/profilo del sistema generico, per il riconoscimento
    nel form. Prima cerca nel database di Palavillage (match completo,
    incluse le preferenze già scelte lì). Se non lo trova, cerca anche
    nel database generico AnnaPadel: se il numero è già conosciuto e
    validato lì, restituisce comunque nome/cognome/livello per
    precompilare il form (stessa Anna, stessa logica di fiducia già
    usata per l'OTP) - ma senza lato/giorni, che sono specifici di
    Palavillage e vanno comunque scelti la prima volta qui.
    """
    utente = db_pv.query(UtentePV).filter(UtentePV.whatsapp_numero == whatsapp_numero).first()
    if utente is not None:
        return {
            "esiste": True,
            "nome": utente.nome,
            "cognome": utente.cognome,
            "livello_playtomic": float(utente.livello_playtomic),
            "livello_dichiarato_scala": utente.livello_dichiarato_scala,
            "livello_dichiarato_originale": utente.livello_dichiarato_originale,
            "lato_preferito": utente.lato_preferito,
            "giorni": giorni_bitmask_a_lista(utente.giorni_bitmask),
        }

    utente_generico = db_generico.query(models_generico.Utente).filter(
        models_generico.Utente.whatsapp_numero == whatsapp_numero
    ).first()
    if utente_generico is not None and utente_generico.whatsapp_validato:
        return {
            "esiste": False,
            "trovato_nel_generico": True,
            "nome": utente_generico.nome,
            "cognome": utente_generico.cognome,
            "livello_playtomic": float(utente_generico.livello_playtomic),
            "livello_dichiarato_scala": utente_generico.livello_dichiarato_scala,
            "livello_dichiarato_originale": utente_generico.livello_dichiarato_originale,
        }

    return {"esiste": False, "trovato_nel_generico": False}


def gestisci_iscrizione(db_pv: Session, db_generico: Session, dati: IscrizionePVCreate) -> dict:
    """
    Crea o aggiorna l'iscrizione di un utente Palavillage.
    Solleva ValueError per errori "di validazione" (400) e RuntimeError
    per il fallimento reale dell'invio OTP (503) - main.py li traduce
    nelle rispettive HTTPException, stesso pattern del sistema generico.
    """
    utente = db_pv.query(UtentePV).filter(UtentePV.whatsapp_numero == dati.whatsapp_numero).first()
    utente_nuovo = utente is None

    fidato_dal_generico = _numero_gia_verificato_nel_generico(db_generico, dati.whatsapp_numero)

    if utente_nuovo:
        try:
            livello_playtomic = ottieni_livello_playtomic(db_generico, dati.livello_scala, dati.livello_valore)
        except ValueError as errore:
            raise ValueError(str(errore))

        utente = UtentePV(
            nome=dati.nome,
            cognome=dati.cognome,
            whatsapp_numero=dati.whatsapp_numero,
            whatsapp_validato=fidato_dal_generico,
            livello_playtomic=livello_playtomic,
            livello_dichiarato_scala=dati.livello_scala,
            livello_dichiarato_originale=dati.livello_valore if dati.livello_scala == "WANSPORT" else None,
            lato_preferito=dati.lato_preferito,
            giorni_bitmask=crea_giorni_bitmask(dati.giorni),
        )
        db_pv.add(utente)
        db_pv.flush()
    else:
        # Il livello non si tocca mai dopo la prima registrazione (stessa
        # regola del sistema generico) - lato e giorni sono invece sempre
        # aggiornabili.
        utente.lato_preferito = dati.lato_preferito
        utente.giorni_bitmask = crea_giorni_bitmask(dati.giorni)

    if not utente.termini_accettati or not utente.privacy_accettata:
        if not (dati.accetta_termini and dati.accetta_privacy):
            raise ValueError("Devi accettare i Termini e Condizioni e la Privacy Policy per continuare.")
        utente.termini_accettati = True
        utente.privacy_accettata = True
        utente.data_accettazione_termini = datetime.utcnow()

    giorni_leggibili = giorni_bitmask_a_leggibile(utente.giorni_bitmask)

    if not utente.whatsapp_validato:
        codice = genera_otp()
        utente.otp_codice = codice
        utente.otp_scadenza = datetime.utcnow() + timedelta(minutes=config_generico.OTP_DURATA_VALIDITA_MINUTI)
        otp_inviato_davvero = invia_otp_whatsapp(utente.whatsapp_numero, codice)

        if not otp_inviato_davvero:
            db_pv.rollback()
            raise RuntimeError("otp_fallito")

        db_pv.commit()
        return {
            "utente_nuovo": utente_nuovo,
            "richiede_validazione_otp": True,
            "messaggio": "Iscrizione salvata. Ti ho appena inviato un codice di verifica su WhatsApp.",
        }

    # Numero già fidato (validato nel sistema generico, o già validato qui
    # in una precedente iscrizione a Palavillage): nessun OTP da rifare.
    riepilogo_inviato_davvero = invia_riepilogo_iscrizione_pv(
        utente.whatsapp_numero, utente.nome, giorni_leggibili,
    )
    db_pv.commit()

    messaggio = (
        "Iscrizione salvata e riepilogo inviato su WhatsApp." if riepilogo_inviato_davvero
        else "Iscrizione salvata, ma non sono riuscito a mandarti la conferma su WhatsApp in "
             "questo momento. La tua iscrizione resta comunque attiva."
    )
    return {"utente_nuovo": utente_nuovo, "richiede_validazione_otp": False, "messaggio": messaggio}


def valida_otp_pv(db_pv: Session, whatsapp_numero: str, codice_otp: str) -> dict:
    utente = db_pv.query(UtentePV).filter(UtentePV.whatsapp_numero == whatsapp_numero).first()
    if utente is None:
        raise LookupError("Utente non trovato")

    if utente.whatsapp_validato:
        return {"messaggio": "Numero già validato in precedenza."}

    if utente.otp_codice != codice_otp:
        raise ValueError("Codice OTP errato")

    if utente.otp_scadenza is None or datetime.utcnow() > utente.otp_scadenza:
        raise ValueError("Codice OTP scaduto, richiedine uno nuovo")

    utente.whatsapp_validato = True
    utente.otp_codice = None
    utente.otp_scadenza = None
    db_pv.commit()

    giorni_leggibili = giorni_bitmask_a_leggibile(utente.giorni_bitmask)
    invia_riepilogo_iscrizione_pv(
        utente.whatsapp_numero, utente.nome, giorni_leggibili,
    )

    return {"messaggio": "Numero verificato con successo."}
