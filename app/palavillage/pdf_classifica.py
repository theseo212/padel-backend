"""
Genera il PDF della classifica di un campionato: cognomi a sinistra,
totale punti, una colonna per ogni tappa già giocata (con il punteggio
o "ASSENTE"), poi presenze e media punti/presenza.

Layout orizzontale (landscape) apposta per poter accogliere molte
tappe: più un campionato va avanti, più stretta diventa ogni colonna
tappa e più piccolo il carattere - cresce sempre, non si "spezza" mai
su più pagine (scelta del cliente, che preferisce un unico colpo
d'occhio a costo di un font via via più piccolo).
"""

import io
from sqlalchemy.orm import Session
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.units import cm
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle

from app.palavillage.models import Campionato, Torneo, GruppoPV, GruppoMembroPV, ClassificaVoce, UtentePV
from app.palavillage.config import NOME_CIRCOLO

_NOMI_GIORNI_LEGGIBILI = ["Lunedì", "Martedì", "Mercoledì", "Giovedì", "Venerdì"]

# Dimensioni fisse delle colonne che NON sono una tappa (cognome, totale,
# presenze, percentuale) - usate sia per calcolare quanto spazio resta
# per le colonne tappa, sia per costruire davvero la tabella più sotto,
# così i due calcoli non possono mai andare fuori sincrono.
LARGHEZZA_COGNOME_CM = 3.4
LARGHEZZA_TOTALE_CM = 1.6
LARGHEZZA_PRESENZE_CM = 1.6
LARGHEZZA_PP_CM = 1.6
LARGHEZZA_PAGINA_ORIZZONTALE_CM = 29.7  # A4 orizzontale
MARGINE_PAGINA_CM = 1.0


def _larghezza_utile_per_tappe_cm() -> float:
    """Quanto spazio resta per le colonne tappa, dopo aver tolto margini e colonne fisse."""
    larghezza_pagina_utile = LARGHEZZA_PAGINA_ORIZZONTALE_CM - (2 * MARGINE_PAGINA_CM)
    larghezza_colonne_fisse = LARGHEZZA_COGNOME_CM + LARGHEZZA_TOTALE_CM + LARGHEZZA_PRESENZE_CM + LARGHEZZA_PP_CM
    return larghezza_pagina_utile - larghezza_colonne_fisse


def _nome_campionato_leggibile(campionato: Campionato) -> str:
    if campionato.nome:
        return campionato.nome
    return f"Campionato {_NOMI_GIORNI_LEGGIBILI[campionato.giorno_settimana]} #{campionato.numero_edizione}"


def _dimensione_font_per_tappe(numero_tappe: int) -> tuple[int, float]:
    """
    Ritorna (dimensione_font, larghezza_colonna_tappa_in_cm) in base a
    quante tappe ci sono - più tappe, più piccola ogni colonna e il
    carattere, per restare sempre su un'unica pagina orizzontale.
    """
    larghezza_colonna = _larghezza_utile_per_tappe_cm() / max(numero_tappe, 1)

    if larghezza_colonna >= 1.8:
        return 9, larghezza_colonna
    elif larghezza_colonna >= 1.3:
        return 8, larghezza_colonna
    elif larghezza_colonna >= 1.0:
        return 7, larghezza_colonna
    elif larghezza_colonna >= 0.75:
        return 6, larghezza_colonna
    else:
        return 5, larghezza_colonna


def genera_pdf_classifica(db_pv: Session, campionato_id: int) -> bytes | None:
    """Ritorna i byte del PDF, o None se il campionato non esiste o non ha ancora nessuna tappa giocata."""
    campionato = db_pv.query(Campionato).filter(Campionato.id == campionato_id).first()
    if campionato is None:
        return None

    tornei_con_gruppi = (
        db_pv.query(Torneo)
        .filter(Torneo.campionato_id == campionato_id)
        .join(GruppoPV, GruppoPV.torneo_id == Torneo.id)
        .distinct()
        .order_by(Torneo.data)
        .all()
    )
    if not tornei_con_gruppi:
        return None

    voci_classifica = (
        db_pv.query(ClassificaVoce)
        .filter(ClassificaVoce.campionato_id == campionato_id)
        .order_by(ClassificaVoce.punti_totali.desc())
        .all()
    )
    if not voci_classifica:
        return None

    # Punteggio per (utente, torneo): None = ASSENTE quella tappa
    punteggi_per_utente_torneo: dict[tuple[int, int], int] = {}
    for torneo in tornei_con_gruppi:
        gruppi = db_pv.query(GruppoPV).filter(GruppoPV.torneo_id == torneo.id).all()
        for gruppo in gruppi:
            membri = db_pv.query(GruppoMembroPV).filter(GruppoMembroPV.gruppo_id == gruppo.id).all()
            for membro in membri:
                if membro.punteggio_riportato is not None:
                    punteggi_per_utente_torneo[(membro.utente_id, torneo.id)] = membro.punteggio_riportato

    numero_tappe = len(tornei_con_gruppi)
    dimensione_font, larghezza_colonna_tappa = _dimensione_font_per_tappe(numero_tappe)

    intestazione = ["GIOCATORI", "Tot Pti"]
    for indice, torneo in enumerate(tornei_con_gruppi, start=1):
        intestazione.append(f"{indice}G {torneo.data.strftime('%d/%m/%y')}")
    intestazione += ["Presenze", "% P/P"]

    righe_dati = [intestazione]
    for voce in voci_classifica:
        utente = db_pv.query(UtentePV).filter(UtentePV.id == voce.utente_id).first()
        if utente is None:
            continue
        riga = [utente.cognome.upper(), str(voce.punti_totali)]
        for torneo in tornei_con_gruppi:
            punteggio = punteggi_per_utente_torneo.get((utente.id, torneo.id))
            riga.append(str(punteggio) if punteggio is not None else "ASSENTE")
        media = round(voce.punti_totali / voce.partite_giocate, 2) if voce.partite_giocate else 0
        riga += [str(voce.partite_giocate), f"{media:.2f}"]
        righe_dati.append(riga)

    larghezze_colonne = (
        [LARGHEZZA_COGNOME_CM * cm, LARGHEZZA_TOTALE_CM * cm]
        + [larghezza_colonna_tappa * cm] * numero_tappe
        + [LARGHEZZA_PRESENZE_CM * cm, LARGHEZZA_PP_CM * cm]
    )

    tabella = Table(righe_dati, colWidths=larghezze_colonne, repeatRows=1)
    stile_tabella = [
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#999999")),
        ("BOX", (0, 0), (-1, -1), 1, colors.black),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1B3A63")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), max(dimensione_font - 1, 5)),
        ("FONTNAME", (0, 1), (0, -1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 1), (-1, -1), dimensione_font),
        ("ALIGN", (1, 0), (-1, -1), "CENTER"),
        ("ALIGN", (0, 0), (0, -1), "LEFT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (0, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        # Righe alternate leggermente ombreggiate, per seguire la riga
        # più facilmente su una tabella così larga.
        *[("BACKGROUND", (0, r), (-1, r), colors.HexColor("#F4F6F8")) for r in range(2, len(righe_dati), 2)],
        # Colonna Totale sempre in evidenza, come nelle tabelle gruppi.
        ("BACKGROUND", (1, 1), (1, -1), colors.HexColor("#FFF3D6")),
        ("FONTNAME", (1, 1), (1, -1), "Helvetica-Bold"),
    ]
    tabella.setStyle(TableStyle(stile_tabella))

    stili = getSampleStyleSheet()
    stile_titolo = ParagraphStyle("TitoloClassifica", parent=stili["Heading1"], fontSize=16, alignment=TA_CENTER, spaceAfter=2)
    stile_sottotitolo = ParagraphStyle("SottotitoloClassifica", parent=stili["Normal"], fontSize=10, alignment=TA_CENTER,
                                        textColor=colors.HexColor("#444444"), spaceAfter=10)

    buffer = io.BytesIO()
    documento = SimpleDocTemplate(
        buffer, pagesize=landscape(A4),
        topMargin=1.0 * cm, bottomMargin=1.0 * cm, leftMargin=1.0 * cm, rightMargin=1.0 * cm,
    )
    story = [
        Paragraph(NOME_CIRCOLO, stile_titolo),
        Paragraph(f"Classifica — {_nome_campionato_leggibile(campionato)}", stile_sottotitolo),
        tabella,
    ]
    documento.build(story)
    return buffer.getvalue()
