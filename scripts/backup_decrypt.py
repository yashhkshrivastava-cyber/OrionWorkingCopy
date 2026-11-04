"""Unlock a downloaded Orion backup, ready for pg_restore.

    python scripts/backup_decrypt.py orion_prod-20261004T100000Z-ab12cd34.dump.age orion-backup-private.key restore.dump

Do this on the machine you restore from, never the office PC. Then, into an empty database:

    pg_restore --no-owner --no-acl -d orion_restore restore.dump

The decrypted file holds all the company data: delete it when the restore is done. docs/backup.md has the full steps.
"""

import sys
from pathlib import Path

import pyrage
from pyrage import x25519


def main() -> int:
    if len(sys.argv) != 4:
        print(__doc__)
        return 2
    source, key_file, target = (Path(arg) for arg in sys.argv[1:])
    if target.exists():
        print(f"{target} already exists; refusing to overwrite.")
        return 1
    lines = [line.strip() for line in key_file.read_text(encoding="utf-8").splitlines()]
    secret = next((line for line in lines if line.startswith("AGE-SECRET-KEY-")), None)
    if not secret:
        print("That file has no AGE-SECRET-KEY line.")
        return 1
    identity = x25519.Identity.from_str(secret)
    try:
        with open(source, "rb") as src, open(target, "wb") as dst:
            pyrage.decrypt_io(src, dst, [identity])
    except pyrage.DecryptError as exc:
        target.unlink(missing_ok=True)
        print(f"Could not unlock the backup with that key: {exc}")
        return 1
    print(f"Unlocked to {target}. Delete it when you are done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
