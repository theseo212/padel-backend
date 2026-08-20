"""
Gestisce il flusso "richiesta via messaggio vocale" (solo per utenti già
verificati): crea una bozza in attesa di conferma quando arriva un
vocale interpretabile, la trasforma in una vera Richiesta quando l'utente
conferma, e la lascia scadere da sola se non risponde in tempo.
"""

from datetime import datetime, timedelta
from sqlalchemy.orm import Session, joinedload

from app import models, config
from app.services.bitmask import crea_bitmask, bitmask_a_fasce_leggibili
from app.services.trascrizione_vocale import trascrivi_e_interpreta_vocale
from app.services.whatsapp import (
    invia_messaggio_richiesta_vocale, invia_conferma_bozza_vocale, invia_link_modifica_preferenze_vocale,
)

_LATO_LEGGIBILE = {"DX": "Destra", "SX": "Sinistra", "INDIFFERENTE": "Indifferente"}


def gestisci_richiesta_vocale(db: Session, numero_whatsapp: str, media_url: str):
    """
    Punto d'ingresso quando arriva un vocale da un numero già verificato:
    trascrive, interpreta, e - se riesce a capire giorno/orario - crea
    una bozza in attesa di conferma e manda il riepilogo.
    """
    utente = (
        db.query(models.Utente)
        .filter(models.Utente.whatsapp_numero == numero_whatsapp, models.Utente.whatsapp_validato == True)
        .first()
    )
    if utente is None:
        # Non è un numero già verificato: questa funzione è pensata solo
        # per chi ha già completato almeno una richiesta dal form.
        return

    ultima_richiesta = (
        db.query(models.Richiesta)
        .options(joinedload(models.Richiesta.circoli))
        .filter(models.Richiesta.utente_id == utente.id)
        .order_by(models.Richiesta.data_creazione.desc())
        .first()
    )
    if ultima_richiesta is None:
        invia_messaggio_richiesta_vocale(
            numero_whatsapp,
            "Per usare le richieste vocali serve aver già fatto almeno una richiesta dal sito, "
            "così posso riutilizzare le tue preferenze abituali (tipo partita, circoli). "
            "La prima volta, usa il form sul sito!"
        )
        return

    risultato = trascrivi_e_interpreta_vocale(media_url)
    if risultato is None:
        invia_messaggio_richiesta_vocale(
            numero_whatsapp,
            "Non sono riuscita a capire bene il giorno e l'orario dal tuo vocale 😅 "
            "Puoi riprovare parlando più chiaramente (es. \"voglio giocare sabato dalle 9 alle 13\"), "
            "oppure usa il form sul sito."
        )
        return

    tipo_partita = ultima_richiesta.tipo_partita
    circoli = ultima_richiesta.circoli
    circoli_ids_csv = ",".join(str(c.id) for c in circoli)
    nomi_circoli = ", ".join(c.nome for c in circoli)

    bitmask = crea_bitmask([(risultato["ora_inizio"], risultato["ora_fine"])])

    # Elimina eventuali bozze precedenti ancora in sospeso per questo
    # utente (es. manda un secondo vocale prima di confermare il primo).
    db.query(models.BozzaRichiestaVocale).filter(models.BozzaRichiestaVocale.utente_id == utente.id).delete()

    bozza = models.BozzaRichiestaVocale(
        utente_id=utente.id,
        giorno=risultato["giorno"],
        disponibilita_bitmask=bitmask,
        tipo_partita=tipo_partita,
        circoli_ids_csv=circoli_ids_csv,
    )
    db.add(bozza)
    db.commit()

    fascia_leggibile = ", ".join(bitmask_a_fasce_leggibili(bitmask))
    lato_leggibile = _LATO_LEGGIBILE.get(utente.lato_preferito, utente.lato_preferito)

    testo = (
        f"Ho capito questo dal tuo vocale:\n"
        f"Giorno: {risultato['giorno']}\n"
        f"Orario: {fascia_leggibile}\n\n"
        f"Uso le tue preferenze abituali:\n"
        f"Tipo partita: {tipo_partita}\n"
        f"Lato: {lato_leggibile}\n"
        f"Circoli: {nomi_circoli}\n\n"
        f"Hai {config.MINUTI_SCADENZA_BOZZA_VOCALE} minuti per confermare, altrimenti la richiesta decade."
    )
    invia_messaggio_richiesta_vocale(numero_whatsapp, testo)
    invia_link_modifica_preferenze_vocale(numero_whatsapp)
    invia_conferma_bozza_vocale(numero_whatsapp)


def gestisci_conferma_bozza_vocale(db: Session, numero_whatsapp: str, testo_risposta: str):
    """
    Controlla se l'utente ha una bozza vocale in sospeso, e se il testo
    ricevuto sembra una conferma, la trasforma in una vera richiesta. Se
    non ha nessuna bozza in sospeso (o il testo non sembra una conferma),
    solleva ValueError - il webhook prova allora con gli altri controlli
    (proposta gruppo, voto feedback), esattamente come le funzioni simili
    già esistenti.
    """
    utente = db.query(models.Utente).filter(models.Utente.whatsapp_numero == numero_whatsapp).first()
    if utente is None:
        raise ValueError("Utente non trovato")

    bozza = (
        db.query(models.BozzaRichiestaVocale)
        .filter(models.BozzaRichiestaVocale.utente_id == utente.id)
        .order_by(models.BozzaRichiestaVocale.creata_il.desc())
        .first()
    )
    if bozza is None:
        raise ValueError("Nessuna bozza vocale in sospeso per questo utente")

    testo_normalizzato = testo_risposta.strip().lower()

    if "annull" in testo_normalizzato or testo_normalizzato in ("no",):
        db.delete(bozza)
        db.commit()
        invia_messaggio_richiesta_vocale(numero_whatsapp, "Va bene, ho annullato la richiesta. Puoi sempre farne una nuova quando vuoi!")
        return

    if "conferm" not in testo_normalizzato:
        raise ValueError("Il testo non sembra una conferma della bozza vocale")

    circoli_ids = [int(x) for x in bozza.circoli_ids_csv.split(",") if x]
    circoli = db.query(models.Circolo).filter(models.Circolo.id.in_(circoli_ids)).all()

    richiesta = models.Richiesta(
        utente_id=utente.id,
        tipo_partita=bozza.tipo_partita,
        giorno=bozza.giorno,
        disponibilita_bitmask=bozza.disponibilita_bitmask,
    )
    db.add(richiesta)
    db.flush()  # serve richiesta.id prima di collegare i circoli

    for circolo in circoli:
        db.add(models.RichiestaCircolo(richiesta_id=richiesta.id, circolo_id=circolo.id))

    db.delete(bozza)
    db.commit()

    fascia_leggibile = ", ".join(bitmask_a_fasce_leggibili(richiesta.disponibilita_bitmask))
    nomi_circoli = ", ".join(c.nome for c in circoli)
    lato_leggibile = _LATO_LEGGIBILE.get(utente.lato_preferito, utente.lato_preferito)

    testo_conferma = (
        f"Fatto! Richiesta registrata:\n"
        f"{richiesta.tipo_partita} - {richiesta.giorno}\n"
        f"Orari: {fascia_leggibile}\n"
        f"Lato: {lato_leggibile}\n"
        f"Circoli: {nomi_circoli}\n\n"
        f"Ora cerco i tuoi compagni!"
    )
    invia_messaggio_richiesta_vocale(numero_whatsapp, testo_conferma)


def controlla_bozze_vocali_scadute(db: Session) -> int:
    """Da eseguire periodicamente: elimina le bozze vocali mai confermate in tempo."""
    scadenza = datetime.utcnow() - timedelta(minutes=config.MINUTI_SCADENZA_BOZZA_VOCALE)
    n = (
        db.query(models.BozzaRichiestaVocale)
        .filter(models.BozzaRichiestaVocale.creata_il < scadenza)
        .delete()
    )
    db.commit()
    return n
