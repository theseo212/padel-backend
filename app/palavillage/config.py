"""
Valori di configurazione specifici di Palavillage. Separato da
app/config.py per non mischiare le variabili d'ambiente dei due sistemi
(stesso pattern del DB separato).
"""

import os

# === IDENTITÀ ===
# La "voce" resta sempre Anna (stesso numero WhatsApp del sistema
# generico) — qui cambia solo il contesto (circolo/torneo) di cui parla.
NOME_CIRCOLO = "Palavillage"
FIRMA_MESSAGGIO = "\n\n♥ La tua Anna"

# === PREFISSO DI INSTRADAMENTO ===
# Ogni bottone WhatsApp creato da Palavillage porta questo prefisso nel
# ButtonPayload (mai nel testo visibile). L'hub nel webhook lo usa per
# capire a quale sistema instradare la risposta, senza toccare la
# cascata esistente del sistema generico (che non usa payload).
PREFISSO_ROUTING = "PV::"

# === INDIRIZZO PUBBLICO DEL FORM (sottocartella dello stesso dominio) ===
PUBLIC_FORM_URL_PALAVILLAGE = os.getenv("PUBLIC_FORM_URL_PALAVILLAGE", "https://www.annapadel.it/palavillage")

# URL pubblico del backend stesso: serve solo per costruire il link
# leggibile nei messaggi di simulazione/testo-libero (nel template Twilio
# vero, questo indirizzo di base è già scritto dentro il template stesso
# su Twilio - il codice manda solo il token come variabile, stesso
# identico schema del link di conferma circolo nel sistema generico).
URL_BASE_BACKEND_PUBBLICO = os.getenv("PADEL_BACKEND_URL", "https://web-production-3d15f.up.railway.app")

# === PROTEZIONE PANNELLO ADMIN PALAVILLAGE ===
ADMIN_PV_USERNAME = os.getenv("ADMIN_PV_USERNAME", "admin_palavillage")
ADMIN_PV_PASSWORD = os.getenv("ADMIN_PV_PASSWORD", "cambiami-anche-questo")

# Credenziali del pannello "ridotto" da dare al circolo cliente: vede
# tornei e campionati come nel pannello completo, ma NON ha accesso al
# database grezzo, agli strumenti di forzatura (pensati per i nostri
# test) né al report mensile per la fatturazione. Se lasciate vuote,
# quel livello di accesso semplicemente non viene mai concesso (nessun
# valore di riserva pubblico, per sicurezza).
ADMIN_PV_CIRCOLO_USERNAME = os.getenv("ADMIN_PV_CIRCOLO_USERNAME", "")
ADMIN_PV_CIRCOLO_PASSWORD = os.getenv("ADMIN_PV_CIRCOLO_PASSWORD", "")

# === TWILIO ===
# Stesso account, stesso numero mittente del sistema generico: le
# credenziali Twilio restano quelle di app/config.py (TWILIO_ACCOUNT_SID,
# TWILIO_AUTH_TOKEN, TWILIO_WHATSAPP_NUMBER) - qui servono solo i SID dei
# template dedicati a questo circolo (contenuti/brand diversi: "torneo"
# invece di "partita", niente circoli da scegliere, ecc.)
TEMPLATE_PV_RICHIESTA_ISCRIZIONE = os.getenv("TEMPLATE_PV_RICHIESTA_ISCRIZIONE")
TEMPLATE_PV_RIEPILOGO_ISCRIZIONE = os.getenv("TEMPLATE_PV_RIEPILOGO_ISCRIZIONE")
TEMPLATE_PV_SOLLECITO_ISCRIZIONE = os.getenv("TEMPLATE_PV_SOLLECITO_ISCRIZIONE")
TEMPLATE_PV_SEI_RISERVA = os.getenv("TEMPLATE_PV_SEI_RISERVA")
TEMPLATE_PV_GRUPPO_ASSEGNATO = os.getenv("TEMPLATE_PV_GRUPPO_ASSEGNATO")
TEMPLATE_PV_PROMOZIONE_RISERVA = os.getenv("TEMPLATE_PV_PROMOZIONE_RISERVA")
TEMPLATE_PV_RICHIESTA_PUNTEGGIO = os.getenv("TEMPLATE_PV_RICHIESTA_PUNTEGGIO")
TEMPLATE_PV_SOLLECITO_PUNTEGGIO = os.getenv("TEMPLATE_PV_SOLLECITO_PUNTEGGIO")
TEMPLATE_PV_CLASSIFICA_AGGIORNATA = os.getenv("TEMPLATE_PV_CLASSIFICA_AGGIORNATA")
TEMPLATE_PV_TORNEO_ANNULLATO = os.getenv("TEMPLATE_PV_TORNEO_ANNULLATO")
TEMPLATE_PV_GRUPPO_INCOMPLETO = os.getenv("TEMPLATE_PV_GRUPPO_INCOMPLETO")
TEMPLATE_PV_SOSTITUZIONE_COMPAGNO = os.getenv("TEMPLATE_PV_SOSTITUZIONE_COMPAGNO")

EMAIL_SEGRETERIA_PALAVILLAGE = os.getenv("EMAIL_SEGRETERIA_PALAVILLAGE", "segreteria@palavillage.it")

# === TEMPISTICHE DEL CICLO TORNEO (in ore, per coerenza con lo scheduler) ===
ORE_RICHIESTA_ISCRIZIONE_PRIMA = 6 * 24    # T-6gg
ORE_SOLLECITO_ISCRIZIONE_PRIMA = 3 * 24    # T-3gg
ORE_FORMAZIONE_GRUPPI_PRIMA = 12           # T-12h
ORE_SOLLECITO_PUNTEGGIO_DOPO = 2           # T+2h dalla fine torneo
ORE_DURATA_TORNEO = 2                      # durata presunta di un torneo, per calcolare quando è "finito"
ORE_CHIUSURA_FORZATA_PUNTEGGIO = 24        # oltre questo tempo, si chiude comunque anche con risposte mancanti
ORA_INIZIO_TORNEO = "08:00"                # orario locale (Europe/Rome) di inizio torneo
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
