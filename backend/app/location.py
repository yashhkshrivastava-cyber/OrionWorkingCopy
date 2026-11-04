import re
from functools import lru_cache

import bharatpin

_STATE_ALIASES = {
    "mp": "Madhya Pradesh",
    "madhyapradesh": "Madhya Pradesh",
    "delhi": "Delhi",
    "nctofdelhi": "Delhi",
    "newdelhi": "Delhi",
    "ncr": "Delhi",
}

_CITY_ALIASES = {
    "gwl": "Gwalior",
    "morar": "Gwalior",
    "morargwl": "Gwalior",
    "tekanpur": "Gwalior",
    "dabra": "Gwalior",
    "datai": "Datia",
    "datia": "Datia",
    "neemach": "Neemuch",
    "neemachmp": "Neemuch",
    "neemuch": "Neemuch",
    "hoshngabad": "Narmadapuram",
    "hoshangabad": "Narmadapuram",
    "narmadapuram": "Narmadapuram",
    "pachmarhi": "Narmadapuram",
    "umaria": "Umaria",
    "umariacmho": "Umaria",
    "tikamgarh": "Tikamgarh",
    "tikamgarhm": "Tikamgarh",
    "tikamgarhmp": "Tikamgarh",
    "sagardhana": "Sagar",
    "dharmp": "Dhar",
    "dhar": "Dhar",
    "bhopal": "Bhopal",
    "hospbhopal": "Bhopal",
    "bsnlbhopaldiv": "Bhopal",
    "habibganj": "Bhopal",
    "jabalpur": "Jabalpur",
    "bsnljbldiv": "Jabalpur",
    "adhaltal": "Jabalpur",
    "adhartal": "Jabalpur",
    "guna": "Guna",
    "indore": "Indore",
    "sagar": "Sagar",
    "shivpuri": "Shivpuri",
    "dewas": "Dewas",
    "rewa": "Rewa",
    "satna": "Satna",
    "ujjain": "Ujjain",
    "ratlam": "Ratlam",
    "katni": "Katni",
    "betul": "Betul",
    "mandla": "Mandla",
    "chhatarpur": "Chhatarpur",
    "chhindwara": "Chhindwara",
    "singrauli": "Singrauli",
    "sidhi": "Sidhi",
    "sindhi": "Sidhi",
    "morena": "Morena",
    "bhind": "Bhind",
    "sheopur": "Sheopur",
    "damoh": "Damoh",
    "khandwa": "Khandwa",
    "balaghat": "Balaghat",
    "sehore": "Sehore",
    "shajapur": "Shajapur",
    "dhanpuri": "Shahdol",
    "jhansi": "Jhansi",
    "agra": "Agra",
}


def _norm_place(value: str) -> str:
    text = re.sub(r"\([^)]*\)", "", str(value or ""))
    return re.sub(r"[^a-z0-9]+", "", text.lower())


@lru_cache(maxsize=1)
def get_all_states():
    return sorted(bharatpin.get_all_states())


@lru_cache(maxsize=128)
def get_cities_for_state(state: str):
    if not state:
        return []
    districts = bharatpin.get_districts_by_state(state)
    return sorted(districts) if districts else []


@lru_cache(maxsize=1)
def _place_index() -> tuple[dict[str, str], dict[str, tuple[str, str]]]:
    states: dict[str, str] = {}
    cities: dict[str, tuple[str, str]] = {}
    for state in get_all_states():
        states[_norm_place(state)] = state
        for city in get_cities_for_state(state):
            cities.setdefault(_norm_place(city), (city, state))
    for alias, state in _STATE_ALIASES.items():
        states.setdefault(alias, state)
    for alias, city in _CITY_ALIASES.items():
        if alias in cities:
            continue
        match = next((pair for key, pair in cities.items() if pair[0].lower() == city.lower()), None)
        if match:
            cities[alias] = match
        else:
            cities[alias] = (city, "Madhya Pradesh" if alias not in {"jhansi", "agra"} else "Uttar Pradesh")
    return states, cities


def resolve_place(token: str | None) -> tuple[str | None, str | None]:
    """Turn a messy city/state label into (city, state).

    If the token is a state: Madhya Pradesh / MP → Gwalior; any other state → Delhi.
    """
    if token is None:
        return None, None
    raw = str(token).strip()
    if not raw:
        return None, None
    key = _norm_place(raw)
    if not key:
        return None, None
    states, cities = _place_index()
    if key in cities:
        return cities[key]
    for extra in re.findall(r"[A-Za-z]{3,}", raw):
        extra_key = _norm_place(extra)
        if extra_key in cities:
            return cities[extra_key]
    state = states.get(key)
    if state:
        if state == "Madhya Pradesh":
            return "Gwalior", "Madhya Pradesh"
        return "Delhi", "Delhi"
    return raw.title(), None
