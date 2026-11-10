import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from flask_app.utils import embeddings

class FakeModel:
    def embed(self, texts):
        return [[1.0, 0.0] for _ in texts]

class FakeDB:
    def query(self, sql, params=()):
        return [
            {
                "table_name": "skills",
                "record_id": 1,
                "embedded_text": "Python",
                "vector_json": "[1.0, 0.0]"
            },
            {
                "table_name": "skills",
                "record_id": 2,
                "embedded_text": "Java",
                "vector_json": "[0.0, 1.0]"
            },
            {
                "table_name": "experiences",
                "record_id": 3,
                "embedded_text": "Programming",
                "vector_json": "[0.8, 0.6]"
            }
        ]

class EmbeddingTests(unittest.TestCase):

    def test_embed_text_returns_valid_vector(self):
        with patch.object(embeddings, "get_embedder", return_value=FakeModel()):
            self.assertEqual(embeddings.embed_text(" Python "), [1.0, 0.0])

    def test_embed_text_rejects_empty_text(self):
        with self.assertRaises(ValueError):
            embeddings.embed_text("   ")

    def test_cosine_similarity_identical_vectors(self):
        self.assertAlmostEqual(
            embeddings.cosine_similarity([1, 0], [1, 0]), 1.0
        )

    def test_cosine_similarity_rejects_different_dimensions(self):
        with self.assertRaises(ValueError):
            embeddings.cosine_similarity([1, 0], [1, 0, 0])

    def test_cosine_similarity_rejects_zero_vector(self):
        with self.assertRaises(ValueError):
            embeddings.cosine_similarity([0, 0], [1, 0])

    def test_embed_records_preserves_record_information(self):
        record = {
            "table_name": "skills",
            "record_id": 7,
            "text": "Python"
        }
        with patch.object(embeddings, "embed_text", return_value=[1.0, 0.0]):
            result = embeddings.embed_records([record])
        self.assertEqual(result[0]["record_id"], 7)
        self.assertEqual(result[0]["table_name"], "skills")
        self.assertEqual(result[0]["vector"], [1.0, 0.0])

    def test_semantic_search_ranks_highest_score_first(self):
        with patch.object(embeddings, "embed_text", return_value=[1.0, 0.0]):
            results = embeddings.semantic_search(FakeDB(), "Python")
        self.assertEqual(results[0]["record_id"], 1)
        self.assertGreater(results[0]["score"], results[1]["score"])

    def test_semantic_search_respects_limit(self):
        with patch.object(embeddings, "embed_text", return_value=[1.0, 0.0]):
            results = embeddings.semantic_search(FakeDB(), "Python", limit=2)
        self.assertEqual(len(results), 2)

if __name__ == "__main__":
    unittest.main(verbosity=2)
