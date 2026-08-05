"""
Questo file contiene le 10 tabelle del database, tradotte in classi Python.
Ogni classe = una tabella. Ogni attributo della classe = una colonna.

Questo modo di lavorare si chiama ORM (Object-Relational Mapping):
invece di scrivere SQL a mano, scriviamo classi Python e la libreria
SQLAlchemy si occupa di tradurle in tabelle reali sul database.
"""

from sqlalchemy import (
    Column, Integer, BigInteger, String, Boolean, Numeric, Date, Time,
    DateTime, ForeignKey, UniqueConstraint
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.database import Base


class Utente(Base):
    __tablename__ = "utenti"

    id = Column(Integer, primary_key=True)
    nome = Column(String(100), nullable=False)
    cognome = Column(String(100), nullable=False)
    whatsapp_numero = Column(String(20), unique=True, nullable=False)
    whatsapp_validato = Column(Boolean, default=False)
    otp_codice = Column(String(6), nullable=True)         # codice temporaneo in attesa di validazione
    otp_scadenza = Column(DateTime, nullable=True)         # dopo quando il codice non è più valido

    livello_playtomic = Column(Numeric(3, 2), nullable=False)
    livello_dichiarato_scala = Column(String(10))       # 'PLAYTOMIC' o 'WANSPORT'
    livello_dichiarato_originale = Column(String(5))     # es. 'B2', NULL se già Playtomic

    lato_preferito = Column(String(15), nullable=False)  # DX, SX, INDIFFERENTE

    stato_account = Column(String(20), default="ATTIVO")  # ATTIVO, SOSPESO
    sospeso_fino_a = Column(DateTime, nullable=True)
    mancate_conferme_consecutive = Column(Integer, default=0)
    ultimo_numero_partite_valutato = Column(Integer, default=0)
    termini_accettati = Column(Boolean, default=False)
    privacy_accettata = Column(Boolean, default=False)
    data_accettazione_termini = Column(DateTime, nullable=True)

    data_creazione = Column(DateTime, server_default=func.now())

    # relazioni: permettono di navigare facilmente da un utente
    # alle sue richieste, senza scrivere query manuali ogni volta
    richieste = relationship("Richiesta", back_populates="utente")


class Circolo(Base):
    __tablename__ = "circoli"

    id = Column(Integer, primary_key=True)
    nome = Column(String(150), nullable=False)
    indirizzo = Column(String(255))
    provincia = Column(String(10), nullable=True)  # es. "TO", "VC" - per filtrare i circoli su vasta scala
    telefono = Column(String(30))
    orario_apertura = Column(Time)
    orario_chiusura = Column(Time)
    numero_campi = Column(Integer, nullable=True)
    dotazioni = Column(String(500), nullable=True)   # es. "spogliatoi, bar, parcheggio, illuminazione"
    note_staff = Column(String(500), nullable=True)   # es. referente, orari contatto, note interne
    attivo = Column(Boolean, default=True)


class Richiesta(Base):
    __tablename__ = "richieste"

    id = Column(Integer, primary_key=True)
    utente_id = Column(Integer, ForeignKey("utenti.id"), nullable=False)

    tipo_partita = Column(String(15), nullable=False)  # MASCHILE, FEMMINILE, MISTA
    giorno = Column(Date, nullable=False)
    disponibilita_bitmask = Column(BigInteger, nullable=False)  # 32 bit, slot da 30 min

    stato = Column(String(20), default="IN_RICERCA")
    # IN_RICERCA, LOCKED, CONFERMATA, SCADUTA, ANNULLATA

    data_creazione = Column(DateTime, server_default=func.now())
    tolleranza_corrente = Column(Numeric(3, 2), default=0.5)
    promemoria_mancata_partita_inviato = Column(Boolean, default=False)

    utente = relationship("Utente", back_populates="richieste")
    circoli = relationship("Circolo", secondary="richieste_circoli")


class RichiestaCircolo(Base):
    __tablename__ = "richieste_circoli"

    richiesta_id = Column(Integer, ForeignKey("richieste.id", ondelete="CASCADE"), primary_key=True)
    circolo_id = Column(Integer, ForeignKey("circoli.id"), primary_key=True)


class Gruppo(Base):
    __tablename__ = "gruppi"

    id = Column(Integer, primary_key=True)
    circolo_id = Column(Integer, ForeignKey("circoli.id"))
    giorno = Column(Date, nullable=False)
    slot_inizio = Column(Integer, nullable=False)    # indice slot bitmask (0-31)
    durata_slot = Column(Integer, nullable=False)     # es. 3 = 1h30

    stato = Column(String(20), default="PROPOSTO")
    # PROPOSTO, CONFERMATO, ANNULLATO, PRENOTATO, GIOCATO

    data_proposta = Column(DateTime, server_default=func.now())
    scadenza_conferma = Column(DateTime, nullable=False)

    membri = relationship("GruppoMembro", back_populates="gruppo")


class GruppoMembro(Base):
    __tablename__ = "gruppi_membri"

    id = Column(Integer, primary_key=True)
    gruppo_id = Column(Integer, ForeignKey("gruppi.id", ondelete="CASCADE"), nullable=False)
    utente_id = Column(Integer, ForeignKey("utenti.id"), nullable=False)
    richiesta_id = Column(Integer, ForeignKey("richieste.id"), nullable=False)

    lato_assegnato = Column(String(2))  # DX o SX

    stato_conferma = Column(String(15), default="IN_ATTESA")
    # IN_ATTESA, CONFERMATO, RIFIUTATO, NON_RISPOSTO

    data_risposta = Column(DateTime, nullable=True)

    gruppo = relationship("Gruppo", back_populates="membri")
    utente = relationship("Utente")


class Partita(Base):
    __tablename__ = "partite"

    id = Column(Integer, primary_key=True)
    gruppo_id = Column(Integer, ForeignKey("gruppi.id"))
    circolo_id = Column(Integer, ForeignKey("circoli.id"))
    giorno = Column(Date, nullable=False)
    ora_inizio = Column(Time, nullable=False)

    stato = Column(String(20), default="PRENOTATA")  # PRENOTATA, GIOCATA, ANNULLATA
    data_prenotazione = Column(DateTime, server_default=func.now())

    data_richiesta_feedback = Column(DateTime, nullable=True)
    promemoria_feedback_inviato = Column(Boolean, default=False)
    finestra_feedback_chiusa = Column(Boolean, default=False)


class FeedbackLivello(Base):
    __tablename__ = "feedback_livello"

    id = Column(Integer, primary_key=True)
    partita_id = Column(Integer, ForeignKey("partite.id"), nullable=False)
    votante_id = Column(Integer, ForeignKey("utenti.id"), nullable=False)
    votato_id = Column(Integer, ForeignKey("utenti.id"), nullable=False)

    voto = Column(String(15), nullable=False)  # PIU_ALTO, GIUSTO, PIU_BASSO
    data_voto = Column(DateTime, server_default=func.now())


class StoricoLivello(Base):
    __tablename__ = "storico_livello"

    id = Column(Integer, primary_key=True)
    utente_id = Column(Integer, ForeignKey("utenti.id"), nullable=False)

    livello_precedente = Column(Numeric(3, 2))
    livello_nuovo = Column(Numeric(3, 2))
    motivo = Column(String(255))

    data_aggiornamento = Column(DateTime, server_default=func.now())


class ConversioneWansportPlaytomic(Base):
    __tablename__ = "conversione_wansport_playtomic"

    id = Column(Integer, primary_key=True)
    livello_wansport = Column(String(5), unique=True, nullable=False)
    livello_playtomic = Column(Numeric(3, 2), nullable=False)


class MessaggioContatto(Base):
    """
    Messaggi inviati dal form Contatti del sito. Vengono sempre salvati
    qui (backup permanente, mai perso), oltre al tentativo di invio email
    reale - così anche se l'email dovesse fallire per qualche motivo, il
    messaggio resta comunque consultabile dal pannello operatore.
    """
    __tablename__ = "messaggi_contatto"

    id = Column(Integer, primary_key=True)
    nome = Column(String(150), nullable=False)
    email_mittente = Column(String(255), nullable=False)
    messaggio = Column(String(2000), nullable=False)
    email_inviata_con_successo = Column(Boolean, default=False)
    data_invio = Column(DateTime, server_default=func.now())
