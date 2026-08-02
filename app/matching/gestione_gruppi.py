"""
Step 03/04 (parte "conferma"): gestisce le risposte dei giocatori a una
proposta di partita, il timeout dei 15 minuti, e le conseguenze previste
(contatore mancate conferme, sospensione dopo 3 - punto 14).
"""

from datetime import datetime, timedelta
from sqlalchemy.orm import Session, joinedload

from app import models, config
from app.matching.notifiche import notifica_annullamento_gruppo, notifica_gruppo_confermato
from app.services.whatsapp import invia_sospensione_account


def _penalizza_mancata_conferma(db: Session, utente: models.Utente):
    """
    Incrementa il contatore delle mancate conferme consecutive (punto 14).
    Se raggiunge la soglia, sospende l'account per i giorni previsti.
    """
    utente.mancate_conferme_consecutive += 1

    if utente.mancate_conferme_consecutive >= config.MAX_MANCATE_CONFERME_PRIMA_SOSPENSIONE:
        utente.stato_account = "SOSPESO"
        utente.sospeso_fino_a = datetime.utcnow() + timedelta(days=config.GIORNI_SOSPENSIONE)
        utente.mancate_conferme_consecutive = 0  # si riparte da zero dopo la sospensione
        invia_sospensione_account(utente.whatsapp_numero, config.GIORNI_SOSPENSIONE)


def _resetta_contatore_mancate_conferme(utente: models.Utente):
    """Una conferma andata a buon fine azzera il contatore (buona fede premiata)."""
    utente.mancate_conferme_consecutive = 0


def _carica_gruppo_completo(db: Session, gruppo_id: int):
    """Recupera un gruppo con tutti i dati collegati necessari (membri, utenti, richieste)."""
    gruppo = (
        db.query(models.Gruppo)
        .options(
            joinedload(models.Gruppo.membri).joinedload(models.GruppoMembro.utente),
        )
        .filter(models.Gruppo.id == gruppo_id)
        .first()
    )
    return gruppo


def _annulla_gruppo(db: Session, gruppo: models.Gruppo, motivo: str):
    """
    Annulla un gruppo (per rifiuto esplicito o per timeout).
    Applica le conseguenze giuste a ciascun membro in base al suo stato:
    - CONFERMATO -> torna in ricerca, nessuna penalità, contatore già azzerato
    - RIFIUTATO o rimasto IN_ATTESA al momento del timeout -> penalizzato,
      la sua richiesta viene annullata (deve reinserirla se vuole)
    - IN_ATTESA per annullamento causato da un ALTRO che ha rifiutato prima
      del timeout -> nessuna penalità, torna in ricerca (non è colpa sua)
    """
    gruppo.stato = "ANNULLATO"
    circolo_nome = motivo  # usato solo per log, il motivo testuale è già pronto

    for membro in gruppo.membri:
        richiesta = db.query(models.Richiesta).filter(models.Richiesta.id == membro.richiesta_id).first()

        if membro.stato_conferma == "CONFERMATO":
            richiesta.stato = "IN_RICERCA"

        elif membro.stato_conferma == "RIFIUTATO":
            richiesta.stato = "ANNULLATA"
            _penalizza_mancata_conferma(db, membro.utente)

        elif membro.stato_conferma == "IN_ATTESA":
            # Se siamo qui per TIMEOUT, chi è rimasto IN_ATTESA non ha risposto: penalizzato.
            # Se siamo qui per un RIFIUTO ALTRUI arrivato prima del timeout, non è colpa sua.
            # Distinguiamo guardando se il gruppo è scaduto per tempo o no.
            if datetime.utcnow() >= gruppo.scadenza_conferma:
                membro.stato_conferma = "NON_RISPOSTO"
                richiesta.stato = "ANNULLATA"
                _penalizza_mancata_conferma(db, membro.utente)
            else:
                richiesta.stato = "IN_RICERCA"

    notifica_annullamento_gruppo(gruppo.membri, motivo)
    db.commit()


def _completa_gruppo_se_possibile(db: Session, gruppo: models.Gruppo) -> bool:
    """Se tutti e 4 hanno confermato, il gruppo passa allo stato CONFERMATO (pronto per lo Step 04)."""
    tutti_confermati = all(m.stato_conferma == "CONFERMATO" for m in gruppo.membri)

    if tutti_confermati:
        gruppo.stato = "CONFERMATO"
        circolo = db.query(models.Circolo).filter(models.Circolo.id == gruppo.circolo_id).first()
        notifica_gruppo_confermato(gruppo.membri, gruppo, circolo)
        db.commit()
        return True

    return False


def rispondi_a_gruppo(db: Session, gruppo_id: int, utente_id: int, risposta: str):
    """
    Registra la risposta di un giocatore a una proposta di partita.
    risposta: "CONFERMA" oppure "RIFIUTO"
    """
    gruppo = _carica_gruppo_completo(db, gruppo_id)
    if gruppo is None:
        raise ValueError("Gruppo non trovato")

    if gruppo.stato != "PROPOSTO":
        raise ValueError(f"Il gruppo non è più in attesa di conferma (stato attuale: {gruppo.stato})")

    membro = next((m for m in gruppo.membri if m.utente_id == utente_id), None)
    if membro is None:
        raise ValueError("Questo utente non fa parte di questo gruppo")

    if membro.stato_conferma != "IN_ATTESA":
        raise ValueError("Hai già risposto a questa proposta")

    membro.data_risposta = datetime.utcnow()

    if risposta == "CONFERMA":
        membro.stato_conferma = "CONFERMATO"
        _resetta_contatore_mancate_conferme(membro.utente)
        db.commit()

        gruppo_completato = _completa_gruppo_se_possibile(db, gruppo)
        return {"stato_gruppo": gruppo.stato, "completato": gruppo_completato}

    elif risposta == "RIFIUTO":
        membro.stato_conferma = "RIFIUTATO"
        db.commit()

        _annulla_gruppo(db, gruppo, motivo=f"{membro.utente.nome} {membro.utente.cognome} ha rifiutato")
        return {"stato_gruppo": "ANNULLATO"}

    else:
        raise ValueError("Risposta non valida, deve essere CONFERMA o RIFIUTO")


def controlla_timeout_gruppi(db: Session):
    """
    Da eseguire periodicamente (ogni minuto): cerca i gruppi ancora
    PROPOSTO la cui scadenza_conferma è passata, e li annulla applicando
    le penalità a chi non ha risposto in tempo.
    """
    adesso = datetime.utcnow()

    gruppi_scaduti = (
        db.query(models.Gruppo)
        .options(joinedload(models.Gruppo.membri).joinedload(models.GruppoMembro.utente))
        .filter(models.Gruppo.stato == "PROPOSTO", models.Gruppo.scadenza_conferma <= adesso)
        .all()
    )

    for gruppo in gruppi_scaduti:
        _annulla_gruppo(db, gruppo, motivo="Tempo scaduto: non tutti hanno confermato in tempo")

    return len(gruppi_scaduti)


def rispondi_a_gruppo_da_whatsapp(db: Session, numero_whatsapp: str, testo_risposta: str) -> dict:
    """
    Collega una risposta arrivata realmente su WhatsApp (via webhook Twilio)
    alla stessa logica già usata da rispondi_a_gruppo. Invece di ricevere
    già gruppo_id/utente_id (che l'utente non manda), li ricava da soli:
    - trova l'utente dal numero di telefono che ha scritto
    - trova la SUA proposta attualmente in attesa di risposta (grazie al
      meccanismo di lock, un utente ha al massimo una proposta PROPOSTO
      alla volta, quindi non c'è ambiguità)
    - interpreta il testo del bottone premuto (Conferma/Rifiuta)
    """
    utente = db.query(models.Utente).filter(models.Utente.whatsapp_numero == numero_whatsapp).first()
    if utente is None:
        raise ValueError(f"Nessun utente trovato con il numero {numero_whatsapp}")

    membro = (
        db.query(models.GruppoMembro)
        .join(models.Gruppo, models.Gruppo.id == models.GruppoMembro.gruppo_id)
        .filter(
            models.GruppoMembro.utente_id == utente.id,
            models.GruppoMembro.stato_conferma == "IN_ATTESA",
            models.Gruppo.stato == "PROPOSTO",
        )
        .order_by(models.Gruppo.data_proposta.desc())
        .first()
    )
    if membro is None:
        raise ValueError(f"Nessuna proposta in attesa di risposta trovata per {numero_whatsapp}")

    testo_normalizzato = testo_risposta.strip().lower()
    if "conferm" in testo_normalizzato:
        risposta = "CONFERMA"
    elif "rifiut" in testo_normalizzato:
        risposta = "RIFIUTO"
    else:
        raise ValueError(f"Risposta '{testo_risposta}' non riconosciuta (atteso Conferma o Rifiuta)")

    return rispondi_a_gruppo(db, membro.gruppo_id, membro.utente_id, risposta)
