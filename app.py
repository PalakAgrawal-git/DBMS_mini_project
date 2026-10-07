# Flask backend for HeatGuard - weather, predictions, alerts, complaints.

import csv
import io
import os
import sqlite3
from datetime import datetime
from functools import wraps

from flask import (Flask, g, redirect, render_template, request, session,
                   url_for, flash, Response, abort, jsonify)
from werkzeug.security import check_password_hash, generate_password_hash

from expert_system import classify_severity, advisories_for

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DATABASE = os.path.join(BASE_DIR, "heatwave.db")

app = Flask(__name__)
app.config["SECRET_KEY"] = "heatwave-dev-secret-key-change-in-prod"


@app.template_filter("when")
def when(value):
    """
    Format a 'YYYY-MM-DD HH:MM:SS' timestamp as relative time if it's recent,
    otherwise as a short absolute date -- so templates stop printing the raw
    SQLite string. Always paired with a title="{{ value }}" attribute in the
    template, so the exact timestamp is still one hover away.

    SQLite's datetime('now') is UTC, so "now" here is utcnow() too -- using
    local time would skew every relative timestamp by the server's UTC offset.
    """
    if not value:
        return "-"
    try:
        dt = datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return value

    delta = datetime.utcnow() - dt
    seconds = delta.total_seconds()
    if seconds < 60:
        return "just now"
    if seconds < 3600:
        mins = int(seconds // 60)
        return f"{mins} min ago"
    if seconds < 86400:
        hours = int(seconds // 3600)
        return f"{hours} hr ago"
    if seconds < 7 * 86400:
        days = int(seconds // 86400)
        return f"{days} day ago" if days == 1 else f"{days} days ago"

    # dt.day avoids the %-d / %#d platform split between Linux and Windows.
    date_part = f"{dt.day} {dt.strftime('%b')}"
    if dt.year != datetime.utcnow().year:
        date_part += f" {dt.year}"
    return f"{date_part}, {dt.strftime('%H:%M')}"

# Tables the Database Administration page is allowed to count / export.
ADMIN_TABLES = [
    "User", "Region", "HeatwaveSeverity", "GovernmentDepartment",
    "Citizen", "Officer", "Administrator", "WeatherStation",
    "WeatherObservation", "HeatwavePrediction", "Advisory",
    "WarningAlert", "Complaint", "Notification",
]


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------
def get_db():
    """Return a request-scoped SQLite connection with FK enforcement on."""
    if "db" not in g:
        g.db = sqlite3.connect(DATABASE)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON;")
    return g.db


@app.teardown_appcontext
def close_db(exception=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def query(sql, args=(), one=False):
    cur = get_db().execute(sql, args)
    rows = cur.fetchall()
    cur.close()
    return (rows[0] if rows else None) if one else rows


def execute(sql, args=()):
    db = get_db()
    cur = db.execute(sql, args)
    db.commit()
    lastid = cur.lastrowid
    cur.close()
    return lastid


# ---------------------------------------------------------------------------
# Auth helpers / decorators
# ---------------------------------------------------------------------------
def current_user():
    uid = session.get("user_id")
    if uid is None:
        return None
    return query("SELECT * FROM User WHERE user_id = ?", (uid,), one=True)


@app.context_processor
def inject_user():
    user = current_user()
    unread = 0
    if user:
        row = query("SELECT COUNT(*) AS c FROM Notification WHERE user_id = ? AND is_read = 0",
                    (user["user_id"],), one=True)
        unread = row["c"] if row else 0
    return {"current_user": user, "unread_notifications": unread}


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if session.get("user_id") is None:
            flash("Please log in first.", "warning")
            return redirect(url_for("login", next=request.path))
        return view(*args, **kwargs)
    return wrapped


def role_required(*roles):
    """Restrict a view to one or more roles."""
    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            user = current_user()
            if user is None:
                return redirect(url_for("login", next=request.path))
            if user["role"] not in roles:
                abort(403)
            return view(*args, **kwargs)
        return wrapped
    return decorator


def notify(user_id, message):
    execute("INSERT INTO Notification (user_id, message) VALUES (?, ?)", (user_id, message))


def severity_lookup():
    """Return {level: {'severity_id':..,'rank':..}} from the lookup table."""
    out = {}
    for r in query("SELECT * FROM HeatwaveSeverity"):
        out[r["level"]] = {"severity_id": r["severity_id"], "rank": r["rank"]}
    return out


# --- user management (register / login / logout) --------------------------
@app.route("/")
def index():
    if session.get("user_id"):
        return redirect(url_for("dashboard"))
    return redirect(url_for("login"))


@app.route("/register", methods=["GET", "POST"])
def register():
    regions = query("SELECT * FROM Region ORDER BY name")
    departments = query("SELECT * FROM GovernmentDepartment ORDER BY name")
    if request.method == "POST":
        username = request.form["username"].strip()
        password = request.form["password"]
        full_name = request.form["full_name"].strip()
        email = request.form.get("email", "").strip() or None
        role = request.form["role"]

        if not username or not password or not full_name:
            flash("Username, password and full name are required.", "danger")
            return render_template("register.html", regions=regions, departments=departments)

        if role not in ("Citizen", "Officer", "Administrator"):
            flash("Invalid role.", "danger")
            return render_template("register.html", regions=regions, departments=departments)

        if query("SELECT 1 FROM User WHERE username = ?", (username,), one=True):
            flash("That username is already taken.", "danger")
            return render_template("register.html", regions=regions, departments=departments)

        user_id = execute(
            "INSERT INTO User (username, password_hash, role, full_name, email) VALUES (?,?,?,?,?)",
            (username, generate_password_hash(password), role, full_name, email),
        )

        # Create the role-specific profile row.
        if role == "Citizen":
            region_id = request.form.get("region_id")
            if not region_id:
                execute("DELETE FROM User WHERE user_id = ?", (user_id,))
                flash("Citizens must select a region.", "danger")
                return render_template("register.html", regions=regions, departments=departments)
            execute(
                "INSERT INTO Citizen (user_id, region_id, phone, address) VALUES (?,?,?,?)",
                (user_id, region_id, request.form.get("phone"), request.form.get("address")),
            )
        elif role == "Officer":
            dept_id = request.form.get("dept_id")
            if not dept_id:
                execute("DELETE FROM User WHERE user_id = ?", (user_id,))
                flash("Officers must select a department.", "danger")
                return render_template("register.html", regions=regions, departments=departments)
            execute(
                "INSERT INTO Officer (user_id, dept_id, designation) VALUES (?,?,?)",
                (user_id, dept_id, request.form.get("designation", "Field Officer")),
            )
        else:  # Administrator
            execute("INSERT INTO Administrator (user_id, office) VALUES (?,?)",
                    (user_id, request.form.get("office", "Head Office")))

        flash("Registration successful. Please log in.", "success")
        return redirect(url_for("login"))

    return render_template("register.html", regions=regions, departments=departments)


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form["username"].strip()
        password = request.form["password"]
        user = query("SELECT * FROM User WHERE username = ?", (username,), one=True)
        if user and check_password_hash(user["password_hash"], password):
            session.clear()
            session["user_id"] = user["user_id"]
            session["role"] = user["role"]
            flash(f"Welcome, {user['full_name']}!", "success")
            nxt = request.args.get("next")
            return redirect(nxt or url_for("dashboard"))
        flash("Invalid username or password.", "danger")
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    flash("You have been logged out.", "info")
    return redirect(url_for("login"))


# ---------------------------------------------------------------------------
# Role-based dashboards
# ---------------------------------------------------------------------------
@app.route("/dashboard")
@login_required
def dashboard():
    user = current_user()
    role = user["role"]

    if role == "Citizen":
        citizen = query("SELECT * FROM Citizen WHERE user_id = ?", (user["user_id"],), one=True)
        region = query("SELECT * FROM Region WHERE region_id = ?", (citizen["region_id"],), one=True)
        alerts = query(
            """SELECT wa.*, s.level FROM WarningAlert wa
               JOIN HeatwaveSeverity s ON s.severity_id = wa.severity_id
               WHERE wa.region_id = ? AND wa.is_active = 1
               ORDER BY wa.issued_at DESC""",
            (citizen["region_id"],),
        )
        latest_pred = query(
            """SELECT hp.*, s.level FROM HeatwavePrediction hp
               JOIN HeatwaveSeverity s ON s.severity_id = hp.severity_id
               WHERE hp.region_id = ? ORDER BY hp.predicted_at DESC LIMIT 1""",
            (citizen["region_id"],), one=True,
        )
        my_complaints = query(
            "SELECT * FROM Complaint WHERE citizen_id = ? ORDER BY created_at DESC",
            (citizen["citizen_id"],),
        )
        advisories = advisories_for(latest_pred["level"]) if latest_pred else []
        return render_template("dashboard_citizen.html", region=region, alerts=alerts,
                               latest_pred=latest_pred, my_complaints=my_complaints,
                               advisories=advisories)

    if role == "Officer":
        officer = query(
            """SELECT o.*, d.name AS dept_name FROM Officer o
               JOIN GovernmentDepartment d ON d.dept_id = o.dept_id
               WHERE o.user_id = ?""", (user["user_id"],), one=True)
        # Complaints assigned to this officer OR to the officer's department, unresolved first,
        # prioritised by the current region severity rank
        assigned = query(
            """SELECT c.*, r.name AS region_name, cu.full_name AS citizen_name,
                      COALESCE(sev.rank, 0) AS region_rank, COALESCE(sev.level, 'Low') AS region_level
               FROM Complaint c
               JOIN Region r  ON r.region_id = c.region_id
               JOIN Citizen ct ON ct.citizen_id = c.citizen_id
               JOIN User cu   ON cu.user_id = ct.user_id
               LEFT JOIN (
                    SELECT hp.region_id, hp.severity_id
                    FROM HeatwavePrediction hp
                    JOIN (SELECT region_id, MAX(predicted_at) AS mx
                          FROM HeatwavePrediction GROUP BY region_id) latest
                      ON latest.region_id = hp.region_id AND latest.mx = hp.predicted_at
               ) lp ON lp.region_id = c.region_id
               LEFT JOIN HeatwaveSeverity sev ON sev.severity_id = lp.severity_id
               WHERE (c.assigned_officer_id = ? OR c.dept_id = ?)
               ORDER BY (c.status = 'Resolved') ASC, region_rank DESC, c.created_at ASC""",
            (officer["officer_id"], officer["dept_id"]),
        )
        summary = query("SELECT * FROM v_region_complaint_summary ORDER BY total_complaints DESC")
        return render_template("dashboard_officer.html", officer=officer,
                               assigned=assigned, summary=summary)

    # Administrator
    counts = {
        "regions": query("SELECT COUNT(*) c FROM Region", one=True)["c"],
        "users": query("SELECT COUNT(*) c FROM User", one=True)["c"],
        "complaints": query("SELECT COUNT(*) c FROM Complaint", one=True)["c"],
        "active_alerts": query("SELECT COUNT(*) c FROM WarningAlert WHERE is_active = 1", one=True)["c"],
    }
    summary = query("SELECT * FROM v_region_complaint_summary ORDER BY total_complaints DESC")
    risk = region_risk_levels()
    return render_template("dashboard_admin.html", counts=counts, summary=summary, risk=risk)


# --- weather monitoring (station + observation CRUD) ----------------------
@app.route("/weather")
@login_required
def weather():
    stations = query(
        """SELECT ws.*, r.name AS region_name FROM WeatherStation ws
           JOIN Region r ON r.region_id = ws.region_id ORDER BY r.name, ws.name""")
    observations = query(
        """SELECT wo.*, ws.name AS station_name, r.name AS region_name
           FROM WeatherObservation wo
           JOIN WeatherStation ws ON ws.station_id = wo.station_id
           JOIN Region r ON r.region_id = ws.region_id
           ORDER BY wo.observed_at DESC LIMIT 50""")
    regions = query("SELECT * FROM Region ORDER BY name")
    can_edit = session.get("role") in ("Officer", "Administrator")
    return render_template("weather.html", stations=stations, observations=observations,
                           regions=regions, can_edit=can_edit)


@app.route("/weather/station/add", methods=["POST"])
@role_required("Officer", "Administrator")
def add_station():
    execute(
        "INSERT INTO WeatherStation (region_id, name, latitude, longitude) VALUES (?,?,?,?)",
        (request.form["region_id"], request.form["name"].strip(),
         request.form.get("latitude") or None, request.form.get("longitude") or None),
    )
    flash("Weather station added.", "success")
    return redirect(url_for("weather"))


@app.route("/weather/station/<int:station_id>/delete", methods=["POST"])
@role_required("Administrator")
def delete_station(station_id):
    execute("DELETE FROM WeatherStation WHERE station_id = ?", (station_id,))
    flash("Weather station deleted.", "info")
    return redirect(url_for("weather"))


@app.route("/weather/observation/add", methods=["POST"])
@role_required("Officer", "Administrator")
def add_observation():
    station_id = request.form["station_id"]
    temperature = float(request.form["temperature"])
    humidity = float(request.form["humidity"])
    wind_speed = float(request.form["wind_speed"])

    obs_id = execute(
        """INSERT INTO WeatherObservation (station_id, temperature, humidity, wind_speed, recorded_by)
           VALUES (?,?,?,?,?)""",
        (station_id, temperature, humidity, wind_speed, session["user_id"]),
    )
    flash("Weather observation recorded.", "success")

    # run the expert system on the new reading, if asked to
    if request.form.get("run_prediction"):
        station = query("SELECT * FROM WeatherStation WHERE station_id = ?", (station_id,), one=True)
        run_prediction_for_region(station["region_id"], obs_id,
                                   temperature, humidity, wind_speed)
        flash("Rule-based prediction generated for the region.", "info")
    return redirect(url_for("weather"))


# --- prediction + early warning ---------------------------------------------
def run_prediction_for_region(region_id, obs_id, temperature, humidity, wind_speed):
    """
    Run the rule-based expert system and write a HeatwavePrediction row.
    A DB TRIGGER (trg_prediction_autowarn) auto-creates a WarningAlert for
    High/Extreme severities. This function then notifies citizens of the region.
    """
    level, reason = classify_severity(temperature, humidity, wind_speed)
    sev = severity_lookup()[level]

    prediction_id = execute(
        """INSERT INTO HeatwavePrediction
               (region_id, obs_id, severity_id, temperature, humidity, wind_speed, reason)
           VALUES (?,?,?,?,?,?,?)""",
        (region_id, obs_id, sev["severity_id"], temperature, humidity, wind_speed, reason),
    )

    # trigger already made the WarningAlert row; just let citizens know
    if sev["rank"] >= 3:
        region = query("SELECT * FROM Region WHERE region_id = ?", (region_id,), one=True)
        citizen_users = query(
            "SELECT user_id FROM Citizen WHERE region_id = ?", (region_id,))
        for cu in citizen_users:
            notify(cu["user_id"],
                   f"Heatwave warning for {region['name']}: temperature reached {temperature}°C. "
                   f"Avoid going out in the afternoon.")
    return prediction_id, level


@app.route("/predictions")
@login_required
def predictions():
    preds = query(
        """SELECT hp.*, r.name AS region_name, s.level
           FROM HeatwavePrediction hp
           JOIN Region r ON r.region_id = hp.region_id
           JOIN HeatwaveSeverity s ON s.severity_id = hp.severity_id
           ORDER BY hp.predicted_at DESC LIMIT 100""")
    regions = query("SELECT * FROM Region ORDER BY name")
    can_run = session.get("role") in ("Officer", "Administrator")
    return render_template("predictions.html", preds=preds, regions=regions, can_run=can_run)


@app.route("/predictions/run", methods=["POST"])
@role_required("Officer", "Administrator")
def run_prediction():
    """Manually run the expert system on a region's most recent observation."""
    region_id = request.form["region_id"]
    obs = query(
        """SELECT wo.* FROM WeatherObservation wo
           JOIN WeatherStation ws ON ws.station_id = wo.station_id
           WHERE ws.region_id = ? ORDER BY wo.observed_at DESC LIMIT 1""",
        (region_id,), one=True)
    if obs is None:
        flash("No weather observation found for that region yet.", "warning")
        return redirect(url_for("predictions"))

    _, level = run_prediction_for_region(region_id, obs["obs_id"],
                                          obs["temperature"], obs["humidity"], obs["wind_speed"])
    flash(f"Prediction complete: severity classified as {level}.", "success")
    return redirect(url_for("predictions"))


@app.route("/alerts")
@login_required
def alerts():
    """Active warning alerts. Citizens see their region; officers/admins see all."""
    user = current_user()
    if user["role"] == "Citizen":
        citizen = query("SELECT * FROM Citizen WHERE user_id = ?", (user["user_id"],), one=True)
        rows = query(
            """SELECT wa.*, r.name AS region_name, s.level FROM WarningAlert wa
               JOIN Region r ON r.region_id = wa.region_id
               JOIN HeatwaveSeverity s ON s.severity_id = wa.severity_id
               WHERE wa.region_id = ? AND wa.is_active = 1
               ORDER BY wa.issued_at DESC""", (citizen["region_id"],))
    else:
        rows = query(
            """SELECT wa.*, r.name AS region_name, s.level FROM WarningAlert wa
               JOIN Region r ON r.region_id = wa.region_id
               JOIN HeatwaveSeverity s ON s.severity_id = wa.severity_id
               WHERE wa.is_active = 1 ORDER BY wa.issued_at DESC""")

    # Attach advisories per alert severity.
    alerts_with_adv = [{**dict(r), "advisories": advisories_for(r["level"])} for r in rows]
    can_manage = user["role"] in ("Officer", "Administrator")
    return render_template("alerts.html", alerts=alerts_with_adv, can_manage=can_manage)


@app.route("/alerts/<int:alert_id>/deactivate", methods=["POST"])
@role_required("Officer", "Administrator")
def deactivate_alert(alert_id):
    execute("UPDATE WarningAlert SET is_active = 0 WHERE alert_id = ?", (alert_id,))
    flash("Alert marked inactive.", "info")
    return redirect(url_for("alerts"))


# --- complaint management (citizen create / view) --------------------------
@app.route("/complaints")
@login_required
def complaints():
    user = current_user()

    if user["role"] == "Citizen":
        citizen = query("SELECT * FROM Citizen WHERE user_id = ?", (user["user_id"],), one=True)
        rows = query(
            """SELECT c.*, r.name AS region_name, d.name AS dept_name
               FROM Complaint c
               JOIN Region r ON r.region_id = c.region_id
               LEFT JOIN GovernmentDepartment d ON d.dept_id = c.dept_id
               WHERE c.citizen_id = ? ORDER BY c.created_at DESC""",
            (citizen["citizen_id"],))
        return render_template("complaints.html", complaints=rows,
                               is_citizen=True, region=query(
                                   "SELECT * FROM Region WHERE region_id = ?",
                                   (citizen["region_id"],), one=True))

    # officer/admin view: all complaints, severity-prioritised
    rows = query(
        """SELECT c.*, r.name AS region_name, d.name AS dept_name, cu.full_name AS citizen_name,
                  COALESCE(sev.rank, 0) AS region_rank, COALESCE(sev.level, 'Low') AS region_level
           FROM Complaint c
           JOIN Region r ON r.region_id = c.region_id
           JOIN Citizen ct ON ct.citizen_id = c.citizen_id
           JOIN User cu ON cu.user_id = ct.user_id
           LEFT JOIN GovernmentDepartment d ON d.dept_id = c.dept_id
           LEFT JOIN (
                SELECT hp.region_id, hp.severity_id
                FROM HeatwavePrediction hp
                JOIN (SELECT region_id, MAX(predicted_at) AS mx
                      FROM HeatwavePrediction GROUP BY region_id) latest
                  ON latest.region_id = hp.region_id AND latest.mx = hp.predicted_at
           ) lp ON lp.region_id = c.region_id
           LEFT JOIN HeatwaveSeverity sev ON sev.severity_id = lp.severity_id
           ORDER BY (c.status = 'Resolved') ASC, region_rank DESC, c.created_at ASC""")
    return render_template("complaints.html", complaints=rows,
                           is_citizen=False, region=None)


@app.route("/complaints/add", methods=["POST"])
@role_required("Citizen")
def add_complaint():
    user = current_user()
    citizen = query("SELECT * FROM Citizen WHERE user_id = ?", (user["user_id"],), one=True)
    complaint_id = execute(
        """INSERT INTO Complaint (citizen_id, region_id, category, description)
           VALUES (?,?,?,?)""",
        (citizen["citizen_id"], citizen["region_id"],
         request.form["category"], request.form["description"].strip()),
    )
    # Notify administrators of the new complaint.
    for admin in query("SELECT user_id FROM User WHERE role = 'Administrator'"):
        notify(admin["user_id"], f"New complaint #{complaint_id} filed and awaiting assignment.")
    flash("Complaint submitted.", "success")
    return redirect(url_for("complaints"))


@app.route("/complaints/<int:complaint_id>")
@login_required
def complaint_detail(complaint_id):
    user = current_user()
    c = query(
        """SELECT c.*, r.name AS region_name, d.name AS dept_name,
                  cu.full_name AS citizen_name, ou.full_name AS officer_name
           FROM Complaint c
           JOIN Region r ON r.region_id = c.region_id
           JOIN Citizen ct ON ct.citizen_id = c.citizen_id
           JOIN User cu ON cu.user_id = ct.user_id
           LEFT JOIN GovernmentDepartment d ON d.dept_id = c.dept_id
           LEFT JOIN Officer o ON o.officer_id = c.assigned_officer_id
           LEFT JOIN User ou ON ou.user_id = o.user_id
           WHERE c.complaint_id = ?""", (complaint_id,), one=True)
    if c is None:
        abort(404)

    # A citizen may only see their own complaint.
    if user["role"] == "Citizen":
        citizen = query("SELECT * FROM Citizen WHERE user_id = ?", (user["user_id"],), one=True)
        if c["citizen_id"] != citizen["citizen_id"]:
            abort(403)

    departments = query("SELECT * FROM GovernmentDepartment ORDER BY name")
    officers = query(
        """SELECT o.officer_id, u.full_name, d.name AS dept_name
           FROM Officer o JOIN User u ON u.user_id = o.user_id
           JOIN GovernmentDepartment d ON d.dept_id = o.dept_id ORDER BY u.full_name""")
    return render_template("complaint_detail.html", c=c, departments=departments,
                           officers=officers, can_manage=user["role"] in ("Officer", "Administrator"))


# --- complaint assignment & resolution --------------------------------------
@app.route("/complaints/<int:complaint_id>/assign", methods=["POST"])
@role_required("Officer", "Administrator")
def assign_complaint(complaint_id):
    dept_id = request.form.get("dept_id") or None
    officer_id = request.form.get("officer_id") or None
    execute("UPDATE Complaint SET dept_id = ?, assigned_officer_id = ? WHERE complaint_id = ?",
            (dept_id, officer_id, complaint_id))
    # Notify assigned officer.
    if officer_id:
        off = query("SELECT user_id FROM Officer WHERE officer_id = ?", (officer_id,), one=True)
        if off:
            notify(off["user_id"], f"Complaint #{complaint_id} has been assigned to you.")
    flash("Complaint assignment updated.", "success")
    return redirect(url_for("complaint_detail", complaint_id=complaint_id))


@app.route("/complaints/<int:complaint_id>/status", methods=["POST"])
@role_required("Officer", "Administrator")
def update_complaint_status(complaint_id):
    status = request.form["status"]
    if status not in ("Open", "In Progress", "Resolved"):
        abort(400)
    if status == "Resolved":
        execute("UPDATE Complaint SET status = ?, resolved_at = datetime('now') WHERE complaint_id = ?",
                (status, complaint_id))
    else:
        execute("UPDATE Complaint SET status = ?, resolved_at = NULL WHERE complaint_id = ?",
                (status, complaint_id))

    # Notify the citizen who filed it.
    c = query("""SELECT ct.user_id FROM Complaint c
                 JOIN Citizen ct ON ct.citizen_id = c.citizen_id
                 WHERE c.complaint_id = ?""", (complaint_id,), one=True)
    if c:
        notify(c["user_id"], f"Your complaint #{complaint_id} status is now '{status}'.")
    flash(f"Complaint status updated to {status}.", "success")
    return redirect(url_for("complaint_detail", complaint_id=complaint_id))


# --- dashboard & reports (Chart.js) ------------------------------------------
def region_risk_levels():
    """Latest severity level per region (for the color-coded risk list)."""
    return query(
        """SELECT r.region_id, r.name AS region_name,
                  COALESCE(s.level, 'No data') AS level,
                  COALESCE(s.rank, 0) AS rank,
                  hp.temperature, hp.predicted_at
           FROM Region r
           LEFT JOIN (
                SELECT hp.* FROM HeatwavePrediction hp
                JOIN (SELECT region_id, MAX(predicted_at) AS mx
                      FROM HeatwavePrediction GROUP BY region_id) latest
                  ON latest.region_id = hp.region_id AND latest.mx = hp.predicted_at
           ) hp ON hp.region_id = r.region_id
           LEFT JOIN HeatwaveSeverity s ON s.severity_id = hp.severity_id
           ORDER BY rank DESC, r.name""")


@app.route("/reports")
@role_required("Officer", "Administrator")
def reports():
    summary = query("SELECT * FROM v_region_complaint_summary ORDER BY total_complaints DESC")
    risk = region_risk_levels()
    active_alerts = query(
        """SELECT wa.*, r.name AS region_name, s.level FROM WarningAlert wa
           JOIN Region r ON r.region_id = wa.region_id
           JOIN HeatwaveSeverity s ON s.severity_id = wa.severity_id
           WHERE wa.is_active = 1 ORDER BY s.rank DESC, wa.issued_at DESC""")
    return render_template("reports.html", summary=summary, risk=risk, active_alerts=active_alerts)


@app.route("/api/complaints_by_status")
@role_required("Officer", "Administrator")
def api_complaints_by_status():
    rows = query("SELECT status, COUNT(*) AS c FROM Complaint GROUP BY status")
    data = {r["status"]: r["c"] for r in rows}
    return jsonify({
        "labels": ["Open", "In Progress", "Resolved"],
        "values": [data.get("Open", 0), data.get("In Progress", 0), data.get("Resolved", 0)],
    })


@app.route("/api/complaints_by_region")
@role_required("Officer", "Administrator")
def api_complaints_by_region():
    rows = query("SELECT region_name, total_complaints FROM v_region_complaint_summary "
                 "ORDER BY total_complaints DESC")
    return jsonify({
        "labels": [r["region_name"] for r in rows],
        "values": [r["total_complaints"] for r in rows],
    })


@app.route("/api/severity_distribution")
@role_required("Officer", "Administrator")
def api_severity_distribution():
    rows = query(
        """SELECT s.level, COUNT(hp.prediction_id) AS c
           FROM HeatwaveSeverity s
           LEFT JOIN HeatwavePrediction hp ON hp.severity_id = s.severity_id
           GROUP BY s.level, s.rank ORDER BY s.rank""")
    return jsonify({
        "labels": [r["level"] for r in rows],
        "values": [r["c"] for r in rows],
    })


@app.route("/api/prediction_trend")
@role_required("Officer", "Administrator")
def api_prediction_trend():
    """Predictions per day (trend chart)."""
    rows = query(
        """SELECT date(predicted_at) AS d, COUNT(*) AS c
           FROM HeatwavePrediction GROUP BY date(predicted_at) ORDER BY d""")
    return jsonify({
        "labels": [r["d"] for r in rows],
        "values": [r["c"] for r in rows],
    })


# --- database administration (row counts + CSV export) ----------------------
@app.route("/admin/db")
@role_required("Administrator")
def admin_db():
    counts = []
    for table in ADMIN_TABLES:
        row = query(f"SELECT COUNT(*) AS c FROM {table}", one=True)
        counts.append({"table": table, "rows": row["c"]})
    return render_template("admin_db.html", counts=counts)


@app.route("/admin/export/<table>")
@role_required("Administrator")
def admin_export(table):
    if table not in ADMIN_TABLES:
        abort(404)
    rows = query(f"SELECT * FROM {table}")
    output = io.StringIO()
    writer = csv.writer(output)
    if rows:
        writer.writerow(rows[0].keys())
        for r in rows:
            writer.writerow(list(r))
    else:
        # Still emit the header row from PRAGMA table_info.
        cols = [c["name"] for c in query(f"PRAGMA table_info({table})")]
        writer.writerow(cols)
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename={table}.csv"},
    )


# ---------------------------------------------------------------------------
# Notifications
# ---------------------------------------------------------------------------
@app.route("/notifications")
@login_required
def notifications():
    user = current_user()
    rows = query("SELECT * FROM Notification WHERE user_id = ? ORDER BY created_at DESC",
                 (user["user_id"],))
    execute("UPDATE Notification SET is_read = 1 WHERE user_id = ?", (user["user_id"],))
    return render_template("notifications.html", notifications=rows)


# ---------------------------------------------------------------------------
# Error handlers
# ---------------------------------------------------------------------------
@app.errorhandler(403)
def forbidden(e):
    return render_template("error.html", code=403,
                           message="You do not have permission to access this page."), 403


@app.errorhandler(404)
def not_found(e):
    return render_template("error.html", code=404, message="Page not found."), 404


if __name__ == "__main__":
    if not os.path.exists(DATABASE):
        print("Database not found. Run:  python init_db.py")
    app.run(debug=True)
