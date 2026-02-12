-- Setup script for pgvector extension (BACKUP/REFERENCE ONLY)
-- 
-- IMPORTANT: This is now OPTIONAL - pgvector extension is automatically installed
-- when you start the application (python main.py).
--
-- Only use this file if automatic setup fails due to permissions.
--
-- IMPORTANT: Embeddings are stored in the SAME database - no separate database needed!
-- pgvector is a PostgreSQL extension, so vector columns are added to existing tables.
-- All your data (users, chats, embeddings) stays in one database.

-- 1. Enable pgvector extension (only needed if automatic setup fails)
CREATE EXTENSION IF NOT EXISTS vector;

-- 2. Verify extension is installed
SELECT * FROM pg_extension WHERE extname = 'vector';

-- 3. Create vector index for faster similarity search
-- This should be run after you have some data in the embeddings table
-- The index improves search performance significantly

-- First, check if you have data:
-- SELECT COUNT(*) FROM embeddings WHERE embedding_vector IS NOT NULL;

-- Then create the index (adjust lists parameter based on your data size):
-- CREATE INDEX idx_embedding_vector ON embeddings 
-- USING ivfflat (embedding_vector vector_cosine_ops) 
-- WITH (lists = 100);

-- For smaller datasets (< 10K embeddings), use:
-- CREATE INDEX idx_embedding_vector ON embeddings 
-- USING ivfflat (embedding_vector vector_cosine_ops) 
-- WITH (lists = 10);

-- Note: ivfflat indexes are approximate but much faster than exact search
-- For exact search (slower but more accurate), use:
-- CREATE INDEX idx_embedding_vector_exact ON embeddings 
-- USING hnsw (embedding_vector vector_cosine_ops);

