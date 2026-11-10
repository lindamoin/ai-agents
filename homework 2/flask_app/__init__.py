
from flask import Flask
from flask_socketio import SocketIO
from dotenv import load_dotenv

socketio = SocketIO(async_mode="threading")


def create_app():
    load_dotenv()

    app = Flask(__name__)
    app.secret_key = 'dev-key-change-for-production'

    from flask_app.utils.database import database
    db = database()

    print("Setting up database...")
    db.createTables(purge=False)
    app.db = db
    print("Database ready.")

    socketio.init_app(app)

    with app.app_context():
        from flask_app.routes import main
        app.register_blueprint(main)
        from flask_app.utils import socket_events

    @app.after_request
    def disable_cache(response):
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
        return response

    return app, socketio
