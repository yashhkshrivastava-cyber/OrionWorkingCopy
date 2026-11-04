"""The task workspace: the rules in pure form, the schema and its registration, and (with ORION_DB_TESTS=1) the whole story against the development database inside one
transaction that is rolled back at the end, so nothing is left behind:

    $env:ORION_DB_TESTS = "1"; python -m pytest backend/tests/test_tasks.py
"""

import contextlib
import itertools
import os
import sys
import unittest
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app import entities, sql_guard, task_common as common, task_items, task_notify, task_templates  # noqa: E402

RUN = os.environ.get("ORION_DB_TESTS") == "1"
SQL = ROOT / ".cursor" / "db"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


class VocabularyTests(unittest.TestCase):
    def test_labels_are_tidied_and_limited(self):
        self.assertEqual(common.clean_labels(" GST , PF ESI, gst "), ["gst", "pf-esi"])
        self.assertEqual(common.clean_labels(["Month End", "month-end", "Q1!"]), ["month-end", "q1"])
        self.assertEqual(common.clean_labels(None), [])
        with self.assertRaises(common.TaskError):
            common.clean_labels([f"label{i}" for i in range(common.MAX_LABELS + 1)])
        with self.assertRaises(common.TaskError):
            common.clean_labels(["x" * (common.MAX_LABEL + 1)])

    def test_mentions_are_read_from_the_picker_token_only(self):
        text = "Please look @[Asha Verma](user:12) and @[Ravi](user:7); not @plain or @[Asha Verma](user:12) twice"
        self.assertEqual(common.mentioned_ids(text), [12, 7])
        self.assertEqual(common.mentioned_ids(None, "nothing here"), [])
        self.assertEqual(common.mentioned_ids("@[Bad](user:abc)"), [])

    def test_text_dates_and_minutes_are_checked(self):
        self.assertEqual(common.clean_text("  a   b  ", 10, "x"), "a b")
        self.assertEqual(common.clean_text("line1\r\nline2 ", 100, "x", multiline=True), "line1\nline2")
        with self.assertRaises(common.TaskError):
            common.clean_text("", 10, "The title", required=True)
        with self.assertRaises(common.TaskError):
            common.clean_text("x" * 11, 10, "The title")
        self.assertEqual(common.clean_date("2026-10-05", "d"), date(2026, 10, 5))
        with self.assertRaises(common.TaskError):
            common.clean_date("05/10/2026", "d")
        self.assertEqual(common.clean_minutes("90", "t"), 90)
        with self.assertRaises(common.TaskError):
            common.clean_minutes("-1", "t")
        with self.assertRaises(common.TaskError):
            common.clean_minutes("abc", "t")

    def test_the_default_workflow_has_every_kind_of_status(self):
        categories = [category for _name, category in common.DEFAULT_STATUSES]
        for needed in common.CATEGORIES:
            self.assertIn(needed, categories)

    def test_a_history_line_is_said_in_words(self):
        words = task_items._words("status", {"from": "To Do", "to": "Done", "resolution": "Done", "note": "ok"})
        self.assertIn("To Do", words)
        self.assertIn("Done", words)
        self.assertEqual(task_items._words("created", {}), "created this task")
        self.assertIn("due date", task_items._words("changed", {"fields": {"due_date": {"from": None, "to": "2026-10-30"}}}))


class ScheduleTests(unittest.TestCase):
    def test_a_month_that_is_too_short_uses_its_last_day(self):
        spec = {"frequency": "monthly", "interval_count": 1, "day_of_month": 31}
        self.assertEqual(task_templates.first_run(spec, date(2026, 4, 10)), date(2026, 4, 30))
        self.assertEqual(task_templates.following(spec, date(2026, 4, 30)), date(2026, 5, 31))
        self.assertEqual(task_templates.following(spec, date(2026, 1, 31)), date(2026, 2, 28))
        self.assertEqual(task_templates.following({**spec, "interval_count": 3}, date(2026, 11, 30)), date(2027, 2, 28))

    def test_the_first_run_is_today_or_the_next_matching_day(self):
        monthly = {"frequency": "monthly", "interval_count": 1, "day_of_month": 15}
        self.assertEqual(task_templates.first_run(monthly, date(2026, 10, 15)), date(2026, 10, 15))
        self.assertEqual(task_templates.first_run(monthly, date(2026, 10, 16)), date(2026, 11, 15))
        weekly = {"frequency": "weekly", "interval_count": 1, "weekday": 0}  # Monday
        self.assertEqual(task_templates.first_run(weekly, date(2026, 10, 28)), date(2026, 11, 2))
        self.assertEqual(task_templates.first_run({"frequency": "daily"}, date(2026, 10, 28)), date(2026, 10, 28))
        yearly = {"frequency": "yearly", "interval_count": 1, "month_of_year": 3, "day_of_month": 31}
        self.assertEqual(task_templates.first_run(yearly, date(2026, 4, 1)), date(2027, 3, 31))

    def test_each_kind_steps_by_its_interval(self):
        self.assertEqual(task_templates.following({"frequency": "daily", "interval_count": 3}, date(2026, 10, 28)), date(2026, 10, 31))
        self.assertEqual(task_templates.following({"frequency": "weekly", "interval_count": 2}, date(2026, 10, 28)), date(2026, 11, 11))
        self.assertEqual(task_templates.following({"frequency": "yearly", "interval_count": 1, "month_of_year": 2, "day_of_month": 29}, date(2024, 2, 29)), date(2025, 2, 28))

    def test_the_schedule_is_said_in_words(self):
        self.assertEqual(task_templates.describe({"frequency": None}), "Not scheduled")
        self.assertEqual(task_templates.describe({"frequency": "monthly", "interval_count": 1, "day_of_month": 15}), "Every month on day 15")
        self.assertEqual(task_templates.describe({"frequency": "weekly", "interval_count": 2, "weekday": 4}), "Every 2 weeks on Friday")


class SchemaAndRoutesTests(unittest.TestCase):
    def test_the_file_is_registered_everywhere(self):
        self.assertIn("migrate_tasks.sql", [p.name for p in entities.SQL_MIGRATIONS])
        for script in ("init_db_mac.sh", "init_db_windows.ps1"):
            self.assertIn("migrate_tasks.sql", (ROOT / "scripts" / script).read_text(encoding="utf-8"))

    def test_a_task_and_its_history_are_kept_for_ever(self):
        sql = (SQL / "migrate_tasks.sql").read_text(encoding="utf-8")
        self.assertIn("BEFORE DELETE ON orion_ods.task ", sql)
        self.assertIn("BEFORE UPDATE OR DELETE ON orion_ods.task_activity", sql)
        self.assertNotIn("DROP TABLE", sql)
        self.assertIn("task_review_one_pending_uidx", sql)
        self.assertIn("task_sprint_one_active_uidx", sql)

    def test_the_sql_editor_treats_every_task_table_as_the_applications_own(self):
        for name in ("task", "task_project", "task_member", "task_status", "task_comment", "task_activity", "task_attachment", "task_file", "task_todo", "task_notification", "task_template"):
            self.assertTrue(sql_guard.OWNED_TABLES.match(name), name)

    def test_every_task_route_needs_a_signed_in_person(self):
        from app.routers import tasks_router

        self.assertGreater(len(tasks_router.router.routes), 60)
        for route in tasks_router.router.routes:
            dependants = {getattr(d.call, "__name__", "") for d in route.dependant.dependencies}
            self.assertIn("get_current_user", dependants, f"{route.methods} {route.path} has no sign-in dependency")

    def test_a_private_project_is_not_visible_to_a_stranger_in_the_listing_condition(self):
        condition, params = common.visible_sql({"id": 5, "role": "editor"})
        self.assertIn("Company", condition)
        self.assertEqual(params, [5])
        self.assertEqual(common.visible_sql({"id": 1, "role": "admin"}), ("TRUE", []))

    def test_the_inbox_kinds_the_code_uses_are_known(self):
        self.assertIn("review_requested", task_notify.KINDS)
        self.assertIn("mentioned", task_notify.KINDS)


def _patched(raw, modules):
    """Every module takes its connection from one transaction (a savepoint for each use, so a refusal undoes only itself) that the test rolls back."""
    names = itertools.count(1)

    @contextlib.contextmanager
    def cursor(commit=False):
        cur = raw.cursor()
        name = f"t_{next(names)}"
        cur.execute(f"SAVEPOINT {name}")
        try:
            yield cur
        except BaseException:
            cur.execute(f"ROLLBACK TO SAVEPOINT {name}")
            raise
        finally:
            cur.close()

    saved = {m: m.db_cursor for m in modules}
    for module in modules:
        module.db_cursor = cursor
    return lambda: [setattr(m, "db_cursor", original) for m, original in saved.items()]


@unittest.skipUnless(RUN, "needs the development database: set ORION_DB_TESTS=1")
class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        from app import database, task_files, task_sprints, task_todo, task_views, tasks

        self.m = {"tasks": tasks, "items": task_items, "files": task_files, "todo": task_todo, "views": task_views, "sprints": task_sprints, "templates": task_templates, "notify": task_notify}
        self.raw = database.raw_connection()
        self.addCleanup(self.raw.close)
        self.addCleanup(self.raw.rollback)
        self.addCleanup(_patched(self.raw, list(self.m.values())))
        cur = self.raw.cursor()
        ids = []
        for n, role in enumerate(("editor", "editor", "viewer")):
            cur.execute("INSERT INTO orion_ods.app_user (username, display_name, password_hash, role) VALUES (%s, %s, 'x', %s) RETURNING id", (f"zz_task_{n}_{os.getpid()}", f"ZZ Person {n}", role))
            ids.append(cur.fetchone()[0])
        cur.close()
        self.a = {"id": ids[0], "role": "editor"}
        self.b = {"id": ids[1], "role": "editor"}
        self.c = {"id": ids[2], "role": "viewer"}
        self.admin = {"id": 1, "role": "admin"}
        self.tasks = tasks
        self.project = tasks.create_project(self.a, {"key": f"Z{os.getpid() % 100000}", "name": "ZZ test project"})
        self.pk = self.project["key"]

    def new(self, title="A job", **extra):
        return self.tasks.create_task(self.a, self.pk, {"title": title, **extra})

    def status(self, category):
        return next(s for s in self.tasks.get_project(self.a, self.pk)["statuses"] if s["category"] == category)

    # -- projects
    def test_a_new_project_has_the_default_workflow_and_its_maker_manages_it(self):
        self.assertEqual([s["category"] for s in self.project["statuses"]], [c for _n, c in common.DEFAULT_STATUSES])
        self.assertEqual(self.project["role"], "Manager")
        with self.assertRaises(common.TaskError):
            self.tasks.create_project(self.b, {"key": self.pk, "name": "again"})
        with self.assertRaises(common.TaskError):
            self.tasks.create_project(self.b, {"key": "x", "name": "bad key"})

    def test_a_private_project_is_invisible_to_those_outside_it_and_open_to_admins(self):
        private = self.tasks.create_project(self.a, {"key": f"P{os.getpid() % 100000}", "name": "Private", "visibility": "Private"})
        with self.assertRaises(common.NotFound):
            self.tasks.get_project(self.b, private["key"])
        self.assertNotIn(private["key"], [p["key"] for p in self.tasks.list_projects(self.b)])
        self.assertIn(private["key"], [p["key"] for p in self.tasks.list_projects(self.admin)])
        self.tasks.set_member(self.a, private["key"], self.b["id"], "Member")
        self.assertEqual(self.tasks.get_project(self.b, private["key"])["role"], "Member")

    def test_a_project_always_keeps_a_manager(self):
        with self.assertRaises(common.TaskError):
            self.tasks.set_member(self.a, self.pk, self.a["id"], "Member")
        with self.assertRaises(common.TaskError):
            self.tasks.set_member(self.a, self.pk, self.a["id"], None)
        with self.assertRaises(common.Forbidden):
            self.tasks.set_member(self.b, self.pk, self.c["id"], "Viewer")

    # -- tasks
    def test_a_task_is_numbered_in_its_project_and_starts_in_the_first_status(self):
        first, second = self.new("One"), self.new("Two")
        self.assertEqual((first["key"], second["key"]), (f"{self.pk}-1", f"{self.pk}-2"))
        self.assertEqual(first["status"]["category"], "todo")
        self.assertEqual(first["reporter"]["id"], self.a["id"])
        self.assertTrue(first["watching"])

    def test_assigning_tells_the_assignee_and_not_the_person_who_did_it(self):
        task = self.new("For B", assignee_id=self.b["id"])
        inbox = task_notify.inbox(self.b)
        self.assertTrue(any(i["kind"] == "assigned" and i["task_key"] == task["key"] for i in inbox["items"]))
        self.assertFalse(any(i["task_key"] == task["key"] for i in task_notify.inbox(self.a)["items"]))

    def test_a_viewer_can_look_and_comment_but_not_change(self):
        private = self.tasks.create_project(self.a, {"key": f"V{os.getpid() % 100000}", "name": "Viewed", "visibility": "Private"})
        self.tasks.set_member(self.a, private["key"], self.c["id"], "Viewer")
        task = self.tasks.create_task(self.a, private["key"], {"title": "Look"})
        self.assertEqual(self.tasks.get_task(self.c, task["key"])["title"], "Look")
        with self.assertRaises(common.Forbidden):
            self.tasks.update_task(self.c, task["key"], {"title": "Changed"})
        self.assertTrue(task_items.add_comment(self.c, task["key"], "Looks fine to me")["id"])

    def test_two_people_saving_the_same_task_do_not_overwrite_each_other(self):
        task = self.new("Race")
        self.tasks.update_task(self.a, task["key"], {"priority": "High"})
        with self.assertRaises(common.Conflict):
            self.tasks.update_task(self.b, task["key"], {"priority": "Low"}, expected_updated=task["updated"])

    def test_changes_are_recorded_in_the_history_and_dates_are_checked(self):
        task = self.new("History")
        self.tasks.update_task(self.a, task["key"], {"due_date": "2026-12-01", "priority": "Critical", "labels": ["GST", "month end"]})
        lines = [i["text"] for i in task_items.activity(self.a, task["key"])]
        self.assertTrue(any("due date" in line for line in lines))
        with self.assertRaises(common.TaskError):
            self.tasks.update_task(self.a, task["key"], {"start_date": "2026-12-05", "due_date": "2026-12-01"})

    # -- moving, review, done
    def test_a_task_is_done_only_when_nothing_blocks_it_and_its_subtasks_are_done(self):
        parent, blocker = self.new("Parent"), self.new("Blocker")
        child = self.new("Child", type="Sub-task", parent_key=parent["key"])
        done = self.status("done")["id"]
        with self.assertRaises(common.TaskError) as why:
            self.tasks.transition(self.a, parent["key"], done)
        self.assertIn(child["key"], str(why.exception))
        task_items.add_link(self.a, parent["key"], "blocked_by", blocker["key"])
        self.tasks.transition(self.a, child["key"], done)
        with self.assertRaises(common.TaskError) as why:
            self.tasks.transition(self.a, parent["key"], done)
        self.assertIn(blocker["key"], str(why.exception))
        self.tasks.transition(self.a, blocker["key"], done)
        finished = self.tasks.transition(self.a, parent["key"], done)
        self.assertEqual((finished["status"]["category"], finished["resolution"]), ("done", "Done"))
        self.assertIsNotNone(finished["resolved"])
        reopened = self.tasks.transition(self.a, parent["key"], self.status("todo")["id"])
        self.assertIsNone(reopened["resolution"])

    def test_a_blocking_cycle_is_refused(self):
        first, second, third = self.new("1"), self.new("2"), self.new("3")
        task_items.add_link(self.a, first["key"], "blocks", second["key"])
        task_items.add_link(self.a, second["key"], "blocks", third["key"])
        with self.assertRaises(common.TaskError):
            task_items.add_link(self.a, third["key"], "blocks", first["key"])

    def test_sending_for_review_needs_someone_else_and_the_reviewer_decides(self):
        task = self.new("Review me", assignee_id=self.a["id"])
        review = self.status("review")["id"]
        with self.assertRaises(common.TaskError):
            self.tasks.transition(self.a, task["key"], review)  # nobody to review it
        with self.assertRaises(common.TaskError):
            self.tasks.transition(self.a, task["key"], review, reviewer_id=self.a["id"])  # the person doing the work cannot review it
        sent = self.tasks.transition(self.a, task["key"], review, reviewer_id=self.b["id"], note="Please check the figures")
        self.assertEqual(sent["pending_review"]["reviewer"]["id"], self.b["id"])
        self.assertTrue(any(i["kind"] == "review_requested" for i in task_notify.inbox(self.b)["items"]))
        with self.assertRaises(common.Forbidden):
            self.tasks.decide_review(self.c, task["key"], "approve")  # neither the reviewer nor a manager
        with self.assertRaises(common.TaskError):
            self.tasks.decide_review(self.b, task["key"], "changes")  # a reason is needed
        back = self.tasks.decide_review(self.b, task["key"], "changes", "Totals do not add up")
        self.assertEqual(back["status"]["category"], "doing")
        self.tasks.transition(self.a, task["key"], review, reviewer_id=self.b["id"])
        approved = self.tasks.decide_review(self.b, task["key"], "approve", "Good")
        self.assertEqual((approved["status"]["category"], approved["resolution"]), ("done", "Done"))
        self.assertEqual([r["status"] for r in approved["reviews"]], ["Approved", "Changes requested"])

    def test_a_project_that_requires_review_does_not_let_a_member_finish_a_task_alone(self):
        self.tasks.update_project(self.a, self.pk, {"require_review": True})
        self.tasks.set_member(self.a, self.pk, self.b["id"], "Member")
        task = self.new("Needs review", assignee_id=self.b["id"])
        with self.assertRaises(common.TaskError):
            self.tasks.transition(self.b, task["key"], self.status("done")["id"])
        self.assertEqual(self.tasks.transition(self.a, task["key"], self.status("done")["id"])["status"]["category"], "done")  # a manager may

    def test_a_full_column_stops_a_member_but_not_a_manager(self):
        doing = next(s for s in self.tasks.get_project(self.a, self.pk)["statuses"] if s["name"] == "In Progress")
        self.tasks.update_status(self.a, self.pk, doing["id"], {"wip_limit": 1})
        self.tasks.set_member(self.a, self.pk, self.b["id"], "Member")
        first, second = self.new("One"), self.new("Two")
        self.tasks.transition(self.b, first["key"], doing["id"])
        with self.assertRaises(common.TaskError):
            self.tasks.transition(self.b, second["key"], doing["id"])
        self.tasks.transition(self.a, second["key"], doing["id"])

    def test_dragging_puts_a_task_where_it_was_dropped(self):
        one, two, three = self.new("1"), self.new("2"), self.new("3")
        self.tasks.transition(self.a, three["key"], one["status"]["id"], before_key=one["key"])
        order = [t["key"] for t in self.tasks.list_tasks(self.a, {"project": self.pk, "sort": "rank"})["tasks"]]
        self.assertEqual(order, [three["key"], one["key"], two["key"]])

    # -- the things on a task
    def test_comments_tell_the_people_named_and_only_the_author_changes_one(self):
        task = self.new("Talk")
        mention = f"@[ZZ Person 1](user:{self.b['id']})"
        comment = task_items.add_comment(self.a, task["key"], f"{mention} can you check this?")
        self.assertTrue(any(i["kind"] == "mentioned" for i in task_notify.inbox(self.b)["items"]))
        with self.assertRaises(common.Forbidden):
            task_items.edit_comment(self.b, comment["id"], "changed")
        task_items.edit_comment(self.a, comment["id"], "edited")
        task_items.delete_comment(self.a, comment["id"])
        self.assertTrue(task_items.list_comments(self.a, task["key"])[0]["deleted"])

    def test_the_checklist_the_time_and_the_links(self):
        task = self.new("Details")
        checklist = task_items.add_checklist_item(self.a, task["key"], "Collect the challans")
        task_items.update_checklist_item(self.a, checklist[0]["id"], done=True)
        logged = task_items.log_time(self.a, task["key"], 90, None, "Prepared")
        self.assertEqual(logged["spent_minutes"], 90)
        with self.assertRaises(common.TaskError):
            task_items.log_time(self.a, task["key"], 30, (date.today() + timedelta(days=2)).isoformat())
        detail = self.tasks.get_task(self.a, task["key"])
        self.assertEqual((detail["checklist"]["done"], detail["spent_minutes"]), (1, 90))
        with self.assertRaises(common.Forbidden):
            task_items.delete_time(self.b, task["key"], logged["logs"][0]["id"])  # not their time
        self.assertEqual(task_items.delete_time(self.a, task["key"], logged["logs"][0]["id"])["spent_minutes"], 0)

    def test_a_file_is_checked_kept_once_and_freed_when_the_last_use_goes(self):
        from app import task_files

        task = self.new("Files")
        added = task_files.add_attachment(self.a, task["key"], "scan.png", PNG)
        again = task_files.add_attachment(self.b, task["key"], "same.png", PNG)
        self.assertEqual(len(again), 2)
        with self.assertRaises(common.TaskError):
            task_files.add_attachment(self.a, task["key"], "tool.exe", b"MZ" + b"\x00" * 10)
        with self.assertRaises(common.TaskError):
            task_files.add_attachment(self.a, task["key"], "fake.png", b"not a picture")
        fetched = task_files.get_file(self.b, added[0]["id"])
        self.assertEqual((fetched["data"], fetched["inline"]), (PNG, True))
        cur = self.raw.cursor()
        cur.execute("SELECT COUNT(*) FROM orion_ods.task_file")
        before = cur.fetchone()[0]
        task_files.delete_attachment(self.a, added[0]["id"])
        cur.execute("SELECT COUNT(*) FROM orion_ods.task_file")
        self.assertEqual(cur.fetchone()[0], before)  # the other attachment still uses the bytes
        task_files.delete_attachment(self.b, again[1]["id"])
        cur.execute("SELECT COUNT(*) FROM orion_ods.task_file")
        self.assertEqual(cur.fetchone()[0], before - 1)
        cur.close()

    def test_a_file_of_a_private_task_is_not_given_to_a_stranger(self):
        from app import task_files

        private = self.tasks.create_project(self.a, {"key": f"F{os.getpid() % 100000}", "name": "Secret", "visibility": "Private"})
        task = self.tasks.create_task(self.a, private["key"], {"title": "Hidden"})
        files = task_files.add_attachment(self.a, task["key"], "secret.png", PNG)
        with self.assertRaises(common.NotFound):
            task_files.get_file(self.b, files[0]["id"])

    # -- finding and counting
    def test_the_list_follows_filters_and_only_shows_what_the_person_may_see(self):
        self.new("Pay the PF", labels=["pf"], assignee_id=self.b["id"], due_date=(date.today() - timedelta(days=2)).isoformat())
        self.new("File the GST return", labels=["gst"])
        private = self.tasks.create_project(self.a, {"key": f"H{os.getpid() % 100000}", "name": "Hidden", "visibility": "Private"})
        self.tasks.create_task(self.a, private["key"], {"title": "Pay the secret"})
        found = self.tasks.list_tasks(self.b, {"q": "pay the"})
        self.assertEqual([t["title"] for t in found["tasks"]], ["Pay the PF"])
        self.assertEqual(self.tasks.list_tasks(self.a, {"project": self.pk, "label": "gst"})["total"], 1)
        late = self.tasks.list_tasks(self.b, {"assignee": "me", "due": "overdue"})
        self.assertEqual(late["tasks"][0]["overdue"], True)
        self.assertEqual(self.tasks.list_tasks(self.admin, {"q": "secret"})["total"], 1)

    def test_a_filter_cannot_be_used_to_inject_sql(self):
        self.new("Safe")
        got = self.tasks.list_tasks(self.a, {"q": "x'; DROP TABLE orion_ods.task; --", "sort": "t.task_no; DROP TABLE x", "label": "a' OR '1'='1"})
        self.assertEqual(got["tasks"], [])
        self.assertEqual(self.tasks.list_tasks(self.a, {"project": self.pk})["total"], 1)

    def test_bulk_changes_report_what_could_not_be_changed(self):
        one, two = self.new("1"), self.new("2")
        result = self.tasks.bulk_update(self.a, [one["key"], two["key"], "NOPE-1"], {"priority": "High"})
        self.assertEqual(sorted(result["changed"]), sorted([one["key"], two["key"]]))
        self.assertEqual(result["failed"][0]["key"], "NOPE-1")
        self.assertEqual(self.tasks.get_task(self.a, one["key"])["priority"], "High")

    def test_a_deleted_task_is_hidden_and_can_be_brought_back(self):
        task = self.new("Gone")
        self.tasks.delete_task(self.a, task["key"])
        with self.assertRaises(common.NotFound):
            self.tasks.get_task(self.a, task["key"])
        self.assertEqual(self.tasks.restore_task(self.a, task["key"])["key"], task["key"])

    # -- sprints
    def test_a_sprint_is_started_and_completed_and_what_is_left_goes_back(self):
        from app import task_sprints

        task_sprints.create_sprint(self.a, self.pk, {"name": "Sprint 1"})
        sprint = task_sprints.list_sprints(self.a, self.pk)[0]
        finished, left = self.new("Finish me", sprint_id=sprint["id"]), self.new("Leave me", sprint_id=sprint["id"])
        task_sprints.start_sprint(self.a, self.pk, sprint["id"])
        task_sprints.create_sprint(self.a, self.pk, {"name": "Sprint 2"})
        planned = next(x for x in task_sprints.list_sprints(self.a, self.pk) if x["state"] == "Planned")
        with self.assertRaises(common.TaskError):
            task_sprints.start_sprint(self.a, self.pk, planned["id"])  # one sprint at a time
        self.tasks.transition(self.a, finished["key"], self.status("done")["id"])
        done = task_sprints.complete_sprint(self.a, self.pk, sprint["id"])
        self.assertEqual((done["summary"]["done"], done["summary"]["unfinished"]), (1, 1))
        self.assertIsNone(self.tasks.get_task(self.a, left["key"])["sprint"])
        self.assertEqual(self.tasks.get_task(self.a, finished["key"])["sprint"]["name"], "Sprint 1")

    # -- the person's own to-do
    def test_the_todo_list_is_private_and_an_item_can_become_a_task(self):
        from app import task_todo

        task_todo.add_item(self.a, {"text": "Call the auditor", "my_day": date.today().isoformat()})
        overview = task_todo.overview(self.a)
        item = overview["items"][0]
        self.assertTrue(item["in_my_day"])
        self.assertEqual(task_todo.overview(self.b)["items"], [])
        with self.assertRaises(common.NotFound):
            task_todo.update_item(self.b, item["id"], {"done": True})
        made = task_todo.make_task(self.a, item["id"], self.pk)
        self.assertEqual(made["task"]["title"], "Call the auditor")
        self.assertTrue(task_todo.overview(self.a)["items"][0]["done"])
        with self.assertRaises(common.TaskError):
            task_todo.make_task(self.a, item["id"], self.pk)

    # -- templates and the tasks that come back
    def test_a_schedule_makes_its_task_once_and_moves_on(self):
        today = date.today()
        task_templates.save_template(self.a, self.pk, {"name": "PF", "title": "Pay PF and ESI", "assignee_id": self.b["id"], "frequency": "monthly", "day_of_month": today.day,
                                                      "due_offset_days": 5, "checklist": ["Upload the return", "Pay the challan"], "labels": ["pf"]})
        template = task_templates.list_templates(self.a, self.pk)[0]
        self.assertEqual(template["next_run"], today.isoformat())
        self.assertEqual(task_templates.run_due(today), 1)
        self.assertEqual(task_templates.run_due(today), 0)  # nothing more until the next month
        made = self.tasks.list_tasks(self.a, {"project": self.pk, "label": "pf"})["tasks"][0]
        self.assertEqual((made["title"], made["recurring"], made["due_date"]), ("Pay PF and ESI", True, (today + timedelta(days=5)).isoformat()))
        self.assertEqual(self.tasks.get_task(self.a, made["key"])["checklist"]["total"], 2)
        later = task_templates.list_templates(self.a, self.pk)[0]
        self.assertGreater(later["next_run"], today.isoformat())

    def test_a_schedule_that_fell_behind_makes_one_task_not_a_pile(self):
        today = date.today()
        task_templates.save_template(self.a, self.pk, {"name": "Daily", "title": "Check the guards' rota", "assignee_id": self.a["id"], "frequency": "daily", "next_run": (today - timedelta(days=5)).isoformat()})
        self.assertEqual(task_templates.run_due(today), 1)
        self.assertEqual(task_templates.list_templates(self.a, self.pk)[0]["next_run"], (today + timedelta(days=1)).isoformat())

    # -- views
    def test_the_views_read_without_error(self):
        from app import task_views

        task = self.new("Shown", assignee_id=self.a["id"], due_date=date.today().isoformat())
        mine = task_views.mine(self.a)
        self.assertIn(task["key"], [t["key"] for t in mine["buckets"]["today"]])
        board = task_views.board(self.a, self.pk)
        self.assertEqual([c["category"] for c in board["columns"]], [c for _n, c in common.DEFAULT_STATUSES])
        self.assertEqual(sum(c["count"] for c in board["columns"]), 1)
        cal = task_views.calendar(self.a, date.today().isoformat(), (date.today() + timedelta(days=20)).isoformat())
        self.assertIn(date.today().isoformat(), cal["days"])
        report = task_views.reports(self.a, self.pk)
        self.assertEqual(report["open"], 1)
        self.assertEqual(len(report["flow"]), 12)
        self.assertEqual(task_views.search(self.a, "shown")["tasks"][0]["key"], task["key"])
        saved = task_views.save_filter(self.a, "Mine open", {"assignee": "me", "open": True, "evil": "x"}, project_key=self.pk)
        self.assertEqual(saved[0]["definition"], {"assignee": "me", "open": True})
        task_views.delete_filter(self.a, saved[0]["id"])

    def test_notifications_are_read_by_their_owner_only(self):
        self.new("Ping", assignee_id=self.b["id"])
        unread = task_notify.inbox(self.b, unread_only=True)
        self.assertGreaterEqual(unread["unread"], 1)
        self.assertEqual(task_notify.mark_read(self.a, [i["id"] for i in unread["items"]]), 0)  # not theirs
        task_notify.mark_read(self.b)
        self.assertEqual(task_notify.unread_count(self.b["id"]), 0)


if __name__ == "__main__":
    unittest.main()
