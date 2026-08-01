# GridVault

GridVault is a secure, authenticated mission workspace for small teams. The Mission Console provides a shared command surface, while The Hub delivers persistent real-time messaging with operator presence, typing indicators, read receipts, and smart autoscroll.

## Foundation modules

- **Mission Console** — authenticated landing page with system metrics, recent signals, and module access
- **The Hub** — live team channel with the original GridVault chat behavior preserved
- **Design Lab** — staged creative systems workspace
- **Engineering Bay** — staged build operations workspace
- **Project Vault** — staged project and artifact inventory
- **Briefing Room** — staged objectives and decision workspace
- **Archive** — staged operational memory
- **Settings** — staged operator and workspace controls

Every application route requires an authenticated callsign except registration and login. The legacy `/chat` URL remains available alongside `/hub`.

## Local setup

GridVault requires Python 3.10 or newer.

```bash
python -m venv .venv
```

Activate the environment, then install dependencies:

```bash
python -m pip install -r requirements.txt
```

Copy `.env.example` to `.env` and set a strong `SECRET_KEY`. Environment files are ignored by Git. PowerShell users can start a development session without an environment loader like this:

```powershell
$env:SECRET_KEY = python -c "import secrets; print(secrets.token_hex(32))"
python server.py
```

GridVault is then available at `http://localhost:5000`.

## Configuration

| Variable | Purpose | Default |
| --- | --- | --- |
| `SECRET_KEY` | Signs login sessions and CSRF tokens | Ephemeral in development; required in production |
| `GRIDVAULT_ENV` | Set to `production` for strict secret validation and secure cookies | `development` |
| `DATABASE_URL` | SQLAlchemy database connection | `sqlite:///gridvault.db` |
| `SOCKETIO_CORS_ALLOWED_ORIGINS` | Optional comma-separated trusted browser origins | Same-origin only |

For production, set both `GRIDVAULT_ENV=production` and a strong `SECRET_KEY`. Never place real secrets in source control.

## Data compatibility

The application factory explicitly keeps Flask's instance directory at `instance/`, and the `User` and `Message` models retain their original table and column names. Existing `instance/gridvault.db` files therefore continue to provide the same user accounts and stored messages after upgrading.

The entire `instance/` directory plus common SQLite extensions are ignored. Do not commit a database file.

## Project structure

```text
gridvault/
├── blueprints/       # Auth, console, Hub, and module routes
├── static/           # Shared styles and Hub client behavior
├── templates/        # Shared shell and module views
├── config.py         # Environment-driven configuration
├── extensions.py     # Flask extension instances
├── models.py         # Compatible User and Message models
├── realtime.py       # Socket.IO presence and messaging events
└── __init__.py       # Application factory
tests/                # Automated application and realtime tests
server.py             # Development and WSGI entry point
```

The application factory allows tests and future deployments to supply configuration without changing application code. Blueprints keep module routes independent as GridVault grows.

## Tests

Run the automated suite with:

```bash
python -m unittest discover -s tests -v
```

The suite verifies authentication, password hashing, authenticated module access, persistent Hub messaging, presence events, legacy route compatibility, and core security headers. The same suite runs in GitHub Actions for pushes and pull requests.

## Production serving

The WSGI application remains available as `server:app`. A typical threaded deployment can run:

```bash
gunicorn --worker-class gthread --threads 100 --bind 0.0.0.0:5000 server:app
```

Use a production database and HTTPS reverse proxy appropriate for the deployment. Configure explicit Socket.IO origins when the browser origin differs from the application origin.
