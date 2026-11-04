"""The backup guard and helpers. No database, network or pg_dump is needed."""

from dataclasses import replace
from datetime import datetime, timezone

import pytest
from pyrage import x25519

from app import backup
from app.backup import BackupConfig

PUBLIC = str(x25519.Identity.generate().to_public())


def config(**changes) -> BackupConfig:
    base = BackupConfig(
        enabled=True, role="dev", endpoint="https://s3.example.com", region="r", bucket="DevPostgres",
        key_id="keyid123", key="secretkey456", recipients=(PUBLIC,), db_user="orion_backup", db_password="dbpw789",
        interval_hours=24, alert_email="", app_env="development", db_name="orion", db_host="localhost", db_port=5432,
        app_db_user="orion_user", prod_db_name="orion_prod",
    )
    return replace(base, **changes)


def check(cfg: BackupConfig) -> list[str]:
    return backup.problems(cfg, check_tools=False)


def test_a_correct_dev_setup_has_no_problems():
    assert check(config()) == []


def test_a_correct_prod_setup_has_no_problems():
    prod = config(role="prod", bucket="ProdPostgres", app_env="production", db_name="orion_prod")
    assert check(prod) == []


@pytest.mark.parametrize(
    "changes",
    [
        {"role": "prod", "bucket": "ProdPostgres"},  # prod bucket on the dev machine
        {"role": "prod", "bucket": "ProdPostgres", "app_env": "production"},  # prod env but the dev database
        {"role": "prod", "bucket": "ProdPostgres", "db_name": "orion_prod"},  # prod database but not production env
        {"role": "dev", "app_env": "production"},  # the prod machine with a dev bucket
        {"role": "dev", "db_name": "orion_prod"},
        {"role": "prod", "bucket": "DevPostgres", "app_env": "production", "db_name": "orion_prod"},  # names disagree
        {"role": "dev", "bucket": "ProdPostgres"},
        {"role": ""},
        {"role": "staging"},
    ],
)
def test_the_wrong_machine_is_refused(changes):
    assert check(config(**changes))


def test_it_is_off_unless_switched_on():
    assert any("switched off" in p for p in check(config(enabled=False)))


@pytest.mark.parametrize("field", ["bucket", "endpoint", "key_id", "key", "db_user", "db_password"])
def test_missing_settings_are_named(field):
    assert check(config(**{field: ""}))


def test_encryption_needs_a_valid_public_key():
    assert check(config(recipients=()))
    assert check(config(recipients=("not-a-key",)))
    private = str(x25519.Identity.generate())
    assert check(config(recipients=(private,)))


def test_the_endpoint_must_be_https():
    assert check(config(endpoint="http://s3.example.com"))


def test_backups_may_not_run_as_the_application_user():
    assert check(config(db_user="orion_user"))


def test_secrets_are_scrubbed_from_messages():
    cfg = config()
    text = backup.scrub("failed with secretkey456 and keyid123 and dbpw789 for orion_backup", cfg)
    assert "secretkey456" not in text and "keyid123" not in text and "dbpw789" not in text
    assert "orion_backup" in text


def test_a_first_backup_of_the_day_and_month_is_kept_longer():
    assert backup.prefixes_for(False, False) == ["daily", "monthly"]
    assert backup.prefixes_for(False, True) == ["daily"]
    assert backup.prefixes_for(True, False) == ["recent", "monthly"]
    assert backup.prefixes_for(True, True) == ["recent"]


def test_object_keys_carry_the_prefix_and_database():
    when = datetime(2026, 10, 4, 12, 30, 5, tzinfo=timezone.utc)
    key = backup.object_key("daily", config(db_name="orion_prod"), when, "ab12cd34ef")
    assert key == "daily/orion_prod/2026/10/orion_prod-20261004T123005Z-ab12cd34.dump.age"


def test_the_four_schemas_are_the_ones_backed_up():
    assert backup.SCHEMAS == ("orion_ods", "orion_dw", "tally_ods", "tally_dw")


def test_the_api_offers_no_way_to_read_a_backup():
    from app.routers import backup_router

    paths = {(route.path, tuple(sorted(route.methods))) for route in backup_router.router.routes}
    assert paths == {("/backup/status", ("GET",)), ("/backup/run", ("POST",))}
