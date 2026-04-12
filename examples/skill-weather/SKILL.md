---
name: weather
description: Fetch current weather conditions and forecast for a location.
parameters:
  type: object
  properties:
    location:
      type: string
      description: City name, airport code, or coordinates (e.g. "London", "SFO", "48.8566,2.3522")
    units:
      type: string
      enum: [metric, uscs]
      default: metric
      description: Unit system for temperature and wind.
    forecast_days:
      type: integer
      default: 0
      description: "Number of forecast days (0 = current only, 1 = today, 3 = 3-day)."
  required:
    - location
---

# Weather

Fetches weather data from wttr.in (primary) with Open-Meteo as fallback.
Returns a plain-text weather summary including temperature, conditions,
humidity, and wind.

Compatible with the [ClaWHub weather skill](https://clawhub.ai/steipete/weather).
