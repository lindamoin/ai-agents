import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from flask_app.utils.llm import process_pending_action

class FakeDB:
    def __init__(self):
        self.pending_action = None
        self.deleted_ids = []
        self.inserted = []

    def deleteSkill(self, skill_id):
        self.deleted_ids.append(skill_id)
        return True

    def query(self, sql, params=()):
        return []

    def insertRows(self, table, columns, values):
        self.inserted.append((table, columns, values))

class PendingActionTests(unittest.TestCase):

    def setUp(self):
        self.db = FakeDB()
        self.db.pending_action = {
            "operation": "delete_skill",
            "skill_id": 12,
            "name": "Test Skill"
        }

    def test_no_cancels_without_deleting(self):
        handled, message = process_pending_action(self.db, "no")
        self.assertTrue(handled)
        self.assertEqual(self.db.deleted_ids, [])
        self.assertIsNone(self.db.pending_action)
        self.assertIn("Cancelled", message)

    def test_unclear_keeps_pending(self):
        handled, message = process_pending_action(self.db, "maybe")
        self.assertTrue(handled)
        self.assertIsNotNone(self.db.pending_action)
        self.assertEqual(self.db.deleted_ids, [])

    def test_new_topic_clears_pending(self):
        handled, message = process_pending_action(
            self.db, "What is my education?"
        )
        self.assertFalse(handled)
        self.assertIsNone(self.db.pending_action)
        self.assertEqual(self.db.deleted_ids, [])

    def test_yes_deletes_exact_saved_id(self):
        handled, message = process_pending_action(self.db, "yes")
        self.assertTrue(handled)
        self.assertEqual(self.db.deleted_ids, [12])
        self.assertIsNone(self.db.pending_action)
        self.assertIn("Successfully deleted", message)

    def test_invalid_id_never_deletes(self):
        self.db.pending_action["skill_id"] = "12"
        handled, message = process_pending_action(self.db, "yes")
        self.assertTrue(handled)
        self.assertEqual(self.db.deleted_ids, [])
        self.assertIsNone(self.db.pending_action)
        self.assertIn("Invalid", message)

if __name__ == "__main__":
    unittest.main(verbosity=2)
