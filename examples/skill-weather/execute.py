"""Weather skill — fetches current weather from wttr.in with Open-Meteo fallback."""
from __future__ import annotations

import httpx

_TIMEOUT = 10


async def execute(location: str, units: str = "metric", forecast_days: int = 0) -> str:
    """Fetch weather for a location. Returns plain-text summary."""
    # Try wttr.in first (fast, no API key needed)
    try:
        return await _wttr(location, units, forecast_days)
    except Exception:
        pass

    # Fallback to Open-Meteo (structured JSON)
    try:
        return await _open_meteo(location)
    except Exception as exc:
        return f"Failed to fetch weather for {location!r}: {exc}"


async def _wttr(location: str, units: str, forecast_days: int) -> str:
    unit_flag = "m" if units == "metric" else "u"
    url = f"https://wttr.in/{location}?{unit_flag}&{forecast_days}&format=4"

    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.get(url, headers={"User-Agent": "curl/8.0"})
        resp.raise_for_status()

    text = resp.text.strip()
    if not text or "Unknown location" in text:
        raise ValueError(f"wttr.in returned no data for {location!r}")
    return text


async def _open_meteo(location: str) -> str:
    # First geocode the location
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        geo = await client.get(
            "https://geocoding-api.open-meteo.com/v1/search",
            params={"name": location, "count": 1},
        )
        geo.raise_for_status()
        results = geo.json().get("results")
        if not results:
            return f"Could not geocode location: {location!r}"

        lat = results[0]["latitude"]
        lon = results[0]["longitude"]
        name = results[0].get("name", location)

        # Fetch weather
        weather = await client.get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": lat,
                "longitude": lon,
                "current_weather": True,
            },
        )
        weather.raise_for_status()
        cw = weather.json().get("current_weather", {})

    temp = cw.get("temperature", "?")
    wind = cw.get("windspeed", "?")
    code = cw.get("weathercode", 0)
    condition = _weather_code(code)

    return f"{name}: {condition}, {temp}°C, wind {wind} km/h"


def _weather_code(code: int) -> str:
    codes = {
        0: "Clear sky", 1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast",
        45: "Foggy", 48: "Rime fog", 51: "Light drizzle", 53: "Drizzle",
        55: "Dense drizzle", 61: "Slight rain", 63: "Rain", 65: "Heavy rain",
        71: "Slight snow", 73: "Snow", 75: "Heavy snow", 80: "Rain showers",
        81: "Moderate showers", 82: "Violent showers", 95: "Thunderstorm",
    }
    return codes.get(code, f"Code {code}")
