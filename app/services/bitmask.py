"""
Gestisce la conversione tra "fasce orarie leggibili" (es. dalle 18:00 alle 21:00)
e il bitmask (un numero che rappresenta quali "slot" da 30 minuti sono occupati).

Perché serve: lo abbiamo deciso nel punto 9 delle specifiche.
Con il bitmask, verificare se 4 persone hanno un orario in comune diventa
una semplice operazione binaria (AND), invece di confrontare intervalli
uno per uno con tutti i casi particolari che questo comporta.
"""

from app.config import ORA_INIZIO_GIORNATA, ORA_FINE_GIORNATA, DURATA_SLOT_MINUTI, NUM_SLOT_TOTALI


def _orario_a_indice_slot(orario: str) -> int:
    """
    Converte un orario tipo "18:30" nell'indice dello slot corrispondente.
    Esempio: con giornata che parte alle 07:00 e slot da 30 minuti,
    "07:00" -> slot 0, "07:30" -> slot 1, "18:00" -> slot 22, ecc.
    """
    ore, minuti = orario.split(":")
    ore, minuti = int(ore), int(minuti)

    if minuti not in (0, 30):
        raise ValueError(f"L'orario {orario} deve essere in punto o e mezza (es. 18:00 o 18:30)")

    minuti_da_inizio_giornata = (ore - ORA_INIZIO_GIORNATA) * 60 + minuti
    indice = minuti_da_inizio_giornata // DURATA_SLOT_MINUTI

    if indice < 0 or indice > NUM_SLOT_TOTALI:
        raise ValueError(
            f"L'orario {orario} è fuori dalla fascia gestita dal sistema "
            f"({ORA_INIZIO_GIORNATA}:00 - {ORA_FINE_GIORNATA}:00)"
        )
    return indice


def crea_bitmask(fasce_orarie: list[tuple[str, str]]) -> int:
    """
    Riceve una lista di fasce orarie, es: [("18:00", "21:00"), ("07:30", "09:00")]
    e restituisce un unico numero (bitmask) che rappresenta tutti gli slot occupati.
    """
    bitmask = 0

    for orario_inizio, orario_fine in fasce_orarie:
        indice_inizio = _orario_a_indice_slot(orario_inizio)
        indice_fine = _orario_a_indice_slot(orario_fine)

        if indice_fine <= indice_inizio:
            raise ValueError(
                f"La fascia {orario_inizio}-{orario_fine} non è valida: "
                f"l'orario di fine deve essere dopo quello di inizio"
            )

        for i in range(indice_inizio, indice_fine):
            bitmask |= (1 << i)   # "accende" il bit corrispondente allo slot i

    return bitmask


def bitmask_a_fasce_leggibili(bitmask: int) -> list[str]:
    """
    Funzione inversa, utile per mostrare all'utente (es. nei messaggi WhatsApp)
    a che ore corrisponde un bitmask, in modo leggibile.
    Esempio: bitmask con slot 22,23,24 accesi -> ["18:00-19:30"]
    """
    orari = []
    for i in range(NUM_SLOT_TOTALI + 1):  # +1: serve anche il confine finale dell'ultimo slot
        minuti_totali = ORA_INIZIO_GIORNATA * 60 + i * DURATA_SLOT_MINUTI
        ore, minuti = divmod(minuti_totali, 60)
        orari.append(f"{ore:02d}:{minuti:02d}")

    fasce = []
    inizio_corrente = None

    for i in range(NUM_SLOT_TOTALI):
        acceso = bool(bitmask & (1 << i))
        if acceso and inizio_corrente is None:
            inizio_corrente = i
        if not acceso and inizio_corrente is not None:
            fasce.append(f"{orari[inizio_corrente]}-{orari[i]}")
            inizio_corrente = None

    if inizio_corrente is not None:
        fasce.append(f"{orari[inizio_corrente]}-{orari[NUM_SLOT_TOTALI]}")

    return fasce
