"""Filters on the columns of a table: what is accepted, the SQL they become (every value a parameter, never text), that the browser's list of
conditions is the server's, and that every table route takes them. No database is needed (the cursor is stubbed where one is read)."""

import json
import re
import sys
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from fastapi.routing import APIRoute  # noqa: E402

from app import column_filters as cf, db_utils  # noqa: E402
from app.routers import dashboard_router, dw_router, entities_router, tally_dashboard_router, tally_dw_router, tally_router  # noqa: E402

FRONTEND = ROOT / "frontend" / "src"
SPECS = {
    "name": ('"name"', "text"),
    "amount": ('"amount"', "number"),
    "day": ('"day"', "date"),
    "flag": ('"flag"', "bool"),
}


def flt(column, op, **rest):
    return {"column": column, "op": op, "value": rest.get("value"), "value2": rest.get("value2"), "values": rest.get("values"), "empty": rest.get("empty", False)}


class Reading(unittest.TestCase):
    def test_nothing_is_no_filters(self):
        self.assertEqual(cf.parse(None), [])
        self.assertEqual(cf.parse("  "), [])

    def test_a_filter_is_shaped_and_limited(self):
        found = cf.parse(json.dumps([{"column": "name", "op": "contains", "value": "abc"}]))
        self.assertEqual(found, [flt("name", "contains", value="abc")])

    def test_what_is_not_a_filter_is_refused(self):
        for bad in ("not json", "{}", '[{"op": "contains"}]', '[{"column": 1, "op": "contains"}]', '["x"]',
                    json.dumps([{"column": "a", "op": "contains"}, {"column": "a", "op": "empty"}]),  # one per column
                    json.dumps([{"column": f"c{i}", "op": "empty"} for i in range(cf.MAX_FILTERS + 1)]),
                    json.dumps([{"column": "a", "op": "in", "values": ["x"] * (cf.MAX_VALUES + 1)}]),
                    json.dumps([{"column": "a", "op": "contains", "value": "x" * (cf.MAX_TEXT + 1)}]),
                    "x" * (cf.MAX_JSON + 1)):
            with self.assertRaises(cf.FilterError, msg=bad[:50]):
                cf.parse(bad)


class TheSql(unittest.TestCase):
    def build(self, *filters, skip=None):
        return cf.build(list(filters), SPECS, skip)

    def test_no_filters_no_condition(self):
        self.assertEqual(self.build(), ("", []))

    def test_text_conditions(self):
        sql, params = self.build(flt("name", "contains", value="50%_off"))
        self.assertIn("ILIKE %s ESCAPE", sql)
        self.assertEqual(params, ["%50\\%\\_off%"])  # the percent and the underscore are text, not wildcards
        self.assertEqual(self.build(flt("name", "starts", value="ab"))[1], ["ab%"])
        self.assertEqual(self.build(flt("name", "ends", value="ab"))[1], ["%ab"])
        self.assertIn("NOT", self.build(flt("name", "not_contains", value="x"))[0])
        sql, params = self.build(flt("name", "equals", value="Won"))
        self.assertIn("lower(", sql)
        self.assertEqual(params, ["Won"])

    def test_number_and_date_conditions_are_converted_first(self):
        sql, params = self.build(flt("amount", "gt", value="1,250.50"))
        self.assertIn("> %s", sql)
        self.assertEqual(str(params[0]), "1250.50")
        sql, params = self.build(flt("amount", "between", value="9", value2="3"))
        self.assertIn("BETWEEN %s AND %s", sql)
        self.assertEqual([str(p) for p in params], ["3", "9"])  # either order
        sql, params = self.build(flt("day", "gte", value="2026-04-01"))
        self.assertIn("::date >= %s", sql)
        self.assertEqual(str(params[0]), "2026-04-01")
        self.assertIn("IS DISTINCT FROM", self.build(flt("amount", "ne", value="1"))[0])

    def test_a_bad_number_or_date_is_refused_not_passed_on(self):
        for column, op, value in (("amount", "gt", "abc"), ("amount", "eq", "1; DROP TABLE x"), ("amount", "gt", "NaN"), ("day", "eq", "yesterday")):
            with self.assertRaises(cf.FilterError):
                self.build(flt(column, op, value=value))

    def test_a_pick_is_one_list_parameter_and_may_take_the_empty_rows(self):
        sql, params = self.build(flt("name", "in", values=["Won", "Open"]))
        self.assertIn("= ANY(%s)", sql)
        self.assertEqual(params, [["Won", "Open"]])
        sql, params = self.build(flt("name", "in", values=["Won"], empty=True))
        self.assertIn(" OR ", sql)
        self.assertEqual(params, [["Won"]])
        sql, params = self.build(flt("name", "in", values=[], empty=True))
        self.assertEqual(params, [])
        with self.assertRaises(cf.FilterError):
            self.build(flt("name", "in", values=[]))

    def test_empty_and_not_empty(self):
        self.assertIn("IS NULL", self.build(flt("name", "empty"))[0])
        self.assertTrue(self.build(flt("name", "not_empty"))[0].startswith("NOT"))

    def test_several_filters_are_all_required(self):
        sql, params = self.build(flt("name", "contains", value="a"), flt("amount", "gt", value="1"))
        self.assertEqual(sql.count(" AND "), 1)
        self.assertEqual(len(params), 2)

    def test_the_request_never_reaches_the_sql_text(self):
        evil = "x'; DROP TABLE orion_ods.case; --"
        for built in (self.build(flt("name", "contains", value=evil)), self.build(flt("name", "in", values=[evil])), self.build(flt("name", "equals", value=evil))):
            self.assertNotIn("DROP", built[0])
            self.assertIn("DROP", str(built[1]))  # it travelled as a parameter
        with self.assertRaises(cf.FilterError):
            self.build(flt('name"; DROP TABLE x; --', "contains", value="a"))

    def test_an_operator_must_suit_the_column(self):
        for column, op in (("amount", "contains"), ("name", "gt"), ("day", "in"), ("flag", "contains"), ("amount", "starts")):
            with self.assertRaises(cf.FilterError, msg=f"{column} {op}"):
                self.build(flt(column, op, value="1", values=["1"]))

    def test_a_filter_can_be_left_out_for_its_own_value_list(self):
        sql, params = self.build(flt("name", "contains", value="a"), flt("amount", "gt", value="1"), skip="name")
        self.assertNotIn("ILIKE", sql)
        self.assertEqual(len(params), 1)

    def test_what_a_column_holds_comes_from_its_database_type(self):
        self.assertEqual([cf.kind_of_type_code(c) for c in (1700, 23, 1082, 1184, 16, 25, 1043, None)], ["number", "number", "date", "date", "bool", "text", "text", "text"])
        self.assertEqual([cf.kind_of_format(f) for f in ("money", "number", "percent", "text", "bill")], ["number", "number", "number", "text", "text"])


class TheBrowsersCopy(unittest.TestCase):
    def test_the_operators_are_the_same_in_the_browser(self):
        text = (FRONTEND / "tables" / "columnFilter.ts").read_text(encoding="utf-8")
        block = text[text.index("export const OPS"):text.index("export const OP_LABEL")]
        for kind, ops in cf.OPS.items():
            line = re.search(rf"{kind}: \[([^\]]*)\]", block).group(1)
            self.assertEqual(re.findall(r"'([a-z_]+)'", line), list(ops), kind)
        self.assertEqual(int(re.search(r"MAX_PICK = (\d+)", text).group(1)), cf.MAX_VALUES)


class ThePreview(unittest.TestCase):
    """fetch_preview builds the filter into its COUNT and SELECT, with every value a parameter."""

    def run_preview(self, **kwargs):
        executed = []

        class Cursor:
            description = [("name", 25), ("amount", 1700), ("day", 1082)]

            def execute(self, sql, params=None):
                executed.append((" ".join(sql.split()), list(params or [])))

            def fetchone(self):
                return (7,)

            def fetchall(self):
                return []

        @contextmanager
        def fake_cursor(commit=False):
            yield Cursor()

        with mock.patch.object(db_utils, "db_cursor", fake_cursor):
            return db_utils.fetch_preview_ex("orion_ods.thing", 10, **kwargs), executed

    def test_the_filter_is_in_the_count_and_the_rows_and_the_kinds_come_back(self):
        found, executed = self.run_preview(filters=cf.parse(json.dumps([{"column": "amount", "op": "gt", "value": "10"}])), search="abc")
        self.assertEqual(found.kinds, {"name": "text", "amount": "number", "day": "date"})
        count_sql, count_params = executed[1]
        self.assertIn("WHERE", count_sql)
        self.assertIn("(\"amount\") > %s", count_sql)
        self.assertEqual(len(count_params), 3 + 1)  # the search over three columns, and the filter
        rows_sql, rows_params = executed[2]
        self.assertTrue(rows_sql.endswith("LIMIT %s"))
        self.assertEqual(rows_params[-1], 10)

    def test_a_column_that_is_not_there_is_refused(self):
        with self.assertRaises(cf.FilterError):
            self.run_preview(filters=cf.parse(json.dumps([{"column": "secret", "op": "empty"}])))

    def test_the_old_way_of_calling_it_still_gives_three_things(self):
        with mock.patch.object(db_utils, "fetch_preview_ex", return_value=db_utils.Preview(["a"], [(1,)], 1, {"a": "text"})):
            self.assertEqual(db_utils.fetch_preview("t", 3), (["a"], [(1,)], 1))

    def test_the_values_of_a_column_ignore_its_own_filter(self):
        executed = []

        class Cursor:
            description = [("name", 25), ("amount", 1700)]

            def execute(self, sql, params=None):
                executed.append((" ".join(sql.split()), list(params or [])))

            def fetchall(self):
                return [("Won", 3), (None, 1)]

        @contextmanager
        def fake_cursor(commit=False):
            yield Cursor()

        filters = cf.parse(json.dumps([{"column": "name", "op": "contains", "value": "zzz"}, {"column": "amount", "op": "gt", "value": "5"}]))
        with mock.patch.object(db_utils, "db_cursor", fake_cursor):
            found = db_utils.fetch_column_values("t", "name", filters=filters, contains="w")
        sql, params = executed[-1]
        self.assertNotIn("zzz", str(params))
        self.assertIn("> %s", sql)
        self.assertIn("GROUP BY 1", sql)
        self.assertEqual(found["values"], [{"value": "Won", "count": 3}, {"value": None, "count": 1}])
        self.assertFalse(found["truncated"])
        with mock.patch.object(db_utils, "db_cursor", fake_cursor), self.assertRaises(cf.FilterError):
            db_utils.fetch_column_values("t", "nope")


class TheRoutes(unittest.TestCase):
    def test_every_table_route_takes_filters_and_offers_values(self):
        for module in (entities_router, dw_router, tally_router, tally_dw_router):
            routes = {route.path.rsplit("/{name}", 1)[1]: route for route in module.router.routes if isinstance(route, APIRoute) and "/{name}/" in route.path}
            for path in ("/preview", "/export"):
                names = {param.name for param in routes[path].dependant.query_params}
                self.assertIn("f", names, f"{module.__name__} {path}")
            values = routes["/values"]
            self.assertTrue(values.dependant.dependencies, module.__name__)  # a permission, like the preview beside it
            self.assertEqual({p.name for p in values.dependant.query_params} >= {"column", "q", "f", "contains"}, True)

    def test_the_drill_through_tables_take_filters_too(self):
        for module in (dashboard_router, tally_dashboard_router):
            route = next(r for r in module.router.routes if isinstance(r, APIRoute) and r.path.endswith("/records/{dataset}"))
            self.assertIn("f", {p.name for p in route.dependant.query_params})

    def test_a_bad_filter_is_a_bad_request_not_a_crash(self):
        from fastapi import HTTPException

        from app.routers.column_filter_params import filters_or_400

        with self.assertRaises(HTTPException) as caught:
            filters_or_400("not json")
        self.assertEqual(caught.exception.status_code, 400)

    def test_a_private_column_cannot_be_filtered_by_someone_who_may_not_see_it(self):
        """An entity's private columns are left out of the source the preview reads, so a filter on one is "no such column"."""
        source = entities_router._shown_source
        with mock.patch.object(entities_router, "can_write_ods", return_value=False), mock.patch.object(entities_router, "source_without", return_value="SELECT name FROM t"):
            self.assertEqual(source({"table": "t", "private_columns": ["salary"]}, {}), "SELECT name FROM t")

    def test_the_dashboard_tables_filter_by_the_columns_they_show(self):
        from app.dashboard import records

        spec = next(iter(records.DATASETS.values()))
        specs = {c["key"]: (c["expr"], cf.kind_of_format(c["format"])) for c in spec["columns"]}
        first = spec["columns"][0]["key"]
        sql, params = cf.build([flt(first, "empty")], specs)
        self.assertIn(spec["columns"][0]["expr"], sql)
        self.assertEqual(params, [])


if __name__ == "__main__":
    unittest.main()
