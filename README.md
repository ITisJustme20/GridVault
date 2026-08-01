# GridVault

GridVault is a secure, authenticated mission workspace for small teams. The Mission Console provides a shared command surface, while The Hub delivers persistent real-time messaging with operator presence, typing indicators, read receipts, and smart autoscroll.

## Foundation modules

- **Mission Console** — authenticated landing page with system metrics, recent signals, and module access
- **The Hub** — live team channel with the original GridVault chat behavior preserved
- **Design Lab** — visual concept boards, versioned dossiers, and review publishing
- **Engineering Bay** — staged build operations workspace
- **Project Vault** — durable project records, assignments, objectives, activity, and discussion
- **Briefing Room** — staged objectives and decision workspace
- **Archive** — staged operational memory
- **Settings** — staged operator and workspace controls

Every application route requires an authenticated callsign except registration and login. The legacy `/chat` URL remains available alongside `/hub`.

## Project Vault

Project Vault v1 provides a complete authenticated project workflow:

- create projects with a unique codename, title, plain-text description, status, objectives, and assigned operators
- move projects through Concept, Research, Active, Prototype, Testing, Paused, and Complete
- search by codename, title, or description and filter by status
- inspect creator attribution, created/updated timestamps, objectives, assignments, and the project activity timeline
- keep a project-specific discussion attributed to operator callsigns
- archive completed projects while retaining their searchable, read-only record

All authenticated operators can view projects and participate in discussion. Only a project's creator can edit it or archive it, and only projects in the Complete state can be archived. Server-side validation enforces field lengths, allowed statuses, valid operators, unique codenames, and plain-text content. CSRF protection applies to every state-changing form.

## Design Lab

Design Lab v2 is GridVault's visual ideation and publishing workspace. Authenticated operators can:

- browse a visual gallery with covers, project links, stages, revisions, search, and filters
- build structured dossiers covering the problem, proposed solution, intended user, goals, constraints, materials, dimensions, components, risks, and references
- develop ideas on an autosaving concept board with notes, headings, uploaded images, shapes, arrows, labels, swatches, and HTTPS reference cards
- drag, resize, edit, delete, reorder, zoom, pan, and reset the board view
- capture immutable numbered revision snapshots with change notes and inspect the complete history
- assign callsign collaborators, attach review comments to revisions, and submit work for approval or rejection
- publish the approved revision and archive completed dossiers as read-only records

Creators manage collaborator assignments and archive approved designs. Creators and assigned collaborators can revise dossiers and boards, capture versions, and comment; only a collaborator can approve or reject a submitted revision. All authenticated operators can browse the gallery and read dossiers and historical revisions.

Uploads are limited to structurally recognized PNG, JPEG, GIF, or WebP images of at most 5 MB. Uploaded assets are stored under the ignored instance directory. Text remains plain text, reference cards and linked URLs require HTTPS, JSON board payloads are bounded and validated, and every state-changing form or request is CSRF-protected.

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
| `DESIGN_UPLOAD_FOLDER` | Private Design Lab image storage | `instance/design_uploads/` |
| `DESIGN_UPLOAD_MAX_BYTES` | Per-image upload limit | 5 MB |

For production, set both `GRIDVAULT_ENV=production` and a strong `SECRET_KEY`. Never place real secrets in source control.

## Data compatibility

The application factory explicitly keeps Flask's instance directory at `instance/`, and the `User` and `Message` models retain their original table and column names. Existing `instance/gridvault.db` files therefore continue to provide the same user accounts and stored messages after upgrading.

GridVault uses an additive schema strategy: `ensure_schema()` calls SQLAlchemy's check-first table creation to create only missing Project Vault and Design Lab tables and indexes. It never drops, rewrites, or renames the existing `user` or `message` tables. The automated suite validates this strategy against a temporary legacy-format database before releases are merged.

The entire `instance/` directory plus common SQLite extensions are ignored. Do not commit a database file.

## Project structure

```text
gridvault/
├── blueprints/       # Auth, console, Hub, Project Vault, and Design Lab routes
├── static/           # Shared styles plus Hub and concept-board clients
├── templates/        # Shared shell and module views
├── config.py         # Environment-driven configuration
├── extensions.py     # Flask extension instances
├── models.py         # Hub, project, dossier, revision, review, and asset data
├── realtime.py       # Socket.IO presence and messaging events
├── schema.py         # Additive, check-first schema upgrades
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

The suite verifies authentication, persistent Hub behavior, Project Vault, Design Lab gallery and dossier flows, board persistence, revision snapshots, collaborators, approval and rejection, uploads, archive lockout, Mission Console metrics, input validation, CSRF enforcement, and legacy-data-preserving schema upgrades. The same suite runs in GitHub Actions for pushes and pull requests.

## Production serving

The WSGI application remains available as `server:app`. A typical threaded deployment can run:

```bash
gunicorn --worker-class gthread --threads 100 --bind 0.0.0.0:5000 server:app
```

Use a production database and HTTPS reverse proxy appropriate for the deployment. Configure explicit Socket.IO origins when the browser origin differs from the application origin.
