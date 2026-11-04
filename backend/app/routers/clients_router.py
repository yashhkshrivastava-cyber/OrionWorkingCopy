from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status

from app import auth, clients
from app.dependencies import require_ods

router = APIRouter(prefix="/clients", tags=["clients"])


@router.get("")
def list_clients(search: Optional[str] = Query(default=None, max_length=80), user=Depends(require_ods)):
    """Every client with its cases; what each owes only for someone who may see billing."""
    return {"clients": clients.directory(search, auth.can_access_billing(user))}


@router.get("/{client_code}")
def get_client(client_code: str = Path(max_length=40), user=Depends(require_ods)):
    """One client: its details, cases and contacts, and its bills and what it owes for someone who may see billing."""
    found = clients.profile(client_code, auth.can_access_billing(user))
    if found is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Client not found")
    return found
