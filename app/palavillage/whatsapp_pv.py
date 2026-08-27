"""
Invio messaggi WhatsApp specifici di Palavillage.

Riusiamo volutamente il "punto unico di invio" (_invia) del sistema
generico: stesso account Twilio, stesso numero mittente, stessa logica
a cascata template->testo libero->simulazione già collaudata - qui
cambiano solo i template SID (dedicati a Palavillage) e i testi di
riserva per la simulazione locale.

Per l'OTP invece riusiamo DIRETTAMENTE anche il template: la categoria
Authentication ha il corpo del messaggio fisso deciso da Meta (vedi
lezioni imparate nell'handoff), quindi non ha senso duplicarlo - lo
stesso codice, sullo stesso numero, serve identico a entrambi i sistemi.
"""

from app.services.whatsapp import _invia, genera_otp, invia_otp_whatsapp  # noqa: F401 (re-esportate)
from app.palavillage.config import (
    NOME_CIRCOLO, FIRMA_MESSAGGIO, TEMPLATE_PV_RIEPILOGO_ISCRIZIONE,
    TEMPLATE_PV_RICHIESTA_ISCRIZIONE, TEMPLATE_PV_SOLLECITO_ISCRIZIONE,
    TEMPLATE_PV_GRUPPO_ASSEGNATO, TEMPLATE_PV_SEI_RISERVA, TEMPLATE_PV_PROMOZIONE_RISERVA,
    TEMPLATE_PV_RICHIESTA_PUNTEGGIO, TEMPLATE_PV_SOLLECITO_PUNTEGGIO, TEMPLATE_PV_CLASSIFICA_AGGIORNATA,
    URL_BASE_BACKEND_PUBBLICO,
)


def invia_riepilogo_iscrizione_pv(numero_whatsapp: str, nome: str, giorni_leggibili: str,
                                    lato_leggibile: str, livello: str) -> bool:
    """
    Mandato una volta confermata l'iscrizione (subito, se il numero è già
    fidato dal sistema generico o già validato qui; altrimenti solo dopo
    la verifica OTP).
    """
    testo = (
        f"Ciao {nome}! Ho registrato la tua iscrizione ai tornei del mattino di "
        f"{NOME_CIRCOLO}.\n"
        f"Mattine scelte: {giorni_leggibili}\n"
        f"Lato: {lato_leggibile}\n"
        f"Livello: {livello}\n\n"
        f"Ti scriverò io qualche giorno prima di ogni torneo per chiederti conferma."
    ) + FIRMA_MESSAGGIO
    variabili = {"1": nome, "2": giorni_leggibili, "3": lato_leggibile, "4": livello} if nome else None
    return _invia(numero_whatsapp, testo, TEMPLATE_PV_RIEPILOGO_ISCRIZIONE, variabili,
                  etichetta_simulazione=" PALAVILLAGE")


def invia_richiesta_iscrizione_torneo(numero_whatsapp: str, nome: str, giorno_leggibile: str,
                                        data_leggibile: str, token: str) -> bool:
    """
    Mandato T-6gg prima del torneo. Include il riferimento specifico
    (giorno + data) per qualificarsi come Utility davanti a Meta (vedi
    lezioni imparate nell'handoff). Il link di risposta usa un token
    (id.codice_casuale) invece di un bottone Quick Reply, perché il
    payload di un Quick Reply è fisso e non può contenere l'id dinamico
    di ogni singola iscrizione (vedi commento su IscrizioneTorneo.codice_risposta).
    """
    url_risposta = f"{URL_BASE_BACKEND_PUBBLICO}/palavillage/rispondi/{token}"
    testo = (
        f"Ciao {nome}! Il torneo di {giorno_leggibile} {data_leggibile} a {NOME_CIRCOLO} si avvicina: "
        f"confermi la tua partecipazione? Rispondi qui: {url_risposta}"
    ) + FIRMA_MESSAGGIO
    # Il template Twilio (Call to Action) ha già l'indirizzo di base
    # scritto al suo interno: la sola variabile dinamica è il token.
    variabili = {"1": nome, "2": giorno_leggibile, "3": data_leggibile, "4": token} if nome else None
    return _invia(numero_whatsapp, testo, TEMPLATE_PV_RICHIESTA_ISCRIZIONE, variabili,
                  etichetta_simulazione=" PALAVILLAGE - RICHIESTA ISCRIZIONE")


def invia_sollecito_iscrizione_torneo(numero_whatsapp: str, nome: str, giorno_leggibile: str,
                                        data_leggibile: str, token: str) -> bool:
    """Mandato T-3gg solo a chi non ha ancora risposto alla richiesta iniziale."""
    url_risposta = f"{URL_BASE_BACKEND_PUBBLICO}/palavillage/rispondi/{token}"
    testo = (
        f"Ciao {nome}, non ho ancora ricevuto una tua risposta per il torneo di "
        f"{giorno_leggibile} {data_leggibile} a {NOME_CIRCOLO}: confermi la tua partecipazione? "
        f"Rispondi qui: {url_risposta}"
    ) + FIRMA_MESSAGGIO
    variabili = {"1": nome, "2": giorno_leggibile, "3": data_leggibile, "4": token} if nome else None
    return _invia(numero_whatsapp, testo, TEMPLATE_PV_SOLLECITO_ISCRIZIONE, variabili,
                  etichetta_simulazione=" PALAVILLAGE - SOLLECITO ISCRIZIONE")


def invia_conferma_ricevuta_torneo(numero_whatsapp: str, confermato: bool, giorno_leggibile: str, data_leggibile: str) -> bool:
    """Piccolo messaggio di conferma immediata dopo aver premuto un bottone (nessun template: risposta a testo libero dentro la finestra di conversazione appena aperta dall'utente)."""
    if confermato:
        testo = f"Perfetto, sei confermato/a per {giorno_leggibile} {data_leggibile}! Ti scriverò con i dettagli del gruppo." + FIRMA_MESSAGGIO
    else:
        testo = f"Ok, ho segnato che non ci sarai {giorno_leggibile} {data_leggibile}. A presto!" + FIRMA_MESSAGGIO
    return _invia(numero_whatsapp, testo, None, None, etichetta_simulazione=" PALAVILLAGE - ACK BOTTONE")


def invia_gruppo_assegnato_torneo(numero_whatsapp: str, nome: str, giorno_leggibile: str, data_leggibile: str,
                                    compagni: str, lato_assegnato: str) -> bool:
    """
    Mandato a ogni titolare dopo la formazione gruppi (T-12h). 'compagni'
    è già una stringa pronta con i 3 nomi (separati da virgola, non da
    ritorni a capo dentro la variabile - vietato da WhatsApp anche con
    JSON tecnicamente valido, vedi lezioni imparate nell'handoff).
    """
    lato_leggibile = {"DX": "Destra", "SX": "Sinistra"}.get(lato_assegnato, lato_assegnato)
    testo = (
        f"Ciao {nome}! Ecco il tuo gruppo per {giorno_leggibile} {data_leggibile} a {NOME_CIRCOLO}:\n"
        f"Giocherai con: {compagni}\n"
        f"Lato assegnato: {lato_leggibile}\n"
        f"Ci vediamo lì!"
    ) + FIRMA_MESSAGGIO
    variabili = {"1": nome, "2": giorno_leggibile, "3": data_leggibile, "4": compagni, "5": lato_leggibile} if nome else None
    return _invia(numero_whatsapp, testo, TEMPLATE_PV_GRUPPO_ASSEGNATO, variabili,
                  etichetta_simulazione=" PALAVILLAGE - GRUPPO ASSEGNATO")


def invia_sei_riserva_torneo(numero_whatsapp: str, nome: str, giorno_leggibile: str, data_leggibile: str) -> bool:
    """
    Mandato a chi resta fuori dai quartetti per un numero di conferme non
    multiplo di 4. Tono positivo di proposito (concordato con il cliente):
    non "sei escluso", ma "sei riserva" - con la prospettiva concreta di
    entrare se si libera un posto.
    """
    testo = (
        f"Ciao {nome}! Per {giorno_leggibile} {data_leggibile} sei riserva: se si libera un posto "
        f"all'ultimo momento sarai il/la prima ad essere chiamato/a. Grazie per la disponibilità!"
    ) + FIRMA_MESSAGGIO
    variabili = {"1": nome, "2": giorno_leggibile, "3": data_leggibile} if nome else None
    return _invia(numero_whatsapp, testo, TEMPLATE_PV_SEI_RISERVA, variabili,
                  etichetta_simulazione=" PALAVILLAGE - SEI RISERVA")


def invia_avviso_gruppo_incompleto(numero_whatsapp: str, nome: str, giorno_leggibile: str, data_leggibile: str) -> bool:
    """Mandato ai 3 compagni rimasti quando un titolare cancella all'ultimo momento, mentre si cerca un sostituto."""
    testo = (
        f"Ciao {nome}, un tuo compagno di {giorno_leggibile} {data_leggibile} non può più venire: "
        f"sto cercando un sostituto tra le riserve, ti aggiorno appena ho novità."
    ) + FIRMA_MESSAGGIO
    return _invia(numero_whatsapp, testo, None, None, etichetta_simulazione=" PALAVILLAGE - GRUPPO INCOMPLETO")


def invia_proposta_promozione_riserva(numero_whatsapp: str, nome: str, giorno_leggibile: str, data_leggibile: str,
                                        token: str, minuti_scadenza: int) -> bool:
    """Mandato alla prima riserva disponibile quando si libera un posto dopo la formazione gruppi."""
    url_risposta = f"{URL_BASE_BACKEND_PUBBLICO}/palavillage/rispondi/{token}"
    testo = (
        f"Ciao {nome}! Si è liberato un posto per il torneo di {giorno_leggibile} {data_leggibile} a {NOME_CIRCOLO}: "
        f"sei dentro! Conferma entro {minuti_scadenza} minuti qui: {url_risposta}"
    ) + FIRMA_MESSAGGIO
    variabili = {"1": nome, "2": giorno_leggibile, "3": data_leggibile, "4": str(minuti_scadenza), "5": token} if nome else None
    return _invia(numero_whatsapp, testo, TEMPLATE_PV_PROMOZIONE_RISERVA, variabili,
                  etichetta_simulazione=" PALAVILLAGE - PROPOSTA PROMOZIONE")


def invia_promozione_confermata(numero_whatsapp: str, nome: str, giorno_leggibile: str, data_leggibile: str,
                                  compagni: str, lato_assegnato: str) -> bool:
    """Conferma alla riserva appena promossa, con i dettagli del gruppo che si ritrova."""
    lato_leggibile = {"DX": "Destra", "SX": "Sinistra"}.get(lato_assegnato, lato_assegnato)
    testo = (
        f"Perfetto {nome}, sei confermato/a per {giorno_leggibile} {data_leggibile}!\n"
        f"Giocherai con: {compagni}\n"
        f"Lato assegnato: {lato_leggibile}"
    ) + FIRMA_MESSAGGIO
    return _invia(numero_whatsapp, testo, None, None, etichetta_simulazione=" PALAVILLAGE - PROMOZIONE CONFERMATA")


def invia_sostituzione_compagno(numero_whatsapp: str, nome: str, giorno_leggibile: str, data_leggibile: str,
                                  nome_nuovo_compagno: str) -> bool:
    """Mandato ai 3 compagni rimasti quando la riserva ha accettato ed è entrata nel gruppo."""
    testo = (
        f"Ciao {nome}, per {giorno_leggibile} {data_leggibile} il tuo nuovo compagno di gruppo è: "
        f"{nome_nuovo_compagno}. A presto!"
    ) + FIRMA_MESSAGGIO
    return _invia(numero_whatsapp, testo, None, None, etichetta_simulazione=" PALAVILLAGE - SOSTITUZIONE COMPAGNO")


def invia_notifica_admin_nessuna_riserva(giorno_leggibile: str, data_leggibile: str, gruppo_numero: int) -> None:
    """
    Nessuna riserva disponibile (o nessuna ha risposto in tempo): avvisa
    SOLO l'amministratore, che gestisce manualmente - nessuna azione
    automatica ulteriore, come concordato.
    """
    from app.config import ADMIN_WHATSAPP_NUMERI
    testo = (
        f"⚠️ Palavillage: nel gruppo {gruppo_numero} del torneo di {giorno_leggibile} {data_leggibile} "
        f"si è liberato un posto e non ci sono (più) riserve disponibili. Serve un intervento manuale."
    )
    for numero in ADMIN_WHATSAPP_NUMERI:
        _invia(numero, testo, None, None, etichetta_simulazione=" PALAVILLAGE - AVVISO ADMIN")


def invia_richiesta_punteggio_torneo(numero_whatsapp: str, nome: str, giorno_leggibile: str, data_leggibile: str) -> bool:
    """Mandato a fine torneo (dopo ORE_DURATA_TORNEO dall'inizio) a ogni titolare che ha giocato."""
    testo = (
        f"Ciao {nome}! Come è andato il torneo di {giorno_leggibile} {data_leggibile}? "
        f"Rispondimi con il numero totale di game fatti (es. \"18\")."
    ) + FIRMA_MESSAGGIO
    variabili = {"1": nome, "2": giorno_leggibile, "3": data_leggibile} if nome else None
    return _invia(numero_whatsapp, testo, TEMPLATE_PV_RICHIESTA_PUNTEGGIO, variabili,
                  etichetta_simulazione=" PALAVILLAGE - RICHIESTA PUNTEGGIO")


def invia_sollecito_punteggio_torneo(numero_whatsapp: str, nome: str, giorno_leggibile: str, data_leggibile: str) -> bool:
    """Mandato T+2h a chi non ha ancora risposto con il proprio punteggio."""
    testo = (
        f"Ciao {nome}, non ho ancora ricevuto il tuo punteggio per il torneo di "
        f"{giorno_leggibile} {data_leggibile}: quanti game hai fatto? Basta il numero (es. \"18\")."
    ) + FIRMA_MESSAGGIO
    variabili = {"1": nome, "2": giorno_leggibile, "3": data_leggibile} if nome else None
    return _invia(numero_whatsapp, testo, TEMPLATE_PV_SOLLECITO_PUNTEGGIO, variabili,
                  etichetta_simulazione=" PALAVILLAGE - SOLLECITO PUNTEGGIO")


def invia_punteggio_non_capito(numero_whatsapp: str) -> bool:
    """Mandato quando la risposta ricevuta non è interpretabile come un numero di game."""
    testo = "Non ho capito il punteggio, rispondimi solo con il numero di game fatti (es. \"18\")." + FIRMA_MESSAGGIO
    return _invia(numero_whatsapp, testo, None, None, etichetta_simulazione=" PALAVILLAGE - PUNTEGGIO NON CAPITO")


def invia_punteggio_confermato(numero_whatsapp: str, punteggio: int) -> bool:
    """Piccola conferma immediata dopo aver ricevuto e registrato il punteggio."""
    testo = f"Perfetto, ho segnato {punteggio} game. Grazie!" + FIRMA_MESSAGGIO
    return _invia(numero_whatsapp, testo, None, None, etichetta_simulazione=" PALAVILLAGE - PUNTEGGIO CONFERMATO")


def invia_classifica_aggiornata(numero_whatsapp: str, nome: str, nome_campionato: str, classifica_testo: str) -> bool:
    """
    Mandato a fine raccolta punteggi, a tutti i partecipanti del
    torneo. 'classifica_testo' è già una stringa pronta con le righe
    separate da " - " (mai un vero ritorno a capo dentro una variabile
    di template, vietato da WhatsApp anche con JSON valido).
    """
    testo = f"Ciao {nome}! Classifica aggiornata di {nome_campionato}:\n{classifica_testo}" + FIRMA_MESSAGGIO
    variabili = {"1": nome, "2": nome_campionato, "3": classifica_testo} if nome else None
    return _invia(numero_whatsapp, testo, TEMPLATE_PV_CLASSIFICA_AGGIORNATA, variabili,
                  etichetta_simulazione=" PALAVILLAGE - CLASSIFICA AGGIORNATA")
