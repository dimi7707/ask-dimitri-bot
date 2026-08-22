import uuid

from app.models.documents import Document, DocumentChunk


def test_document_has_expected_fields_and_defaults():
    document = Document(filename="cv.pdf", doc_type="cv", version="v1")

    assert isinstance(document.id, uuid.UUID)
    assert document.filename == "cv.pdf"
    assert document.doc_type == "cv"
    assert document.version == "v1"
    assert document.ingested_at is not None


def test_document_chunk_has_expected_fields_and_defaults():
    document_id = uuid.uuid4()

    chunk = DocumentChunk(
        document_id=document_id,
        chunk_text="Dimitri trabaja con Python",
        embedding=[0.1] * 1024,
        chunk_index=0,
    )

    assert isinstance(chunk.id, uuid.UUID)
    assert chunk.document_id == document_id
    assert chunk.chunk_text == "Dimitri trabaja con Python"
    assert len(chunk.embedding) == 1024
    assert chunk.chunk_index == 0
    assert chunk.metadata_ == {}
    assert chunk.created_at is not None
