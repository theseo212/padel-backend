"""
Step 04 (parte "prenotazione"): gestisce cosa succede a un gruppo che è
passato allo stato CONFERMATO (tutti e 4 hanno confermato la partita).

Per l'MVP, la prenotazione vera e propria sul circolo è fatta da un
operatore umano (punto 15): questo modulo espone la funzione che
l'operatore chiama per dire "campo disponibile" o "campo non disponibile",
e gestisce le conseguenze in entrambi i casi.
"""

from datetime import datetime
from sqlalchemy.orm import Session, joinedload

from app import models
from app.services.whatsapp import invia_prenotazione_confermata, invia_prenotazione_fallita


def _carica_gruppo_completo(db: Session, gruppo_id: int):
    return (
        db.query(models.Gruppo)
        .options(joinedload(models.Gruppo.membri).joinedload(models.GruppoMembro.utente))
        .filter(models.Gruppo.id == gruppo_id)
        .first()
    )


def _orario_leggibile(slot_inizio: int) -> str:
    from app.config import ORA_INIZIO_GIORNATA, DURATA_SLOT_MINUTI
    minuti_totali = ORA_INIZIO_GIORNATA * 60 + slot_inizio * DURATA_SLOT_MINUTI
    ore, minuti = divmod(minuti_totali, 60)
    return f"{ore:02d}:{minuti:02d}"


def conferma_prenotazione(db: Session, gruppo_id: int) -> models.Partita:
    """
    Chiamata dall'operatore (o in futuro da un'integrazione automatica)
    quando il campo RISULTA DISPONIBILE. Crea la partita nel database,
    passa le richieste allo stato finale CONFERMATA, e avvisa i 4 giocatori
    (incluso il promemoria sul pagamento al circolo, punto 16).
    """
    gruppo = _carica_gruppo_completo(db, gruppo_id)
    if gruppo is None:
        raise ValueError("Gruppo non trovato")
    if gruppo.stato != "CONFERMATO":
        raise ValueError(f"Il gruppo non è nello stato giusto per essere prenotato (stato: {gruppo.stato})")

    circolo = db.query(models.Circolo).filter(models.Circolo.id == gruppo.circolo_id).first()
    orario = _orario_leggibile(gruppo.slot_inizio)

    partita = models.Partita(
        gruppo_id=gruppo.id,
        circolo_id=gruppo.circolo_id,
        giorno=gruppo.giorno,
        ora_inizio=orario,
        stato="PRENOTATA",
    )
    db.add(partita)

    gruppo.stato = "PRENOTATO"

    for membro in gruppo.membri:
        richiesta = db.query(models.Richiesta).filter(models.Richiesta.id == membro.richiesta_id).first()
        richiesta.stato = "CONFERMATA"

    testo = (
        f"✅ Fatto! Ho confermato la prenotazione!\n"
        f"Circolo: {circolo.nome}\n"
        f"Giorno: {gruppo.giorno} alle {orario}\n"
        f"Il pagamento del campo si effettua direttamente al circolo all'arrivo, come di consueto.\n"
        f"Buona partita! ߎ"
    )
    for membro in gruppo.membri:
        invia_prenotazione_confermata(
            membro.utente.whatsapp_numero, testo,
            circolo=circolo.nome, giorno=str(gruppo.giorno), orario=orario,
        )

    db.commit()
    db.refresh(partita)
    return partita


def fallisce_prenotazione(db: Session, gruppo_id: int):
    """
    Chiamata dall'operatore quando il campo RISULTA NON DISPONIBILE.
    Nessuna colpa dei giocatori: tornano tutti in ricerca, senza penalità.

    Per evitare un loop infinito in cui il sistema ripropone sempre lo
    stesso circolo (che non ha disponibilità), rimuoviamo quello specifico
    circolo dalle preferenze di ciascuna richiesta coinvolta, a meno che
    non fosse l'unico circolo scelto (in quel caso lo lasciamo, altrimenti
    la richiesta non avrebbe più nessun circolo su cui cercare).
    """
    gruppo = _carica_gruppo_completo(db, gruppo_id)
    if gruppo is None:
        raise ValueError("Gruppo non trovato")
    if gruppo.stato != "CONFERMATO":
        raise ValueError(f"Il gruppo non è nello stato giusto (stato: {gruppo.stato})")

    circolo = db.query(models.Circolo).filter(models.Circolo.id == gruppo.circolo_id).first()
    gruppo.stato = "ANNULLATO"

    for membro in gruppo.membri:
        richiesta = db.query(models.Richiesta).filter(models.Richiesta.id == membro.richiesta_id).first()
        richiesta.stato = "IN_RICERCA"

        if len(richiesta.circoli) > 1:
            richiesta.circoli = [c for c in richiesta.circoli if c.id != gruppo.circolo_id]

    testo = (
        f"❌ Partita annullata: il campo al circolo {circolo.nome} "
        f"non è risultato disponibile. Sto cercando una nuova soluzione per te."
    )
    for membro in gruppo.membri:
        invia_prenotazione_fallita(membro.utente.whatsapp_numero, testo, circolo=circolo.nome)

    db.commit()
