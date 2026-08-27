"""
Costruisce il testo dei messaggi WhatsApp legati a un gruppo (Step 03)
e li invia a ciascuno dei 4 giocatori coinvolti.
"""

import secrets
from datetime import datetime
from app import config, models
from app.config import ORA_INIZIO_GIORNATA, DURATA_SLOT_MINUTI
from app.services.bitmask import bitmask_a_fasce_leggibili
from app.services.whatsapp import (
    invia_proposta_gruppo, invia_annullamento_gruppo, invia_gruppo_confermato,
    invia_notifica_operatore, invia_richiesta_prenotazione_circolo,
)


def slot_a_orario(slot_inizio: int) -> str:
    """Converte l'indice di uno slot bitmask nell'orario leggibile, es. 23 -> '18:30'."""
    minuti_totali = ORA_INIZIO_GIORNATA * 60 + slot_inizio * DURATA_SLOT_MINUTI
    ore, minuti = divmod(minuti_totali, 60)
    return f"{ore:02d}:{minuti:02d}"


def notifica_proposta_gruppo(gruppo, membri, circolo):
    """
    Invia a ognuno dei 4 membri il messaggio di proposta con i nomi di tutti,
    il circolo, l'orario, e richiede conferma entro TIMEOUT_CONFERMA_MINUTI
    (punto 13) - letto dalla configurazione, non scritto a mano, così
    cambiando quella variabile su Railway il testo resta sempre coerente
    col vero limite di tempo (il messaggio VERO che arriva agli utenti
    segue comunque il testo fisso del template su Meta, che va comunque
    aggiornato a parte - questo testo qui serve solo come riserva, per il
    caso in cui l'invio tramite template dovesse fallire).
    """
    orario = slot_a_orario(gruppo.slot_inizio)
    # Solo iniziale del cognome, non per intero: la segreteria (nell'altro
    # messaggio) ha bisogno dell'identità completa per contattare/prenotare,
    # ma tra i 4 giocatori stessi basta riconoscersi a grandi linee, non
    # serve l'identità completa di 3 sconosciuti prima ancora di confermare.
    nomi = ", ".join(
        f"{m.utente.nome} {m.utente.cognome[0]}. ({m.lato_assegnato})" if m.utente.cognome
        else f"{m.utente.nome} ({m.lato_assegnato})"
        for m in membri
    )

    testo = (
        f"✅ Ho trovato dei compagni per te!\n"
        f"Circolo: {circolo.nome}\n"
        f"Giorno: {gruppo.giorno} alle {orario}\n"
        f"Giocatori: {nomi}\n\n"
        f"Confermi entro {config.TIMEOUT_CONFERMA_MINUTI} minuti? [CONFERMA] [RIFIUTA]"
    )

    for membro in membri:
        invia_proposta_gruppo(
            membro.utente.whatsapp_numero, testo,
            circolo=circolo.nome, giorno=str(gruppo.giorno), orario=orario, giocatori=nomi,
        )


def notifica_annullamento_gruppo(membri, motivo: str):
    """Invia a tutti e 4 il messaggio di annullamento partita (Step 04)."""
    for membro in membri:
        invia_annullamento_gruppo(membro.utente.whatsapp_numero, motivo)


def notifica_gruppo_confermato(membri, gruppo, circolo, db):
    """Invia il messaggio quando tutti e 4 hanno confermato (in attesa della prenotazione)."""
    orario = slot_a_orario(gruppo.slot_inizio)
    testo = (
        f"✅ Tutti hanno confermato!\n"
        f"Circolo: {circolo.nome}\n"
        f"Giorno: {gruppo.giorno} alle {orario}\n"
        f"Sto procedendo con la prenotazione del campo, ti aggiorno a breve con la conferma definitiva."
    )
    for membro in membri:
        invia_gruppo_confermato(
            membro.utente.whatsapp_numero, testo,
            circolo=circolo.nome, giorno=str(gruppo.giorno), orario=orario,
        )

    # Genera un codice casuale (non indovinabile) per il link privato di
    # conferma prenotazione, e registra l'orario esatto in cui la
    # richiesta viene inviata - serve al pannello per mostrare quanto
    # stanno tardando i circoli a rispondere.
    codice = secrets.token_urlsafe(6)
    gruppo.codice_conferma_circolo = codice
    gruppo.data_richiesta_prenotazione = datetime.utcnow()
    db.commit()

    token_conferma = f"{gruppo.id}.{codice}"
    # WhatsApp vieta i ritorni a capo DENTRO una singola variabile (anche
    # se il JSON è valido) - quindi separiamo i 4 giocatori con " - "
    # invece di un vero a capo, restando su un'unica variabile (evitiamo
    # così di dover cambiare la struttura del template già approvato).
    # Recuperiamo per ciascuno anche la fascia oraria dichiarata nella sua
    # richiesta originale, utile alla segreteria per un eventuale piccolo
    # spostamento d'orario (sanno subito chi ha più margine).
    pezzi_giocatori = []
    for m in membri:
        richiesta = db.query(models.Richiesta).filter(models.Richiesta.id == m.richiesta_id).first()
        fascia = ", ".join(bitmask_a_fasce_leggibili(richiesta.disponibilita_bitmask)) if richiesta else "?"
        pezzi_giocatori.append(
            f"{m.utente.nome} {m.utente.cognome}: {m.utente.whatsapp_numero} (disp. {fascia})"
        )
    elenco_giocatori = " - ".join(pezzi_giocatori)
    testo_prenotazione = (
        f"‼️ Nuovo gruppo pronto per la prenotazione!\n"
        f"Circolo: {circolo.nome}\n"
        f"Giorno: {gruppo.giorno} alle {orario}\n"
        f"Giocatori: {elenco_giocatori}\n"
        f"Clicca qui sotto per confermare la prenotazione (o segnalare che il campo non è disponibile)."
    )

    # Lo stesso identico messaggio va sia al circolo sia all'operatore:
    # chi conferma per primo (il circolo dalla sua pagina, o l'operatore
    # dal pannello) fa scomparire la riga per l'altro, senza conflitti.
    destinatari = []
    if circolo.telefono:
        destinatari.append(circolo.telefono)
    destinatari.extend(config.ADMIN_WHATSAPP_NUMERI)

    for numero in destinatari:
        invia_richiesta_prenotazione_circolo(
            numero, testo_prenotazione,
            circolo=circolo.nome, giorno=str(gruppo.giorno), orario=orario,
            giocatori=elenco_giocatori, token_conferma=token_conferma,
        )
