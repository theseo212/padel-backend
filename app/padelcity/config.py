"""
Valori di configurazione specifici di PadelCity. Separato da
app/config.py per non mischiare le variabili d'ambiente dei due sistemi
(stesso pattern del DB separato).
"""

import os

# === IDENTITÀ ===
# La "voce" resta sempre Anna (stesso numero WhatsApp del sistema
# generico) — qui cambia solo il contesto (circolo/torneo) di cui parla.
NOME_CIRCOLO = "PadelCity"
FIRMA_MESSAGGIO = "\n\n♥ La tua Anna"

# === PREFISSO DI INSTRADAMENTO ===
# Ogni bottone WhatsApp creato da PadelCity porta questo prefisso nel
# ButtonPayload (mai nel testo visibile). L'hub nel webhook lo usa per
# capire a quale sistema instradare la risposta, senza toccare la
# cascata esistente del sistema generico (che non usa payload).
PREFISSO_ROUTING = "PC::"

# === INDIRIZZO PUBBLICO DEL FORM (sottocartella dello stesso dominio) ===
PUBLIC_FORM_URL_PADELCITY = os.getenv("PUBLIC_FORM_URL_PADELCITY", "https://www.annapadel.it/padelcity")

# URL pubblico del backend stesso: serve solo per costruire il link
# leggibile nei messaggi di simulazione/testo-libero (nel template Twilio
# vero, questo indirizzo di base è già scritto dentro il template stesso
# su Twilio - il codice manda solo il token come variabile, stesso
# identico schema del link di conferma circolo nel sistema generico).
URL_BASE_BACKEND_PUBBLICO = os.getenv("PADEL_BACKEND_URL", "https://web-production-3d15f.up.railway.app")

# === PROTEZIONE PANNELLO ADMIN PADELCITY ===
ADMIN_PC_USERNAME = os.getenv("ADMIN_PC_USERNAME", "admin_padelcity")
ADMIN_PC_PASSWORD = os.getenv("ADMIN_PC_PASSWORD", "cambiami-anche-questo")

# Credenziali del pannello "ridotto" da dare al circolo cliente: vede
# tornei e campionati come nel pannello completo, ma NON ha accesso al
# database grezzo, agli strumenti di forzatura (pensati per i nostri
# test) né al report mensile per la fatturazione. Se lasciate vuote,
# quel livello di accesso semplicemente non viene mai concesso (nessun
# valore di riserva pubblico, per sicurezza).
ADMIN_PC_CIRCOLO_USERNAME = os.getenv("ADMIN_PC_CIRCOLO_USERNAME", "")
ADMIN_PC_CIRCOLO_PASSWORD = os.getenv("ADMIN_PC_CIRCOLO_PASSWORD", "")

# === TWILIO ===
# Stesso account, stesso numero mittente del sistema generico: le
# credenziali Twilio restano quelle di app/config.py (TWILIO_ACCOUNT_SID,
# TWILIO_AUTH_TOKEN, TWILIO_WHATSAPP_NUMBER) - qui servono solo i SID dei
# template dedicati a questo circolo (contenuti/brand diversi: "torneo"
# invece di "partita", niente circoli da scegliere, ecc.)
TEMPLATE_PC_RICHIESTA_ISCRIZIONE = os.getenv("TEMPLATE_PC_RICHIESTA_ISCRIZIONE")
TEMPLATE_PC_RIEPILOGO_ISCRIZIONE = os.getenv("TEMPLATE_PC_RIEPILOGO_ISCRIZIONE")
TEMPLATE_PC_SOLLECITO_ISCRIZIONE = os.getenv("TEMPLATE_PC_SOLLECITO_ISCRIZIONE")
TEMPLATE_PC_SEI_RISERVA = os.getenv("TEMPLATE_PC_SEI_RISERVA")
TEMPLATE_PC_GRUPPO_ASSEGNATO = os.getenv("TEMPLATE_PC_GRUPPO_ASSEGNATO")
TEMPLATE_PC_PROMOZIONE_RISERVA = os.getenv("TEMPLATE_PC_PROMOZIONE_RISERVA")
TEMPLATE_PC_RICHIESTA_PUNTEGGIO = os.getenv("TEMPLATE_PC_RICHIESTA_PUNTEGGIO")
TEMPLATE_PC_SOLLECITO_PUNTEGGIO = os.getenv("TEMPLATE_PC_SOLLECITO_PUNTEGGIO")
TEMPLATE_PC_CLASSIFICA_AGGIORNATA = os.getenv("TEMPLATE_PC_CLASSIFICA_AGGIORNATA")
TEMPLATE_PC_TORNEO_ANNULLATO = os.getenv("TEMPLATE_PC_TORNEO_ANNULLATO")
TEMPLATE_PC_GRUPPO_INCOMPLETO = os.getenv("TEMPLATE_PC_GRUPPO_INCOMPLETO")
TEMPLATE_PC_SOSTITUZIONE_COMPAGNO = os.getenv("TEMPLATE_PC_SOSTITUZIONE_COMPAGNO")

EMAIL_SEGRETERIA_PADELCITY = os.getenv("EMAIL_SEGRETERIA_PADELCITY", "segreteria@padelcity.it")

# === TEMPISTICHE DEL CICLO TORNEO (in ore, per coerenza con lo scheduler) ===
ORE_RICHIESTA_ISCRIZIONE_PRIMA = 6 * 24    # T-6gg
ORE_SOLLECITO_ISCRIZIONE_PRIMA = 3 * 24    # T-3gg
ORE_FORMAZIONE_GRUPPI_PRIMA = 12           # T-12h
ORE_SOLLECITO_PUNTEGGIO_DOPO = 2           # T+2h dalla fine torneo
ORE_DURATA_TORNEO = 2                      # durata presunta di un torneo, per calcolare quando è "finito"
ORE_CHIUSURA_FORZATA_PUNTEGGIO = 24        # oltre questo tempo, si chiude comunque anche con risposte mancanti
ORA_INIZIO_TORNEO = "08:00"                # orario locale (Europe/Rome) di inizio torneo, di riserva se lo slot non ha un proprio orario

# Quanti campionati (slot) esistono in totale - non più uno per giorno
# della settimana: ogni slot ha il proprio giorno e orario, decisi
# liberamente dall'admin (anche più slot nello stesso giorno). Cambiare
# questo numero richiede comunque di generare/rimuovere manualmente le
# righe Campionato corrispondenti dal pannello - non è automatico.
NUMERO_CAMPIONATI = 6
GIORNI_TORNEI_DA_GENERARE_IN_ANTICIPO = 14 # quante giornate future tenere sempre pronte
MINUTI_TIMEOUT_PROMOZIONE_RISERVA = 30     # tempo dato a una riserva per confermare dopo una cancellazione tardiva

# === CONTESTO ATTIVO WHATSAPP (routing testo libero) ===
MINUTI_VALIDITA_CONTESTO_ATTIVO = 1500  # oltre questa finestra, si considera scaduto
# 25 ore: deve coprire tutta la finestra realistica in cui un giocatore
# può rispondere con il punteggio (fino alle ORE_CHIUSURA_FORZATA_PUNTEGGIO
# = 24h), altrimenti chi risponde tardi (ma comunque entro un giorno) si
# vede il messaggio scorrere verso il sistema generico invece di essere
# riconosciuto come risposta al punteggio - bug reale scoperto durante
# un test: 2 giocatori su 4 hanno risposto dopo 12h+ e non sono stati
# riconosciuti, con le 3 ore (180 minuti) di validità precedenti.
