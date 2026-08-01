import io
import json
import tempfile
import unittest
from pathlib import Path

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
        return self.client.post(
            "/register",
            data={
                "username": username,
                "password": "secure-passphrase",
                "confirm_password": "secure-passphrase",
            },
            follow_redirects=True,
        )

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
            json={"elements": elements},
        )
        self.assertEqual(response.status_code, 200)
        with self.app.app_context():
            saved = json.loads(db.session.get(Design, design_id).board_state)
            self.assertEqual({item["type"] for item in saved}, set(element_types))

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
        self.assertEqual(self.client.get(f"/design-lab/{design_id}/edit").status_code, 409)
        self.assertEqual(self.client.post(f"/design-lab/{design_id}/board", json={"elements": []}).status_code, 409)
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


if __name__ == "__main__":
    unittest.main()
