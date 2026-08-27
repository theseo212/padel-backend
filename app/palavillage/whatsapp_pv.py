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
from app.palavillage.config import NOME_CIRCOLO, FIRMA_MESSAGGIO, TEMPLATE_PV_RIEPILOGO_ISCRIZIONE


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
