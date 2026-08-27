"""
Motore del ciclo torneo di Palavillage - prima parte: generazione delle
date future e il ciclo di richiesta iscrizione (T-6gg, T-3gg).

Ogni funzione "job_*" è pensata per essere chiamata periodicamente dallo
scheduler (vedi main.py, stesso pattern del sistema generico: un job a
intervalli che ricontrolla lo stato nel database, invece di programmare
un evento esatto per ogni singolo torneo - più semplice e più resiliente
a riavvii del server).
"""

from datetime import datetime, date, time, timedelta
import secrets
from zoneinfo import ZoneInfo
from sqlalchemy.orm import Session

from app.palavillage.models import Campionato, Torneo, IscrizioneTorneo, UtentePV
from app.palavillage.config import (
    ORE_RICHIESTA_ISCRIZIONE_PRIMA, ORE_SOLLECITO_ISCRIZIONE_PRIMA,
    ORA_INIZIO_TORNEO, GIORNI_TORNEI_DA_GENERARE_IN_ANTICIPO,
)
from app.palavillage.whatsapp_pv import (
    invia_richiesta_iscrizione_torneo, invia_sollecito_iscrizione_torneo, invia_conferma_ricevuta_torneo,
)

_NOMI_GIORNI_LEGGIBILI = ["lunedì", "martedì", "mercoledì", "giovedì", "venerdì"]


def _adesso_italia() -> datetime:
    """Ora corrente, timezone-aware, fuso di Roma - stesso pattern usato nel resto del progetto."""
    return datetime.now(ZoneInfo("Europe/Rome"))


def _inizio_torneo_italia(data_torneo: date) -> datetime:
    """Data/ora esatta (timezone-aware) di inizio di un torneo in un giorno specifico."""
    ora_h, ora_m = (int(x) for x in ORA_INIZIO_TORNEO.split(":"))
    return datetime.combine(data_torneo, time(ora_h, ora_m), tzinfo=ZoneInfo("Europe/Rome"))


def genera_tornei_futuri(db_pv: Session) -> int:
    """
    Assicura che esistano righe Torneo per ogni giorno lavorativo (lun-ven)
    dei prossimi N giorni (vedi config), agganciate al campionato APERTO
    di quel giorno della settimana - creandolo (edizione 1) se non ne
    esiste ancora nessuno. Idempotente: non duplica un torneo già
    esistente per la stessa data.

    Ritorna il numero di nuovi tornei creati (comodo per i test/log).
    """
    oggi = _adesso_italia().date()
    creati = 0

    for offset in range(GIORNI_TORNEI_DA_GENERARE_IN_ANTICIPO):
        giorno_data = oggi + timedelta(days=offset)
        giorno_settimana = giorno_data.weekday()  # 0=lunedì ... 6=domenica
        if giorno_settimana > 4:
            continue  # solo lun-ven

        esiste_gia = db_pv.query(Torneo).filter(Torneo.data == giorno_data).first()
        if esiste_gia is not None:
            continue

        campionato = (
            db_pv.query(Campionato)
            .filter(Campionato.giorno_settimana == giorno_settimana, Campionato.stato == "APERTO")
            .first()
        )
        if campionato is None:
            ultima_edizione = (
                db_pv.query(Campionato)
                .filter(Campionato.giorno_settimana == giorno_settimana)
                .order_by(Campionato.numero_edizione.desc())
                .first()
            )
            nuovo_numero = (ultima_edizione.numero_edizione + 1) if ultima_edizione else 1
            campionato = Campionato(giorno_settimana=giorno_settimana, numero_edizione=nuovo_numero)
            db_pv.add(campionato)
            db_pv.flush()

        db_pv.add(Torneo(
            campionato_id=campionato.id,
            data=giorno_data,
            giorno_settimana=giorno_settimana,
            stato="PROGRAMMATO",
        ))
        creati += 1

    db_pv.commit()
    return creati


def job_invia_richieste_iscrizione(db_pv: Session) -> int:
    """
    Per ogni torneo attivo (non annullato) ancora PROGRAMMATO il cui
    T-6gg è arrivato: manda la richiesta a tutti gli utenti attivi che
    hanno quel giorno tra le loro mattine scelte, crea le righe
    IscrizioneTorneo IN_ATTESA e sposta il torneo a RICHIESTE_INVIATE.

    Ritorna il numero di tornei elaborati in questa chiamata.
    """
    adesso = _adesso_italia()
    elaborati = 0

    tornei_da_elaborare = (
        db_pv.query(Torneo)
        .filter(Torneo.stato == "PROGRAMMATO", Torneo.attivo == True)  # noqa: E712
        .all()
    )
    for torneo in tornei_da_elaborare:
        soglia = _inizio_torneo_italia(torneo.data) - timedelta(hours=ORE_RICHIESTA_ISCRIZIONE_PRIMA)
        if adesso < soglia:
            continue

        bit_giorno = 1 << torneo.giorno_settimana
        utenti_da_contattare = (
            db_pv.query(UtentePV)
            .filter(
                UtentePV.stato_account == "ATTIVO",
                UtentePV.giorni_bitmask.op("&")(bit_giorno) == bit_giorno,
            )
            .all()
        )

        giorno_leggibile = _NOMI_GIORNI_LEGGIBILI[torneo.giorno_settimana].capitalize()
        data_leggibile = torneo.data.strftime("%d/%m")

        for utente in utenti_da_contattare:
            già_iscritto = (
                db_pv.query(IscrizioneTorneo)
                .filter(IscrizioneTorneo.torneo_id == torneo.id, IscrizioneTorneo.utente_id == utente.id)
                .first()
            )
            if già_iscritto is not None:
                continue

            iscrizione = IscrizioneTorneo(
                torneo_id=torneo.id, utente_id=utente.id, stato_risposta="IN_ATTESA",
                codice_risposta=secrets.token_urlsafe(6),
            )
            db_pv.add(iscrizione)
            db_pv.flush()

            token = f"{iscrizione.id}.{iscrizione.codice_risposta}"
            invia_richiesta_iscrizione_torneo(
                utente.whatsapp_numero, utente.nome, giorno_leggibile, data_leggibile, token
            )

        torneo.stato = "RICHIESTE_INVIATE"
        elaborati += 1

    db_pv.commit()
    return elaborati


def job_invia_solleciti_iscrizione(db_pv: Session) -> int:
    """
    Per ogni torneo RICHIESTE_INVIATE il cui T-3gg è arrivato: rimanda un
    sollecito solo a chi ha ancora stato_risposta IN_ATTESA, poi sposta
    il torneo a SOLLECITO_INVIATO (una volta sola, non ripetuto ad ogni
    passaggio del job).
    """
    adesso = _adesso_italia()
    elaborati = 0

    tornei_da_elaborare = (
        db_pv.query(Torneo)
        .filter(Torneo.stato == "RICHIESTE_INVIATE", Torneo.attivo == True)  # noqa: E712
        .all()
    )
    for torneo in tornei_da_elaborare:
        soglia = _inizio_torneo_italia(torneo.data) - timedelta(hours=ORE_SOLLECITO_ISCRIZIONE_PRIMA)
        if adesso < soglia:
            continue

        giorno_leggibile = _NOMI_GIORNI_LEGGIBILI[torneo.giorno_settimana].capitalize()
        data_leggibile = torneo.data.strftime("%d/%m")

        non_risposto = (
            db_pv.query(IscrizioneTorneo)
            .filter(IscrizioneTorneo.torneo_id == torneo.id, IscrizioneTorneo.stato_risposta == "IN_ATTESA")
            .all()
        )
        for iscrizione in non_risposto:
            utente = db_pv.query(UtentePV).filter(UtentePV.id == iscrizione.utente_id).first()
            if utente is None:
                continue
            token = f"{iscrizione.id}.{iscrizione.codice_risposta}"
            invia_sollecito_iscrizione_torneo(
                utente.whatsapp_numero, utente.nome, giorno_leggibile, data_leggibile, token
            )

        torneo.stato = "SOLLECITO_INVIATO"
        elaborati += 1

    db_pv.commit()
    return elaborati


def gestisci_risposta_bottone_iscrizione(db_pv: Session, iscrizione_id: int, confermato: bool) -> dict:
    """
    Chiamata dal webhook quando arriva la risposta a un bottone Conferma/
    Non posso venire. Idempotente: se l'utente ha già risposto in
    precedenza (es. preme due volte lo stesso bottone), non cambia nulla
    e non manda un secondo messaggio di conferma.
    """
    iscrizione = db_pv.query(IscrizioneTorneo).filter(IscrizioneTorneo.id == iscrizione_id).first()
    if iscrizione is None:
        return {"gestito": False, "motivo": "iscrizione_non_trovata"}

    if iscrizione.stato_risposta != "IN_ATTESA":
        return {"gestito": False, "motivo": "già_risposto"}

    torneo = db_pv.query(Torneo).filter(Torneo.id == iscrizione.torneo_id).first()
    utente = db_pv.query(UtentePV).filter(UtentePV.id == iscrizione.utente_id).first()
    if torneo is None or utente is None:
        return {"gestito": False, "motivo": "dati_incoerenti"}

    iscrizione.stato_risposta = "CONFERMATO" if confermato else "RIFIUTATO"
    iscrizione.data_risposta = _adesso_italia().replace(tzinfo=None)
    db_pv.flush()

    if confermato:
        # L'ordine di conferma serve più avanti (formazione gruppi) per
        # decidere chi resta escluso/riserva se il totale non è multiplo
        # di 4: contiamo quanti CONFERMATO esistono ora per questo
        # torneo, inclusa questa stessa riga appena aggiornata.
        iscrizione.ordine_conferma = (
            db_pv.query(IscrizioneTorneo)
            .filter(IscrizioneTorneo.torneo_id == torneo.id, IscrizioneTorneo.stato_risposta == "CONFERMATO")
            .count()
        )

    db_pv.commit()

    giorno_leggibile = _NOMI_GIORNI_LEGGIBILI[torneo.giorno_settimana].capitalize()
    data_leggibile = torneo.data.strftime("%d/%m")
    invia_conferma_ricevuta_torneo(utente.whatsapp_numero, confermato, giorno_leggibile, data_leggibile)

    return {"gestito": True, "stato": iscrizione.stato_risposta}
