import os
import shutil
import tempfile
import unittest

from flask_app.utils.database import database

class FixtureDatabaseTests(unittest.TestCase):

    def test_fixtures_load_into_separate_database(self):
        project = os.path.abspath("homework 2")
        source_sql = os.path.join(
            project, "flask_app", "database", "create_tables"
        )
        source_fixtures = os.path.join(project, "fixtures")

        with tempfile.TemporaryDirectory() as temp:
            data_folder = os.path.join(temp, "data")
            os.makedirs(os.path.join(data_folder, "initial_data"))

            shutil.copytree(
                source_sql,
                os.path.join(data_folder, "create_tables")
            )

            for filename in os.listdir(source_fixtures):
                shutil.copy(
                    os.path.join(source_fixtures, filename),
                    os.path.join(data_folder, "initial_data", filename)
                )

            db = database()
            db.db_path = os.path.join(temp, "test.db")

            tables = [
                "institutions", "positions",
                "experiences", "skills"
            ]

            for table in tables:
                db._create_table(data_folder, table)

            for table in tables:
                db._seed_table(data_folder, table)

            self.assertEqual(
                db.query("SELECT name FROM institutions")[0]["name"],
                "Michigan State University"
            )
            self.assertEqual(
                db.query("SELECT name FROM skills ORDER BY skill_id")[0]["name"],
                "Python"
            )
            self.assertEqual(len(db.query("SELECT * FROM positions")), 1)
            self.assertEqual(len(db.query("SELECT * FROM experiences")), 1)

if __name__ == "__main__":
    unittest.main()

