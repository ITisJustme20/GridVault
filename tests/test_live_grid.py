import io
import tempfile
import unittest

from werkzeug.security import generate_password_hash

from gridvault import create_app
from gridvault.extensions import db, socketio
from gridvault.models import Conversation, User
from gridvault.realtime import (
    connected_users,
    message_receipts,
    recent_grid_activity,
    record_grid_activity,
    sid_to_user_id,
)


class LiveGridTestCase(unittest.TestCase):
    def setUp(self):
        self.private_files = tempfile.TemporaryDirectory()
        self.app = create_app(
            {
                "TESTING": True,
                "SECRET_KEY": "live-grid-test-key",
                "SQLALCHEMY_DATABASE_URI": "sqlite://",
                "WTF_CSRF_ENABLED": False,
                "CHAT_UPLOAD_FOLDER": self.private_files.name,
            }
        )
        self.clients = {}
        recent_grid_activity.clear()

    def tearDown(self):
        connected_users.clear()
        sid_to_user_id.clear()
        message_receipts.clear()
        recent_grid_activity.clear()
        with self.app.app_context():
            db.session.remove()
            db.drop_all()
        self.private_files.cleanup()

    def add_operator(self, callsign, *, admin=False):
        with self.app.app_context():
            db.session.add(
                User(
                    username=callsign,
                    password_hash=generate_password_hash("secure-passphrase"),
                    is_admin=admin,
                )
            )
            db.session.commit()
        client = self.app.test_client()
        response = client.post(
            "/login",
            data={"username": callsign, "password": "secure-passphrase"},
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        self.clients[callsign] = client
        return client

    @staticmethod
    def event_payload(events, name):
        matches = [event for event in events if event["name"] == name]
        return matches[-1]["args"][0] if matches else None

    def test_live_grid_requires_authentication_and_links_existing_sectors(self):
        anonymous = self.app.test_client()
        response = anonymous.get("/live-grid")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login", response.headers["Location"])

        client = self.add_operator("MAP_ALPHA")
        response = client.get("/live-grid")
        self.assertEqual(response.status_code, 200)
        for label in (b"GRID", b"DIRECT", b"GROUPS", b"VC BOARD", b"FILE VAULT", b"ACCESS"):
            self.assertIn(label, response.data)
        self.assertIn(b"/chat?area=direct", response.data)
        self.assertIn(b"/chat?area=groups", response.data)
        self.assertIn(b"/design-lab", response.data)
        self.assertIn(b"/operators/MAP_ALPHA", response.data)
        self.assertNotIn(b"Access Control</a>", response.data)

    def test_presence_privacy_multiple_tabs_and_suspension(self):
        alpha = self.add_operator("PRESENCE_ALPHA")
        bravo = self.add_operator("PRESENCE_BRAVO")
        admin = self.add_operator("PRESENCE_ADMIN", admin=True)
        alpha_first = socketio.test_client(self.app, flask_test_client=alpha)
        alpha_second = socketio.test_client(self.app, flask_test_client=alpha)
        bravo_socket = socketio.test_client(self.app, flask_test_client=bravo)
        alpha_first.get_received()
        alpha_second.get_received()
        bravo_socket.get_received()

        alpha_first.emit("presence_sector", {"sector": "GRID"})
        alpha_second.emit("presence_sector", {"sector": "VC BOARD"})
        bravo_socket.emit("live_grid_subscribe")
        private_state = self.event_payload(bravo_socket.get_received(), "live_grid_state")
        alpha_nodes = [item for item in private_state["operators"] if item["callsign"] == "PRESENCE_ALPHA"]
        self.assertEqual(alpha_nodes, [{"callsign": "PRESENCE_ALPHA", "sector": "ACTIVE"}])

        alpha.post(
            "/live-grid/presence-visibility",
            data={"presence_visibility": "Sector", "user_id": "2"},
        )
        bravo_socket.get_received()
        bravo_socket.emit("live_grid_subscribe")
        sector_state = self.event_payload(bravo_socket.get_received(), "live_grid_state")
        alpha_nodes = [item for item in sector_state["operators"] if item["callsign"] == "PRESENCE_ALPHA"]
        self.assertEqual(alpha_nodes, [{"callsign": "PRESENCE_ALPHA", "sector": "VC BOARD"}])
        with self.app.app_context():
            alpha_user = db.session.scalar(db.select(User).where(User.username == "PRESENCE_ALPHA"))
            bravo_user = db.session.scalar(db.select(User).where(User.username == "PRESENCE_BRAVO"))
            self.assertEqual(alpha_user.presence_visibility, "Sector")
            self.assertEqual(bravo_user.presence_visibility, "Active")

        alpha_first.emit("presence_sector", {"sector": "DIRECT:PRIVATE"})
        self.assertIsNotNone(self.event_payload(alpha_first.get_received(), "presence_error"))

        admin.post(
            "/access-control/operators/PRESENCE_ALPHA/suspend",
            data={"reason": "Focused Live Grid suspension test."},
        )
        self.assertFalse(alpha_first.is_connected())
        self.assertFalse(alpha_second.is_connected())
        bravo_socket.get_received()
        bravo_socket.emit("live_grid_subscribe")
        suspended_state = self.event_payload(bravo_socket.get_received(), "live_grid_state")
        self.assertNotIn("PRESENCE_ALPHA", [item["callsign"] for item in suspended_state["operators"]])
        bravo_socket.disconnect()

    def test_activity_pulses_are_abstract_and_private(self):
        alpha = self.add_operator("PULSE_ALPHA")
        self.add_operator("PULSE_BRAVO")
        self.add_operator("PULSE_CHARLIE")
        observer = self.add_operator("PULSE_OBSERVER")
        alpha.post("/chat/conversations", data={"callsigns": "PULSE_BRAVO"})
        alpha.post(
            "/chat/conversations",
            data={"callsigns": "PULSE_BRAVO,PULSE_CHARLIE", "group_name": "SECRET GROUP NAME"},
        )
        with self.app.app_context():
            direct = db.session.scalar(db.select(Conversation).where(Conversation.type == "direct"))
            group = db.session.scalar(db.select(Conversation).where(Conversation.type == "group"))

        alpha_socket = socketio.test_client(self.app, flask_test_client=alpha)
        observer_socket = socketio.test_client(self.app, flask_test_client=observer)
        alpha_socket.get_received()
        observer_socket.get_received()
        observer_socket.emit("live_grid_subscribe")
        observer_socket.get_received()

        alpha_socket.emit(
            "send_message",
            {"conversation_id": direct.id, "message": "PRIVATE DIRECT TEXT"},
        )
        alpha_socket.emit(
            "send_message",
            {"conversation_id": group.id, "message": "PRIVATE GROUP TEXT"},
        )
        pulse_events = [
            event["args"][0]
            for event in observer_socket.get_received()
            if event["name"] == "live_grid_pulse"
        ]
        self.assertIn("DIRECT", [item["sector"] for item in pulse_events])
        self.assertIn("GROUPS", [item["sector"] for item in pulse_events])

        upload = alpha.post(
            f"/chat/conversations/{direct.id}/attachments",
            data={"file": (io.BytesIO(b"private file contents"), "PRIVATE-FILENAME.txt")},
            content_type="multipart/form-data",
        )
        self.assertEqual(upload.status_code, 201)
        file_pulse = self.event_payload(observer_socket.get_received(), "live_grid_pulse")
        self.assertEqual(file_pulse["type"], "FILE TRANSFER")
        self.assertEqual(file_pulse["sector"], "FILE VAULT")

        with self.app.app_context():
            record_grid_activity("BOARD UPDATE", "VC BOARD")
        board_pulse = self.event_payload(observer_socket.get_received(), "live_grid_pulse")
        self.assertEqual(board_pulse["type"], "BOARD UPDATE")
        self.assertEqual(set(board_pulse), {"id", "type", "sector", "created_at"})

        serialized = repr(pulse_events + [file_pulse, board_pulse])
        for private_value in (
            "PULSE_ALPHA",
            "PULSE_BRAVO",
            "SECRET GROUP NAME",
            "PRIVATE DIRECT TEXT",
            "PRIVATE GROUP TEXT",
            "PRIVATE-FILENAME.txt",
        ):
            self.assertNotIn(private_value, serialized)
        alpha_socket.disconnect()
        observer_socket.disconnect()

    def test_presence_preference_requires_csrf(self):
        client = self.add_operator("PRESENCE_CSRF")
        self.app.config["WTF_CSRF_ENABLED"] = True
        response = client.post(
            "/live-grid/presence-visibility",
            data={"presence_visibility": "Sector"},
        )
        self.assertEqual(response.status_code, 400)


if __name__ == "__main__":
    unittest.main()
