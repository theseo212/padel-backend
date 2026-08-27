"""
Script da eseguire UNA VOLTA per creare le tabelle nel database di
Palavillage (SEPARATO da quello generico — vedi init_db.py per quello).

Per eseguirlo (da terminale, nella cartella del progetto):
    python init_db_palavillage.py

Richiede PALAVILLAGE_DATABASE_URL impostata (vedi app/palavillage/database.py).
"""

from app.palavillage.database import engine_pv, BasePV
from app.palavillage import models as models_pv  # noqa: F401 (serve per registrare le tabelle su BasePV)

print("Creo le tabelle nel database Palavillage...")
BasePV.metadata.create_all(bind=engine_pv)
print("Tabelle create con successo.")
