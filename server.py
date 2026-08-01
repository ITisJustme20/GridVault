"""GridVault development and WSGI entry point."""

import os

from gridvault import create_app
from gridvault.extensions import socketio


app = create_app()


if __name__ == "__main__":
    debug_enabled = os.environ.get("GRIDVAULT_DEBUG", "").lower() in {
        "1",
        "true",
        "yes",
    }
    socketio.run(
        app,
        host="0.0.0.0",
        port=5000,
        debug=debug_enabled,
        use_reloader=debug_enabled,
    )
