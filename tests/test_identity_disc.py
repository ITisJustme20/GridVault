import re
import unittest

from werkzeug.security import generate_password_hash

from gridvault import create_app
from gridvault.extensions import db, socketio
from gridvault.identity_disc import identity_disc_for_user
from gridvault.models import User
from gridvault.realtime import (
    connected_users,
    message_receipts,
    recent_grid_activity,
    sid_to_user_id,
)


class IdentityDiscTestCase(unittest.TestCase):
    disc_secret = "identity-disc-test-secret-0123456789abcdef"

    def setUp(self):
        self.app = create_app(
            {
                "TESTING": True,
                "SECRET_KEY": "identity-disc-session-test-key",
                "IDENTITY_DISC_SECRET": self.disc_secret,
                "SQLALCHEMY_DATABASE_URI": "sqlite://",
                "WTF_CSRF_ENABLED": False,
            }
        )

    def tearDown(self):
        connected_users.clear()
        sid_to_user_id.clear()
        message_receipts.clear()
        recent_grid_activity.clear()
        with self.app.app_context():
            db.session.remove()
            db.drop_all()

    def add_operator(self, callsign, *, state="Active"):
        with self.app.app_context():
            user = User(
                username=callsign,
                password_hash=generate_password_hash("secure-passphrase"),
                account_state=state,
            )
            db.session.add(user)
            db.session.commit()
            return user.id

    def login(self, callsign):
        client = self.app.test_client()
        response = client.post(
            "/login",
            data={"username": callsign, "password": "secure-passphrase"},
            follow_redirects=True,
        )
        return client, response

    def disc_for(self, user_id):
        with self.app.app_context():
            return identity_disc_for_user(db.session.get(User, user_id))

    def test_disc_is_stable_unique_and_human_readable(self):
        alpha_id = self.add_operator("DISC_ALPHA")
        bravo_id = self.add_operator("DISC_BRAVO")
        alpha_first = self.disc_for(alpha_id)
        alpha_second = self.disc_for(alpha_id)
        bravo = self.disc_for(bravo_id)

        self.assertEqual(alpha_first, alpha_second)
        self.assertNotEqual(alpha_first, bravo)
        self.assertRegex(alpha_first["code"], r"^[0-9A-F]{4}(?:-[0-9A-F]{4}){2}$")
        self.assertEqual(
            set(alpha_first["visual"]),
            {
                "version",
                "accent",
                "outer_rotation",
                "outer_dash",
                "middle_rotation",
                "middle_dash",
                "inner_rotation",
                "inner_dash",
                "core_rotation",
                "circuit_rotation",
                "spokes",
            },
        )

    def test_profile_and_presence_edits_do_not_change_identity(self):
        alpha_id = self.add_operator("DISC_EDIT_ALPHA")
        client, login_response = self.login("DISC_EDIT_ALPHA")
        self.assertEqual(login_response.status_code, 200)
        before = self.disc_for(alpha_id)

        profile_response = client.post(
            "/profile/edit",
            data={"specialty": "Engineering", "status_text": "Systems ready."},
            follow_redirects=True,
        )
        self.assertEqual(profile_response.status_code, 200)
        presence_response = client.post(
            "/live-grid/presence-visibility",
            data={"presence_visibility": "Sector"},
            follow_redirects=True,
        )
        self.assertEqual(presence_response.status_code, 200)
        self.assertEqual(before, self.disc_for(alpha_id))

    def test_profile_renders_same_safe_identity_for_authorized_viewers(self):
        alpha_id = self.add_operator("DISC_VIEW_ALPHA")
        self.add_operator("DISC_VIEW_BRAVO")
        alpha, _ = self.login("DISC_VIEW_ALPHA")
        bravo, _ = self.login("DISC_VIEW_BRAVO")
        disc = self.disc_for(alpha_id)

        own_html = alpha.get("/operators/DISC_VIEW_ALPHA").get_data(as_text=True)
        viewer_html = bravo.get("/operators/DISC_VIEW_ALPHA").get_data(as_text=True)
        for html in (own_html, viewer_html):
            self.assertIn("IDENTITY DISC", html)
            self.assertIn("IDENTITY REFERENCE ONLY", html)
            self.assertIn(disc["code"], html)
            self.assertIn("data-identity-disc", html)
            self.assertNotIn(self.disc_secret, html)
            self.assertNotIn("password_hash", html)
            self.assertNotIn("auth_version", html)
            self.assertNotIn("invitation", html.lower())

        bravo.post("/operators/DISC_VIEW_ALPHA/block")
        blocked_html = bravo.get("/operators/DISC_VIEW_ALPHA")
        self.assertEqual(blocked_html.status_code, 200)
        self.assertIn(disc["code"].encode(), blocked_html.data)

    def test_live_grid_sends_only_public_disc_parameters(self):
        alpha_id = self.add_operator("DISC_GRID_ALPHA")
        self.add_operator("DISC_GRID_BRAVO")
        alpha, _ = self.login("DISC_GRID_ALPHA")
        bravo, _ = self.login("DISC_GRID_BRAVO")
        alpha_socket = socketio.test_client(self.app, flask_test_client=alpha)
        bravo_socket = socketio.test_client(self.app, flask_test_client=bravo)
        bravo_socket.get_received()
        bravo_socket.emit("live_grid_subscribe")
        state = next(
            event["args"][0]
            for event in bravo_socket.get_received()
            if event["name"] == "live_grid_state"
        )
        alpha_node = next(
            item for item in state["operators"] if item["callsign"] == "DISC_GRID_ALPHA"
        )
        expected = self.disc_for(alpha_id)
        self.assertEqual(alpha_node["disc"], expected["visual"])
        serialized = repr(alpha_node)
        self.assertNotIn(expected["code"], serialized)
        self.assertNotIn(self.disc_secret, serialized)
        self.assertNotIn("user_id", serialized)
        alpha_socket.disconnect()
        bravo_socket.disconnect()

    def test_suspended_operator_cannot_access_identity_profile(self):
        self.add_operator("DISC_SUSPENDED", state="Suspended")
        client, response = self.login("DISC_SUSPENDED")
        self.assertEqual(response.status_code, 403)
        protected = client.get("/operators/DISC_SUSPENDED")
        self.assertEqual(protected.status_code, 302)
        self.assertTrue(re.search(r"/login", protected.headers["Location"]))


if __name__ == "__main__":
    unittest.main()
