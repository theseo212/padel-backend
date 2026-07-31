"""
Questo file gestisce la connessione al database PostgreSQL.
Non contiene le tabelle (quelle sono in models.py), solo la "presa elettrica"
che collega il resto del programma al database.
"""

import os
from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    raise ValueError(
        "DATABASE_URL non trovata. Copia .env.example in .env e inserisci "
        "l'indirizzo del tuo database PostgreSQL."
    )

# Adatta l'indirizzo per usare il driver psycopg v3 (più compatibile con
# Python 3.13 e ambienti containerizzati minimali rispetto al vecchio
# psycopg2-binary, che su alcune immagini non trova la libreria di sistema
# libpq). Gestisce sia il prefisso "postgres://" (usato da alcuni provider,
# es. storico Heroku) sia quello standard "postgresql://".
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)
if DATABASE_URL.startswith("postgresql://") and "+psycopg" not in DATABASE_URL:
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+psycopg://", 1)

engine = create_engine(DATABASE_URL)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    """
    Funzione di utilità: apre una sessione verso il database, la rende disponibile,
    e la chiude sempre correttamente alla fine (anche in caso di errore).
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
