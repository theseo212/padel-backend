"""
Questo file gestisce la connessione al database PostgreSQL.
Non contiene le tabelle (quelle sono in models.py), solo la "presa elettrica"
che collega il resto del programma al database.
"""

import os
from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

# Carica le variabili dal file .env (es. DATABASE_URL)
load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    raise ValueError(
        "DATABASE_URL non trovata. Copia .env.example in .env e inserisci "
        "l'indirizzo del tuo database PostgreSQL."
    )

# L'engine è l'oggetto che sa "come parlare" con PostgreSQL
engine = create_engine(DATABASE_URL)

# SessionLocal è una "sessione di lavoro" verso il database:
# ogni volta che il codice deve leggere/scrivere dati, apre una sessione così
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Base è la classe da cui erediteranno tutte le tabelle definite in models.py
Base = declarative_base()


def get_db():
    """
    Funzione di utilità: apre una sessione verso il database, la rende disponibile,
    e la chiude sempre correttamente alla fine (anche in caso di errore).
    Verrà usata più avanti da FastAPI per ogni richiesta che tocca il database.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
