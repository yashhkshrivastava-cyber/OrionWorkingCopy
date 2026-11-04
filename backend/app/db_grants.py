"""Whether the warehouse grants script has anything to do.

``grants.sql`` runs as the Postgres superuser to make the application's role the owner of the warehouse schemas and tables.
Changing an owner takes an exclusive lock on the table, so running it when everything is already owned by the application
role did nothing useful and could wait on, or deadlock with, a table that autovacuum or a load had. The script is only
run when this check, which reads the catalog and takes no table lock, finds something the application role does not have.
"""

from __future__ import annotations

from app.database import db_cursor

# orion_ods is shared with other owners and only needs to be usable; the three warehouse schemas must be owned.
_SQL = """
SELECT EXISTS (
    SELECT 1
    FROM (VALUES ('orion_ods', FALSE), ('orion_dw', TRUE), ('tally_ods', TRUE), ('tally_dw', TRUE)) AS wanted(name, must_own)
    LEFT JOIN pg_namespace n ON n.nspname = wanted.name
    WHERE n.oid IS NULL
       OR NOT has_schema_privilege(current_user, n.oid, 'USAGE, CREATE')
       OR (wanted.must_own AND pg_get_userbyid(n.nspowner) <> current_user)
)
OR EXISTS (
    SELECT 1
    FROM pg_class c
    JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname IN ('orion_ods', 'orion_dw', 'tally_ods', 'tally_dw')
      AND c.relkind IN ('r', 'p', 'v')
      AND (
          NOT has_table_privilege(current_user, c.oid, 'SELECT, INSERT, UPDATE, DELETE')
          OR (n.nspname <> 'orion_ods' AND pg_get_userbyid(c.relowner) <> current_user)
      )
)
"""


def needed() -> bool:
    """True when a schema is missing or not owned, or a table cannot be used, by the application's database role."""
    try:
        with db_cursor() as cur:
            cur.execute(_SQL)
            return bool(cur.fetchone()[0])
    except Exception:
        # If it cannot be checked, run the script as before rather than skip a grant that is missing.
        return True
