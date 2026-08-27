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
