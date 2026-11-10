import unittest
from unittest.mock import Mock, patch
import json

from flask_app.utils import llm

class OrchestratorTests(unittest.TestCase):

    def setUp(self):
        self.db = Mock()
        self.db.pending_action = None

    @patch("flask_app.utils.llm.semantic_search")
    @patch("flask_app.utils.llm.send_message")
    def test_semantic_question_uses_semantic_search(
        self, mock_send, mock_search
    ):
        mock_search.return_value = [
            {
                "table_name": "skills",
                "record_id": 1,
                "score": 0.85,
                "name": "Machine Learning"
            }
        ]
        mock_send.return_value = "Machine Learning is relevant."

        result = llm.run_orchestrator_plan(
            self.db, "What skills are related to AI?"
        )

        mock_search.assert_called_once()
        mock_send.assert_called_once()
        self.assertEqual(result, "Machine Learning is relevant.")
        self.assertIn("Machine Learning", mock_send.call_args[0][0])

    @patch("flask_app.utils.llm.semantic_search")
    def test_semantic_search_returns_no_records(
        self, mock_search
    ):
        mock_search.return_value = []

        result = llm.run_orchestrator_plan(
            self.db, "Find skills related to AI"
        )

        self.assertEqual(result, "No matching records were found.")

    @patch("flask_app.utils.llm.semantic_search")
    @patch("flask_app.utils.llm.send_message")
    def test_low_similarity_is_rejected(
        self, mock_send, mock_search
    ):
        mock_search.return_value = [
            {
                "table_name": "institutions",
                "record_id": 1,
                "score": 0.30,
                "name": "Example University"
            }
        ]

        result = llm.run_orchestrator_plan(
            self.db, "Find an institution similar to MSU"
        )

        self.assertIn("No sufficiently relevant records", result)
        mock_send.assert_not_called()

    @patch("flask_app.utils.llm.semantic_search")
    @patch("flask_app.utils.llm.send_message")
    @patch("flask_app.utils.llm.handle_ai_chat_request")
    def test_exact_question_uses_orchestrator_not_semantic_search(
        self, mock_handle, mock_send, mock_search
    ):
        mock_send.side_effect = [
            json.dumps([
                {
                    "role": "Database Read Expert",
                    "message": "Count all skills"
                }
            ]),
            "There are 2 skills."
        ]
        mock_handle.return_value = "2"

        result = llm.run_orchestrator_plan(
            self.db, "How many skills do I have?"
        )

        mock_search.assert_not_called()
        self.assertEqual(result, "There are 2 skills.")

    @patch("flask_app.utils.llm.send_message")
    @patch("flask_app.utils.llm.handle_ai_chat_request")
    def test_dependent_steps_receive_previous_result(
        self, mock_handle, mock_send
    ):
        mock_send.side_effect = [
            json.dumps([
                {
                    "role": "Database Read Expert",
                    "message": "Find my education institution"
                },
                {
                    "role": "Database Read Expert",
                    "message": "Find its department"
                }
            ]),
            "Your department is Computer Science."
        ]

        mock_handle.side_effect = [
            "Example University",
            "Computer Science"
        ]

        result = llm.run_orchestrator_plan(
            self.db,
            "Find my education institution and then its department"
        )

        self.assertEqual(mock_handle.call_count, 2)

        second_message = mock_handle.call_args_list[1].kwargs["message"]

        self.assertIn("Example University", second_message)
        self.assertIn("Previous expert step results", second_message)
        self.assertEqual(
            result,
            "Your department is Computer Science."
        )

    def test_bulk_delete_is_blocked(self):
        result = llm.run_orchestrator_plan(
            self.db, "Delete all skills"
        )

        self.assertIn("can't delete all skills", result)

if __name__ == "__main__":
    unittest.main()
