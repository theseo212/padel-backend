"""
Algoritmo di formazione dei gruppi da 4 per un torneo. Funzioni pure,
senza alcuna dipendenza dal database: prendono una lista di candidati
già pronta e restituiscono i gruppi - così sono testabili in isolamento,
senza dover simulare un database per ogni scenario.

Criteri, in ordine di priorità (decisi con il cliente):
1. Cambiare il più possibile i compagni rispetto al torneo precedente
   dello stesso campionato (idealmente tutti e 3 diversi, altrimenti 2,
   altrimenti almeno 1).
2. Bilanciare per livello e lato di gioco - ma se questo confligge con
   il punto 1, si mescola pur di completare i quartetti (il cambio
   compagni viene prima).

Approccio: si parte da un raggruppamento "a fasce di livello" (ordinamento
per livello, chunk da 4), poi si migliora con una ricerca locale che
scambia coppie di giocatori tra gruppi diversi finché non si trova più
nessuno scambio che migliori la situazione. Per un circolo di padel
(tipicamente poche decine di giocatori per torneo) questo converge in
pochi millisecondi ed è più che sufficiente - non serve un ottimo
matematico assoluto, un buon risultato pratico sì.
"""

from dataclasses import dataclass, field


@dataclass
class Candidato:
    id: int
    livello: float
    lato: str  # "DX", "SX", "INDIFFERENTE"
    compagni_precedenti: set = field(default_factory=set)  # id degli utenti con cui ha giocato l'ultima volta


def _costo_gruppo(gruppo: list[Candidato]) -> tuple[int, float, int]:
    """
    Ritorna (numero_coppie_ripetute, ampiezza_livello, sbilanciamento_lato)
    per UN gruppo - più basso è meglio su tutte e tre le componenti,
    confrontate in quest'ordine di priorità.
    """
    ripetute = 0
    for i in range(len(gruppo)):
        for j in range(i + 1, len(gruppo)):
            if gruppo[j].id in gruppo[i].compagni_precedenti:
                ripetute += 1

    livelli = [c.livello for c in gruppo]
    ampiezza_livello = max(livelli) - min(livelli) if livelli else 0.0

    dx = sum(1 for c in gruppo if c.lato == "DX")
    sx = sum(1 for c in gruppo if c.lato == "SX")
    sbilanciamento_lato = abs(dx - sx)

    return (ripetute, ampiezza_livello, sbilanciamento_lato)


def _costo_totale(gruppi: list[list[Candidato]]) -> tuple[int, float, int]:
    """Somma dei costi dei singoli gruppi - stessa struttura (ripetute, ampiezza, sbilanciamento)."""
    ripetute_tot, ampiezza_tot, sbilanciamento_tot = 0, 0.0, 0
    for gruppo in gruppi:
        r, a, s = _costo_gruppo(gruppo)
        ripetute_tot += r
        ampiezza_tot += a
        sbilanciamento_tot += s
    return (ripetute_tot, ampiezza_tot, sbilanciamento_tot)


import random


def forma_gruppi(candidati: list[Candidato], max_passate: int = 30, tentativi: int = 25) -> list[list[Candidato]]:
    """
    candidati: lista di Candidato, con lunghezza multipla di 4 (il
    chiamante deve già aver tolto le riserve prima di chiamare questa
    funzione).

    Ritorna una lista di gruppi da 4 candidati ciascuno.

    Usa più tentativi con punti di partenza diversi (uno ordinato per
    livello, gli altri mescolati casualmente) e tiene il risultato
    migliore: una singola ricerca locale può restare bloccata in un
    "ottimo locale" (una soluzione discreta ma non la migliore possibile)
    - i riavvii multipli sono il modo classico per uscirne, mantenendo i
    tempi di calcolo comunque bassissimi per i numeri in gioco in un
    circolo di padel.
    """
    if len(candidati) % 4 != 0:
        raise ValueError(f"Il numero di candidati deve essere multiplo di 4, ricevuti {len(candidati)}")
    if len(candidati) == 0:
        return []

    generatore_casuale = random.Random(12345)  # seed fisso: risultato riproducibile a parità di input

    ordini_di_partenza = [sorted(candidati, key=lambda c: c.livello)]
    for _ in range(tentativi - 1):
        mescolato = list(candidati)
        generatore_casuale.shuffle(mescolato)
        ordini_di_partenza.append(mescolato)

    migliore_gruppi = None
    migliore_costo = None

    for ordine in ordini_di_partenza:
        gruppi = [list(ordine[i:i + 4]) for i in range(0, len(ordine), 4)]

        for _ in range(max_passate):
            migliorato = False
            for gi in range(len(gruppi)):
                for gj in range(gi + 1, len(gruppi)):
                    for pi in range(4):
                        for pj in range(4):
                            costo_prima = _costo_totale(gruppi)

                            gruppi[gi][pi], gruppi[gj][pj] = gruppi[gj][pj], gruppi[gi][pi]
                            costo_dopo = _costo_totale(gruppi)

                            if costo_dopo < costo_prima:
                                migliorato = True
                            else:
                                gruppi[gi][pi], gruppi[gj][pj] = gruppi[gj][pj], gruppi[gi][pi]
            if not migliorato:
                break

        costo_finale = _costo_totale(gruppi)
        if migliore_costo is None or costo_finale < migliore_costo:
            migliore_costo = costo_finale
            migliore_gruppi = [list(g) for g in gruppi]

    return migliore_gruppi


def assegna_lati(gruppo: list[Candidato]) -> dict[int, str]:
    """
    Assegna DX/SX ai 4 membri di un gruppo, puntando a 2 e 2. Le
    preferenze esplicite (DX/SX) hanno priorità; INDIFFERENTE riempie
    gli spazi rimasti; in caso di reale conflitto (es. 3 persone su 4
    vogliono DX) qualcuno gioca comunque fuori dalla propria preferenza -
    non c'è alternativa possibile in quel caso.
    """
    assegnazione: dict[int, str] = {}
    slot_liberi = {"DX": 2, "SX": 2}

    # 1. Prima le preferenze esplicite, finché ci sono slot
    for candidato in gruppo:
        if candidato.lato in ("DX", "SX") and slot_liberi[candidato.lato] > 0:
            assegnazione[candidato.id] = candidato.lato
            slot_liberi[candidato.lato] -= 1

    # 2. Poi gli INDIFFERENTI, verso il lato che ha ancora spazio
    for candidato in gruppo:
        if candidato.id in assegnazione:
            continue
        if candidato.lato == "INDIFFERENTE":
            lato_scelto = "DX" if slot_liberi["DX"] >= slot_liberi["SX"] else "SX"
            if slot_liberi[lato_scelto] == 0:
                lato_scelto = "SX" if lato_scelto == "DX" else "DX"
            assegnazione[candidato.id] = lato_scelto
            slot_liberi[lato_scelto] -= 1

    # 3. Chi resta (preferenza esplicita ma senza più slot sul suo lato)
    #    viene piazzato dove c'è ancora posto, fuori dalla sua preferenza.
    for candidato in gruppo:
        if candidato.id in assegnazione:
            continue
        lato_scelto = "DX" if slot_liberi["DX"] > 0 else "SX"
        assegnazione[candidato.id] = lato_scelto
        slot_liberi[lato_scelto] -= 1

    return assegnazione
