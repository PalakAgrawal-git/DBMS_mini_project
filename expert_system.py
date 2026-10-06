"""
expert_system.py
================
Rule-based classifier for heatwave severity -- fixed IF-THEN threshold rules
on the latest weather observation, no trained model and no ML libraries.

Rules (evaluated top-down, first match wins):

    | Severity | Condition                                      |
    |----------|-------------------------------------------------|
    | Extreme  | temp >= 45 C, OR (temp >= 40 C AND humidity <= 20%) |
    | High     | temp >= 40 C                                     |
    | Moderate | temp >= 35 C                                     |
    | Low      | anything below that                              |

classify_severity() returns (level, reason) -- reason names which rule fired,
and is stored in HeatwavePrediction.reason for transparency.
"""

# The four severity levels, matched to the HeatwaveSeverity lookup table.
SEVERITY_LEVELS = ("Low", "Moderate", "High", "Extreme")

# Static catalogue of advisory messages per severity level. Seeded into the
# Advisory table by seed.py; kept here too so the expert system is self-contained.
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
    """
    Apply the rule-based expert-system rules and return (level, reason).

    Parameters
    ----------
    temperature : float   degrees Celsius
    humidity    : float   percent (0-100)
    wind_speed  : float   km/h (accepted for completeness; not part of the
                          threshold rules, but stored with the prediction)

    Returns
    -------
    (level, reason) : tuple[str, str]
    """
    t = float(temperature)
    h = float(humidity)

    # Rule 1 -- Extreme
    if t >= 45:
        return "Extreme", f"Rule: temperature {t} C >= 45 C."
    if t >= 40 and h <= 20:
        return "Extreme", f"Rule: temperature {t} C >= 40 C AND humidity {h}% <= 20% (dry heat)."

    # Rule 2 -- High
    if t >= 40:
        return "High", f"Rule: temperature {t} C >= 40 C."

    # Rule 3 -- Moderate
    if t >= 35:
        return "Moderate", f"Rule: temperature {t} C >= 35 C."

    # Rule 4 -- Low (default)
    return "Low", f"Rule: temperature {t} C is below 35 C."


def advisories_for(level):
    """Return the list of advisory messages for a given severity level."""
    return ADVISORIES.get(level, [])


if __name__ == "__main__":
    # Quick self-test of the rule set.
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
