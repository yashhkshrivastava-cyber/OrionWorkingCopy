"""Forecasting a monthly business figure: what the next month, quarter, half-year, year and three years are likely to look like.

Pure Python (no database, no numeric library), so it is fast to test and adds no dependency. It is a small, honest forecasting engine, built the way
a careful analyst would do it by hand, not a black box:

1. **Clean the history.** Leading empty months are dropped; the month in progress is left out (it is not a whole month yet); a one-month spike or
   a missing month is smoothed for fitting (and counted); and a **level shift** (the business changed size at a point in time, as when a large
   contract ends) is found, so that the forecast learns from the new level and not from a past that no longer applies.
2. **Fit several simple models** and let the history choose: the run-rate (recent average), a damped trend (Holt), a trend line, and, when two
   full years exist, a seasonal damped trend (Holt-Winters) and last year's pattern grown at the recent pace.
3. **Test them honestly.** Every model is back-tested the way it would have been used: fitted on the past up to a month, asked for the next few months, and
   scored against what happened, over many starting months. The best models are combined, weighted by how well they did.
4. **Say how sure it is.** The spread of the back-test errors, at each distance ahead, sets the range around the forecast (80 and 95 per cent), widened
   for horizons much longer than the history and checked against how often the back-test actually fell inside its own range (the range is stretched
   if it was too confident). A short history gives a wide range and a plain "low confidence" label; it never gives a confident-looking number.

Nothing here knows about Orion's tables: ``forecast_series`` takes months and values and returns a plain dict the screens draw.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date
from typing import Any, Callable, Optional, Sequence

HORIZON = 36
HORIZON_STEPS = (1, 3, 6, 12, 36)
HORIZON_LABELS = {1: "Next month", 3: "Next 3 months", 6: "Next 6 months", 12: "Next 12 months", 36: "Next 3 years"}
SEASON = 12
MIN_FIT = 6                 # fewer clean months than this and no model is tested: a run-rate with a wide range is all that can be said
MIN_SEASONAL = 24           # two full years
Z80, Z95 = 1.2815516, 1.959964
CORR = 0.7                  # forecast errors of neighbouring months move together: how much, when adding months into a period
EPS = 1e-9
GROWTH_UNCERTAINTY = 0.06     # how far, as a share of the level, the pace of growth itself may turn out wrong in a year
GROWTH_UNCERTAINTY_SHORT = 0.10
MIN_TESTED = 10               # fewer back-tested months than this and 'did it beat the simple guess' is not a fair question


# ------------------------------------------------------------------------------------------------------------------ small maths


def _mean(xs: Sequence[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def _median(xs: Sequence[float]) -> float:
    s = sorted(xs)
    n = len(s)
    if not n:
        return 0.0
    mid = n // 2
    return s[mid] if n % 2 else (s[mid - 1] + s[mid]) / 2


def _mad(xs: Sequence[float]) -> float:
    """Median absolute deviation, scaled to be comparable with a standard deviation."""
    if not xs:
        return 0.0
    m = _median(xs)
    return 1.4826 * _median([abs(x - m) for x in xs])


def _std(xs: Sequence[float]) -> float:
    if len(xs) < 2:
        return 0.0
    m = _mean(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - 1))


def _ols(ys: Sequence[float]) -> tuple[float, float]:
    """Intercept at the first point and slope per step of the straight line through ``ys``."""
    n = len(ys)
    if n < 2:
        return (ys[0] if ys else 0.0), 0.0
    xs = range(n)
    mx, my = (n - 1) / 2, _mean(ys)
    sxx = sum((x - mx) ** 2 for x in xs)
    slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx if sxx else 0.0
    return my - slope * mx, slope


def month_add(month: str, count: int) -> str:
    year, number = int(month[:4]), int(month[5:7])
    index = year * 12 + (number - 1) + count
    return f"{index // 12:04d}-{index % 12 + 1:02d}"


def months_between(first: str, last: str) -> int:
    return (int(last[:4]) - int(first[:4])) * 12 + int(last[5:7]) - int(first[5:7])


def fiscal_year(month: str) -> str:
    """Indian financial year of a month: 2026-04 .. 2027-03 is FY 2026-27."""
    year, number = int(month[:4]), int(month[5:7])
    start = year if number >= 4 else year - 1
    return f"{start}-{str(start + 1)[2:]}"


# --------------------------------------------------------------------------------------------------------------------- cleaning


@dataclass
class Prepared:
    months: list[str]
    raw: list[float]
    values: list[float]          # what the models are fitted on: gaps and spikes smoothed, and only the current regime
    regime_from: int             # index into ``months`` where the fitted part begins
    notes: list[str]
    adjusted: int
    recent_shift: bool


def _fill(months_values: Sequence[tuple[str, float]]) -> tuple[list[str], list[float]]:
    """Every month between the first and last, a month with no figure being zero."""
    found: dict[str, float] = {}
    for month, value in months_values:
        if value is None or isinstance(value, bool) or not math.isfinite(float(value)):
            continue
        found[month] = found.get(month, 0.0) + float(value)
    if not found:
        return [], []
    first, last = min(found), max(found)
    months = [month_add(first, i) for i in range(months_between(first, last) + 1)]
    return months, [found.get(m, 0.0) for m in months]


def _scale(values: Sequence[float]) -> float:
    positive = [abs(v) for v in values if abs(v) > EPS]
    return _median(positive) if positive else 1.0


def _spikes(values: list[float]) -> list[int]:
    """Months that jump away from both neighbours and come back: a one-off, or a month with no data, not a change in the business."""
    n = len(values)
    scale = _scale(values)
    out = []
    for i in range(1, n - 1):
        a, b, c = values[i - 1], values[i], values[i + 1]
        around = (a + c) / 2
        if abs(a - c) > 0.6 * max(abs(around), 0.25 * scale):
            continue  # the neighbours disagree: this is a step, not a spike
        gap = abs(b - around)
        if gap > 0.5 * max(abs(around), 0.25 * scale) and gap > 3 * _mad([values[j] - values[j - 1] for j in range(1, n)]):
            out.append(i)
    return out


def _shift_point(values: Sequence[float]) -> Optional[int]:
    """The index where the latest level shift begins: a jump between two months far bigger than months usually move."""
    n = len(values)
    if n < 10:
        return None
    scale = _scale(values)
    if all(v > 0 for v in values):
        steps = [math.log(values[i] / values[i - 1]) for i in range(1, n)]
        floor = 0.12
    else:
        steps = [(values[i] - values[i - 1]) / scale for i in range(1, n)]
        floor = 0.2
    threshold = max(floor, 4 * _mad(steps))
    jumps = [i + 1 for i, s in enumerate(steps) if abs(s) > threshold]
    return jumps[-1] if jumps else None


def prepare(months_values: Sequence[tuple[str, float]], as_of: Optional[date]) -> Optional[Prepared]:
    months, raw = _fill(months_values)
    if not months:
        return None
    notes: list[str] = []
    if as_of is not None:
        current = f"{as_of.year:04d}-{as_of.month:02d}"
        kept = [i for i, m in enumerate(months) if m < current]
        if len(kept) < len(months):
            notes.append(f"The month in progress ({months[-1]}) is left out: it is not a whole month yet.")
            months, raw = [months[i] for i in kept], [raw[i] for i in kept]
    start = next((i for i, v in enumerate(raw) if abs(v) > EPS), None)
    if start is None:
        return None
    if start:
        months, raw = months[start:], raw[start:]
    values = list(raw)
    adjusted = 0
    for i in _spikes(values):
        values[i] = (values[i - 1] + values[i + 1]) / 2
        adjusted += 1
    if adjusted:
        notes.append(f"{adjusted} month{'s' if adjusted != 1 else ''} that stood far out from the months around {'them were' if adjusted != 1 else 'it was'} smoothed for fitting (a one-off, or a month with no data).")
    shift = _shift_point(values)
    regime = 0
    recent = False
    if shift is not None:
        if len(values) - shift >= MIN_FIT:
            regime = shift
            notes.append(f"The level changed in {months[shift]}, so the forecast learns only from {months[shift]} onwards ({len(values) - shift} months).")
        else:
            recent = True
            notes.append(f"The level changed in {months[shift]}, too recently to learn the new level from, so the range is wider than usual.")
    return Prepared(months, raw, values[regime:], regime, notes, adjusted, recent)


# ---------------------------------------------------------------------------------------------------------------------- models

Model = Callable[[Sequence[float], int], Optional[list[float]]]


def _grid(seasonal: bool):
    for alpha in (0.2, 0.4, 0.6, 0.8):
        for beta in (0.05, 0.15, 0.3):
            for phi in (0.8, 0.9, 0.96, 0.99):
                if seasonal:
                    for gamma in (0.1, 0.3):
                        yield alpha, beta, phi, gamma
                else:
                    yield alpha, beta, phi, 0.0


def _holt_run(y: Sequence[float], alpha: float, beta: float, phi: float, gamma: float, season: list[float] | None):
    """One pass of (damped, optionally seasonal) Holt-Winters. Returns the squared one-step error and the final state."""
    n = len(y)
    m = SEASON
    seas = list(season) if season is not None else None
    level = y[0] - (seas[0] if seas else 0.0)
    k = min(n, 4)
    trend = (y[k - 1] - y[0]) / (k - 1) if k > 1 else 0.0
    sse = 0.0
    for t in range(1, n):
        s = seas[t % m] if seas else 0.0
        fitted = level + phi * trend + s
        error = y[t] - fitted
        if t >= 2:
            sse += error * error
        new_level = alpha * (y[t] - s) + (1 - alpha) * (level + phi * trend)
        trend = beta * (new_level - level) + (1 - beta) * phi * trend
        if seas is not None:
            seas[t % m] = gamma * (y[t] - new_level) + (1 - gamma) * s
        level = new_level
    return sse, level, trend, seas


def _initial_season(y: Sequence[float]) -> list[float]:
    """Seasonal offsets from the first full years: each month's average difference from its year's average."""
    n = len(y)
    years = n // SEASON
    year_mean = [_mean(y[j * SEASON:(j + 1) * SEASON]) for j in range(years)]
    offsets = [_mean([y[j * SEASON + i] - year_mean[j] for j in range(years)]) for i in range(SEASON)]
    mean_offset = _mean(offsets)
    return [o - mean_offset for o in offsets]


def _holt_fit(y: Sequence[float], seasonal: bool):
    best = None
    base_season = _initial_season(y) if seasonal else None
    for alpha, beta, phi, gamma in _grid(seasonal):
        sse, level, trend, seas = _holt_run(y, alpha, beta, phi, gamma, base_season)
        if best is None or sse < best[0]:
            best = (sse, level, trend, seas, phi)
    return best


def _holt_forecast(y: Sequence[float], h: int, seasonal: bool) -> list[float]:
    n = len(y)
    _sse, level, trend, seas, phi = _holt_fit(y, seasonal)
    out, damp, acc = [], 1.0, 0.0
    for step in range(1, h + 1):
        damp *= phi
        acc += damp
        s = seas[(n - 1 + step) % SEASON] if seas else 0.0
        out.append(level + acc * trend + s)
    return out


def model_level(y: Sequence[float], h: int) -> Optional[list[float]]:
    """The run-rate: the recent average, carried forward."""
    window = min(len(y), 6)
    return [_mean(y[-window:])] * h


def model_holt(y: Sequence[float], h: int) -> Optional[list[float]]:
    """A level and a trend that fades with distance (a damped trend), both learned from the whole current regime."""
    if len(y) < MIN_FIT:
        return None
    return _holt_forecast(y, h, False)


def model_trend_line(y: Sequence[float], h: int) -> Optional[list[float]]:
    """A straight line through the last year, the slope fading with distance."""
    if len(y) < MIN_FIT:
        return None
    window = list(y[-min(len(y), 12):])
    intercept, slope = _ols(window)
    level = intercept + slope * (len(window) - 1)
    out, damp, acc = [], 1.0, 0.0
    for _ in range(h):
        damp *= 0.93
        acc += damp
        out.append(level + acc * slope)
    return out


def model_seasonal(y: Sequence[float], h: int) -> Optional[list[float]]:
    """A damped trend with a pattern for each month of the year. Needs two full years."""
    if len(y) < MIN_SEASONAL:
        return None
    return _holt_forecast(y, h, True)


def model_seasonal_growth(y: Sequence[float], h: int) -> Optional[list[float]]:
    """Last year's same month, grown at the pace of the last twelve months against the twelve before. The growth fades in each later year."""
    n = len(y)
    if n < MIN_SEASONAL:
        return None
    recent, before = sum(y[-12:]), sum(y[-24:-12])
    growth = recent / before if before > EPS and recent > EPS else 1.0
    growth = min(max(growth, 0.7), 1.4)
    out = []
    for step in range(1, h + 1):
        year = (step - 1) // 12
        factor = 1.0
        for k in range(year + 1):
            factor *= 1 + (growth - 1) * (0.6 ** k)
        out.append(y[n - 12 + ((step - 1) % 12)] * factor)
    return out


MODELS: dict[str, tuple[str, Model]] = {
    "level": ("Recent run-rate", model_level),
    "holt": ("Damped trend", model_holt),
    "trend": ("Trend line", model_trend_line),
    "seasonal": ("Seasonal trend", model_seasonal),
    "last_year": ("Last year's pattern, grown", model_seasonal_growth),
}


# --------------------------------------------------------------------------------------------------------------------- back-test


def _origins(n: int) -> list[int]:
    """The months to stand at, back in time: from half-way through the history to the second last, at most 24 of them."""
    first = max(MIN_FIT, n // 2)
    last = n - 2
    if last < first:
        return []
    span = last - first + 1
    step = max(1, math.ceil(span / 24))
    return list(range(first, last + 1, step))


Errors = dict[int, dict[int, float]]   # distance ahead -> {the month stood at -> actual less forecast}


def _backtest(y: Sequence[float], horizon: int) -> dict[str, Errors]:
    """For each model, the errors (actual less forecast) by distance ahead, over every starting month."""
    errors: dict[str, Errors] = {key: {} for key in MODELS}
    naive: Errors = {}
    n = len(y)
    for origin in _origins(n):
        train = y[:origin]
        reach = min(horizon, n - origin)
        for key, (_label, model) in MODELS.items():
            predicted = model(train, reach)
            if predicted is None:
                continue
            for h in range(1, reach + 1):
                errors[key].setdefault(h, {})[origin] = y[origin + h - 1] - predicted[h - 1]
        for h in range(1, reach + 1):
            naive.setdefault(h, {})[origin] = y[origin + h - 1] - train[-1]
    errors["naive"] = naive
    return errors


def _flat(errors: Errors, up_to: int = 12) -> dict[int, list[float]]:
    return {h: list(es.values()) for h, es in errors.items() if h <= up_to}


def _score(errors: Errors, level: float, up_to: int = 6) -> Optional[float]:
    """Mean absolute error over the first ``up_to`` months ahead, as a share of the typical level."""
    values = [abs(e) for h, es in errors.items() if h <= up_to for e in es.values()]
    if len(values) < 3 or level <= EPS:
        return None
    return _mean(values) / level


def _blend(parts: Sequence[tuple[float, Errors]]) -> Errors:
    """The errors of a weighted mix of models: the weighted mix of their errors, at the months every part was tested."""
    out: Errors = {}
    for h in range(1, 13):
        present = [(w, errs[h]) for w, errs in parts if h in errs]
        if len(present) != len(parts):
            continue
        origins = set.intersection(*(set(es) for _w, es in present))
        wsum = sum(w for w, _es in present)
        if origins:
            out[h] = {o: sum(w * es[o] for w, es in present) / wsum for o in origins}
    return out


def _rmse(es: Sequence[float]) -> float:
    return math.sqrt(_mean([e * e for e in es])) if es else 0.0


# --------------------------------------------------------------------------------------------------------------------- the result


def _quantile(forecast: float, sigma: float, z: float, positive: bool) -> float:
    if positive and forecast > EPS and sigma > EPS:
        spread = math.sqrt(math.log(1 + (sigma / forecast) ** 2))
        return math.exp(math.log(forecast) - spread * spread / 2 + z * spread)
    return forecast + z * sigma


def _sigmas(errors: Errors, level: float, horizon: int, n_eff: int, recent_shift: bool) -> list[float]:
    """The standard deviation of the forecast error at each distance ahead: measured in the back-test where it was tested, then grown like a
    random walk beyond that; never below a small share of the level, widened when the history is much shorter than the horizon."""
    flat = _flat(errors)
    measured = {h: _rmse(es) for h, es in flat.items() if len(es) >= 3}
    floor = 0.02 * level
    if measured:
        reach = max(measured)
        running, top = [], 0.0
        for h in range(1, reach + 1):
            top = max(top, measured.get(h, top))  # an error never shrinks with distance
            running.append(top)
        sigmas = [max(running[h - 1] if h <= reach else running[-1] * (h / reach) ** 0.5, floor, running[0]) for h in range(1, horizon + 1)]
    else:
        # nothing to test against: a tenth of the level a month, growing like a random walk
        sigmas = [max(floor, 0.1 * level) * math.sqrt(h) for h in range(1, horizon + 1)]
    sigmas = [s * math.sqrt(1 + max(0, h - n_eff) / max(n_eff, 1) * 0.5) for h, s in enumerate(sigmas, start=1)]
    return [s * (1.5 if recent_shift else 1.0) for s in sigmas]


def _coverage(errors: Errors, sigmas: Sequence[float]) -> Optional[float]:
    inside = total = 0
    for h, es in errors.items():
        if h > len(sigmas):
            continue
        for e in es.values():
            total += 1
            inside += abs(e) <= Z80 * sigmas[h - 1]
    return inside / total if total >= 8 else None


def _confidence(n_eff: int, skill: Optional[float], coverage: Optional[float], recent_shift: bool) -> tuple[str, list[str]]:
    reasons = []
    if n_eff < 9:
        return "very_low", [f"Only {n_eff} whole month{'s' if n_eff != 1 else ''} of history to learn from."]
    level = "high"
    if n_eff < 36:
        level = "medium"
        reasons.append(f"{n_eff} months of history: enough for the next few months, thin for the far end.")
    if n_eff < 18:
        level = "low"
        reasons.append("Under 18 months of history: no pattern through the year can be learned.")
    if skill is None:
        level = "low"
        reasons.append("Too little history to test the forecast against what happened.")
    elif skill <= 0.05:
        level = "low"
        reasons.append("Looking back, this forecast did no better than a simple guess (this month, or the recent average).")
    elif skill < 0.2 and level == "high":
        level = "medium"
        reasons.append("Looking back, it beat the simple guess only a little.")
    if coverage is not None and (coverage < 0.62 or coverage > 0.96):
        level = {"high": "medium", "medium": "low"}.get(level, level)
        reasons.append("The range did not fit past months well, so treat it loosely.")
    if recent_shift:
        level = {"high": "medium", "medium": "low"}.get(level, level)
        reasons.append("The business changed level recently.")
    if not reasons:
        reasons.append("A long history, and the forecast has beaten the simple guess in testing.")
    return level, reasons


def forecast_series(
    months_values: Sequence[tuple[str, float]],
    *,
    as_of: Optional[date] = None,
    horizon: int = HORIZON,
    non_negative: bool = True,
    label: str = "",
    unit: str = "inr",
) -> dict[str, Any]:
    """Forecast ``horizon`` months ahead from ``(YYYY-MM, value)`` pairs. See the module note for how."""
    base: dict[str, Any] = {"label": label, "unit": unit, "available": False, "history": [], "forecast": [], "horizons": [], "years": [], "notes": []}
    prepared = prepare(months_values, as_of)
    if prepared is None:
        base["notes"] = ["There is no history to forecast from yet."]
        return base
    y = prepared.values
    n = len(y)
    last = prepared.months[-1]
    level = _scale(y[-12:])
    notes = list(prepared.notes)
    history = [
        {"month": m, "value": round(v, 2), "fitted": i >= prepared.regime_from}
        for i, (m, v) in enumerate(zip(prepared.months, prepared.raw))
    ]
    first_forecast = month_add(last, 1)

    if n < MIN_FIT:
        point = [_mean(y[-min(n, 3):])] * horizon
        errors: Errors = {}
        chosen = [("level", 1.0)]
        skill = None
        tested = 0
        notes.append("Too few months to learn a trend, so this is the recent average carried forward, with a wide range.")
    else:
        errors_by_model = _backtest(y, 12)
        naive_score = _score(errors_by_model.pop("naive"), level)
        level_score = _score(errors_by_model.get("level", {}), level)
        # the simple guesses to beat: next month equals this month, or equals the recent average. The better of the two
        guess_score = min((x for x in (naive_score, level_score) if x is not None), default=None)
        scored = []
        for key in MODELS:
            sc = _score(errors_by_model.get(key, {}), level)
            if sc is not None:
                scored.append((sc, key))
        scored.sort()
        if scored:
            top = scored[:3]
            weights = [1.0 / max(sc, 0.005) ** 2 for sc, _k in top]
            total = sum(weights)
            chosen = [(key, w / total) for (_sc, key), w in zip(top, weights)]
        else:
            chosen = [("holt" if n >= MIN_FIT else "level", 1.0)]
        point = [0.0] * horizon
        for key, weight in chosen:
            forecast = MODELS[key][1](y, horizon) or MODELS["level"][1](y, horizon)
            point = [p + weight * f for p, f in zip(point, forecast)]
        # the errors of the blend, by distance ahead, from the back-test of its parts
        errors = _blend([(weight, errors_by_model.get(key, {})) for key, weight in chosen])
        best = scored[0][0] if scored else None
        blended = _score(errors, level)
        mine = blended if blended is not None else best
        tested = sum(len(es) for h, es in errors.items() if h <= 6)
        skill = (1 - mine / guess_score) if (mine is not None and guess_score and guess_score > EPS and tested >= MIN_TESTED) else None

    n_eff = n
    sigmas = _sigmas(errors, level, horizon, n_eff, prepared.recent_shift)
    coverage = _coverage(errors, sigmas)
    if coverage is not None and coverage < 0.7:
        factor = min(1.6, 0.8 / max(coverage, 0.35))
        sigmas = [s * factor for s in sigmas]
        coverage = _coverage(errors, sigmas)
    # on top of what the back-test measured: the pace of growth itself may turn out different, and that error compounds with distance
    growth = GROWTH_UNCERTAINTY_SHORT if n < 18 else GROWTH_UNCERTAINTY
    sigmas = [math.sqrt(s * s + (level * growth * h / 12) ** 2) for h, s in enumerate(sigmas, start=1)]
    if non_negative:
        point = [max(0.0, p) for p in point]
    rows = []
    for h in range(1, horizon + 1):
        f, s = point[h - 1], sigmas[h - 1]
        rows.append({
            "month": month_add(last, h), "expected": f, "sigma": s,
            "p10": _quantile(f, s, -Z80, non_negative), "p90": _quantile(f, s, Z80, non_negative),
            "p025": _quantile(f, s, -Z95, non_negative), "p975": _quantile(f, s, Z95, non_negative),
        })
    for row in rows:
        if non_negative:
            for key in ("p10", "p90", "p025", "p975"):
                row[key] = max(0.0, row[key])

    seasonal = _seasonality(y, prepared.months[prepared.regime_from:]) if n >= MIN_SEASONAL else None
    confidence, reasons = _confidence(n, skill, coverage, prepared.recent_shift)
    if horizon >= 36 and n < 24:
        notes.append("The three-year figure is indicative only: it rests on less than two years of history.")
    out = {
        "label": label, "unit": unit, "available": True, "data_through": last, "first_forecast": first_forecast,
        "history": history, "forecast": rows, "notes": notes,
        "model": {
            "components": [{"key": key, "name": MODELS[key][0], "weight": round(w, 3)} for key, w in chosen],
            "seasonal": any(key in ("seasonal", "last_year") for key, _w in chosen),
            "history_months": n,
            "from": prepared.months[prepared.regime_from],
        },
        "accuracy": {
            "origins": len(_origins(n)) if n >= MIN_FIT else 0,
            "error_pct": _score(errors, level) * 100 if (_score(errors, level) is not None and tested >= MIN_TESTED) else None,
            "tested": tested,
            "skill": skill,
            "coverage_80": coverage,
        },
        "drivers": _drivers(prepared, rows, level),
        "seasonality": seasonal,
        "confidence": {"level": confidence, "reasons": reasons},
    }
    out["horizons"] = _horizons(prepared, rows)
    out["years"] = _years(prepared, rows)
    return out


def _seasonality(y: Sequence[float], months: Sequence[str]) -> Optional[dict[str, Any]]:
    """How much each calendar month usually differs from the year's average (as a share), and how strong the pattern is."""
    if len(y) < MIN_SEASONAL:
        return None
    intercept, slope = _ols(list(y))
    detrended = [v - (intercept + slope * i) for i, v in enumerate(y)]
    by_month: dict[int, list[float]] = {}
    for month, d in zip(months, detrended):
        by_month.setdefault(int(month[5:7]), []).append(d)
    effect = {m: _mean(ds) for m, ds in by_month.items()}
    centre = _mean(list(effect.values()))
    effect = {m: e - centre for m, e in effect.items()}
    level = _mean([abs(v) for v in y]) or 1.0
    residual = [d - effect[int(m[5:7])] for m, d in zip(months, detrended)]
    var_total = _std(detrended) ** 2
    var_resid = _std(residual) ** 2
    strength = max(0.0, 1 - var_resid / var_total) if var_total > EPS else 0.0
    return {"index": [{"month": m, "effect_pct": effect.get(m, 0.0) / level * 100} for m in range(1, 13)], "strength": strength}


def _drivers(prepared: Prepared, rows: list[dict[str, Any]], level: float) -> dict[str, Any]:
    raw = prepared.raw
    recent3 = _mean(raw[-3:]) if len(raw) >= 3 else _mean(raw)
    out: dict[str, Any] = {"run_rate_per_month": recent3, "run_rate_per_year": recent3 * 12}
    if len(raw) >= 24 and sum(raw[-24:-12]) > EPS:
        out["growth_yoy_pct"] = (sum(raw[-12:]) / sum(raw[-24:-12]) - 1) * 100
    else:
        out["growth_yoy_pct"] = None
    now = _mean(raw[-3:])
    ahead = _mean([r["expected"] for r in rows[9:12]]) if len(rows) >= 12 else None
    out["pace_pct_per_year"] = ((ahead / now - 1) * 100) if (ahead is not None and abs(now) > EPS) else None
    out["volatility_pct"] = (_std(prepared.values[-12:]) / abs(_mean(prepared.values[-12:])) * 100) if len(prepared.values) >= 6 and abs(_mean(prepared.values[-12:])) > EPS else None
    return out


def _sum_range(rows: Sequence[dict[str, Any]], non_negative: bool = True) -> dict[str, float]:
    total = sum(r["expected"] for r in rows)
    s1 = sum(r["sigma"] for r in rows)
    s2 = sum(r["sigma"] ** 2 for r in rows)
    sigma = math.sqrt(max(s2 + CORR * (s1 * s1 - s2), 0.0))
    low10, high90 = _quantile(total, sigma, -Z80, non_negative), _quantile(total, sigma, Z80, non_negative)
    low25, high975 = _quantile(total, sigma, -Z95, non_negative), _quantile(total, sigma, Z95, non_negative)
    return {"expected": total, "p10": max(0.0, low10) if non_negative else low10, "p90": high90, "p025": max(0.0, low25) if non_negative else low25, "p975": high975, "sigma": sigma}


def _horizons(prepared: Prepared, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    raw = prepared.raw
    for months in HORIZON_STEPS:
        if months > len(rows):
            continue
        window = rows[:months]
        spread = _sum_range(window)
        before = sum(raw[-months:]) if len(raw) >= months else None
        out.append({
            "months": months, "label": HORIZON_LABELS[months], "through": window[-1]["month"], **spread,
            "previous": before,
            "change_pct": ((spread["expected"] / before - 1) * 100) if (before is not None and abs(before) > EPS) else None,
            "previous_note": f"the last {months} month{'s' if months != 1 else ''}" if before is not None else None,
        })
    return out


def _years(prepared: Prepared, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Each financial year the forecast touches: the months already done plus the months still to come."""
    actual: dict[str, float] = {}
    count: dict[str, int] = {}
    for m, v in zip(prepared.months, prepared.raw):
        actual[fiscal_year(m)] = actual.get(fiscal_year(m), 0.0) + v
        count[fiscal_year(m)] = count.get(fiscal_year(m), 0) + 1
    out = []
    for fy in dict.fromkeys(fiscal_year(r["month"]) for r in rows):
        part = [r for r in rows if fiscal_year(r["month"]) == fy]
        spread = _sum_range(part)
        done = actual.get(fy, 0.0)
        out.append({
            "fy": fy, "actual_months": count.get(fy, 0), "forecast_months": len(part), "actual": done, "complete": len(part) + count.get(fy, 0) >= 12,
            "expected": done + spread["expected"], "p10": done + spread["p10"], "p90": done + spread["p90"],
        })
    return out


# ------------------------------------------------------------------------------------------------------------- derived figures


def difference(first: dict[str, Any], second: dict[str, Any], *, label: str, correlation: float = 0.5, unit: str = "inr") -> dict[str, Any]:
    """The forecast of ``first - second`` (margin = revenue - cost) from the two forecasts, never from a third guess: the point is the
    difference of the points; the spread combines the two spreads, less what they share (costs move with revenue, so the margin is steadier than
    either part alone)."""
    if not (first.get("available") and second.get("available")):
        return {"label": label, "unit": unit, "available": False, "history": [], "forecast": [], "horizons": [], "years": [], "notes": ["Needs both parts to have a history."]}
    a_rows = {r["month"]: r for r in first["forecast"]}
    b_rows = {r["month"]: r for r in second["forecast"]}
    months = [m for m in a_rows if m in b_rows]
    rows = []
    for m in months:
        a, b = a_rows[m], b_rows[m]
        sigma = math.sqrt(max(a["sigma"] ** 2 + b["sigma"] ** 2 - 2 * correlation * a["sigma"] * b["sigma"], 0.0))
        f = a["expected"] - b["expected"]
        rows.append({"month": m, "expected": f, "sigma": sigma,
                     "p10": f - Z80 * sigma, "p90": f + Z80 * sigma, "p025": f - Z95 * sigma, "p975": f + Z95 * sigma})
    a_hist = {h["month"]: h["value"] for h in first["history"]}
    b_hist = {h["month"]: h["value"] for h in second["history"]}
    both = sorted(set(a_hist) & set(b_hist))
    history = [{"month": m, "value": round(a_hist[m] - b_hist[m], 2), "fitted": True} for m in both]
    if not rows or not history:
        return {"label": label, "unit": unit, "available": False, "history": [], "forecast": [], "horizons": [], "years": [], "notes": ["The two parts do not share any months yet."]}
    pseudo = Prepared([h["month"] for h in history], [h["value"] for h in history], [h["value"] for h in history], 0, [], 0, False)
    horizons = []
    for months in HORIZON_STEPS:
        if months > len(rows):
            continue
        window = rows[:months]
        total = sum(r["expected"] for r in window)
        s1 = sum(r["sigma"] for r in window)
        s2 = sum(r["sigma"] ** 2 for r in window)
        sigma = math.sqrt(max(s2 + CORR * (s1 * s1 - s2), 0.0))
        before = sum(pseudo.raw[-months:]) if len(pseudo.raw) >= months else None
        horizons.append({
            "months": months, "label": HORIZON_LABELS[months], "through": window[-1]["month"], "expected": total, "sigma": sigma,
            "p10": total - Z80 * sigma, "p90": total + Z80 * sigma, "p025": total - Z95 * sigma, "p975": total + Z95 * sigma,
            "previous": before, "change_pct": ((total / before - 1) * 100) if (before is not None and abs(before) > EPS) else None,
            "previous_note": f"the last {months} month{'s' if months != 1 else ''}" if before is not None else None,
        })
    confidence = min((first["confidence"]["level"], second["confidence"]["level"]), key=["very_low", "low", "medium", "high"].index)
    return {
        "label": label, "unit": unit, "available": True, "data_through": min(first["data_through"], second["data_through"]),
        "first_forecast": rows[0]["month"], "history": history, "forecast": rows,
        "notes": [f"Worked out as {first['label'].lower()} less {second['label'].lower()}, so it always agrees with them."] + [n for n in (first["notes"] + second["notes"]) if "left out" in n][:1],
        "model": {"components": [], "seasonal": False, "history_months": len(history), "from": history[0]["month"], "derived": True},
        "accuracy": {"origins": 0, "error_pct": None, "skill": None, "coverage_80": None},
        "drivers": _drivers(pseudo, rows, _scale(pseudo.values[-12:])),
        "seasonality": None,
        "confidence": {"level": confidence, "reasons": ["Takes the lower confidence of its two parts."]},
        "horizons": horizons, "years": _years(pseudo, rows),
    }


def public(result: dict[str, Any]) -> dict[str, Any]:
    """What goes to the screen: figures rounded to the paisa, and the working fields (the spread) dropped."""
    def clean(value: Any) -> Any:
        if isinstance(value, float):
            return round(value, 2) if math.isfinite(value) else None
        if isinstance(value, dict):
            return {k: clean(v) for k, v in value.items() if k != "sigma"}
        if isinstance(value, list):
            return [clean(v) for v in value]
        return value
    return clean(result)
