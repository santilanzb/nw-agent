CREATE TABLE IF NOT EXISTS intent_vectors (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  intent_class TEXT NOT NULL,
  example_text TEXT NOT NULL,
  language TEXT NOT NULL DEFAULT 'es',
  embedding VECTOR(1536),
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (intent_class, example_text, language)
);

CREATE INDEX IF NOT EXISTS idx_intent_vectors_class
  ON intent_vectors (intent_class);

CREATE INDEX IF NOT EXISTS idx_intent_vectors_embedding_hnsw
  ON intent_vectors USING HNSW (embedding vector_cosine_ops);
