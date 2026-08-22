import uuid
from datetime import datetime, timezone

from pgvector.sqlalchemy import Vector
from sqlalchemy import Column
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel

EMBEDDING_DIMENSIONS = 1024


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Document(SQLModel, table=True):
    __tablename__ = "documents"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    filename: str
    doc_type: str
    version: str
    ingested_at: datetime = Field(default_factory=_utcnow)


class DocumentChunk(SQLModel, table=True):
    __tablename__ = "document_chunks"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    document_id: uuid.UUID = Field(foreign_key="documents.id")
    chunk_text: str
    embedding: list[float] = Field(sa_column=Column(Vector(EMBEDDING_DIMENSIONS)))
    chunk_index: int
    # Mapped to the `metadata` DB column; the `metadata` attribute name itself is
    # reserved by SQLAlchemy's declarative base for the schema MetaData object.
    metadata_: dict = Field(default_factory=dict, sa_column=Column("metadata", JSONB))
    created_at: datetime = Field(default_factory=_utcnow)
