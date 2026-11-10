

"""
socket_events.py — handles real-time chat messages.
"""

from flask_socketio import emit
from flask_app import socketio
from flask_app.utils.llm import handle_ai_chat_request
from flask import current_app


@socketio.on('send_message')
def handle_message(data):
    user_message = data.get('message', '').strip()

    if not user_message:
        return

    try:
        db = current_app.db

        ai_response = handle_ai_chat_request(
            db,
            role="Orchestrator",
            message=user_message
        )

    except Exception as error:
        print(f"LLM error: {error}")
        ai_response = f"Could not reach the AI: {error}"

    emit('receive_message', {'response': ai_response})

