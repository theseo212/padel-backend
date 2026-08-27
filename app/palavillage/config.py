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

# === PROTEZIONE PANNELLO ADMIN PALAVILLAGE ===
ADMIN_PV_USERNAME = os.getenv("ADMIN_PV_USERNAME", "admin")
ADMIN_PV_PASSWORD = os.getenv("ADMIN_PV_PASSWORD", "cambiami-subito")

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

EMAIL_SEGRETERIA_PALAVILLAGE = os.getenv("EMAIL_SEGRETERIA_PALAVILLAGE", "segreteria@palavillage.it")

# === TEMPISTICHE DEL CICLO TORNEO (in ore, per coerenza con lo scheduler) ===
ORE_RICHIESTA_ISCRIZIONE_PRIMA = 6 * 24    # T-6gg
ORE_SOLLECITO_ISCRIZIONE_PRIMA = 3 * 24    # T-3gg
ORE_FORMAZIONE_GRUPPI_PRIMA = 12           # T-12h
ORE_SOLLECITO_PUNTEGGIO_DOPO = 2           # T+2h dalla fine torneo

# === CONTESTO ATTIVO WHATSAPP (routing testo libero) ===
MINUTI_VALIDITA_CONTESTO_ATTIVO = 180  # oltre questa finestra, si considera scaduto
