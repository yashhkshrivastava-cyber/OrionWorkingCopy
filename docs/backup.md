# Database backups

Once a day while the API runs, Orion takes an encrypted copy of the four schemas (`orion_ods`, `orion_dw`, `tally_ods`,
`tally_dw`) and uploads it to Backblaze B2. Restoring a backup into an empty database brings the application back
(the `data/` folder of uploads, avatars and chat media is not in it; see "What is not in a backup").

How the pieces are protected:

| Threat | Protection |
|---|---|
| Someone gets into Orion and wants the data | The API can only show status and start a backup. It cannot list, download or delete one. |
| Someone steals the bucket key from `.env` | The key is write-only for one bucket: it can add files, not read, list or delete. |
| Someone gets the backup files from B2 | They are `age`-encrypted to a public key. The private key is not on the office PC or in B2. |
| A dev machine writes into prod, or the reverse | Each bucket has a role; the machine must match it (see below) or nothing runs. |
| Ransomware or a mistake deletes backups | B2 Object Lock holds each file for a retention period; the key could not delete them anyway. |
| The backup job writes to the database | It runs as `orion_backup`, a read-only role. |

## Prod or dev: how the machine is identified

`ORION_BACKUP_BUCKET_ROLE` is `prod` or `dev`. A `prod` bucket is written only if `ORION_ENV=production` **and** the
database is `orion_prod`. A `dev` bucket only if neither is true. Bucket names containing "dev" or "prod" must agree with
the role. Any mismatch means backups do not run, the API logs why, and `GET /api/backup/status` shows it. The dev PC holds
only the dev key, so it could not write to the prod bucket even if the guard were removed.

## One-time setup

### 1. Backblaze B2 (per bucket: `DevPostgres`, `ProdPostgres`)

1. Bucket settings: private; **Default Encryption** on; **Object Lock** on with a default retention of 7 days
   (Governance is enough). Object Lock is what stops a stolen or buggy key from erasing backups.
2. **Lifecycle rules** (Object Lock retention must not outlast them; B2 will not delete a locked file early):
   - `recent/`: keep 7 days (extra same-day runs only)
   - `daily/`: keep 90 days
   - `monthly/`: keep 7 years (2555 days)
3. **Application keys.** Make two per bucket:
   - the **backup key** the PC uses: restricted to that one bucket, capability **Write only** (`writeFiles`). This goes
     in `.env` as `ORION_BACKUP_KEY_ID` and `ORION_BACKUP_KEY`.
   - a **restore key**: same bucket, read and list only. Keep it with the private key, never on the PC.
4. The `ProdPostgres` key goes only in `C:\orion-prod\.env` on the office PC, never on a dev machine.

### 2. The encryption key pair (on your own laptop, not the office PC)

```
python scripts/backup_keygen.py orion-backup-private.key
```

This writes the private key and prints a public key starting `age1`. Put the public key in `.env` as
`ORION_BACKUP_AGE_RECIPIENTS`. Keep the private key in two places away from the office PC (a password manager, plus
a printed copy). **Lose it and every backup is unreadable.** You can list more than one public key, separated by commas,
so that a second person's key can also open backups. Use a different pair for dev and prod if you want dev backups
to be openable without touching the prod key.

### 3. The read-only database role (once per database)

As the `postgres` user, on each database (dev: `orion`, prod: `orion_prod`):

```
psql -U postgres -d orion_prod -v pw="'a-long-random-password'" -f deploy/create_backup_role.sql
```

Put the same password in `.env` as `ORION_BACKUP_DB_PASSWORD`.

### 4. `.env`

See `.env.example` (dev) and `deploy/env.prod.example` (prod) for every setting. Set `ORION_BACKUP_ENABLED=1`,
`ORION_BACKUP_ALERT_EMAIL` to who should hear about failures (it uses the SMTP settings), restart the API. The log says
`Backups every 24 hours to <bucket>` or why it will not run. The PC also needs the PostgreSQL client tools
(`pg_dump`, `pg_restore`); they come with PostgreSQL and are found automatically, or point `ORION_PG_BIN` at the folder.

## What a run does

1. Reads a fingerprint of the four schemas. If `ORION_BACKUP_INTERVAL_HOURS` is under 24, a scheduled run with nothing
   changed since a success under 24 hours old does nothing and writes no row. At the default of 24 every run takes a backup.
   After the API restarts it waits out the rest of the interval instead of backing up at once.
2. Records a row in `orion_ods.backup_run`.
3. `pg_dump -Fc` as `orion_backup`, piped through `age` encryption to a temporary file in `data/backup-tmp/`.
   The plain dump is never written to disk.
4. Checks the dump's table of contents (`pg_restore --list` on its first 4 MB, before encryption) includes all four schemas.
5. Uploads to `daily/…` if it is the day's first (otherwise `recent/…`), plus `monthly/…` if it is the month's first.
   The upload's checksum is compared with the file's. The temporary file is deleted.
6. Updates the row with size, SHA-256, duration, and the object keys, or the error with secrets removed.

Objects are named `<prefix>/<database>/<yyyy>/<mm>/<database>-<utc timestamp>-<sha8>.dump.age`.
Because the key can't read, a backup is checked by its upload checksum and by a **restore drill** (below), not by reading it back.

## Restoring

Do this on a laptop or the replacement PC, not by editing `C:\orion-prod`.

1. Download the file you want from the B2 website (or with the restore key). The newest file under `daily/` or `recent/` is the latest backup.
2. Unlock it, with the private key:
   ```
   python scripts/backup_decrypt.py orion_prod-20261004T100000Z-ab12cd34.dump.age orion-backup-private.key restore.dump
   ```
3. Create an empty database and restore into it:
   ```
   createdb -U postgres orion_restore
   pg_restore --no-owner --no-acl -U postgres -d orion_restore restore.dump
   ```
   The dump is a single stream, so it restores in one pass (no `-j`).
4. Create the roles the schema expects (`orion_user`, and `orion_backup` with `deploy/create_backup_role.sql`), point
   `.env` at the database, and start the API. The start-up schema steps are safe on a restored database.
5. Delete `restore.dump`: it holds all the company data in plain form.

**Do a restore drill** into a scratch database soon after setup, then every few months. A backup nobody has restored is a hope.

## What is not in a backup

- `data/`: uploaded files, avatars, chat media and support attachments. Copy that folder separately if it matters.
- `.env` and the keys. Keep a record of the settings elsewhere; never in the same place as the private key.
- Other schemas in the database (login accounts are in `orion_ods`, so they are included).

## If something is wrong

`GET /api/backup/status` (the Admin-only status) shows the state, the reasons backups are blocked, and the last 10 runs.
Failed runs say why. After three missed intervals an email goes out once a day; failures email at most every 6 hours.
