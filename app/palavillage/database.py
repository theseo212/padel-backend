"""
Connessione al database di Palavillage — SEPARATO da quello generico
AnnaPadel (variabili d'ambiente diverse, engine diverso, sessioni diverse).

Il resto del backend (app/database.py, app/models.py) non viene toccato:
questo è un modulo aggiuntivo che vive accanto, non al posto di quello.
"""

import os
from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

load_dotenv()

PALAVILLAGE_DATABASE_URL = os.getenv("PALAVILLAGE_DATABASE_URL")

if not PALAVILLAGE_DATABASE_URL:
    raise ValueError(
        "PALAVILLAGE_DATABASE_URL non trovata. Su Railway serve un secondo "
        "Postgres, collegato a questo stesso servizio backend, con questa "
        "variabile che punta alla sua connection string."
    )

# Railway fornisce di default una stringa "postgresql://...", che
# SQLAlchemy interpreta usando psycopg2 se non specificato altrimenti.
# Questo progetto usa però psycopg (versione 3, vedi requirements.txt),
# quindi normalizziamo lo schema qui invece di dover ricordare di
# modificare a mano il valore incollato su Railway.
if PALAVILLAGE_DATABASE_URL.startswith("postgresql://"):
    PALAVILLAGE_DATABASE_URL = PALAVILLAGE_DATABASE_URL.replace(
        "postgresql://", "postgresql+psycopg://", 1
    )

engine_pv = create_engine(PALAVILLAGE_DATABASE_URL)

SessionLocalPV = sessionmaker(autocommit=False, autoflush=False, bind=engine_pv)

# Base separata: le tabelle di Palavillage non condividono metadata con
# quelle generiche, anche se vivono nello stesso processo Python.
BasePV = declarative_base()


def get_db_pv():
    """
    Stesso pattern di app/database.py:get_db, ma per il DB di Palavillage.
    Usata come seconda dependency FastAPI, accanto a get_db (generico),
    ovunque un endpoint debba parlare con ENTRAMBI i database (es. il
    webhook Twilio unico, che deve poter smistare verso l'uno o l'altro).
    """
    db = SessionLocalPV()
    try:
        yield db
    finally:
        db.close()
