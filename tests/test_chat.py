import tempfile
import unittest
from pathlib import Path

from sqlalchemy import create_engine, text
from werkzeug.security import generate_password_hash

from gridvault import create_app
from gridvault.extensions import db, socketio
from gridvault.models import Conversation, ConversationMember, Message, User
from gridvault.realtime import connected_users, message_receipts, sid_to_user_id


class ChatTestCase(unittest.TestCase):
    def setUp(self):
        self.app = create_app(
            {
                "TESTING": True,
                "SECRET_KEY": "chat-test-key",
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

    def register(self, callsign):
        client = self.app.test_client()
        response = client.post(
            "/register",
            data={
                "username": callsign,
                "password": "secure-passphrase",
                "confirm_password": "secure-passphrase",
            },
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        self.clients[callsign] = client
        return client

    def conversation(self, conversation_type):
        with self.app.app_context():
            return db.session.execute(
                db.select(Conversation).where(Conversation.type == conversation_type)
            ).scalars().first()

    def test_grid_and_legacy_history_are_preserved(self):
        client = self.register("GRID_ONE")
        grid = self.conversation("grid")
        with self.app.app_context():
            user = db.session.scalar(
                db.select(User).where(User.username == "GRID_ONE")
            )
            db.session.add(
                Message(
                    body="Preserved Grid history",
                    user_id=user.id,
                    conversation_id=grid.id,
                )
            )
            db.session.commit()
        response = client.get("/chat")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Preserved Grid history", response.data)
        self.assertIn(b">GRID<", response.data)

    def test_one_callsign_opens_one_unique_direct_conversation(self):
        alpha = self.register("ALPHA_ONE")
        self.register("BRAVO_TWO")
        first = alpha.post(
            "/chat/conversations",
            data={"callsigns": "BRAVO_TWO", "group_name": "Ignored"},
        )
        second = alpha.post(
            "/chat/conversations",
            data={"callsigns": "bravo_two"},
        )
        with self.app.app_context():
            directs = db.session.execute(
                db.select(Conversation).where(Conversation.type == "direct")
            ).scalars().all()
            self.assertEqual(len(directs), 1)
            self.assertEqual(len(directs[0].memberships), 2)
        self.assertEqual(first.headers["Location"], second.headers["Location"])

    def test_multiple_callsigns_create_private_group_and_membership_changes(self):
        alpha = self.register("GROUP_ALPHA")
        bravo = self.register("GROUP_BRAVO")
        charlie = self.register("GROUP_CHARLIE")
        outsider = self.register("GROUP_DELTA")
        response = alpha.post(
            "/chat/conversations",
            data={
                "callsigns": "GROUP_BRAVO,GROUP_CHARLIE",
                "group_name": "Launch Review",
            },
        )
        group = self.conversation("group")
        self.assertIn(f"conversation={group.id}", response.headers["Location"])
        self.assertEqual(outsider.get(f"/chat?conversation={group.id}").status_code, 403)
        self.assertEqual(
            bravo.post(
                f"/chat/conversations/{group.id}/members",
                data={"callsign": "GROUP_DELTA"},
            ).status_code,
            403,
        )
        alpha.post(
            f"/chat/conversations/{group.id}/members",
            data={"callsign": "GROUP_DELTA"},
        )
        charlie.post(f"/chat/conversations/{group.id}/leave")
        with self.app.app_context():
            refreshed = db.session.get(Conversation, group.id)
            callsigns = {item.user.username for item in refreshed.memberships}
            self.assertEqual(refreshed.type, "group")
            self.assertEqual(
                callsigns,
                {"GROUP_ALPHA", "GROUP_BRAVO", "GROUP_DELTA"},
            )

    def test_invalid_callsigns_and_self_membership_are_rejected(self):
        alpha = self.register("VALID_ALPHA")
        missing = alpha.post(
            "/chat/conversations",
            data={"callsigns": "DOES_NOT_EXIST"},
            follow_redirects=True,
        )
        self.assertIn(b"Unknown callsign", missing.data)
        self_chat = alpha.post(
            "/chat/conversations",
            data={"callsigns": "VALID_ALPHA"},
            follow_redirects=True,
        )
        self.assertIn(b"already included", self_chat.data)
        with self.app.app_context():
            self.assertEqual(
                db.session.scalar(
                    db.select(db.func.count(Conversation.id)).where(
                        Conversation.type != "grid"
                    )
                ),
                0,
            )

    def test_socket_events_are_conversation_scoped_and_unauthorized_sends_fail(self):
        alpha_client = self.register("SOCKET_ALPHA")
        bravo_client = self.register("SOCKET_BRAVO")
        charlie_client = self.register("SOCKET_CHARLIE")
        alpha_client.post(
            "/chat/conversations",
            data={"callsigns": "SOCKET_BRAVO"},
        )
        direct = self.conversation("direct")
        alpha_socket = socketio.test_client(
            self.app, flask_test_client=alpha_client
        )
        bravo_socket = socketio.test_client(
            self.app, flask_test_client=bravo_client
        )
        charlie_socket = socketio.test_client(
            self.app, flask_test_client=charlie_client
        )
        alpha_socket.get_received()
        bravo_socket.get_received()
        charlie_socket.get_received()

        alpha_socket.emit("typing", {"conversation_id": direct.id})
        self.assertIn(
            "user_typing",
            [event["name"] for event in bravo_socket.get_received()],
        )
        self.assertNotIn(
            "user_typing",
            [event["name"] for event in charlie_socket.get_received()],
        )

        alpha_socket.emit(
            "send_message",
            {
                "conversation_id": direct.id,
                "message": "Private mission detail",
                "client_id": "pending_alpha",
            },
        )
        alpha_events = alpha_socket.get_received()
        received = next(
            event for event in alpha_events if event["name"] == "receive_message"
        )
        message_id = received["args"][0]["id"]
        self.assertIn(
            "receive_message",
            [event["name"] for event in bravo_socket.get_received()],
        )
        charlie_events = charlie_socket.get_received()
        self.assertNotIn("receive_message", [event["name"] for event in charlie_events])

        bravo_socket.emit(
            "mark_read",
            {"conversation_id": direct.id, "message_id": message_id},
        )
        receipt = next(
            event
            for event in alpha_socket.get_received()
            if event["name"] == "read_receipt_update"
        )
        self.assertEqual(receipt["args"][0]["callsigns"], ["SOCKET_BRAVO"])

        with self.app.app_context():
            message_count = db.session.scalar(db.select(db.func.count(Message.id)))
        charlie_socket.emit("subscribe_conversation", direct.id)
        self.assertIn(
            "conversation_error",
            [event["name"] for event in charlie_socket.get_received()],
        )
        charlie_socket.emit(
            "send_message",
            {
                "conversation_id": direct.id,
                "message": "Unauthorized",
            },
        )
        self.assertIn(
            "conversation_error",
            [event["name"] for event in charlie_socket.get_received()],
        )
        with self.app.app_context():
            self.assertEqual(
                db.session.scalar(db.select(db.func.count(Message.id))),
                message_count,
            )
        alpha_socket.disconnect()
        bravo_socket.disconnect()
        charlie_socket.disconnect()

    def test_unread_count_appears_outside_active_conversation(self):
        alpha_client = self.register("UNREAD_ALPHA")
        bravo_client = self.register("UNREAD_BRAVO")
        alpha_client.post(
            "/chat/conversations",
            data={"callsigns": "UNREAD_BRAVO"},
        )
        direct = self.conversation("direct")
        alpha_socket = socketio.test_client(
            self.app, flask_test_client=alpha_client
        )
        alpha_socket.emit(
            "send_message",
            {
                "conversation_id": direct.id,
                "message": "Unread direct message",
            },
        )
        response = bravo_client.get("/chat")
        self.assertIn(b"UNREAD_ALPHA", response.data)
        self.assertIn(b'class="unread-count">1</strong>', response.data)
        alpha_socket.disconnect()


class ChatCsrfTestCase(unittest.TestCase):
    def test_chat_mutations_require_csrf_token(self):
        app = create_app(
            {
                "TESTING": True,
                "SECRET_KEY": "chat-csrf-key",
                "SQLALCHEMY_DATABASE_URI": "sqlite://",
                "WTF_CSRF_ENABLED": True,
            }
        )
        with app.app_context():
            user = User(
                username="CSRF_OPERATOR",
                password_hash=generate_password_hash("secure-passphrase"),
            )
            db.session.add(user)
            db.session.commit()
            user_id = user.id

        client = app.test_client()
        with client.session_transaction() as session:
            session["_user_id"] = str(user_id)
            session["_fresh"] = True
        response = client.post(
            "/chat/conversations",
            data={"callsigns": "OTHER_OPERATOR"},
        )
        self.assertEqual(response.status_code, 400)
        with app.app_context():
            db.session.remove()
            db.drop_all()


class LegacyChatUpgradeTestCase(unittest.TestCase):
    def test_additive_upgrade_links_legacy_messages_to_grid(self):
        with tempfile.TemporaryDirectory() as directory:
            database_path = Path(directory) / "legacy-chat.db"
            engine = create_engine(f"sqlite:///{database_path.as_posix()}")
            with engine.begin() as connection:
                connection.execute(text(
                    "CREATE TABLE user (id INTEGER PRIMARY KEY, username VARCHAR(30) UNIQUE NOT NULL, password_hash VARCHAR(255) NOT NULL, created_at DATETIME NOT NULL)"
                ))
                connection.execute(text(
                    "CREATE TABLE message (id INTEGER PRIMARY KEY, body VARCHAR(500) NOT NULL, created_at DATETIME NOT NULL, user_id INTEGER NOT NULL REFERENCES user(id))"
                ))
                connection.execute(text(
                    "INSERT INTO user VALUES (1, 'LEGACY_GRID', 'hash', '2026-01-01 00:00:00')"
                ))
                connection.execute(text(
                    "INSERT INTO message VALUES (1, 'Legacy transmission', '2026-01-01 00:00:00', 1)"
                ))
            upgrade_app = create_app(
                {
                    "TESTING": True,
                    "SECRET_KEY": "legacy-chat-upgrade",
                    "SQLALCHEMY_DATABASE_URI": f"sqlite:///{database_path.as_posix()}",
                    "WTF_CSRF_ENABLED": False,
                }
            )
            with upgrade_app.app_context():
                message = db.session.get(Message, 1)
                self.assertEqual(message.body, "Legacy transmission")
                self.assertEqual(message.conversation.type, "grid")
                self.assertIsNotNone(
                    db.session.get(ConversationMember, (message.conversation_id, 1))
                )
                db.session.remove()
                db.engine.dispose()
            engine.dispose()


if __name__ == "__main__":
    unittest.main()
