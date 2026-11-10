
import os
import re
import json

from groq import Groq
from jinja2 import Template
from flask_app.utils.embeddings import semantic_search


DEFAULT_MODEL = "openai/gpt-oss-120b"
SEMANTIC_MIN_SCORE = 0.60


MASTER_TEMPLATE = Template("""
You are an AI expert with the following role:

Role: {{ role }}
Domain: {{ domain }}

Specific instructions:
{{ specific_instructions }}

Background context:
{{ background_context }}

Examples:
{{ few_shot_examples }}

User request:
{{ user_message }}
""")


def fill_template(role_data, user_message):
    return MASTER_TEMPLATE.render(
        role=role_data["role"],
        domain=role_data["domain"],
        specific_instructions=role_data["specific_instructions"],
        background_context=role_data["background_context"] or "",
        few_shot_examples=role_data["few_shot_examples"] or "",
        user_message=user_message
    )


def send_message(user_message, system_prompt="You are a helpful assistant."):
    api_key = os.getenv("GROQ_API_KEY")

    if not api_key:
        return "GROQ_API_KEY is missing. Check your .env file."

    try:
        client = Groq(api_key=api_key)

        response = client.chat.completions.create(
            model=DEFAULT_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message}
            ],
            temperature=0.2,
            max_tokens=2048
        )

        content = response.choices[0].message.content

        if not content:
            return "The AI returned an empty response."

        return content.strip()

    except Exception as error:
        print(f"Groq error: {error}")
        return f"Could not reach the AI: {error}"


def process_pending_action(db, message):
    pending = getattr(db, "pending_action", None)

    if not pending:
        return False, None

    answer = message.strip().lower().rstrip(" .!?")

    yes_answers = ("yes", "y", "confirm", "confirmed")
    no_answers = ("no", "n", "cancel", "cancel it", "nope")
    uncertain_answers = (
        "maybe", "not sure", "unsure",
        "perhaps", "i don't know"
    )

    if answer in uncertain_answers:
        return True, (
            "No action taken. Your pending request is still "
            "waiting for confirmation."
        )

    if answer in no_answers:
        db.pending_action = None
        return True, "Cancelled. No database changes were made."

    if answer not in yes_answers:
        # A different request cancels the old pending action.
        db.pending_action = None
        return False, None

    operation = pending.get("operation")

    if operation == "delete_skill":
        skill_id = pending.get("skill_id")

        if type(skill_id) is not int or skill_id <= 0:
            db.pending_action = None
            return True, "Invalid saved skill ID. Cancelled."

        try:
            deleted = db.deleteSkill(skill_id)
        except Exception:
            db.pending_action = None
            return True, (
                "Could not delete the skill. "
                "No further action was taken."
            )

        db.pending_action = None

        if not deleted:
            return True, "Skill no longer exists. No change made."

        return True, (
            f"Successfully deleted skill: "
            f"{pending.get('name', 'Unknown')}."
        )

    if operation == "add_skill":
        name = pending.get("name")
        level = pending.get("skill_level")
        experience_id = pending.get("experience_id")

        if not isinstance(name, str) or not name.strip():
            db.pending_action = None
            return True, "Invalid saved action. Cancelled."

        if type(level) is not int or not 1 <= level <= 10:
            db.pending_action = None
            return True, "Invalid saved skill level. Cancelled."

        if experience_id is not None:
            if type(experience_id) is not int or experience_id <= 0:
                db.pending_action = None
                return True, "Invalid saved experience ID. Cancelled."

            exists = db.query(
                "SELECT experience_id FROM experiences "
                "WHERE experience_id = ?",
                (experience_id,)
            )

            if not exists:
                db.pending_action = None
                return True, "Experience no longer exists. Cancelled."

        duplicate = db.query(
            "SELECT skill_id FROM skills "
            "WHERE LOWER(name) = LOWER(?) "
            "AND experience_id IS ?",
            (name.strip(), experience_id)
        )

        if duplicate:
            db.pending_action = None
            return True, f"'{name}' already exists. No change made."

        try:
            db.insertRows(
                "skills",
                ["experience_id", "name", "skill_level"],
                [experience_id, name.strip(), level]
            )
        except Exception:
            db.pending_action = None
            return True, "Could not add the skill. No change was confirmed."

        db.pending_action = None
        return True, f"Successfully added skill: {name.strip()}."

    db.pending_action = None
    return True, "Cancelled: unsupported pending operation."


def handle_ai_chat_request(db, role, message):

    if role == "Orchestrator":
        handled, response = process_pending_action(db, message)

        if handled:
            return response

        return run_orchestrator_plan(db, message)

    roles = db.getLLMRoles()

    if role not in roles:
        return f"Unknown role: {role}"

    role_data = roles[role]

    if role == "Content Expert":
        role_data = dict(role_data)
        role_data["background_context"] = (
            (role_data["background_context"] or "")
            + "\n\nResume content:\n"
            + db.getResumeText()
        )

    prompt = fill_template(role_data, message)

    if role == "Database Read Expert":
        return execute_read_query(db, prompt)

    if role == "Database Write Expert":
        return execute_write_action(db, prompt)

    if role == "Content Expert":
        return send_message(
            prompt,
            system_prompt=(
                "You are a resume content expert. "
                "Use only the supplied resume information. "
                "Never invent qualifications or experience."
            )
        )

    return "Unsupported role."


def execute_read_query(db, prompt):

    sql = send_message(
        prompt,
        system_prompt=(
            "You are a SQLite database query generator. "
            "Return exactly one valid SQLite SELECT statement. "
            "Never generate INSERT, UPDATE, DELETE, DROP, or other "
            "modifying statements. "
            "Never use question-mark or named SQL parameters. "
            "Use actual values from the supplied context. "
            "Never assume values for database columns. "
            "Do not invent table names or column names. "
            "Return SQL only, without markdown or explanations."
        )
    )

    if sql.startswith("Could not reach the AI"):
        return sql

    sql = re.sub(
        r"^\s*```(?:sql)?\s*",
        "",
        sql,
        flags=re.IGNORECASE
    )

    sql = re.sub(r"\s*```\s*$", "", sql).strip()

    if not re.match(r"^SELECT\b", sql, flags=re.IGNORECASE):
        return (
            "The Database Read Expert did not generate "
            "a valid SELECT query."
        )

        # Allow one optional semicolon at the end of a SELECT query.
    if sql.endswith(";"):
        sql = sql[:-1].rstrip()

    # Reject multiple statements and SQL comments.
    if ";" in sql or "--" in sql or "/*" in sql or "*/" in sql:
        return "The generated SQL query was rejected for safety."

    if "?" in sql:
        return (
            "The generated SQL query contains missing parameters. "
            "Please try again."
        )

    try:
        rows = db.query(sql)
        return str(rows)

    except Exception as error:
        return f"Database query error: {error}"


def execute_write_action(db, prompt):

    generated = send_message(
        prompt,
        system_prompt=(
            "You are a database write action generator. "
            "Return one JSON object only. "
            "Allowed operations are add_skill and delete_skill. "
            "Never execute a database operation. "
            "Never return SQL, Python code, or function calls. "
            "For add_skill use keys: operation, name, "
            "skill_level, experience_id. "
            "For delete_skill use keys: operation and name. "
            "Use null for experience_id when no experience is specified."
        )
    )

    if generated.startswith("Could not reach the AI"):
        return generated

    generated = re.sub(
        r"^\s*```(?:json)?\s*",
        "",
        generated,
        flags=re.IGNORECASE
    )

    generated = re.sub(r"\s*```\s*$", "", generated).strip()

    try:
        action = json.loads(generated)

    except (ValueError, TypeError):
        return "Invalid action: the AI must return valid JSON."

    if not isinstance(action, dict):
        return "Invalid action format."

    operation = action.get("operation")

    if operation == "delete_skill":

        name = action.get("name")

        if not isinstance(name, str) or not name.strip():
            return "Invalid skill name."

        matches = db.query(
            """
            SELECT skill_id, name, skill_level, experience_id
            FROM skills
            WHERE LOWER(name) = LOWER(?)
            ORDER BY skill_id
            """,
            (name.strip(),)
        )

        if not matches:
            return f"Skill '{name.strip()}' was not found."

        if len(matches) > 1:
            ids = ", ".join(
                str(item["skill_id"]) for item in matches
            )

            return (
                f"Multiple skills named '{name.strip()}' were found "
                f"(IDs: {ids}). Please specify which record to delete."
            )

        skill = matches[0]

        db.pending_action = {
            "operation": "delete_skill",
            "skill_id": skill["skill_id"],
            "name": skill["name"]
        }

        return (
            f"Please confirm: delete skill '{skill['name']}' "
            f"(ID: {skill['skill_id']})? "
            "Reply yes to confirm or no to cancel."
        )

    if operation == "add_skill":

        name = action.get("name")
        level = action.get("skill_level")
        experience_id = action.get("experience_id")

        if not isinstance(name, str) or not name.strip():
            return "Invalid skill name."

        if type(level) is not int or not 1 <= level <= 10:
            return "Skill level must be an integer from 1 to 10."

        if experience_id is not None:
            if type(experience_id) is not int or experience_id <= 0:
                return "Invalid experience ID."

            exists = db.query(
                "SELECT experience_id FROM experiences "
                "WHERE experience_id = ?",
                (experience_id,)
            )

            if not exists:
                return "Experience not found."

        duplicate = db.query(
            "SELECT skill_id FROM skills "
            "WHERE LOWER(name) = LOWER(?) "
            "AND experience_id IS ?",
            (name.strip(), experience_id)
        )

        if duplicate:
            return f"'{name.strip()}' already exists."

        db.pending_action = {
            "operation": "add_skill",
            "name": name.strip(),
            "skill_level": level,
            "experience_id": experience_id
        }

        return (
            f"Please confirm: add skill '{name.strip()}' "
            f"with level {level}? "
            "Reply yes to confirm or no to cancel."
        )

    return "This write operation is not allowed."



def run_orchestrator_plan(db, prompt):

    lower_prompt = prompt.lower()
    print("[TRACE] New request received.")

    # Block requests to delete the entire skills collection.
    destructive_words = (
        "delete", "remove", "clear", "clean up", "empty"
    )

    bulk_targets = (
        "all skills",
        "every skill",
        "skills so the list is empty",
        "skills list empty",
        "list is empty",
        "entire skills list",
        "all of my skills",
        "every one of my skills"
    )

    is_bulk_delete = (
        any(word in lower_prompt for word in destructive_words)
        and any(target in lower_prompt for target in bulk_targets)
    )

    if is_bulk_delete:
        print("[TRACE] Blocked bulk delete request.")
        return (
            "I can't delete all skills in one operation. "
            "Please name one specific skill to delete."
        )

    exact_keywords = (
        "list all", "count", "how many",
        "show all", "give me all", "exact number"
    )

    semantic_keywords = (
        "similar", "related", "conceptual",
        "alternative", "msu", "michigan state",
        "ai skills", "machine learning",
        "what skills relate", "meaning", "abbreviation"
    )

    is_exact = any(
        word in lower_prompt for word in exact_keywords
    )

    is_semantic = any(
        word in lower_prompt for word in semantic_keywords
    )

    if is_semantic and not is_exact:
        print(
            "[TRACE] Route: semantic search. "
            "Reason: semantic keywords matched."
        )

        try:
            results = semantic_search(
                db,
                prompt,
                limit=5
            )

            if not results:
                print("[TRACE] Semantic search returned no records.")
                return "No matching records were found."

            print("[TRACE] Semantic search results (ranked):")

            for item in results:
                print(
                    f"[TRACE] table={item.get('table_name')} "
                    f"id={item.get('record_id')} "
                    f"score={item.get('score')}"
                )

            relevant = [
                item for item in results
                if item.get("score", 0) >= SEMANTIC_MIN_SCORE
            ]

            print(
                f"[TRACE] Relevant results above threshold "
                f"{SEMANTIC_MIN_SCORE}: {len(relevant)}"
            )

            if not relevant:
                return (
                    "No sufficiently relevant records were found. "
                    "I cannot confirm that the requested institution "
                    "or experience exists in the resume."
                )

            semantic_prompt = (
                "User question:\n"
                + prompt
                + "\n\nRetrieved resume records:\n"
                + json.dumps(relevant, ensure_ascii=False)
                + "\n\nAnswer using only records that are genuinely "
                "relevant to the user's question. "
                "Do not treat similar names as identical institutions. "
                "Do not assume an abbreviation refers to a retrieved "
                "institution unless the records explicitly support it. "
                "If the records do not establish the requested fact, "
                "say that it could not be confirmed."
            )

            return send_message(
                semantic_prompt,
                system_prompt=(
                    "You are a careful resume semantic search assistant. "
                    "Never invent facts or claim that two different "
                    "institutions are the same."
                )
            )

        except Exception as error:
            print(f"[TRACE] Semantic search error: {error}")
            return f"Semantic search failed: {error}"

    if is_exact:
        print(
            "[TRACE] Route: orchestrator. "
            "Reason: exact database question."
        )
    else:
        print(
            "[TRACE] Route: orchestrator. "
            "Reason: no semantic keyword matched."
        )

    plan_text = send_message(
        prompt,
        system_prompt=(
            "You are a strict Orchestrator. "
            "Return only a valid JSON array. "
            "Every item must contain exactly two keys: role and message. "
            "Allowed roles are: Database Read Expert, "
            "Database Write Expert, and Content Expert. "
            "Never use assistant as a role. "
            "Never ask the user for information that can be retrieved "
            "from the resume database. "
            "Questions about education, institutions, departments, "
            "skills, positions, experience, dates, and counts "
            "must use Database Read Expert. "
            "Requests to add or delete one specific skill "
            "must use Database Write Expert. "
            "For a request to find the education institution and then "
            "its department, return two Database Read Expert steps: "
            "first retrieve the institution name, then retrieve its "
            "department using the previous step result. "
            "Do not return explanations, markdown, or empty responses."
        )
    )

    if plan_text.startswith("Could not reach the AI"):
        return plan_text

    plan_text = re.sub(
        r"^\s*```(?:json)?\s*",
        "",
        plan_text,
        flags=re.IGNORECASE
    )

    plan_text = re.sub(r"\s*```\s*$", "", plan_text).strip()

    try:
        plan = json.loads(plan_text)

        if not isinstance(plan, list) or not plan:
            return "The Orchestrator did not return a valid JSON array."

        if len(plan) > 5:
            return "The Orchestrator returned too many steps."

        results = []
        previous_results = []

        print(f"[TRACE] Plan contains {len(plan)} step(s).")

        for step_number, item in enumerate(plan, start=1):

            if not isinstance(item, dict):
                return "Invalid expert request format."

            if set(item.keys()) != {"role", "message"}:
                return "The Orchestrator returned invalid step fields."

            expert_role = item.get("role")
            expert_message = item.get("message")

            if expert_role not in (
                "Database Read Expert",
                "Database Write Expert",
                "Content Expert"
            ):
                return "The Orchestrator requested an unsupported expert."

            if (
                not isinstance(expert_message, str)
                or not expert_message.strip()
            ):
                return "The Orchestrator returned an empty message."

            print(
                f"[TRACE] Step {step_number}/{len(plan)}: "
                f"{expert_role}"
            )

            contextual_message = expert_message

            if previous_results:
                print(
                    "[TRACE] Passing previous step results "
                    "to the next expert."
                )

                contextual_message = (
                    "Previous expert step results:\n"
                    + "\n\n".join(previous_results)
                    + "\n\nComplete the next step using the previous "
                    "results. Do not assume missing information:\n"
                    + expert_message
                )

            result = handle_ai_chat_request(
                db,
                role=expert_role,
                message=contextual_message
            )

            if not isinstance(result, str):
                result = str(result)

            if result.startswith(
                (
                    "Could not reach the AI",
                    "Database query error:",
                    "Semantic search failed:",
                    "Orchestrator error:"
                )
            ):
                print(f"[TRACE] Step {step_number} failed.")
                return result

            if result.strip() == "[]":
                return (
                    "The requested information was not found "
                    "in the resume database."
                )

            step_result = (
                f"Expert: {expert_role}\n"
                f"Result: {result}"
            )

            results.append(step_result)
            previous_results.append(step_result)

            if getattr(db, "pending_action", None):
                print(
                    "[TRACE] Write action is pending user approval. "
                    "Stopping execution."
                )
                return result

        print("[TRACE] All expert steps completed.")

        synthesis_prompt = (
            "Original user question:\n"
            + prompt
            + "\n\nExpert results:\n"
            + "\n\n".join(results)
            + "\n\nAnswer the original question directly in plain text. "
            "Use only the expert results above. "
            "Combine dependent results when appropriate. "
            "Do not invent facts. "
            "Do not ask the user what they want to know. "
            "Do not return JSON or a plan."
        )

        return send_message(
            synthesis_prompt,
            system_prompt=(
                "You are a helpful and factual final assistant. "
                "Answer directly using only the supplied expert results."
            )
        )

    except (ValueError, TypeError):
        return (
            "I couldn't process this request because the AI "
            "did not return a valid plan. Please try again."
        )

    except Exception as error:
        return f"Orchestrator error: {error}"


