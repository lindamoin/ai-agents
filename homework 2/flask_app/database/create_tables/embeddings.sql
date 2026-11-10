
CREATE TABLE IF NOT EXISTS embeddings (
    table_name TEXT NOT NULL,
    record_id INTEGER NOT NULL,
    embedded_text TEXT NOT NULL,
    vector_json TEXT NOT NULL,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (table_name, record_id)
);
