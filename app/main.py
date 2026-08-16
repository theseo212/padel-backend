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

from fastapi import FastAPI, Depends, HTTPException, Request
from fastapi.security import HTTPBasic, HTTPBasicCredentials
import secrets
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
from app.services.email_service import invia_email_contatto
from app.matching.motore import esegui_ciclo_matching
from app.matching.gestione_gruppi import rispondi_a_gruppo, controlla_timeout_gruppi, rispondi_a_gruppo_da_whatsapp
from app.matching.prenotazione import conferma_prenotazione, fallisce_prenotazione
from app.matching.feedback import (
    segna_partita_giocata, registra_feedback, controlla_cicli_feedback,
    controlla_partite_da_segnare_automaticamente, rispondi_feedback_da_whatsapp,
)
from app.matching.promemoria_disponibilita import controlla_promemoria_mancata_partita

app = FastAPI(title="AnnaPadel")

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

_sicurezza_admin = HTTPBasic()


def verifica_credenziali_admin(credenziali: HTTPBasicCredentials = Depends(_sicurezza_admin)):
    """
    Protegge il pannello operatore e tutte le azioni amministrative con
    nome utente e password (autenticazione HTTP Basic - il browser mostra
    un piccolo popup di accesso al primo utilizzo, poi ricorda le
    credenziali per le richieste successive sulla stessa pagina).

    Usa secrets.compare_digest invece di un semplice "==" per confrontare
    le password: un confronto normale potrebbe rivelare, tramite il tempo
    impiegato a rispondere, quanti caratteri sono corretti (un attacco
    noto come "timing attack") - compare_digest impiega sempre lo stesso
    tempo, indipendentemente da quanto la password è vicina a quella giusta.
    """
    utente_corretto = secrets.compare_digest(credenziali.username, config.ADMIN_USERNAME)
    password_corretta = secrets.compare_digest(credenziali.password, config.ADMIN_PASSWORD)

    if not (utente_corretto and password_corretta):
        raise HTTPException(
            status_code=401,
            detail="Credenziali non valide",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credenziali.username


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


def job_promemoria_mancata_partita():
    """
    Funzione eseguita automaticamente ogni 5 minuti: avvisa gli utenti
    che, a un'ora dall'inizio della loro fascia oraria, non hanno ancora
    trovato una partita.
    """
    db = SessionLocal()
    try:
        n = controlla_promemoria_mancata_partita(db)
        if n:
            print(f"[PROMEMORIA] {n} promemoria di mancata partita inviati.")
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
    # (la tabella messaggi_contatto invece è nuova: create_all la crea da
    # sola, non serve nessuna riga qui sotto per lei)
    with engine.connect() as connessione:
        connessione.execute(text("ALTER TABLE circoli ADD COLUMN IF NOT EXISTS provincia VARCHAR(10)"))
        connessione.execute(text(
            "ALTER TABLE richieste ADD COLUMN IF NOT EXISTS promemoria_mancata_partita_inviato BOOLEAN DEFAULT FALSE"
        ))
        # Bug corretto: il bitmask usa fino al bit 31, che supera il massimo
        # di un INTEGER con segno. BIGINT lo gestisce correttamente.
        connessione.execute(text(
            "ALTER TABLE richieste ALTER COLUMN disponibilita_bitmask TYPE BIGINT"
        ))
        connessione.execute(text(
            "ALTER TABLE utenti ADD COLUMN IF NOT EXISTS termini_accettati BOOLEAN DEFAULT FALSE"
        ))
        connessione.execute(text(
            "ALTER TABLE utenti ADD COLUMN IF NOT EXISTS privacy_accettata BOOLEAN DEFAULT FALSE"
        ))
        connessione.execute(text(
            "ALTER TABLE utenti ADD COLUMN IF NOT EXISTS data_accettazione_termini TIMESTAMP"
        ))
        connessione.execute(text(
            "ALTER TABLE messaggi_contatto ADD COLUMN IF NOT EXISTS telefono VARCHAR(30) NOT NULL DEFAULT ''"
        ))
        connessione.execute(text(
            "ALTER TABLE circoli ADD COLUMN IF NOT EXISTS gmaps_url VARCHAR(500)"
        ))
        connessione.execute(text(
            "ALTER TABLE circoli ADD COLUMN IF NOT EXISTS costo_servizio NUMERIC(3,2)"
        ))
        connessione.execute(text(
            "ALTER TABLE gruppi ADD COLUMN IF NOT EXISTS codice_conferma_circolo VARCHAR(20)"
        ))
        connessione.execute(text(
            "ALTER TABLE gruppi ADD COLUMN IF NOT EXISTS data_richiesta_prenotazione TIMESTAMP"
        ))
        connessione.execute(text(
            "ALTER TABLE gruppi ADD COLUMN IF NOT EXISTS numero_campo VARCHAR(20)"
        ))
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
    scheduler.add_job(
        job_promemoria_mancata_partita,
        "interval",
        minutes=5,
        id="promemoria_mancata_partita",
    )
    scheduler.start()


@app.on_event("shutdown")
def ferma_scheduler():
    scheduler.shutdown()


@app.get("/")
def home():
    return {"messaggio": "Il server è acceso e funzionante."}


@app.get("/admin", dependencies=[Depends(verifica_credenziali_admin)])
def pannello_operatore():
    """Serve la pagina web del pannello operatore."""
    import os
    percorso = os.path.join(os.path.dirname(__file__), "static", "admin.html")
    return FileResponse(percorso)


@app.get("/admin/report", dependencies=[Depends(verifica_credenziali_admin)])
def pagina_report():
    """Serve la pagina web del report partite."""
    import os
    percorso = os.path.join(os.path.dirname(__file__), "static", "report.html")
    return FileResponse(percorso)


@app.get("/admin/contatti", dependencies=[Depends(verifica_credenziali_admin)])
def pagina_admin_contatti():
    """Serve la pagina web dei messaggi ricevuti dal form Contatti."""
    import os
    percorso = os.path.join(os.path.dirname(__file__), "static", "admin_contatti.html")
    return FileResponse(percorso)


@app.get("/admin/circoli", dependencies=[Depends(verifica_credenziali_admin)])
def pagina_admin_circoli():
    """Serve la pagina web della gestione circoli."""
    import os
    percorso = os.path.join(os.path.dirname(__file__), "static", "admin_circoli.html")
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

    # --- 2bis. Accettazione Termini e Condizioni + Privacy Policy ---
    # Richiesta obbligatoria solo finché l'utente non li ha già accettati una
    # volta (poi resta registrata per sempre, non si richiede più - stesso
    # principio del livello: una scelta fissata che non serve ripetere).
    if not utente.termini_accettati or not utente.privacy_accettata:
        if not (dati.accetta_termini and dati.accetta_privacy):
            raise HTTPException(
                status_code=400,
                detail="Devi accettare i Termini e Condizioni e la Privacy Policy per continuare."
            )
        utente.termini_accettati = True
        utente.privacy_accettata = True
        utente.data_accettazione_termini = datetime.utcnow()

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
        otp_inviato_davvero = invia_otp_whatsapp(utente.whatsapp_numero, codice)

        if not otp_inviato_davvero:
            # L'invio è fallito per davvero (es. limite giornaliero di
            # conversazioni WhatsApp superato): meglio annullare tutto
            # ed essere onesti, invece di lasciare un account "a metà"
            # che aspetta per sempre un codice mai arrivato.
            db.rollback()
            raise HTTPException(
                status_code=503,
                detail="Il servizio WhatsApp è temporaneamente al completo (troppe nuove "
                       "richieste oggi). Riprova tra qualche ora."
            )

        db.commit()
        return schemas.RichiestaResponse(
            richiesta_id=richiesta.id,
            utente_nuovo=utente_nuovo,
            richiede_validazione_otp=True,
            messaggio="Richiesta salvata. Ti ho appena inviato un codice di verifica su WhatsApp.",
        )

    else:
        fasce_leggibili = ", ".join(bitmask_a_fasce_leggibili(bitmask))
        lato_leggibile = {"DX": "Destra", "SX": "Sinistra", "INDIFFERENTE": "Indifferente"}.get(
            utente.lato_preferito, utente.lato_preferito
        )
        riepilogo = (
            f"Ciao {utente.nome}, ho registrato la tua richiesta!\n"
            f"{dati.tipo_partita} - {dati.giorno}\n"
            f"Orari: {fasce_leggibili}\n"
            f"Livello: {utente.livello_playtomic}\n"
            f"Lato: {lato_leggibile}\n"
            f"Circoli: {', '.join(c.nome for c in circoli)}\n\n"
            f"Io non ti disturberò più con altri messaggi finché non avrò formato la partita giusta per te. "
            f"Quando sarà pronta ti manderò un messaggio per avere la tua conferma e poter prenotare il campo.\n"
            f"Attenzione: avrai solo 15 minuti per dare questa tua conferma!!\n"
            f"Se nel frattempo vuoi vedere il riassunto e lo stato delle tue richieste, usa il pulsante qui sotto."
        )
        riepilogo_inviato_davvero = invia_riepilogo_richiesta(
            utente.whatsapp_numero, riepilogo,
            nome=utente.nome, tipo_partita=dati.tipo_partita, giorno=str(dati.giorno),
            orari=fasce_leggibili, livello=str(utente.livello_playtomic),
            lato=lato_leggibile, circoli=', '.join(c.nome for c in circoli),
        )
        # Qui la richiesta è comunque valida e verrà comunque cercata dal
        # matching, quindi NON la annulliamo se manca solo la conferma
        # WhatsApp - siamo semplicemente onesti nel messaggio di risposta.
        messaggio_risposta = (
            "Richiesta salvata e riepilogo inviato su WhatsApp." if riepilogo_inviato_davvero
            else "Richiesta salvata, ma non sono riuscito a mandarti la conferma su WhatsApp "
                 "in questo momento (il servizio è temporaneamente al completo). La tua "
                 "richiesta resta comunque attiva e verrà elaborata normalmente."
        )
        db.commit()
        return schemas.RichiestaResponse(
            richiesta_id=richiesta.id,
            utente_nuovo=utente_nuovo,
            richiede_validazione_otp=False,
            messaggio=messaggio_risposta,
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

    # Il riepilogo non era ancora stato mandato per questa primissima
    # richiesta (era stato inviato solo l'OTP): lo mandiamo ora, recuperando
    # i dati dell'ultima richiesta inserita da questo utente - così la
    # promessa mostrata nel form ("riceverai anche su WhatsApp una conferma
    # con questo riepilogo") viene mantenuta anche al primissimo utilizzo.
    ultima_richiesta = (
        db.query(models.Richiesta)
        .filter(models.Richiesta.utente_id == utente.id)
        .order_by(models.Richiesta.data_creazione.desc())
        .first()
    )
    if ultima_richiesta is not None:
        fasce_leggibili = ", ".join(bitmask_a_fasce_leggibili(ultima_richiesta.disponibilita_bitmask))
        lato_leggibile = {"DX": "Destra", "SX": "Sinistra", "INDIFFERENTE": "Indifferente"}.get(
            utente.lato_preferito, utente.lato_preferito
        )
        riepilogo = (
            f"Perfetto {utente.nome}, numero verificato! Ecco il riepilogo della tua richiesta:\n"
            f"{ultima_richiesta.tipo_partita} - {ultima_richiesta.giorno}\n"
            f"Orari: {fasce_leggibili}\n"
            f"Livello: {utente.livello_playtomic}\n"
            f"Lato: {lato_leggibile}\n"
            f"Circoli: {', '.join(c.nome for c in ultima_richiesta.circoli)}\n\n"
            f"Io non ti disturberò più con altri messaggi finché non avrò formato la partita giusta per te. "
            f"Quando sarà pronta ti manderò un messaggio per avere la tua conferma e poter prenotare il campo.\n"
            f"Attenzione: avrai solo 15 minuti per dare questa tua conferma!!\n"
            f"Se nel frattempo vuoi vedere il riassunto e lo stato delle tue richieste, usa il pulsante qui sotto."
        )
        invia_riepilogo_richiesta(
            utente.whatsapp_numero, riepilogo,
            nome=utente.nome, tipo_partita=ultima_richiesta.tipo_partita, giorno=str(ultima_richiesta.giorno),
            orari=fasce_leggibili, livello=str(utente.livello_playtomic),
            lato=lato_leggibile, circoli=', '.join(c.nome for c in ultima_richiesta.circoli),
        )

    return {"messaggio": "Numero verificato con successo."}


def _annulla_richiesta_logica(richiesta_id: int, db: Session) -> dict:
    """
    Logica condivisa tra l'endpoint POST (usato dal form web) e quello
    GET (usato dal link cliccabile nei messaggi WhatsApp): annulla una
    richiesta gestendo diversamente i casi IN_RICERCA e LOCKED.
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


@app.post("/richieste/{richiesta_id}/annulla")
def annulla_richiesta(richiesta_id: int, db: Session = Depends(get_db)):
    """
    Permette a un utente di annullare una propria richiesta, tipicamente
    dopo essere stato avvisato di averne già una attiva per lo stesso giorno.
    Usato dal form web (chiamata JSON, non un semplice link).
    """
    return _annulla_richiesta_logica(richiesta_id, db)


@app.get("/richieste/{richiesta_id}/annulla-da-link")
def annulla_richiesta_da_link(richiesta_id: int, db: Session = Depends(get_db)):
    """
    Versione "cliccabile" dell'annullamento, pensata per i link dentro i
    messaggi WhatsApp (dove serve un semplice click, non una chiamata
    tecnica). Mostra una pagina HTML minimale di conferma invece di un JSON.
    """
    try:
        risultato = _annulla_richiesta_logica(richiesta_id, db)
        messaggio = risultato.get("messaggio", "Operazione completata.")
        colore = "#1a7a3a"
    except HTTPException as errore:
        messaggio = errore.detail if isinstance(errore.detail, str) else "Si è verificato un errore."
        colore = "#a3231f"

    html = f"""
    <!DOCTYPE html>
    <html lang="it">
    <head>
        <meta charset="UTF-8">
        <title>Annullamento richiesta</title>
        <style>
            body {{ font-family: -apple-system, sans-serif; background: #f6f7f8;
                    display: flex; align-items: center; justify-content: center;
                    height: 100vh; margin: 0; padding: 20px; text-align: center; }}
            .box {{ background: white; padding: 28px; border-radius: 12px;
                     max-width: 420px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }}
            p {{ color: {colore}; font-size: 16px; }}
            a {{ display: inline-block; margin-top: 16px; color: #2563eb;
                  text-decoration: none; font-size: 14px; }}
        </style>
    </head>
    <body>
        <div class="box">
            <p>{messaggio}</p>
            <a href="{config.PUBLIC_FORM_URL}">Inserisci una nuova richiesta →</a>
        </div>
    </body>
    </html>
    """
    return Response(content=html, media_type="text/html")


def _orario_leggibile_gruppo(slot_inizio: int) -> str:
    minuti_totali = config.ORA_INIZIO_GIORNATA * 60 + slot_inizio * config.DURATA_SLOT_MINUTI
    ore, minuti = divmod(minuti_totali, 60)
    return f"{ore:02d}:{minuti:02d}"


@app.get("/annulla/{richiesta_id}")
def annulla_richiesta_da_bottone_whatsapp(richiesta_id: int, db: Session = Depends(get_db)):
    """
    Stessa identica funzione di /richieste/{id}/annulla-da-link, ma con
    un indirizzo più corto e con l'ID alla FINE dell'URL - necessario per
    i bottoni "Call to Action" di WhatsApp, che permettono una parte
    variabile solo se è l'ultimo pezzo del link (non è possibile avere
    l'ID nel mezzo, come nell'altra rotta).
    """
    return annulla_richiesta_da_link(richiesta_id, db)


def _pagina_conferma_circolo_html(titolo: str, corpo: str) -> Response:
    """Stile condiviso per tutte le schermate della pagina di conferma circolo."""
    html = f"""
    <!DOCTYPE html>
    <html lang="it">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <title>{titolo}</title>
        <style>
            body {{ font-family: -apple-system, sans-serif; background: #f6f7f8;
                    display: flex; align-items: center; justify-content: center;
                    min-height: 100vh; margin: 0; padding: 20px; }}
            .box {{ background: white; padding: 28px; border-radius: 12px;
                     max-width: 420px; width: 100%; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }}
            h1 {{ font-size: 19px; color: #1B3A63; margin: 0 0 6px; }}
            p {{ color: #444; font-size: 14px; line-height: 1.5; }}
            .dettaglio {{ margin: 4px 0; }}
            label {{ display: block; font-size: 13px; font-weight: 600; margin: 16px 0 6px; color: #333; }}
            input[type="text"] {{ width: 100%; padding: 10px 12px; border: 1px solid #d5d7db;
                     border-radius: 8px; font-size: 15px; box-sizing: border-box; }}
            button {{ width: 100%; padding: 13px; border: none; border-radius: 8px;
                       font-size: 15px; font-weight: 600; cursor: pointer; margin-top: 10px; }}
            .btn-conferma {{ background: #7CB342; color: white; }}
            .btn-fallita {{ background: #fbdcdc; color: #a3231f; }}
            .esito {{ font-size: 16px; font-weight: 600; }}
            .esito.ok {{ color: #1a7a3a; }}
            .esito.errore {{ color: #a3231f; }}
        </style>
    </head>
    <body>
        <div class="box">
            <h1>{titolo}</h1>
            {corpo}
        </div>
    </body>
    </html>
    """
    return Response(content=html, media_type="text/html")


def _carica_gruppo_da_token(token: str, db: Session):
    """
    Divide il token nel suo id gruppo + codice, e verifica che il codice
    corrisponda - è la nostra "chiave d'accesso" al posto di una password,
    dato che questa pagina la usa anche il circolo, senza credenziali.
    """
    try:
        gruppo_id_str, codice = token.rsplit(".", 1)
        gruppo_id = int(gruppo_id_str)
    except (ValueError, IndexError):
        return None, None

    gruppo = (
        db.query(models.Gruppo)
        .options(joinedload(models.Gruppo.membri).joinedload(models.GruppoMembro.utente))
        .filter(models.Gruppo.id == gruppo_id)
        .first()
    )
    if gruppo is None or gruppo.codice_conferma_circolo != codice:
        return None, None
    return gruppo, codice


@app.get("/circolo/conferma/{token}")
def pagina_conferma_circolo(token: str, db: Session = Depends(get_db)):
    """
    Pagina pubblica (nessuna credenziale) raggiungibile dal link mandato
    al circolo e all'operatore: permette di confermare la prenotazione
    (indicando facoltativamente il numero del campo) o segnalare che il
    campo non è disponibile. Il token stesso, con il suo codice casuale,
    fa da chiave d'accesso privata.
    """
    gruppo, _ = _carica_gruppo_da_token(token, db)
    if gruppo is None:
        return _pagina_conferma_circolo_html(
            "Link non valido",
            "<p>Questo link non è valido, o si riferisce a una richiesta che non esiste più.</p>",
        )

    circolo = db.query(models.Circolo).filter(models.Circolo.id == gruppo.circolo_id).first()
    orario = _orario_leggibile_gruppo(gruppo.slot_inizio)
    nomi_giocatori = ", ".join(f"{m.utente.nome} {m.utente.cognome}" for m in gruppo.membri)

    if gruppo.stato != "CONFERMATO":
        # Qualcuno (il circolo stesso da un altro dispositivo, o
        # l'operatore dal pannello) ha già gestito questo gruppo.
        return _pagina_conferma_circolo_html(
            "Già gestito",
            "<p class='esito ok'>✅ Questa prenotazione è già stata gestita in precedenza, non c'è più nulla da fare qui.</p>",
        )

    corpo = f"""
        <p class="dettaglio"><strong>Circolo:</strong> {circolo.nome}</p>
        <p class="dettaglio"><strong>Giorno:</strong> {gruppo.giorno} alle {orario}</p>
        <p class="dettaglio"><strong>Giocatori:</strong> {nomi_giocatori}</p>
        <form method="POST" action="/circolo/conferma/{token}">
            <label for="numero_campo">Numero campo (facoltativo)</label>
            <input type="text" id="numero_campo" name="numero_campo" placeholder="es. 3">
            <label for="orario_effettivo">Hai dovuto spostare l'orario? (facoltativo, lascia vuoto se uguale a quello proposto)</label>
            <input type="text" id="orario_effettivo" name="orario_effettivo" placeholder="es. 16:30">
            <button type="submit" name="azione" value="conferma" class="btn-conferma">Conferma prenotazione</button>
            <button type="submit" name="azione" value="non_disponibile" class="btn-fallita">Campo non disponibile</button>
        </form>
    """
    return _pagina_conferma_circolo_html("Conferma prenotazione campo", corpo)


@app.post("/circolo/conferma/{token}")
async def gestisci_conferma_circolo(token: str, request: Request, db: Session = Depends(get_db)):
    gruppo, _ = _carica_gruppo_da_token(token, db)
    if gruppo is None:
        return _pagina_conferma_circolo_html(
            "Link non valido",
            "<p>Questo link non è valido, o si riferisce a una richiesta che non esiste più.</p>",
        )

    if gruppo.stato != "CONFERMATO":
        return _pagina_conferma_circolo_html(
            "Già gestito",
            "<p class='esito ok'>✅ Questa prenotazione è già stata gestita in precedenza (magari da un'altra persona), non c'è più nulla da fare qui.</p>",
        )

    corpo_form = await request.form()
    azione = corpo_form.get("azione")
    numero_campo = (corpo_form.get("numero_campo") or "").strip() or None
    orario_effettivo = (corpo_form.get("orario_effettivo") or "").strip() or None

    if orario_effettivo:
        import re
        if not re.match(r"^([01]\d|2[0-3]):[0-5]\d$", orario_effettivo):
            return _pagina_conferma_circolo_html(
                "Formato orario non valido",
                "<p class='esito errore'>L'orario va scritto nel formato HH:MM, per esempio 16:30. Torna indietro e riprova.</p>",
            )

    try:
        if azione == "conferma":
            conferma_prenotazione(db, gruppo.id, numero_campo=numero_campo, orario_effettivo=orario_effettivo)
            return _pagina_conferma_circolo_html(
                "Fatto!",
                "<p class='esito ok'>✅ Prenotazione confermata, i 4 giocatori sono stati avvisati. Grazie!</p>",
            )
        elif azione == "non_disponibile":
            fallisce_prenotazione(db, gruppo.id)
            return _pagina_conferma_circolo_html(
                "Segnalato",
                "<p class='esito ok'>Grazie per la segnalazione: i 4 giocatori sono stati avvisati e verranno rimessi in ricerca automaticamente.</p>",
            )
        else:
            return _pagina_conferma_circolo_html("Errore", "<p class='esito errore'>Azione non riconosciuta.</p>")
    except ValueError as errore:
        return _pagina_conferma_circolo_html("Errore", f"<p class='esito errore'>{errore}</p>")


@app.post("/matching/esegui-ora", dependencies=[Depends(verifica_credenziali_admin)])
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


@app.post("/gruppi/{gruppo_id}/rispondi", dependencies=[Depends(verifica_credenziali_admin)])
def rispondi_a_proposta(gruppo_id: int, dati: schemas.RispostaGruppo, db: Session = Depends(get_db)):
    """
    Endpoint dello Step 03: un giocatore conferma o rifiuta una proposta di partita.
    Usato per i test manuali; le risposte reali via WhatsApp arrivano invece
    tramite /webhooks/twilio/incoming.
    """
    try:
        risultato = rispondi_a_gruppo(db, gruppo_id, dati.utente_id, dati.risposta)
    except ValueError as errore:
        raise HTTPException(status_code=400, detail=str(errore))
    return risultato


@app.post("/webhooks/twilio/incoming")
async def webhook_twilio_incoming(request: Request, db: Session = Depends(get_db)):
    """
    Riceve i messaggi in arrivo su WhatsApp (es. quando un utente preme
    il bottone Conferma o Rifiuta su una proposta di partita). Va
    configurato come "webhook URL" per i messaggi in arrivo, nel pannello
    Twilio (sezione WhatsApp Sender).

    Verifica la firma di Twilio per essere sicuri che la richiesta arrivi
    davvero da loro (altrimenti chiunque conoscesse questo indirizzo
    potrebbe inviare risposte false a nome di un utente). La verifica
    viene saltata solo se TWILIO_AUTH_TOKEN non è configurato (utile per
    testare l'endpoint in locale senza credenziali reali).
    """
    corpo_form = await request.form()
    dati = dict(corpo_form)

    if config.TWILIO_AUTH_TOKEN:
        from twilio.request_validator import RequestValidator
        validatore = RequestValidator(config.TWILIO_AUTH_TOKEN)
        firma = request.headers.get("X-Twilio-Signature", "")

        # Railway (come molti servizi simili) riceve le richieste in HTTPS
        # dall'esterno, ma le inoltra internamente come HTTP - senza questa
        # correzione, l'indirizzo usato per calcolare la firma non
        # corrisponderebbe MAI a quello vero usato da Twilio per firmare,
        # facendo fallire la verifica per ogni singola richiesta reale.
        url_da_verificare = str(request.url)
        proto_originale = request.headers.get("x-forwarded-proto")
        if proto_originale and url_da_verificare.startswith("http://"):
            url_da_verificare = url_da_verificare.replace("http://", f"{proto_originale}://", 1)

        valido = validatore.validate(url_da_verificare, dati, firma)
        if not valido:
            raise HTTPException(status_code=403, detail="Firma Twilio non valida")

    numero_mittente = dati.get("From", "").replace("whatsapp:", "")
    testo_messaggio = dati.get("Body", "")

    try:
        rispondi_a_gruppo_da_whatsapp(db, numero_mittente, testo_messaggio)
    except ValueError:
        # Non era una risposta a una proposta di gruppo in corso: proviamo
        # a interpretarlo come un voto di valutazione livello (Step 04).
        try:
            rispondi_feedback_da_whatsapp(db, numero_mittente, testo_messaggio)
        except ValueError as errore:
            # Nemmeno questo: non è un errore del server, es. un messaggio
            # che non c'entra nulla. Lo logghiamo e rispondiamo comunque 200
            # a Twilio (altrimenti riproverebbe a inviarcelo).
            print(f"[WEBHOOK TWILIO] Messaggio non gestito da {numero_mittente}: {errore}")

    return Response(content="<Response></Response>", media_type="application/xml")


@app.post("/matching/controlla-timeout-ora", dependencies=[Depends(verifica_credenziali_admin)])
def controlla_timeout_manuale(db: Session = Depends(get_db)):
    """Endpoint SOLO PER TEST: forza il controllo dei timeout invece di aspettare lo scheduler."""
    n = controlla_timeout_gruppi(db)
    return {"gruppi_annullati_per_timeout": n}


@app.post("/gruppi/{gruppo_id}/prenotazione/conferma", dependencies=[Depends(verifica_credenziali_admin)])
def prenotazione_confermata(gruppo_id: int, orario_effettivo: str | None = None, db: Session = Depends(get_db)):
    """
    Endpoint per l'OPERATORE (Step 04, punto 15): usato quando ha verificato
    che il campo è disponibile e ha effettuato la prenotazione sul circolo.
    'orario_effettivo' (facoltativo, es. "16:30") serve se ha dovuto
    spostare leggermente l'orario rispetto a quello inizialmente proposto.
    """
    try:
        partita = conferma_prenotazione(db, gruppo_id, orario_effettivo=orario_effettivo)
    except ValueError as errore:
        raise HTTPException(status_code=400, detail=str(errore))
    return {"partita_id": partita.id, "stato": partita.stato}


@app.post("/gruppi/{gruppo_id}/prenotazione/fallita", dependencies=[Depends(verifica_credenziali_admin)])
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


@app.post("/partite/{partita_id}/segna-giocata", dependencies=[Depends(verifica_credenziali_admin)])
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


@app.post("/partite/{partita_id}/feedback", dependencies=[Depends(verifica_credenziali_admin)])
def invia_feedback(partita_id: int, dati: schemas.FeedbackCreate, db: Session = Depends(get_db)):
    """Un giocatore invia il proprio voto su un compagno di partita."""
    try:
        registra_feedback(db, partita_id, dati.votante_id, dati.votato_id, dati.voto)
    except ValueError as errore:
        raise HTTPException(status_code=400, detail=str(errore))
    return {"messaggio": "Voto registrato."}


@app.post("/feedback/controlla-cicli-ora", dependencies=[Depends(verifica_credenziali_admin)])
def controlla_feedback_manuale(db: Session = Depends(get_db)):
    """Endpoint SOLO PER TEST: forza il controllo dei cicli di feedback."""
    n = controlla_cicli_feedback(db)
    return {"finestre_chiuse": n}


@app.post("/partite/controlla-concluse-ora", dependencies=[Depends(verifica_credenziali_admin)])
def controlla_partite_concluse_manuale(db: Session = Depends(get_db)):
    """Endpoint SOLO PER TEST: forza il controllo automatico delle partite concluse."""
    n = controlla_partite_da_segnare_automaticamente(db)
    return {"partite_segnate_automaticamente": n}


@app.post("/richieste/controlla-promemoria-ora", dependencies=[Depends(verifica_credenziali_admin)])
def controlla_promemoria_manuale(db: Session = Depends(get_db)):
    """Endpoint SOLO PER TEST: forza il controllo del promemoria mancata partita."""
    n = controlla_promemoria_mancata_partita(db)
    return {"promemoria_inviati": n}


@app.get("/admin/gruppi-da-prenotare", dependencies=[Depends(verifica_credenziali_admin)])
def lista_gruppi_da_prenotare(db: Session = Depends(get_db)):
    """
    Restituisce tutti i gruppi CONFERMATI in attesa che l'operatore
    verifichi la disponibilità del campo e confermi/annulli la prenotazione.
    """
    from sqlalchemy.orm import joinedload
    from zoneinfo import ZoneInfo

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

        ora_invio_leggibile = None
        if g.data_richiesta_prenotazione:
            # Il database salva in UTC - la convertiamo nell'ora italiana
            # vera (gestisce da sola l'ora legale/solare, niente offset
            # fisso scritto a mano che diventerebbe sbagliato in inverno).
            ora_italiana = g.data_richiesta_prenotazione.replace(tzinfo=ZoneInfo("UTC")).astimezone(ZoneInfo("Europe/Rome"))
            ora_invio_leggibile = ora_italiana.strftime("%H:%M")

        giocatori_con_fascia = []
        for m in g.membri:
            richiesta = db.query(models.Richiesta).filter(models.Richiesta.id == m.richiesta_id).first()
            fascia = ", ".join(bitmask_a_fasce_leggibili(richiesta.disponibilita_bitmask)) if richiesta else "?"
            giocatori_con_fascia.append(f"{m.utente.nome} {m.utente.cognome} ({fascia})")

        risultato.append({
            "gruppo_id": g.id,
            "circolo_nome": circolo.nome if circolo else "?",
            "giorno": str(g.giorno),
            "orario": f"{ore:02d}:{minuti:02d}",
            "giocatori": giocatori_con_fascia,
            "ora_invio": ora_invio_leggibile,
        })
    return risultato


@app.get("/admin/partite-da-segnare", dependencies=[Depends(verifica_credenziali_admin)])
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
        "gmaps_url": c.gmaps_url,
        "costo_servizio": float(c.costo_servizio) if c.costo_servizio is not None else None,
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


@app.post("/circoli", dependencies=[Depends(verifica_credenziali_admin)])
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
        gmaps_url=dati.gmaps_url,
        costo_servizio=dati.costo_servizio,
        attivo=True,
    )
    db.add(circolo)
    db.commit()
    db.refresh(circolo)
    return _circolo_a_dict(circolo)


@app.put("/circoli/{circolo_id}", dependencies=[Depends(verifica_credenziali_admin)])
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


@app.delete("/circoli/{circolo_id}", dependencies=[Depends(verifica_credenziali_admin)])
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


@app.get("/admin/report-partite", dependencies=[Depends(verifica_credenziali_admin)])
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


@app.get("/admin/report-partite/export", dependencies=[Depends(verifica_credenziali_admin)])
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


@app.post("/contatti")
def invia_messaggio_contatto(dati: schemas.ContattoCreate, db: Session = Depends(get_db)):
    """
    Endpoint pubblico del form Contatti. Il messaggio viene SEMPRE salvato
    nel database (backup permanente), e viene comunque tentato l'invio
    dell'email vera alla casella configurata. Anche se l'email dovesse
    fallire, il messaggio non va perso: resta visibile nel pannello.
    """
    email_inviata = invia_email_contatto(dati.nome, dati.email, dati.telefono, dati.messaggio)

    messaggio_salvato = models.MessaggioContatto(
        nome=dati.nome,
        email_mittente=dati.email,
        telefono=dati.telefono,
        messaggio=dati.messaggio,
        email_inviata_con_successo=email_inviata,
    )
    db.add(messaggio_salvato)
    db.commit()

    return {
        "messaggio": "Grazie! Ho ricevuto il tuo messaggio, ti risponderò il prima possibile.",
    }


@app.get("/admin/messaggi-contatto", dependencies=[Depends(verifica_credenziali_admin)])
def lista_messaggi_contatto(db: Session = Depends(get_db)):
    """Restituisce tutti i messaggi ricevuti dal form Contatti, i più recenti per primi."""
    messaggi = (
        db.query(models.MessaggioContatto)
        .order_by(models.MessaggioContatto.data_invio.desc())
        .all()
    )
    return [
        {
            "id": m.id,
            "nome": m.nome,
            "email": m.email_mittente,
            "telefono": m.telefono,
            "messaggio": m.messaggio,
            "email_inviata": m.email_inviata_con_successo,
            "data": m.data_invio.isoformat() if m.data_invio else None,
        }
        for m in messaggi
    ]


def _conta_persone_compatibili(db: Session, richiesta: models.Richiesta) -> int:
    """
    Conta quante ALTRE richieste attive (IN_RICERCA) sono potenzialmente
    compatibili con questa: stesso giorno, stesso tipo partita, almeno un
    circolo in comune, fascia oraria che si sovrappone, livello entro la
    tolleranza attuale di una delle due.

    Attenzione: "compatibile con questa richiesta" NON significa che si
    formerà per forza un gruppo - servirebbe che tutte e 4 le persone
    fossero compatibili anche TRA loro (non solo con questa), e che i lati
    DX/SX si distribuiscano correttamente. È quindi un indicatore di
    quanta "gente in giro" c'è con caratteristiche simili, onesto ma non
    una promessa di match garantito - per questo lo chiamiamo "persone
    potenzialmente compatibili", non "persone con cui giocherai".
    """
    altre_richieste = (
        db.query(models.Richiesta)
        .options(joinedload(models.Richiesta.utente), joinedload(models.Richiesta.circoli))
        .filter(
            models.Richiesta.id != richiesta.id,
            models.Richiesta.utente_id != richiesta.utente_id,
            models.Richiesta.stato == "IN_RICERCA",
            models.Richiesta.giorno == richiesta.giorno,
            models.Richiesta.tipo_partita == richiesta.tipo_partita,
        )
        .all()
    )

    circoli_richiesta = set(c.id for c in richiesta.circoli)
    conteggio = 0
    for altra in altre_richieste:
        if not (altra.disponibilita_bitmask & richiesta.disponibilita_bitmask):
            continue
        if not (set(c.id for c in altra.circoli) & circoli_richiesta):
            continue
        tolleranza_effettiva = max(float(richiesta.tolleranza_corrente), float(altra.tolleranza_corrente))
        if abs(float(altra.utente.livello_playtomic) - float(richiesta.utente.livello_playtomic)) > tolleranza_effettiva:
            continue
        conteggio += 1

    return conteggio


def _probabilita_da_conteggio(conteggio: int) -> str:
    """Traduce il numero di persone compatibili in un'etichetta comprensibile."""
    if conteggio >= 13:
        return "Ottime"
    if conteggio >= 8:
        return "Molto buone"
    if conteggio >= 5:
        return "Buone"
    if conteggio >= 3:
        return "Sufficienti"
    return "Scarse"


@app.get("/stato-richieste/{numero_whatsapp}")
def stato_richieste_utente(numero_whatsapp: str, db: Session = Depends(get_db)):
    """
    Pagina di stato pubblica per un utente: mostra le sue richieste ancora
    IN_RICERCA (non ancora abbinate), con un'indicazione onesta di quanta
    "gente compatibile" c'è in giro in questo momento. Raggiungibile dal
    link nel messaggio WhatsApp di riepilogo, usando il numero come
    identificativo (nessuna password: il link stesso, ricevuto privatamente
    su WhatsApp, fa da chiave d'accesso).
    """
    utente = db.query(models.Utente).filter(models.Utente.whatsapp_numero == numero_whatsapp).first()
    if utente is None:
        raise HTTPException(status_code=404, detail="Nessun utente trovato con questo numero")

    richieste = (
        db.query(models.Richiesta)
        .options(joinedload(models.Richiesta.circoli))
        .filter(
            models.Richiesta.utente_id == utente.id,
            models.Richiesta.stato == "IN_RICERCA",
        )
        .order_by(models.Richiesta.giorno)
        .all()
    )

    risultato = []
    for r in richieste:
        conteggio = _conta_persone_compatibili(db, r)
        risultato.append({
            "id": r.id,
            "giorno": str(r.giorno),
            "fasce_orarie": ", ".join(bitmask_a_fasce_leggibili(r.disponibilita_bitmask)),
            "tipo_partita": r.tipo_partita,
            "persone_compatibili": conteggio,
            "probabilita": _probabilita_da_conteggio(conteggio),
        })

    return {"nome": utente.nome, "richieste": risultato}


# === PANNELLO DATABASE (tipo "phpMyAdmin" semplificato) ===
# Un sistema GENERICO (non 11 endpoint separati da mantenere): legge le
# colonne di qualsiasi tabella direttamente dai modelli SQLAlchemy, così
# funziona automaticamente anche per tabelle future, senza dover
# aggiornare questo file ogni volta che cambia qualcosa.
#
# ATTENZIONE: è uno strumento potente e diretto sul database reale - va
# usato con cautela (l'interfaccia lo ricorda chiaramente all'operatore).

from sqlalchemy import inspect as sa_inspect
from sqlalchemy.exc import IntegrityError
from datetime import date as _date_type, time as _time_type
import decimal as _decimal_modulo

TABELLE_DB = {
    "utenti": models.Utente,
    "circoli": models.Circolo,
    "richieste": models.Richiesta,
    "richieste_circoli": models.RichiestaCircolo,
    "gruppi": models.Gruppo,
    "gruppi_membri": models.GruppoMembro,
    "partite": models.Partita,
    "feedback_livello": models.FeedbackLivello,
    "storico_livello": models.StoricoLivello,
    "conversione_wansport_playtomic": models.ConversioneWansportPlaytomic,
    "messaggi_contatto": models.MessaggioContatto,
}


def _chiavi_primarie_tabella(modello) -> list[str]:
    return [colonna.name for colonna in sa_inspect(modello).primary_key]


def _riga_a_dict_generico(riga) -> dict:
    """Converte una riga qualsiasi in un dizionario semplice, pronto per il JSON."""
    risultato = {}
    for colonna in riga.__table__.columns:
        valore = getattr(riga, colonna.name)
        if valore is not None and not isinstance(valore, (str, int, float, bool)):
            valore = str(valore)  # date, orari, importi, ecc. -> testo leggibile
        risultato[colonna.name] = valore
    return risultato


def _converti_valore_per_colonna(colonna, valore_testo: str):
    """Converte il testo ricevuto dal form nel tipo Python giusto per quella colonna."""
    if valore_testo == "" or valore_testo is None:
        return None
    tipo = colonna.type.python_type
    if tipo is bool:
        return valore_testo.strip().lower() in ("true", "1", "si", "sì", "t", "yes")
    if tipo is int:
        return int(valore_testo)
    if tipo is float:
        return float(valore_testo)
    if tipo is _decimal_modulo.Decimal:
        return _decimal_modulo.Decimal(valore_testo)
    if tipo is _date_type:
        return _date_type.fromisoformat(valore_testo)
    if tipo is datetime:
        return datetime.fromisoformat(valore_testo)
    if tipo is _time_type:
        return _time_type.fromisoformat(valore_testo)
    return valore_testo


@app.get("/admin/db/tabelle", dependencies=[Depends(verifica_credenziali_admin)])
def lista_tabelle_db():
    """Elenco dei nomi di tutte le tabelle gestibili da questo pannello."""
    return sorted(TABELLE_DB.keys())


@app.get("/admin/db/tabelle/{nome_tabella}", dependencies=[Depends(verifica_credenziali_admin)])
def leggi_tabella_db(nome_tabella: str, db: Session = Depends(get_db)):
    """Restituisce tutte le righe di una tabella, con nomi colonne e chiavi primarie."""
    modello = TABELLE_DB.get(nome_tabella)
    if modello is None:
        raise HTTPException(status_code=404, detail="Tabella non trovata")

    righe = db.query(modello).all()
    return {
        "colonne": [c.name for c in modello.__table__.columns],
        "chiavi_primarie": _chiavi_primarie_tabella(modello),
        "righe": [_riga_a_dict_generico(r) for r in righe],
    }


@app.put("/admin/db/tabelle/{nome_tabella}", dependencies=[Depends(verifica_credenziali_admin)])
def modifica_riga_db(nome_tabella: str, dati: dict, db: Session = Depends(get_db)):
    """
    Modifica una riga. 'dati' contiene tutti i campi della riga (nuovi
    valori) più '_chiavi_originali' per identificare QUALE riga modificare
    (necessario per le tabelle con chiave primaria composta, es.
    richieste_circoli, dove non basta un singolo 'id').
    """
    modello = TABELLE_DB.get(nome_tabella)
    if modello is None:
        raise HTTPException(status_code=404, detail="Tabella non trovata")

    chiavi_primarie = _chiavi_primarie_tabella(modello)
    chiavi_originali = dati.pop("_chiavi_originali", {})

    query = db.query(modello)
    for chiave in chiavi_primarie:
        query = query.filter(getattr(modello, chiave) == chiavi_originali.get(chiave))
    riga = query.first()
    if riga is None:
        raise HTTPException(status_code=404, detail="Riga non trovata")

    colonne_per_nome = {c.name: c for c in modello.__table__.columns}
    for nome_campo, valore in dati.items():
        if nome_campo not in colonne_per_nome:
            continue
        try:
            setattr(riga, nome_campo, _converti_valore_per_colonna(colonne_per_nome[nome_campo], valore))
        except (ValueError, TypeError) as errore:
            raise HTTPException(status_code=400, detail=f"Valore non valido per '{nome_campo}': {errore}")

    try:
        db.commit()
    except IntegrityError as errore:
        db.rollback()
        raise HTTPException(status_code=409, detail=f"Modifica non consentita dal database: {errore.orig}")

    return {"messaggio": "Riga modificata con successo."}


@app.delete("/admin/db/tabelle/{nome_tabella}", dependencies=[Depends(verifica_credenziali_admin)])
def elimina_riga_db(nome_tabella: str, chiavi: dict, db: Session = Depends(get_db)):
    """Elimina una riga, identificata dalle sue chiavi primarie (una o più colonne)."""
    modello = TABELLE_DB.get(nome_tabella)
    if modello is None:
        raise HTTPException(status_code=404, detail="Tabella non trovata")

    chiavi_primarie = _chiavi_primarie_tabella(modello)
    query = db.query(modello)
    for chiave in chiavi_primarie:
        query = query.filter(getattr(modello, chiave) == chiavi.get(chiave))
    riga = query.first()
    if riga is None:
        raise HTTPException(status_code=404, detail="Riga non trovata")

    try:
        db.delete(riga)
        db.commit()
    except IntegrityError as errore:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail=f"Impossibile eliminare: questa riga è collegata ad altri dati ({errore.orig})"
        )

    return {"messaggio": "Riga eliminata con successo."}


@app.get("/admin/database", dependencies=[Depends(verifica_credenziali_admin)])
def pagina_admin_database():
    """Serve la pagina web del pannello database."""
    import os
    percorso = os.path.join(os.path.dirname(__file__), "static", "admin_database.html")
    return FileResponse(percorso)
