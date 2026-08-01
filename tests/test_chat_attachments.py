import base64
import io
import tempfile
import unittest

from werkzeug.security import generate_password_hash

from gridvault import create_app
from gridvault.extensions import db, socketio
from gridvault.models import (
    ChatAttachment,
    Conversation,
    ConversationMember,
    Message,
    User,
)
from gridvault.realtime import connected_users, message_receipts, sid_to_user_id


PNG_PIXEL = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


class ChatAttachmentTestCase(unittest.TestCase):
    def setUp(self):
        self.uploads = tempfile.TemporaryDirectory()
        self.app = create_app(
            {
                "TESTING": True,
                "SECRET_KEY": "attachment-test-key",
                "SQLALCHEMY_DATABASE_URI": "sqlite://",
                "WTF_CSRF_ENABLED": False,
                "CHAT_UPLOAD_FOLDER": self.uploads.name,
                "CHAT_UPLOAD_MAX_BYTES": 1024,
            }
        )

    def tearDown(self):
        connected_users.clear()
        sid_to_user_id.clear()
        message_receipts.clear()
        with self.app.app_context():
            db.session.remove()
            db.drop_all()
        self.uploads.cleanup()

    def register(self, callsign):
        client = self.app.test_client()
        with self.app.app_context():
            db.session.add(User(username=callsign, password_hash=generate_password_hash("secure-passphrase")))
            db.session.commit()
        response = client.post("/login", data={"username": callsign, "password": "secure-passphrase"}, follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        return client

    def conversation(self, conversation_type, newest=False):
        with self.app.app_context():
            query = db.select(Conversation).where(Conversation.type == conversation_type)
            if newest:
                query = query.order_by(Conversation.id.desc())
            return db.session.execute(query).scalars().first()

    def upload(self, client, conversation_id, filename, data, mime="text/plain", message=""):
        return client.post(
            f"/chat/conversations/{conversation_id}/attachments",
            data={
                "file": (io.BytesIO(data), filename, mime),
                "message": message,
                "client_id": "pending_attachment_test",
            },
            content_type="multipart/form-data",
        )

    def test_direct_upload_download_realtime_and_refresh_persistence(self):
        alpha = self.register("FILE_ALPHA")
        bravo = self.register("FILE_BRAVO")
        outsider = self.register("FILE_OUTSIDER")
        alpha.post("/chat/conversations", data={"callsigns": "FILE_BRAVO"})
        direct = self.conversation("direct")
        bravo_socket = socketio.test_client(self.app, flask_test_client=bravo)
        bravo_socket.get_received()

        response = self.upload(
            alpha,
            direct.id,
            "mission.txt",
            b"Private mission file",
            message="Review this file",
        )
        self.assertEqual(response.status_code, 201)
        payload = response.get_json()["message"]
        attachment = payload["attachment"]
        received = [
            event for event in bravo_socket.get_received()
            if event["name"] == "receive_message"
        ]
        self.assertEqual(len(received), 1)
        self.assertEqual(received[0]["args"][0]["attachment"]["filename"], "mission.txt")

        download = bravo.get(attachment["download_url"])
        self.assertEqual(download.status_code, 200)
        self.assertEqual(download.data, b"Private mission file")
        self.assertIn("attachment", download.headers["Content-Disposition"])
        self.assertEqual(download.headers["X-Content-Type-Options"], "nosniff")
        download.close()
        self.assertEqual(outsider.get(attachment["metadata_url"]).status_code, 403)
        self.assertEqual(outsider.get(attachment["download_url"]).status_code, 403)

        refreshed = bravo.get(f"/chat?conversation={direct.id}")
        self.assertIn(b"mission.txt", refreshed.data)
        with self.app.app_context():
            self.assertEqual(
                db.session.scalar(db.select(db.func.count(Message.id)).where(
                    Message.conversation_id == direct.id,
                )),
                1,
            )
        bravo_socket.disconnect()

    def test_group_member_access_and_former_member_lockout(self):
        alpha = self.register("VAULT_ALPHA")
        bravo = self.register("VAULT_BRAVO")
        self.register("VAULT_CHARLIE")
        alpha.post(
            "/chat/conversations",
            data={"callsigns": "VAULT_BRAVO,VAULT_CHARLIE", "group_name": "Vault Team"},
        )
        group = self.conversation("group")
        response = self.upload(alpha, group.id, "group.json", b'{"ready": true}', "application/json")
        self.assertEqual(response.status_code, 201)
        download_url = response.get_json()["message"]["attachment"]["download_url"]
        group_download = bravo.get(download_url)
        self.assertEqual(group_download.status_code, 200)
        group_download.close()
        bravo.post(f"/chat/conversations/{group.id}/leave")
        self.assertEqual(bravo.get(download_url).status_code, 403)
        self.assertEqual(bravo.get(f"/chat/conversations/{group.id}/files").status_code, 403)

    def test_grid_unsupported_oversized_and_disguised_files_are_rejected(self):
        alpha = self.register("BLOCK_ALPHA")
        grid = self.conversation("grid")
        self.assertEqual(
            self.upload(alpha, grid.id, "grid.txt", b"blocked").status_code,
            400,
        )
        self.register("BLOCK_BRAVO")
        alpha.post("/chat/conversations", data={"callsigns": "BLOCK_BRAVO"})
        direct = self.conversation("direct")
        for filename in ("malware.exe", "payload.js.txt", "archive.rar"):
            response = self.upload(alpha, direct.id, filename, b"not permitted")
            self.assertEqual(response.status_code, 400, filename)
        oversized = self.upload(alpha, direct.id, "large.txt", b"x" * 1025)
        self.assertEqual(oversized.status_code, 400)
        with self.app.app_context():
            self.assertEqual(db.session.scalar(db.select(db.func.count(ChatAttachment.id))), 0)

    def test_path_traversal_is_sanitized_and_duplicate_names_never_overwrite(self):
        alpha = self.register("PATH_ALPHA")
        self.register("PATH_BRAVO")
        alpha.post("/chat/conversations", data={"callsigns": "PATH_BRAVO"})
        direct = self.conversation("direct")
        first = self.upload(alpha, direct.id, "../../notes.txt", b"first")
        second = self.upload(alpha, direct.id, "notes.txt", b"second")
        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 201)
        with self.app.app_context():
            attachments = db.session.execute(
                db.select(ChatAttachment).order_by(ChatAttachment.uploaded_at)
            ).scalars().all()
            self.assertEqual([item.original_filename for item in attachments], ["notes.txt", "notes.txt"])
            self.assertNotEqual(attachments[0].storage_key, attachments[1].storage_key)
            self.assertNotIn("..", attachments[0].storage_key)
            self.assertTrue(all("/" not in item.storage_key and "\\" not in item.storage_key for item in attachments))

    def test_image_preview_and_text_preview_use_safe_headers(self):
        alpha = self.register("PREVIEW_ALPHA")
        self.register("PREVIEW_BRAVO")
        alpha.post("/chat/conversations", data={"callsigns": "PREVIEW_BRAVO"})
        direct = self.conversation("direct")
        image = self.upload(alpha, direct.id, "pixel.png", PNG_PIXEL, "image/png")
        self.assertEqual(image.status_code, 201)
        image_preview = alpha.get(image.get_json()["message"]["attachment"]["preview_url"])
        self.assertEqual(image_preview.status_code, 200)
        self.assertEqual(image_preview.mimetype, "image/png")
        self.assertEqual(image_preview.headers["X-Content-Type-Options"], "nosniff")
        image_preview.close()

        code = self.upload(
            alpha,
            direct.id,
            "unsafe.html",
            b"<script>globalThis.compromised=true</script>",
            "text/html",
        )
        preview_url = code.get_json()["message"]["attachment"]["preview_url"]
        text_preview = alpha.get(preview_url)
        self.assertEqual(text_preview.status_code, 200)
        self.assertEqual(text_preview.mimetype, "text/plain")
        self.assertIn(b"<script>", text_preview.data)
        self.assertEqual(text_preview.headers["Content-Security-Policy"], "sandbox; default-src 'none'")
        text_preview.close()

    def test_files_view_is_scoped_to_active_conversation(self):
        alpha = self.register("LIST_ALPHA")
        self.register("LIST_BRAVO")
        self.register("LIST_CHARLIE")
        alpha.post("/chat/conversations", data={"callsigns": "LIST_BRAVO"})
        first_direct = self.conversation("direct")
        self.upload(alpha, first_direct.id, "bravo-only.txt", b"bravo")
        alpha.post("/chat/conversations", data={"callsigns": "LIST_CHARLIE"})
        second_direct = self.conversation("direct", newest=True)
        self.upload(alpha, second_direct.id, "charlie-only.txt", b"charlie")

        first_page = alpha.get(f"/chat?conversation={first_direct.id}")
        self.assertIn(b"bravo-only.txt", first_page.data)
        self.assertNotIn(b"charlie-only.txt", first_page.data)
        files = alpha.get(f"/chat/conversations/{first_direct.id}/files").get_json()["files"]
        self.assertEqual([item["filename"] for item in files], ["bravo-only.txt"])


class ChatAttachmentCsrfTestCase(unittest.TestCase):
    def test_attachment_upload_requires_csrf(self):
        uploads = tempfile.TemporaryDirectory()
        app = create_app(
            {
                "TESTING": True,
                "SECRET_KEY": "attachment-csrf-key",
                "SQLALCHEMY_DATABASE_URI": "sqlite://",
                "WTF_CSRF_ENABLED": True,
                "CHAT_UPLOAD_FOLDER": uploads.name,
            }
        )
        with app.app_context():
            alpha = User(username="CSRF_FILE_ALPHA", password_hash=generate_password_hash("password"))
            bravo = User(username="CSRF_FILE_BRAVO", password_hash=generate_password_hash("password"))
            conversation = Conversation(type="direct", direct_key="1:2", creator=alpha)
            conversation.memberships = [
                ConversationMember(user=alpha),
                ConversationMember(user=bravo),
            ]
            db.session.add(conversation)
            db.session.commit()
            user_id = alpha.id
            conversation_id = conversation.id
        client = app.test_client()
        with client.session_transaction() as session:
            session["_user_id"] = str(user_id)
            session["_fresh"] = True
        response = client.post(
            f"/chat/conversations/{conversation_id}/attachments",
            data={"file": (io.BytesIO(b"safe"), "safe.txt")},
            content_type="multipart/form-data",
        )
        self.assertEqual(response.status_code, 400)
        with app.app_context():
            db.session.remove()
            db.drop_all()
        uploads.cleanup()


if __name__ == "__main__":
    unittest.main()
