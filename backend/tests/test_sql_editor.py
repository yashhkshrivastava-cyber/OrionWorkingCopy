"""The SQL editor: what the guard lets through and what it refuses, how a script is read apart, the modes, who may use it, and that the
routes are guarded and every run is audited. No database is needed (the connection is stubbed where a run is tried)."""

import inspect
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from fastapi.routing import APIRoute  # noqa: E402

from app import auth, sql_guard as g, sql_lab  # noqa: E402
from app.entities import SQL_LAB_MIGRATE, SQL_MIGRATIONS  # noqa: E402
from app.routers import sql_router  # noqa: E402

ADMIN = {"id": 1, "username": "admin", "role": "admin"}


def allowed(sql, change=False):
    return [(s.first, v.kind) for s, v in g.vet_script(sql, may_change=change)]


def refused(sql, change=False):
    with unittest.TestCase().assertRaises(g.Blocked) as caught:
        g.vet_script(sql, may_change=change)
    return str(caught.exception)


class ReadingAScript(unittest.TestCase):
    def test_statements_are_split_at_semicolons_that_are_not_inside_text(self):
        found = g.scan("select 1; select 'a;b', \"c;d\", $$e;f$$; -- g;h\n select /* i;j */ 2;")
        self.assertEqual([s.first for s in found], ["select", "select", "select"])
        self.assertEqual(len(found), 3)

    def test_a_comment_and_a_string_do_not_change_what_a_statement_is(self):
        s = g.scan("select 'drop table x' /* delete from y */ from client -- update z")[0]
        self.assertNotIn("drop", s.clean)
        self.assertNotIn("delete", s.clean)
        self.assertNotIn("update", s.clean)

    def test_a_quoted_name_is_read_as_the_name(self):
        self.assertIn("app_user", g.scan('select * from "App_User"')[0].clean)

    def test_dollar_quotes_with_a_tag_and_nested_comments(self):
        self.assertEqual(len(g.scan("select $t$ ; $t$; select /* a /* b ; */ c */ 2")), 2)

    def test_an_escaped_quote_does_not_end_a_string_early(self):
        self.assertEqual(len(g.scan("select 'it''s; fine'; select E'a\\'b;c'")), 2)

    def test_where_a_statement_starts_is_kept_for_an_errors_position(self):
        self.assertEqual([s.line for s in g.scan("select 1;\n\nselect 2;\nselect 3")], [1, 3, 4])

    def test_nothing_to_run_and_too_much_are_refused(self):
        self.assertIn("nothing", refused("  -- only a comment\n").lower())
        self.assertIn("at most", refused("select 1;" * (g.MAX_STATEMENTS + 1)))
        self.assertIn("too long", refused("select '" + "x" * g.MAX_SQL + "'"))


class Reading(unittest.TestCase):
    def test_reads_are_allowed_without_changes_turned_on(self):
        for sql in ("select 1", "with a as (select 1) select * from a", "values (1)", "show server_version", "table orion_ods.client", "explain select 1", "select count(*) from reports.users"):
            self.assertEqual(allowed(sql)[0][1], "read", sql)

    def test_private_tables_are_never_readable_however_they_are_written(self):
        for sql in ("select * from app_user", "select * from orion_ods.app_user", 'select * from "app_user"', "select * from orion_ods . app_session", "select token_id from app_session",
                    "select * from signup_request", "select * from gdrive_connection", "select * from chat_message", "select * from idempotency_key",
                    "select * from pg_authid", "select * from pg_shadow"):
            self.assertRegex(refused(sql, True), r"not readable|secrets", sql)

    def test_the_users_can_be_read_through_the_safe_view(self):
        self.assertEqual(allowed("select * from reports.users")[0][1], "read")
        sql = (ROOT / ".cursor" / "db" / "migrate_sql_lab.sql").read_text(encoding="utf-8")
        view = sql[sql.index("CREATE OR REPLACE VIEW reports.users"):sql.index("-- A query kept")]
        for secret in ("password_hash", "password_reset_token", "password_reset_expires"):
            self.assertNotIn(secret, view)

    def test_functions_that_reach_outside_are_refused(self):
        for sql in ("select pg_terminate_backend(1)", "select pg_cancel_backend(1)", "select nextval('orion_ods.bill_seq')", "select setval('x', 1)", "select pg_read_file('x')",
                    "select set_config('a','b',false)", "select query_to_xml('select 1', true, true, '')", "select lo_import('x')", "select dblink('a','b')"):
            self.assertIn("cannot be used", refused(sql), sql)

    def test_select_into_is_pointed_at_create_table_as(self):
        self.assertIn("CREATE TABLE reports", refused("select * into t from client", True))
        self.assertEqual(allowed("select a, 'into' from client")[0][1], "read")

    def test_what_the_editor_never_runs(self):
        for sql in ("set role x", "reset all", "begin", "commit", "rollback", "savepoint a", "grant all on x to y", "revoke all on x from y", "copy client to stdout", "do $$ begin end $$",
                    "execute foo", "prepare a as select 1", "listen x", "notify x", "vacuum", "lock table x", "call p()", "analyze client"):
            self.assertIn("cannot be run", refused(sql, True), sql)

    def test_an_unknown_first_word_is_refused_in_words(self):
        self.assertIn("is not something", refused("selec 1"))

    def test_explain_is_only_a_plan_unless_it_runs_the_statement(self):
        self.assertEqual(allowed("explain delete from client where x = 1")[0][1], "read")  # a plan changes nothing
        self.assertEqual(allowed("explain (analyze, buffers) select 1")[0][1], "read")
        self.assertEqual(allowed("explain analyze delete from client where x = 1", True)[0][1], "write")
        self.assertIn("Allow changes", refused("explain analyze delete from client where x = 1"))
        self.assertIn("only through Orion", refused("explain analyze delete from bill where x=1", True))


class ChangingData(unittest.TestCase):
    def test_data_changes_need_the_switch(self):
        for sql in ("insert into client (a) values (1)", "update client set a = 1 where b = 2", "delete from client where a = 1", "with a as (delete from client where x=1 returning *) select * from a"):
            self.assertIn("Allow changes", refused(sql), sql)
            self.assertEqual(allowed(sql, True)[0][1], "write", sql)

    def test_the_tables_orion_owns_can_be_read_but_not_changed(self):
        for sql in ("update bill set a = 1 where x=1", "delete from orion_ods.case_transaction where x=1", "insert into bank_entry (a) values (1)", "update expense_payment set a=1 where x=1",
                    "truncate salary_run", "delete from document where x=1", "update attendance_line set a=1 where x=1", "insert into schema_migrations (a) values (1)",
                    "delete from sql_query_log where x=1", "update app_user set role = 'admin'"):
            self.assertRegex(refused(sql, True), r"only through Orion|not readable|limited to", sql)
        self.assertEqual(allowed("select * from bill")[0][1], "read")
        self.assertEqual(allowed("update client set a = 1 where b = 2", True)[0][1], "write")

    def test_an_update_or_delete_with_no_where_must_be_confirmed(self):
        for sql in ("update client set a = 1", "delete from client"):
            verdict = g.vet_script(sql, may_change=True)[0][1]
            self.assertTrue(verdict.confirm, sql)
        self.assertFalse(g.vet_script("update client set a = 1 where b = 2", may_change=True)[0][1].confirm)
        self.assertTrue(g.vet_script("update client set a = 1 -- where b = 2", may_change=True)[0][1].confirm)  # a WHERE in a comment is not a WHERE


class ChangingStructure(unittest.TestCase):
    def test_structure_is_for_the_reports_schema_only(self):
        for sql in ("create table reports.t (id int)", "create table t (id int)", "drop table reports.t", "alter table reports.t add column x int", "truncate reports.t",
                    "create index ix on reports.t (id)", "create sequence reports.s", "comment on table reports.t is 'x'", "refresh materialized view reports.m",
                    "create view reports.v as select * from orion_ods.client", "create or replace view v as select 1", "create materialized view reports.m as select 1"):
            self.assertEqual(allowed(sql, True)[0][1], "structure", sql)

    def test_structure_in_orions_own_schemas_is_refused(self):
        for sql in ("drop table orion_ods.client", "alter table orion_dw.dim_client add column x int", "truncate orion_ods.client", "create table orion_ods.t (id int)",
                    "create view orion_ods.v as select 1", "drop view tally_dw.x", "create index ix on public.t (id)", "alter table information_schema.x add column y int"):
            self.assertRegex(refused(sql, True), r"reports", sql)

    def test_a_name_with_no_schema_is_looked_up_only_in_reports_so_it_cannot_reach_an_app_table(self):
        for sql in ("drop table client", "alter table client add column x int", "truncate client"):
            verdict = g.vet_script(sql, may_change=True)[0][1]
            self.assertEqual(verdict.search_path, "reports", sql)
        view = g.vet_script("create view reports.v as select * from client", may_change=True)[0][1]
        self.assertIn("orion_ods", view.search_path)  # a view's body may name Orion's tables, unqualified

    def test_the_kinds_of_object_that_can_be_made(self):
        for sql in ("create function f() returns int as $$select 1$$ language sql", "create schema x", "create extension x", "create role x", "create database x", "create trigger t before insert on reports.x for each row execute function f()",
                    "drop schema reports", "alter role x", "drop function f()", "alter database x set a = 1"):
            self.assertRegex(refused(sql, True), r"not supported|cannot be run|not something", sql)

    def test_dropping_and_truncating_are_confirmed(self):
        self.assertTrue(g.vet_script("drop table reports.t", may_change=True)[0][1].confirm)
        self.assertTrue(g.vet_script("truncate reports.t", may_change=True)[0][1].confirm)

    def test_a_script_is_refused_whole_and_says_which_statement(self):
        message = refused("select 1; drop table orion_ods.client; select 2", True)
        self.assertIn("Statement 2", message)


class TheModes(unittest.TestCase):
    def test_a_development_computer_can_change_and_production_reads(self):
        self.assertEqual(sql_lab.mode({}), "full")
        self.assertEqual(sql_lab.mode({"ORION_ENV": "production"}), "readonly")
        self.assertEqual(sql_lab.mode({"ORION_ENV": "production", "ORION_SQL_EDITOR": "full"}), "full")
        self.assertEqual(sql_lab.mode({"ORION_SQL_EDITOR": "off"}), "off")
        self.assertEqual(sql_lab.mode({"ORION_SQL_EDITOR": "readonly"}), "readonly")
        self.assertEqual(sql_lab.mode({"ORION_SQL_EDITOR": "nonsense"}), "full")

    def test_only_an_admin_may_use_it_and_not_when_it_is_off(self):
        self.assertTrue(sql_lab.can_use(ADMIN))
        self.assertFalse(sql_lab.can_use({"id": 2, "role": "editor"}))
        self.assertFalse(sql_lab.can_use(None))
        with mock.patch("app.sql_lab.mode", return_value="off"):
            self.assertFalse(sql_lab.can_use(ADMIN))
        self.assertTrue(auth.can_access_page(ADMIN, "sql"))
        self.assertFalse(auth.can_access_page({"id": 2, "role": "editor"}, "sql"))

    def test_changes_are_refused_when_the_server_is_read_only(self):
        with mock.patch("app.sql_lab.mode", return_value="readonly"), self.assertRaises(sql_lab.RunError):
            sql_lab.run(ADMIN, "update client set a=1 where b=2", write=True)

    def test_the_limits_are_clamped(self):
        self.assertLessEqual(sql_lab.MAX_LIMIT, 10_000)
        self.assertLessEqual(sql_lab.MAX_TIMEOUT, 120)


class RunningIt(unittest.TestCase):
    """What run() does around the database, with the database stubbed."""

    def test_a_refused_script_is_audited_and_never_reaches_the_database(self):
        with mock.patch("app.sql_lab._log") as log, mock.patch("app.sql_lab.raw_connection") as connect:
            answer = sql_lab.run(ADMIN, "select * from app_user")
        connect.assert_not_called()
        self.assertTrue(answer["blocked"])
        self.assertEqual(log.call_args.kwargs["status_"], "blocked")

    def test_something_to_confirm_is_asked_first_and_nothing_runs(self):
        with mock.patch("app.sql_lab._log") as log, mock.patch("app.sql_lab.raw_connection") as connect:
            answer = sql_lab.run(ADMIN, "delete from client", write=True)
        connect.assert_not_called()
        log.assert_not_called()
        self.assertTrue(answer["needs_confirmation"])

    def test_a_read_runs_in_a_read_only_transaction_with_a_timeout_and_is_rolled_back(self):
        executed = []

        class Cursor:
            description = [("a", 23)]
            statusmessage = "SELECT 1"
            rowcount = 1

            def execute(self, sql, params=None):
                executed.append(" ".join(str(sql).split()))

            def fetchmany(self, n):
                return [(1,)]

            def fetchall(self):
                return [(23, "integer")]

        class Connection:
            autocommit = True
            committed = rolled_back = closed = False

            def cursor(self):
                return Cursor()

            def get_backend_pid(self):
                return 4242

            def commit(self):
                self.committed = True

            def rollback(self):
                self.rolled_back = True

            def close(self):
                self.closed = True

        conn = Connection()
        with mock.patch("app.sql_lab.raw_connection", return_value=conn), mock.patch("app.sql_lab._log") as log:
            answer = sql_lab.run(ADMIN, "select 1", timeout=5)
        self.assertEqual(executed[0], "SET TRANSACTION READ ONLY")
        self.assertIn("set_config('statement_timeout'", executed[1])
        self.assertTrue(any(line.startswith("SET LOCAL search_path = reports") for line in executed))
        self.assertTrue(conn.rolled_back and not conn.committed and conn.closed)
        self.assertEqual(answer["results"][0]["rows"], [[1]])
        self.assertEqual(answer["results"][0]["columns"], [{"name": "a", "type": "integer"}])
        self.assertEqual(log.call_args.kwargs["status_"], "ok")

    def test_changes_are_committed_only_when_not_rolled_back(self):
        class Cursor:
            description = None
            statusmessage = "UPDATE 2"
            rowcount = 2

            def execute(self, sql, params=None):
                pass

        for rollback, committed in ((True, False), (False, True)):
            conn = mock.MagicMock()
            conn.cursor.return_value = Cursor()
            with mock.patch("app.sql_lab.raw_connection", return_value=conn), mock.patch("app.sql_lab._log"):
                answer = sql_lab.run(ADMIN, "update client set a=1 where b=2", write=True, rollback=rollback)
            self.assertEqual(conn.commit.called, committed, rollback)
            self.assertEqual(answer["rolled_back"], rollback)

    def test_a_person_can_cancel_only_their_own_run(self):
        with sql_lab._lock:
            sql_lab._running["abc"] = (1, 99)
        with mock.patch("app.sql_lab.db_cursor") as cursor:
            self.assertFalse(sql_lab.cancel({"id": 2}, "abc"))
            self.assertFalse(sql_lab.cancel(ADMIN, "nope"))
            self.assertTrue(sql_lab.cancel(ADMIN, "abc"))
        self.assertTrue(cursor.called)
        with sql_lab._lock:
            sql_lab._running.pop("abc", None)
            sql_lab._cancelled.discard("abc")

    def test_values_are_made_safe_for_the_browser(self):
        from datetime import date, datetime
        from decimal import Decimal
        import uuid

        self.assertEqual(sql_lab._cell(Decimal("1.50")), "1.50")
        self.assertEqual(sql_lab._cell(date(2026, 1, 2)), "2026-01-02")
        self.assertEqual(sql_lab._cell(datetime(2026, 1, 2, 3, 4)), "2026-01-02T03:04:00")
        self.assertEqual(sql_lab._cell(float("nan")), "nan")
        self.assertEqual(sql_lab._cell(b"\x01\x02"), "\\x0102")
        self.assertEqual(sql_lab._cell({"a": 1}), '{"a": 1}')
        self.assertEqual(sql_lab._cell(uuid.UUID(int=1)), "00000000-0000-0000-0000-000000000001")
        self.assertTrue(sql_lab._cell("x" * 10_000).endswith("…"))


class TheRoutes(unittest.TestCase):
    def test_every_route_needs_an_admin_with_the_editor_on(self):
        routes = [r for r in sql_router.router.routes if isinstance(r, APIRoute)]
        self.assertGreaterEqual(len(routes), 10)
        for route in routes:
            names = [d.call.__name__ for d in route.dependant.dependencies]
            self.assertIn("require_sql", names, route.path)

    def test_the_guard_runs_before_the_connection_is_opened(self):
        source = inspect.getsource(sql_lab.run)
        self.assertLess(source.index("vet_script"), source.index("raw_connection()"))

    def test_every_run_is_audited_and_the_editor_cannot_change_the_log(self):
        self.assertIn("_log(", inspect.getsource(sql_lab.run))
        self.assertRegex(refused("delete from sql_query_log where log_id = 1", True), r"only through Orion")
        self.assertRegex(refused("truncate sql_query_log", True), r"limited to")

    def test_the_schema_is_registered_where_it_must_be(self):
        self.assertIn(SQL_LAB_MIGRATE, SQL_MIGRATIONS)
        for script in ("init_db_windows.ps1", "init_db_mac.sh"):
            self.assertIn("migrate_sql_lab.sql", (ROOT / "scripts" / script).read_text(encoding="utf-8"), script)

    def test_a_private_table_is_listed_but_its_columns_and_detail_are_not_given(self):
        with mock.patch("app.sql_lab.db_cursor"), self.assertRaises(sql_lab.RunError):
            sql_lab.object_detail("orion_ods", "app_user")
        with self.assertRaises(sql_lab.RunError):
            sql_lab.object_detail("pg_catalog", "pg_class")


if __name__ == "__main__":
    unittest.main()
