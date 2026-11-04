import threading

from fastapi import APIRouter, Depends, HTTPException, status

from app import backup
from app.dependencies import require_admin

router = APIRouter(prefix="/backup", tags=["backup"])

# Status and "run now" only. There is deliberately no route that lists, downloads or deletes a backup: the
# application cannot read them back, so nobody who gets into it can either.


@router.get("/status")
def backup_status(_user=Depends(require_admin)):
    return backup.status()


@router.post("/run", status_code=status.HTTP_202_ACCEPTED)
def run_now(user=Depends(require_admin)):
    stop = backup.problems(backup.load_config())
    if stop:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=" ".join(stop))
    if backup.status()["running"]:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="A backup is already running.")

    def work() -> None:
        try:
            backup.run_backup("manual", user["id"], force=True)
        except backup.BackupError:
            pass  # recorded in the backup log, which the page shows

    threading.Thread(target=work, name="orion-backup-manual", daemon=True).start()
    return {"started": True}
