## ADDED Requirements

### Requirement: Health check endpoint
The system SHALL expose `GET /health` returning HTTP 200 with a body indicating the service is up, without depending on the vector store, embedding provider, or generation provider being reachable.

#### Scenario: Health check succeeds independently of the RAG pipeline
- **WHEN** a client sends `GET /health`
- **THEN** the response is HTTP 200 with a body indicating a healthy status, even if the vector store or Bedrock is unreachable
