"""Sessions the server can end, and a limit on guessing passwords.

The first half needs no database. The second half drives the real endpoints against the development database and runs only
with ORION_AUTH_DB_TESTS=1 (it creates and removes its own `zz_sec_*` users and the attempts from the test client's address):

    $env:ORION_AUTH_DB_TESTS = "1"; python -m pytest backend/tests/test_sessions_and_throttle.py
"""

import inspect
import math
import os
import sys
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app import auth, dependencies, sessions, throttle  # noqa: E402
from app.routers import auth_router, messages_router, users_router  # noqa: E402
from app.throttle import Rule, TooManyAttempts, retry_after  # noqa: E402

RUN = os.environ.get("ORION_AUTH_DB_TESTS") == "1"


# ------------------------------------------------------------------------------------------------------- the cookie


class Cookie(unittest.TestCase):
    def test_a_cookie_we_made_is_read_back(self):
        token = sessions.make_token("abc_DEF-123", int(time.time()) + 60)
        self.assertEqual(sessions.parse_token(token), "abc_DEF-123")

    def test_a_changed_cookie_is_refused(self):
        token = sessions.make_token("abc", int(time.time()) + 60)
        tid, exp, sig = token.split(":")
        self.assertIsNone(sessions.parse_token(f"other:{exp}:{sig}"))  # someone else's id
        self.assertIsNone(sessions.parse_token(f"{tid}:{int(exp) + 99999}:{sig}"))  # a longer life
        self.assertIsNone(sessions.parse_token(f"{tid}:{exp}:{'0' * len(sig)}"))

    def test_a_cookie_signed_with_another_secret_is_refused(self):
        token = sessions.make_token("abc", int(time.time()) + 60)
        with mock.patch("app.sessions.session_secret", return_value=b"a different secret"):
            self.assertIsNone(sessions.parse_token(token))

    def test_an_expired_cookie_is_refused(self):
        self.assertIsNone(sessions.parse_token(sessions.make_token("abc", int(time.time()) - 5)))

    def test_rubbish_is_refused(self):
        for value in (None, "", "abc", "a:b", "a:b:c:d", "a:notanumber:c", ":" + str(int(time.time()) + 9) + ":x", "x" * 500):
            self.assertIsNone(sessions.parse_token(value), repr(value))

    def test_each_session_gets_its_own_random_id(self):
        # The id is what the cookie and the row share; it must not be guessable from the person or the time.
        source = inspect.getsource(sessions.create_session)
        self.assertIn("secrets.token_urlsafe", source)


class Devices(unittest.TestCase):
    def test_a_person_can_recognise_their_own_devices(self):
        chrome_win = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
        edge = chrome_win + " Edg/126.0"
        firefox = "Mozilla/5.0 (X11; Linux x86_64; rv:127.0) Gecko/20100101 Firefox/127.0"
        iphone = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1"
        self.assertEqual(sessions.describe_agent(chrome_win), "Chrome on Windows")
        self.assertEqual(sessions.describe_agent(edge), "Edge on Windows")
        self.assertEqual(sessions.describe_agent(firefox), "Firefox on Linux")
        self.assertEqual(sessions.describe_agent(iphone), "Safari on iPhone")
        self.assertEqual(sessions.describe_agent(None), "Unknown device")


# -------------------------------------------------------------------------------------------------------- the limits


class Arithmetic(unittest.TestCase):
    rule = Rule("pair", limit=5, window_seconds=900)

    def test_under_the_limit_nothing_waits(self):
        self.assertEqual(retry_after([], self.rule, 1000.0), 0)
        self.assertEqual(retry_after([990, 991, 992, 993], self.rule, 1000.0), 0)

    def test_at_the_limit_it_waits_until_the_oldest_ages_out(self):
        times = [100.0, 110.0, 120.0, 130.0, 140.0]
        self.assertEqual(retry_after(times, self.rule, 200.0), math.ceil(100.0 + 900 - 200.0))

    def test_old_attempts_do_not_count(self):
        times = [1.0, 2.0, 3.0, 4.0, 5.0, 2000.0]
        self.assertEqual(retry_after(times, self.rule, 2100.0), 0)

    def test_extra_attempts_do_not_lengthen_it_beyond_what_is_needed(self):
        # Seven in the window, limit five: one more is allowed once enough have aged out to leave four, i.e. the third oldest.
        times = [100.0, 101.0, 102.0, 103.0, 104.0, 105.0, 106.0]
        self.assertEqual(retry_after(times, self.rule, 200.0), math.ceil(102.0 + 900 - 200.0))

    def test_it_is_at_least_a_second(self):
        self.assertEqual(retry_after([100.0] * 5, self.rule, 100.0 + 900 - 0.2), 1)

    def test_the_message_says_how_long_in_minutes(self):
        self.assertIn("3 minutes", TooManyAttempts("login", 150).message)
        self.assertIn("1 minute.", TooManyAttempts("login", 20).message)
        self.assertEqual(TooManyAttempts("login", 0).retry_after, 1)


class Policy(unittest.TestCase):
    def test_every_kind_has_rules_and_a_message(self):
        for kind in ("login", "forgot", "register", "reset"):
            self.assertTrue(throttle.RULES[kind], kind)
            self.assertIn(kind, throttle.MESSAGES)

    def test_a_person_who_mistypes_is_stopped_sooner_than_a_spread_out_attack(self):
        rules = {rule.scope: rule for rule in throttle.RULES["login"]}
        self.assertLess(rules["pair"].limit, rules["username"].limit)
        self.assertLess(rules["username"].limit, rules["ip"].limit)
        self.assertTrue(rules["pair"].cleared_by_success)
        self.assertFalse(rules["username"].cleared_by_success)  # a real sign-in must not wipe an attacker's count

    def test_asking_for_email_counts_every_request_not_just_failures(self):
        for kind in ("forgot", "register"):
            self.assertTrue(all(not rule.failures_only for rule in throttle.RULES[kind]), kind)

    def test_a_guess_at_a_reset_token_counts_failures(self):
        self.assertTrue(all(rule.failures_only for rule in throttle.RULES["reset"]))

    def test_which_rules_can_be_judged(self):
        pair, user, ip, everyone = (Rule(scope, 1, 1) for scope in ("pair", "username", "ip", "global"))
        self.assertTrue(throttle.applies(user, "ann", "10.0.0.5"))
        self.assertFalse(throttle.applies(user, None, "10.0.0.5"))
        self.assertTrue(throttle.applies(pair, "ann", "10.0.0.5"))
        self.assertFalse(throttle.applies(pair, "ann", throttle.UNKNOWN_IP))
        self.assertTrue(throttle.applies(ip, None, "10.0.0.5"))
        # Behind a proxy on this PC every request is from the machine itself: an address limit would lock out everyone.
        for local in ("127.0.0.1", "::1"):
            self.assertFalse(throttle.applies(ip, None, local), local)
        self.assertTrue(throttle.applies(everyone, None, "127.0.0.1"))  # the ceiling that still holds there

    def test_names_are_compared_without_case_or_stray_spaces(self):
        self.assertEqual(throttle.normalise_username("  Ann.Lee "), "ann.lee")
        self.assertIsNone(throttle.normalise_username("   "))
        self.assertEqual(throttle.normalise_ip(None), throttle.UNKNOWN_IP)

    def test_no_password_or_token_is_ever_stored(self):
        sql = (ROOT / ".cursor" / "db" / "migrate_auth_security.sql").read_text(encoding="utf-8")
        attempts = sql.split("auth_attempt (", 1)[1].split(");", 1)[0]
        for forbidden in ("password", "token", "hash"):
            self.assertNotIn(forbidden, attempts.lower())


# ----------------------------------------------------------------------------------------------------------- wiring


class Wiring(unittest.TestCase):
    def test_every_door_that_can_be_knocked_on_without_signing_in_is_limited(self):
        for function, kind in (
            (auth_router.login, "login"), (auth_router.register, "register"), (auth_router.forgot_password, "forgot"),
            (auth_router.reset_password, "reset"), (auth_router.reset_password_status, "reset"),
        ):
            self.assertIn(f'_limited("{kind}"', inspect.getsource(function), function.__name__)

    def test_a_blocked_sign_in_is_refused_before_the_password_is_checked(self):
        source = inspect.getsource(auth_router.login)
        self.assertLess(source.index('_limited("login"'), source.index("authenticate("))
        self.assertIn("Retry-After", inspect.getsource(auth_router._limited))

    def test_every_sign_in_attempt_is_recorded_whatever_the_outcome(self):
        self.assertIn('throttle.record("login"', inspect.getsource(auth_router.login))
        self.assertIn("succeeded=user is not None", inspect.getsource(auth_router.login))

    def test_signing_out_ends_the_session_on_the_server(self):
        self.assertIn("sessions.revoke_token", inspect.getsource(auth_router.logout))

    def test_requests_and_the_chat_socket_go_through_the_session_table(self):
        self.assertIn("sessions.user_for_token", inspect.getsource(dependencies.get_current_user))
        self.assertIn("sessions.user_for_token", inspect.getsource(dependencies.get_optional_user))
        self.assertIn("sessions.user_for_token", inspect.getsource(messages_router._socket_user))
        self.assertFalse(hasattr(auth, "parse_session_token"), "the stateless cookie check must be gone")
        self.assertFalse(hasattr(auth, "make_session_token"))

    def test_a_live_chat_connection_is_checked_again_after_it_is_opened(self):
        self.assertIn("_end_when_signed_out", inspect.getsource(messages_router.messages_ws))
        self.assertLessEqual(messages_router.SOCKET_RECHECK_SECONDS, 60)

    def test_anything_that_changes_who_may_sign_in_ends_their_sessions_in_the_same_transaction(self):
        for function, reason in (
            (auth.update_user_password, "REASON_PASSWORD"), (auth.complete_password_reset, "REASON_PASSWORD"),
            (auth.set_user_active, "REASON_DISABLED"),
        ):
            source = inspect.getsource(function)
            self.assertIn("sessions.revoke_all", source, function.__name__)
            self.assertIn(reason, source, function.__name__)
            self.assertIn("cur=cur", source, f"{function.__name__} must do it in the same transaction")

    def test_an_administrator_can_end_a_persons_sessions(self):
        self.assertIn("sessions.revoke_all", inspect.getsource(users_router.post_sign_out_everywhere))
        route = next(r for r in users_router.router.routes if r.path.endswith("/{user_id}/sign-out"))
        self.assertIn("require_admin", {dep.call.__name__ for dep in route.dependant.dependencies})

    def test_the_devices_routes_need_a_signed_in_person(self):
        wanted = {"/auth/sessions", "/auth/sessions/revoke-others", "/auth/sessions/{session_id}"}
        found = {r.path: r for r in auth_router.router.routes if r.path in wanted}
        self.assertEqual(set(found), wanted)
        for path, route in found.items():
            self.assertIn("get_current_user", {dep.call.__name__ for dep in route.dependant.dependencies}, path)

    def test_a_wrong_name_costs_the_same_password_check_as_a_wrong_password(self):
        with mock.patch.object(auth, "_fetch_user_by_username", return_value=None), \
             mock.patch.object(auth, "verify_password", return_value=False) as verify:
            self.assertIsNone(auth.authenticate("nobody", "whatever"))
        verify.assert_called_once()
        user = {"password_hash": "x", "is_active": False}
        with mock.patch.object(auth, "_fetch_user_by_username", return_value=user), \
             mock.patch.object(auth, "verify_password", return_value=True) as verify:
            self.assertIsNone(auth.authenticate("disabled", "right-password"))  # right password, disabled account
        verify.assert_called_once()

    def test_the_tables_reach_every_database(self):
        from app import entities

        self.assertTrue(entities.AUTH_SECURITY_MIGRATE.is_file())
        self.assertIn(entities.AUTH_SECURITY_MIGRATE, entities.SQL_MIGRATIONS)
        for script in ("scripts/init_db_windows.ps1", "scripts/init_db_mac.sh"):
            self.assertIn("migrate_auth_security.sql", (ROOT / script).read_text(encoding="utf-8"), script)


# -------------------------------------------------------------------------------- against the development database

if RUN:
    from fastapi.testclient import TestClient
    from starlette.websockets import WebSocketDisconnect

    from app.database import db_cursor
    from app.main import app


@unittest.skipUnless(RUN, "set ORION_AUTH_DB_TESTS=1 to run these against the development database")
class RealEndpoints(unittest.TestCase):
    PASSWORD = "a long private pass phrase 1"
    PREFIX = "zz_sec_"

    @classmethod
    def setUpClass(cls):
        sql = (ROOT / ".cursor" / "db" / "migrate_auth_security.sql").read_text(encoding="utf-8")
        with db_cursor(commit=True) as cur:
            cur.execute(sql)
        cls.cleanup()
        cls.ann = cls.make_user("ann", "viewer")
        cls.bob = cls.make_user("bob", "viewer")
        cls.boss = cls.make_user("boss", "admin")

    @classmethod
    def make_user(cls, name, role):
        auth.create_user(cls.PREFIX + name, name.title(), cls.PASSWORD, role=role)
        return cls.PREFIX + name

    @classmethod
    def cleanup(cls):
        with db_cursor(commit=True) as cur:
            cur.execute("DELETE FROM orion_ods.auth_attempt WHERE ip = 'testclient' OR username LIKE %s OR ip LIKE '203.0.113.%%'", (cls.PREFIX + "%",))
            cur.execute("DELETE FROM orion_ods.app_user WHERE username LIKE %s", (cls.PREFIX + "%",))  # sessions go with them

    @classmethod
    def tearDownClass(cls):
        cls.cleanup()

    def setUp(self):
        with db_cursor(commit=True) as cur:
            cur.execute("DELETE FROM orion_ods.auth_attempt WHERE ip = 'testclient' OR ip LIKE '203.0.113.%%' OR username LIKE %s", (self.PREFIX + "%",))
            cur.execute("UPDATE orion_ods.app_user SET is_active = TRUE WHERE username LIKE %s", (self.PREFIX + "%",))
        self.addCleanup(self.cleanup_sessions)

    def cleanup_sessions(self):
        with db_cursor(commit=True) as cur:
            cur.execute("DELETE FROM orion_ods.app_session WHERE user_id IN (SELECT id FROM orion_ods.app_user WHERE username LIKE %s)", (self.PREFIX + "%",))

    def login(self, name, password=None, client=None):
        client = client or TestClient(app)
        response = client.post("/api/auth/login", json={"username": self.PREFIX + name, "password": password or self.PASSWORD})
        return client, response

    def token_of(self, client):
        return client.cookies.get("orion_session")

    def fresh(self, token):
        client = TestClient(app)
        client.cookies.set("orion_session", token)
        return client

    def user_id(self, name):
        return auth._fetch_user_by_username(self.PREFIX + name)["id"]

    # ---- sessions

    def test_signing_in_makes_a_session_and_signing_out_ends_it_even_for_a_copied_cookie(self):
        client, response = self.login("ann")
        self.assertEqual(response.status_code, 200)
        token = self.token_of(client)
        self.assertEqual(client.get("/api/auth/me").status_code, 200)
        copy = self.fresh(token)  # the same cookie, in another browser
        self.assertEqual(copy.get("/api/auth/me").status_code, 200)
        client.post("/api/auth/logout")
        self.assertEqual(copy.get("/api/auth/me").status_code, 401, "a copied cookie must stop working at sign-out")

    def test_the_cookie_is_secure_only_when_the_browser_used_https(self):
        body = {"username": self.PREFIX + "ann", "password": self.PASSWORD}
        plain = TestClient(app, base_url="http://testserver").post("/api/auth/login", json=body)
        self.assertEqual(plain.status_code, 200)
        self.assertNotIn("secure", plain.headers["set-cookie"].lower().replace("samesite", ""))
        secure = TestClient(app, base_url="https://testserver").post("/api/auth/login", json=body)
        cookie = secure.headers["set-cookie"].lower()
        self.assertIn("secure", cookie.replace("samesite", ""))
        self.assertIn("httponly", cookie)
        self.assertIn("strict-transport-security", secure.headers)
        # and signing out clears it with the same attributes, over the same scheme
        out = TestClient(app, base_url="https://testserver").post("/api/auth/logout")
        self.assertIn("secure", out.headers["set-cookie"].lower().replace("samesite", ""))

    def test_the_system_page_is_for_administrators_and_reads_the_real_database(self):
        boss, _ = self.login("boss")
        ann, _ = self.login("ann")
        self.assertEqual(ann.get("/api/health/details").status_code, 403)
        response = boss.get("/api/health/details", headers={"X-Request-ID": "system-page-0001"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["x-request-id"], "system-page-0001")
        found = response.json()
        self.assertTrue(found["database"]["ok"])
        self.assertIn(found["status"], ("ok", "attention"))
        for key in ("loads", "backup", "requests", "problems", "log", "autoload", "attention"):
            self.assertIn(key, found)
        self.assertTrue(all("pipeline" in load for load in found["loads"]))
        self.assertNotIn("bucket", found["backup"] or {})  # nothing about where backups go
        self.assertEqual(TestClient(app).get("/api/health/ready").json(), {"status": "ok", "database": "ok"})

    def test_a_cookie_from_before_this_existed_is_not_accepted(self):
        import hashlib
        import hmac

        from app.config import session_secret

        payload = f"{self.user_id('ann')}:{int(time.time()) + 600}"
        legacy = f"{payload}:{hmac.new(session_secret(), payload.encode(), hashlib.sha256).hexdigest()}"
        self.assertEqual(self.fresh(legacy).get("/api/auth/me").status_code, 401)

    def test_a_session_past_its_end_is_refused_by_the_server(self):
        client, _ = self.login("ann")
        with db_cursor(commit=True) as cur:
            cur.execute("UPDATE orion_ods.app_session SET expires_timestamp = CURRENT_TIMESTAMP - interval '1 minute' WHERE user_id = %s", (self.user_id("ann"),))
        self.assertEqual(client.get("/api/auth/me").status_code, 401)

    def test_devices_are_listed_and_the_others_can_be_signed_out(self):
        here, _ = self.login("ann")
        there, _ = self.login("ann")
        listed = here.get("/api/auth/sessions").json()["sessions"]
        self.assertEqual(len(listed), 2)
        self.assertEqual(sum(1 for item in listed if item["current"]), 1)
        self.assertTrue(all("token" not in item and "token_id" not in item for item in listed))
        ended = here.post("/api/auth/sessions/revoke-others").json()["ended"]
        self.assertEqual(ended, 1)
        self.assertEqual(here.get("/api/auth/me").status_code, 200)
        self.assertEqual(there.get("/api/auth/me").status_code, 401)

    def test_one_device_can_be_ended_and_only_by_its_owner(self):
        ann, _ = self.login("ann")
        other, _ = self.login("ann")
        bob, _ = self.login("bob")
        theirs = next(item for item in ann.get("/api/auth/sessions").json()["sessions"] if not item["current"])
        self.assertEqual(bob.delete(f"/api/auth/sessions/{theirs['id']}").status_code, 404)
        self.assertEqual(other.get("/api/auth/me").status_code, 200)
        self.assertEqual(ann.delete(f"/api/auth/sessions/{theirs['id']}").status_code, 200)
        self.assertEqual(other.get("/api/auth/me").status_code, 401)

    def test_changing_a_password_ends_every_session(self):
        a, _ = self.login("ann")
        b, _ = self.login("ann")
        auth.update_user_password(self.user_id("ann"), self.PASSWORD + "x")
        try:
            self.assertEqual(a.get("/api/auth/me").status_code, 401)
            self.assertEqual(b.get("/api/auth/me").status_code, 401)
            self.assertEqual(self.login("ann", self.PASSWORD + "x")[1].status_code, 200)
        finally:
            auth.update_user_password(self.user_id("ann"), self.PASSWORD)

    def test_finishing_a_password_reset_ends_every_session(self):
        a, _ = self.login("ann")
        raw = auth._store_password_reset_token(self.user_id("ann"))
        auth.complete_password_reset(raw, self.PASSWORD)
        self.assertEqual(a.get("/api/auth/me").status_code, 401)

    def test_disabling_an_account_ends_its_sessions_and_blocks_sign_in(self):
        a, _ = self.login("bob")
        auth.set_user_active(self.user_id("bob"), False, self.user_id("boss"))
        self.assertEqual(a.get("/api/auth/me").status_code, 401)
        self.assertEqual(self.login("bob")[1].status_code, 401)
        auth.set_user_active(self.user_id("bob"), True, self.user_id("boss"))
        self.assertEqual(self.login("bob")[1].status_code, 200)

    def test_an_administrator_can_sign_a_person_out_everywhere(self):
        victim, _ = self.login("bob")
        boss, _ = self.login("boss")
        self.assertEqual(victim.get("/api/auth/me").status_code, 200)
        self.assertEqual(boss.post(f"/api/users/{self.user_id('bob')}/sign-out").json()["ended"], 1)
        self.assertEqual(victim.get("/api/auth/me").status_code, 401)
        self.assertEqual(boss.get("/api/auth/me").status_code, 200)
        ann, _ = self.login("ann")
        self.assertEqual(ann.post(f"/api/users/{self.user_id('bob')}/sign-out").status_code, 403)

    def test_the_session_row_records_why_it_ended(self):
        client, _ = self.login("ann")
        client.post("/api/auth/logout")
        with db_cursor() as cur:
            cur.execute("SELECT revoked_reason FROM orion_ods.app_session WHERE user_id = %s ORDER BY id DESC LIMIT 1", (self.user_id("ann"),))
            self.assertEqual(cur.fetchone()[0], sessions.REASON_SIGNED_OUT)

    def test_a_live_chat_connection_ends_when_its_session_does(self):
        client, _ = self.login("ann")
        with mock.patch.object(messages_router, "SOCKET_RECHECK_SECONDS", 0.2):
            with client.websocket_connect("/api/messages/ws") as socket:
                socket.receive_json()  # the first thing it sends
                client.post("/api/auth/logout")
                deadline = time.time() + 5
                while time.time() < deadline:
                    try:  # asking and listening, so a connection that is NOT ended fails the test instead of waiting for ever
                        socket.send_json({"type": "ping"})
                        socket.receive_json()
                    except WebSocketDisconnect:
                        return
                    time.sleep(0.1)
                self.fail("the chat connection stayed open after its session ended")

    # ---- limits

    def test_the_sixth_wrong_password_is_refused_before_it_is_checked(self):
        for _ in range(5):
            self.assertEqual(self.login("ann", "wrong")[1].status_code, 401)
        blocked = self.login("ann", "wrong")[1]
        self.assertEqual(blocked.status_code, 429)
        self.assertIn("minute", blocked.json()["detail"])
        self.assertGreater(int(blocked.headers["Retry-After"]), 0)
        # even the right password is refused during the block, so a block cannot be used to test passwords
        self.assertEqual(self.login("ann")[1].status_code, 429)

    def test_the_block_is_for_that_name_and_address_not_for_everyone(self):
        for _ in range(5):
            self.login("ann", "wrong")
        self.assertEqual(self.login("ann")[1].status_code, 429)
        self.assertEqual(self.login("bob")[1].status_code, 200)

    def test_a_name_that_does_not_exist_is_limited_too(self):
        for _ in range(5):
            self.assertEqual(TestClient(app).post("/api/auth/login", json={"username": "nobody_here", "password": "x"}).status_code, 401)
        self.assertEqual(TestClient(app).post("/api/auth/login", json={"username": "nobody_here", "password": "x"}).status_code, 429)

    def test_a_correct_sign_in_clears_the_count_for_that_pair(self):
        for _ in range(4):
            self.login("ann", "wrong")
        self.assertEqual(self.login("ann")[1].status_code, 200)
        for _ in range(4):
            self.assertEqual(self.login("ann", "wrong")[1].status_code, 401)  # four more would have been a block without it
        self.assertEqual(self.login("ann")[1].status_code, 200)

    def test_guessing_one_name_from_many_addresses_is_stopped(self):
        with db_cursor(commit=True) as cur:
            for index in range(15):
                cur.execute(
                    "INSERT INTO orion_ods.auth_attempt (kind, username, ip, succeeded) VALUES ('login', %s, %s, FALSE)",
                    (self.PREFIX + "ann", f"203.0.113.{index + 1}"),
                )
        self.assertEqual(self.login("ann")[1].status_code, 429)
        self.assertEqual(self.login("bob")[1].status_code, 200)

    def test_one_address_trying_many_names_is_stopped(self):
        with db_cursor(commit=True) as cur:
            for index in range(30):
                cur.execute(
                    "INSERT INTO orion_ods.auth_attempt (kind, username, ip, succeeded) VALUES ('login', %s, 'testclient', FALSE)",
                    (f"{self.PREFIX}name{index}",),
                )
        self.assertEqual(self.login("bob")[1].status_code, 429)

    def test_the_block_ends_by_itself(self):
        for _ in range(5):
            self.login("ann", "wrong")
        with db_cursor(commit=True) as cur:
            cur.execute("UPDATE orion_ods.auth_attempt SET attempted_timestamp = attempted_timestamp - interval '16 minutes' WHERE username = %s", (self.PREFIX + "ann",))
        self.assertEqual(self.login("ann")[1].status_code, 200)

    def test_every_attempt_is_on_record_without_the_password(self):
        self.login("ann", "wrong-secret-xyz")
        self.login("ann")
        with db_cursor() as cur:
            cur.execute("SELECT succeeded, ip FROM orion_ods.auth_attempt WHERE username = %s ORDER BY id", (self.PREFIX + "ann",))
            self.assertEqual([row[0] for row in cur.fetchall()], [False, True])
            cur.execute("SELECT count(*) FROM orion_ods.auth_attempt WHERE username || ip ILIKE '%%secret%%'")
            self.assertEqual(cur.fetchone()[0], 0)

    def test_reset_emails_are_limited_per_name(self):
        client = TestClient(app)
        with mock.patch.object(auth_router, "request_password_reset"):
            codes = [client.post("/api/auth/forgot-password", json={"username": self.PREFIX + "ann", "email": "a@b.co"}).status_code for _ in range(4)]
        self.assertEqual(codes, [200, 200, 200, 429])

    def test_account_requests_are_limited(self):
        client = TestClient(app)
        body = {"username": "x", "display_name": "X", "password": "p", "email": "x@y.co"}
        with mock.patch.object(auth_router, "request_signup"):
            codes = [client.post("/api/auth/register", json=body).status_code for _ in range(6)]
        self.assertEqual(codes, [200] * 5 + [429])

    def test_wrong_reset_links_are_limited(self):
        client = TestClient(app)
        for _ in range(10):
            self.assertEqual(client.post("/api/auth/reset-password", json={"token": "nope", "password": self.PASSWORD}).status_code, 400)
        self.assertEqual(client.post("/api/auth/reset-password", json={"token": "nope", "password": self.PASSWORD}).status_code, 429)
        self.assertEqual(client.get("/api/auth/reset-password", params={"token": "nope"}).status_code, 429)


if __name__ == "__main__":
    unittest.main()
