

import os
import re
import ast
from groq import Groq
from jinja2 import Template

DEFAULT_MODEL = "openai/gpt-oss-120b"

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
            temperature=0.7,
            max_tokens=2048
        )

        return response.choices[0].message.content

    except Exception as error:
        print(f"Groq error: {error}")
        return f"Could not reach the AI: {error}"


def handle_ai_chat_request(db, role, message):
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
        return send_message(prompt)

    if role == "Orchestrator":
        return run_orchestrator_plan(db, prompt)

    return "Unsupported role."


def execute_read_query(db, prompt):
    sql = send_message(prompt)

    if sql.startswith("Could not reach the AI"):
        return sql

    sql = re.sub(r"```(?:sql)?", "", sql, flags=re.IGNORECASE).strip()
    sql = sql.replace("```", "").strip()

    if not sql.upper().startswith("SELECT"):
        return "The Database Read Expert did not generate a valid SELECT query."

    try:
        rows = db.query(sql)
        return str(rows)
    except Exception as error:
        return f"Database query error: {error}"


def execute_write_action(db, prompt):
    generated_code = send_message(prompt)

    if generated_code.startswith("Could not reach the AI"):
        return generated_code

    generated_code = re.sub(
        r"```(?:python)?", "", generated_code, flags=re.IGNORECASE
    ).replace("```", "").strip()

    try:
        local_vars = {}
        exec(generated_code, {"db": db}, local_vars)
        return local_vars.get("outcome", "The database update was completed.")
    except Exception as error:
        return f"Database update error: {error}"


def run_orchestrator_plan(db, prompt):
    plan_text = send_message(prompt)

    if plan_text.startswith("Could not reach the AI"):
        return plan_text

    plan_text = re.sub(
        r"```(?:python)?", "", plan_text, flags=re.IGNORECASE
    ).replace("```", "").strip()

    try:
        plan = ast.literal_eval(plan_text)

        if not isinstance(plan, list):
            return "The Orchestrator did not return a valid list."

        results = []

        for call in plan:
            match = re.fullmatch(
                r'handle_ai_chat_request\(role="([^"]+)",\s*message="(.*?)"\s*\)',
                call
            )

            if not match:
                return "The Orchestrator generated an invalid expert call."

            expert_role = match.group(1)
            expert_message = match.group(2)

            result = handle_ai_chat_request(
                db,
                role=expert_role,
                message=expert_message
            )

            results.append(
                f"Expert: {expert_role}\nResult: {result}"
            )

        synthesis_prompt = (
            "Answer the user's original request using the expert results below. "
            "Give a clear, natural response. If an expert reports an error, "
            "explain it honestly.\n\n"
            f"Original request: {prompt}\n\n"
            + "\n\n".join(results)
        )

        return send_message(synthesis_prompt)

    except Exception as error:
        return f"Orchestrator error: {error}"

