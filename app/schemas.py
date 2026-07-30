"""
Questi "schemi" definiscono esattamente che forma devono avere i dati
che il form web invia al server, e che il server restituisce.
FastAPI li usa per validare automaticamente ogni richiesta: se manca
un campo obbligatorio o è del tipo sbagliato, il server risponde con
un errore chiaro, senza che dobbiamo scrivere controlli manuali.
"""

from datetime import date
from typing import Literal
from pydantic import BaseModel, Field


class RichiestaCreate(BaseModel):
    # dati dell'utente (usati solo se è il suo primo inserimento in assoluto)
    nome: str
    cognome: str
    whatsapp_numero: str = Field(..., description="Formato internazionale, es. +393331234567")
    livello_scala: Literal["PLAYTOMIC", "WANSPORT"]
    livello_valore: str = Field(..., description="es. '3.5' oppure 'B2'")
    lato_preferito: Literal["DX", "SX", "INDIFFERENTE"]

    # dati della richiesta specifica (sempre richiesti, ad ogni richiesta)
    tipo_partita: Literal["MASCHILE", "FEMMINILE", "MISTA"]
    giorno: date
    fasce_orarie: list[tuple[str, str]] = Field(
        ..., description="Lista di fasce, es. [['18:00','21:00']]"
    )
    circoli_ids: list[int] = Field(..., min_length=1)


class RichiestaResponse(BaseModel):
    richiesta_id: int
    utente_nuovo: bool
    richiede_validazione_otp: bool
    messaggio: str


class ValidaOtpRequest(BaseModel):
    whatsapp_numero: str
    codice_otp: str


class RispostaGruppo(BaseModel):
    utente_id: int
    risposta: Literal["CONFERMA", "RIFIUTO"]


class FeedbackCreate(BaseModel):
    votante_id: int
    votato_id: int
    voto: Literal["PIU_ALTO", "GIUSTO", "PIU_BASSO"]


class CircoloCreate(BaseModel):
    nome: str
    indirizzo: str | None = None
    telefono: str | None = None
    orario_apertura: str | None = Field(None, description="es. '08:00'")
    orario_chiusura: str | None = Field(None, description="es. '23:00'")
    numero_campi: int | None = None
    dotazioni: str | None = Field(None, description="es. 'spogliatoi, bar, parcheggio'")
    note_staff: str | None = None


class CircoloUpdate(BaseModel):
    nome: str | None = None
    indirizzo: str | None = None
    telefono: str | None = None
    orario_apertura: str | None = None
    orario_chiusura: str | None = None
    numero_campi: int | None = None
    dotazioni: str | None = None
    note_staff: str | None = None
    attivo: bool | None = None
