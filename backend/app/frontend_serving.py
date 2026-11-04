"""Serving the built web app from the API process (production, ``ORION_SERVE_FRONTEND=1``).

Orion's pages are separate files fetched when they are opened, and every file in ``assets/`` has a hash of its content in its name.
That makes two cache rules safe, and together they are what makes the split pay off:

* ``assets/*`` never change under the same name, so the browser keeps them for a year and does not even ask again
  (``immutable``). A release changes only the files whose content changed; the libraries stay where they were.
* ``index.html`` (and anything else outside ``assets/``) is what names the current files, so the browser must ask whether it
  changed every time (``no-cache`` means revalidate, not "do not store"). Without this a browser may keep an old ``index.html``
  for hours after a release, pointing at files that no longer exist.
"""

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

IMMUTABLE = "public, max-age=31536000, immutable"
REVALIDATE = "no-cache"


class HashedAssets(StaticFiles):
    """``assets/``: files whose names carry their content's hash."""

    def file_response(self, *args, **kwargs):
        response = super().file_response(*args, **kwargs)
        response.headers["Cache-Control"] = IMMUTABLE
        return response


def mount_frontend(app: FastAPI, dist: Path) -> bool:
    """Serve ``dist`` (the Vite build) from ``app``: its ``assets/`` folder, and for every other address that is not the API the file
    if it exists, else ``index.html`` (the app's own router takes it from there). False when there is no build to serve."""
    if not (dist / "index.html").is_file():
        return False
    dist = dist.resolve()
    app.mount("/assets", HashedAssets(directory=str(dist / "assets")), name="frontend-assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def serve_frontend(full_path: str):
        if full_path.startswith("api/"):
            raise HTTPException(status_code=404)
        candidate = (dist / full_path).resolve()
        if full_path and candidate.is_file() and dist in candidate.parents:
            return FileResponse(candidate, headers={"Cache-Control": REVALIDATE})
        return FileResponse(dist / "index.html", headers={"Cache-Control": REVALIDATE})

    return True
