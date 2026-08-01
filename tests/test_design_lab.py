import io
import json
import tempfile
import unittest
from pathlib import Path

from sqlalchemy import inspect, text
from werkzeug.security import generate_password_hash

from gridvault import create_app
from gridvault.extensions import db
from gridvault.models import (
    Design,
    DesignActivity,
    DesignAsset,
    DesignRevision,
    DesignReviewComment,
    DesignStatusHistory,
    Project,
    User,
)


class DesignLabTestCase(unittest.TestCase):
    def setUp(self):
        self.uploads = tempfile.TemporaryDirectory()
        self.app = create_app(
            {
                "TESTING": True,
                "SECRET_KEY": "design-lab-v2-test",
                "SQLALCHEMY_DATABASE_URI": "sqlite://",
                "WTF_CSRF_ENABLED": False,
                "DESIGN_UPLOAD_FOLDER": self.uploads.name,
            }
        )
        self.client = self.app.test_client()

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.drop_all()
        self.uploads.cleanup()

    def register(self, username):
        with self.app.app_context():
            db.session.add(User(username=username, password_hash=generate_password_hash("secure-passphrase")))
            db.session.commit()
        return self.login(username)

    def login(self, username):
        return self.client.post(
            "/login",
            data={"username": username, "password": "secure-passphrase"},
            follow_redirects=True,
        )

    def add_operator(self, username):
        self.client.post("/logout")
        self.register(username)
        with self.app.app_context():
            operator_id = db.session.scalar(
                db.select(User.id).where(User.username == username)
            )
        return operator_id

    def create_project(self):
        self.client.post(
            "/project-vault/new",
            data={
                "codename": "NIGHTFALL",
                "title": "Nightfall Mission",
                "description": "Coordinate the complete mission handoff.",
                "status": "Active",
                "objectives": "Establish mission direction",
            },
        )
        with self.app.app_context():
            return db.session.scalar(db.select(Project.id))

    def payload(self, **changes):
        payload = {
            "codename": "AURORA_UI",
            "title": "Aurora Operator Console",
            "stage": "Concept",
            "project_id": "",
            "problem": "Operators cannot scan mission context quickly enough.",
            "proposed_solution": "A layered console with clear hierarchy and quiet visual signals.",
            "intended_user": "GridVault mission operators",
            "design_goals": "Fast scanning\nCalm visual hierarchy",
            "constraints": "Low-light operation\nResponsive layout",
            "materials": "OLED display\nAnodized controls",
            "dimensions": "1440 × 1024 reference viewport",
            "components": "Status rail\nMission canvas\nAction dock",
            "risks": "Information density may obscure priority.",
            "references": "Console study https://example.com/reference",
            "collaborator_ids": [],
        }
        payload.update(changes)
        return payload

    def create_design(self, **changes):
        return self.client.post(
            "/design-lab/new",
            data=self.payload(**changes),
            follow_redirects=True,
        )

    def design_id(self):
        with self.app.app_context():
            return db.session.scalar(db.select(Design.id))

    def test_gallery_dossier_project_link_search_and_filter(self):
        self.register("VEGA_7")
        project_id = self.create_project()
        response = self.create_design(project_id=str(project_id))

        self.assertIn(b"Aurora Operator Console", response.data)
        self.assertIn(b"Intended user", response.data)
        gallery = self.client.get("/design-lab?q=hierarchy&stage=Concept")
        self.assertIn(b"AURORA_UI", gallery.data)
        self.assertIn(b"NIGHTFALL", gallery.data)
        with self.app.app_context():
            design = db.session.scalar(db.select(Design))
            self.assertEqual(design.project_id, project_id)
            self.assertEqual(design.revision_number, 1)
            self.assertEqual(len(design.revisions), 1)

    def test_optional_dossier_fields_have_polished_empty_states(self):
        self.register("VEGA_7")
        response = self.create_design(
            constraints="",
            materials="",
            dimensions="",
            components="",
            risks="",
            references="",
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Awaiting cover image", response.data)
        self.assertGreaterEqual(response.data.count(b"Not specified."), 6)
        self.assertIn(b"No revision feedback yet.", response.data)

    def test_concept_board_persists_all_supported_elements(self):
        self.register("VEGA_7")
        self.create_design()
        design_id = self.design_id()
        png = (
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
            b"\x00\x00\x00\x01\x00\x00\x00\x01"
            b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
        )
        asset_response = self.client.post(
            f"/design-lab/{design_id}/uploads",
            data={"usage": "board", "image": (io.BytesIO(png), "concept.png")},
            content_type="multipart/form-data",
            headers={"Accept": "application/json", "X-Requested-With": "fetch"},
        )
        asset_url = asset_response.get_json()["url"]
        element_types = (
            "text", "heading", "image", "rectangle", "circle", "arrow",
            "label", "swatch", "reference",
        )
        elements = []
        for index, element_type in enumerate(element_types):
            elements.append(
                {
                    "id": f"element_{index}",
                    "type": element_type,
                    "x": index * 10,
                    "y": index * 12,
                    "width": 180,
                    "height": 100,
                    "z": index,
                    "content": f"Concept {index}",
                    "color": "#67d8c4",
                    "url": (
                        "https://example.com/reference"
                        if element_type == "reference"
                        else (
                            asset_url
                            if element_type == "image"
                            else ""
                        )
                    ),
                }
            )
        response = self.client.post(
            f"/design-lab/{design_id}/board",
            json={"elements": elements, "base_version": 0},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["board_version"], 1)
        with self.app.app_context():
            design = db.session.get(Design, design_id)
            saved = json.loads(design.board_state)
            self.assertEqual({item["type"] for item in saved}, set(element_types))
            self.assertEqual(design.board_version, 1)
            arrow = next(item for item in saved if item["type"] == "arrow")
            self.assertEqual(
                {"start_x", "start_y", "end_x", "end_y"},
                {key for key in arrow if key.endswith(("_x", "_y"))},
            )

    def test_concurrent_board_save_cannot_overwrite_newer_state(self):
        self.register("VEGA_7")
        self.create_design()
        design_id = self.design_id()
        first_state = [{
            "id": "first_position",
            "type": "text",
            "x": 120,
            "y": 160,
            "width": 220,
            "height": 140,
            "z": 0,
            "content": "Newest position",
            "color": "#67d8c4",
            "url": "",
        }]
        stale_state = [{**first_state[0], "x": 900, "content": "Stale position"}]

        first = self.client.post(
            f"/design-lab/{design_id}/board",
            json={"elements": first_state, "base_version": 0},
        )
        stale = self.client.post(
            f"/design-lab/{design_id}/board",
            json={"elements": stale_state, "base_version": 0},
        )

        self.assertEqual(first.status_code, 200)
        self.assertEqual(stale.status_code, 409)
        self.assertEqual(stale.get_json()["board_version"], 1)
        with self.app.app_context():
            design = db.session.get(Design, design_id)
            self.assertEqual(design.board_version, 1)
            self.assertEqual(json.loads(design.board_state), first_state)

    def test_toolkit_objects_and_connector_serialize_safely(self):
        self.register("TOOLKIT_7")
        self.create_design(codename="TKV_ONE")
        design_id = self.design_id()
        representative = [
            {
                "id": "heading_one", "type": "heading", "x": 100, "y": 100,
                "width": 320, "height": 90, "z": 1, "content": "", "color": "#67d8c4", "url": "",
                "data": {"text": "System map", "size": "32", "alignment": "left", "accent": "#67d8c4"},
            },
            {
                "id": "zone_one", "type": "zone", "x": 80, "y": 70,
                "width": 700, "height": 420, "z": 0, "content": "", "color": "#67d8c4", "url": "",
                "data": {"name": "Authentication", "opacity": "18"},
            },
            {
                "id": "code_one", "type": "code", "x": 470, "y": 120,
                "width": 360, "height": 260, "z": 2, "content": "", "color": "#67d8c4", "url": "",
                "data": {"language": "Python", "filename": "auth.py", "code": "def verify():\n    return True", "line_numbers": True, "wrap": False},
            },
            {
                "id": "market_one", "type": "market", "x": 900, "y": 120,
                "width": 350, "height": 300, "z": 3, "content": "", "color": "#67d8c4", "url": "",
                "data": {"symbol": "GRID", "name": "Grid Systems", "asset_type": "Stock", "price": "42.50", "change": "1.4", "status": "Researching", "thesis": "Manual research", "risks": "Execution", "history": "38,40,42.5"},
            },
            {
                "id": "map_one", "type": "minimap", "x": 1300, "y": 120,
                "width": 300, "height": 220, "z": 4, "content": "", "color": "#67d8c4", "url": "", "data": {},
            },
            {
                "id": "connector_one", "type": "connector", "x": 380, "y": 120,
                "width": 120, "height": 80, "z": 5, "content": "", "color": "#67d8c4", "url": "",
                "source_id": "heading_one", "target_id": "code_one", "data": {"label": "documents"},
            },
        ]
        response = self.client.post(
            f"/design-lab/{design_id}/board",
            json={"elements": representative, "base_version": 0},
        )
        self.assertEqual(response.status_code, 200)
        with self.app.app_context():
            saved = json.loads(db.session.get(Design, design_id).board_state)
            self.assertEqual({item["type"] for item in saved}, {"heading", "zone", "code", "market", "minimap", "connector"})
            connector = next(item for item in saved if item["type"] == "connector")
            self.assertEqual((connector["source_id"], connector["target_id"]), ("heading_one", "code_one"))

        unsafe = [{**representative[0], "data": {**representative[0]["data"], "text": "<script>alert(1)</script>"}}]
        rejected = self.client.post(
            f"/design-lab/{design_id}/board",
            json={"elements": unsafe, "base_version": 1},
        )
        self.assertEqual(rejected.status_code, 400)

    def test_board_geometry_must_stay_inside_canvas(self):
        self.register("VEGA_7")
        self.create_design()
        design_id = self.design_id()
        outside = [{
            "id": "outside",
            "type": "rectangle",
            "x": 3990,
            "y": 2990,
            "width": 100,
            "height": 100,
            "z": 0,
            "content": "",
            "color": "#67d8c4",
            "url": "",
        }]

        response = self.client.post(
            f"/design-lab/{design_id}/board",
            json={"elements": outside, "base_version": 0},
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn(b"outside the allowed bounds", response.data)

    def test_dossier_edits_and_board_checkpoints_create_revision_snapshots(self):
        self.register("VEGA_7")
        self.create_design()
        design_id = self.design_id()
        self.client.post(
            f"/design-lab/{design_id}/edit",
            data=self.payload(
                title="Aurora Console Refined",
                stage="Exploring",
                change_note="Refined the dossier hierarchy.",
            ),
        )
        self.client.post(
            f"/design-lab/{design_id}/revisions",
            data={"change_note": "Captured the first concept board layout."},
        )
        with self.app.app_context():
            design = db.session.get(Design, design_id)
            self.assertEqual(design.revision_number, 3)
            revisions = db.session.scalars(
                db.select(DesignRevision).order_by(DesignRevision.revision_number)
            ).all()
            self.assertEqual([item.revision_number for item in revisions], [1, 2, 3])
            self.assertEqual(json.loads(revisions[0].snapshot)["title"], "Aurora Operator Console")
        old = self.client.get(f"/design-lab/{design_id}/revisions/1")
        self.assertIn(b"Read-only snapshot", old.data)
        self.assertIn(b"Aurora Operator Console", old.data)

    def test_collaborator_can_edit_comment_approve_and_publish(self):
        self.register("OWNER_1")
        collaborator_id = self.add_operator("SCOUT_4")
        self.client.post("/logout")
        self.login("OWNER_1")
        self.create_design(collaborator_ids=[str(collaborator_id)])
        design_id = self.design_id()
        self.client.post("/logout")
        self.login("SCOUT_4")
        revised = self.client.post(
            f"/design-lab/{design_id}/edit",
            data=self.payload(
                title="Aurora Console Collaboration Pass",
                stage="Exploring",
                change_note="Refined the component language with the design team.",
            ),
            follow_redirects=True,
        )
        self.assertIn(b"Aurora Console Collaboration Pass", revised.data)
        self.client.post("/logout")
        self.login("OWNER_1")
        submitted = self.client.post(
            f"/design-lab/{design_id}/submit-review",
            data={"change_note": "Complete dossier and board ready for review."},
            follow_redirects=True,
        )
        self.assertIn(b"In Review", submitted.data)

        self.client.post("/logout")
        self.login("SCOUT_4")
        self.client.post(
            f"/design-lab/{design_id}/comments",
            data={"revision_number": "3", "body": "Hierarchy is clear and mission ready."},
        )
        approved = self.client.post(
            f"/design-lab/{design_id}/review",
            data={"decision": "approve", "note": "Approved after visual hierarchy review."},
            follow_redirects=True,
        )
        self.assertIn(b"Published r4", approved.data)
        with self.app.app_context():
            design = db.session.get(Design, design_id)
            self.assertEqual(design.stage, "Approved")
            self.assertEqual(design.published_revision_number, 4)
            self.assertEqual(db.session.scalar(db.select(db.func.count(DesignReviewComment.id))), 1)

    def test_rejection_records_status_history_and_creator_cannot_review(self):
        self.register("OWNER_1")
        reviewer_id = self.add_operator("REVIEW_2")
        self.client.post("/logout")
        self.login("OWNER_1")
        self.create_design(collaborator_ids=[str(reviewer_id)])
        design_id = self.design_id()
        self.client.post(f"/design-lab/{design_id}/submit-review", data={"change_note": "Review the current visual direction."})
        self.assertEqual(
            self.client.post(f"/design-lab/{design_id}/review", data={"decision": "approve", "note": "Creator cannot self approve."}).status_code,
            403,
        )
        self.client.post("/logout")
        self.login("REVIEW_2")
        self.client.post(f"/design-lab/{design_id}/review", data={"decision": "reject", "note": "Revise the contrast and component spacing."})
        with self.app.app_context():
            design = db.session.get(Design, design_id)
            self.assertEqual(design.stage, "Rejected")
            self.assertIsNone(design.published_revision_number)
            self.assertIn("Rejected", [entry.to_stage for entry in design.status_history])

    def test_permissions_and_archived_designs_are_read_only(self):
        self.register("OWNER_1")
        reviewer_id = self.add_operator("REVIEW_2")
        self.client.post("/logout")
        self.login("OWNER_1")
        self.create_design(collaborator_ids=[str(reviewer_id)])
        design_id = self.design_id()
        self.client.post(f"/design-lab/{design_id}/submit-review", data={"change_note": "Ready for final collaborator approval."})
        self.client.post("/logout")
        self.login("REVIEW_2")
        self.client.post(f"/design-lab/{design_id}/review", data={"decision": "approve", "note": "Approved for publication and archive."})
        self.client.post("/logout")
        self.login("OWNER_1")
        archived = self.client.post(f"/design-lab/{design_id}/archive", follow_redirects=True)
        self.assertIn(b"Archived", archived.data)
        archived_board = self.client.get(f"/design-lab/{design_id}/board")
        self.assertIn(b'data-editable="false"', archived_board.data)
        self.assertIn(b"Archived designs cannot be modified.", archived_board.data)
        self.assertIn(b"Read-only board", archived_board.data)
        self.assertIn(b"disabled", archived_board.data)
        self.assertEqual(self.client.get(f"/design-lab/{design_id}/edit").status_code, 409)
        self.assertEqual(self.client.post(f"/design-lab/{design_id}/board", json={"elements": [], "base_version": 0}).status_code, 409)
        self.assertEqual(self.client.post(f"/design-lab/{design_id}/comments", data={"revision_number": "4", "body": "No more edits."}).status_code, 409)

        self.client.post("/logout")
        self.register("OBSERVER_9")
        self.assertEqual(self.client.get(f"/design-lab/{design_id}").status_code, 200)
        self.assertEqual(self.client.get(f"/design-lab/{design_id}/edit").status_code, 403)

    def test_upload_and_text_url_validation(self):
        self.register("VEGA_7")
        rejected = self.create_design(
            title="<b>Unsafe</b>",
            references="Unsafe http://example.com/reference",
        )
        self.assertIn(b"HTML markup is not allowed", rejected.data)
        self.assertIn(b"Reference URLs must use", rejected.data)
        self.create_design()
        design_id = self.design_id()
        invalid = self.client.post(
            f"/design-lab/{design_id}/uploads",
            data={"usage": "cover", "image": (io.BytesIO(b"not-an-image"), "payload.svg")},
            content_type="multipart/form-data",
        )
        self.assertEqual(invalid.status_code, 400)
        png = (
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
            b"\x00\x00\x00\x01\x00\x00\x00\x01"
            b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
        )
        uploaded = self.client.post(
            f"/design-lab/{design_id}/uploads",
            data={"usage": "cover", "image": (io.BytesIO(png), "cover.png")},
            content_type="multipart/form-data",
            follow_redirects=True,
        )
        self.assertIn(b"Cover image updated", uploaded.data)
        with self.app.app_context():
            asset = db.session.scalar(db.select(DesignAsset))
            self.assertEqual(asset.mime_type, "image/png")
            self.assertTrue((Path(self.uploads.name) / asset.stored_filename).is_file())

    def test_mission_console_design_metrics_and_activity(self):
        self.register("VEGA_7")
        self.create_design()
        response = self.client.get("/mission-console")
        self.assertIn(b"Total designs", response.data)
        self.assertIn(b"Designs under review", response.data)
        self.assertIn(b"Approved designs", response.data)
        self.assertIn(b"Created design AURORA_UI", response.data)
        with self.app.app_context():
            self.assertEqual(db.session.scalar(db.select(db.func.count(DesignActivity.id))), 1)

    def test_design_forms_and_json_autosave_require_csrf(self):
        self.register("VEGA_7")
        self.create_design()
        design_id = self.design_id()
        self.app.config["WTF_CSRF_ENABLED"] = True
        self.assertIn(b'name="csrf_token"', self.client.get(f"/design-lab/{design_id}").data)
        self.assertEqual(self.client.post("/design-lab/new", data=self.payload()).status_code, 400)
        self.assertEqual(self.client.post(f"/design-lab/{design_id}/board", json={"elements": []}).status_code, 400)

    def test_additive_schema_upgrade_adds_board_version_to_v2_database(self):
        with tempfile.TemporaryDirectory() as temp_directory:
            database_path = Path(temp_directory) / "design-v2.db"
            database_uri = f"sqlite:///{database_path.as_posix()}"
            baseline = create_app(
                {
                    "TESTING": True,
                    "SECRET_KEY": "baseline-schema-key",
                    "SQLALCHEMY_DATABASE_URI": database_uri,
                    "WTF_CSRF_ENABLED": False,
                }
            )
            with baseline.app_context():
                with db.engine.begin() as connection:
                    connection.execute(
                        text("ALTER TABLE design DROP COLUMN board_version")
                    )
                self.assertNotIn(
                    "board_version",
                    {
                        column["name"]
                        for column in inspect(db.engine).get_columns("design")
                    },
                )
                db.session.remove()
                db.engine.dispose()

            upgraded = create_app(
                {
                    "TESTING": True,
                    "SECRET_KEY": "upgraded-schema-key",
                    "SQLALCHEMY_DATABASE_URI": database_uri,
                    "WTF_CSRF_ENABLED": False,
                }
            )
            with upgraded.app_context():
                self.assertIn(
                    "board_version",
                    {
                        column["name"]
                        for column in inspect(db.engine).get_columns("design")
                    },
                )
                db.session.remove()
                db.engine.dispose()


if __name__ == "__main__":
    unittest.main()
