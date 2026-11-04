from fastapi import APIRouter, Depends, Query

from app.dependencies import get_current_user
from app.location import get_all_states, get_cities_for_state

router = APIRouter(prefix="/location", tags=["location"])


@router.get("/states")
def states(_user=Depends(get_current_user)):
    return {"states": get_all_states()}


@router.get("/cities")
def cities(state: str = Query(...), _user=Depends(get_current_user)):
    return {"cities": get_cities_for_state(state)}
