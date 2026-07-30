"""
Gestisce la conversione del livello dichiarato dall'utente.
Se l'utente ha inserito un livello Playtomic, lo usa direttamente.
Se ha inserito un livello Wansport, lo converte consultando la tabella
"conversione_wansport_playtomic" nel database (punto 10 dello schema).
"""

from sqlalchemy.orm import Session
from app import models


def ottieni_livello_playtomic(db: Session, scala: str, valore: str) -> float:
    """
    scala: "PLAYTOMIC" oppure "WANSPORT"
    valore: es. "3.5" se scala Playtomic, oppure "B2" se scala Wansport

    Restituisce sempre un numero in scala Playtomic, pronto per essere
    salvato in utenti.livello_playtomic
    """
    if scala == "PLAYTOMIC":
        return float(valore)

    if scala == "WANSPORT":
        riga = db.query(models.ConversioneWansportPlaytomic).filter(
            models.ConversioneWansportPlaytomic.livello_wansport == valore.upper()
        ).first()

        if riga is None:
            raise ValueError(
                f"Livello Wansport '{valore}' non riconosciuto. "
                f"Valori validi: C4, C3, C2, C1, B4, B3, B2, B1, A4, A3, A2, A1"
            )
        return float(riga.livello_playtomic)

    raise ValueError(f"Scala '{scala}' non valida. Deve essere 'PLAYTOMIC' o 'WANSPORT'")
