"""
Il motore di matching (Step 02).
Va eseguito periodicamente (ogni INTERVALLO_BATCH_MINUTI, punto 10) e:
1. Legge tutte le richieste attive (stato IN_RICERCA)
2. Aggiorna la tolleranza di ciascuna in base al tempo di attesa
3. Cerca gruppi di 4 compatibili
4. Risolve i conflitti (un utente può comparire in più gruppi candidati)
   con la strategia greedy per punteggio (punto 10)
5. Per ogni gruppo finale, lo crea nel database con stato PROPOSTO,
   e blocca (LOCKED) le 4 richieste coinvolte
"""

from itertools import combinations
from datetime import datetime, timedelta
from types import SimpleNamespace
from sqlalchemy.orm import Session, joinedload

from app import models, config
from app.matching.compatibilita import (
    calcola_tolleranza, lato_compatibile, gruppo_livelli_compatibile,
    trova_slot_partita, conta_slot_consecutivi_massimi,
)
from app.matching.notifiche import notifica_proposta_gruppo


def aggiorna_tolleranze(db: Session, richieste: list):
    """Ricalcola la tolleranza corrente di ogni richiesta attiva (punto 12)."""
    adesso = datetime.utcnow()
    for r in richieste:
        r.tolleranza_corrente = calcola_tolleranza(r.data_creazione, adesso)
    db.flush()


def circoli_comuni(gruppo: list) -> list:
    """Restituisce i circoli scelti da TUTTI e 4 i giocatori del gruppo."""
    insiemi_circoli = [set(c.id for c in r.circoli) for r in gruppo]
    comuni = set.intersection(*insiemi_circoli) if insiemi_circoli else set()
    # restituiamo gli oggetti Circolo, non solo gli id
    if not comuni:
        return []
    return [c for c in gruppo[0].circoli if c.id in comuni]


def scegli_circolo(circoli_candidati: list, gruppo: list, db: Session) -> models.Circolo | None:
    """
    Sceglie il circolo tra quelli comuni a tutti e 4 i giocatori, bilanciando
    il carico: preferisce il circolo con MENO partite già attive (proposte,
    confermate o prenotate - non annullate) per quello stesso giorno, per
    non concentrare sempre tutto sullo stesso circolo quando ce n'è un
    altro ugualmente valido e più libero.
    In caso di parità anche nel conteggio, l'id numerico più basso fa da
    ultimo criterio, solo per restare deterministici (punto 20).
    """
    if not circoli_candidati:
        return None
    if len(circoli_candidati) == 1:
        return circoli_candidati[0]

    giorno = gruppo[0].giorno
    conteggio_per_circolo = {}
    for circolo in circoli_candidati:
        conteggio_per_circolo[circolo.id] = (
            db.query(models.Gruppo)
            .filter(
                models.Gruppo.circolo_id == circolo.id,
                models.Gruppo.giorno == giorno,
                models.Gruppo.stato != "ANNULLATO",
            )
            .count()
        )

    carico_minimo = min(conteggio_per_circolo.values())
    candidati_al_carico_minimo = [c for c in circoli_candidati if conteggio_per_circolo[c.id] == carico_minimo]

    return min(candidati_al_carico_minimo, key=lambda c: c.id)


def bitmask_intersezione(gruppo: list) -> int:
    """AND bit a bit tra le disponibilità di tutti e 4 (punto 9)."""
    risultato = gruppo[0].disponibilita_bitmask
    for r in gruppo[1:]:
        risultato &= r.disponibilita_bitmask
    return risultato


def calcola_punteggio(gruppo: list, slot_partita: int, circolo, adesso: datetime) -> float:
    """
    Punteggio di un gruppo candidato, usato per il greedy nella risoluzione
    conflitti (punto 10). Più alto = gruppo preferibile.
    """
    livelli = [float(r.utente.livello_playtomic) for r in gruppo]
    varianza_livello = sum((l - sum(livelli) / 4) ** 2 for l in livelli) / 4

    intersezione = bitmask_intersezione(gruppo)
    ampiezza_oraria = conta_slot_consecutivi_massimi(intersezione)

    attesa_media_minuti = sum(
        (adesso - r.data_creazione).total_seconds() / 60 for r in gruppo
    ) / 4

    punteggio = 0.0
    punteggio += 10.0 / (1 + varianza_livello)     # livelli simili = punteggio più alto
    punteggio += 0.5 * ampiezza_oraria              # più margine orario = meglio
    punteggio += 0.1 * attesa_media_minuti          # premia chi aspetta di più
    return punteggio


def trova_candidati_per_seed(seed, richieste_attive: list) -> list:
    """
    Primo filtro, economico: stesso giorno, stesso tipo partita,
    almeno un circolo in comune, esclude il seed stesso.
    """
    candidati = []
    circoli_seed = set(c.id for c in seed.circoli)

    for r in richieste_attive:
        if r.id == seed.id:
            continue
        if r.giorno != seed.giorno:
            continue
        if r.tipo_partita != seed.tipo_partita:
            continue
        if r.stato != "IN_RICERCA":
            continue
        circoli_r = set(c.id for c in r.circoli)
        if not (circoli_seed & circoli_r):
            continue
        candidati.append(r)

    return candidati


def genera_combinazioni_valide(seed, candidati: list, adesso: datetime, db: Session) -> list:
    """
    Prova tutte le combinazioni di 3 candidati (+ seed = gruppo di 4) e
    restituisce quelle valide, con punteggio, slot orario e circolo scelto.
    Corrisponde alla funzione GENERA_COMBINAZIONI_VALIDE dello pseudocodice.
    """
    gruppi_possibili = []

    for terna in combinations(candidati, 3):
        gruppo = [seed] + list(terna)

        # controllo più economico per primo (punto 11)
        if not lato_compatibile(gruppo):
            continue

        # controllo livello su ogni coppia (punto 12)
        if not gruppo_livelli_compatibile(gruppo):
            continue

        # controllo circolo comune a tutti e 4 (punto 20)
        comuni = circoli_comuni(gruppo)
        if not comuni:
            continue

        # controllo intersezione oraria valida per tutti e 4 (punto 9)
        intersezione = bitmask_intersezione(gruppo)
        slot_partita = trova_slot_partita(intersezione, config.DURATA_MINIMA_PARTITA_SLOT)
        if slot_partita is None:
            continue

        circolo_scelto = scegli_circolo(comuni, gruppo, db)
        punteggio = calcola_punteggio(gruppo, slot_partita, circolo_scelto, adesso)

        gruppi_possibili.append({
            "gruppo": gruppo,
            "slot_partita": slot_partita,
            "circolo": circolo_scelto,
            "punteggio": punteggio,
        })

    return gruppi_possibili


def risolvi_conflitti(gruppi_candidati: list) -> list:
    """
    Strategia greedy per punteggio (punto 10): ordina i gruppi candidati
    per punteggio decrescente, conferma il primo, scarta ogni gruppo
    successivo che contiene un utente già assegnato.
    """
    gruppi_ordinati = sorted(gruppi_candidati, key=lambda g: g["punteggio"], reverse=True)

    utenti_gia_assegnati = set()
    gruppi_finali = []

    for candidato in gruppi_ordinati:
        utenti_del_gruppo = {r.utente_id for r in candidato["gruppo"]}
        if utenti_del_gruppo & utenti_gia_assegnati:
            continue  # almeno uno di questi utenti è già in un altro gruppo migliore
        gruppi_finali.append(candidato)
        utenti_gia_assegnati |= utenti_del_gruppo

    return gruppi_finali


def crea_gruppo_nel_db(db: Session, candidato: dict) -> models.Gruppo:
    """
    Salva un gruppo confermato nel database: crea la riga in `gruppi`,
    le 4 righe in `gruppi_membri`, e blocca (LOCKED) le 4 richieste.
    """
    gruppo_dati = candidato["gruppo"]
    scadenza = datetime.utcnow() + timedelta(minutes=config.TIMEOUT_CONFERMA_MINUTI)

    nuovo_gruppo = models.Gruppo(
        circolo_id=candidato["circolo"].id,
        giorno=gruppo_dati[0].giorno,
        slot_inizio=candidato["slot_partita"],
        durata_slot=config.DURATA_MINIMA_PARTITA_SLOT,
        stato="PROPOSTO",
        scadenza_conferma=scadenza,
    )
    db.add(nuovo_gruppo)
    db.flush()  # per ottenere l'id del gruppo

    # assegnazione lato: semplice, assegna DX/SX rispettando le preferenze fisse
    # e riempendo con gli indifferenti (la logica esatta di assegnazione
    # verrà rifinita quando costruiremo il messaggio di proposta)
    lati_assegnati = _assegna_lati(gruppo_dati)

    for richiesta, lato in zip(gruppo_dati, lati_assegnati):
        db.add(models.GruppoMembro(
            gruppo_id=nuovo_gruppo.id,
            utente_id=richiesta.utente_id,
            richiesta_id=richiesta.id,
            lato_assegnato=lato,
            stato_conferma="IN_ATTESA",
        ))
        richiesta.stato = "LOCKED"

    db.flush()

    # Notifica ai 4 giocatori (Step 03) - costruiamo "membri finti" leggeri
    # a partire dai dati che abbiamo già in memoria, senza query aggiuntive
    membri_per_notifica = [
        SimpleNamespace(utente=richiesta.utente, lato_assegnato=lato)
        for richiesta, lato in zip(gruppo_dati, lati_assegnati)
    ]
    notifica_proposta_gruppo(nuovo_gruppo, membri_per_notifica, candidato["circolo"])

    return nuovo_gruppo


def _assegna_lati(gruppo: list) -> list:
    """Assegna DX/SX definitivi ai 4 giocatori, rispettando le preferenze fisse."""
    lati = [r.utente.lato_preferito for r in gruppo]
    n_dx = lati.count("DX")
    n_sx = lati.count("SX")

    risultato = list(lati)
    for i, lato in enumerate(risultato):
        if lato == "INDIFFERENTE":
            if n_dx < 2:
                risultato[i] = "DX"
                n_dx += 1
            else:
                risultato[i] = "SX"
    return risultato


def esegui_ciclo_matching(db: Session):
    """
    Funzione principale: un'esecuzione completa del motore di matching.
    Verrà chiamata dallo scheduler ogni INTERVALLO_BATCH_MINUTI.
    """
    adesso = datetime.utcnow()

    richieste_attive = (
        db.query(models.Richiesta)
        .options(joinedload(models.Richiesta.utente), joinedload(models.Richiesta.circoli))
        .filter(models.Richiesta.stato == "IN_RICERCA")
        .all()
    )

    if len(richieste_attive) < 4:
        return []  # non ha senso nemmeno provare

    aggiorna_tolleranze(db, richieste_attive)

    # ordiniamo per priorità: chi aspetta di più viene provato come "seed" per primo
    richieste_attive.sort(key=lambda r: r.data_creazione)

    tutti_i_gruppi_candidati = []
    utenti_gia_usati_come_seed = set()

    for seed in richieste_attive:
        if seed.id in utenti_gia_usati_come_seed:
            continue

        candidati = trova_candidati_per_seed(seed, richieste_attive)
        if len(candidati) < 3:
            continue

        gruppi_possibili = genera_combinazioni_valide(seed, candidati, adesso, db)
        tutti_i_gruppi_candidati.extend(gruppi_possibili)

    gruppi_finali = risolvi_conflitti(tutti_i_gruppi_candidati)

    gruppi_creati = []
    for candidato in gruppi_finali:
        nuovo_gruppo = crea_gruppo_nel_db(db, candidato)
        gruppi_creati.append(nuovo_gruppo)

    db.commit()
    return gruppi_creati
