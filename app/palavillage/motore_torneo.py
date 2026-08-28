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

from app.palavillage.models import Campionato, Torneo, IscrizioneTorneo, UtentePV, GruppoPV, GruppoMembroPV, ClassificaVoce
from app.palavillage.config import (
    ORE_RICHIESTA_ISCRIZIONE_PRIMA, ORE_SOLLECITO_ISCRIZIONE_PRIMA, ORE_FORMAZIONE_GRUPPI_PRIMA,
    ORA_INIZIO_TORNEO, GIORNI_TORNEI_DA_GENERARE_IN_ANTICIPO, MINUTI_TIMEOUT_PROMOZIONE_RISERVA,
    ORE_DURATA_TORNEO, ORE_SOLLECITO_PUNTEGGIO_DOPO, ORE_CHIUSURA_FORZATA_PUNTEGGIO, URL_BASE_BACKEND_PUBBLICO,
)
from app.palavillage.whatsapp_pv import (
    invia_richiesta_iscrizione_torneo, invia_sollecito_iscrizione_torneo, invia_conferma_ricevuta_torneo,
    invia_gruppo_assegnato_torneo, invia_sei_riserva_torneo, invia_avviso_gruppo_incompleto,
    invia_proposta_promozione_riserva, invia_promozione_confermata, invia_sostituzione_compagno,
    invia_notifica_admin_nessuna_riserva, invia_richiesta_punteggio_torneo, invia_sollecito_punteggio_torneo,
    invia_punteggio_non_capito, invia_punteggio_confermato, invia_classifica_aggiornata, invia_torneo_annullato,
)
from app.palavillage.formazione_gruppi import Candidato, forma_gruppi, assegna_lati
from app.palavillage.pdf_torneo import genera_pdf_torneo, _nome_campionato_leggibile
from app.palavillage.email_pv import invia_pdf_torneo_segreteria
from app.palavillage.routing import imposta_contesto_attivo, rimuovi_contesto_attivo

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

        numero_tappa_attuale = db_pv.query(Torneo).filter(Torneo.campionato_id == campionato.id).count() + 1

        db_pv.add(Torneo(
            campionato_id=campionato.id,
            data=giorno_data,
            giorno_settimana=giorno_settimana,
            numero_tappa=numero_tappa_attuale,
            stato="PROGRAMMATO",
        ))
        creati += 1

    db_pv.commit()
    return creati


def job_invia_richieste_iscrizione(db_pv: Session, torneo_id_specifico: int | None = None, ignora_soglia_tempo: bool = False) -> int:
    """
    Per ogni torneo attivo (non annullato) ancora PROGRAMMATO il cui
    T-6gg è arrivato: manda la richiesta a tutti gli utenti attivi che
    hanno quel giorno tra le loro mattine scelte, crea le righe
    IscrizioneTorneo IN_ATTESA e sposta il torneo a RICHIESTE_INVIATE.

    RECUPERO RITARDATARI: controlla anche i tornei già passati a
    RICHIESTE_INVIATE o SOLLECITO_INVIATO, per contattare SUBITO chi si
    iscrive a quel giorno DOPO che le richieste erano già partite -
    altrimenti quella persona resterebbe esclusa da quel torneo per
    sempre (il giro successivo lo riguarderebbe solo dal torneo dopo).
    Per questi tornei "già avviati", lo stato non viene ritoccato (resta
    RICHIESTE_INVIATE o SOLLECITO_INVIATO com'era) - si aggiungono solo
    le nuove iscrizioni mancanti.

    torneo_id_specifico e ignora_soglia_tempo esistono per permettere
    all'admin di "forzare" manualmente questo passaggio su un singolo
    torneo (es. per testare il ciclo senza aspettare i giorni veri) -
    lo scheduler normale non li usa mai, chiama questa funzione senza
    argomenti extra.

    Ritorna il numero di tornei elaborati in questa chiamata.
    """
    adesso = _adesso_italia()
    elaborati = 0

    query = db_pv.query(Torneo).filter(
        Torneo.stato.in_(["PROGRAMMATO", "RICHIESTE_INVIATE", "SOLLECITO_INVIATO"]),
        Torneo.attivo == True,  # noqa: E712
    )
    if torneo_id_specifico is not None:
        query = query.filter(Torneo.id == torneo_id_specifico)
    tornei_da_elaborare = query.all()

    for torneo in tornei_da_elaborare:
        era_ancora_da_iniziare = torneo.stato == "PROGRAMMATO"

        if era_ancora_da_iniziare and not ignora_soglia_tempo:
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
        campionato = db_pv.query(Campionato).filter(Campionato.id == torneo.campionato_id).first()
        nome_campionato = _nome_campionato_leggibile(campionato)

        nuovi_contattati = 0
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
                utente.whatsapp_numero, utente.nome, nome_campionato, giorno_leggibile, data_leggibile, token
            )
            nuovi_contattati += 1

        if era_ancora_da_iniziare:
            torneo.stato = "RICHIESTE_INVIATE"
        if era_ancora_da_iniziare or nuovi_contattati > 0:
            elaborati += 1

    db_pv.commit()
    return elaborati


def job_invia_solleciti_iscrizione(db_pv: Session, torneo_id_specifico: int | None = None, ignora_soglia_tempo: bool = False) -> int:
    """
    Per ogni torneo RICHIESTE_INVIATE il cui T-3gg è arrivato: rimanda un
    sollecito solo a chi ha ancora stato_risposta IN_ATTESA, poi sposta
    il torneo a SOLLECITO_INVIATO (una volta sola, non ripetuto ad ogni
    passaggio del job).

    torneo_id_specifico e ignora_soglia_tempo: vedi job_invia_richieste_iscrizione.
    """
    adesso = _adesso_italia()
    elaborati = 0

    query = db_pv.query(Torneo).filter(Torneo.stato == "RICHIESTE_INVIATE", Torneo.attivo == True)  # noqa: E712
    if torneo_id_specifico is not None:
        query = query.filter(Torneo.id == torneo_id_specifico)
    tornei_da_elaborare = query.all()

    for torneo in tornei_da_elaborare:
        if not ignora_soglia_tempo:
            soglia = _inizio_torneo_italia(torneo.data) - timedelta(hours=ORE_SOLLECITO_ISCRIZIONE_PRIMA)
            if adesso < soglia:
                continue

        giorno_leggibile = _NOMI_GIORNI_LEGGIBILI[torneo.giorno_settimana].capitalize()
        data_leggibile = torneo.data.strftime("%d/%m")
        campionato = db_pv.query(Campionato).filter(Campionato.id == torneo.campionato_id).first()
        nome_campionato = _nome_campionato_leggibile(campionato)

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
                utente.whatsapp_numero, utente.nome, nome_campionato, giorno_leggibile, data_leggibile, token
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


def job_forma_gruppi_torneo(db_pv: Session, torneo_id_specifico: int | None = None, ignora_soglia_tempo: bool = False) -> int:
    """
    Per ogni torneo attivo il cui T-12h è arrivato: chiude le iscrizioni,
    decide titolari/riserve in base all'ordine di conferma, forma i
    gruppi da 4 con l'algoritmo di formazione_gruppi.py, li salva e manda
    i messaggi (gruppo assegnato ai titolari, "sei riserva" agli esclusi).

    torneo_id_specifico e ignora_soglia_tempo: vedi job_invia_richieste_iscrizione.
    """
    adesso = _adesso_italia()
    elaborati = 0

    query = db_pv.query(Torneo).filter(Torneo.stato == "SOLLECITO_INVIATO", Torneo.attivo == True)  # noqa: E712
    if torneo_id_specifico is not None:
        query = query.filter(Torneo.id == torneo_id_specifico)
    tornei_da_elaborare = query.all()

    for torneo in tornei_da_elaborare:
        if not ignora_soglia_tempo:
            soglia = _inizio_torneo_italia(torneo.data) - timedelta(hours=ORE_FORMAZIONE_GRUPPI_PRIMA)
            if adesso < soglia:
                continue

        giorno_leggibile = _NOMI_GIORNI_LEGGIBILI[torneo.giorno_settimana].capitalize()
        data_leggibile = torneo.data.strftime("%d/%m")
        campionato_corrente = db_pv.query(Campionato).filter(Campionato.id == torneo.campionato_id).first()
        nome_campionato = _nome_campionato_leggibile(campionato_corrente)

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
                        utente.whatsapp_numero, utente.nome, nome_campionato, giorno_leggibile, data_leggibile,
                        compagni_nomi,
                    )

        for iscrizione in riserve_iscrizioni:
            utente = db_pv.query(UtentePV).filter(UtentePV.id == iscrizione.utente_id).first()
            if utente is not None:
                invia_sei_riserva_torneo(utente.whatsapp_numero, utente.nome, nome_campionato, giorno_leggibile, data_leggibile)

        if n_completi > 0:
            pdf_bytes = genera_pdf_torneo(db_pv, torneo.id)
            if pdf_bytes is not None:
                nome_file = f"palavillage_gruppi_{torneo.data.isoformat()}.pdf"
                oggetto = f"Palavillage - Gruppi torneo {giorno_leggibile} {data_leggibile}"
                corpo_testo = (
                    f"In allegato le tabelle dei gruppi e la griglia punteggi per il torneo di "
                    f"{giorno_leggibile} {data_leggibile}."
                )
                invia_pdf_torneo_segreteria(pdf_bytes, nome_file, oggetto, corpo_testo)
            torneo.stato = "PDF_INVIATI"
        else:
            torneo.stato = "GRUPPI_FORMATI"

        db_pv.commit()
        elaborati += 1

    return elaborati


def _prova_promuovi_prossima_riserva(db_pv: Session, torneo: Torneo, gruppo_id: int, lato_da_coprire: str) -> bool:
    """
    Cerca la prima riserva ancora disponibile (non già "saltata" per
    aver rifiutato o non risposto in tempo a un tentativo precedente) e
    le propone il posto libero. Se non ce n'è nessuna, avvisa SOLO
    l'amministratore (nessuna azione automatica ulteriore, come
    concordato) e ritorna False.
    """
    candidata = (
        db_pv.query(IscrizioneTorneo)
        .filter(
            IscrizioneTorneo.torneo_id == torneo.id,
            IscrizioneTorneo.ruolo == "RISERVA",
            IscrizioneTorneo.stato_risposta == "CONFERMATO",
        )
        .order_by(IscrizioneTorneo.ordine_conferma)
        .first()
    )

    giorno_leggibile = _NOMI_GIORNI_LEGGIBILI[torneo.giorno_settimana].capitalize()
    data_leggibile = torneo.data.strftime("%d/%m")
    campionato_torneo = db_pv.query(Campionato).filter(Campionato.id == torneo.campionato_id).first()
    nome_campionato = _nome_campionato_leggibile(campionato_torneo)

    if candidata is None:
        gruppo = db_pv.query(GruppoPV).filter(GruppoPV.id == gruppo_id).first()
        numero_gruppo = gruppo.numero_gruppo if gruppo else 0
        invia_notifica_admin_nessuna_riserva(nome_campionato, giorno_leggibile, data_leggibile, numero_gruppo)
        return False

    utente = db_pv.query(UtentePV).filter(UtentePV.id == candidata.utente_id).first()
    candidata.promozione_scadenza = _adesso_italia().replace(tzinfo=None) + timedelta(minutes=MINUTI_TIMEOUT_PROMOZIONE_RISERVA)
    candidata.gruppo_proposto_id = gruppo_id
    candidata.lato_proposto = lato_da_coprire
    db_pv.commit()

    token = f"{candidata.id}.{candidata.codice_risposta}"
    invia_proposta_promozione_riserva(
        utente.whatsapp_numero, utente.nome, nome_campionato, giorno_leggibile, data_leggibile, token, MINUTI_TIMEOUT_PROMOZIONE_RISERVA
    )
    return True


def richiedi_cancellazione_tardiva(db_pv: Session, iscrizione_id: int) -> dict:
    """
    Un titolare, dopo che i gruppi sono già stati formati, comunica che
    non può più venire. Libera il suo posto nel gruppo, avvisa i 3
    compagni rimasti, e tenta subito di promuovere la prima riserva
    disponibile.
    """
    iscrizione = db_pv.query(IscrizioneTorneo).filter(IscrizioneTorneo.id == iscrizione_id).first()
    if iscrizione is None:
        return {"gestito": False, "motivo": "iscrizione_non_trovata"}

    torneo = db_pv.query(Torneo).filter(Torneo.id == iscrizione.torneo_id).first()
    if torneo is None or torneo.stato not in ("GRUPPI_FORMATI", "PDF_INVIATI") or iscrizione.stato_risposta != "CONFERMATO" or iscrizione.ruolo != "TITOLARE":
        return {"gestito": False, "motivo": "non_cancellabile_in_questo_momento"}

    membro = (
        db_pv.query(GruppoMembroPV)
        .filter(GruppoMembroPV.utente_id == iscrizione.utente_id)
        .join(GruppoPV, GruppoPV.id == GruppoMembroPV.gruppo_id)
        .filter(GruppoPV.torneo_id == torneo.id)
        .first()
    )
    if membro is None:
        return {"gestito": False, "motivo": "dati_incoerenti"}

    gruppo_id = membro.gruppo_id
    lato_liberato = membro.lato_assegnato

    giorno_leggibile = _NOMI_GIORNI_LEGGIBILI[torneo.giorno_settimana].capitalize()
    data_leggibile = torneo.data.strftime("%d/%m")
    campionato_torneo = db_pv.query(Campionato).filter(Campionato.id == torneo.campionato_id).first()
    nome_campionato = _nome_campionato_leggibile(campionato_torneo)

    altri_membri = (
        db_pv.query(GruppoMembroPV)
        .filter(GruppoMembroPV.gruppo_id == gruppo_id, GruppoMembroPV.utente_id != iscrizione.utente_id)
        .all()
    )
    for altro in altri_membri:
        altro_utente = db_pv.query(UtentePV).filter(UtentePV.id == altro.utente_id).first()
        if altro_utente is not None:
            invia_avviso_gruppo_incompleto(altro_utente.whatsapp_numero, altro_utente.nome, nome_campionato, giorno_leggibile, data_leggibile)

    db_pv.delete(membro)
    iscrizione.stato_risposta = "RITIRATO_DOPO_GRUPPO"
    db_pv.commit()

    trovata_riserva = _prova_promuovi_prossima_riserva(db_pv, torneo, gruppo_id, lato_liberato)

    return {"gestito": True, "riserva_contattata": trovata_riserva}


def gestisci_risposta_promozione(db_pv: Session, iscrizione_id: int, accettata: bool) -> dict:
    """
    Risposta di una riserva a una proposta di promozione attiva. Se
    rifiuta (o la proposta nel frattempo è scaduta), si passa in cascata
    alla riserva successiva - non ci si ferma al primo rifiuto se ce ne
    sono altre disponibili.
    """
    iscrizione = db_pv.query(IscrizioneTorneo).filter(IscrizioneTorneo.id == iscrizione_id).first()
    if iscrizione is None or iscrizione.promozione_scadenza is None:
        return {"gestito": False, "motivo": "nessuna_proposta_attiva"}

    torneo = db_pv.query(Torneo).filter(Torneo.id == iscrizione.torneo_id).first()
    gruppo_id = iscrizione.gruppo_proposto_id
    lato_proposto = iscrizione.lato_proposto
    scaduta = _adesso_italia().replace(tzinfo=None) > iscrizione.promozione_scadenza

    iscrizione.promozione_scadenza = None
    iscrizione.gruppo_proposto_id = None
    iscrizione.lato_proposto = None

    if scaduta:
        iscrizione.ruolo = "RISERVA_SALTATA"
        db_pv.commit()
        _prova_promuovi_prossima_riserva(db_pv, torneo, gruppo_id, lato_proposto)
        return {"gestito": False, "motivo": "proposta_scaduta"}

    if not accettata:
        iscrizione.ruolo = "RISERVA_SALTATA"
        db_pv.commit()
        _prova_promuovi_prossima_riserva(db_pv, torneo, gruppo_id, lato_proposto)
        return {"gestito": True, "esito": "rifiutata"}

    utente = db_pv.query(UtentePV).filter(UtentePV.id == iscrizione.utente_id).first()
    db_pv.add(GruppoMembroPV(gruppo_id=gruppo_id, utente_id=utente.id, lato_assegnato=lato_proposto))
    iscrizione.ruolo = "TITOLARE"
    db_pv.commit()

    giorno_leggibile = _NOMI_GIORNI_LEGGIBILI[torneo.giorno_settimana].capitalize()
    data_leggibile = torneo.data.strftime("%d/%m")
    campionato_torneo = db_pv.query(Campionato).filter(Campionato.id == torneo.campionato_id).first()
    nome_campionato = _nome_campionato_leggibile(campionato_torneo)

    membri_gruppo = db_pv.query(GruppoMembroPV).filter(GruppoMembroPV.gruppo_id == gruppo_id).all()
    nomi_compagni = []
    for membro in membri_gruppo:
        if membro.utente_id == utente.id:
            continue
        compagno = db_pv.query(UtentePV).filter(UtentePV.id == membro.utente_id).first()
        if compagno is not None:
            nomi_compagni.append(compagno.nome)
            invia_sostituzione_compagno(compagno.whatsapp_numero, compagno.nome, nome_campionato, giorno_leggibile, data_leggibile, utente.nome)

    invia_promozione_confermata(utente.whatsapp_numero, utente.nome, giorno_leggibile, data_leggibile,
                                  ", ".join(nomi_compagni))

    return {"gestito": True, "esito": "promossa"}


def job_gestisci_promozioni_scadute(db_pv: Session) -> int:
    """
    Job periodico: chi aveva una proposta di promozione attiva ma non ha
    risposto entro il tempo dato viene considerato "saltato" e si passa
    alla riserva successiva - stessa logica di un rifiuto esplicito.
    """
    adesso = _adesso_italia().replace(tzinfo=None)
    scadute = (
        db_pv.query(IscrizioneTorneo)
        .filter(IscrizioneTorneo.promozione_scadenza.isnot(None), IscrizioneTorneo.promozione_scadenza < adesso)
        .all()
    )
    for iscrizione in scadute:
        gestisci_risposta_promozione(db_pv, iscrizione.id, accettata=False)

    return len(scadute)


def job_richiedi_punteggio_torneo(db_pv: Session, torneo_id_specifico: int | None = None, ignora_soglia_tempo: bool = False) -> int:
    """
    Quando un torneo è "finito" (ORE_DURATA_TORNEO dopo l'inizio), chiede
    il punteggio a ogni titolare che ha davvero giocato (uno dei membri
    di uno dei gruppi). Imposta anche il "contesto attivo" per ogni
    numero, così il webhook sa interpretare il prossimo messaggio di
    testo libero come una risposta a questa domanda.

    torneo_id_specifico e ignora_soglia_tempo: vedi job_invia_richieste_iscrizione.
    """
    adesso = _adesso_italia().replace(tzinfo=None)
    elaborati = 0

    query = db_pv.query(Torneo).filter(Torneo.stato.in_(["PDF_INVIATI", "GRUPPI_FORMATI"]), Torneo.attivo == True)  # noqa: E712
    if torneo_id_specifico is not None:
        query = query.filter(Torneo.id == torneo_id_specifico)
    tornei_da_elaborare = query.all()

    for torneo in tornei_da_elaborare:
        if not ignora_soglia_tempo:
            soglia = _inizio_torneo_italia(torneo.data) + timedelta(hours=ORE_DURATA_TORNEO)
            soglia_naive = soglia.replace(tzinfo=None)
            if adesso < soglia_naive:
                continue

        giorno_leggibile = _NOMI_GIORNI_LEGGIBILI[torneo.giorno_settimana].capitalize()
        data_leggibile = torneo.data.strftime("%d/%m")
        campionato_torneo = db_pv.query(Campionato).filter(Campionato.id == torneo.campionato_id).first()
        nome_campionato = _nome_campionato_leggibile(campionato_torneo)

        gruppi = db_pv.query(GruppoPV).filter(GruppoPV.torneo_id == torneo.id).all()
        for gruppo in gruppi:
            membri = db_pv.query(GruppoMembroPV).filter(GruppoMembroPV.gruppo_id == gruppo.id).all()
            for membro in membri:
                utente = db_pv.query(UtentePV).filter(UtentePV.id == membro.utente_id).first()
                if utente is None:
                    continue
                membro.punteggio_richiesto_il = adesso
                invia_richiesta_punteggio_torneo(utente.whatsapp_numero, utente.nome, nome_campionato, giorno_leggibile, data_leggibile)
                imposta_contesto_attivo(db_pv, utente.whatsapp_numero, "RICHIESTA_PUNTEGGIO", membro.id)

        torneo.stato = "RICHIESTA_PUNTEGGIO_INVIATA"
        db_pv.commit()
        elaborati += 1

    return elaborati


def job_sollecito_punteggio_torneo(db_pv: Session) -> int:
    """T+2h dalla richiesta iniziale: sollecita solo chi non ha ancora risposto, una volta sola."""
    adesso = _adesso_italia().replace(tzinfo=None)
    soglia_sollecito = adesso - timedelta(hours=ORE_SOLLECITO_PUNTEGGIO_DOPO)

    da_sollecitare = (
        db_pv.query(GruppoMembroPV)
        .filter(
            GruppoMembroPV.stato_richiesta_punteggio == "IN_ATTESA",
            GruppoMembroPV.punteggio_richiesto_il.isnot(None),
            GruppoMembroPV.punteggio_richiesto_il < soglia_sollecito,
            GruppoMembroPV.punteggio_sollecito_inviato == False,  # noqa: E712
        )
        .all()
    )

    for membro in da_sollecitare:
        utente = db_pv.query(UtentePV).filter(UtentePV.id == membro.utente_id).first()
        gruppo = db_pv.query(GruppoPV).filter(GruppoPV.id == membro.gruppo_id).first()
        torneo = db_pv.query(Torneo).filter(Torneo.id == gruppo.torneo_id).first() if gruppo else None
        if utente is None or torneo is None:
            continue

        giorno_leggibile = _NOMI_GIORNI_LEGGIBILI[torneo.giorno_settimana].capitalize()
        data_leggibile = torneo.data.strftime("%d/%m")
        campionato_torneo = db_pv.query(Campionato).filter(Campionato.id == torneo.campionato_id).first()
        nome_campionato = _nome_campionato_leggibile(campionato_torneo)
        invia_sollecito_punteggio_torneo(utente.whatsapp_numero, utente.nome, nome_campionato, giorno_leggibile, data_leggibile)
        # Rinnoviamo il contesto attivo: la finestra iniziale (3h) potrebbe
        # scadere prima che arrivi la risposta, specie se il sollecito
        # stesso arriva dopo 2h - senza questo rinnovo, un messaggio di
        # testo libero mandato dopo la scadenza scorrerebbe verso il
        # sistema generico invece di essere interpretato come punteggio.
        imposta_contesto_attivo(db_pv, utente.whatsapp_numero, "RICHIESTA_PUNTEGGIO", membro.id)
        membro.punteggio_sollecito_inviato = True

    db_pv.commit()
    return len(da_sollecitare)


def registra_punteggio_gruppo_membro(db_pv: Session, gruppo_membro_id: int, testo_ricevuto: str) -> dict:
    """
    Chiamata dal webhook quando arriva un messaggio di testo libero e il
    contesto attivo dice che stiamo aspettando un punteggio da questo
    numero. Prova a interpretare 'testo_ricevuto' come un numero di game;
    se non ci riesce, chiede di ripetere SENZA cancellare il contesto
    attivo (l'utente può riprovare subito dopo).
    """
    membro = db_pv.query(GruppoMembroPV).filter(GruppoMembroPV.id == gruppo_membro_id).first()
    if membro is None:
        return {"gestito": False, "motivo": "membro_non_trovato"}

    utente = db_pv.query(UtentePV).filter(UtentePV.id == membro.utente_id).first()
    if utente is None:
        return {"gestito": False, "motivo": "utente_non_trovato"}

    if membro.stato_richiesta_punteggio == "RICEVUTO":
        rimuovi_contesto_attivo(db_pv, utente.whatsapp_numero)
        return {"gestito": False, "motivo": "già_ricevuto"}

    import re
    corrispondenza = re.search(r"\d+", testo_ricevuto or "")
    if not corrispondenza:
        invia_punteggio_non_capito(utente.whatsapp_numero)
        return {"gestito": False, "motivo": "non_interpretabile"}

    punteggio = int(corrispondenza.group())
    if punteggio < 0 or punteggio > 200:
        invia_punteggio_non_capito(utente.whatsapp_numero)
        return {"gestito": False, "motivo": "fuori_range"}

    membro.punteggio_riportato = punteggio
    membro.stato_richiesta_punteggio = "RICEVUTO"
    membro.data_risposta_punteggio = _adesso_italia().replace(tzinfo=None)
    db_pv.commit()

    rimuovi_contesto_attivo(db_pv, utente.whatsapp_numero)
    invia_punteggio_confermato(utente.whatsapp_numero, punteggio)

    return {"gestito": True, "punteggio": punteggio}


def job_finalizza_punteggi_torneo(db_pv: Session) -> int:
    """
    Per ogni torneo in attesa di punteggi: se TUTTI i titolari hanno
    risposto, oppure se è passato troppo tempo (chiusura forzata anche
    con risposte mancanti), aggiorna la classifica del campionato e la
    manda a tutti i partecipanti, poi segna il torneo TERMINATO.
    """
    adesso = _adesso_italia().replace(tzinfo=None)
    elaborati = 0

    tornei_da_elaborare = (
        db_pv.query(Torneo)
        .filter(Torneo.stato == "RICHIESTA_PUNTEGGIO_INVIATA", Torneo.attivo == True)  # noqa: E712
        .all()
    )
    for torneo in tornei_da_elaborare:
        gruppi = db_pv.query(GruppoPV).filter(GruppoPV.torneo_id == torneo.id).all()
        gruppo_ids = [g.id for g in gruppi]
        if not gruppo_ids:
            continue

        membri = db_pv.query(GruppoMembroPV).filter(GruppoMembroPV.gruppo_id.in_(gruppo_ids)).all()
        if not membri:
            continue

        tutti_risposto = all(m.stato_richiesta_punteggio == "RICEVUTO" for m in membri)

        richiesta_piu_vecchia = min((m.punteggio_richiesto_il for m in membri if m.punteggio_richiesto_il), default=None)
        tempo_scaduto = (
            richiesta_piu_vecchia is not None
            and adesso - richiesta_piu_vecchia > timedelta(hours=ORE_CHIUSURA_FORZATA_PUNTEGGIO)
        )

        if not (tutti_risposto or tempo_scaduto):
            continue

        # Aggiorna la classifica con chi ha effettivamente riportato un punteggio
        for membro in membri:
            if membro.punteggio_riportato is None:
                if membro.stato_richiesta_punteggio == "IN_ATTESA":
                    membro.stato_richiesta_punteggio = "NON_RISPOSTO"
                utente_senza_risposta = db_pv.query(UtentePV).filter(UtentePV.id == membro.utente_id).first()
                if utente_senza_risposta is not None:
                    rimuovi_contesto_attivo(db_pv, utente_senza_risposta.whatsapp_numero)
                continue

            voce = (
                db_pv.query(ClassificaVoce)
                .filter(ClassificaVoce.campionato_id == torneo.campionato_id, ClassificaVoce.utente_id == membro.utente_id)
                .first()
            )
            if voce is None:
                voce = ClassificaVoce(campionato_id=torneo.campionato_id, utente_id=membro.utente_id, punti_totali=0, partite_giocate=0)
                db_pv.add(voce)
                db_pv.flush()
            voce.punti_totali += membro.punteggio_riportato
            voce.partite_giocate += 1

        db_pv.commit()

        # Manda a tutti i partecipanti il link al PDF della classifica aggiornata
        campionato = db_pv.query(Campionato).filter(Campionato.id == torneo.campionato_id).first()
        nome_campionato = _nome_campionato_leggibile(campionato)
        giorno_leggibile = _NOMI_GIORNI_LEGGIBILI[torneo.giorno_settimana].capitalize()
        data_leggibile = torneo.data.strftime("%d/%m")

        for membro in membri:
            utente = db_pv.query(UtentePV).filter(UtentePV.id == membro.utente_id).first()
            if utente is not None:
                invia_classifica_aggiornata(
                    utente.whatsapp_numero, utente.nome, nome_campionato,
                    giorno_leggibile, data_leggibile, torneo.campionato_id,
                )

        torneo.stato = "TERMINATO"
        db_pv.commit()
        elaborati += 1

    return elaborati


# Stati in cui un torneo può ancora essere cancellato dall'admin - prima
# che i gruppi vengano formati. Una volta formati i gruppi, cancellare
# creerebbe troppa confusione (giocatori già avvisati dei compagni, PDF
# già mandato alla segreteria) - da lì in poi non si cancella più, come
# concordato.
STATI_TORNEO_CANCELLABILI = {"PROGRAMMATO", "RICHIESTE_INVIATE", "SOLLECITO_INVIATO"}


def attiva_torneo(db_pv: Session, torneo_id: int) -> dict:
    """Riattiva un torneo precedentemente cancellato (finché non sono già stati formati i gruppi)."""
    torneo = db_pv.query(Torneo).filter(Torneo.id == torneo_id).first()
    if torneo is None:
        return {"ok": False, "motivo": "torneo_non_trovato"}
    torneo.attivo = True
    db_pv.commit()
    return {"ok": True}


def cancella_torneo(db_pv: Session, torneo_id: int) -> dict:
    """
    Cancella un torneo futuro (es. giorno festivo). Se erano già state
    mandate richieste di iscrizione, avvisa chi le aveva ricevute. Non
    permette di cancellare un torneo i cui gruppi sono già stati formati.
    """
    torneo = db_pv.query(Torneo).filter(Torneo.id == torneo_id).first()
    if torneo is None:
        return {"ok": False, "motivo": "torneo_non_trovato"}

    if torneo.stato not in STATI_TORNEO_CANCELLABILI:
        return {"ok": False, "motivo": "non_cancellabile_gruppi_gia_formati"}

    giorno_leggibile = _NOMI_GIORNI_LEGGIBILI[torneo.giorno_settimana].capitalize()
    data_leggibile = torneo.data.strftime("%d/%m")
    campionato_torneo = db_pv.query(Campionato).filter(Campionato.id == torneo.campionato_id).first()
    nome_campionato = _nome_campionato_leggibile(campionato_torneo)

    iscrizioni_gia_contattate = db_pv.query(IscrizioneTorneo).filter(IscrizioneTorneo.torneo_id == torneo.id).all()
    for iscrizione in iscrizioni_gia_contattate:
        utente = db_pv.query(UtentePV).filter(UtentePV.id == iscrizione.utente_id).first()
        if utente is not None:
            invia_torneo_annullato(utente.whatsapp_numero, utente.nome, nome_campionato, giorno_leggibile, data_leggibile)

    torneo.attivo = False
    db_pv.commit()
    return {"ok": True, "utenti_avvisati": len(iscrizioni_gia_contattate)}
