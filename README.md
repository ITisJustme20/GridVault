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

Every workspace route requires an authenticated callsign. Existing operators use `/login`; new operators must use a valid one-time administrator authorization at `/access`. The legacy `/register` route cannot create accounts and redirects to the Access Gate. The legacy `/chat` URL remains available alongside `/hub`.

## Access Gate

GridVault is invitation-only. Administrators can open **Access Control** from the authenticated navigation to create a cryptographically random one-time code, optionally reserve it for a callsign, choose a 24-hour, 7-day, 30-day, or unlimited lifetime, and revoke an unused authorization. The plaintext code is displayed only in the creation response; the database retains only its SHA-256 hash and a short safe ledger reference.

Administrator access uses the additive `User.is_admin` flag. Existing installations can bootstrap selected established operators without rewriting database rows by setting `GRIDVAULT_ADMIN_CALLSIGNS` to a comma-separated list of callsigns. Configure that list only in the deployment environment, never in source control.

Invitation consumption validates and normalizes the callsign, hashes the passphrase with Werkzeug's established password hashing, and atomically changes the authorization from Active to Used in the same database transaction that creates the user. A conditional update prevents two concurrent requests from consuming the same code. Newly invited operators see one concise orientation screen; existing users retain their normal login and do not see it.

## Operator profiles and trust controls

Each callsign has a compact authenticated profile containing only specialty, short status, join date, and Groups shared with the viewer. Operators may edit only their own specialty and status. Callsigns remain permanent, and profile views never expose Direct conversations, non-mutual Groups, reports, suspension reasons, invitation details, or internal identifiers.

Blocking is private and reversible. A block disables Direct discovery, history access, files, messages, typing, and presence in both directions while preserving GRID and shared Group access and history. Reports use a fixed reason category and bounded plain-text explanation and are visible only in administrator Access Control.

Administrators can suspend or reactivate accounts from Access Control. Suspension preserves all historical content, rotates the account's authentication version, disconnects active sockets, and prevents HTTP, WebSocket, and login activity. Reactivation requires a fresh login; previously invalidated sessions do not resume.

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

On the concept board, drag an element by its labeled move bar or drag a non-text shape directly. Drag empty canvas space to pan. Two-finger touchpad scrolling pans, while pinch/Control-scroll zooms around the pointer. Text regions remain selectable and editable without starting a drag. Autosave serializes local writes and uses an additive board-version token so an older browser tab cannot overwrite newer saved work; a visible conflict state offers a safe Reload board action.

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
| `GRIDVAULT_ADMIN_CALLSIGNS` | Comma-separated existing callsigns allowed to manage invitations | Empty |
| `DESIGN_UPLOAD_FOLDER` | Private Design Lab image storage | `instance/design_uploads/` |
| `DESIGN_UPLOAD_MAX_BYTES` | Per-image upload limit | 5 MB |
| `GRIDVAULT_DEBUG` | Opt into the Flask debugger and reloader for local development | Disabled |

For production, set both `GRIDVAULT_ENV=production` and a strong `SECRET_KEY`. Never place real secrets in source control.

## Data compatibility

The application factory explicitly keeps Flask's instance directory at `instance/`, and the `User` and `Message` models retain their original table and column names. Existing `instance/gridvault.db` files therefore continue to provide the same user accounts and stored messages after upgrading.

GridVault uses an additive schema strategy: `ensure_schema()` calls SQLAlchemy's check-first table creation to create only missing tables and indexes, including invitation, block, and report records. It adds only nullable or safely defaulted profile, account-state, and session-version columns to legacy users; existing accounts remain Active and already oriented. It never drops, rewrites, or renames the existing `user` or `message` tables. The automated suite validates this strategy against a temporary legacy-format database before releases are merged.

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
node --test tests/js/*.test.js
node --check gridvault/static/js/design_board_core.js
node --check gridvault/static/js/design_board.js
node --check gridvault/static/js/chat.js
node --check gridvault/static/js/access_control.js
```

The suite verifies invitation-only authentication, operator-profile privacy, Direct blocking, private reporting, suspension and session invalidation, administrator permissions, persistent Hub behavior, Project Vault, Design Lab gallery and dossier flows, board persistence and concurrent-save protection, bounded drag and resize geometry, zoom anchoring, layer ordering, revision snapshots, collaborators, approval and rejection, uploads, archive lockout, Mission Console metrics, input validation, CSRF enforcement, and legacy-data-preserving schema upgrades. The same Python and JavaScript checks run in GitHub Actions for pushes and pull requests.

## Production serving

The WSGI application remains available as `server:app`. A typical threaded deployment can run:

```bash
gunicorn --worker-class gthread --threads 100 --bind 0.0.0.0:5000 server:app
```

Use a production database and HTTPS reverse proxy appropriate for the deployment. Configure explicit Socket.IO origins when the browser origin differs from the application origin.
