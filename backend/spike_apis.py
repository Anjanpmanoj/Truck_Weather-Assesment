import os
import sys

import httpx
from dotenv import load_dotenv

load_dotenv()
TOKEN = os.environ.get("MAPBOX_TOKEN")
if not TOKEN:
    sys.exit("Set MAPBOX_TOKEN in backend/.env first")

PAIRS = [
    ("Chicago, IL", "Milwaukee, WI"),
    ("Dallas, TX", "Denver, CO"),
    ("Los Angeles, CA", "Las Vegas, NV"),
]


def geocode(q):
    r = httpx.get(
        "https://api.mapbox.com/search/geocode/v6/forward",
        params={"q": q, "country": "us", "limit": 1, "access_token": TOKEN},
        timeout=20,
    )
    r.raise_for_status()
    f = r.json()["features"][0]
    lon, lat = f["geometry"]["coordinates"]
    name = f["properties"].get("full_address") or f["properties"].get("name")
    return lon, lat, name


def directions(a, b):
    coords = f"{a[0]},{a[1]};{b[0]},{b[1]}"
    r = httpx.get(
        f"https://api.mapbox.com/directions/v5/mapbox/driving/{coords}",
        params={
            "alternatives": "true",
            "geometries": "geojson",
            "overview": "full",
            "steps": "true",
            "annotations": "duration,distance",
            "access_token": TOKEN,
        },
        timeout=30,
    )
    r.raise_for_status()
    return r.json()


def rounded(coords):
    return {(round(x, 3), round(y, 3)) for x, y in coords}


def test_routing():
    for origin, dest in PAIRS:
        print("=" * 70)
        print(f"{origin} -> {dest}")
        a, b = geocode(origin), geocode(dest)
        print("geocoded:", a[2], "|", b[2])
        data = directions(a, b)
        routes = data.get("routes", [])
        print("routes returned:", len(routes))
        base = rounded(routes[0]["geometry"]["coordinates"]) if routes else set()
        for i, rt in enumerate(routes):
            coords = rt["geometry"]["coordinates"]
            leg = rt["legs"][0]
            ann = leg.get("annotation", {})
            overlap = len(rounded(coords) & base) / max(len(rounded(coords)), 1)
            print(
                f"  route {i}: {rt['distance'] / 1609.344:.1f} mi, "
                f"{rt['duration'] / 3600:.2f} h, "
                f"geometry pts={len(coords)}, steps={len(leg.get('steps', []))}, "
                f"annotation duration/distance len="
                f"{len(ann.get('duration', []))}/{len(ann.get('distance', []))}, "
                f"overlap with route 0={overlap:.0%}"
            )


def test_weather():
    print("=" * 70)
    print("Open-Meteo batch test")
    pts = [(41.88, -87.63), (43.04, -87.91), (39.74, -104.99)]
    r = httpx.get(
        "https://api.open-meteo.com/v1/forecast",
        params={
            "latitude": ",".join(str(p[0]) for p in pts),
            "longitude": ",".join(str(p[1]) for p in pts),
            "hourly": "wind_speed_10m,wind_gusts_10m,rain,snowfall,precipitation",
            "wind_speed_unit": "mph",
            "precipitation_unit": "inch",
            "timezone": "UTC",
            "forecast_days": 3,
        },
        timeout=30,
    )
    r.raise_for_status()
    data = r.json()
    print("response type:", type(data).__name__, "| locations:", len(data))
    first = data[0]
    print("units:", first["hourly_units"])
    print("hours per location:", len(first["hourly"]["time"]))
    for i in range(3):
        print(
            first["hourly"]["time"][i],
            "wind", first["hourly"]["wind_speed_10m"][i],
            "gust", first["hourly"]["wind_gusts_10m"][i],
            "rain", first["hourly"]["rain"][i],
            "snow", first["hourly"]["snowfall"][i],
        )


if __name__ == "__main__":
    test_routing()
    test_weather()