"""
Tabelle del sistema Palavillage — un solo circolo, tornei del mattino
dal lunedì al venerdì. DB completamente separato da quello generico
AnnaPadel (vedi database.py), anche se la "voce" che scrive ai giocatori
è la stessa Anna, con lo stesso numero WhatsApp.

Convenzione per il giorno della settimana, usata in più tabelle:
0=lunedì, 1=martedì, 2=mercoledì, 3=giovedì, 4=venerdì
"""

from sqlalchemy import (
    Column, Integer, BigInteger, String, Boolean, Numeric, Date,
    DateTime, ForeignKey, UniqueConstraint
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.palavillage.database import BasePV

GIORNI_SETTIMANA = ["Lunedì", "Martedì", "Mercoledì", "Giovedì", "Venerdì"]


class UtentePV(BasePV):
    """
    Un giocatore iscritto ai tornei del mattino di Palavillage.

    Se il numero risulta già validato sul sistema generico AnnaPadel,
    la verifica OTP viene saltata (vedi logica applicativa, non qui) e
    nome/cognome possono essere precompilati — ma restano comunque
    campi propri di questa tabella: i due sistemi non condividono righe,
    solo la fiducia sulla validazione del numero.
    """
    __tablename__ = "utenti_pv"

    id = Column(Integer, primary_key=True)
    nome = Column(String(100), nullable=False)
    cognome = Column(String(100), nullable=False)
    whatsapp_numero = Column(String(20), unique=True, nullable=False)
    whatsapp_validato = Column(Boolean, default=False)
    otp_codice = Column(String(6), nullable=True)
    otp_scadenza = Column(DateTime, nullable=True)

    # Stessa logica del sistema generico: immutabile una volta fissato.
    livello_playtomic = Column(Numeric(3, 2), nullable=False)
    livello_dichiarato_scala = Column(String(10))
    livello_dichiarato_originale = Column(String(5))

    lato_preferito = Column(String(15), nullable=False)  # DX, SX, INDIFFERENTE

    # Bitmask a 5 bit: bit 0 = lunedì ... bit 4 = venerdì.
    # Modificabile in ogni momento dal form (a differenza del livello).
    giorni_bitmask = Column(Integer, nullable=False, default=0)

    stato_account = Column(String(20), default="ATTIVO")  # ATTIVO, SOSPESO
    termini_accettati = Column(Boolean, default=False)
    privacy_accettata = Column(Boolean, default=False)
    data_accettazione_termini = Column(DateTime, nullable=True)

    data_creazione = Column(DateTime, server_default=func.now())

    iscrizioni = relationship("IscrizioneTorneo", back_populates="utente")


class Campionato(BasePV):
    """
    Un'edizione del campionato per un giorno della settimana. Quando
    l'admin "chiude" un campionato, si congela la classifica (per
    premiare i vincitori) e se ne apre uno nuovo, sempre per lo stesso
    giorno, che riparte da zero.
    """
    __tablename__ = "campionati"

    id = Column(Integer, primary_key=True)
    giorno_settimana = Column(Integer, nullable=False)  # 0=lun ... 4=ven
    numero_edizione = Column(Integer, nullable=False)  # 1, 2, 3... per quel giorno

    # Nome facoltativo assegnabile dall'admin (es. "Campionato Estivo
    # 2026"). Se non impostato, si usa un nome di riserva generato
    # automaticamente (es. "Campionato Lunedì #1") ovunque serva
    # visualizzarlo (PDF, messaggi, pannello).
    nome = Column(String(100), nullable=True)

    stato = Column(String(15), default="APERTO")  # APERTO, CHIUSO

    data_apertura = Column(DateTime, server_default=func.now())
    data_chiusura = Column(DateTime, nullable=True)
    vincitore_utente_id = Column(Integer, ForeignKey("utenti_pv.id"), nullable=True)

    tornei = relationship("Torneo", back_populates="campionato")

    __table_args__ = (
        UniqueConstraint("giorno_settimana", "numero_edizione", name="uq_campionato_giorno_edizione"),
    )


class Torneo(BasePV):
    """
    Un singolo torneo in una data specifica (es. lunedì 7/10/2026).
    Corrisponde a UNA riga nel pannello admin.
    """
    __tablename__ = "tornei"

    id = Column(Integer, primary_key=True)
    campionato_id = Column(Integer, ForeignKey("campionati.id"), nullable=False)
    data = Column(Date, nullable=False, unique=True)
    giorno_settimana = Column(Integer, nullable=False)  # denormalizzato, comodo per query/filtri

    # Numero progressivo del torneo all'interno del suo campionato (1ª
    # tappa, 2ª tappa...), assegnato una volta sola alla creazione -
    # usato in testa alle tabelle PDF stampate per la segreteria.
    numero_tappa = Column(Integer, nullable=True)

    # PROGRAMMATO, RICHIESTE_INVIATE, SOLLECITO_INVIATO, GRUPPI_FORMATI,
    # PDF_INVIATI, RICHIESTA_PUNTEGGIO_INVIATA, TERMINATO, ANNULLATO
    stato = Column(String(30), default="PROGRAMMATO")

    attivo = Column(Boolean, default=True)  # False = annullato dall'admin (es. Natale)

    data_creazione = Column(DateTime, server_default=func.now())

    campionato = relationship("Campionato", back_populates="tornei")
    iscrizioni = relationship("IscrizioneTorneo", back_populates="torneo")
    gruppi = relationship("GruppoPV", back_populates="torneo")


class IscrizioneTorneo(BasePV):
    """
    La risposta di un utente alla richiesta di iscrizione per UN torneo
    specifico (non la preferenza settimanale generale, quella è in
    UtentePV.giorni_bitmask — questa è la conferma per la singola data).
    """
    __tablename__ = "iscrizioni_torneo"

    id = Column(Integer, primary_key=True)
    torneo_id = Column(Integer, ForeignKey("tornei.id"), nullable=False)
    utente_id = Column(Integer, ForeignKey("utenti_pv.id"), nullable=False)

    stato_risposta = Column(String(15), default="IN_ATTESA")
    # IN_ATTESA, CONFERMATO, RIFIUTATO, NON_RISPOSTO

    # TITOLARE o RISERVA — deciso al momento della formazione gruppi (T-12h)
    ruolo = Column(String(10), nullable=True)

    ordine_conferma = Column(Integer, nullable=True)  # per stabilire chi resta fuori
    data_risposta = Column(DateTime, nullable=True)

    # Codice casuale (non indovinabile) per il link di conferma mandato
    # su WhatsApp - stessa identica idea del sistema generico per la
    # conferma prenotazione circolo (vedi gruppi.codice_conferma_circolo):
    # i bottoni "Quick Reply" di WhatsApp hanno un payload FISSO deciso
    # una volta per tutte in fase di creazione del template su Twilio,
    # quindi non possono contenere l'id dinamico di ogni iscrizione - un
    # link con token invece sì.
    codice_risposta = Column(String(20), nullable=True)

    # Usati SOLO durante la finestra di una proposta di promozione a una
    # riserva (dopo una cancellazione tardiva di un titolare): quale
    # gruppo/lato erediterebbe se accetta, ed entro quando deve rispondere.
    # Tornano a None appena la proposta si risolve (accettata, rifiutata
    # o scaduta).
    promozione_scadenza = Column(DateTime, nullable=True)
    gruppo_proposto_id = Column(Integer, nullable=True)
    lato_proposto = Column(String(2), nullable=True)

    torneo = relationship("Torneo", back_populates="iscrizioni")
    utente = relationship("UtentePV", back_populates="iscrizioni")

    __table_args__ = (
        UniqueConstraint("torneo_id", "utente_id", name="uq_iscrizione_torneo_utente"),
    )


class GruppoPV(BasePV):
    """Un quartetto formato per un torneo specifico."""
    __tablename__ = "gruppi_pv"

    id = Column(Integer, primary_key=True)
    torneo_id = Column(Integer, ForeignKey("tornei.id"), nullable=False)
    numero_gruppo = Column(Integer, nullable=False)  # 1, 2, 3... solo per stampa/ordine

    data_creazione = Column(DateTime, server_default=func.now())

    torneo = relationship("Torneo", back_populates="gruppi")
    membri = relationship("GruppoMembroPV", back_populates="gruppo")


class GruppoMembroPV(BasePV):
    __tablename__ = "gruppi_membri_pv"

    id = Column(Integer, primary_key=True)
    gruppo_id = Column(Integer, ForeignKey("gruppi_pv.id", ondelete="CASCADE"), nullable=False)
    utente_id = Column(Integer, ForeignKey("utenti_pv.id"), nullable=False)

    lato_assegnato = Column(String(2))  # DX o SX

    punteggio_riportato = Column(Integer, nullable=True)  # game fatti in quel torneo
    stato_richiesta_punteggio = Column(String(15), default="IN_ATTESA")
    # IN_ATTESA, RICEVUTO, NON_RISPOSTO
    data_risposta_punteggio = Column(DateTime, nullable=True)

    gruppo = relationship("GruppoPV", back_populates="membri")
    utente = relationship("UtentePV")


class ClassificaVoce(BasePV):
    """
    Riepilogo per campionato+utente, aggiornato a ogni punteggio ricevuto
    (evita di dover risommare tutta la storia ogni volta che si manda la
    classifica aggiornata via WhatsApp).
    """
    __tablename__ = "classifica_voci"

    id = Column(Integer, primary_key=True)
    campionato_id = Column(Integer, ForeignKey("campionati.id"), nullable=False)
    utente_id = Column(Integer, ForeignKey("utenti_pv.id"), nullable=False)

    punti_totali = Column(Integer, default=0)
    partite_giocate = Column(Integer, default=0)

    __table_args__ = (
        UniqueConstraint("campionato_id", "utente_id", name="uq_classifica_campionato_utente"),
    )


class ContestoAttivoWhatsApp(BasePV):
    """
    Usata SOLO per instradare i messaggi WhatsApp in arrivo che sono
    testo libero (non risposte a bottone con payload). Tiene traccia,
    per numero di telefono, se Palavillage sta "aspettando" una risposta
    in questo momento (es. il punteggio del torneo) — se non c'è nessuna
    riga valida (o è scaduta), l'hub lascia che il messaggio scorra verso
    il sistema generico AnnaPadel come già fa oggi.
    """
    __tablename__ = "contesto_attivo_whatsapp"

    whatsapp_numero = Column(String(20), primary_key=True)
    tipo_contesto = Column(String(30), nullable=False)  # es. RICHIESTA_PUNTEGGIO
    riferimento_id = Column(Integer, nullable=True)  # es. torneo_id o gruppo_membro_id

    creato_il = Column(DateTime, server_default=func.now())
    scade_il = Column(DateTime, nullable=False)
