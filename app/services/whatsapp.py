"""
Gestisce l'invio dei messaggi WhatsApp.

Ogni messaggio ha un template dedicato, con testo fisso attorno alle
variabili (Meta rifiuta i template dove una variabile non ha un contesto
chiaro - niente più "contenitore generico" con un solo segnaposto libero).

Tre modalità possibili, scelte automaticamente in base a cosa è configurato:
1. NESSUNA credenziale Twilio -> simulazione (stampa nei log).
2. Credenziali Twilio configurate MA il template specifico non è ancora
   pronto -> invio reale come testo libero (funziona nel Sandbox, o
   comunque dentro una finestra di conversazione aperta).
3. Credenziali Twilio + template specifico configurato -> invio reale
   tramite quel template, con le variabili giuste al posto giusto.
"""

import json
import random
import string
from app.config import (
    OTP_LUNGHEZZA, OTP_DURATA_VALIDITA_MINUTI, NOME_BRAND, FIRMA_MESSAGGIO,
    TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_WHATSAPP_NUMBER,
    TEMPLATE_OTP, TEMPLATE_RIEPILOGO, TEMPLATE_PROPOSTA_GRUPPO,
    TEMPLATE_ANNULLAMENTO, TEMPLATE_GRUPPO_CONFERMATO,
    TEMPLATE_PRENOTAZIONE_CONFERMATA, TEMPLATE_PRENOTAZIONE_FALLITA,
    TEMPLATE_RICHIESTA_FEEDBACK, TEMPLATE_PROMEMORIA_FEEDBACK,
    TEMPLATE_SOSPENSIONE, TEMPLATE_PROMEMORIA_MANCATA_PARTITA,
    TEMPLATE_RICHIESTA_PRENOTAZIONE_CIRCOLO, TEMPLATE_RICHIESTA_SCADUTA, TEMPLATE_CONFERMA_BOZZA_VOCALE,
    TEMPLATE_MODIFICA_PREFERENZE_VOCALE, TEMPLATE_AVVISO_MESSAGGIO_NON_GESTITO,
)

_TWILIO_CONFIGURATO = bool(TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN and TWILIO_WHATSAPP_NUMBER)

_client = None
if _TWILIO_CONFIGURATO:
    from twilio.rest import Client
    _client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)


def genera_otp() -> str:
    """Genera un codice numerico casuale, es. '482913'."""
    return "".join(random.choices(string.digits, k=OTP_LUNGHEZZA))


def _invia(numero_whatsapp: str, testo_completo: str, content_sid: str | None, variabili: dict | None, etichetta_simulazione: str = "") -> bool:
    """
    Punto unico di invio.
    - Se c'è un template configurato per questo messaggio specifico, lo usa
      con le sue variabili (necessario per un numero Business vero).
    - Altrimenti, se Twilio è comunque configurato, manda il testo libero
      (funziona nel Sandbox).
    - Altrimenti, simula (stampa nei log).

    Restituisce True se il messaggio è stato mandato per davvero (o siamo
    in simulazione locale, che consideriamo "riuscita" per non bloccare lo
    sviluppo), False SOLO se Twilio è configurato ma entrambi i tentativi
    di invio reale sono falliti sul serio (es. limite giornaliero di
    conversazioni superato) - in quel caso il chiamante può decidere di
    avvisare l'utente invece di fingere che sia andato tutto bene.
    """
    if _TWILIO_CONFIGURATO and content_sid and variabili is not None:
        try:
            parametri = {
                "from_": TWILIO_WHATSAPP_NUMBER,
                "to": f"whatsapp:{numero_whatsapp}",
                "content_sid": content_sid,
            }
            # Se il template non ha nessuna variabile (dizionario vuoto),
            # ometti del tutto il parametro invece di mandare '{}' - alcuni
            # template senza nessuna variabile sembrano comportarsi in modo
            # imprevedibile (bottoni persi) quando riceve un oggetto JSON
            # vuoto invece che nessun parametro affatto.
            if variabili:
                parametri["content_variables"] = json.dumps(variabili)
            _client.messages.create(**parametri)
            return True
        except Exception as errore:
            print(f"[TWILIO][ERRORE INVIO TEMPLATE] a {numero_whatsapp}: {errore}")

    if _TWILIO_CONFIGURATO:
        try:
            _client.messages.create(
                from_=TWILIO_WHATSAPP_NUMBER,
                to=f"whatsapp:{numero_whatsapp}",
                body=testo_completo,
            )
            return True
        except Exception as errore:
            print(f"[TWILIO][ERRORE INVIO TESTO LIBERO] a {numero_whatsapp}: {errore}")
            print(f"[TWILIO][INVIO FALLITO DAVVERO] messaggio NON recapitato a {numero_whatsapp}")
            return False

    prefisso = f"[SIMULAZIONE WHATSAPP{etichetta_simulazione}]"
    print(f"{prefisso} Invio a {numero_whatsapp}:\n{testo_completo}")
    return True


def invia_otp_whatsapp(numero_whatsapp: str, codice_otp: str) -> bool:
    # Il template Authentication ha il testo FISSO deciso da Meta (non
    # modificabile) - qui costruiamo solo il testo di riserva per la
    # simulazione locale, che resta con la voce di Anna. La chiamata vera
    # a Twilio manda invece UNA SOLA variabile (il codice): i minuti di
    # validità sono stati impostati una volta per sempre in fase di
    # creazione del template su Twilio, non si mandano più ad ogni invio.
    testo = (
        f"Ciao! Sono Anna ✅ Per completare la tua richiesta su {NOME_BRAND}, "
        f"usa questo codice: {codice_otp} (valido {OTP_DURATA_VALIDITA_MINUTI} minuti)."
    ) + FIRMA_MESSAGGIO
    variabili = {"1": codice_otp}
    return _invia(numero_whatsapp, testo, TEMPLATE_OTP, variabili)


def invia_riepilogo_richiesta(numero_whatsapp: str, riepilogo: str, nome: str = "", tipo_partita: str = "",
                                giorno: str = "", orari: str = "", livello: str = "", lato: str = "",
                                circoli: str = "") -> bool:
    """
    'riepilogo' resta il testo già formattato (usato per la simulazione),
    gli altri parametri sono i pezzi separati necessari al template reale.
    L'ottava variabile del template è ora un bottone "Call to Action" con
    URL dinamico (non più un link intero come variabile di testo - Meta lo
    rifiuta, lo scambia per phishing): la parte variabile è solo il numero
    di telefono, aggiunto in fondo a un indirizzo fisso
    (https://annapadel.it/stato/NUMERO).
    """
    variabili = {
        "1": nome, "2": tipo_partita, "3": giorno, "4": orari,
        "5": livello, "6": lato, "7": circoli, "8": numero_whatsapp.lstrip("+"),
    } if nome else None
    return _invia(numero_whatsapp, riepilogo, TEMPLATE_RIEPILOGO, variabili)


def invia_proposta_gruppo(numero_whatsapp: str, testo_proposta: str, circolo: str = "", giorno: str = "",
                            orario: str = "", giocatori: str = ""):
    variabili = {"1": circolo, "2": giorno, "3": orario, "4": giocatori} if circolo else None
    _invia(numero_whatsapp, testo_proposta, TEMPLATE_PROPOSTA_GRUPPO, variabili,
           etichetta_simulazione=" - PROPOSTA con bottoni Conferma/Rifiuta")


def invia_annullamento_gruppo(numero_whatsapp: str, motivo: str):
    testo = (
        f"Ops! Ho dovuto annullare questa partita. Motivo: {motivo}\n"
        f"Non preoccuparti, continuo subito a cercarti nuovi compagni!"
    ) + FIRMA_MESSAGGIO
    variabili = {"1": motivo}
    _invia(numero_whatsapp, testo, TEMPLATE_ANNULLAMENTO, variabili)


def invia_gruppo_confermato(numero_whatsapp: str, testo: str, circolo: str = "", giorno: str = "", orario: str = ""):
    variabili = {"1": circolo, "2": giorno, "3": orario} if circolo else None
    _invia(numero_whatsapp, testo, TEMPLATE_GRUPPO_CONFERMATO, variabili)


def invia_sospensione_account(numero_whatsapp: str, giorni: int):
    testo = (
        f"Il tuo account è stato sospeso per {giorni} giorni per mancate conferme ripetute."
    ) + FIRMA_MESSAGGIO
    variabili = {"1": str(giorni)}
    _invia(numero_whatsapp, testo, TEMPLATE_SOSPENSIONE, variabili)


def invia_prenotazione_confermata(numero_whatsapp: str, testo: str, circolo: str = "", giorno: str = "",
                                    orario: str = "", campo: str = ""):
    variabili = {"1": circolo, "2": giorno, "3": orario, "4": campo} if circolo else None
    _invia(numero_whatsapp, testo, TEMPLATE_PRENOTAZIONE_CONFERMATA, variabili)


def invia_prenotazione_fallita(numero_whatsapp: str, testo: str, circolo: str = ""):
    variabili = {"1": circolo} if circolo else None
    _invia(numero_whatsapp, testo, TEMPLATE_PRENOTAZIONE_FALLITA, variabili)


def invia_richiesta_feedback(numero_whatsapp: str, testo: str, nome_compagno: str = "", riferimento_partita: str = ""):
    variabili = {"1": nome_compagno, "2": riferimento_partita} if nome_compagno else None
    _invia(numero_whatsapp, testo, TEMPLATE_RICHIESTA_FEEDBACK, variabili,
           etichetta_simulazione=" - RICHIESTA FEEDBACK")


def invia_promemoria_feedback(numero_whatsapp: str, riferimento_partita: str = ""):
    """
    Cita esplicitamente circolo e data della partita (stesso principio già
    validato per annapadel_richiesta_feedback): Meta approva come
    "Utility" solo i sondaggi legati a un'interazione specifica.
    """
    testo = f"Psst! Non dimenticare di valutare i tuoi compagni della partita al {riferimento_partita} ✅" + FIRMA_MESSAGGIO
    variabili = {"1": riferimento_partita} if riferimento_partita else {}
    _invia(numero_whatsapp, testo, TEMPLATE_PROMEMORIA_FEEDBACK, variabili)


def invia_promemoria_mancata_partita(numero_whatsapp: str, testo: str, nome: str = "", giorno: str = "",
                                       fascia_oraria: str = "", id_richiesta: str = "") -> bool:
    """
    Il link di annullamento è un bottone "Call to Action" con URL dinamico
    (non più una variabile di testo libero - Meta la rifiuta, la scambia
    per phishing): la parte variabile è solo l'ID della richiesta.
    Il messaggio cita esplicitamente giorno e fascia oraria richiesti:
    Meta approva come "Utility" solo i messaggi che fanno riferimento a
    un'interazione SPECIFICA, non un avviso generico.
    """
    variabili = {"1": nome, "2": giorno, "3": fascia_oraria, "4": id_richiesta} if nome else None
    return _invia(numero_whatsapp, testo, TEMPLATE_PROMEMORIA_MANCATA_PARTITA, variabili,
                  etichetta_simulazione=" - PROMEMORIA")


def invia_richiesta_prenotazione_circolo(numero_whatsapp: str, testo: str, circolo: str = "",
                                           giorno: str = "", orario: str = "", giocatori: str = "",
                                           token_conferma: str = "") -> bool:
    """
    Manda al circolo (e per conoscenza all'operatore) la richiesta di
    prenotare il campo, con un bottone che porta alla pagina dedicata.
    Attenzione: 'giocatori' NON deve mai contenere ritorni a capo -
    WhatsApp li vieta dentro il valore di una singola variabile (anche se
    il JSON è tecnicamente valido) - va costruito con un separatore tipo
    " - ", non "\\n".
    """
    variabili = {"1": circolo, "2": giorno, "3": orario, "4": giocatori, "5": token_conferma} if circolo else None
    return _invia(numero_whatsapp, testo, TEMPLATE_RICHIESTA_PRENOTAZIONE_CIRCOLO, variabili,
                  etichetta_simulazione=" - RICHIESTA PRENOTAZIONE CIRCOLO")


def invia_notifica_operatore(testo: str, circolo: str = "", giorno: str = "", orario: str = "", giocatori: str = ""):
    """
    Avvisa TUTTI i numeri configurati in ADMIN_WHATSAPP_NUMERI (uno o più)
    che un gruppo è pronto per la prenotazione. Se non è ancora configurato
    nessun template dedicato, prova comunque a mandare il testo libero
    (funziona se l'operatore ha già una conversazione aperta col numero).
    """
    from app.config import ADMIN_WHATSAPP_NUMERI, TEMPLATE_NOTIFICA_OPERATORE
    variabili = {"1": circolo, "2": giorno, "3": orario, "4": giocatori} if circolo else None
    for numero in ADMIN_WHATSAPP_NUMERI:
        _invia(numero, testo, TEMPLATE_NOTIFICA_OPERATORE, variabili, etichetta_simulazione=" - AVVISO OPERATORE")


def invia_conferma_ricevuta(numero_whatsapp: str, testo: str):
    """
    Risposta immediata quando UN giocatore conferma, prima che tutti e 4
    abbiano risposto. È sempre dentro una conversazione che l'utente ha
    appena aperto lui stesso (scrivendoci "Confermo"), quindi il testo
    libero funziona sempre, senza bisogno di un template approvato.
    """
    _invia(numero_whatsapp, testo, None, None)


def invia_risposta_tardiva(numero_whatsapp: str, testo: str):
    """Stesso discorso: risposta dentro una conversazione già aperta, nessun template necessario."""
    _invia(numero_whatsapp, testo, None, None)


def invia_messaggio_richiesta_vocale(numero_whatsapp: str, testo: str):
    """
    Usata per tutti i messaggi del flusso "richiesta via vocale" (riepilogo
    da confermare, conferma finale, errori) - sempre risposta dentro una
    conversazione che l'utente ha appena aperto lui stesso mandando il
    vocale, quindi nessun template necessario.
    """
    _invia(numero_whatsapp, testo, None, None)


def invia_conferma_bozza_vocale(numero_whatsapp: str, giorno: str = "", fascia_oraria: str = ""):
    """
    Manda i due bottoni "Confermo"/"Annulla" per la bozza vocale.
    Cita giorno e fascia oraria specifici (non un generico "confermi?"):
    stesso principio già usato per altri template riclassificati come
    Marketing - Meta approva come Utility solo i messaggi legati a
    un'interazione specifica dell'utente, non un avviso generico.
    """
    variabili = {"1": giorno, "2": fascia_oraria} if giorno else {}
    _invia(numero_whatsapp, f"Ho registrato la tua richiesta vocale per il {giorno} ({fascia_oraria}). Confermi che vada bene?",
           TEMPLATE_CONFERMA_BOZZA_VOCALE, variabili)


def invia_link_modifica_preferenze_vocale(numero_whatsapp: str, giorno: str = ""):
    """
    Bottone che porta al form del sito, per chi vuole cambiare tipo
    partita/lato/circoli invece di usare quelli riusati automaticamente.
    In un messaggio SEPARATO da quello con Confermo/Annulla: WhatsApp non
    permette di mescolare, nello stesso messaggio, bottoni "Quick Reply"
    e bottoni "apri sito web". Cita il giorno della richiesta, stesso
    principio di specificità del template sopra.
    """
    variabili = {"1": giorno} if giorno else {}
    _invia(numero_whatsapp, f"Per la tua richiesta del {giorno}, se vuoi cambiare tipo partita, lato o circoli:",
           TEMPLATE_MODIFICA_PREFERENZE_VOCALE, variabili)


def invia_richiesta_scaduta(numero_whatsapp: str, testo: str, tipo_partita: str = "",
                              giorno: str = "", fascia_oraria: str = "") -> bool:
    """
    Avvisa l'utente che la sua richiesta è scaduta senza aver trovato
    compagni compatibili in tempo, con un bottone (fisso, non dinamico -
    porta sempre alla stessa pagina del form) per inserirne subito una nuova.
    Cita tipo partita, giorno e fascia oraria: Meta approva come "Utility"
    solo i messaggi che fanno riferimento a un'interazione SPECIFICA
    (la richiesta vera dell'utente), non un avviso generico.
    """
    variabili = {"1": tipo_partita, "2": giorno, "3": fascia_oraria} if tipo_partita else None
    return _invia(numero_whatsapp, testo, TEMPLATE_RICHIESTA_SCADUTA, variabili,
                  etichetta_simulazione=" - RICHIESTA SCADUTA")


def invia_messaggio_non_riconosciuto(numero_whatsapp: str):
    """
    Risposta automatica quando arriva un messaggio che non rientra in
    nessuno dei flussi previsti (es. "Ciao Anna", una domanda libera,
    ecc.) - senza questo, l'utente resterebbe nel silenzio più totale,
    pensando magari di essere stato ignorato. È sempre una risposta
    dentro una conversazione che l'utente ha appena aperto lui stesso,
    quindi nessun template necessario.
    """
    _invia(
        numero_whatsapp,
        "Ciao! Sono un sistema automatico, purtroppo non posso rispondere a messaggi liberi. "
        "Per assistenza, scrivi a info@annapadel.it",
        None, None,
    )


def invia_avviso_messaggio_non_gestito_operatore(numero_mittente: str, testo_ricevuto: str):
    """
    Avvisa l'operatore quando arriva un messaggio non gestito da nessun
    flusso automatico, con il numero e il testo esatto ricevuto - così
    l'operatore sa che qualcuno ha scritto qualcosa fuori dai flussi
    previsti, e può decidere se e come contattarlo personalmente.
    """
    from app.config import ADMIN_WHATSAPP_NUMERI

    # WhatsApp vieta i ritorni a capo dentro una singola variabile - il
    # testo qui lo scrive l'UTENTE, quindi non possiamo controllarlo in
    # anticipo: sostituiamo eventuali "a capo" con uno spazio, e
    # tronchiamo se troppo lungo (i template hanno un limite ragionevole
    # di lunghezza per variabile).
    testo_pulito = testo_ricevuto.replace("\n", " ").replace("\r", " ").strip()
    if len(testo_pulito) > 200:
        testo_pulito = testo_pulito[:200] + "..."
    if not testo_pulito:
        testo_pulito = "(messaggio vuoto o senza testo, es. un'immagine)"

    testo_semplice = (
        f"‼️ Messaggio non gestito da {numero_mittente}:\n\"{testo_pulito}\""
    )
    variabili = {"1": numero_mittente, "2": testo_pulito}
    for numero in ADMIN_WHATSAPP_NUMERI:
        _invia(numero, testo_semplice, TEMPLATE_AVVISO_MESSAGGIO_NON_GESTITO, variabili,
               etichetta_simulazione=" - AVVISO MESSAGGIO NON GESTITO")


def invia_template_grezzo_per_demo(numero_whatsapp: str, content_sid: str, variabili: dict) -> tuple[bool, str]:
    """
    SOLO per lo strumento demo nel pannello admin (mostrare i template a
    chi visita, senza dover rifare tutto il giro di 4 telefoni/richieste
    vere). A differenza di _invia, qui NON c'è nessun ripiego automatico
    su testo libero se il template fallisce - per una demo vogliamo
    sapere SEMPRE con certezza se il template vero è arrivato o no, non
    un ripiego silenzioso che nasconderebbe il problema.
    """
    if not _TWILIO_CONFIGURATO:
        return False, "Twilio non è configurato in questo ambiente (variabili TWILIO_* mancanti)."
    if not content_sid:
        return False, "Questo template non ha ancora un Content SID impostato su Railway."
    try:
        parametri = {
            "from_": TWILIO_WHATSAPP_NUMBER,
            "to": f"whatsapp:{numero_whatsapp}",
            "content_sid": content_sid,
        }
        if variabili:
            parametri["content_variables"] = json.dumps(variabili)
        _client.messages.create(**parametri)
        return True, ""
    except Exception as errore:
        return False, str(errore)
