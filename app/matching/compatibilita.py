"""
Le funzioni di compatibilità di base tra giocatori.
Ognuna corrisponde a una regola che abbiamo fissato nelle specifiche
(vedi documento di riferimento, punti 9, 11, 12, 20).

Ogni funzione riceve un "gruppo" = lista di 4 oggetti Richiesta
(con il relativo utente collegato), e risponde vero/falso o un valore.
"""

from app.config import (
    SOGLIE_TEMPO_MINUTI, VALORI_TOLLERANZA, NUM_SLOT_TOTALI, DURATA_MINIMA_PARTITA_SLOT
)
from datetime import datetime


def calcola_tolleranza(data_creazione_richiesta: datetime, adesso: datetime = None) -> float:
    """
    Calcola la tolleranza di livello attuale di una richiesta, in base a
    quanto tempo è passato dalla sua creazione (punto 12 - funzione a gradini).
    """
    if adesso is None:
        adesso = datetime.utcnow()

    minuti_attesa = (adesso - data_creazione_richiesta).total_seconds() / 60

    tolleranza = VALORI_TOLLERANZA[0]  # valore di partenza (0.5)
    for soglia, valore in zip(SOGLIE_TEMPO_MINUTI, VALORI_TOLLERANZA[1:]):
        if minuti_attesa >= soglia:
            tolleranza = valore
    return tolleranza


def lato_compatibile(gruppo: list) -> bool:
    """
    Verifica che 4 giocatori possano disporsi 2 a destra + 2 a sinistra
    (punto 11). gruppo = lista di 4 Richiesta (ognuna collegata a un Utente).
    """
    lati = [r.utente.lato_preferito for r in gruppo]
    n_dx = lati.count("DX")
    n_sx = lati.count("SX")
    n_ind = lati.count("INDIFFERENTE")

    return (n_dx <= 2) and (n_sx <= 2) and (n_dx + n_ind >= 2) and (n_sx + n_ind >= 2)


def livelli_compatibili(richiesta_a, richiesta_b) -> bool:
    """
    Verifica che due giocatori siano compatibili per livello, usando
    sempre la tolleranza PIÙ STRETTA tra le due (punto 12).
    """
    tolleranza_effettiva = min(richiesta_a.tolleranza_corrente, richiesta_b.tolleranza_corrente)
    differenza = abs(float(richiesta_a.utente.livello_playtomic) - float(richiesta_b.utente.livello_playtomic))
    return differenza <= float(tolleranza_effettiva)


def gruppo_livelli_compatibile(gruppo: list) -> bool:
    """
    Verifica la compatibilità di livello su OGNI coppia del gruppo di 4,
    non solo rispetto al seed (altrimenti due candidati compatibili col
    seed ma non tra loro finirebbero comunque nello stesso gruppo).
    """
    for i in range(len(gruppo)):
        for j in range(i + 1, len(gruppo)):
            if not livelli_compatibili(gruppo[i], gruppo[j]):
                return False
    return True


def trova_slot_partita(intersezione_bitmask: int, durata_slot_richiesta: int = DURATA_MINIMA_PARTITA_SLOT):
    """
    Cerca all'interno di un bitmask di intersezione una sequenza di bit
    consecutivi accesi lunga almeno "durata_slot_richiesta" (punto 9).
    Restituisce l'indice di inizio della sequenza più CENTRALE trovata
    (punto 5 dello step 02: preferiamo lo slot più centrale, per avere
    margine di manovra in caso di retry allo Step 04), oppure None se non
    esiste nessuna sequenza abbastanza lunga.
    """
    sequenze_trovate = []
    contatore_consecutivi = 0
    inizio_sequenza_corrente = None

    for i in range(NUM_SLOT_TOTALI + 1):  # +1 per chiudere una sequenza che arriva fino in fondo
        acceso = i < NUM_SLOT_TOTALI and bool(intersezione_bitmask & (1 << i))

        if acceso:
            if inizio_sequenza_corrente is None:
                inizio_sequenza_corrente = i
            contatore_consecutivi += 1
        else:
            if contatore_consecutivi >= durata_slot_richiesta:
                sequenze_trovate.append((inizio_sequenza_corrente, contatore_consecutivi))
            contatore_consecutivi = 0
            inizio_sequenza_corrente = None

    if not sequenze_trovate:
        return None

    # Tra tutte le sequenze abbastanza lunghe, scegliamo lo slot di inizio
    # più centrale possibile all'interno della sequenza più ampia disponibile
    migliore_inizio, migliore_lunghezza = max(sequenze_trovate, key=lambda s: s[1])
    centro_offset = (migliore_lunghezza - durata_slot_richiesta) // 2
    return migliore_inizio + centro_offset


def conta_slot_consecutivi_massimi(bitmask: int) -> int:
    """Utile per scegli_circolo: quanti slot consecutivi accesi ci sono al massimo."""
    massimo = 0
    corrente = 0
    for i in range(NUM_SLOT_TOTALI):
        if bitmask & (1 << i):
            corrente += 1
            massimo = max(massimo, corrente)
        else:
            corrente = 0
    return massimo
