"""Маршрут М-36 Астана → Караганда (полилиния из reference/driverguard_dashboard.html)."""

ROUTE: list[tuple[float, float]] = [
    (51.128, 71.430),
    (51.02, 71.62),
    (50.90, 71.83),
    (50.76, 72.06),
    (50.60, 72.28),
    (50.42, 72.47),
    (50.23, 72.66),
    (50.055, 72.964),
    (49.93, 73.03),
    (49.806, 73.085),
]


def route_point(t: float) -> tuple[float, float]:
    """Точка на маршруте по доле пути t ∈ [0, 1]."""
    t = max(0.0, min(1.0, t))
    s = t * (len(ROUTE) - 1)
    i = min(int(s), len(ROUTE) - 2)
    f = s - i
    lat = ROUTE[i][0] + (ROUTE[i + 1][0] - ROUTE[i][0]) * f
    lon = ROUTE[i][1] + (ROUTE[i + 1][1] - ROUTE[i][1]) * f
    return round(lat, 4), round(lon, 4)
