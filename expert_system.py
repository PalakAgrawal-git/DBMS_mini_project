# Rule-based severity classifier. Fixed thresholds, no ML.
#
#   Extreme  temp >= 45, OR (temp >= 40 AND humidity <= 20)
#   High     temp >= 40
#   Moderate temp >= 35
#   Low      anything below that

SEVERITY_LEVELS = ("Low", "Moderate", "High", "Extreme")

ADVISORIES = {
    "Low": [
        "Conditions are normal. Stay aware of weather updates.",
    ],
    "Moderate": [
        "Stay hydrated and drink water regularly.",
        "Limit strenuous outdoor activity during the afternoon.",
    ],
    "High": [
        "Avoid outdoor activity between 11am and 4pm.",
        "Drink plenty of water; avoid alcohol and caffeine.",
        "Check on elderly relatives and young children.",
    ],
    "Extreme": [
        "Do NOT go outdoors between 11am and 4pm unless absolutely necessary.",
        "Stay hydrated; carry water at all times.",
        "Watch for signs of heat stroke (dizziness, nausea, confusion).",
        "Keep pets and vulnerable people in cool, ventilated spaces.",
    ],
}


def classify_severity(temperature, humidity, wind_speed):
    # wind_speed isn't used by the rules, just stored with the prediction
    t = float(temperature)
    h = float(humidity)

    if t >= 45:
        return "Extreme", "temp >= 45"
    if t >= 40 and h <= 20:
        return "Extreme", "temp >= 40 and humidity <= 20"
    if t >= 40:
        return "High", "temp >= 40"
    if t >= 35:
        return "Moderate", "temp >= 35"
    return "Low", "temp < 35"


def advisories_for(level):
    return ADVISORIES.get(level, [])


if __name__ == "__main__":
    samples = [
        (46, 30, 10),
        (41, 15, 5),
        (41, 40, 5),
        (37, 50, 8),
        (30, 60, 12),
    ]
    for temp, hum, wind in samples:
        level, reason = classify_severity(temp, hum, wind)
        print(f"{temp} C / {hum}% / {wind} km/h -> {level:8s} | {reason}")
