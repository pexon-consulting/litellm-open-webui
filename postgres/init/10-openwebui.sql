-- Runs once, on the first start with an empty volume.
-- LiteLLM uses the database "litellm" (POSTGRES_DB), Open WebUI gets its own database.
CREATE DATABASE openwebui OWNER llm;
\connect openwebui
CREATE EXTENSION IF NOT EXISTS vector;
