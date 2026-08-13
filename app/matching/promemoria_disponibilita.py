"""
Finezza aggiuntiva: se un'ora prima dell'inizio della fascia oraria
richiesta il sistema non ha ancora trovato compagni, avvisa l'utente
che la ricerca continua, invece di lasciarlo nel silenzio totale.

Non scatta se la richiesta è stata inserita meno di un'ora prima
dell'inizio della fascia (non ci sarebbe comunque tempo per un preavviso
utile), e scatta una sola volta per richiesta.
"""

from datetime import datetime, timedelta, time
from sqlalchemy.orm import Session, joinedload

from app import models, config
from app.services.whatsapp import invia_promemoria_mancata_partita
from app.services.bitmask import bitmask_a_fasce_leggibili


def _primo_slot_disponibile(bitmask: int) -> int | None:
    """Restituisce l'indice del primo slot acceso nel bitmask, o None se vuoto."""
    for i in range(config.NUM_SLOT_TOTALI):
        if bitmask & (1 << i):
            return i
    return None


def _inizio_finestra_disponibilita(richiesta: models.Richiesta) -> datetime | None:
    """Calcola l'orario (data+ora) di inizio della fascia richiesta dall'utente."""
    primo_slot = _primo_slot_disponibile(richiesta.disponibilita_bitmask)
    if primo_slot is None:
        return None
    minuti_da_mezzanotte = config.ORA_INIZIO_GIORNATA * 60 + primo_slot * config.DURATA_SLOT_MINUTI
    return datetime.combine(richiesta.giorno, time()) + timedelta(minutes=minuti_da_mezzanotte)


def controlla_promemoria_mancata_partita(db: Session, adesso: datetime | None = None):
    """
    Da eseguire periodicamente: per ogni richiesta ancora IN_RICERCA,
    controlla se è il momento di avvisare l'utente che manca un'ora
    all'inizio della sua fascia oraria e non è stata ancora trovata
    una partita.

    Il parametro "adesso" è opzionale (di default usa l'ora corrente reale)
    ed esiste principalmente per poter scrivere test deterministici, senza
    dipendere dall'orario reale in cui gira il test.
    """
    if adesso is None:
        adesso = datetime.utcnow()

    richieste = (
        db.query(models.Richiesta)
        .options(joinedload(models.Richiesta.utente))
        .filter(
            models.Richiesta.stato == "IN_RICERCA",
            models.Richiesta.promemoria_mancata_partita_inviato == False,
        )
        .all()
    )

    inviati = 0
    for richiesta in richieste:
        inizio_finestra = _inizio_finestra_disponibilita(richiesta)
        if inizio_finestra is None:
            continue

        soglia_avviso = inizio_finestra - timedelta(hours=1)

        # Caso 3 (concordato): richiesta inserita troppo vicina all'inizio
        # della finestra, il preavviso non avrebbe senso - non si manda,
        # ma si segna comunque come "gestita" per non ricontrollarla ad ogni ciclo
        if richiesta.data_creazione > soglia_avviso:
            richiesta.promemoria_mancata_partita_inviato = True
            continue

        # La finestra è già iniziata: il preavviso "manca un'ora" non ha più senso
        if adesso >= inizio_finestra:
            richiesta.promemoria_mancata_partita_inviato = True
            continue

        # È il momento giusto per avvisare
        if adesso >= soglia_avviso:
            fascia_leggibile = ", ".join(bitmask_a_fasce_leggibili(richiesta.disponibilita_bitmask))
            testo = (
                f"Ciao {richiesta.utente.nome}, sono Anna! Manca un'ora all'inizio della tua finestra "
                f"di disponibilità per il {richiesta.giorno} ({fascia_leggibile}) e non ho ancora trovato "
                f"una partita con le caratteristiche che mi hai chiesto, ma continuerò a cercare "
                f"automaticamente.\n\n"
                f"Se vuoi, puoi annullare la richiesta o inserirne una nuova dai pulsanti qui sotto."
            )
            invia_promemoria_mancata_partita(
                richiesta.utente.whatsapp_numero, testo,
                nome=richiesta.utente.nome, giorno=str(richiesta.giorno),
                fascia_oraria=fascia_leggibile, id_richiesta=str(richiesta.id),
            )
            richiesta.promemoria_mancata_partita_inviato = True
            inviati += 1

    db.commit()
    return inviati
