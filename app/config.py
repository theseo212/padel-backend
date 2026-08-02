"""
Tutti i valori che potrebbero servire regolare nel tempo sono qui,
in un unico posto. Se in futuro vuoi cambiare un numero (es. la durata
di validità dell'OTP), lo cambi solo qui, senza toccare il resto del codice.
"""

import os

# === INDIRIZZO PUBBLICO DEL FORM (usato nei link dei messaggi WhatsApp) ===
PUBLIC_FORM_URL = os.getenv("PUBLIC_FORM_URL", "https://padel-frontend-production-913f.up.railway.app")

# === INDIRIZZO PUBBLICO DI QUESTO BACKEND (per i link "clicca per annullare") ===
BACKEND_PUBLIC_URL = os.getenv("BACKEND_PUBLIC_URL", "https://web-production-3d15f.up.railway.app")

# === FASCIA ORARIA GESTITA DAL SISTEMA ===
ORA_INIZIO_GIORNATA = 7    # 07:00
ORA_FINE_GIORNATA = 23     # 23:00
DURATA_SLOT_MINUTI = 30    # ogni "slot" dura 30 minuti
NUM_SLOT_TOTALI = (ORA_FINE_GIORNATA - ORA_INIZIO_GIORNATA) * 60 // DURATA_SLOT_MINUTI  # 32

# === OTP (validazione numero WhatsApp) ===
OTP_DURATA_VALIDITA_MINUTI = 10
OTP_LUNGHEZZA = 6

# === LIVELLO E FEEDBACK (li useremo nei prossimi passi) ===
SOGLIA_MIN_PARTITE_PER_AGGIORNAMENTO = 3
INCREMENTO_DECREMENTO_LIVELLO = 0.25
SOGLIA_PREVALENZA_VOTI = 0.60
PROMEMORIA_FEEDBACK_ORE = 6
FINESTRA_VOTAZIONE_FEEDBACK_ORE = 24

# === TOLLERANZA LIVELLO NEL TEMPO (li useremo nei prossimi passi) ===
TOLLERANZA_INIZIALE = 0.5
SOGLIE_TEMPO_MINUTI = [20, 45, 90, 180]
VALORI_TOLLERANZA = [0.5, 0.75, 1.0, 1.25, 1.5]

# === MATCHING (li useremo nei prossimi passi) ===
INTERVALLO_BATCH_MINUTI = 3
DURATA_MINIMA_PARTITA_SLOT = 3
TIMEOUT_CONFERMA_MINUTI = 15
MAX_MANCATE_CONFERME_PRIMA_SOSPENSIONE = 3
GIORNI_SOSPENSIONE = 7
