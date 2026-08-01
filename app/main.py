"""
Questo è il file principale dell'applicazione: qui nasce il server web.
Per ora contiene solo un endpoint di verifica ("health check"), utile
per controllare che il server sia acceso e collegato al database.

Nei prossimi passi aggiungeremo qui gli endpoint veri (es. per inserire
una richiesta dal form web).
"""

from datetime import datetime, timedelta
import os
import csv
import io

from fastapi import FastAPI, Depends, HTTPException
from fastapi.responses import FileResponse, Response
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import text
from apscheduler.schedulers.background import BackgroundScheduler

from app.database import get_db, SessionLocal, engine, Base
from app import models, schemas, config
from app.services.bitmask import crea_bitmask, bitmask_a_fasce_leggibili
from app.services.conversione_livello import ottieni_livello_playtomic
from app.services.whatsapp import genera_otp, invia_otp_whatsapp, invia_riepilogo_richiesta
from app.matching.motore import esegui_ciclo_matching
from app.matching.gestione_gruppi import rispondi_a_gruppo, controlla_timeout_gruppi
from app.matching.prenotazione import conferma_prenotazione, fallisce_prenotazione
from app.matching.feedback import (
    segna_partita_giocata, registra_feedback, controlla_cicli_feedback,
    controlla_partite_da_segnare_automaticamente,
)

app = FastAPI(title="Sistema Prenotazione Padel")

# CORS: permette al form pubblico (che gira su un dominio/porta diversa)
# di chiamare questa API dal browser. In sviluppo locale, se la variabile
# CORS_ALLOWED_ORIGINS non è impostata, si apre a tutti ("*") per comodità.
# IN PRODUZIONE: impostare CORS_ALLOWED_ORIGINS su Railway con l'indirizzo
# reale del frontend (es. "https://tuosito.up.railway.app"), separando
# più indirizzi con una virgola se necessario.
origini_consentite = os.getenv("CORS_ALLOWED_ORIGINS", "*").strip()
if not origini_consentite:
    origini_consentite = "*"
lista_origini = ["*"] if origini_consentite == "*" else [
    o.strip() for o in origini_consentite.split(",") if o.strip()
]
if not lista_origini:
    lista_origini = ["*"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=lista_origini,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

scheduler = BackgroundScheduler()


def job_matching_periodico():
    """Funzione eseguita automaticamente ogni INTERVALLO_BATCH_MINUTI."""
    db = SessionLocal()
    try:
        gruppi = esegui_ciclo_matching(db)
        if gruppi:
            print(f"[MATCHING] Creati {len(gruppi)} nuovi gruppi.")
    finally:
        db.close()


def job_controllo_timeout():
    """Funzione eseguita automaticamente ogni minuto, per chiudere le proposte scadute."""
    db = SessionLocal()
    try:
        n = controlla_timeout_gruppi(db)
        if n:
            print(f"[TIMEOUT] {n} gruppi annullati per timeout.")
    finally:
        db.close()


def job_controllo_feedback():
    """Funzione eseguita automaticamente ogni ora, per promemoria e chiusura feedback."""
    db = SessionLocal()
    try:
        n = controlla_cicli_feedback(db)
        if n:
            print(f"[FEEDBACK] {n} finestre di feedback chiuse ed elaborate.")
    finally:
        db.close()


def job_segna_partite_concluse():
    """
    Funzione eseguita automaticamente ogni 5 minuti: segna come GIOCATA
    le partite il cui orario + durata prevista sono passati, senza bisogno
    di intervento dell'operatore.
    """
    db = SessionLocal()
    try:
        n = controlla_partite_da_segnare_automaticamente(db)
        if n:
            print(f"[AUTO] {n} partite segnate automaticamente come giocate.")
    finally:
        db.close()


CONVERSIONI_WANSPORT_PLAYTOMIC = [
    ("C4", 1.00), ("C3", 1.50), ("C2", 2.00), ("C1", 2.50),
    ("B4", 3.00), ("B3", 3.50), ("B2", 4.00), ("B1", 4.50),
    ("A4", 5.00), ("A3", 5.50), ("A2", 6.00), ("A1", 6.50),
]


def inizializza_database_se_necessario():
    """
    Crea le tabelle (se non esistono già) e inserisce i valori di
    conversione Wansport->Playtomic (se la tabella è vuota). Eseguito
    automaticamente ad ogni avvio del server: è un'operazione sicura da
    ripetere (non duplica nulla se già fatto), pensata per non dover
    lanciare init_db.py a mano su un server remoto come Railway.

    NOTA IMPORTANTE: create_all crea solo le tabelle che NON esistono
    ancora - non aggiunge colonne nuove a tabelle già esistenti. Per
    questo, ogni volta che aggiungiamo un campo a una tabella che
    potrebbe già esistere in produzione, serve anche una piccola riga
    "ALTER TABLE ... ADD COLUMN IF NOT EXISTS" qui sotto, altrimenti il
    database resta con lo schema vecchio nonostante il codice sia aggiornato.
    """
    Base.metadata.create_all(bind=engine)

    # "Migrazioni leggere": colonne aggiunte dopo la primissima creazione
    # delle tabelle, che vanno aggiunte anche ai database già esistenti.
    with engine.connect() as connessione:
        connessione.execute(text("ALTER TABLE circoli ADD COLUMN IF NOT EXISTS provincia VARCHAR(10)"))
        connessione.commit()

    db = SessionLocal()
    try:
        tabella_vuota = db.query(models.ConversioneWansportPlaytomic).count() == 0
        if tabella_vuota:
            for wansport, playtomic in CONVERSIONI_WANSPORT_PLAYTOMIC:
                db.add(models.ConversioneWansportPlaytomic(
                    livello_wansport=wansport, livello_playtomic=playtomic
                ))
            db.commit()
            print("[STARTUP] Tabelle create e valori di conversione inseriti.")
        else:
            print("[STARTUP] Database già inizializzato.")
    finally:
        db.close()


@app.on_event("startup")
def avvia_scheduler():
    inizializza_database_se_necessario()

    scheduler.add_job(
        job_matching_periodico,
        "interval",
        minutes=config.INTERVALLO_BATCH_MINUTI,
        id="matching_periodico",
    )
    scheduler.add_job(
        job_controllo_timeout,
        "interval",
        minutes=1,
        id="controllo_timeout",
    )
    scheduler.add_job(
        job_controllo_feedback,
        "interval",
        hours=1,
        id="controllo_feedback",
    )
    scheduler.add_job(
        job_segna_partite_concluse,
        "interval",
        minutes=5,
        id="segna_partite_concluse",
    )
    scheduler.start()


@app.on_event("shutdown")
def ferma_scheduler():
    scheduler.shutdown()


@app.get("/")
def home():
    return {"messaggio": "Il server è acceso e funzionante."}


@app.get("/admin")
def pannello_operatore():
    """Serve la pagina web del pannello operatore."""
    import os
    percorso = os.path.join(os.path.dirname(__file__), "static", "admin.html")
    return FileResponse(percorso)


@app.get("/admin/report")
def pagina_report():
    """Serve la pagina web del report partite."""
    import os
    percorso = os.path.join(os.path.dirname(__file__), "static", "report.html")
    return FileResponse(percorso)


@app.get("/health/db")
def health_check_database(db: Session = Depends(get_db)):
    """
    Verifica che il collegamento al database funzioni davvero,
    eseguendo una query semplicissima.
    """
    risultato = db.execute(text("SELECT 1")).scalar()
    return {"database_collegato": risultato == 1}


@app.get("/utenti/profilo")
def profilo_utente(whatsapp_numero: str, db: Session = Depends(get_db)):
    """
    Cerca un utente per numero WhatsApp e restituisce i suoi dati fissi
    (nome, cognome, livello, lato - immutabili dopo la prima richiesta,
    punto 17) più i dettagli della sua ultima richiesta (tipo di partita
    e circoli scelti). Usato dal form pubblico per riconoscere un utente
    già registrato e non fargli riscrivere tutto da capo.
    """
    utente = db.query(models.Utente).filter(
        models.Utente.whatsapp_numero == whatsapp_numero
    ).first()

    if utente is None:
        return {"esiste": False}

    ultima_richiesta = (
        db.query(models.Richiesta)
        .filter(models.Richiesta.utente_id == utente.id)
        .order_by(models.Richiesta.data_creazione.desc())
        .first()
    )

    return {
        "esiste": True,
        "nome": utente.nome,
        "cognome": utente.cognome,
        "livello_playtomic": float(utente.livello_playtomic),
        "livello_dichiarato_scala": utente.livello_dichiarato_scala,
        "livello_dichiarato_originale": utente.livello_dichiarato_originale,
        "lato_preferito": utente.lato_preferito,
        "ultima_richiesta": {
            "tipo_partita": ultima_richiesta.tipo_partita,
            "circoli_ids": [c.id for c in ultima_richiesta.circoli],
        } if ultima_richiesta else None,
    }


@app.post("/richieste", response_model=schemas.RichiestaResponse)
def crea_richiesta(dati: schemas.RichiestaCreate, db: Session = Depends(get_db)):
    """
    Endpoint dello Step 1: riceve i dati del form e:
    1. Se l'utente non esiste, lo crea (livello immutabile da qui in poi - punto 17)
    2. Se l'utente esiste già, IGNORA il livello inviato in questa richiesta
       e usa sempre quello salvato al primo inserimento
    3. Crea la nuova richiesta (un giorno solo - punto 8) collegata ai circoli scelti
    4. Se l'utente non è ancora validato, genera e "invia" un OTP
    5. Se è già validato, "invia" il riepilogo di conferma
    """

    # --- 1. Cerca l'utente per numero WhatsApp ---
    utente = db.query(models.Utente).filter(
        models.Utente.whatsapp_numero == dati.whatsapp_numero
    ).first()

    utente_nuovo = utente is None

    if not utente_nuovo:
        # Controllo sospensione (punto 14): un utente sospeso non può inserire nuove richieste
        if utente.stato_account == "SOSPESO":
            if utente.sospeso_fino_a and datetime.utcnow() < utente.sospeso_fino_a:
                raise HTTPException(
                    status_code=403,
                    detail=f"Account sospeso fino al {utente.sospeso_fino_a.strftime('%d/%m/%Y')} "
                           f"per mancate conferme ripetute."
                )
            else:
                utente.stato_account = "ATTIVO"

        # Controllo richiesta duplicata per lo stesso giorno: un utente non può avere
        # più di una richiesta attiva (IN_RICERCA o LOCKED) per lo stesso giorno.
        richiesta_esistente = (
            db.query(models.Richiesta)
            .filter(
                models.Richiesta.utente_id == utente.id,
                models.Richiesta.giorno == dati.giorno,
                models.Richiesta.stato.in_(["IN_RICERCA", "LOCKED"]),
            )
            .first()
        )
        if richiesta_esistente is not None:
            raise HTTPException(
                status_code=409,
                detail={
                    "messaggio": "Hai già una richiesta attiva per questo giorno.",
                    "richiesta_esistente_id": richiesta_esistente.id,
                    "stato_richiesta_esistente": richiesta_esistente.stato,
                    "azione_annulla": f"/richieste/{richiesta_esistente.id}/annulla",
                }
            )

    if utente_nuovo:
        # Prima richiesta in assoluto: calcoliamo e "congeliamo" il livello
        try:
            livello_playtomic = ottieni_livello_playtomic(db, dati.livello_scala, dati.livello_valore)
        except ValueError as errore:
            raise HTTPException(status_code=400, detail=str(errore))

        utente = models.Utente(
            nome=dati.nome,
            cognome=dati.cognome,
            whatsapp_numero=dati.whatsapp_numero,
            whatsapp_validato=False,
            livello_playtomic=livello_playtomic,
            livello_dichiarato_scala=dati.livello_scala,
            livello_dichiarato_originale=dati.livello_valore if dati.livello_scala == "WANSPORT" else None,
            lato_preferito=dati.lato_preferito,
        )
        db.add(utente)
        db.flush()  # assegna l'id all'utente senza chiudere la transazione

    # --- 2. Se l'utente esiste già, il livello NON viene mai ri-scritto (punto 17) ---
    # (nessuna azione necessaria: semplicemente non tocchiamo utente.livello_playtomic)
    #
    # Il lato di gioco preferito, invece, PUÒ cambiare nel tempo (a differenza
    # del livello): non è una questione di equità nel matching come il livello,
    # è solo una preferenza personale che può cambiare con l'esperienza.
    if not utente_nuovo:
        utente.lato_preferito = dati.lato_preferito

    # --- 3. Costruisce il bitmask e crea la richiesta ---
    try:
        bitmask = crea_bitmask(dati.fasce_orarie)
    except ValueError as errore:
        raise HTTPException(status_code=400, detail=str(errore))

    circoli = db.query(models.Circolo).filter(models.Circolo.id.in_(dati.circoli_ids)).all()
    if len(circoli) != len(dati.circoli_ids):
        raise HTTPException(status_code=400, detail="Uno o più circoli selezionati non esistono")

    circoli_non_attivi = [c.nome for c in circoli if not c.attivo]
    if circoli_non_attivi:
        raise HTTPException(
            status_code=400,
            detail=f"Questi circoli non sono più disponibili: {', '.join(circoli_non_attivi)}"
        )

    richiesta = models.Richiesta(
        utente_id=utente.id,
        tipo_partita=dati.tipo_partita,
        giorno=dati.giorno,
        disponibilita_bitmask=bitmask,
        stato="IN_RICERCA",
        tolleranza_corrente=config.TOLLERANZA_INIZIALE,
    )
    richiesta.circoli = circoli
    db.add(richiesta)
    db.flush()

    # --- 4/5. Validazione OTP oppure riepilogo ---
    if not utente.whatsapp_validato:
        codice = genera_otp()
        utente.otp_codice = codice
        utente.otp_scadenza = datetime.utcnow() + timedelta(minutes=config.OTP_DURATA_VALIDITA_MINUTI)
        invia_otp_whatsapp(utente.whatsapp_numero, codice)

        db.commit()
        return schemas.RichiestaResponse(
            richiesta_id=richiesta.id,
            utente_nuovo=utente_nuovo,
            richiede_validazione_otp=True,
            messaggio="Richiesta salvata. Ti abbiamo inviato un codice di verifica su WhatsApp.",
        )

    else:
        fasce_leggibili = ", ".join(bitmask_a_fasce_leggibili(bitmask))
        riepilogo = (
            f"Richiesta confermata!\n"
            f"{dati.tipo_partita} - {dati.giorno}\n"
            f"Orari: {fasce_leggibili}\n"
            f"Livello: {utente.livello_playtomic}\n"
            f"Circoli: {', '.join(c.nome for c in circoli)}"
        )
        invia_riepilogo_richiesta(utente.whatsapp_numero, riepilogo)

        db.commit()
        return schemas.RichiestaResponse(
            richiesta_id=richiesta.id,
            utente_nuovo=utente_nuovo,
            richiede_validazione_otp=False,
            messaggio="Richiesta salvata e riepilogo inviato su WhatsApp.",
        )


@app.post("/richieste/valida-otp")
def valida_otp(dati: schemas.ValidaOtpRequest, db: Session = Depends(get_db)):
    """
    Endpoint per validare il codice OTP inserito dall'utente nel form web.
    """
    utente = db.query(models.Utente).filter(
        models.Utente.whatsapp_numero == dati.whatsapp_numero
    ).first()

    if utente is None:
        raise HTTPException(status_code=404, detail="Utente non trovato")

    if utente.whatsapp_validato:
        return {"messaggio": "Numero già validato in precedenza."}

    if utente.otp_codice != dati.codice_otp:
        raise HTTPException(status_code=400, detail="Codice OTP errato")

    if utente.otp_scadenza is None or datetime.utcnow() > utente.otp_scadenza:
        raise HTTPException(status_code=400, detail="Codice OTP scaduto, richiedine uno nuovo")

    utente.whatsapp_validato = True
    utente.otp_codice = None
    utente.otp_scadenza = None
    db.commit()

    return {"messaggio": "Numero verificato con successo."}


@app.post("/richieste/{richiesta_id}/annulla")
def annulla_richiesta(richiesta_id: int, db: Session = Depends(get_db)):
    """
    Permette a un utente di annullare una propria richiesta, tipicamente
    dopo essere stato avvisato di averne già una attiva per lo stesso giorno.

    - Se la richiesta è ancora IN_RICERCA: annullamento semplice, nessuna
      penalità (l'utente non ha ancora impegnato nessun altro giocatore).
    - Se la richiesta è LOCKED (già proposta in un gruppo con altri 3
      giocatori): equivale a un RIFIUTO vero e proprio della proposta,
      con le stesse conseguenze previste (punto 14): gli altri 3 tornano
      in ricerca, l'utente viene penalizzato come per un rifiuto esplicito.
      Riusiamo la stessa logica già validata in gestione_gruppi, invece
      di duplicarla, per garantire lo stesso comportamento in entrambi i casi.
    """
    richiesta = db.query(models.Richiesta).filter(models.Richiesta.id == richiesta_id).first()
    if richiesta is None:
        raise HTTPException(status_code=404, detail="Richiesta non trovata")

    if richiesta.stato == "IN_RICERCA":
        richiesta.stato = "ANNULLATA"
        db.commit()
        return {"messaggio": "Richiesta annullata, nessuna penalità.", "stato": "ANNULLATA"}

    elif richiesta.stato == "LOCKED":
        membro = (
            db.query(models.GruppoMembro)
            .filter(models.GruppoMembro.richiesta_id == richiesta_id)
            .first()
        )
        if membro is None:
            raise HTTPException(status_code=500, detail="Dati incoerenti: richiesta LOCKED senza gruppo collegato")

        try:
            risultato = rispondi_a_gruppo(db, membro.gruppo_id, membro.utente_id, "RIFIUTO")
        except ValueError as errore:
            raise HTTPException(status_code=400, detail=str(errore))

        return {
            "messaggio": "La richiesta era già proposta in un gruppo: annullamento registrato "
                         "come rifiuto della proposta, gli altri giocatori sono stati avvisati.",
            "stato_gruppo": risultato.get("stato_gruppo"),
        }

    else:
        raise HTTPException(
            status_code=400,
            detail=f"Questa richiesta non può essere annullata (stato attuale: {richiesta.stato})"
        )


@app.post("/matching/esegui-ora")
def esegui_matching_manuale(db: Session = Depends(get_db)):
    """
    Endpoint SOLO PER TEST: fa scattare subito un ciclo di matching,
    invece di aspettare i 3 minuti dello scheduler automatico.
    In produzione questo endpoint andrà protetto o rimosso.
    """
    gruppi = esegui_ciclo_matching(db)
    return {
        "gruppi_creati": len(gruppi),
        "dettagli": [
            {
                "gruppo_id": g.id,
                "circolo_id": g.circolo_id,
                "giorno": str(g.giorno),
                "slot_inizio": g.slot_inizio,
            }
            for g in gruppi
        ],
    }


@app.post("/gruppi/{gruppo_id}/rispondi")
def rispondi_a_proposta(gruppo_id: int, dati: schemas.RispostaGruppo, db: Session = Depends(get_db)):
    """
    Endpoint dello Step 03: un giocatore conferma o rifiuta una proposta di partita.
    In produzione questo verrà chiamato dal webhook di Twilio quando l'utente
    preme il bottone Quick Reply su WhatsApp; per ora lo chiamiamo direttamente per i test.
    """
    try:
        risultato = rispondi_a_gruppo(db, gruppo_id, dati.utente_id, dati.risposta)
    except ValueError as errore:
        raise HTTPException(status_code=400, detail=str(errore))
    return risultato


@app.post("/matching/controlla-timeout-ora")
def controlla_timeout_manuale(db: Session = Depends(get_db)):
    """Endpoint SOLO PER TEST: forza il controllo dei timeout invece di aspettare lo scheduler."""
    n = controlla_timeout_gruppi(db)
    return {"gruppi_annullati_per_timeout": n}


@app.post("/gruppi/{gruppo_id}/prenotazione/conferma")
def prenotazione_confermata(gruppo_id: int, db: Session = Depends(get_db)):
    """
    Endpoint per l'OPERATORE (Step 04, punto 15): usato quando ha verificato
    che il campo è disponibile e ha effettuato la prenotazione sul circolo.
    """
    try:
        partita = conferma_prenotazione(db, gruppo_id)
    except ValueError as errore:
        raise HTTPException(status_code=400, detail=str(errore))
    return {"partita_id": partita.id, "stato": partita.stato}


@app.post("/gruppi/{gruppo_id}/prenotazione/fallita")
def prenotazione_fallita_endpoint(gruppo_id: int, db: Session = Depends(get_db)):
    """
    Endpoint per l'OPERATORE: usato quando ha verificato che il campo
    NON è disponibile. I 4 giocatori tornano in ricerca senza penalità.
    """
    try:
        fallisce_prenotazione(db, gruppo_id)
    except ValueError as errore:
        raise HTTPException(status_code=400, detail=str(errore))
    return {"messaggio": "Prenotazione fallita, giocatori rimessi in ricerca."}


@app.post("/partite/{partita_id}/segna-giocata")
def segna_giocata(partita_id: int, db: Session = Depends(get_db)):
    """
    Da chiamare dopo che la partita si è effettivamente svolta.
    Invia a ciascun giocatore la richiesta di valutazione sugli altri 3.
    """
    try:
        partita = segna_partita_giocata(db, partita_id)
    except ValueError as errore:
        raise HTTPException(status_code=400, detail=str(errore))
    return {"partita_id": partita.id, "stato": partita.stato}


@app.post("/partite/{partita_id}/feedback")
def invia_feedback(partita_id: int, dati: schemas.FeedbackCreate, db: Session = Depends(get_db)):
    """Un giocatore invia il proprio voto su un compagno di partita."""
    try:
        registra_feedback(db, partita_id, dati.votante_id, dati.votato_id, dati.voto)
    except ValueError as errore:
        raise HTTPException(status_code=400, detail=str(errore))
    return {"messaggio": "Voto registrato."}


@app.post("/feedback/controlla-cicli-ora")
def controlla_feedback_manuale(db: Session = Depends(get_db)):
    """Endpoint SOLO PER TEST: forza il controllo dei cicli di feedback."""
    n = controlla_cicli_feedback(db)
    return {"finestre_chiuse": n}


@app.post("/partite/controlla-concluse-ora")
def controlla_partite_concluse_manuale(db: Session = Depends(get_db)):
    """Endpoint SOLO PER TEST: forza il controllo automatico delle partite concluse."""
    n = controlla_partite_da_segnare_automaticamente(db)
    return {"partite_segnate_automaticamente": n}


@app.get("/admin/gruppi-da-prenotare")
def lista_gruppi_da_prenotare(db: Session = Depends(get_db)):
    """
    Restituisce tutti i gruppi CONFERMATI in attesa che l'operatore
    verifichi la disponibilità del campo e confermi/annulli la prenotazione.
    """
    from sqlalchemy.orm import joinedload

    gruppi = (
        db.query(models.Gruppo)
        .options(
            joinedload(models.Gruppo.membri).joinedload(models.GruppoMembro.utente),
        )
        .filter(models.Gruppo.stato == "CONFERMATO")
        .order_by(models.Gruppo.giorno, models.Gruppo.slot_inizio)
        .all()
    )

    risultato = []
    for g in gruppi:
        circolo = db.query(models.Circolo).filter(models.Circolo.id == g.circolo_id).first()
        minuti_totali = config.ORA_INIZIO_GIORNATA * 60 + g.slot_inizio * config.DURATA_SLOT_MINUTI
        ore, minuti = divmod(minuti_totali, 60)
        risultato.append({
            "gruppo_id": g.id,
            "circolo_nome": circolo.nome if circolo else "?",
            "giorno": str(g.giorno),
            "orario": f"{ore:02d}:{minuti:02d}",
            "giocatori": [f"{m.utente.nome} {m.utente.cognome} ({m.lato_assegnato})" for m in g.membri],
        })
    return risultato


@app.get("/admin/partite-da-segnare")
def lista_partite_da_segnare(db: Session = Depends(get_db)):
    """Restituisce tutte le partite PRENOTATE, da segnare come giocate quando si sono svolte."""
    from sqlalchemy.orm import joinedload

    partite = (
        db.query(models.Partita)
        .filter(models.Partita.stato == "PRENOTATA")
        .order_by(models.Partita.giorno, models.Partita.ora_inizio)
        .all()
    )

    risultato = []
    for p in partite:
        circolo = db.query(models.Circolo).filter(models.Circolo.id == p.circolo_id).first()
        gruppo = (
            db.query(models.Gruppo)
            .options(joinedload(models.Gruppo.membri).joinedload(models.GruppoMembro.utente))
            .filter(models.Gruppo.id == p.gruppo_id)
            .first()
        )
        giocatori = [f"{m.utente.nome} {m.utente.cognome}" for m in gruppo.membri] if gruppo else []
        risultato.append({
            "partita_id": p.id,
            "circolo_nome": circolo.nome if circolo else "?",
            "giorno": str(p.giorno),
            "orario": str(p.ora_inizio),
            "giocatori": giocatori,
        })
    return risultato


def _circolo_a_dict(c: models.Circolo) -> dict:
    return {
        "id": c.id,
        "nome": c.nome,
        "indirizzo": c.indirizzo,
        "provincia": c.provincia,
        "telefono": c.telefono,
        "orario_apertura": str(c.orario_apertura) if c.orario_apertura else None,
        "orario_chiusura": str(c.orario_chiusura) if c.orario_chiusura else None,
        "numero_campi": c.numero_campi,
        "dotazioni": c.dotazioni,
        "note_staff": c.note_staff,
        "attivo": c.attivo,
    }


@app.get("/circoli")
def lista_circoli(solo_attivi: bool = False, provincia: str | None = None, db: Session = Depends(get_db)):
    """
    Restituisce i circoli. Il pannello operatore chiama questo endpoint
    senza filtro (vuole vedere anche quelli disattivati, per poterli
    riattivare). Il form pubblico dello Step 01 lo chiamerà con
    ?solo_attivi=true, per non proporre agli utenti circoli disattivati.
    Il filtro ?provincia= è pensato per quando la lista crescerà molto
    (es. copertura regionale): filtra lato server invece di scaricare
    sempre tutti i circoli e filtrare solo nel browser.
    Ordinati alfabeticamente per nome (criterio scelto per semplicità).
    """
    query = db.query(models.Circolo)
    if solo_attivi:
        query = query.filter(models.Circolo.attivo == True)
    if provincia:
        query = query.filter(models.Circolo.provincia == provincia)
    circoli = query.order_by(models.Circolo.nome).all()
    return [_circolo_a_dict(c) for c in circoli]


@app.post("/circoli")
def crea_circolo(dati: schemas.CircoloCreate, db: Session = Depends(get_db)):
    """Crea un nuovo circolo."""
    circolo = models.Circolo(
        nome=dati.nome,
        indirizzo=dati.indirizzo,
        provincia=dati.provincia,
        telefono=dati.telefono,
        orario_apertura=dati.orario_apertura,
        orario_chiusura=dati.orario_chiusura,
        numero_campi=dati.numero_campi,
        dotazioni=dati.dotazioni,
        note_staff=dati.note_staff,
        attivo=True,
    )
    db.add(circolo)
    db.commit()
    db.refresh(circolo)
    return _circolo_a_dict(circolo)


@app.put("/circoli/{circolo_id}")
def modifica_circolo(circolo_id: int, dati: schemas.CircoloUpdate, db: Session = Depends(get_db)):
    """Modifica i dati di un circolo esistente (solo i campi inviati vengono aggiornati)."""
    circolo = db.query(models.Circolo).filter(models.Circolo.id == circolo_id).first()
    if circolo is None:
        raise HTTPException(status_code=404, detail="Circolo non trovato")

    aggiornamenti = dati.model_dump(exclude_unset=True)
    for campo, valore in aggiornamenti.items():
        setattr(circolo, campo, valore)

    db.commit()
    db.refresh(circolo)
    return _circolo_a_dict(circolo)


@app.delete("/circoli/{circolo_id}")
def elimina_circolo(circolo_id: int, db: Session = Depends(get_db)):
    """
    Elimina definitivamente un circolo, SOLO se non è coinvolto in nessuna
    richiesta attiva o partita passata/futura (per non rompere lo storico
    o le ricerche in corso). In caso contrario, suggerisce di disattivarlo.
    """
    circolo = db.query(models.Circolo).filter(models.Circolo.id == circolo_id).first()
    if circolo is None:
        raise HTTPException(status_code=404, detail="Circolo non trovato")

    ha_richieste_collegate = (
        db.query(models.RichiestaCircolo)
        .filter(models.RichiestaCircolo.circolo_id == circolo_id)
        .first()
    ) is not None
    ha_gruppi_collegati = (
        db.query(models.Gruppo).filter(models.Gruppo.circolo_id == circolo_id).first()
    ) is not None
    ha_partite_collegate = (
        db.query(models.Partita).filter(models.Partita.circolo_id == circolo_id).first()
    ) is not None

    if ha_richieste_collegate or ha_gruppi_collegati or ha_partite_collegate:
        raise HTTPException(
            status_code=409,
            detail="Questo circolo è collegato a richieste, gruppi o partite esistenti "
                   "e non può essere eliminato definitivamente. Puoi disattivarlo invece "
                   "(non comparirà più tra le scelte per nuove richieste, ma lo storico resta intatto)."
        )

    db.delete(circolo)
    db.commit()
    return {"messaggio": "Circolo eliminato definitivamente."}


def _cerca_partite_per_report(
    db: Session,
    giorno_da: str | None,
    giorno_a: str | None,
    circolo_id: int | None,
    giocatore: str | None,
    stato: str,
    ordina: str,
    direzione: str,
) -> list[dict]:
    """
    Funzione condivisa tra la visualizzazione a schermo e l'esportazione CSV
    del report partite. Filtra per data, circolo, giocatore (ricerca parziale
    su nome+cognome) e stato, poi ordina secondo il criterio richiesto.
    """
    query = db.query(models.Partita)
    if stato:
        query = query.filter(models.Partita.stato == stato)
    if giorno_da:
        try:
            data_da = datetime.strptime(giorno_da, "%Y-%m-%d").date()
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Data non valida: '{giorno_da}', usa il formato AAAA-MM-GG")
        query = query.filter(models.Partita.giorno >= data_da)
    if giorno_a:
        try:
            data_a = datetime.strptime(giorno_a, "%Y-%m-%d").date()
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Data non valida: '{giorno_a}', usa il formato AAAA-MM-GG")
        query = query.filter(models.Partita.giorno <= data_a)
    if circolo_id:
        query = query.filter(models.Partita.circolo_id == circolo_id)

    partite = query.all()

    risultato = []
    for p in partite:
        circolo = db.query(models.Circolo).filter(models.Circolo.id == p.circolo_id).first()
        gruppo = (
            db.query(models.Gruppo)
            .options(joinedload(models.Gruppo.membri).joinedload(models.GruppoMembro.utente))
            .filter(models.Gruppo.id == p.gruppo_id)
            .first()
        )
        giocatori = [f"{m.utente.nome} {m.utente.cognome}" for m in gruppo.membri] if gruppo else []

        if giocatore:
            testo_ricerca = giocatore.lower()
            if not any(testo_ricerca in g.lower() for g in giocatori):
                continue

        risultato.append({
            "partita_id": p.id,
            "giorno": str(p.giorno),
            "orario": str(p.ora_inizio),
            "circolo_nome": circolo.nome if circolo else "?",
            "giocatori": giocatori,
            "stato": p.stato,
        })

    reverse = (direzione == "desc")
    if ordina == "circolo":
        risultato.sort(key=lambda r: r["circolo_nome"].lower(), reverse=reverse)
    elif ordina == "giocatore":
        risultato.sort(key=lambda r: (r["giocatori"][0].lower() if r["giocatori"] else ""), reverse=reverse)
    else:  # default: giorno (+ orario come criterio secondario)
        risultato.sort(key=lambda r: (r["giorno"], r["orario"]), reverse=reverse)

    return risultato


@app.get("/admin/report-partite")
def report_partite(
    giorno_da: str | None = None,
    giorno_a: str | None = None,
    circolo_id: int | None = None,
    giocatore: str | None = None,
    stato: str = "GIOCATA",
    ordina: str = "giorno",
    direzione: str = "desc",
    db: Session = Depends(get_db),
):
    """
    Restituisce l'elenco delle partite (di default quelle concluse, stato
    GIOCATA) filtrate e ordinate secondo i parametri passati. Usato dalla
    pagina di report del pannello operatore.
    """
    return _cerca_partite_per_report(db, giorno_da, giorno_a, circolo_id, giocatore, stato, ordina, direzione)


@app.get("/admin/report-partite/export")
def esporta_report_partite_csv(
    giorno_da: str | None = None,
    giorno_a: str | None = None,
    circolo_id: int | None = None,
    giocatore: str | None = None,
    stato: str = "GIOCATA",
    ordina: str = "giorno",
    direzione: str = "desc",
    db: Session = Depends(get_db),
):
    """
    Stessa ricerca di /admin/report-partite, ma restituisce un file CSV
    scaricabile (si apre direttamente in Excel/Fogli Google) invece del
    JSON per la pagina web.
    """
    righe = _cerca_partite_per_report(db, giorno_da, giorno_a, circolo_id, giocatore, stato, ordina, direzione)

    buffer = io.StringIO()
    scrittore = csv.writer(buffer, delimiter=';')  # ';' per compatibilità con Excel in italiano
    scrittore.writerow(["Data", "Ora", "Circolo", "Giocatore 1", "Giocatore 2", "Giocatore 3", "Giocatore 4", "Stato"])

    for riga in righe:
        giocatori = riga["giocatori"] + [""] * (4 - len(riga["giocatori"]))  # riempie fino a 4 colonne
        scrittore.writerow([riga["giorno"], riga["orario"], riga["circolo_nome"], *giocatori[:4], riga["stato"]])

    contenuto = buffer.getvalue()
    return Response(
        content=contenuto,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=report_partite.csv"},
    )
