import sqlite3
import tempfile
import unittest
from pathlib import Path

from sqlalchemy import inspect
from werkzeug.security import generate_password_hash

from gridvault import create_app
from gridvault.extensions import db
from gridvault.models import (
    Message,
    Project,
    ProjectActivity,
    ProjectComment,
    User,
)
from gridvault.realtime import connected_users, message_receipts, sid_to_user_id


class ProjectVaultTestCase(unittest.TestCase):
    def setUp(self):
        self.app = create_app(
            {
                "TESTING": True,
                "SECRET_KEY": "project-vault-test-key",
                "SQLALCHEMY_DATABASE_URI": "sqlite://",
                "WTF_CSRF_ENABLED": False,
            }
        )
        self.client = self.app.test_client()

    def tearDown(self):
        connected_users.clear()
        sid_to_user_id.clear()
        message_receipts.clear()
        with self.app.app_context():
            db.session.remove()
            db.drop_all()

    def register(self, callsign, password="secure-passphrase"):
        with self.app.app_context():
            db.session.add(User(username=callsign, password_hash=generate_password_hash(password)))
            db.session.commit()
        return self.login(callsign, password)

    def login(self, callsign, password="secure-passphrase"):
        return self.client.post(
            "/login",
            data={"username": callsign, "password": password},
            follow_redirects=True,
        )

    def project_payload(self, **overrides):
        payload = {
            "codename": "NIGHTFALL",
            "title": "Nightfall Coordination Layer",
            "description": "Coordinate the full mission handoff across operators.",
            "status": "Active",
            "objectives": "Map the mission surface\nShip the operator workflow",
            "assignee_ids": [],
        }
        payload.update(overrides)
        return payload

    def create_project(self, **overrides):
        return self.client.post(
            "/project-vault/new",
            data=self.project_payload(**overrides),
            follow_redirects=True,
        )

    def test_project_creation_persists_assignments_objectives_and_activity(self):
        self.register("VEGA_7")
        with self.app.app_context():
            creator_id = db.session.scalar(
                db.select(User.id).where(User.username == "VEGA_7")
            )

        self.client.post("/logout")
        self.register("ATLAS_2")
        with self.app.app_context():
            assignee_id = db.session.scalar(
                db.select(User.id).where(User.username == "ATLAS_2")
            )

        self.client.post("/logout")
        self.login("VEGA_7")
        response = self.create_project(assignee_ids=[str(assignee_id)])

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"NIGHTFALL", response.data)
        with self.app.app_context():
            project = db.session.scalar(db.select(Project))
            self.assertEqual(project.creator_id, creator_id)
            self.assertEqual(project.status, "Active")
            self.assertEqual(
                [operator.username for operator in project.assigned_operators],
                ["ATLAS_2"],
            )
            self.assertEqual(len(project.objectives), 2)
            self.assertIsNotNone(project.created_at)
            self.assertIsNotNone(project.updated_at)
            self.assertEqual(project.activities[0].action, "created")

    def test_project_access_and_edit_permissions(self):
        self.register("OWNER_1")
        self.create_project()
        with self.app.app_context():
            project_id = db.session.scalar(db.select(Project.id))

        self.client.post("/logout")
        anonymous = self.client.get("/project-vault")
        self.assertEqual(anonymous.status_code, 302)
        self.assertIn("/login", anonymous.headers["Location"])

        self.register("SCOUT_4")
        self.assertEqual(
            self.client.get(f"/project-vault/{project_id}").status_code,
            200,
        )
        self.assertEqual(
            self.client.get(f"/project-vault/{project_id}/edit").status_code,
            403,
        )
        self.assertEqual(
            self.client.post(f"/project-vault/{project_id}/archive").status_code,
            403,
        )

    def test_creator_can_edit_project_and_timeline_records_change(self):
        self.register("OWNER_1")
        self.create_project()
        with self.app.app_context():
            project_id = db.session.scalar(db.select(Project.id))

        response = self.client.post(
            f"/project-vault/{project_id}/edit",
            data=self.project_payload(
                title="Nightfall Prototype",
                status="Prototype",
                objectives="Build the prototype\nValidate the project workflow",
            ),
            follow_redirects=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Nightfall Prototype", response.data)
        with self.app.app_context():
            project = db.session.get(Project, project_id)
            self.assertEqual(project.status, "Prototype")
            self.assertEqual(project.title, "Nightfall Prototype")
            self.assertEqual(len(project.objectives), 2)
            actions = db.session.scalars(
                db.select(ProjectActivity).where(
                    ProjectActivity.project_id == project_id
                )
            ).all()
            self.assertEqual([activity.action for activity in actions], ["created", "updated"])

    def test_status_filter_and_search(self):
        self.register("VEGA_7")
        self.create_project()
        self.create_project(
            codename="LANTERN",
            title="Research Lantern",
            description="Investigate navigation signals for the archive layer.",
            status="Research",
        )

        active_response = self.client.get("/project-vault?status=Active")
        self.assertIn(b"NIGHTFALL", active_response.data)
        self.assertNotIn(b"LANTERN", active_response.data)

        search_response = self.client.get("/project-vault?q=navigation")
        self.assertIn(b"LANTERN", search_response.data)
        self.assertNotIn(b"NIGHTFALL", search_response.data)
        self.assertEqual(
            self.client.get("/project-vault?status=Invalid").status_code,
            400,
        )

    def test_mission_console_shows_active_project_count_and_activity(self):
        self.register("VEGA_7")
        self.create_project()

        response = self.client.get("/mission-console")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Active projects", response.data)
        self.assertIn(b"Created project NIGHTFALL", response.data)

    def test_only_complete_projects_can_be_archived(self):
        self.register("OWNER_1")
        self.create_project()
        with self.app.app_context():
            project_id = db.session.scalar(db.select(Project.id))

        blocked = self.client.post(
            f"/project-vault/{project_id}/archive",
            follow_redirects=True,
        )
        self.assertIn(b"Only completed projects may be archived", blocked.data)

        self.client.post(
            f"/project-vault/{project_id}/edit",
            data=self.project_payload(status="Complete"),
        )
        archived = self.client.post(
            f"/project-vault/{project_id}/archive",
            follow_redirects=True,
        )
        self.assertIn(b"Archived", archived.data)

        default_list = self.client.get("/project-vault")
        self.assertNotIn(b"NIGHTFALL", default_list.data)
        archive_list = self.client.get("/project-vault?status=Archived")
        self.assertIn(b"NIGHTFALL", archive_list.data)
        with self.app.app_context():
            project = db.session.get(Project, project_id)
            self.assertEqual(project.status, "Archived")
        self.assertEqual(
            self.client.post(
                f"/project-vault/{project_id}/discussion",
                data={"body": "Archived records are immutable."},
            ).status_code,
            409,
        )

    def test_project_discussion_is_attributed_and_rejects_html(self):
        self.register("OWNER_1")
        self.create_project()
        with self.app.app_context():
            project_id = db.session.scalar(db.select(Project.id))

        self.client.post("/logout")
        self.register("SCOUT_4")
        response = self.client.post(
            f"/project-vault/{project_id}/discussion",
            data={"body": "Prototype review is ready for the mission team."},
            follow_redirects=True,
        )
        self.assertIn(b"Prototype review is ready", response.data)
        self.assertIn(b"SCOUT_4", response.data)

        rejected = self.client.post(
            f"/project-vault/{project_id}/discussion",
            data={"body": "<script>alert('no')</script>"},
            follow_redirects=True,
        )
        self.assertIn(b"HTML markup is not allowed", rejected.data)
        with self.app.app_context():
            comments = db.session.scalars(db.select(ProjectComment)).all()
            self.assertEqual(len(comments), 1)
            self.assertEqual(comments[0].author.username, "SCOUT_4")

    def test_invalid_project_input_is_rejected(self):
        self.register("VEGA_7")
        response = self.create_project(
            codename="<b>bad</b>",
            title="x",
            description="<script>unsafe</script>",
            status="Archived",
            objectives="x",
        )
        self.assertIn(b"Select a valid project status", response.data)
        self.assertIn(b"HTML markup is not allowed", response.data)
        with self.app.app_context():
            self.assertEqual(db.session.scalar(db.select(db.func.count(Project.id))), 0)

    def test_project_forms_require_csrf_when_enabled(self):
        self.register("VEGA_7")
        self.app.config["WTF_CSRF_ENABLED"] = True

        form_response = self.client.get("/project-vault/new")
        self.assertIn(b'name="csrf_token"', form_response.data)
        rejected = self.client.post(
            "/project-vault/new",
            data=self.project_payload(),
        )
        self.assertEqual(rejected.status_code, 400)

    def test_additive_schema_upgrade_preserves_legacy_user_and_message(self):
        with tempfile.TemporaryDirectory() as temp_directory:
            database_path = Path(temp_directory) / "legacy.db"
            connection = sqlite3.connect(database_path)
            connection.executescript(
                """
                CREATE TABLE user (
                    id INTEGER PRIMARY KEY,
                    username VARCHAR(30) NOT NULL UNIQUE,
                    password_hash VARCHAR(255) NOT NULL,
                    created_at DATETIME NOT NULL
                );
                CREATE TABLE message (
                    id INTEGER PRIMARY KEY,
                    body VARCHAR(500) NOT NULL,
                    created_at DATETIME NOT NULL,
                    user_id INTEGER NOT NULL REFERENCES user(id)
                );
                INSERT INTO user VALUES (1, 'LEGACY_1', 'preserved-hash', '2026-01-01 00:00:00');
                INSERT INTO message VALUES (1, 'Preserve this signal.', '2026-01-01 00:01:00', 1);
                """
            )
            connection.commit()
            connection.close()

            upgrade_app = create_app(
                {
                    "TESTING": True,
                    "SECRET_KEY": "schema-upgrade-test-key",
                    "SQLALCHEMY_DATABASE_URI": f"sqlite:///{database_path.as_posix()}",
                    "WTF_CSRF_ENABLED": False,
                }
            )
            with upgrade_app.app_context():
                self.assertEqual(db.session.get(User, 1).username, "LEGACY_1")
                self.assertEqual(db.session.get(Message, 1).body, "Preserve this signal.")
                table_names = set(inspect(db.engine).get_table_names())
                self.assertTrue(
                    {
                        "project",
                        "project_activity",
                        "project_comment",
                        "design",
                        "design_revision",
                        "design_review_comment",
                        "design_status_history",
                        "design_activity",
                        "design_asset",
                    }.issubset(
                        table_names
                    )
                )
                design_columns = {
                    column["name"]
                    for column in inspect(db.engine).get_columns("design")
                }
                self.assertIn("board_version", design_columns)
                user_columns = {
                    column["name"]
                    for column in inspect(db.engine).get_columns("user")
                }
                self.assertTrue(
                    {
                        "is_admin",
                        "has_seen_orientation",
                        "specialty",
                        "status_text",
                        "account_state",
                        "suspended_at",
                        "suspension_reason",
                        "suspended_by_user_id",
                        "auth_version",
                        "presence_visibility",
                    }.issubset(user_columns)
                )
                self.assertIn("invitation", table_names)
                self.assertIn("user_block", table_names)
                self.assertIn("user_report", table_names)
                self.assertTrue(db.session.get(User, 1).has_seen_orientation)
                self.assertEqual(db.session.get(User, 1).account_state, "Active")
                db.session.remove()
                db.engine.dispose()


if __name__ == "__main__":
    unittest.main()
