# document-ingestion Specification

## Purpose

The standalone ingestion pipeline that turns source documents (CV, profile PDFs) stored in S3 into chunked, embedded rows in the vector store, with idempotent reindexing by `document_id`.

## Requirements

### Requirement: Standalone ingestion script
The system SHALL provide a standalone script (not exposed as a public API endpoint) that reads a source document from object storage, splits it into chunks, generates an embedding per chunk, and persists the chunks and embeddings to the vector store.

#### Scenario: Ingesting a supported document
- **WHEN** the ingestion script is run against a `.pdf`, `.docx`, or `.pptx` file present in object storage
- **THEN** the script creates one `documents` row (with `filename`, `doc_type`, `version`, `ingested_at`) and one or more `document_chunks` rows, each with `chunk_text`, a 1024-dimension `embedding`, `chunk_index`, and `metadata`, linked via `document_id`

#### Scenario: Unsupported file type is rejected
- **WHEN** the ingestion script is run against a file whose extension is not `.pdf`, `.docx`, or `.pptx`
- **THEN** the script fails with a clear error and persists no `documents` or `document_chunks` rows for that file

### Requirement: Idempotent reindexing by document_id
When re-ingesting a document that was previously ingested, the system SHALL delete all existing `document_chunks` rows for that `document_id` before inserting the newly generated chunks, so that reindexing never leaves duplicate chunks for the same document.

#### Scenario: Re-ingesting an already-ingested document replaces its chunks
- **WHEN** the ingestion script is run for a `document_id` that already has `document_chunks` rows from a prior run
- **THEN** all prior `document_chunks` rows for that `document_id` are deleted before the new chunks are inserted, leaving only the chunks from the latest run

#### Scenario: Ingesting a new document does not affect other documents
- **WHEN** the ingestion script processes a document with a `document_id` that has no prior chunks
- **THEN** existing `document_chunks` rows belonging to other `document_id` values are left unchanged
