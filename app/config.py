"""
Tutti i valori che potrebbero servire regolare nel tempo sono qui,
in un unico posto. Se in futuro vuoi cambiare un numero (es. la durata
di validità dell'OTP), lo cambi solo qui, senza toccare il resto del codice.
"""

import os

# === IDENTITÀ DEL SERVIZIO ===
# Tutti i messaggi WhatsApp vengono scritti come se li scrivesse "Anna" in
# prima persona (una specie di segretaria personale), non un "sistema"
# impersonale. Il nome del brand e la firma sono centralizzati qui.
NOME_BRAND = "AnnaPadel"
FIRMA_MESSAGGIO = "\n\n♥ La tua Anna"

# === INDIRIZZO PUBBLICO DEL FORM (usato nei link dei messaggi WhatsApp) ===
PUBLIC_FORM_URL = os.getenv("PUBLIC_FORM_URL", "https://padel-frontend-production-913f.up.railway.app")

# === INDIRIZZO PUBBLICO DI QUESTO BACKEND (per i link "clicca per annullare") ===
BACKEND_PUBLIC_URL = os.getenv("BACKEND_PUBLIC_URL", "https://web02-production-7527.up.railway.app")

# === PROTEZIONE PANNELLO OPERATORE ===
# Nome utente e password per accedere a /admin e a tutte le azioni
# amministrative. IMPORTANTE: imposta questi valori su Railway con
# credenziali vere prima di andare in produzione - i valori di riserva
# qui sotto sono solo per non rompere lo sviluppo locale, NON vanno usati
# per davvero.
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "cambiami-subito")

# === EMAIL (form contatti) ===
# Railway blocca le porte SMTP sui piani Free/Trial/Hobby (policy fissa,
# non aggirabile) - usiamo quindi Resend, un servizio che invia email
# tramite HTTPS (porta 443, mai bloccata) invece che SMTP diretto.
# Se RESEND_API_KEY non è impostata, il sistema salva comunque il
# messaggio nel database, ma non prova a inviare l'email.
RESEND_API_KEY = os.getenv("RESEND_API_KEY")
EMAIL_MITTENTE = os.getenv("EMAIL_MITTENTE", "noreply@annapadel.it")  # dominio verificato su Resend
EMAIL_DESTINATARIO_CONTATTI = os.getenv("EMAIL_DESTINATARIO_CONTATTI", "info@annapadel.it")

# === TWILIO (invio WhatsApp reale) ===
# Se questi valori non sono impostati, il sistema resta in modalità
# "simulazione" (stampa nei log invece di inviare davvero) - lo stesso
# comportamento usato durante tutto lo sviluppo. Appena vengono impostati
# su Railway, l'invio diventa reale senza bisogno di altre modifiche.
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_WHATSAPP_NUMBER = os.getenv("TWILIO_WHATSAPP_NUMBER")  # es. "whatsapp:+14155238886"

# Ogni messaggio ha il suo template, con testo fisso attorno alle variabili
# (Meta rifiuta i template dove una variabile non ha contesto chiaro intorno,
# quindi niente più "contenitori generici" con un solo segnaposto libero).
TEMPLATE_OTP = os.getenv("TEMPLATE_OTP")
TEMPLATE_RIEPILOGO = os.getenv("TEMPLATE_RIEPILOGO")
TEMPLATE_PROPOSTA_GRUPPO = os.getenv("TEMPLATE_PROPOSTA_GRUPPO")
TEMPLATE_ANNULLAMENTO = os.getenv("TEMPLATE_ANNULLAMENTO")
TEMPLATE_GRUPPO_CONFERMATO = os.getenv("TEMPLATE_GRUPPO_CONFERMATO")
TEMPLATE_PRENOTAZIONE_CONFERMATA = os.getenv("TEMPLATE_PRENOTAZIONE_CONFERMATA")
TEMPLATE_PRENOTAZIONE_FALLITA = os.getenv("TEMPLATE_PRENOTAZIONE_FALLITA")
TEMPLATE_RICHIESTA_FEEDBACK = os.getenv("TEMPLATE_RICHIESTA_FEEDBACK")
TEMPLATE_PROMEMORIA_FEEDBACK = os.getenv("TEMPLATE_PROMEMORIA_FEEDBACK")
TEMPLATE_SOSPENSIONE = os.getenv("TEMPLATE_SOSPENSIONE")
TEMPLATE_PROMEMORIA_MANCATA_PARTITA = os.getenv("TEMPLATE_PROMEMORIA_MANCATA_PARTITA")

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
