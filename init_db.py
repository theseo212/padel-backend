"""
Script da eseguire UNA VOLA per creare le tabelle nel database
e inserire i valori di partenza della conversione Wansport -> Playtomic.

Per eseguirlo (da terminale, nella cartella del progetto):
    python init_db.py
"""

from app.database import engine, SessionLocal, Base
from app import models

# Crea tutte le tabelle definite in models.py, se non esistono già
print("Creo le tabelle nel database...")
Base.metadata.create_all(bind=engine)
print("Tabelle create con successo.")

# Inserisce i valori di conversione Wansport -> Playtomic, solo se la tabella è vuota
db = SessionLocal()
try:
    tabella_vuota = db.query(models.ConversioneWansportPlaytomic).count() == 0

    if tabella_vuota:
        print("Inserisco i valori di conversione Wansport -> Playtomic...")
        conversioni = [
            ("C4", 1.00), ("C3", 1.50), ("C2", 2.00), ("C1", 2.50),
            ("B4", 3.00), ("B3", 3.50), ("B2", 4.00), ("B1", 4.50),
            ("A4", 5.00), ("A3", 5.50), ("A2", 6.00), ("A1", 6.50),
        ]
        for wansport, playtomic in conversioni:
            db.add(models.ConversioneWansportPlaytomic(
                livello_wansport=wansport,
                livello_playtomic=playtomic
            ))
        db.commit()
        print("Valori di conversione inseriti.")
    else:
        print("La tabella di conversione contiene già dei dati, non la tocco.")
finally:
    db.close()

print("\nFatto! Il database è pronto.")
