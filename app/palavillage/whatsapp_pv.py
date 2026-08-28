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

CONVENZIONE VARIABILI (importante per il riutilizzo futuro): il nome
del circolo e il nome del torneo/campionato NON sono mai scritti fissi
nel testo del template - sono sempre variabili numerate ({{N}}), esattamente
come nome/giorno/data. Così un domani, quando si aggiungerà un nuovo
circolo sullo stesso numero WhatsApp, gli stessi template già approvati
da Meta potranno essere riusati identici, cambiando solo i VALORI delle
variabili (letti da NOME_CIRCOLO del circolo in questione) - senza
dover sottomettere una nuova approvazione per ogni nuovo circolo.
"""

from app.services.whatsapp import _invia, genera_otp, invia_otp_whatsapp  # noqa: F401 (re-esportate)
from app.palavillage.config import (
    NOME_CIRCOLO, FIRMA_MESSAGGIO, TEMPLATE_PV_RIEPILOGO_ISCRIZIONE,
    TEMPLATE_PV_RICHIESTA_ISCRIZIONE, TEMPLATE_PV_SOLLECITO_ISCRIZIONE,
    TEMPLATE_PV_GRUPPO_ASSEGNATO, TEMPLATE_PV_SEI_RISERVA, TEMPLATE_PV_PROMOZIONE_RISERVA,
    TEMPLATE_PV_RICHIESTA_PUNTEGGIO, TEMPLATE_PV_SOLLECITO_PUNTEGGIO, TEMPLATE_PV_CLASSIFICA_AGGIORNATA,
    TEMPLATE_PV_TORNEO_ANNULLATO, TEMPLATE_PV_GRUPPO_INCOMPLETO, TEMPLATE_PV_SOSTITUZIONE_COMPAGNO,
    URL_BASE_BACKEND_PUBBLICO,
)


def invia_riepilogo_iscrizione_pv(numero_whatsapp: str, nome: str, giorni_leggibili: str,
                                    nome_circolo: str = NOME_CIRCOLO) -> bool:
    """
    Mandato una volta confermata l'iscrizione (subito, se il numero è già
    fidato dal sistema generico o già validato qui; altrimenti solo dopo
    la verifica OTP).
    """
    testo = (
        f"Ciao {nome}! Ho registrato la tua iscrizione ai campionati di {nome_circolo}: "
        f"{giorni_leggibili}. Ti scriverò prima di ogni torneo per la conferma."
    ) + FIRMA_MESSAGGIO
    variabili = {"1": nome, "2": giorni_leggibili, "3": nome_circolo} if nome else None
    return _invia(numero_whatsapp, testo, TEMPLATE_PV_RIEPILOGO_ISCRIZIONE, variabili,
                  etichetta_simulazione=" PALAVILLAGE")


def invia_richiesta_iscrizione_torneo(numero_whatsapp: str, nome: str, nome_torneo: str, giorno_leggibile: str,
                                        data_leggibile: str, token: str, nome_circolo: str = NOME_CIRCOLO) -> bool:
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
        f"Ciao {nome}! Il torneo {nome_torneo} di {giorno_leggibile} {data_leggibile} a {nome_circolo} si avvicina: "
        f"confermi la tua partecipazione? Rispondi qui: {url_risposta}"
    ) + FIRMA_MESSAGGIO
    # Il template Twilio (Call to Action) ha già l'indirizzo di base
    # scritto al suo interno: la sola variabile dinamica nel bottone è
    # il token (ultima variabile, {{6}}).
    variabili = {"1": nome, "2": nome_torneo, "3": giorno_leggibile, "4": data_leggibile, "5": nome_circolo, "6": token} if nome else None
    return _invia(numero_whatsapp, testo, TEMPLATE_PV_RICHIESTA_ISCRIZIONE, variabili,
                  etichetta_simulazione=" PALAVILLAGE - RICHIESTA ISCRIZIONE")


def invia_sollecito_iscrizione_torneo(numero_whatsapp: str, nome: str, nome_torneo: str, giorno_leggibile: str,
                                        data_leggibile: str, token: str, nome_circolo: str = NOME_CIRCOLO) -> bool:
    """Mandato T-3gg solo a chi non ha ancora risposto alla richiesta iniziale."""
    url_risposta = f"{URL_BASE_BACKEND_PUBBLICO}/palavillage/rispondi/{token}"
    testo = (
        f"Ciao {nome}, non ho ancora ricevuto una tua risposta per il torneo {nome_torneo} di "
        f"{giorno_leggibile} {data_leggibile} a {nome_circolo}: confermi la tua partecipazione? "
        f"Rispondi qui: {url_risposta}"
    ) + FIRMA_MESSAGGIO
    variabili = {"1": nome, "2": nome_torneo, "3": giorno_leggibile, "4": data_leggibile, "5": nome_circolo, "6": token} if nome else None
    return _invia(numero_whatsapp, testo, TEMPLATE_PV_SOLLECITO_ISCRIZIONE, variabili,
                  etichetta_simulazione=" PALAVILLAGE - SOLLECITO ISCRIZIONE")


def invia_conferma_ricevuta_torneo(numero_whatsapp: str, confermato: bool, giorno_leggibile: str, data_leggibile: str) -> bool:
    """Piccolo messaggio di conferma immediata dopo aver premuto un bottone (nessun template: risposta a testo libero dentro la finestra di conversazione appena aperta dall'utente)."""
    if confermato:
        testo = f"Perfetto, sei confermato/a per {giorno_leggibile} {data_leggibile}! Ti scriverò con i dettagli del gruppo." + FIRMA_MESSAGGIO
    else:
        testo = f"Ok, ho segnato che non ci sarai {giorno_leggibile} {data_leggibile}. A presto!" + FIRMA_MESSAGGIO
    return _invia(numero_whatsapp, testo, None, None, etichetta_simulazione=" PALAVILLAGE - ACK BOTTONE")


def invia_gruppo_assegnato_torneo(numero_whatsapp: str, nome: str, nome_torneo: str, giorno_leggibile: str,
                                    data_leggibile: str, compagni: str,
                                    nome_circolo: str = NOME_CIRCOLO) -> bool:
    """
    Mandato a ogni titolare dopo la formazione gruppi (T-12h). 'compagni'
    è già una stringa pronta con i 3 nomi (separati da virgola, non da
    ritorni a capo dentro la variabile - vietato da WhatsApp anche con
    JSON tecnicamente valido, vedi lezioni imparate nell'handoff).
    """
    testo = (
        f"Ciao {nome}! Ecco il tuo gruppo per il torneo {nome_torneo} di {giorno_leggibile} {data_leggibile} a {nome_circolo}. "
        f"Giocherai con: {compagni}. Ci vediamo lì!"
    ) + FIRMA_MESSAGGIO
    variabili = {
        "1": nome, "2": nome_torneo, "3": giorno_leggibile, "4": data_leggibile,
        "5": nome_circolo, "6": compagni,
    } if nome else None
    return _invia(numero_whatsapp, testo, TEMPLATE_PV_GRUPPO_ASSEGNATO, variabili,
                  etichetta_simulazione=" PALAVILLAGE - GRUPPO ASSEGNATO")


def invia_sei_riserva_torneo(numero_whatsapp: str, nome: str, nome_torneo: str, giorno_leggibile: str, data_leggibile: str) -> bool:
    """
    Mandato a chi resta fuori dai quartetti per un numero di conferme non
    multiplo di 4. Tono positivo di proposito (concordato con il cliente):
    non "sei escluso", ma "sei riserva" - con la prospettiva concreta di
    entrare se si libera un posto.
    """
    testo = (
        f"Ciao {nome}! Per il torneo {nome_torneo} di {giorno_leggibile} {data_leggibile} sei riserva: se si libera un posto "
        f"all'ultimo momento sarai il/la prima ad essere chiamato/a. Grazie per la disponibilità!"
    ) + FIRMA_MESSAGGIO
    variabili = {"1": nome, "2": nome_torneo, "3": giorno_leggibile, "4": data_leggibile} if nome else None
    return _invia(numero_whatsapp, testo, TEMPLATE_PV_SEI_RISERVA, variabili,
                  etichetta_simulazione=" PALAVILLAGE - SEI RISERVA")


def invia_avviso_gruppo_incompleto(numero_whatsapp: str, nome: str, nome_torneo: str, giorno_leggibile: str, data_leggibile: str) -> bool:
    """Mandato ai 3 compagni rimasti quando un titolare cancella all'ultimo momento, mentre si cerca un sostituto."""
    testo = (
        f"Ciao {nome}, un tuo compagno del torneo {nome_torneo} di {giorno_leggibile} {data_leggibile} non può più venire: "
        f"sto cercando un sostituto tra le riserve, ti aggiorno appena ho novità."
    ) + FIRMA_MESSAGGIO
    variabili = {"1": nome, "2": nome_torneo, "3": giorno_leggibile, "4": data_leggibile} if nome else None
    return _invia(numero_whatsapp, testo, TEMPLATE_PV_GRUPPO_INCOMPLETO, variabili,
                  etichetta_simulazione=" PALAVILLAGE - GRUPPO INCOMPLETO")


def invia_proposta_promozione_riserva(numero_whatsapp: str, nome: str, nome_torneo: str, giorno_leggibile: str,
                                        data_leggibile: str, token: str, minuti_scadenza: int,
                                        nome_circolo: str = NOME_CIRCOLO) -> bool:
    """Mandato alla prima riserva disponibile quando si libera un posto dopo la formazione gruppi."""
    url_risposta = f"{URL_BASE_BACKEND_PUBBLICO}/palavillage/rispondi/{token}"
    testo = (
        f"Ciao {nome}! Si è liberato un posto per il torneo {nome_torneo} di {giorno_leggibile} {data_leggibile} a {nome_circolo}: "
        f"sei dentro! Conferma entro {minuti_scadenza} minuti qui: {url_risposta}"
    ) + FIRMA_MESSAGGIO
    variabili = {
        "1": nome, "2": nome_torneo, "3": giorno_leggibile, "4": data_leggibile,
        "5": nome_circolo, "6": str(minuti_scadenza), "7": token,
    } if nome else None
    return _invia(numero_whatsapp, testo, TEMPLATE_PV_PROMOZIONE_RISERVA, variabili,
                  etichetta_simulazione=" PALAVILLAGE - PROPOSTA PROMOZIONE")


def invia_promozione_confermata(numero_whatsapp: str, nome: str, giorno_leggibile: str, data_leggibile: str,
                                  compagni: str) -> bool:
    """Conferma alla riserva appena promossa, con i dettagli del gruppo che si ritrova."""
    testo = (
        f"Perfetto {nome}, sei confermato/a per {giorno_leggibile} {data_leggibile}!\n"
        f"Giocherai con: {compagni}"
    ) + FIRMA_MESSAGGIO
    return _invia(numero_whatsapp, testo, None, None, etichetta_simulazione=" PALAVILLAGE - PROMOZIONE CONFERMATA")


def invia_sostituzione_compagno(numero_whatsapp: str, nome: str, nome_torneo: str, giorno_leggibile: str,
                                  data_leggibile: str, nome_nuovo_compagno: str) -> bool:
    """Mandato ai 3 compagni rimasti quando la riserva ha accettato ed è entrata nel gruppo."""
    testo = (
        f"Ciao {nome}, per il torneo {nome_torneo} di {giorno_leggibile} {data_leggibile} il tuo nuovo compagno di gruppo è: "
        f"{nome_nuovo_compagno}. A presto!"
    ) + FIRMA_MESSAGGIO
    variabili = {
        "1": nome, "2": nome_torneo, "3": giorno_leggibile, "4": data_leggibile, "5": nome_nuovo_compagno,
    } if nome else None
    return _invia(numero_whatsapp, testo, TEMPLATE_PV_SOSTITUZIONE_COMPAGNO, variabili,
                  etichetta_simulazione=" PALAVILLAGE - SOSTITUZIONE COMPAGNO")


def invia_notifica_admin_nessuna_riserva(nome_torneo: str, giorno_leggibile: str, data_leggibile: str, gruppo_numero: int,
                                           nome_circolo: str = NOME_CIRCOLO) -> None:
    """
    Nessuna riserva disponibile (o nessuna ha risposto in tempo): avvisa
    SOLO l'amministratore, che gestisce manualmente - nessuna azione
    automatica ulteriore, come concordato. Nessun template: messaggio
    tecnico solo per te, non per un giocatore.
    """
    from app.config import ADMIN_WHATSAPP_NUMERI
    testo = (
        f"⚠️ {nome_circolo}: nel gruppo {gruppo_numero} del torneo {nome_torneo} di {giorno_leggibile} {data_leggibile} "
        f"si è liberato un posto e non ci sono (più) riserve disponibili. Serve un intervento manuale."
    )
    for numero in ADMIN_WHATSAPP_NUMERI:
        _invia(numero, testo, None, None, etichetta_simulazione=" PALAVILLAGE - AVVISO ADMIN")


def invia_richiesta_punteggio_torneo(numero_whatsapp: str, nome: str, nome_torneo: str, giorno_leggibile: str, data_leggibile: str) -> bool:
    """Mandato a fine torneo (dopo ORE_DURATA_TORNEO dall'inizio) a ogni titolare che ha giocato."""
    testo = (
        f"Ciao {nome}! Come è andato il torneo {nome_torneo} di {giorno_leggibile} {data_leggibile}? "
        f"Rispondimi con il numero totale di game fatti (es. \"18\")."
    ) + FIRMA_MESSAGGIO
    variabili = {"1": nome, "2": nome_torneo, "3": giorno_leggibile, "4": data_leggibile} if nome else None
    return _invia(numero_whatsapp, testo, TEMPLATE_PV_RICHIESTA_PUNTEGGIO, variabili,
                  etichetta_simulazione=" PALAVILLAGE - RICHIESTA PUNTEGGIO")


def invia_sollecito_punteggio_torneo(numero_whatsapp: str, nome: str, nome_torneo: str, giorno_leggibile: str, data_leggibile: str) -> bool:
    """Mandato T+2h a chi non ha ancora risposto con il proprio punteggio."""
    testo = (
        f"Ciao {nome}, non ho ancora ricevuto il tuo punteggio per il torneo {nome_torneo} di "
        f"{giorno_leggibile} {data_leggibile}: quanti game hai fatto? Basta il numero (es. \"18\")."
    ) + FIRMA_MESSAGGIO
    variabili = {"1": nome, "2": nome_torneo, "3": giorno_leggibile, "4": data_leggibile} if nome else None
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


def invia_classifica_aggiornata(numero_whatsapp: str, nome: str, nome_campionato: str, campionato_id: int) -> bool:
    """
    Mandato a fine raccolta punteggi, a tutti i partecipanti del
    torneo: non più un elenco testuale (limitato dalla lunghezza
    massima di un template WhatsApp), ma un link al PDF con la
    classifica completa, tabella orizzontale con tutte le tappe.

    Il link è un bottone Call to Action con indirizzo di base FISSO e
    solo l'id del campionato come variabile - non l'URL intero dentro
    il testo: Meta è cauto nell'approvare template dove una variabile
    diventa un link completo e libero (potrebbe teoricamente portare a
    qualunque indirizzo, cosa che l'approvazione non può controllare in
    anticipo). Con un bottone, il dominio di destinazione è fisso e
    verificato una volta sola in fase di approvazione.
    """
    url_classifica = f"{URL_BASE_BACKEND_PUBBLICO}/palavillage/classifica/{campionato_id}"
    testo = f"Ciao {nome}! È pronta la classifica aggiornata di {nome_campionato}. Guardala qui: {url_classifica}" + FIRMA_MESSAGGIO
    # Il template Twilio (Call to Action) ha già l'indirizzo di base e il
    # suffisso ".pdf" scritti al suo interno: la sola variabile dinamica
    # nel bottone è l'id del campionato ({{3}}).
    variabili = {"1": nome, "2": nome_campionato, "3": str(campionato_id)} if nome else None
    return _invia(numero_whatsapp, testo, TEMPLATE_PV_CLASSIFICA_AGGIORNATA, variabili,
                  etichetta_simulazione=" PALAVILLAGE - CLASSIFICA AGGIORNATA (link)")


def invia_torneo_annullato(numero_whatsapp: str, nome: str, nome_torneo: str, giorno_leggibile: str,
                             data_leggibile: str, nome_circolo: str = NOME_CIRCOLO) -> bool:
    """Mandato solo a chi aveva già ricevuto una richiesta di iscrizione, quando l'admin cancella un torneo futuro (es. giorno festivo)."""
    testo = (
        f"Ciao {nome}, il torneo {nome_torneo} di {giorno_leggibile} {data_leggibile} a {nome_circolo} è stato annullato. "
        f"Ti aggiornerò per la prossima data disponibile."
    ) + FIRMA_MESSAGGIO
    variabili = {"1": nome, "2": nome_torneo, "3": giorno_leggibile, "4": data_leggibile, "5": nome_circolo} if nome else None
    return _invia(numero_whatsapp, testo, TEMPLATE_PV_TORNEO_ANNULLATO, variabili,
                  etichetta_simulazione=" PALAVILLAGE - TORNEO ANNULLATO")
