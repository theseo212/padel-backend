"""
Punto di instradamento tra il sistema generico AnnaPadel e Palavillage,
per i messaggi WhatsApp in arrivo sullo stesso numero.

Questo modulo NON sostituisce il webhook esistente in app/main.py: viene
chiamato da lì, PRIMA della cascata generica, e restituisce True/False
per dire "l'ho gestito io" oppure "lascialo scorrere come prima".

Regola di instradamento (in ordine):
1. C'è un ButtonPayload con il prefisso di Palavillage? -> instradamento
   deterministico, gestito qui.
2. Non c'è nessun payload riconosciuto, ma il numero ha un "contesto
   attivo" Palavillage non scaduto (es. sta per rispondere con il
   punteggio del torneo)? -> instradato qui.
3. Altrimenti -> non è compito nostro, torna False, il chiamante
   prosegue con la cascata generica esattamente come fa oggi.
"""

from datetime import datetime, timedelta
from sqlalchemy.orm import Session

from app.palavillage.config import PREFISSO_ROUTING, MINUTI_VALIDITA_CONTESTO_ATTIVO
from app.palavillage.models import ContestoAttivoWhatsApp


def gestisci_webhook_palavillage(db_pv: Session, numero_mittente: str, dati: dict) -> bool:
    """
    dati = lo stesso dizionario del corpo del webhook Twilio (From, Body,
    ButtonPayload, ButtonText, NumMedia, ...), passato tale e quale da
    app/main.py.

    Ritorna True se il messaggio era di competenza di Palavillage (gestito
    qui, indipendentemente dall'esito), False se va lasciato scorrere.
    """
    button_payload = dati.get("ButtonPayload", "") or ""

    if button_payload.startswith(PREFISSO_ROUTING):
        azione = button_payload[len(PREFISSO_ROUTING):]  # es. "CONF::123"
        _gestisci_risposta_bottone(db_pv, numero_mittente, azione)
        return True

    contesto = (
        db_pv.query(ContestoAttivoWhatsApp)
        .filter(ContestoAttivoWhatsApp.whatsapp_numero == numero_mittente)
        .first()
    )
    if contesto and contesto.scade_il > datetime.utcnow():
        testo_messaggio = dati.get("Body", "")
        _gestisci_testo_libero(db_pv, numero_mittente, contesto, testo_messaggio)
        return True

    return False


def _gestisci_risposta_bottone(db_pv: Session, numero_mittente: str, azione: str) -> None:
    """
    Gestisce risposte a VERI bottoni Quick Reply WhatsApp (payload fisso,
    deciso in fase di creazione del template). La conferma/rifiuto di
    iscrizione al torneo NON passa da qui: usa un link con token
    (id.codice_casuale) invece di un bottone, perché il payload di un
    Quick Reply non può contenere l'id dinamico di ogni iscrizione - vedi
    /palavillage/rispondi/{token} in main.py e IscrizioneTorneo.codice_risposta.

    Questa funzione resta pronta per future interazioni Palavillage che
    useranno davvero bottoni Quick Reply a payload fisso (es. un singolo
    "Sì/No" senza bisogno di riferirsi a un id specifico).
    """
    print(f"[PALAVILLAGE][BOTTONE] {numero_mittente} -> azione non riconosciuta: '{azione}'")


def _gestisci_testo_libero(db_pv: Session, numero_mittente: str, contesto: ContestoAttivoWhatsApp, testo: str) -> None:
    """
    Il tipo di contesto (es. RICHIESTA_PUNTEGGIO) dice quale handler
    interpretare per il testo libero in arrivo.
    """
    if contesto.tipo_contesto == "RICHIESTA_PUNTEGGIO":
        from app.palavillage.motore_torneo import registra_punteggio_gruppo_membro
        registra_punteggio_gruppo_membro(db_pv, contesto.riferimento_id, testo)
        return

    print(
        f"[PALAVILLAGE][TESTO LIBERO] {numero_mittente} -> "
        f"tipo='{contesto.tipo_contesto}' rif={contesto.riferimento_id} testo='{testo}' "
        f"(handler da implementare)"
    )


def imposta_contesto_attivo(db_pv: Session, numero_whatsapp: str, tipo_contesto: str, riferimento_id: int | None = None) -> None:
    """
    Da chiamare ogni volta che Palavillage manda un messaggio che si
    aspetta una risposta in testo libero (es. richiesta punteggio).
    Sovrascrive un eventuale contesto precedente per lo stesso numero:
    vince sempre l'ultimo messaggio mandato (criterio "più recente vince"
    concordato per i casi ambigui).
    """
    scade_il = datetime.utcnow() + timedelta(minutes=MINUTI_VALIDITA_CONTESTO_ATTIVO)
    esistente = (
        db_pv.query(ContestoAttivoWhatsApp)
        .filter(ContestoAttivoWhatsApp.whatsapp_numero == numero_whatsapp)
        .first()
    )
    if esistente:
        esistente.tipo_contesto = tipo_contesto
        esistente.riferimento_id = riferimento_id
        esistente.creato_il = datetime.utcnow()
        esistente.scade_il = scade_il
    else:
        db_pv.add(ContestoAttivoWhatsApp(
            whatsapp_numero=numero_whatsapp,
            tipo_contesto=tipo_contesto,
            riferimento_id=riferimento_id,
            scade_il=scade_il,
        ))
    db_pv.commit()


def rimuovi_contesto_attivo(db_pv: Session, numero_whatsapp: str) -> None:
    """Da chiamare quando la risposta attesa è arrivata ed è stata gestita."""
    db_pv.query(ContestoAttivoWhatsApp).filter(
        ContestoAttivoWhatsApp.whatsapp_numero == numero_whatsapp
    ).delete()
    db_pv.commit()
