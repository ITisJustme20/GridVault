import tempfile
import threading
import unittest
from datetime import timedelta
from pathlib import Path

from werkzeug.security import generate_password_hash

from gridvault import create_app
from gridvault.extensions import db
from gridvault.invitations import consume_invitation, issue_invitation, reset_invitation_attempts, utc_now
from gridvault.models import Invitation, User


class AccessGateTestCase(unittest.TestCase):
    def setUp(self):
        self.app = create_app(
            {
                "TESTING": True,
                "SECRET_KEY": "access-gate-test-key",
                "SQLALCHEMY_DATABASE_URI": "sqlite://",
                "WTF_CSRF_ENABLED": False,
            }
        )
        self.client = self.app.test_client()

    def tearDown(self):
        reset_invitation_attempts()
        with self.app.app_context():
            db.session.remove()
            db.drop_all()

    def add_user(self, callsign, *, admin=False, password="existing-passphrase"):
        with self.app.app_context():
            user = User(
                username=callsign,
                password_hash=generate_password_hash(password),
                is_admin=admin,
            )
            db.session.add(user)
            db.session.commit()
            return user.id

    def login(self, callsign, password="existing-passphrase"):
        return self.client.post(
            "/login",
            data={"username": callsign, "password": password},
            follow_redirects=True,
        )

    def issue(self, *, reserved="", expires_in=None):
        with self.app.app_context():
            admin = db.session.scalar(db.select(User).where(User.is_admin.is_(True)))
            invite, code = issue_invitation(admin, reserved_callsign=reserved, expires_in=expires_in)
            return invite.public_id, code

    def enter(self, code, callsign):
        return self.client.post(
            "/access",
            data={
                "invite_code": code,
                "username": callsign,
                "password": "invited-passphrase",
                "confirm_password": "invited-passphrase",
            },
            follow_redirects=True,
        )

    def test_existing_login_works_and_public_registration_is_disabled(self):
        self.add_user("LEGACY_ONE")
        login = self.login("legacy_one")
        self.assertIn(b"Mission Console", login.data)
        self.client.post("/logout")

        registration = self.client.post(
            "/register",
            data={"username": "PUBLIC_USER", "password": "not-allowed"},
            follow_redirects=True,
        )
        self.assertIn(b"ACCESS AUTHORIZATION REQUIRED", registration.data)
        with self.app.app_context():
            self.assertIsNone(db.session.scalar(db.select(User).where(User.username == "PUBLIC_USER")))

    def test_valid_invitation_is_hashed_single_use_and_orientation_is_once(self):
        self.add_user("ADMIN", admin=True)
        _, code = self.issue()
        first = self.enter(code.lower(), "new_operator")
        self.assertIn(b"ACCESS GRANTED", first.data)

        with self.app.app_context():
            invite = db.session.scalar(db.select(Invitation))
            user = db.session.scalar(db.select(User).where(User.username == "NEW_OPERATOR"))
            self.assertEqual(invite.status, "Used")
            self.assertEqual(invite.used_by_user_id, user.id)
            self.assertNotEqual(invite.code_hash, code)
            self.assertNotIn(code, repr(invite.__dict__))

        continued = self.client.post("/orientation", follow_redirects=True)
        self.assertIn(b"Mission Console", continued.data)
        self.client.post("/logout")
        relogin = self.login("NEW_OPERATOR", "invited-passphrase")
        self.assertIn(b"Mission Console", relogin.data)
        self.assertNotIn(b"ACCESS GRANTED", relogin.data)

        self.client.post("/logout")
        reused = self.enter(code, "SECOND_OPERATOR")
        self.assertIn(b"Authorization could not be verified", reused.data)
        with self.app.app_context():
            self.assertIsNone(db.session.scalar(db.select(User).where(User.username == "SECOND_OPERATOR")))

    def test_expired_and_revoked_invitations_fail(self):
        self.add_user("ADMIN", admin=True)
        expired_id, expired_code = self.issue(expires_in=timedelta(hours=1))
        revoked_id, revoked_code = self.issue()
        with self.app.app_context():
            expired = db.session.scalar(db.select(Invitation).where(Invitation.public_id == expired_id))
            expired.expires_at = utc_now() - timedelta(minutes=1)
            revoked = db.session.scalar(db.select(Invitation).where(Invitation.public_id == revoked_id))
            revoked.status = "Revoked"
            revoked.revoked_at = utc_now()
            db.session.commit()

        self.assertIn(b"Authorization could not be verified", self.enter(expired_code, "EXPIRED_USER").data)
        self.assertIn(b"Authorization could not be verified", self.enter(revoked_code, "REVOKED_USER").data)

    def test_reserved_and_open_invitations_validate_callsigns_safely(self):
        self.add_user("ADMIN", admin=True)
        self.add_user("EXISTING_NAME")
        _, reserved_code = self.issue(reserved="RESERVED_ONE")
        wrong = self.enter(reserved_code, "WRONG_NAME")
        self.assertIn(b"reserved for a different callsign", wrong.data)
        self.assertIn(b"ACCESS GRANTED", self.enter(reserved_code, "reserved_one").data)

        self.client.post("/logout")
        _, open_code = self.issue(expires_in=timedelta(hours=24))
        duplicate = self.enter(open_code, "existing_name")
        self.assertIn(b"callsign is unavailable", duplicate.data)
        self.assertIn(b"ACCESS GRANTED", self.enter(open_code, "OPEN_CHOICE").data)

    def test_only_administrators_can_view_create_or_revoke(self):
        self.add_user("ADMIN", admin=True)
        public_id, _ = self.issue()
        self.add_user("OPERATOR")
        self.login("OPERATOR")
        self.assertEqual(self.client.get("/access-control").status_code, 403)
        self.assertEqual(self.client.post("/access-control/invitations", data={"expiration": "none"}).status_code, 403)
        self.assertEqual(self.client.post(f"/access-control/invitations/{public_id}/revoke").status_code, 403)

    def test_administrator_creates_one_time_display_and_revokes(self):
        self.add_user("ADMIN", admin=True)
        self.login("ADMIN")
        created = self.client.post(
            "/access-control/invitations",
            data={"reserved_callsign": "RESERVED_TWO", "expiration": "7d"},
        )
        self.assertEqual(created.status_code, 200)
        self.assertEqual(created.headers["Cache-Control"], "no-store")
        self.assertIn(b"Shown once", created.data)
        with self.app.app_context():
            invite = db.session.scalar(db.select(Invitation))
            self.assertEqual(invite.reserved_callsign, "RESERVED_TWO")
            public_id = invite.public_id
            short_label = f"INV-{invite.code_hash[:8].upper()}".encode()
        self.assertIn(short_label, self.client.get("/access-control").data)
        self.assertNotIn(b"GV-", self.client.get("/access-control").data)

        revoked = self.client.post(f"/access-control/invitations/{public_id}/revoke", follow_redirects=True)
        self.assertIn(b"Authorization revoked", revoked.data)
        with self.app.app_context():
            self.assertEqual(db.session.scalar(db.select(Invitation)).status, "Revoked")

    def test_account_and_invitation_mutations_require_csrf(self):
        self.add_user("ADMIN", admin=True)
        self.login("ADMIN")
        self.app.config["WTF_CSRF_ENABLED"] = True
        self.assertEqual(
            self.client.post("/access-control/invitations", data={"expiration": "24h"}).status_code,
            400,
        )
        self.client.post("/logout", data={"csrf_token": "invalid"})
        other_client = self.app.test_client()
        self.assertEqual(
            other_client.post(
                "/access",
                data={
                    "invite_code": "GV-" + "A" * 40,
                    "username": "NO_CSRF",
                    "password": "invited-passphrase",
                    "confirm_password": "invited-passphrase",
                },
            ).status_code,
            400,
        )


class ConcurrentInvitationTestCase(unittest.TestCase):
    def test_one_invitation_can_only_create_one_account_concurrently(self):
        temporary = tempfile.TemporaryDirectory()
        try:
            database_path = (Path(temporary.name) / "concurrent.db").as_posix()
            app = create_app(
                {
                    "TESTING": True,
                    "SECRET_KEY": "concurrent-test-key",
                    "SQLALCHEMY_DATABASE_URI": f"sqlite:///{database_path}",
                    "WTF_CSRF_ENABLED": False,
                }
            )
            with app.app_context():
                admin = User(username="ADMIN", password_hash=generate_password_hash("existing-passphrase"), is_admin=True)
                db.session.add(admin)
                db.session.commit()
                _, code = issue_invitation(admin)

            barrier = threading.Barrier(2)
            outcomes = []

            def attempt(callsign):
                with app.app_context():
                    barrier.wait()
                    user, _ = consume_invitation(code, callsign, "invited-passphrase")
                    outcomes.append(user is not None)

            threads = [threading.Thread(target=attempt, args=(name,)) for name in ("RACE_ONE", "RACE_TWO")]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()

            self.assertEqual(outcomes.count(True), 1)
            with app.app_context():
                invited_users = db.session.scalar(
                    db.select(db.func.count(User.id)).where(User.username.in_(("RACE_ONE", "RACE_TWO")))
                )
                self.assertEqual(invited_users, 1)
                self.assertEqual(db.session.scalar(db.select(Invitation)).status, "Used")
                db.session.remove()
                db.engine.dispose()
        finally:
            temporary.cleanup()


if __name__ == "__main__":
    unittest.main()
