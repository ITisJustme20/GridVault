import unittest

from werkzeug.security import generate_password_hash

from gridvault import create_app
from gridvault.extensions import db, socketio
from gridvault.models import Conversation, ConversationMember, Message, User, UserBlock, UserReport
from gridvault.realtime import connected_users, message_receipts, sid_to_user_id


class ProfileTrustTestCase(unittest.TestCase):
    def setUp(self):
        self.app = create_app(
            {
                "TESTING": True,
                "SECRET_KEY": "profile-trust-test-key",
                "SQLALCHEMY_DATABASE_URI": "sqlite://",
                "WTF_CSRF_ENABLED": False,
            }
        )
        self.clients = {}

    def tearDown(self):
        connected_users.clear()
        sid_to_user_id.clear()
        message_receipts.clear()
        with self.app.app_context():
            db.session.remove()
            db.drop_all()

    def add_operator(self, callsign, *, admin=False):
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
        self.clients[callsign] = client
        return client

    def conversation(self, conversation_type, *, name=None):
        with self.app.app_context():
            query = db.select(Conversation).where(Conversation.type == conversation_type)
            if name is not None:
                query = query.where(Conversation.name == name)
            return db.session.execute(query).scalars().first()

    def test_operator_edits_only_own_profile(self):
        alpha = self.add_operator("PROFILE_ALPHA")
        self.add_operator("PROFILE_BRAVO")

        response = alpha.post(
            "/profile/edit",
            data={
                "specialty": "Engineering",
                "status_text": "Testing the control surface.",
                "username": "CHANGED_CALLSIGN",
            },
            follow_redirects=True,
        )
        self.assertIn(b"Engineering", response.data)
        self.assertIn(b"Testing the control surface", response.data)
        self.assertEqual(alpha.post("/operators/PROFILE_BRAVO/edit", data={}).status_code, 404)
        with self.app.app_context():
            alpha_user = db.session.scalar(db.select(User).where(User.username == "PROFILE_ALPHA"))
            bravo_user = db.session.scalar(db.select(User).where(User.username == "PROFILE_BRAVO"))
            self.assertEqual(alpha_user.specialty, "Engineering")
            self.assertEqual(alpha_user.status_text, "Testing the control surface.")
            self.assertIsNone(bravo_user.specialty)
            self.assertIsNone(db.session.scalar(db.select(User).where(User.username == "CHANGED_CALLSIGN")))

    def test_shared_groups_are_calculated_from_mutual_membership(self):
        alpha = self.add_operator("GROUP_ALPHA")
        self.add_operator("GROUP_BRAVO")
        self.add_operator("GROUP_CHARLIE")
        alpha.post(
            "/chat/conversations",
            data={"callsigns": "GROUP_BRAVO", "group_name": "Ignored direct"},
        )
        alpha.post(
            "/chat/conversations",
            data={"callsigns": "GROUP_BRAVO,GROUP_CHARLIE", "group_name": "Mutual Review"},
        )
        alpha.post(
            "/chat/conversations",
            data={"callsigns": "GROUP_CHARLIE,GROUP_ALPHA_EXTRA", "group_name": "Invalid"},
        )
        # Add a real group that BRAVO does not share, without exposing it through profile logic.
        with self.app.app_context():
            alpha_user = db.session.scalar(db.select(User).where(User.username == "GROUP_ALPHA"))
            charlie = db.session.scalar(db.select(User).where(User.username == "GROUP_CHARLIE"))
            private_group = Conversation(type="group", name="Alpha Charlie Private", creator=alpha_user)
            private_group.memberships = [
                ConversationMember(user=alpha_user),
                ConversationMember(user=charlie),
            ]
            db.session.add(private_group)
            db.session.commit()

        response = alpha.get("/operators/GROUP_BRAVO")
        self.assertIn(b"Mutual Review", response.data)
        self.assertNotIn(b"Alpha Charlie Private", response.data)
        self.assertNotIn(b"direct", response.data.lower())

    def test_blocking_disables_direct_but_preserves_grid_and_groups(self):
        alpha = self.add_operator("BLOCK_ALPHA")
        bravo = self.add_operator("BLOCK_BRAVO")
        self.add_operator("BLOCK_CHARLIE")
        alpha.post("/chat/conversations", data={"callsigns": "BLOCK_BRAVO"})
        alpha.post(
            "/chat/conversations",
            data={"callsigns": "BLOCK_BRAVO,BLOCK_CHARLIE", "group_name": "Shared Operations"},
        )
        direct = self.conversation("direct")
        group = self.conversation("group", name="Shared Operations")
        grid = self.conversation("grid")
        alpha_socket = socketio.test_client(self.app, flask_test_client=alpha)
        bravo_socket = socketio.test_client(self.app, flask_test_client=bravo)
        alpha_socket.get_received()
        bravo_socket.get_received()

        blocked = alpha.post("/operators/BLOCK_BRAVO/block", follow_redirects=True)
        self.assertIn(b"Operator blocked", blocked.data)
        alpha_presence = next(
            event for event in alpha_socket.get_received() if event["name"] == "online_users"
        )
        bravo_presence = next(
            event for event in bravo_socket.get_received() if event["name"] == "online_users"
        )
        self.assertNotIn("BLOCK_BRAVO", alpha_presence["args"][0]["users"])
        self.assertNotIn("BLOCK_ALPHA", bravo_presence["args"][0]["users"])
        with self.app.app_context():
            self.assertEqual(db.session.scalar(db.select(db.func.count(UserBlock.blocker_id))), 1)
            direct_message_count = db.session.scalar(
                db.select(db.func.count(Message.id)).where(Message.conversation_id == direct.id)
            )

        self.assertEqual(alpha.get(f"/chat?conversation={direct.id}").status_code, 403)
        self.assertEqual(bravo.get(f"/chat?conversation={direct.id}").status_code, 403)
        self.assertNotIn(
            f'data-conversation-link="{direct.id}"'.encode(),
            alpha.get("/chat").data,
        )
        retry = bravo.post(
            "/chat/conversations",
            data={"callsigns": "BLOCK_ALPHA"},
            follow_redirects=True,
        )
        self.assertIn(b"Direct conversation is unavailable", retry.data)
        alpha_socket.emit(
            "send_message",
            {"conversation_id": direct.id, "message": "Blocked direct"},
        )
        self.assertIn("conversation_error", [event["name"] for event in alpha_socket.get_received()])
        alpha_socket.emit("typing", {"conversation_id": direct.id})
        self.assertNotIn("user_typing", [event["name"] for event in bravo_socket.get_received()])

        self.assertEqual(alpha.get(f"/chat?conversation={group.id}").status_code, 200)
        alpha_socket.emit(
            "send_message",
            {"conversation_id": group.id, "message": "Group remains available"},
        )
        self.assertIn("receive_message", [event["name"] for event in bravo_socket.get_received()])
        alpha_socket.emit(
            "send_message",
            {"conversation_id": grid.id, "message": "Grid remains available"},
        )
        self.assertIn("receive_message", [event["name"] for event in bravo_socket.get_received()])
        with self.app.app_context():
            self.assertEqual(
                db.session.scalar(
                    db.select(db.func.count(Message.id)).where(Message.conversation_id == direct.id)
                ),
                direct_message_count,
            )

        alpha.post("/operators/BLOCK_BRAVO/unblock")
        self.assertEqual(alpha.get(f"/chat?conversation={direct.id}").status_code, 200)
        alpha_socket.disconnect()
        bravo_socket.disconnect()

    def test_reports_are_private_to_administrators(self):
        reporter = self.add_operator("REPORTER")
        self.add_operator("REPORTED")
        admin = self.add_operator("TRUST_ADMIN", admin=True)
        submitted = reporter.post(
            "/operators/REPORTED/report",
            data={
                "category": "Spam",
                "explanation": "Repeated unsolicited Direct messages.",
            },
            follow_redirects=True,
        )
        self.assertIn(b"Report submitted", submitted.data)
        self.assertEqual(reporter.get("/access-control").status_code, 403)
        self.assertEqual(
            reporter.post(
                "/access-control/operators/REPORTED/suspend",
                data={"reason": "Unauthorized attempt"},
            ).status_code,
            403,
        )
        ordinary_profile = reporter.get("/operators/REPORTED")
        self.assertNotIn(b"Repeated unsolicited", ordinary_profile.data)
        admin_view = admin.get("/access-control")
        self.assertIn(b"Repeated unsolicited Direct messages", admin_view.data)
        self.assertIn(b"REPORTER", admin_view.data)
        with self.app.app_context():
            report = db.session.scalar(db.select(UserReport))
            self.assertEqual(report.category, "Spam")

    def test_administrator_suspends_disconnects_and_reactivates(self):
        admin = self.add_operator("SUSPEND_ADMIN", admin=True)
        operator = self.add_operator("SUSPEND_TARGET")
        operator_socket = socketio.test_client(self.app, flask_test_client=operator)
        self.assertTrue(operator_socket.is_connected())

        response = admin.post(
            "/access-control/operators/SUSPEND_TARGET/suspend",
            data={"reason": "Repeated security policy violations."},
            follow_redirects=True,
        )
        self.assertIn(b"SUSPEND_TARGET suspended", response.data)
        self.assertFalse(operator_socket.is_connected())
        self.assertIn("/login", operator.get("/mission-console").headers["Location"])
        rejected_login = operator.post(
            "/login",
            data={"username": "SUSPEND_TARGET", "password": "secure-passphrase"},
        )
        self.assertEqual(rejected_login.status_code, 403)
        self.assertIn(b"Account access is unavailable", rejected_login.data)

        admin.post(
            "/access-control/operators/SUSPEND_TARGET/reactivate",
            follow_redirects=True,
        )
        # The pre-suspension session remains invalid after reactivation.
        self.assertIn("/login", operator.get("/mission-console").headers["Location"])
        restored = operator.post(
            "/login",
            data={"username": "SUSPEND_TARGET", "password": "secure-passphrase"},
            follow_redirects=True,
        )
        self.assertIn(b"Mission Console", restored.data)
        with self.app.app_context():
            target = db.session.scalar(db.select(User).where(User.username == "SUSPEND_TARGET"))
            self.assertEqual(target.account_state, "Active")
            self.assertEqual(target.auth_version, 1)
            self.assertIsNone(target.suspension_reason)

    def test_profile_and_trust_forms_require_csrf(self):
        alpha = self.add_operator("CSRF_ALPHA")
        self.add_operator("CSRF_BRAVO")
        self.app.config["WTF_CSRF_ENABLED"] = True
        self.assertEqual(
            alpha.post("/profile/edit", data={"specialty": "Design"}).status_code,
            400,
        )
        self.assertEqual(alpha.post("/operators/CSRF_BRAVO/block").status_code, 400)
        self.assertEqual(
            alpha.post(
                "/operators/CSRF_BRAVO/report",
                data={"category": "Spam", "explanation": "No token"},
            ).status_code,
            400,
        )


if __name__ == "__main__":
    unittest.main()
