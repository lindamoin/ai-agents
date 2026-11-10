import json
import os
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from flask_app.utils.database import database

class EmbeddingPersistenceTests(unittest.TestCase):

    def test_embeddings_persist_after_database_reopen(self):
        with tempfile.TemporaryDirectory() as folder:
            db_path = os.path.join(folder, "test_resume.db")

            connection = sqlite3.connect(db_path)
            connection.executescript("""
                CREATE TABLE institutions (
                    inst_id INTEGER PRIMARY KEY,
                    name TEXT, type TEXT, department TEXT,
                    city TEXT, state TEXT
                );
                CREATE TABLE positions (
                    position_id INTEGER PRIMARY KEY,
                    inst_id INTEGER, title TEXT,
                    responsibilities TEXT, start_date TEXT, end_date TEXT
                );
                CREATE TABLE experiences (
                    experience_id INTEGER PRIMARY KEY,
                    position_id INTEGER, name TEXT, description TEXT
                );
                CREATE TABLE skills (
                    skill_id INTEGER PRIMARY KEY,
                    name TEXT, skill_level INTEGER, experience_id INTEGER
                );
                CREATE TABLE embeddings (
                    table_name TEXT NOT NULL,
                    record_id INTEGER NOT NULL,
                    embedded_text TEXT NOT NULL,
                    vector_json TEXT NOT NULL,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (table_name, record_id)
                );
                INSERT INTO institutions
                VALUES (1, 'Test University', 'University',
                        'Computer Science', 'Test City', 'Test State');
            """)
            connection.commit()
            connection.close()

            first_db = database()
            first_db.db_path = db_path

            with patch(
                "flask_app.utils.embeddings.embed_text",
                return_value=[0.1, 0.2, 0.3]
            ) as mocked_embed:
                first_db.sync_embeddings()
                self.assertEqual(mocked_embed.call_count, 1)

            reopened_db = database()
            reopened_db.db_path = db_path

            saved = reopened_db.query(
                "SELECT * FROM embeddings WHERE table_name = ? AND record_id = ?",
                ("institutions", 1)
            )

            self.assertEqual(len(saved), 1)
            self.assertEqual(
                json.loads(saved[0]["vector_json"]),
                [0.1, 0.2, 0.3]
            )

            with patch(
                "flask_app.utils.embeddings.embed_text"
            ) as mocked_embed:
                reopened_db.sync_embeddings()
                mocked_embed.assert_not_called()

if __name__ == "__main__":
    unittest.main()
