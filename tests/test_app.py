import unittest

from gridvault import create_app
from gridvault.extensions import db, socketio
from gridvault.models import Message, User
from gridvault.realtime import connected_users, message_receipts, sid_to_user_id


class GridVaultTestCase(unittest.TestCase):
    def setUp(self):
        self.app = create_app(
            {
                "TESTING": True,
                "SECRET_KEY": "test-only-key",
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

    def register(self, callsign="VEGA_7", password="secure-passphrase"):
        return self.client.post(
            "/register",
            data={
                "username": callsign,
                "password": password,
                "confirm_password": password,
            },
            follow_redirects=True,
        )

    def test_mission_console_requires_authentication(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login", response.headers["Location"])

    def test_registration_lands_on_console_and_hashes_password(self):
        response = self.register()
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Mission Console", response.data)
        self.assertIn(b"VEGA_7", response.data)

        with self.app.app_context():
            user = db.session.scalar(db.select(User).where(User.username == "VEGA_7"))
            self.assertIsNotNone(user)
            self.assertNotEqual(user.password_hash, "secure-passphrase")

    def test_existing_operator_can_log_in(self):
        self.register("ORBIT_2")
        self.client.post("/logout")

        response = self.client.post(
            "/login",
            data={"username": "orbit_2", "password": "secure-passphrase"},
            follow_redirects=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Good to see you", response.data)

    def test_all_console_modules_are_authenticated_and_available(self):
        self.register()
        paths = (
            "/hub",
            "/chat",
            "/design-lab",
            "/engineering-bay",
            "/project-vault",
            "/briefing-room",
            "/archive",
            "/settings",
        )

        for path in paths:
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200)
                self.assertIn(b"GridVault", response.data)

    def test_hub_socket_message_is_broadcast_and_persisted(self):
        self.register()
        socket_client = socketio.test_client(
            self.app,
            flask_test_client=self.client,
        )
        self.assertTrue(socket_client.is_connected())

        initial_events = socket_client.get_received()
        self.assertIn("online_users", [event["name"] for event in initial_events])

        socket_client.emit("send_message", {"message": "Mission clock synchronized."})
        events = socket_client.get_received()
        self.assertIn("receive_message", [event["name"] for event in events])

        with self.app.app_context():
            message = db.session.scalar(db.select(Message))
            self.assertEqual(message.body, "Mission clock synchronized.")

        response = self.client.get("/hub")
        self.assertIn(b"Mission clock synchronized.", response.data)
        socket_client.disconnect()

    def test_security_headers_are_present(self):
        response = self.client.get("/login")
        self.assertEqual(response.headers["X-Frame-Options"], "DENY")
        self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")
        self.assertIn("default-src 'self'", response.headers["Content-Security-Policy"])


if __name__ == "__main__":
    unittest.main()
