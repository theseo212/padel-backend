"""
Connessione al database di PadelCity — SEPARATO da quello generico
AnnaPadel (variabili d'ambiente diverse, engine diverso, sessioni diverse).

Il resto del backend (app/database.py, app/models.py) non viene toccato:
questo è un modulo aggiuntivo che vive accanto, non al posto di quello.
"""

import os
from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

load_dotenv()

PADELCITY_DATABASE_URL = os.getenv("PADELCITY_DATABASE_URL")

if not PADELCITY_DATABASE_URL:
    raise ValueError(
        "PADELCITY_DATABASE_URL non trovata. Su Railway serve un secondo "
        "Postgres, collegato a questo stesso servizio backend, con questa "
        "variabile che punta alla sua connection string."
    )

# Railway fornisce di default una stringa "postgresql://...", che
# SQLAlchemy interpreta usando psycopg2 se non specificato altrimenti.
# Questo progetto usa però psycopg (versione 3, vedi requirements.txt),
# quindi normalizziamo lo schema qui invece di dover ricordare di
# modificare a mano il valore incollato su Railway.
if PADELCITY_DATABASE_URL.startswith("postgresql://"):
    PADELCITY_DATABASE_URL = PADELCITY_DATABASE_URL.replace(
        "postgresql://", "postgresql+psycopg://", 1
    )

engine_pc = create_engine(PADELCITY_DATABASE_URL)

SessionLocalPC = sessionmaker(autocommit=False, autoflush=False, bind=engine_pc)

# Base separata: le tabelle di PadelCity non condividono metadata con
# quelle generiche, anche se vivono nello stesso processo Python.
BasePC = declarative_base()


def get_db_pc():
    """
    Stesso pattern di app/database.py:get_db, ma per il DB di PadelCity.
    Usata come seconda dependency FastAPI, accanto a get_db (generico),
    ovunque un endpoint debba parlare con ENTRAMBI i database (es. il
    webhook Twilio unico, che deve poter smistare verso l'uno o l'altro).
    """
    db = SessionLocalPC()
    try:
        yield db
    finally:
        db.close()
