"""GridVault development and WSGI entry point."""

from gridvault import create_app
from gridvault.extensions import socketio


app = create_app()


if __name__ == "__main__":
    socketio.run(
        app,
        host="0.0.0.0",
        port=5000,
        debug=app.config.get("ENVIRONMENT") == "development",
    )
