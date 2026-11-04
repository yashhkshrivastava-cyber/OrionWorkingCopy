"""Make the key pair that locks Orion's database backups.

Run this on a machine that is NOT the office PC (your own laptop). It writes the private key to a file and prints the
public key. Only the public key goes into Orion's .env (ORION_BACKUP_AGE_RECIPIENTS); it can lock backups but not open
them. Keep the private key somewhere safe and away from the office PC, in at least two places (a password manager and
a printed copy in a safe, say). Lose it and every backup is unreadable; leak it and anyone with the backup files can read
them.

    python scripts/backup_keygen.py orion-backup-private.key
"""

import sys
from pathlib import Path

from pyrage import x25519


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    target = Path(sys.argv[1])
    if target.exists():
        print(f"{target} already exists; refusing to overwrite a key.")
        return 1
    identity = x25519.Identity.generate()
    target.write_text(f"# Orion backup private key. Keep offline. Never put on the office PC.\n{identity}\n", encoding="utf-8")
    print(f"Private key written to {target}. Move it somewhere safe now.")
    print("\nPut this public key in .env as ORION_BACKUP_AGE_RECIPIENTS:\n")
    print(identity.to_public())
    return 0


if __name__ == "__main__":
    sys.exit(main())
