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

from app.palavillage.models import Campionato, Torneo, IscrizioneTorneo, UtentePV, GruppoPV, GruppoMembroPV
from app.palavillage.config import (
    ORE_RICHIESTA_ISCRIZIONE_PRIMA, ORE_SOLLECITO_ISCRIZIONE_PRIMA, ORE_FORMAZIONE_GRUPPI_PRIMA,
    ORA_INIZIO_TORNEO, GIORNI_TORNEI_DA_GENERARE_IN_ANTICIPO,
)
from app.palavillage.whatsapp_pv import (
    invia_richiesta_iscrizione_torneo, invia_sollecito_iscrizione_torneo, invia_conferma_ricevuta_torneo,
    invia_gruppo_assegnato_torneo, invia_sei_riserva_torneo,
)
from app.palavillage.formazione_gruppi import Candidato, forma_gruppi, assegna_lati

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


def _mappa_compagni_precedenti(db_pv: Session, campionato_id: int, torneo_id_corrente: int) -> dict[int, set]:
    """
    Guarda l'ultimo torneo passato dello stesso campionato (stesso giorno
    della settimana) che ha già gruppi formati, e ricostruisce per ogni
    utente l'insieme dei compagni con cui ha giocato quella volta. Se non
    esiste un torneo precedente con gruppi (es. prima edizione in
    assoluto), ritorna una mappa vuota - va bene, in quel caso l'algoritmo
    di formazione gruppi si limita a bilanciare per livello/lato.
    """
    torneo_precedente = (
        db_pv.query(Torneo)
        .filter(Torneo.campionato_id == campionato_id, Torneo.id != torneo_id_corrente)
        .join(GruppoPV, GruppoPV.torneo_id == Torneo.id)
        .order_by(Torneo.data.desc())
        .first()
    )
    if torneo_precedente is None:
        return {}

    gruppi_precedenti = db_pv.query(GruppoPV).filter(GruppoPV.torneo_id == torneo_precedente.id).all()
    mappa: dict[int, set] = {}
    for gruppo in gruppi_precedenti:
        membri = db_pv.query(GruppoMembroPV).filter(GruppoMembroPV.gruppo_id == gruppo.id).all()
        ids_membri = [m.utente_id for m in membri]
        for utente_id in ids_membri:
            mappa[utente_id] = set(ids_membri) - {utente_id}

    return mappa


def job_forma_gruppi_torneo(db_pv: Session) -> int:
    """
    Per ogni torneo attivo il cui T-12h è arrivato: chiude le iscrizioni,
    decide titolari/riserve in base all'ordine di conferma, forma i
    gruppi da 4 con l'algoritmo di formazione_gruppi.py, li salva e manda
    i messaggi (gruppo assegnato ai titolari, "sei riserva" agli esclusi).
    """
    adesso = _adesso_italia()
    elaborati = 0

    tornei_da_elaborare = (
        db_pv.query(Torneo)
        .filter(Torneo.stato == "SOLLECITO_INVIATO", Torneo.attivo == True)  # noqa: E712
        .all()
    )
    for torneo in tornei_da_elaborare:
        soglia = _inizio_torneo_italia(torneo.data) - timedelta(hours=ORE_FORMAZIONE_GRUPPI_PRIMA)
        if adesso < soglia:
            continue

        giorno_leggibile = _NOMI_GIORNI_LEGGIBILI[torneo.giorno_settimana].capitalize()
        data_leggibile = torneo.data.strftime("%d/%m")

        confermati = (
            db_pv.query(IscrizioneTorneo)
            .filter(IscrizioneTorneo.torneo_id == torneo.id, IscrizioneTorneo.stato_risposta == "CONFERMATO")
            .order_by(IscrizioneTorneo.ordine_conferma)
            .all()
        )

        n_completi = (len(confermati) // 4) * 4
        titolari_iscrizioni = confermati[:n_completi]
        riserve_iscrizioni = confermati[n_completi:]

        for iscrizione in riserve_iscrizioni:
            iscrizione.ruolo = "RISERVA"
        for iscrizione in titolari_iscrizioni:
            iscrizione.ruolo = "TITOLARE"
        db_pv.commit()

        if n_completi > 0:
            compagni_precedenti = _mappa_compagni_precedenti(db_pv, torneo.campionato_id, torneo.id)

            utenti_per_id = {}
            candidati = []
            for iscrizione in titolari_iscrizioni:
                utente = db_pv.query(UtentePV).filter(UtentePV.id == iscrizione.utente_id).first()
                utenti_per_id[utente.id] = utente
                candidati.append(Candidato(
                    id=utente.id,
                    livello=float(utente.livello_playtomic),
                    lato=utente.lato_preferito,
                    compagni_precedenti=compagni_precedenti.get(utente.id, set()),
                ))

            gruppi_formati = forma_gruppi(candidati)

            for indice, gruppo in enumerate(gruppi_formati, start=1):
                gruppo_db = GruppoPV(torneo_id=torneo.id, numero_gruppo=indice)
                db_pv.add(gruppo_db)
                db_pv.flush()

                assegnazione_lati = assegna_lati(gruppo)
                for candidato in gruppo:
                    db_pv.add(GruppoMembroPV(
                        gruppo_id=gruppo_db.id,
                        utente_id=candidato.id,
                        lato_assegnato=assegnazione_lati[candidato.id],
                    ))
                db_pv.commit()

                nomi_gruppo = {c.id: utenti_per_id[c.id].nome for c in gruppo}
                for candidato in gruppo:
                    compagni_nomi = ", ".join(nomi_gruppo[c.id] for c in gruppo if c.id != candidato.id)
                    utente = utenti_per_id[candidato.id]
                    invia_gruppo_assegnato_torneo(
                        utente.whatsapp_numero, utente.nome, giorno_leggibile, data_leggibile,
                        compagni_nomi, assegnazione_lati[candidato.id],
                    )

        for iscrizione in riserve_iscrizioni:
            utente = db_pv.query(UtentePV).filter(UtentePV.id == iscrizione.utente_id).first()
            if utente is not None:
                invia_sei_riserva_torneo(utente.whatsapp_numero, utente.nome, giorno_leggibile, data_leggibile)

        torneo.stato = "GRUPPI_FORMATI"
        db_pv.commit()
        elaborati += 1

    return elaborati
