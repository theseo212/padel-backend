"""
Step 04 (parte finale): al termine della partita, richiede a ciascun
giocatore una valutazione sugli altri 3 (punto 18), e usa questi voti
per aggiustare gradualmente il livello dichiarato, con soglia minima
di partite e step configurabili (punto 18), gestendo anche la mancata
risposta senza penalità (punto 19).
"""

from datetime import datetime, timedelta
from collections import Counter
from sqlalchemy.orm import Session, joinedload

from app import models, config
from app.services.whatsapp import invia_richiesta_feedback


def _prossimo_compagno_da_valutare(db: Session, partita_id: int, votante_id: int):
    """
    Restituisce il PROSSIMO compagno (tra gli altri 3 membri del gruppo)
    che il votante non ha ancora valutato per questa partita, oppure None
    se li ha già valutati tutti. L'ordine è deterministico (per utente_id),
    così sappiamo sempre "a quale domanda sta rispondendo" quando arriva
    un voto via WhatsApp, senza bisogno di altre informazioni.
    """
    partita = db.query(models.Partita).filter(models.Partita.id == partita_id).first()
    if partita is None:
        return None

    gruppo = (
        db.query(models.Gruppo)
        .options(joinedload(models.Gruppo.membri).joinedload(models.GruppoMembro.utente))
        .filter(models.Gruppo.id == partita.gruppo_id)
        .first()
    )
    compagni = sorted(
        [m for m in gruppo.membri if m.utente_id != votante_id],
        key=lambda m: m.utente_id,
    )

    for compagno in compagni:
        gia_votato = (
            db.query(models.FeedbackLivello)
            .filter(
                models.FeedbackLivello.partita_id == partita_id,
                models.FeedbackLivello.votante_id == votante_id,
                models.FeedbackLivello.votato_id == compagno.utente_id,
            )
            .first()
        )
        if gia_votato is None:
            return compagno

    return None  # ha già valutato tutti


def invia_prossima_domanda_feedback(db: Session, partita_id: int, votante_utente_id: int):
    """
    Manda al votante la domanda sul PROSSIMO compagno ancora da valutare
    (un compagno alla volta, con 3 bottoni - punto sollevato dall'utente:
    più affidabile che chiedere di scrivere a mano tutte le valutazioni
    in un unico messaggio).

    Il messaggio cita esplicitamente circolo e data della partita: Meta
    approva come "Utility" solo i sondaggi di feedback che fanno
    riferimento a un'interazione SPECIFICA (non un sondaggio generico) -
    vedi le loro linee guida su "Utility feedback surveys".
    """
    compagno = _prossimo_compagno_da_valutare(db, partita_id, votante_utente_id)
    if compagno is None:
        return  # ha già finito di valutare tutti, nessun'altra domanda da mandare

    votante = db.query(models.Utente).filter(models.Utente.id == votante_utente_id).first()
    partita = db.query(models.Partita).filter(models.Partita.id == partita_id).first()
    circolo = db.query(models.Circolo).filter(models.Circolo.id == partita.circolo_id).first() if partita else None

    nome_compagno = f"{compagno.utente.nome} {compagno.utente.cognome}"
    nome_circolo = circolo.nome if circolo else "circolo"
    data_partita = str(partita.giorno) if partita else ""
    riferimento_partita = f"{nome_circolo} del {data_partita}"

    testo = f"La tua partita al {riferimento_partita} è finita! Come valuti il livello di {nome_compagno}?"
    invia_richiesta_feedback(
        votante.whatsapp_numero, testo,
        nome_compagno=nome_compagno, riferimento_partita=riferimento_partita,
    )


def rispondi_feedback_da_whatsapp(db: Session, numero_whatsapp: str, testo_risposta: str):
    """
    Collega una risposta di valutazione arrivata via WhatsApp (bottone
    "Più alto" / "Giusto" / "Più basso") alla logica di voto. Come per le
    risposte di conferma/rifiuto gruppo, capiamo "a cosa" sta rispondendo
    trovando il prossimo compagno in sospeso per lui - dato che le domande
    vengono mandate una alla volta, in ordine, non c'è ambiguità.
    """
    utente = db.query(models.Utente).filter(models.Utente.whatsapp_numero == numero_whatsapp).first()
    if utente is None:
        raise ValueError(f"Nessun utente trovato con il numero {numero_whatsapp}")

    testo_normalizzato = testo_risposta.strip().lower()
    if "alt" in testo_normalizzato:
        voto = "PIU_ALTO"
    elif "giust" in testo_normalizzato:
        voto = "GIUSTO"
    elif "bass" in testo_normalizzato:
        voto = "PIU_BASSO"
    else:
        raise ValueError(f"Voto '{testo_risposta}' non riconosciuto (atteso Più alto / Giusto / Più basso)")

    # cerca, tra le partite giocate con finestra ancora aperta, quella più
    # recente in cui questo utente ha ancora un compagno da valutare
    partite_aperte = (
        db.query(models.Partita)
        .filter(
            models.Partita.stato == "GIOCATA",
            models.Partita.finestra_feedback_chiusa == False,
        )
        .order_by(models.Partita.data_richiesta_feedback.desc())
        .all()
    )

    for partita in partite_aperte:
        gruppo = db.query(models.Gruppo).filter(models.Gruppo.id == partita.gruppo_id).first()
        e_membro = (
            db.query(models.GruppoMembro)
            .filter(models.GruppoMembro.gruppo_id == gruppo.id, models.GruppoMembro.utente_id == utente.id)
            .first()
        )
        if e_membro is None:
            continue

        compagno = _prossimo_compagno_da_valutare(db, partita.id, utente.id)
        if compagno is not None:
            registra_feedback(db, partita.id, utente.id, compagno.utente_id, voto)
            invia_prossima_domanda_feedback(db, partita.id, utente.id)
            return

    raise ValueError(f"Nessuna valutazione in sospeso trovata per {numero_whatsapp}")


def controlla_partite_da_segnare_automaticamente(db: Session):
    """
    Da eseguire periodicamente: trova le partite PRENOTATE il cui orario
    di inizio + la durata prevista sono già passati, e le segna
    automaticamente come GIOCATA, avviando il ciclo di feedback.

    Non serve nessun intervento umano qui: l'operatore non ha nessuna
    informazione in più rispetto a "l'orario previsto è passato", quindi
    il sistema può calcolarlo da solo. Il bottone manuale nel pannello
    resta disponibile solo come eccezione (es. partita finita in anticipo).
    """
    adesso = datetime.utcnow()
    durata_partita_minuti = config.DURATA_MINIMA_PARTITA_SLOT * config.DURATA_SLOT_MINUTI

    partite_prenotate = db.query(models.Partita).filter(models.Partita.stato == "PRENOTATA").all()

    segnate = 0
    for partita in partite_prenotate:
        inizio_partita = datetime.combine(partita.giorno, partita.ora_inizio)
        fine_prevista = inizio_partita + timedelta(minutes=durata_partita_minuti)

        if adesso >= fine_prevista:
            segna_partita_giocata(db, partita.id)
            segnate += 1

    return segnate


def segna_partita_giocata(db: Session, partita_id: int):
    """
    Segna una partita come GIOCATA e invia a ciascuno dei 4 giocatori
    la richiesta di valutazione sugli altri 3.
    """
    partita = db.query(models.Partita).filter(models.Partita.id == partita_id).first()
    if partita is None:
        raise ValueError("Partita non trovata")
    if partita.stato != "PRENOTATA":
        raise ValueError(f"La partita non è nello stato giusto (stato: {partita.stato})")

    gruppo = (
        db.query(models.Gruppo)
        .options(joinedload(models.Gruppo.membri).joinedload(models.GruppoMembro.utente))
        .filter(models.Gruppo.id == partita.gruppo_id)
        .first()
    )

    partita.stato = "GIOCATA"
    partita.data_richiesta_feedback = datetime.utcnow()
    db.commit()

    for membro in gruppo.membri:
        invia_prossima_domanda_feedback(db, partita.id, membro.utente_id)

    return partita


def registra_feedback(db: Session, partita_id: int, votante_id: int, votato_id: int, voto: str):
    """
    Registra un singolo voto (votante su votato) per una partita.
    Dopo la registrazione, verifica se scatta un aggiornamento di livello
    per il giocatore votato (punto 18).
    """
    partita = db.query(models.Partita).filter(models.Partita.id == partita_id).first()
    if partita is None:
        raise ValueError("Partita non trovata")
    if partita.stato != "GIOCATA":
        raise ValueError("Non è ancora possibile votare per questa partita")
    if partita.finestra_feedback_chiusa:
        raise ValueError("La finestra per votare questa partita è chiusa")
    if voto not in ("PIU_ALTO", "GIUSTO", "PIU_BASSO"):
        raise ValueError("Voto non valido")

    esiste_gia = (
        db.query(models.FeedbackLivello)
        .filter(
            models.FeedbackLivello.partita_id == partita_id,
            models.FeedbackLivello.votante_id == votante_id,
            models.FeedbackLivello.votato_id == votato_id,
        )
        .first()
    )
    if esiste_gia:
        raise ValueError("Hai già votato per questo giocatore in questa partita")

    db.add(models.FeedbackLivello(
        partita_id=partita_id,
        votante_id=votante_id,
        votato_id=votato_id,
        voto=voto,
    ))
    db.commit()


def _numero_partite_con_feedback(db: Session, utente_id: int) -> int:
    """Quante partite distinte hanno già ricevuto almeno un voto per questo utente."""
    righe = (
        db.query(models.FeedbackLivello.partita_id)
        .filter(models.FeedbackLivello.votato_id == utente_id)
        .distinct()
        .all()
    )
    return len(righe)


def _valuta_aggiornamento_livello(db: Session, utente_id: int):
    """
    Se l'utente ha raggiunto un multiplo della soglia minima di partite
    (punto 18), guarda la prevalenza dei voti delle ultime N partite e,
    se supera la soglia, aggiusta il livello di uno step.
    """
    utente = db.query(models.Utente).filter(models.Utente.id == utente_id).first()
    numero_partite = _numero_partite_con_feedback(db, utente_id)

    if numero_partite == 0 or numero_partite % config.SOGLIA_MIN_PARTITE_PER_AGGIORNAMENTO != 0:
        return  # non è ancora il momento di valutare un aggiornamento

    if numero_partite <= utente.ultimo_numero_partite_valutato:
        return  # questa soglia di partite è già stata valutata in precedenza, non riapplicare

    # prendiamo le ultime N partite (in ordine di tempo) che hanno votato questo utente
    ultime_partite = (
        db.query(models.Partita.id, models.Partita.giorno)
        .join(models.FeedbackLivello, models.FeedbackLivello.partita_id == models.Partita.id)
        .filter(models.FeedbackLivello.votato_id == utente_id)
        .distinct()
        .order_by(models.Partita.giorno.desc())
        .limit(config.SOGLIA_MIN_PARTITE_PER_AGGIORNAMENTO)
        .all()
    )
    ids = [p[0] for p in ultime_partite]

    voti = (
        db.query(models.FeedbackLivello.voto)
        .filter(
            models.FeedbackLivello.votato_id == utente_id,
            models.FeedbackLivello.partita_id.in_(ids),
        )
        .all()
    )
    voti = [v[0] for v in voti]
    if not voti:
        return

    conteggio = Counter(voti)
    totale = len(voti)

    prevalenza_alto = conteggio.get("PIU_ALTO", 0) / totale
    prevalenza_basso = conteggio.get("PIU_BASSO", 0) / totale

    livello_precedente = float(utente.livello_playtomic)
    nuovo_livello = livello_precedente
    motivo = None

    if prevalenza_alto >= config.SOGLIA_PREVALENZA_VOTI:
        nuovo_livello = livello_precedente + config.INCREMENTO_DECREMENTO_LIVELLO
        motivo = f"aggiornamento automatico dopo {numero_partite} partite, prevalenza PIU_ALTO ({prevalenza_alto:.0%})"
    elif prevalenza_basso >= config.SOGLIA_PREVALENZA_VOTI:
        nuovo_livello = livello_precedente - config.INCREMENTO_DECREMENTO_LIVELLO
        motivo = f"aggiornamento automatico dopo {numero_partite} partite, prevalenza PIU_BASSO ({prevalenza_basso:.0%})"

    utente.ultimo_numero_partite_valutato = numero_partite  # segna questa soglia come già valutata

    if motivo is not None:
        utente.livello_playtomic = nuovo_livello
        db.add(models.StoricoLivello(
            utente_id=utente.id,
            livello_precedente=livello_precedente,
            livello_nuovo=nuovo_livello,
            motivo=motivo,
        ))
        db.commit()
    else:
        db.commit()  # salva comunque l'aggiornamento di ultimo_numero_partite_valutato


def elabora_feedback_partita(db: Session, partita_id: int):
    """
    Da chiamare quando si vuole "chiudere" una partita ai fini del calcolo
    livello (es. dopo la finestra di 24 ore, punto 19): valuta l'aggiornamento
    di livello per ciascuno dei 4 giocatori coinvolti.
    """
    partita = db.query(models.Partita).filter(models.Partita.id == partita_id).first()
    gruppo = (
        db.query(models.Gruppo)
        .options(joinedload(models.Gruppo.membri))
        .filter(models.Gruppo.id == partita.gruppo_id)
        .first()
    )
    for membro in gruppo.membri:
        _valuta_aggiornamento_livello(db, membro.utente_id)


def controlla_cicli_feedback(db: Session):
    """
    Da eseguire periodicamente: gestisce promemoria (a PROMEMORIA_FEEDBACK_ORE
    ore) e chiusura finestra (a FINESTRA_VOTAZIONE_FEEDBACK_ORE ore) per le
    partite GIOCATA in attesa di feedback (punto 19).
    """
    adesso = datetime.utcnow()

    # 1. Promemoria per chi non ha ancora votato tutti e 3 i compagni
    partite_da_ricordare = (
        db.query(models.Partita)
        .filter(
            models.Partita.stato == "GIOCATA",
            models.Partita.promemoria_feedback_inviato == False,
            models.Partita.data_richiesta_feedback.isnot(None),
        )
        .all()
    )
    for partita in partite_da_ricordare:
        ore_passate = (adesso - partita.data_richiesta_feedback).total_seconds() / 3600
        if ore_passate >= config.PROMEMORIA_FEEDBACK_ORE:
            gruppo = (
                db.query(models.Gruppo)
                .options(joinedload(models.Gruppo.membri).joinedload(models.GruppoMembro.utente))
                .filter(models.Gruppo.id == partita.gruppo_id)
                .first()
            )
            for membro in gruppo.membri:
                voti_dati = (
                    db.query(models.FeedbackLivello)
                    .filter(
                        models.FeedbackLivello.partita_id == partita.id,
                        models.FeedbackLivello.votante_id == membro.utente_id,
                    )
                    .count()
                )
                if voti_dati < 3:  # non ha ancora votato tutti e 3 i compagni
                    # Riusiamo lo stesso template già approvato della prima
                    # domanda (con i bottoni Più alto/Giusto/Più basso),
                    # invece di un secondo template generico "promemoria":
                    # più utile per l'utente (bottoni diretti, non solo un
                    # testo) e non richiede una seconda approvazione Meta
                    # (che continuava a classificarlo come Marketing).
                    invia_prossima_domanda_feedback(db, partita.id, membro.utente_id)
            partita.promemoria_feedback_inviato = True
            db.commit()

    # 2. Chiusura finestra: valuta l'aggiornamento livello e blocca ulteriori voti
    partite_da_chiudere = (
        db.query(models.Partita)
        .filter(
            models.Partita.stato == "GIOCATA",
            models.Partita.finestra_feedback_chiusa == False,
            models.Partita.data_richiesta_feedback.isnot(None),
        )
        .all()
    )
    chiuse = 0
    for partita in partite_da_chiudere:
        ore_passate = (adesso - partita.data_richiesta_feedback).total_seconds() / 3600
        if ore_passate >= config.FINESTRA_VOTAZIONE_FEEDBACK_ORE:
            elabora_feedback_partita(db, partita.id)
            partita.finestra_feedback_chiusa = True
            db.commit()
            chiuse += 1

    return chiuse
