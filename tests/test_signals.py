import io
import tempfile
import unittest

from werkzeug.security import generate_password_hash

from gridvault import create_app
from gridvault.extensions import db, socketio
from gridvault.models import (
    AttachmentOpen,
    Conversation,
    OperatorSignal,
    User,
    UserBlock,
    UserReport,
)
from gridvault.realtime import connected_users, message_receipts, sid_to_user_id


class SignalQueueTestCase(unittest.TestCase):
    def setUp(self):
        self.uploads = tempfile.TemporaryDirectory()
        self.app = create_app(
            {
                "TESTING": True,
                "SECRET_KEY": "signal-test-key",
                "SQLALCHEMY_DATABASE_URI": "sqlite://",
                "WTF_CSRF_ENABLED": False,
                "CHAT_UPLOAD_FOLDER": self.uploads.name,
                "CHAT_UPLOAD_MAX_BYTES": 4096,
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

    def operator(self, callsign, *, admin=False):
        with self.app.app_context():
            user = User(
                username=callsign,
                password_hash=generate_password_hash("secure-passphrase"),
                is_admin=admin,
            )
            db.session.add(user)
            db.session.commit()
        client = self.app.test_client()
        response = client.post(
            "/login",
            data={"username": callsign, "password": "secure-passphrase"},
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        return client

    def conversation(self, conversation_type):
        with self.app.app_context():
            return db.session.scalar(
                db.select(Conversation).where(Conversation.type == conversation_type)
            )

    def test_direct_signal_is_realtime_private_and_resolves_on_read(self):
        alpha = self.operator("SIGNAL_ALPHA")
        bravo = self.operator("SIGNAL_BRAVO")
        outsider = self.operator("SIGNAL_OUTSIDER")
        alpha.post("/chat/conversations", data={"callsigns": "SIGNAL_BRAVO"})
        direct = self.conversation("direct")
        alpha_socket = socketio.test_client(self.app, flask_test_client=alpha)
        bravo_socket = socketio.test_client(self.app, flask_test_client=bravo)
        outsider_socket = socketio.test_client(self.app, flask_test_client=outsider)
        alpha_socket.get_received()
        bravo_socket.get_received()
        outsider_socket.get_received()

        alpha_socket.emit(
            "send_message",
            {"conversation_id": direct.id, "message": "Private action required"},
        )
        bravo_events = bravo_socket.get_received()
        self.assertIn("signal_queue_updated", [event["name"] for event in bravo_events])
        self.assertNotIn(
            "signal_queue_updated",
            [event["name"] for event in outsider_socket.get_received()],
        )
        queue = bravo.get("/signals")
        self.assertIn(b"DIRECT", queue.data)
        self.assertIn(b"SIGNAL_ALPHA", queue.data)
        self.assertNotIn(b"Private action required", outsider.get("/signals").data)

        message_id = next(
            event["args"][0]["id"]
            for event in bravo_events
            if event["name"] == "receive_message"
        )
        bravo_socket.emit(
            "mark_read",
            {"conversation_id": direct.id, "message_id": message_id},
        )
        self.assertNotIn(b"DIRECT", bravo.get("/signals").data)

    def test_grid_activity_and_blocked_directs_do_not_create_signals(self):
        alpha = self.operator("QUIET_ALPHA")
        bravo = self.operator("QUIET_BRAVO")
        alpha_socket = socketio.test_client(self.app, flask_test_client=alpha)
        bravo_socket = socketio.test_client(self.app, flask_test_client=bravo)
        grid = self.conversation("grid")
        alpha_socket.emit(
            "send_message",
            {"conversation_id": grid.id, "message": "Grid traffic"},
        )
        self.assertIn(b"NO ACTIVE SIGNALS", bravo.get("/signals").data)

        alpha.post("/chat/conversations", data={"callsigns": "QUIET_BRAVO"})
        direct = self.conversation("direct")
        with self.app.app_context():
            alpha_user = db.session.scalar(db.select(User).where(User.username == "QUIET_ALPHA"))
            bravo_user = db.session.scalar(db.select(User).where(User.username == "QUIET_BRAVO"))
            db.session.add(UserBlock(blocker_id=bravo_user.id, blocked_id=alpha_user.id))
            db.session.commit()
        alpha_socket.emit(
            "send_message",
            {"conversation_id": direct.id, "message": "Blocked traffic"},
        )
        self.assertIn(b"NO ACTIVE SIGNALS", bravo.get("/signals").data)

    def test_group_access_signal_resolves_on_open_or_authorized_dismiss(self):
        alpha = self.operator("GROUP_SIGNAL_ALPHA")
        bravo = self.operator("GROUP_SIGNAL_BRAVO")
        charlie = self.operator("GROUP_SIGNAL_CHARLIE")
        outsider = self.operator("GROUP_SIGNAL_OUTSIDER")
        alpha.post(
            "/chat/conversations",
            data={
                "callsigns": "GROUP_SIGNAL_BRAVO,GROUP_SIGNAL_CHARLIE",
                "group_name": "Signal Review",
            },
        )
        group = self.conversation("group")
        self.assertIn(b"GROUP ACCESS", bravo.get("/signals").data)
        bravo.get(f"/chat?conversation={group.id}")
        self.assertNotIn(b"GROUP ACCESS", bravo.get("/signals").data)

        with self.app.app_context():
            signal = db.session.scalar(
                db.select(OperatorSignal).where(
                    OperatorSignal.recipient.has(username="GROUP_SIGNAL_CHARLIE")
                )
            )
            signal_id = signal.id
        self.assertEqual(outsider.post(f"/signals/{signal_id}/dismiss").status_code, 403)
        self.assertEqual(charlie.post(f"/signals/{signal_id}/dismiss").status_code, 302)

    def test_file_signal_waits_for_explicit_preview_or_download(self):
        alpha = self.operator("FILE_SIGNAL_ALPHA")
        bravo = self.operator("FILE_SIGNAL_BRAVO")
        alpha.post("/chat/conversations", data={"callsigns": "FILE_SIGNAL_BRAVO"})
        direct = self.conversation("direct")
        upload = alpha.post(
            f"/chat/conversations/{direct.id}/attachments",
            data={"file": (io.BytesIO(b"review me"), "brief.txt")},
            content_type="multipart/form-data",
        )
        self.assertEqual(upload.status_code, 201)
        attachment = upload.get_json()["message"]["attachment"]
        self.assertIn(b"FILE TRANSFER", bravo.get("/signals").data)
        bravo.get(attachment["metadata_url"])
        self.assertIn(b"FILE TRANSFER", bravo.get("/signals").data)
        bravo.get(f'{attachment["preview_url"]}?inline=1')
        self.assertIn(b"FILE TRANSFER", bravo.get("/signals").data)
        bravo.get(attachment["preview_url"])
        self.assertNotIn(b"FILE TRANSFER", bravo.get("/signals").data)
        with self.app.app_context():
            self.assertEqual(db.session.scalar(db.select(db.func.count(AttachmentOpen.user_id))), 1)

    def test_report_signal_is_admin_only_and_review_state_is_durable(self):
        reporter = self.operator("REPORT_SIGNAL")
        self.operator("REPORT_TARGET")
        admin = self.operator("REPORT_ADMIN", admin=True)
        second_admin = self.operator("REPORT_ADMIN_TWO", admin=True)
        admin_socket = socketio.test_client(self.app, flask_test_client=admin)
        second_admin_socket = socketio.test_client(
            self.app,
            flask_test_client=second_admin,
        )
        admin_socket.get_received()
        second_admin_socket.get_received()
        reporter.post(
            "/operators/REPORT_TARGET/report",
            data={"category": "Spam", "explanation": "Repeated unwanted contact."},
        )
        self.assertIn(
            "signal_queue_updated",
            [event["name"] for event in admin_socket.get_received()],
        )
        self.assertIn(
            "signal_queue_updated",
            [event["name"] for event in second_admin_socket.get_received()],
        )
        self.assertNotIn(b"administrator review", reporter.get("/signals").data)
        admin_queue = admin.get("/signals")
        self.assertIn(b"administrator review", admin_queue.data)
        with self.app.app_context():
            report_id = db.session.scalar(db.select(UserReport.id))
        self.assertEqual(
            reporter.post(f"/signals/reports/{report_id}/review").status_code,
            403,
        )
        self.assertEqual(admin.post(f"/signals/reports/{report_id}/review").status_code, 302)
        self.assertIn(
            "signal_queue_updated",
            [event["name"] for event in admin_socket.get_received()],
        )
        self.assertIn(
            "signal_queue_updated",
            [event["name"] for event in second_admin_socket.get_received()],
        )
        reviewed_queue = admin.get("/signals")
        self.assertIn(b"NO ACTIVE SIGNALS", reviewed_queue.data)
        self.assertNotIn(b"requires administrator review", reviewed_queue.data)
        with self.app.app_context():
            report = db.session.get(UserReport, report_id)
            self.assertIsNotNone(report.reviewed_at)
            self.assertEqual(report.reviewed_by.username, "REPORT_ADMIN")


class SignalQueueCsrfTestCase(unittest.TestCase):
    def test_signal_mutation_requires_csrf(self):
        app = create_app(
            {
                "TESTING": True,
                "SECRET_KEY": "signal-csrf-key",
                "SQLALCHEMY_DATABASE_URI": "sqlite://",
                "WTF_CSRF_ENABLED": True,
            }
        )
        with app.app_context():
            user = User(
                username="SIGNAL_CSRF",
                password_hash=generate_password_hash("password"),
            )
            db.session.add(user)
            db.session.flush()
            signal = OperatorSignal(recipient=user, signal_type="SYSTEM", description="Review")
            db.session.add(signal)
            db.session.commit()
            user_id = user.id
            signal_id = signal.id
        client = app.test_client()
        with client.session_transaction() as session:
            session["_user_id"] = str(user_id)
            session["_fresh"] = True
            session["auth_version"] = 0
        self.assertEqual(client.post(f"/signals/{signal_id}/dismiss").status_code, 400)
        with app.app_context():
            db.session.remove()
            db.drop_all()


if __name__ == "__main__":
    unittest.main()
