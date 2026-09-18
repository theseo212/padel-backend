"""
Bitmask per il tipo di partita (punto 21): stesso principio già usato per
le fasce orarie, applicato alla scelta MASCHILE/FEMMINILE/MISTA. Un
utente può accettarne più di uno (es. "MASCHILE o MISTA"), e due
richieste sono compatibili se hanno ALMENO UN tipo in comune, non se
coincidono esattamente.
"""

TIPO_MASCHILE = 1
TIPO_FEMMINILE = 2
TIPO_MISTA = 4

_VALORE_PER_NOME = {"MASCHILE": TIPO_MASCHILE, "FEMMINILE": TIPO_FEMMINILE, "MISTA": TIPO_MISTA}
_NOME_PER_VALORE = {v: k for k, v in _VALORE_PER_NOME.items()}
_LEGGIBILE_PER_NOME = {"MASCHILE": "Maschile", "FEMMINILE": "Femminile", "MISTA": "Mista"}

# Ordine di priorità per scegliere UN tipo solo quando un gruppo si forma
# (l'intersezione tra i 4 membri può contenere più di un tipo in comune,
# ma il messaggio finale al circolo/giocatori ne cita uno solo).
_PRIORITA_SCELTA = ["MISTA", "MASCHILE", "FEMMINILE"]


def crea_bitmask_tipo(lista_tipi: list[str]) -> int:
    """Converte una lista di nomi (es. ['MASCHILE', 'MISTA']) in bitmask."""
    bitmask = 0
    for nome in lista_tipi:
        bitmask |= _VALORE_PER_NOME[nome]
    return bitmask


def bitmask_tipo_a_lista(bitmask: int) -> list[str]:
    """Converte un bitmask nell'elenco dei nomi che contiene, es. ['MASCHILE', 'MISTA']."""
    return [nome for valore, nome in _NOME_PER_VALORE.items() if bitmask & valore]


def bitmask_tipo_a_stringa_leggibile(bitmask: int) -> str:
    """Es. 'Maschile' se un solo tipo, 'Maschile o Mista' se più di uno."""
    lista = bitmask_tipo_a_lista(bitmask)
    return " o ".join(_LEGGIBILE_PER_NOME[nome] for nome in lista)


def scegli_tipo_singolo(bitmask_intersezione: int) -> str:
    """
    Quando un gruppo di 4 si forma, l'intersezione dei loro tipi accettati
    può contenere più di un'opzione in comune - qui ne scegliamo UNA sola
    (con una priorità fissa, solo per essere deterministici) per il
    messaggio finale e per la riga salvata sul gruppo.
    """
    tipi_in_comune = bitmask_tipo_a_lista(bitmask_intersezione)
    for candidato in _PRIORITA_SCELTA:
        if candidato in tipi_in_comune:
            return candidato
    return tipi_in_comune[0]  # non dovrebbe mai succedere, ma per sicurezza
