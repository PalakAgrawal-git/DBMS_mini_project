# Loads dummy data into heatwave.db so the app isn't empty on first run.
# Run via `python init_db.py`, or directly with `python seed.py` if the
# schema already exists.
#
# Login accounts (all password: pass123):
#   admin, officer1 (Water Supply), officer2 (Health),
#   priya/rahul/sana/dev (citizens, one per region)

import os
import sqlite3

from werkzeug.security import generate_password_hash

from expert_system import classify_severity, ADVISORIES

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DATABASE = os.path.join(BASE_DIR, "heatwave.db")

PASSWORD = "pass123"


def run():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    cur = conn.cursor()
    pw = generate_password_hash(PASSWORD)

    # rank is used by the trigger and for complaint prioritisation
    severities = [
        ("Low", 1, "Normal conditions; no significant heat risk."),
        ("Moderate", 2, "Elevated temperatures; take basic precautions."),
        ("High", 3, "Dangerous heat; avoid midday exposure."),
        ("Extreme", 4, "Life-threatening heat; stay indoors, high alert."),
    ]
    cur.executemany(
        "INSERT INTO HeatwaveSeverity (level, rank, description) VALUES (?,?,?)", severities)
    sev_id = {r["level"]: r["severity_id"] for r in
              conn.execute("SELECT * FROM HeatwaveSeverity")}


    regions = [
        ("Nagpur", "Maharashtra", 2500000),
        ("Vidarbha East", "Maharashtra", 900000),
        ("Akola", "Maharashtra", 600000),
        ("Chandrapur", "Maharashtra", 450000),
    ]
    cur.executemany("INSERT INTO Region (name, state, population) VALUES (?,?,?)", regions)
    region_id = {r["name"]: r["region_id"] for r in conn.execute("SELECT * FROM Region")}


    departments = [
        ("Water Supply", "Manages drinking water and tanker distribution.", "1800-111-222"),
        ("Health", "Handles heat-illness response and hospitals.", "1800-333-444"),
        ("Electricity Board", "Power supply and outage response.", "1800-555-666"),
        ("Disaster Management", "Coordinates emergency heatwave response.", "1800-777-888"),
    ]
    cur.executemany(
        "INSERT INTO GovernmentDepartment (name, description, contact) VALUES (?,?,?)", departments)
    dept_id = {r["name"]: r["dept_id"] for r in conn.execute("SELECT * FROM GovernmentDepartment")}

    # static advisory catalogue, one row per message per severity
    for level, messages in ADVISORIES.items():
        for msg in messages:
            cur.execute("INSERT INTO Advisory (severity_id, message) VALUES (?,?)",
                        (sev_id[level], msg))


    def add_user(username, role, full_name, email):
        cur.execute(
            "INSERT INTO User (username, password_hash, role, full_name, email) VALUES (?,?,?,?,?)",
            (username, pw, role, full_name, email))
        return cur.lastrowid

    admin_uid = add_user("admin", "Administrator", "System Administrator", "admin@heatgov.in")
    cur.execute("INSERT INTO Administrator (user_id, office) VALUES (?,?)",
                (admin_uid, "State Disaster Cell"))

    off1_uid = add_user("officer1", "Officer", "Anil Deshmukh", "anil@heatgov.in")
    cur.execute("INSERT INTO Officer (user_id, dept_id, designation) VALUES (?,?,?)",
                (off1_uid, dept_id["Water Supply"], "Water Supply Officer"))
    off1_id = cur.lastrowid

    off2_uid = add_user("officer2", "Officer", "Meena Kulkarni", "meena@heatgov.in")
    cur.execute("INSERT INTO Officer (user_id, dept_id, designation) VALUES (?,?,?)",
                (off2_uid, dept_id["Health"], "Health Officer"))
    off2_id = cur.lastrowid

    citizens_spec = [
        ("priya", "Priya Sharma", "priya@example.com", "Nagpur", "9800000001", "12 MG Road, Nagpur"),
        ("rahul", "Rahul Verma", "rahul@example.com", "Vidarbha East", "9800000002", "5 Station Rd"),
        ("sana", "Sana Khan", "sana@example.com", "Akola", "9800000003", "88 Civil Lines, Akola"),
        ("dev", "Dev Patel", "dev@example.com", "Chandrapur", "9800000004", "3 Market Ln"),
    ]
    citizen_id = {}
    for uname, fname, email, region, phone, addr in citizens_spec:
        uid = add_user(uname, "Citizen", fname, email)
        cur.execute("INSERT INTO Citizen (user_id, region_id, phone, address) VALUES (?,?,?,?)",
                    (uid, region_id[region], phone, addr))
        citizen_id[uname] = cur.lastrowid


    stations_spec = [
        ("Nagpur", "Nagpur Central AWS", 21.1458, 79.0882),
        ("Nagpur", "Nagpur Airport AWS", 21.0922, 79.0472),
        ("Vidarbha East", "Vidarbha East AWS", 20.9320, 79.9500),
        ("Akola", "Akola City AWS", 20.7000, 77.0000),
        ("Chandrapur", "Chandrapur AWS", 19.9615, 79.2961),
    ]
    station_id = {}
    for region, name, lat, lon in stations_spec:
        cur.execute(
            "INSERT INTO WeatherStation (region_id, name, latitude, longitude) VALUES (?,?,?,?)",
            (region_id[region], name, lat, lon))
        station_id[name] = cur.lastrowid

    # ---- Weather observations + expert-system predictions ------------------
    # Timestamps are uneven (hours_ago) so the trend chart doesn't look fake.
    observations_spec = [
        # station name,            temp,  hum, wind, hours_ago, make_prediction
        ("Nagpur Central AWS",     44.8,  32,  11,  2,   True),   # High
        ("Nagpur Airport AWS",     41.3,  45,  13,  5,   False),
        ("Vidarbha East AWS",      41.7,  38,  14,  5,   True),   # High
        ("Chandrapur AWS",         46.3,  25,   7,  26,  True),   # Extreme
        ("Nagpur Central AWS",     39.6,  42,  10,  26,  True),   # Moderate
        ("Vidarbha East AWS",      37.8,  50,   8,  76,  True),   # Moderate
        ("Akola City AWS",         36.1,  55,  10,  76,  True),   # Moderate
        ("Akola City AWS",         33.4,  60,   9,  168, True),   # Low
        ("Chandrapur AWS",         34.9,  58,  12,  168, False),
    ]

    for station, temp, hum, wind, hours_ago, make_pred in observations_spec:
        sid = station_id[station]
        cur.execute(
            f"""INSERT INTO WeatherObservation
                    (station_id, temperature, humidity, wind_speed, observed_at, recorded_by)
                VALUES (?,?,?,?, datetime('now', '-{hours_ago} hours'), ?)""",
            (sid, temp, hum, wind, off1_uid))
        obs_id = cur.lastrowid

        if make_pred:
            level, reason = classify_severity(temp, hum, wind)
            region_of = conn.execute(
                "SELECT region_id FROM WeatherStation WHERE station_id = ?", (sid,)).fetchone()[0]
            cur.execute(
                f"""INSERT INTO HeatwavePrediction
                        (region_id, obs_id, severity_id, temperature, humidity, wind_speed,
                         reason, predicted_at)
                    VALUES (?,?,?,?,?,?,?, datetime('now', '-{hours_ago} hours'))""",
                (region_of, obs_id, sev_id[level], temp, hum, wind, reason))
            # trigger handles the alert, not python


    # (citizen, category, description, status, dept, officer, hours_ago)
    complaints_spec = [
        ("priya", "Water Shortage", "No drinking water since morning, whole street affected.",
         "Open", None, None, 2),
        ("priya", "Heat Illness", "Elderly neighbour showing signs of heat exhaustion, need help.",
         "In Progress", "Health", off2_id, 5),
        ("rahul", "Power Outage", "Power cut for 6 hours yesterday, fans not working.",
         "Open", "Electricity Board", None, 5),
        ("sana", "Water Shortage", "Tanker didnt come this week again.",
         "Resolved", "Water Supply", off1_id, 76),
        ("dev", "Public Cooling", "No shade at bus stand, people fainting in the heat.",
         "Open", None, None, 26),
        ("rahul", "Heat Illness", "Need ORS packets at community hall asap.",
         "In Progress", "Health", off2_id, 26),
        ("sana", "Power Outage", "Hospital ward has no power backup during outages.",
         "Open", "Health", None, 168),
        ("priya", "Public Cooling", "Can we get a cooling center near MG road.",
         "Resolved", None, off1_id, 168),
        ("dev", "Water Shortage", "Water pressure very low since 3 days.",
         "In Progress", "Water Supply", off1_id, 76),
    ]
    for uname, cat, desc, status, dept, officer, hours_ago in complaints_spec:
        cur.execute(
            f"""INSERT INTO Complaint
                    (citizen_id, region_id, dept_id, assigned_officer_id, category, description,
                     status, created_at, resolved_at)
                VALUES (?, (SELECT region_id FROM Citizen WHERE citizen_id = ?), ?, ?, ?, ?, ?,
                        datetime('now', '-{hours_ago} hours'),
                        {"datetime('now')" if status == 'Resolved' else "NULL"})""",
            (citizen_id[uname], citizen_id[uname],
             dept_id[dept] if dept else None, officer, cat, desc, status))


    cur.execute("INSERT INTO Notification (user_id, message) VALUES (?,?)",
                (admin_uid, "Welcome to the Heatwave Early Warning System."))

    conn.commit()

    # Report what was created.
    def count(t):
        return conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]

    print("[seed] Data loaded:")
    for t in ("User", "Region", "WeatherStation", "WeatherObservation",
              "HeatwavePrediction", "WarningAlert", "Advisory", "Complaint"):
        print(f"        {t:20s}: {count(t)}")
    print(f"[seed] Login with any of: admin / officer1 / officer2 / priya / rahul / sana "
          f"(password: {PASSWORD})")
    conn.close()


if __name__ == "__main__":
    run()
