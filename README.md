# Sistema Prenotazione Padel — Setup completo (Step 01-04 + Pannello + Circoli)

Tutti e 4 gli step del flusso sono implementati e testati end-to-end.
Il pannello operatore copre: prenotazione campo (manuale, dove serve
davvero un giudizio umano), partite concluse (automatico), e la gestione
completa dei circoli (inserimento, modifica, disattivazione, eliminazione).

## Struttura del progetto

```
padel-system/
├── requirements.txt
├── .env.example
├── init_db.py
├── specifiche_sistema_padel.md
└── app/
    ├── config.py
    ├── database.py
    ├── models.py
    ├── schemas.py
    ├── main.py                    → server + scheduler + pannello + circoli
    ├── static/
    │   └── admin.html               → pannello operatore (prenotazioni + circoli)
    ├── services/
    │   ├── bitmask.py
    │   ├── conversione_livello.py
    │   └── whatsapp.py
    └── matching/
        ├── compatibilita.py
        ├── motore.py                  → Step 02
        ├── notifiche.py                → testi messaggi Step 03
        ├── gestione_gruppi.py           → Step 03: conferme/rifiuti/timeout
        ├── prenotazione.py               → Step 04: prenotazione campo
        └── feedback.py                    → Step 04: valutazione livello (incluso
                                               il controllo automatico partite concluse)
```

## Gestione Circoli

Sezione in `/admin`: un form per aggiungere circoli con nome, indirizzo,
telefono, orari di apertura/chiusura, numero campi, dotazioni (es. bar,
spogliatoi, parcheggio) e note staff/referente. Tabella con tutti i
circoli inseriti, con due azioni:

- **Disattiva/Riattiva** — il circolo non compare più tra le scelte
  disponibili per nuove richieste, ma tutto lo storico resta intatto.
  Azione consigliata nella maggior parte dei casi
- **Elimina** — cancellazione definitiva, **permessa solo se il circolo
  non è collegato a nessuna richiesta, gruppo o partita esistente**. Se
  è già in uso, il sistema blocca l'eliminazione con un messaggio chiaro
  e suggerisce di disattivarlo invece

`GET /circoli` supporta il parametro `?solo_attivi=true`: il pannello
operatore lo chiama senza filtro (deve poter riattivare quelli disattivati),
mentre il futuro form pubblico dello Step 01 lo chiamerà con il filtro,
per non proporre agli utenti circoli disattivati. La lista è sempre
ordinata **alfabeticamente per nome**.

Anche lo Step 01 backend (`POST /richieste`) blocca esplicitamente la
scelta di un circolo disattivato, come doppia sicurezza anche se il form
pubblico dovesse per qualche motivo non filtrarli correttamente.

Endpoint: `GET /circoli`, `POST /circoli`, `PUT /circoli/{id}`, `DELETE /circoli/{id}`.

## Come dovrà apparire la scelta dei circoli nel form pubblico (Step 01, da costruire)

Non un `<select>` a tendina classico, ma una lista di checkbox (selezione
multipla più comoda da usare su mobile). Ogni riga mostra `Nome — Indirizzo`,
in ordine alfabetico, includendo solo i circoli attivi.

## Pannello Operatore — cosa serve davvero e cosa no

1. **Gruppi in attesa di prenotazione** — richiede l'operatore: solo una
   persona può verificare la disponibilità reale del campo sul circolo
2. **Partite da segnare manualmente come giocate** — solo un'ECCEZIONE.
   Il sistema segna automaticamente ogni partita come giocata 90 minuti
   dopo l'orario di inizio, tramite un job ogni 5 minuti
3. **Gestione Circoli** — CRUD completo, senza più bisogno di toccare SQL

## Endpoint disponibili ora

- Step 01: `POST /richieste`, `POST /richieste/valida-otp`
- Step 02: `POST /matching/esegui-ora` (test)
- Step 03: `POST /gruppi/{id}/rispondi`, `POST /matching/controlla-timeout-ora` (test)
- Step 04:
  - `POST /gruppi/{id}/prenotazione/conferma`, `POST /gruppi/{id}/prenotazione/fallita`
  - `POST /partite/{id}/segna-giocata`, `POST /partite/controlla-concluse-ora` (test)
  - `POST /partite/{id}/feedback`, `POST /feedback/controlla-cicli-ora` (test)
- Circoli: `GET/POST /circoli`, `PUT/DELETE /circoli/{id}`
- Pannello: `GET /admin`, `GET /admin/gruppi-da-prenotare`, `GET /admin/partite-da-segnare`

## Test effettuati (tutti confermati funzionanti)

Tutti gli step (01-04), il pannello operatore, il controllo automatico
partite concluse, e la gestione circoli (creazione, modifica, filtro
solo_attivi, protezione da eliminazione, ordinamento alfabetico) sono
stati testati end-to-end con successo. Due bug reali sono stati trovati
e corretti durante i test (una relazione mancante nel modello, una
query SQL non valida su PostgreSQL, e un bug logico sull'aggiornamento
duplicato del livello quando più finestre di feedback si chiudono
nello stesso ciclo).

## Come provarlo tu stesso

1. Installa le librerie: `pip install -r requirements.txt`
2. Copia `.env.example` in `.env` con l'indirizzo del tuo database
3. Esegui `python init_db.py`
4. Avvia il server: `uvicorn app.main:app --reload`
5. Vai su `http://127.0.0.1:8000/admin` — da qui puoi già inserire i
   circoli direttamente dal browser, senza più bisogno di SQL
6. Su `http://127.0.0.1:8000/docs` puoi testare gli altri endpoint

## Controllo richieste duplicate per lo stesso giorno

`POST /richieste` ora blocca (HTTP 409) un utente che tenta di inserire
una seconda richiesta per un giorno in cui ne ha già una attiva
(`IN_RICERCA` o `LOCKED`). La risposta include tutti i dati che servirà
al futuro form pubblico per offrire le due azioni ("annulla" / "mantieni"):

```json
{
  "messaggio": "Hai già una richiesta attiva per questo giorno.",
  "richiesta_esistente_id": 2,
  "stato_richiesta_esistente": "LOCKED",
  "azione_annulla": "/richieste/2/annulla"
}
```

`POST /richieste/{id}/annulla` gestisce due casi in modo diverso:
- **Richiesta `IN_RICERCA`** → annullamento semplice, nessuna penalità
- **Richiesta `LOCKED`** (già proposta in un gruppo con altri 3
  giocatori) → equivale a un **rifiuto vero e proprio** della proposta:
  riusa la stessa logica di `gestione_gruppi.rispondi_a_gruppo`, quindi
  gli altri 3 tornano in ricerca senza penalità e l'utente che annulla
  viene penalizzato esattamente come se avesse rifiutato esplicitamente
  (stesso contatore, stessa eventuale sospensione dopo 3 volte)

## Frontend pubblico (Step 01) — completato

Il form web è ora un progetto separato, `padel-frontend` (Next.js), con
tutti i campi previsti, gestione OTP, e gestione del conflitto di
richieste duplicate (le due azioni "annulla"/"mantieni"). Vedi il README
di quel progetto per le istruzioni di avvio.

**Nota tecnica**: è stato aggiunto il middleware CORS a questo backend
(vedi `app/main.py`) per permettere le richieste dal frontend, che gira
su un indirizzo/porta diversa. **In produzione, restringere
`allow_origins` all'indirizzo reale del sito** invece di lasciare `"*"`
(va bene solo per lo sviluppo locale).

## Prossimo passo possibile

- L'integrazione vera con Twilio per l'invio reale dei messaggi WhatsApp
- Il deploy su Railway (sia backend che frontend)
- Applicare la grafica definitiva al frontend, quando sarà pronta
