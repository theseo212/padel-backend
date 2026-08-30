"""
Genera il report mensile usato per la fatturazione al circolo: un elenco
di ogni "partita" (gruppo da 4 formato) nel mese, con data, tappa,
campionato, orario e componenti - più il totale in fondo, che è il
numero su cui si basa l'importo da fatturare.

REGOLA DI CONTEGGIO: ogni GruppoPV esistente conta come una partita,
punto - non importa quanti membri ha ADESSO. Il sistema forma SEMPRE i
gruppi con esattamente 4 titolari (mai meno, per costruzione
dell'algoritmo in formazione_gruppi.py); se un gruppo nel database ha
meno di 4 membri, è solo perché uno ha cancellato all'ultimo momento e
non si è trovato un sostituto (la sua riga viene davvero eliminata, non
solo segnata - vedi richiedi_cancellazione_tardiva in motore_torneo.py).
In quel caso il gruppo va comunque fatturato: il costo organizzativo
(messaggi Twilio, formazione, ecc.) è già stato sostenuto, ed erano
davvero 4 giocatori convocati in origine.
"""

import calendar
import io
from datetime import date
from sqlalchemy.orm import Session
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.units import cm
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle

from app.palavillage.models import Torneo, Campionato, GruppoPV, GruppoMembroPV, UtentePV
from app.palavillage.config import NOME_CIRCOLO

_NOMI_MESI = [
    "Gennaio", "Febbraio", "Marzo", "Aprile", "Maggio", "Giugno",
    "Luglio", "Agosto", "Settembre", "Ottobre", "Novembre", "Dicembre",
]


def _nome_campionato_leggibile_locale(campionato: Campionato) -> str:
    # Piccola copia locale per non creare una dipendenza circolare con pdf_torneo.py
    from app.palavillage.pdf_torneo import _nome_campionato_leggibile
    return _nome_campionato_leggibile(campionato)


def genera_pdf_report_fatturazione(db_pv: Session, anno: int, mese: int) -> bytes | None:
    """
    Ritorna i byte del PDF con il report del mese indicato, o None se in
    quel mese non è stato formato nessun gruppo (nulla da fatturare).
    """
    primo_giorno = date(anno, mese, 1)
    ultimo_giorno = date(anno, mese, calendar.monthrange(anno, mese)[1])

    gruppi = (
        db_pv.query(GruppoPV)
        .join(Torneo, GruppoPV.torneo_id == Torneo.id)
        .filter(Torneo.data >= primo_giorno, Torneo.data <= ultimo_giorno)
        .order_by(Torneo.data, GruppoPV.numero_gruppo)
        .all()
    )
    if not gruppi:
        return None

    intestazione = ["Data", "Tappa", "Campionato", "Orario", "Componenti"]
    righe_dati = [intestazione]

    for gruppo in gruppi:
        torneo = db_pv.query(Torneo).filter(Torneo.id == gruppo.torneo_id).first()
        campionato = db_pv.query(Campionato).filter(Campionato.id == torneo.campionato_id).first()
        membri = db_pv.query(GruppoMembroPV).filter(GruppoMembroPV.gruppo_id == gruppo.id).all()

        nomi_componenti = []
        for membro in membri:
            utente = db_pv.query(UtentePV).filter(UtentePV.id == membro.utente_id).first()
            if utente is not None:
                nomi_componenti.append(f"{utente.nome} {utente.cognome}")

        if campionato and campionato.orario_inizio:
            orario = campionato.orario_inizio + (f"-{campionato.orario_fine}" if campionato.orario_fine else "")
        else:
            orario = "—"

        if not nomi_componenti:
            testo_componenti = "(gruppo incompleto, nessun giocatore registrato)"
        elif len(nomi_componenti) < 4:
            testo_componenti = f"{', '.join(nomi_componenti)} (incompleto: {len(nomi_componenti)}/4)"
        else:
            testo_componenti = ", ".join(nomi_componenti)

        righe_dati.append([
            torneo.data.strftime("%d/%m/%Y"),
            str(torneo.numero_tappa) if torneo.numero_tappa else "—",
            _nome_campionato_leggibile_locale(campionato) if campionato else "—",
            orario,
            testo_componenti,
        ])

    totale_partite = len(gruppi)

    tabella = Table(
        righe_dati,
        colWidths=[2.6 * cm, 1.8 * cm, 5.0 * cm, 2.6 * cm, 12.2 * cm],
        repeatRows=1,
    )
    tabella.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#999999")),
        ("BOX", (0, 0), (-1, -1), 1, colors.black),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1B3A63")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 9),
        ("FONTSIZE", (0, 1), (-1, -1), 8.5),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (0, 0), (3, -1), "CENTER"),
        ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 6), ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        *[("BACKGROUND", (0, r), (-1, r), colors.HexColor("#F4F6F8")) for r in range(2, len(righe_dati), 2)],
    ]))

    stili = getSampleStyleSheet()
    stile_titolo = ParagraphStyle("TitoloReport", parent=stili["Heading1"], fontSize=16, alignment=TA_CENTER, spaceAfter=2)
    stile_sottotitolo = ParagraphStyle("SottotitoloReport", parent=stili["Normal"], fontSize=11, alignment=TA_CENTER,
                                        textColor=colors.HexColor("#444444"), spaceAfter=14)
    stile_totale = ParagraphStyle("TotaleReport", fontSize=13, fontName="Helvetica-Bold",
                                    textColor=colors.HexColor("#1B3A63"), alignment=TA_CENTER, spaceBefore=18)

    buffer = io.BytesIO()
    documento = SimpleDocTemplate(
        buffer, pagesize=landscape(A4),
        topMargin=1.2 * cm, bottomMargin=1.2 * cm, leftMargin=1.2 * cm, rightMargin=1.2 * cm,
    )
    story = [
        Paragraph(NOME_CIRCOLO, stile_titolo),
        Paragraph(f"Report mensile partite — {_NOMI_MESI[mese - 1]} {anno}", stile_sottotitolo),
        tabella,
        Paragraph(f"Totale partite organizzate nel mese: {totale_partite}", stile_totale),
    ]
    documento.build(story)
    return buffer.getvalue()
