"""
Schemi dei dati scambiati tra il form web di Palavillage e il backend.
Stesso principio del sistema generico (app/schemas.py): FastAPI valida
automaticamente ogni richiesta contro questi modelli.
"""

from typing import Literal
from pydantic import BaseModel, Field, field_validator

from app.palavillage.config import NUMERO_CAMPIONATI


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
    # Non più i giorni della settimana: ogni campionato è ora uno slot
    # libero (1..NUMERO_CAMPIONATI) con il proprio giorno/orario decisi
    # dall'admin - qui arriva l'elenco degli SLOT scelti dal giocatore.
    campionati: list[int] = Field(..., description="Slot dei campionati scelti (1..NUMERO_CAMPIONATI)")

    @field_validator("campionati")
    @classmethod
    def _valida_slot_campionati(cls, valori: list[int]) -> list[int]:
        for slot in valori:
            if not (1 <= slot <= NUMERO_CAMPIONATI):
                raise ValueError(f"Slot campionato non valido: {slot} (deve essere tra 1 e {NUMERO_CAMPIONATI})")
        return valori

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
