"""
Gestione "gioco già in coppia" (punto 22): quando A indica un compagno
già verificato, la richiesta di A resta in ATTESA_CONFERMA_COMPAGNO finché
B non risponde su WhatsApp. Questo modulo gestisce SOLO la risposta di B
(conferma o rifiuto) - la creazione della richiesta in attesa avviene in
main.py, insieme al resto della logica di creazione richiesta.
"""

from sqlalchemy.orm import Session

from app import models
from app.services.bitmask import bitmask_a_fasce_leggibili
from app.services.bitmask_tipo import bitmask_tipo_a_stringa_leggibile
from app.services.whatsapp import invia_esito_richiesta_coppia, _invia


def rispondi_a_richiesta_coppia_da_whatsapp(db: Session, numero_whatsapp: str, testo_risposta: str) -> dict:
    """
    Collega una risposta arrivata su WhatsApp alla richiesta di coppia in
    attesa. Stesso principio di rispondi_a_gruppo_da_whatsapp: troviamo da
    soli CHI ha scritto e QUALE richiesta stava aspettando la sua risposta
    (un utente ha al massimo una richiesta di questo tipo in sospeso per
    volta, grazie a come viene creata in main.py).
    """
    utente_compagno = db.query(models.Utente).filter(models.Utente.whatsapp_numero == numero_whatsapp).first()
    if utente_compagno is None:
        raise ValueError(f"Nessun utente trovato con il numero {numero_whatsapp}")

    richiesta_a = (
        db.query(models.Richiesta)
        .filter(
            models.Richiesta.stato == "ATTESA_CONFERMA_COMPAGNO",
            models.Richiesta.utente_compagno_atteso_id == utente_compagno.id,
        )
        .order_by(models.Richiesta.data_creazione.desc())
        .first()
    )

    testo_normalizzato = testo_risposta.strip().lower()
    sembra_conferma_o_rifiuto = "conferm" in testo_normalizzato or "rifiut" in testo_normalizzato

    if richiesta_a is None:
        if sembra_conferma_o_rifiuto:
            # Probabile risposta tardiva: non c'è più nulla in attesa per
            # questo utente (magari ha già risposto, o A ha ritirato la
            # richiesta nel frattempo). Meglio dirlo chiaramente.
            _invia(numero_whatsapp,
                   "Questa richiesta non è più valida (forse hai già risposto, o è scaduta). "
                   "Se serve, chiedi al tuo compagno di invitarti di nuovo.",
                   None, None)
            return {"gestito": True, "esito": "RISPOSTA_TARDIVA"}
        raise ValueError(f"Nessuna richiesta di coppia in attesa per {numero_whatsapp}")

    utente_a = richiesta_a.utente
    fascia_leggibile = ", ".join(bitmask_a_fasce_leggibili(richiesta_a.disponibilita_bitmask))
    tipo_leggibile = bitmask_tipo_a_stringa_leggibile(richiesta_a.tipi_partita_bitmask)
    nomi_circoli = ", ".join(c.nome for c in richiesta_a.circoli)

    if "rifiut" in testo_normalizzato:
        db.delete(richiesta_a)
        db.commit()

        testo_a = (
            f"Il tuo compagno di gioco ha rifiutato l'invito per la partita del {richiesta_a.giorno}. "
            f"La richiesta è stata annullata - se vuoi, inseriscine una nuova (anche da solo)."
        )
        invia_esito_richiesta_coppia(
            utente_a.whatsapp_numero, testo_a,
            nome_compagno=utente_compagno.nome, giorno=str(richiesta_a.giorno),
            fascia_oraria=fascia_leggibile, circoli=nomi_circoli,
            esito="ha rifiutato l'invito - la richiesta è stata annullata",
        )
        _invia(numero_whatsapp, "Va bene, ho annullato la richiesta. Grazie per aver risposto!", None, None)
        return {"gestito": True, "esito": "RIFIUTATA"}

    if "conferm" in testo_normalizzato:
        # Creiamo la richiesta di B, identica a quella di A (stesso
        # giorno/tipi/fasce/circoli - B non deve ricompilare nulla), e
        # colleghiamo le due reciprocamente. Il legame vale SOLO per
        # questa specifica coppia di richieste, non è permanente.
        richiesta_b = models.Richiesta(
            utente_id=utente_compagno.id,
            tipi_partita_bitmask=richiesta_a.tipi_partita_bitmask,
            giorno=richiesta_a.giorno,
            disponibilita_bitmask=richiesta_a.disponibilita_bitmask,
            stato="IN_RICERCA",
        )
        db.add(richiesta_b)
        db.flush()  # serve richiesta_b.id

        for circolo in richiesta_a.circoli:
            db.add(models.RichiestaCircolo(richiesta_id=richiesta_b.id, circolo_id=circolo.id))

        richiesta_a.stato = "IN_RICERCA"
        richiesta_a.richiesta_partner_id = richiesta_b.id
        richiesta_b.richiesta_partner_id = richiesta_a.id
        db.commit()

        testo_a = (
            f"{utente_compagno.nome} ha confermato! Ora vi cerco altri 2 compagni per la partita "
            f"{tipo_leggibile} del {richiesta_a.giorno} ({fascia_leggibile}) nei circoli {nomi_circoli}."
        )
        invia_esito_richiesta_coppia(
            utente_a.whatsapp_numero, testo_a,
            nome_compagno=utente_compagno.nome, giorno=str(richiesta_a.giorno),
            fascia_oraria=fascia_leggibile, circoli=nomi_circoli,
            esito="ha confermato! Ora cerco gli altri 2 compagni per voi due",
        )
        _invia(
            numero_whatsapp,
            f"Fatto! Ora cerco altri 2 compagni per te e {utente_a.nome}, "
            f"per la partita {tipo_leggibile} del {richiesta_a.giorno} ({fascia_leggibile}).",
            None, None,
        )
        return {"gestito": True, "esito": "CONFERMATA"}

    raise ValueError(f"Testo non riconosciuto come risposta coppia: {testo_risposta!r}")
