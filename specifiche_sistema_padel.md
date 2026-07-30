# Sistema di Prenotazione e Formazione Partite di Padel
## Documento di specifiche — versione 1.0

---

## 1. Obiettivo del sistema

Permettere ai padelisti di un'ampia zona geografica di inserire la propria disponibilità a giocare, e formare automaticamente partite di 4 giocatori compatibili per livello, orario, circolo, lato di gioco e tipo di partita, gestendo l'intero ciclo tramite form web (solo per l'inserimento iniziale) e WhatsApp (per tutte le notifiche e conferme successive).

---

## 2. Flusso generale (4 step)

### Step 01 — Inserimento richiesta
L'utente compila un form web con: nome, cognome, numero WhatsApp, livello di gioco (Playtomic o Wansport, convertito automaticamente), lato di gioco preferito, tipo di partita, un giorno specifico, fascia oraria di disponibilità in quel giorno, e uno o più circoli in cui è disposto a giocare.

Alla prima richiesta in assoluto, il numero WhatsApp viene validato tramite OTP. Ad ogni richiesta (prima o successiva), il sistema invia su WhatsApp un riepilogo di conferma.

### Step 02 — Matching
Un motore a batch, eseguito periodicamente, analizza tutte le richieste attive e cerca gruppi di 4 giocatori compatibili per: tipo di partita (match esatto), circolo comune, intersezione oraria, lato di gioco (assegnazione 2+2 valida), e livello (entro una tolleranza che si allarga nel tempo).

### Step 03 — Proposta e conferma
Appena un gruppo di 4 è formato, tutti e 4 ricevono una proposta WhatsApp con bottoni di risposta rapida (Quick Reply): circolo, giorno, ora, nomi dei 4 giocatori. Serve conferma entro 15 minuti. Un utente compatibile con più gruppi riceve una sola proposta (diventa "bloccato" appena entra nella prima proposta).

### Step 04 — Prenotazione e post-partita
Se tutti e 4 confermano, il sistema avvia la prenotazione del campo (in fase MVP, con supporto di un operatore umano). Se il campo è disponibile, invia conferma WhatsApp e archivia la partita. Se non lo è, annulla e rimette i 4 giocatori in ricerca. Se anche solo uno non conferma, il gruppo si scioglie e i restanti tornano in ricerca; chi non conferma (rifiuto o mancata risposta) accumula un contatore, con sospensione di 7 giorni dopo 3 mancate conferme consecutive.

Al termine della partita, ogni giocatore riceve una richiesta di valutazione sul livello degli altri 3 (più alto / giusto / più basso), usata per aggiustare gradualmente il livello dichiarato nel tempo.

---

## 3. Decisioni fissate

### Architettura e stack tecnologico

| # | Decisione |
|---|-----------|
| 1 | Sistema come **web app**, non app nativa. Form web (Next.js) solo per l'inserimento iniziale; tutto il resto (proposte, conferme, notifiche) avviene su WhatsApp |
| 2 | Backend: **Python + FastAPI** |
| 3 | Database: **PostgreSQL** |
| 4 | Scheduler per il matching: **APScheduler** (batch ogni 3 minuti). Migrabile a Celery+Redis in futuro se il volume crescerà molto |
| 5 | Integrazione WhatsApp: **Twilio** come BSP (Business Solution Provider) sopra la Cloud API di Meta |
| 6 | Hosting: **Railway** (deploy automatico da GitHub, nessuna gestione server manuale) |

### Logica di sistema

| # | Decisione |
|---|-----------|
| 7 | Validazione numero WhatsApp: **OTP** (codice a 6 cifre) inviato via WhatsApp alla prima richiesta |
| 8 | **Una richiesta copre un solo giorno.** Per più giorni, l'utente crea più richieste separate |
| 9 | Disponibilità oraria rappresentata come **bitmask a 32 bit**, slot da 30 minuti, fascia 07:00–23:00. Intersezione tra giocatori = semplice AND bit a bit |
| 10 | Risoluzione conflitti nel matching: strategia **greedy per punteggio** (ordina i gruppi candidati per punteggio decrescente, conferma il primo, scarta i successivi con utenti già assegnati) |
| 11 | Compatibilità lato di gioco: gruppo valido se `n_dx≤2 AND n_sx≤2 AND (n_dx+n_ind)≥2 AND (n_sx+n_ind)≥2` |
| 12 | Tolleranza di livello: funzione **a gradini nel tempo** (0.5 → 0.75 → 1.0 → 1.25 → 1.5, tetto massimo), calibrabile. Nel confronto tra due utenti si usa sempre la tolleranza **più stretta** delle due |
| 13 | Proposta partita: messaggio WhatsApp con **bottoni Quick Reply**, non testo libero. Timeout di **15 minuti** per la conferma |
| 14 | Mancata conferma (rifiuto o non risposta): il gruppo si scioglie, i restanti tornano in ricerca. Contatore mancate conferme consecutive → **sospensione account 7 giorni** dopo 3 |
| 15 | Prenotazione campo: **MVP con conferma umana/operatore** (nessuna integrazione API automatica diretta con Playtomic/Wansport/circoli in questa fase) |
| 16 | Pagamento del campo: **nessuna gestione da parte del sistema** — ogni giocatore paga al circolo all'arrivo, come da abitudine consolidata |
| 17 | Livello di gioco: dichiarato **una sola volta** alla prima richiesta, **immutabile lato utente** da quel momento. Cambia solo tramite il meccanismo di feedback automatico o tramite correzione manuale da parte dell'amministrazione, su richiesta motivata scritta fuori dal sistema |
| 18 | Feedback post-partita: il livello si aggiorna solo dopo una **soglia minima di 3 partite** giocate, con step di **±0.25** per aggiustamento, basato sulla prevalenza dei voti ricevuti. Tutti i valori sono parametri configurabili nel codice |
| 19 | Mancata risposta al feedback finale: **nessuna penalità** per l'utente. Un solo promemoria dopo 6 ore; finestra di voto chiusa dopo 24 ore (il voto mancante non viene più conteggiato) |
| 20 | Scelta del circolo quando più circoli sono comuni al gruppo: si sceglie quello con **intersezione oraria più ampia**; in caso di parità, il circolo con **id numerico più basso** (criterio deterministico) |

### Parametri configurabili (da regolare durante l'uso reale)

```python
# === LIVELLO E FEEDBACK ===
SOGLIA_MIN_PARTITE_PER_AGGIORNAMENTO = 3
INCREMENTO_DECREMENTO_LIVELLO = 0.25
SOGLIA_PREVALENZA_VOTI = 0.60
PROMEMORIA_FEEDBACK_ORE = 6
FINESTRA_VOTAZIONE_FEEDBACK_ORE = 24

# === TOLLERANZA LIVELLO NEL TEMPO ===
TOLLERANZA_INIZIALE = 0.5
SOGLIE_TEMPO_MINUTI = [20, 45, 90, 180]
VALORI_TOLLERANZA = [0.5, 0.75, 1.0, 1.25, 1.5]

# === MATCHING ===
INTERVALLO_BATCH_MINUTI = 3
DURATA_MINIMA_PARTITA_SLOT = 3       # slot da 30 min (es. 3 = 1h30)
TIMEOUT_CONFERMA_MINUTI = 15
MAX_MANCATE_CONFERME_PRIMA_SOSPENSIONE = 3
GIORNI_SOSPENSIONE = 7
```

---

## 4. Schema del Database

### 4.1 `utenti`
Dati anagrafici stabili della persona.

```sql
CREATE TABLE utenti (
    id                              SERIAL PRIMARY KEY,
    nome                            VARCHAR(100) NOT NULL,
    cognome                         VARCHAR(100) NOT NULL,
    whatsapp_numero                 VARCHAR(20) UNIQUE NOT NULL,
    whatsapp_validato                BOOLEAN DEFAULT FALSE,
    livello_playtomic                NUMERIC(3,2) NOT NULL,
    livello_dichiarato_scala         VARCHAR(10),         -- 'PLAYTOMIC' o 'WANSPORT'
    livello_dichiarato_originale     VARCHAR(5),           -- es. 'B2' se Wansport, NULL se già Playtomic
    lato_preferito                   VARCHAR(15) NOT NULL, -- DX, SX, INDIFFERENTE
    stato_account                    VARCHAR(20) DEFAULT 'ATTIVO', -- ATTIVO, SOSPESO
    sospeso_fino_a                   TIMESTAMP NULL,
    mancate_conferme_consecutive     INTEGER DEFAULT 0,
    data_creazione                   TIMESTAMP DEFAULT NOW()
);
```

### 4.2 `circoli`
Lista dei circoli disponibili, gestita dal sistema/admin.

```sql
CREATE TABLE circoli (
    id              SERIAL PRIMARY KEY,
    nome            VARCHAR(150) NOT NULL,
    indirizzo       VARCHAR(255),
    orario_apertura TIME,
    orario_chiusura TIME,
    attivo          BOOLEAN DEFAULT TRUE
);
```

### 4.3 `richieste`
Una richiesta di disponibilità = un giorno preciso.

```sql
CREATE TABLE richieste (
    id                      SERIAL PRIMARY KEY,
    utente_id               INTEGER REFERENCES utenti(id),
    tipo_partita             VARCHAR(15) NOT NULL,  -- MASCHILE, FEMMINILE, MISTA
    giorno                   DATE NOT NULL,
    disponibilita_bitmask    INTEGER NOT NULL,       -- 32 bit, slot da 30 min, 07:00-23:00
    stato                    VARCHAR(20) DEFAULT 'IN_RICERCA', -- IN_RICERCA, LOCKED, CONFERMATA, SCADUTA, ANNULLATA
    data_creazione            TIMESTAMP DEFAULT NOW(),
    tolleranza_corrente       NUMERIC(3,2) DEFAULT 0.5
);
```

### 4.4 `richieste_circoli`
Relazione molti-a-molti tra richiesta e circoli scelti.

```sql
CREATE TABLE richieste_circoli (
    richiesta_id    INTEGER REFERENCES richieste(id) ON DELETE CASCADE,
    circolo_id      INTEGER REFERENCES circoli(id),
    PRIMARY KEY (richiesta_id, circolo_id)
);
```

### 4.5 `gruppi`
Un gruppo di 4 giocatori proposto dal matching.

```sql
CREATE TABLE gruppi (
    id                  SERIAL PRIMARY KEY,
    circolo_id           INTEGER REFERENCES circoli(id),
    giorno                DATE NOT NULL,
    slot_inizio           INTEGER NOT NULL,   -- indice slot bitmask (0-31)
    durata_slot            INTEGER NOT NULL,   -- es. 3 = 1h30
    stato                  VARCHAR(20) DEFAULT 'PROPOSTO', -- PROPOSTO, CONFERMATO, ANNULLATO, PRENOTATO, GIOCATO
    data_proposta           TIMESTAMP DEFAULT NOW(),
    scadenza_conferma       TIMESTAMP NOT NULL
);
```

### 4.6 `gruppi_membri`
I 4 giocatori di ogni gruppo.

```sql
CREATE TABLE gruppi_membri (
    id              SERIAL PRIMARY KEY,
    gruppo_id       INTEGER REFERENCES gruppi(id) ON DELETE CASCADE,
    utente_id       INTEGER REFERENCES utenti(id),
    richiesta_id    INTEGER REFERENCES richieste(id),
    lato_assegnato  VARCHAR(2),   -- DX o SX
    stato_conferma   VARCHAR(15) DEFAULT 'IN_ATTESA', -- IN_ATTESA, CONFERMATO, RIFIUTATO, NON_RISPOSTO
    data_risposta    TIMESTAMP NULL
);
```

### 4.7 `partite`
Archivio storico delle partite effettivamente organizzate.

```sql
CREATE TABLE partite (
    id                  SERIAL PRIMARY KEY,
    gruppo_id            INTEGER REFERENCES gruppi(id),
    circolo_id            INTEGER REFERENCES circoli(id),
    giorno                 DATE NOT NULL,
    ora_inizio              TIME NOT NULL,
    stato                   VARCHAR(20) DEFAULT 'PRENOTATA', -- PRENOTATA, GIOCATA, ANNULLATA
    data_prenotazione        TIMESTAMP DEFAULT NOW()
);
```

*Nota: nomi/cognomi dei 4 giocatori non sono duplicati qui, ma recuperati via JOIN attraverso `gruppo_id → gruppi_membri → utenti`.*

### 4.8 `feedback_livello`
Voti post-partita sul livello dei compagni.

```sql
CREATE TABLE feedback_livello (
    id              SERIAL PRIMARY KEY,
    partita_id      INTEGER REFERENCES partite(id),
    votante_id      INTEGER REFERENCES utenti(id),
    votato_id       INTEGER REFERENCES utenti(id),
    voto            VARCHAR(15) NOT NULL,  -- PIU_ALTO, GIUSTO, PIU_BASSO
    data_voto       TIMESTAMP DEFAULT NOW()
);
```

### 4.9 `storico_livello`
Traccia ogni aggiustamento del livello di un utente nel tempo.

```sql
CREATE TABLE storico_livello (
    id                    SERIAL PRIMARY KEY,
    utente_id              INTEGER REFERENCES utenti(id),
    livello_precedente      NUMERIC(3,2),
    livello_nuovo            NUMERIC(3,2),
    motivo                    VARCHAR(255),  -- es. 'aggiornamento automatico dopo 3 partite' o 'correzione admin su richiesta utente'
    data_aggiornamento        TIMESTAMP DEFAULT NOW()
);
```

### 4.10 `conversione_wansport_playtomic`
Tabella di conversione tra le due scale di livello.

```sql
CREATE TABLE conversione_wansport_playtomic (
    id                  SERIAL PRIMARY KEY,
    livello_wansport    VARCHAR(5) UNIQUE NOT NULL,
    livello_playtomic   NUMERIC(3,2) NOT NULL
);

INSERT INTO conversione_wansport_playtomic (livello_wansport, livello_playtomic) VALUES
('C4', 1.00), ('C3', 1.50), ('C2', 2.00), ('C1', 2.50),
('B4', 3.00), ('B3', 3.50), ('B2', 4.00), ('B1', 4.50),
('A4', 5.00), ('A3', 5.50), ('A2', 6.00), ('A1', 6.50);
```

> ⚠️ Questa mappatura è una stima di partenza, non un dato ufficiale. Va validata con un maestro/giocatore esperto di entrambe le scale prima del lancio.

---

## 5. Pseudocodice principale del motore di matching (Step 02)

```
FUNZIONE motore_matching_batch():
    ESEGUI ogni INTERVALLO_BATCH_MINUTI:

    richieste_attive = DB.get_richieste(stato = IN_RICERCA)

    PER OGNI r IN richieste_attive:
        r.tolleranza_corrente = calcola_tolleranza(tempo_attesa(r))

    richieste_attive.ordina_per(tempo_attesa DESC)

    gruppi_candidati = []

    PER OGNI r IN richieste_attive:
        SE r.stato != IN_RICERCA: CONTINUA

        candidati = TROVA_COMPATIBILI(r, richieste_attive)
        SE lunghezza(candidati) < 3: CONTINUA

        migliori_gruppi = GENERA_COMBINAZIONI_VALIDE(r, candidati)
        SE migliori_gruppi non vuoto:
            gruppo_scelto = migliori_gruppi.con_punteggio_massimo()
            gruppi_candidati.aggiungi(gruppo_scelto)

    gruppi_finali = RISOLVI_CONFLITTI(gruppi_candidati)  // greedy per punteggio

    PER OGNI gruppo IN gruppi_finali:
        LOCK(gruppo.4_utenti)
        invia_proposta_whatsapp(gruppo)
        avvia_timer_15_minuti(gruppo)


FUNZIONE GENERA_COMBINAZIONI_VALIDE(seed, candidati):
    PER OGNI combinazione di 3 candidati tra i candidati compatibili con seed:
        gruppo = [seed] + combinazione

        SE NON lato_compatibile(gruppo): CONTINUA
        SE NON gruppo_livelli_compatibile(gruppo): CONTINUA

        intersezione_oraria = AND(disponibilita di tutti e 4, stesso giorno)
        slot_partita = trova_slot_partita(intersezione_oraria, DURATA_MINIMA_PARTITA_SLOT)
        SE slot_partita non trovato: CONTINUA

        circoli_comuni = intersezione(circoli scelti da tutti e 4)
        SE circoli_comuni vuoto: CONTINUA
        circolo_scelto = scegli_circolo(circoli_comuni, gruppo, giorno)

        aggiungi {gruppo, giorno, slot_partita, circolo_scelto, punteggio} a lista_gruppi_possibili

    RETURN lista_gruppi_possibili


FUNZIONE lato_compatibile(gruppo):
    n_dx = conta(gruppo, lato == DX)
    n_sx = conta(gruppo, lato == SX)
    n_ind = conta(gruppo, lato == INDIFFERENTE)
    RETURN (n_dx <= 2) E (n_sx <= 2) E (n_dx + n_ind >= 2) E (n_sx + n_ind >= 2)


FUNZIONE gruppo_livelli_compatibile(gruppo):
    PER OGNI coppia (X, Y) IN gruppo:
        tolleranza_effettiva = min(X.tolleranza_corrente, Y.tolleranza_corrente)
        SE |X.livello - Y.livello| > tolleranza_effettiva: RETURN falso
    RETURN vero


FUNZIONE scegli_circolo(circoli_comuni, gruppo, giorno):
    migliore = null
    massima_ampiezza = -1
    PER OGNI circolo IN circoli_comuni:
        ampiezza = conta_slot_consecutivi_massimi(intersezione_oraria_per(circolo, giorno))
        SE ampiezza > massima_ampiezza:
            massima_ampiezza = ampiezza
            migliore = circolo
        ALTRIMENTI SE ampiezza == massima_ampiezza E circolo.id < migliore.id:
            migliore = circolo
    RETURN migliore
```

---

## 5bis. Nota su una possibile evoluzione futura della prenotazione (Step 04)

Approfondimento fatto durante lo sviluppo, a integrazione del punto 15.

**Situazione attuale confermata**: Playtomic offre una API ufficiale ai circoli partner, ma è di **sola lettura** — permette di consultare le prenotazioni esistenti, non di crearne di nuove. Non esiste quindi, ad oggi, una via ufficiale e supportata per automatizzare la prenotazione di un campo per conto di terzi.

**Cosa esiste comunque sul mercato**: automazioni non ufficiali basate su browser agent (RPA/Computer Use) che simulano un utente umano sul sito/app Playtomic. Alcuni servizi commerciali lo fanno già per prenotazioni personali (un utente che automatizza il proprio account). I termini di servizio pubblici di Playtomic, ad oggi, non contengono un divieto esplicito di questo tipo di automazione, ma non c'è alcuna garanzia che questa tolleranza implicita resti valida nel tempo — Playtomic potrebbe cambiare policy o rilevare e bloccare comportamenti automatizzati in qualsiasi momento.

**Decisione presa per l'eventuale fase 2** (non l'MVP, che resta con conferma umana — punto 15):
Se in futuro si deciderà di automatizzare la prenotazione tramite browser agent, si userà **un unico account Playtomic "di sistema"**, intestato alla piattaforma stessa — **mai le credenziali personali dei singoli utenti**. Questo evita di dover conservare e gestire le password Playtomic di centinaia di persone diverse, riducendo drasticamente il rischio di sicurezza e la responsabilità legale legata alla custodia di credenziali di terzi.

**Rischi da tenere presente se/quando si svilupperà questa fase**:
- Fragilità: un cambio di interfaccia sul sito Playtomic può interrompere l'automazione senza preavviso
- Rischio di sospensione dell'account "di sistema" se il volume di prenotazioni automatizzate diventa alto e viene rilevato come comportamento anomalo
- Nessuna garanzia contrattuale: la tolleranza attuale di Playtomic verso l'automazione non è scritta né garantita, e può cambiare in qualunque momento

Questa resta quindi un'opzione da validare con test reali e in piccola scala prima di un uso esteso, non una soluzione da considerare "sicura" solo perché tecnicamente fattibile.

---

## 6. Punti da validare/rifinire durante lo sviluppo e i primi test

- Valori esatti della funzione a gradini della tolleranza di livello (soglie minuti e incrementi)
- Valori esatti della tabella di conversione Wansport → Playtomic (richiede validazione da un esperto)
- Pesi della funzione di punteggio usata per scegliere tra gruppi candidati multipli
- Durata minima/massima di validità di una richiesta prima che scada automaticamente se non trova match
- Eventuale introduzione futura di un pannello di amministrazione (oggi le correzioni manuali di livello si fanno via query diretta)
- Eventuale integrazione API diretta con i circoli per la prenotazione automatica (oggi MVP con operatore umano)

---

*Documento generato il 25 luglio 2026, a supporto della fase di sviluppo del sistema.*
