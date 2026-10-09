"""
Connessione al database di Brangi — SEPARATO da quello generico
AnnaPadel (variabili d'ambiente diverse, engine diverso, sessioni diverse).

Il resto del backend (app/database.py, app/models.py) non viene toccato:
questo è un modulo aggiuntivo che vive accanto, non al posto di quello.
"""

import os
from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

load_dotenv()

BRANGI_DATABASE_URL = os.getenv("BRANGI_DATABASE_URL")

if not BRANGI_DATABASE_URL:
    raise ValueError(
        "BRANGI_DATABASE_URL non trovata. Su Railway serve un secondo "
        "Postgres, collegato a questo stesso servizio backend, con questa "
        "variabile che punta alla sua connection string."
    )

# Railway fornisce di default una stringa "postgresql://...", che
# SQLAlchemy interpreta usando psycopg2 se non specificato altrimenti.
# Questo progetto usa però psycopg (versione 3, vedi requirements.txt),
# quindi normalizziamo lo schema qui invece di dover ricordare di
# modificare a mano il valore incollato su Railway.
if BRANGI_DATABASE_URL.startswith("postgresql://"):
    BRANGI_DATABASE_URL = BRANGI_DATABASE_URL.replace(
        "postgresql://", "postgresql+psycopg://", 1
    )

engine_brg = create_engine(BRANGI_DATABASE_URL)

SessionLocalBRG = sessionmaker(autocommit=False, autoflush=False, bind=engine_brg)

# Base separata: le tabelle di Brangi non condividono metadata con
# quelle generiche, anche se vivono nello stesso processo Python.
BaseBRG = declarative_base()


def get_db_brg():
    """
    Stesso pattern di app/database.py:get_db, ma per il DB di Brangi.
    Usata come seconda dependency FastAPI, accanto a get_db (generico),
    ovunque un endpoint debba parlare con ENTRAMBI i database (es. il
    webhook Twilio unico, che deve poter smistare verso l'uno o l'altro).
    """
    db = SessionLocalBRG()
    try:
        yield db
    finally:
        db.close()
