"""
Schemi dei dati scambiati tra il form web di Palavillage e il backend.
Stesso principio del sistema generico (app/schemas.py): FastAPI valida
automaticamente ogni richiesta contro questi modelli.
"""

from typing import Literal
from pydantic import BaseModel, Field

GIORNO_VALIDO = Literal["LUN", "MAR", "MER", "GIO", "VEN"]


class IscrizionePVCreate(BaseModel):
    # dati anagrafici (usati solo se è la prima iscrizione in assoluto
    # su Palavillage - se il numero è già presente, questi campi vengono
    # ignorati per nome/cognome/livello, esattamente come nel generico)
    nome: str
    cognome: str
    whatsapp_numero: str = Field(..., description="Formato internazionale, es. +393331234567")
    livello_scala: Literal["PLAYTOMIC", "WANSPORT"]
    livello_valore: str = Field(..., description="es. '3.5' oppure 'B2'")

    # sempre modificabili, ad ogni invio
    lato_preferito: Literal["DX", "SX", "INDIFFERENTE"]
    giorni: list[GIORNO_VALIDO] = Field(..., description="Mattine in cui si vuole giocare")

    # richiesti solo alla primissima iscrizione (vedi main.py)
    accetta_termini: bool = False
    accetta_privacy: bool = False


class IscrizionePVResponse(BaseModel):
    utente_nuovo: bool
    richiede_validazione_otp: bool
    messaggio: str


class ValidaOtpPVRequest(BaseModel):
    whatsapp_numero: str
    codice_otp: str
