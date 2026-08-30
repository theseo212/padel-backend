"""
Genera il PDF con le tabelle dei gruppi e la griglia punteggi da stampare
per la segreteria, un torneo alla volta. Layout concordato:
- Foglio A4 verticale
- 2 gruppi per pagina (uno sopra, uno sotto)
- Intestazione pagina: nome circolo, nome campionato, numero tappa, data
- Per ogni gruppo: tabella 5 righe x 5 colonne (intestazione + 4
  giocatori) x (cognome, 1ª partita, 2ª partita, 3ª partita, totale) -
  solo i cognomi, le altre celle vanno compilate a penna durante il torneo.
"""

import io
from sqlalchemy.orm import Session
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak

from app.palavillage.models import Torneo, Campionato, GruppoPV, GruppoMembroPV, UtentePV
from app.palavillage.config import NOME_CIRCOLO

_NOMI_GIORNI_LEGGIBILI = ["Lunedì", "Martedì", "Mercoledì", "Giovedì", "Venerdì", "Sabato", "Domenica"]


def _nome_campionato_leggibile(campionato: Campionato) -> str:
    if campionato.nome:
        return campionato.nome
    return f"Campionato {_NOMI_GIORNI_LEGGIBILI[campionato.giorno_settimana]} #{campionato.numero_edizione}"


def _tabella_gruppo(numero_gruppo: int, cognomi: list[str]) -> list:
    """
    Costruisce il titolo + la tabella di UN gruppo (elementi platypus
    pronti da aggiungere alla story).

    Dimensionata apposta per occupare circa metà di un foglio A4 a
    gruppo: questi fogli vengono ritagliati e portati fisicamente sul
    campo, quindi devono restare grandi e ben visibili (cognomi in
    caratteri grandi e leggibili da qualche metro di distanza) - un
    foglietto piccolo si perde o si sporca troppo facilmente.
    """
    stili = getSampleStyleSheet()
    stile_titolo_gruppo = ParagraphStyle(
        "TitoloGruppo", parent=stili["Heading2"], fontSize=16, spaceAfter=4, spaceBefore=2,
    )

    dati_tabella = [["Cognome", "1ª partita", "2ª partita", "3ª partita", "TOTALE"]]
    for cognome in cognomi:
        dati_tabella.append([cognome, "", "", "", ""])
    while len(dati_tabella) < 5:
        dati_tabella.append(["", "", "", "", ""])

    larghezza_cognome = 6.0 * cm
    larghezza_partita = 3.0 * cm
    larghezza_totale = 3.4 * cm
    tabella = Table(
        dati_tabella,
        colWidths=[larghezza_cognome, larghezza_partita, larghezza_partita, larghezza_partita, larghezza_totale],
        rowHeights=[1.1 * cm] + [2.15 * cm] * 4,
    )
    tabella.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 1, colors.black),
        ("BOX", (0, 0), (-1, -1), 1.5, colors.black),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1B3A63")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 12),
        # Cognomi: grandi e in grassetto, per essere letti da lontano
        # una volta che il foglio è ritagliato e appoggiato a bordo campo.
        ("FONTNAME", (0, 1), (0, -1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 1), (0, -1), 22),
        ("FONTSIZE", (1, 1), (-1, -1), 12),
        ("ALIGN", (1, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (0, -1), 10),
        # Testo grande "centrato" percepito come troppo basso (effetto
        # tipografico normale con caratteri grandi: lo spazio riservato
        # sotto per lettere come g/p/q sposta il centro ottico verso il
        # basso) - compensiamo con un padding asimmetrico che sposta
        # visivamente il testo un po' più in alto nella cella.
        ("TOPPADDING", (0, 1), (0, -1), 2),
        ("BOTTOMPADDING", (0, 1), (0, -1), 14),
        # Colonna Totale: è il dato più importante di tutti. Nessuno
        # sfondo colorato (uno sfondo scuro impedirebbe pure di scriverci
        # sopra a penna, e uno chiaro sparisce in stampa bianco/nero) -
        # solo un bordo ben più spesso delle altre colonne e una cifra
        # grande quanto il cognome, per essere inequivocabile a colpo
        # d'occhio senza affidarsi al colore.
        ("BOX", (4, 0), (4, -1), 4, colors.black),
        ("FONTNAME", (4, 1), (4, -1), "Helvetica-Bold"),
        ("FONTSIZE", (4, 1), (4, -1), 24),
        ("TOPPADDING", (4, 1), (4, -1), 2),
        ("BOTTOMPADDING", (4, 1), (4, -1), 14),
    ]))

    return [Paragraph(f"Gruppo {numero_gruppo}", stile_titolo_gruppo), tabella]


def genera_pdf_torneo(db_pv: Session, torneo_id: int) -> bytes | None:
    """
    Ritorna i byte del PDF pronto da allegare all'email, oppure None se
    il torneo non ha nessun gruppo formato (nulla da stampare).
    """
    torneo = db_pv.query(Torneo).filter(Torneo.id == torneo_id).first()
    if torneo is None:
        return None

    campionato = db_pv.query(Campionato).filter(Campionato.id == torneo.campionato_id).first()
    gruppi = db_pv.query(GruppoPV).filter(GruppoPV.torneo_id == torneo.id).order_by(GruppoPV.numero_gruppo).all()
    if not gruppi:
        return None

    giorno_leggibile = _NOMI_GIORNI_LEGGIBILI[torneo.giorno_settimana]
    data_leggibile = torneo.data.strftime("%d/%m/%Y")
    nome_campionato = _nome_campionato_leggibile(campionato)
    numero_tappa = torneo.numero_tappa or "?"

    stili = getSampleStyleSheet()
    stile_intestazione = ParagraphStyle(
        "Intestazione", parent=stili["Heading1"], fontSize=15, alignment=TA_CENTER, spaceAfter=2,
    )
    stile_sottintestazione = ParagraphStyle(
        "Sottointestazione", parent=stili["Normal"], fontSize=11, alignment=TA_CENTER,
        textColor=colors.HexColor("#444444"), spaceAfter=14,
    )

    buffer = io.BytesIO()
    documento = SimpleDocTemplate(
        buffer, pagesize=A4,
        topMargin=1.0 * cm, bottomMargin=1.0 * cm, leftMargin=1.3 * cm, rightMargin=1.3 * cm,
    )

    story = []
    for indice, gruppo in enumerate(gruppi):
        if indice % 2 == 0:
            if indice > 0:
                story.append(PageBreak())
            story.append(Paragraph(NOME_CIRCOLO, stile_intestazione))
            story.append(Paragraph(
                f"{nome_campionato} — Tappa {numero_tappa} — {giorno_leggibile} {data_leggibile}",
                stile_sottintestazione,
            ))

        membri = (
            db_pv.query(GruppoMembroPV)
            .filter(GruppoMembroPV.gruppo_id == gruppo.id)
            .all()
        )
        cognomi = []
        for membro in membri:
            utente = db_pv.query(UtentePV).filter(UtentePV.id == membro.utente_id).first()
            if utente is not None:
                cognomi.append(utente.cognome)

        story.extend(_tabella_gruppo(gruppo.numero_gruppo, cognomi))
        story.append(Spacer(1, 0.4 * cm))

    documento.build(story)
    return buffer.getvalue()
