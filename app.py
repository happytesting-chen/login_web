import logging
import smtplib
import threading
from contextlib import contextmanager
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from flask import Flask, request, jsonify, session, render_template, redirect, url_for
from flask_bcrypt import Bcrypt
from flask_cors import CORS
from itsdangerous import URLSafeTimedSerializer
import sqlite3
from datetime import datetime, timezone, timedelta
import os
import requests

# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------
app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY")
bcrypt = Bcrypt(app)
CORS(app, supports_credentials=True)  # allow cookies + any origin during dev

DB_PATH = "app.db"

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Email configuration (Gmail SMTP)
# ---------------------------------------------------------------------------
# Set these environment variables or change the defaults below:
#   SMTP_EMAIL     – your Gmail address (used to send emails)
#   SMTP_PASSWORD  – Gmail App Password (NOT your normal password)
#   BOSS_EMAIL     – the boss's email to receive leave notifications

SMTP_EMAIL    = os.environ.get("SMTP_EMAIL", "")
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")
BOSS_EMAIL    = os.environ.get("BOSS_EMAIL", "cherrycc0324@gmail.com")

# Token serializer for email approve/reject links
token_serializer = URLSafeTimedSerializer(
    os.environ.get("FLASK_SECRET_KEY", "change-this-in-production")
)


def _generate_leave_token(leave_id: int, action: str) -> str:
    """Generate a signed token for approving/rejecting a leave via email link."""
    return token_serializer.dumps({"leave_id": leave_id, "action": action}, salt="leave-action")


def _verify_leave_token(token: str, max_age: int = 7 * 86400) -> dict | None:
    """Verify a leave action token. Valid for 7 days by default."""
    try:
        return token_serializer.loads(token, salt="leave-action", max_age=max_age)
    except Exception:
        return None


def _send_email(to_email: str, subject: str, html_body: str):
    """Send an HTML email via Gmail SMTP in a background thread."""
    if not SMTP_EMAIL or not SMTP_PASSWORD:
        log.warning("Email not configured (SMTP_EMAIL / SMTP_PASSWORD missing). Skipping email to %s", to_email)
        return

    def _do_send():
        try:
            msg = MIMEMultipart("alternative")
            msg["From"] = SMTP_EMAIL
            msg["To"] = to_email
            msg["Subject"] = subject
            msg.attach(MIMEText(html_body, "html"))

            with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
                server.login(SMTP_EMAIL, SMTP_PASSWORD)
                server.sendmail(SMTP_EMAIL, to_email, msg.as_string())
            log.info("Email sent to %s: %s", to_email, subject)
        except Exception as exc:
            log.error("Failed to send email to %s: %s", to_email, exc)

    threading.Thread(target=_do_send, daemon=True).start()


def _get_base_url() -> str:
    """Get the base URL (works with ngrok / proxy)."""
    proto = request.headers.get("X-Forwarded-Proto", request.scheme)
    host = request.headers.get("X-Forwarded-Host") or request.headers.get("Host", "localhost:5000")
    return f"{proto}://{host}"


def _send_leave_notification(leave_id, username, leave_type, from_date, to_date, days, reason, submitted_at):
    """Send leave request email to boss with approve/reject links."""
    base_url = _get_base_url()
    approve_token = _generate_leave_token(leave_id, "Approved")
    reject_token = _generate_leave_token(leave_id, "Rejected")

    approve_url = f"{base_url}/leave-action/{approve_token}"
    reject_url = f"{base_url}/leave-action/{reject_token}"

    subject = f"Leave Request: {username} — {leave_type} ({days} day{'s' if days != 1 else ''})"

    html = f"""
    <div style="font-family: Arial, sans-serif; max-width: 520px; margin: 0 auto; padding: 20px;">
      <h2 style="color: #1a1a1a; margin-bottom: 20px;">Leave Request</h2>
      <table style="width: 100%; border-collapse: collapse; font-size: 15px;">
        <tr><td style="padding: 8px 0; color: #888; width: 110px;">Staff</td>
            <td style="padding: 8px 0; font-weight: 700;">{username}</td></tr>
        <tr><td style="padding: 8px 0; color: #888;">Leave Type</td>
            <td style="padding: 8px 0;">{leave_type}</td></tr>
        <tr><td style="padding: 8px 0; color: #888;">Dates</td>
            <td style="padding: 8px 0;">{from_date}  →  {to_date}  ({days} day{'s' if days != 1 else ''})</td></tr>
        <tr><td style="padding: 8px 0; color: #888;">Reason</td>
            <td style="padding: 8px 0;">{reason or '—'}</td></tr>
        <tr><td style="padding: 8px 0; color: #888;">Submitted</td>
            <td style="padding: 8px 0;">{submitted_at}</td></tr>
      </table>

      <div style="margin-top: 24px; text-align: center;">
        <a href="{approve_url}"
           style="display: inline-block; background: #28a745; color: #fff; text-decoration: none;
                  padding: 14px 40px; border-radius: 8px; font-size: 16px; font-weight: 600;
                  margin-right: 12px;">
          ✓ Approve
        </a>
        <a href="{reject_url}"
           style="display: inline-block; background: #dc3545; color: #fff; text-decoration: none;
                  padding: 14px 40px; border-radius: 8px; font-size: 16px; font-weight: 600;">
          ✗ Reject
        </a>
      </div>

      <p style="margin-top: 24px; font-size: 12px; color: #999;">
        Click a button above to approve or reject. Links expire in 7 days.
      </p>
    </div>
    """

    _send_email(BOSS_EMAIL, subject, html)

# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------

@contextmanager
def get_db():
    """Context-managed DB connection – auto-closes on exit."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def init_db():
    with get_db() as conn:
        cur = conn.cursor()

        cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS login_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                username TEXT NOT NULL,
                login_time TEXT NOT NULL,
                ip TEXT,
                user_agent TEXT,
                lat REAL,
                lon REAL,
                location_source TEXT,
                area TEXT,
                address_text TEXT,
                event_type TEXT DEFAULT '',
                is_late INTEGER DEFAULT 0,
                ot_minutes INTEGER DEFAULT 0,
                working_minutes INTEGER DEFAULT 0,
                FOREIGN KEY(user_id) REFERENCES users(id)
            )
        """)

        # Migrate: add columns if table was created before this change
        existing_cols = {
            row["name"]
            for row in cur.execute("PRAGMA table_info(login_events)").fetchall()
        }
        for col, dtype in [("area", "TEXT"), ("address_text", "TEXT"),
                           ("event_type", "TEXT DEFAULT ''"),
                           ("is_late", "INTEGER DEFAULT 0"),
                           ("ot_minutes", "INTEGER DEFAULT 0"),
                           ("working_minutes", "INTEGER DEFAULT 0")]:
            if col not in existing_cols:
                cur.execute(f"ALTER TABLE login_events ADD COLUMN {col} {dtype}")

        cur.execute("""
            CREATE TABLE IF NOT EXISTS leave_applications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                username TEXT NOT NULL,
                leave_type TEXT NOT NULL,
                from_date TEXT NOT NULL,
                to_date TEXT NOT NULL,
                days REAL DEFAULT 0,
                reason TEXT DEFAULT '',
                status TEXT DEFAULT 'Pending',
                submitted_at TEXT NOT NULL,
                reviewed_by TEXT DEFAULT '',
                reviewed_at TEXT DEFAULT '',
                FOREIGN KEY(user_id) REFERENCES users(id)
            )
        """)

        # Migrate leave_applications if needed
        la_cols = {
            row["name"]
            for row in cur.execute("PRAGMA table_info(leave_applications)").fetchall()
        }
        for col, dtype in [("days", "REAL DEFAULT 0"),
                           ("reviewed_by", "TEXT DEFAULT ''"),
                           ("reviewed_at", "TEXT DEFAULT ''")]:
            if col not in la_cols:
                cur.execute(f"ALTER TABLE leave_applications ADD COLUMN {col} {dtype}")

        cur.execute("""
            CREATE TABLE IF NOT EXISTS leave_entitlements (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                username TEXT NOT NULL,
                leave_type TEXT NOT NULL,
                total_days REAL NOT NULL DEFAULT 0,
                UNIQUE(user_id, leave_type),
                FOREIGN KEY(user_id) REFERENCES users(id)
            )
        """)

        conn.commit()


# ---------------------------------------------------------------------------
# Utility helpers
# ---------------------------------------------------------------------------

SGT = timezone(timedelta(hours=8))  # Singapore Time (UTC+8)

WORK_START = 8 * 60 + 30   # 08:30 in minutes since midnight
WORK_END   = 17 * 60       # 17:00 (5 PM) in minutes since midnight


def _now_sgt() -> datetime:
    """Return current Singapore datetime object."""
    return datetime.now(SGT)


def _fmt_sgt(dt: datetime) -> str:
    """Format a datetime as a human-readable SGT string (12-hour AM/PM)."""
    return dt.strftime("%d %b %Y %I:%M:%S %p")


def _today_date_str(dt: datetime) -> str:
    """Return date in the same format prefix stored in login_time (e.g. '10 Feb 2026')."""
    return dt.strftime("%d %b %Y")


def client_ip() -> str:
    """Best-effort client IP (respects X-Forwarded-For)."""
    xff = request.headers.get("X-Forwarded-For", "")
    if xff:
        return xff.split(",")[0].strip()
    return request.remote_addr


def _is_admin() -> bool:
    """Check if the current logged-in user is an admin (username contains 'admin' or 'shawn')."""
    uname = (session.get("username") or "").lower()
    return "admin" in uname or "shawn" in uname


# ---------------------------------------------------------------------------
# Reverse geocoding via OpenStreetMap Nominatim
# ---------------------------------------------------------------------------

NOMINATIM_URL = "https://nominatim.openstreetmap.org/reverse"
NOMINATIM_HEADERS = {
    "User-Agent": "LoginAuditApp/1.0",
    "Accept-Language": "en",
}
NOMINATIM_TIMEOUT = 5  # seconds


def reverse_geocode(lat: float, lon: float) -> dict:
    """
    Convert lat/lon → human-readable location via Nominatim.
    Returns {"area": "...", "address_text": "..."} or empty strings on failure.
    """
    try:
        resp = requests.get(
            NOMINATIM_URL,
            params={"lat": lat, "lon": lon, "format": "jsonv2",
                    "zoom": 18, "addressdetails": 1},
            headers=NOMINATIM_HEADERS,
            timeout=NOMINATIM_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()

        addr = data.get("address", {})
        # Build area: neighbourhood + suburb for Singapore context
        # e.g. "Teck Whye, Choa Chu Kang" or just "Choa Chu Kang"
        neighbourhood = (
            addr.get("neighbourhood")
            or addr.get("residential")
            or ""
        )
        suburb = (
            addr.get("suburb")
            or addr.get("town")
            or addr.get("city_district")
            or addr.get("borough")
            or addr.get("city")
            or ""
        )
        if neighbourhood and suburb and neighbourhood != suburb:
            area = f"{neighbourhood}, {suburb}"
        else:
            area = suburb or neighbourhood
        address_text = data.get("display_name", "")

        log.info("Geocoded (%s, %s) → area=%s", lat, lon, area)
        return {"area": area, "address_text": address_text}

    except Exception as exc:
        log.warning("Reverse-geocode failed for (%s, %s): %s", lat, lon, exc)
        return {"area": "", "address_text": ""}


# ---------------------------------------------------------------------------
# Routes – pages
# ---------------------------------------------------------------------------

@app.get("/")
def home():
    # If already logged in, go straight to dashboard
    if "user_id" in session:
        return render_template("dashboard.html")
    return render_template("index.html")


@app.get("/dashboard")
def dashboard():
    if "user_id" not in session:
        return render_template("index.html")
    return render_template("dashboard.html")


# ---------------------------------------------------------------------------
# Routes – auth API
# ---------------------------------------------------------------------------

@app.post("/api/register")
def register():
    data = request.get_json(force=True)
    username = (data.get("username") or "").strip()
    password = (data.get("password") or "")

    if len(username) < 3:
        return jsonify(error="Username must be at least 3 characters."), 400
    if len(password) < 8:
        return jsonify(error="Password must be at least 8 characters."), 400

    pw_hash = bcrypt.generate_password_hash(password).decode("utf-8")
    now = _fmt_sgt(_now_sgt())

    try:
        with get_db() as conn:
            conn.execute(
                "INSERT INTO users (username, password_hash, created_at) VALUES (?, ?, ?)",
                (username, pw_hash, now),
            )
            conn.commit()
        return jsonify(ok=True), 201
    except sqlite3.IntegrityError:
        return jsonify(error="Username already exists."), 409


@app.post("/api/login")
def login():
    data = request.get_json(force=True)
    username = (data.get("username") or "").strip()
    password = (data.get("password") or "")

    if not username or not password:
        return jsonify(error="Username and password required."), 400

    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT id, username, password_hash FROM users WHERE username = ?",
            (username,),
        )
        row = cur.fetchone()

        if not row or not bcrypt.check_password_hash(row["password_hash"], password):
            return jsonify(error="Invalid username or password."), 401

        # Create session
        session["user_id"] = row["id"]
        session["username"] = row["username"]

    return jsonify(ok=True, username=row["username"])


# ---------------------------------------------------------------------------
# Routes – Clock In/Out (separate from login)
# ---------------------------------------------------------------------------

@app.post("/api/clock")
def clock():
    if "user_id" not in session:
        return jsonify(error="Not logged in"), 401

    # Admin accounts don't clock
    if _is_admin():
        return jsonify(error="Admin accounts do not clock in/out."), 400

    data = request.get_json(force=True)
    location = data.get("location") or {}
    action = (data.get("action") or "").strip()

    if action not in ("Clock In", "Clock Out"):
        return jsonify(error="Invalid action."), 400

    user_id = session["user_id"]
    username = session["username"]

    ip = client_ip()
    ua = request.headers.get("User-Agent")
    now_dt = _now_sgt()
    now = _fmt_sgt(now_dt)
    today = _today_date_str(now_dt)

    lat = location.get("lat")
    lon = location.get("lon")
    source = location.get("source", "none")

    # Reverse-geocode
    area = ""
    address_text = ""
    if lat is not None and lon is not None:
        geo = reverse_geocode(lat, lon)
        area = geo["area"]
        address_text = geo["address_text"]

    with get_db() as conn:
        cur = conn.cursor()

        # Check today's events
        cur.execute("""
            SELECT id, login_time, event_type FROM login_events
            WHERE user_id = ? AND login_time LIKE ?
            ORDER BY id ASC
        """, (user_id, f"%{today}%"))
        today_events = cur.fetchall()

        event_type = action

        # Validate: can't clock in if already clocked in without clock out
        has_clock_in = any(e["event_type"] == "Clock In" for e in today_events)
        has_clock_out = any(e["event_type"] == "Clock Out" for e in today_events)

        if action == "Clock In" and has_clock_in:
            return jsonify(error="You have already clocked in today."), 400
        if action == "Clock Out" and not has_clock_in:
            return jsonify(error="You need to clock in first."), 400

        # Late detection
        is_late = 0
        if event_type == "Clock In":
            minutes_now = now_dt.hour * 60 + now_dt.minute
            if minutes_now > WORK_START:
                is_late = 1

        # OT calculation
        ot_minutes = 0
        if event_type == "Clock Out":
            minutes_now = now_dt.hour * 60 + now_dt.minute
            if minutes_now > WORK_END:
                ot_minutes = minutes_now - WORK_END

        # Working hours
        working_minutes = 0
        if event_type == "Clock Out" and today_events:
            clock_in_row = None
            for ev in today_events:
                if ev["event_type"] == "Clock In":
                    clock_in_row = ev
                    break
            if clock_in_row:
                try:
                    clock_in_dt = datetime.strptime(
                        clock_in_row["login_time"], "%d %b %Y %I:%M:%S %p"
                    ).replace(tzinfo=SGT)
                    diff = now_dt - clock_in_dt
                    working_minutes = max(0, int(diff.total_seconds() // 60))
                except Exception:
                    working_minutes = 0

        cur.execute("""
            INSERT INTO login_events
                (user_id, username, login_time, ip, user_agent,
                 lat, lon, location_source, area, address_text,
                 event_type, is_late, ot_minutes, working_minutes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (user_id, username, now, ip, ua,
              lat, lon, source, area, address_text,
              event_type, is_late, ot_minutes, working_minutes))
        conn.commit()

    return jsonify(ok=True, event_type=event_type, time=now)


# ---------------------------------------------------------------------------
# Leave helpers
# ---------------------------------------------------------------------------

LEAVE_TYPES = ["Annual Leave", "Sick Leave", "Child Care Leave"]

DEFAULT_ENTITLEMENTS = {
    "Annual Leave": 18,
    "Sick Leave": 12,
    "Child Care Leave": 7,
}


def _count_weekdays(from_str: str, to_str: str) -> int:
    """Count weekdays (Mon-Fri) between two ISO date strings inclusive."""
    try:
        d1 = datetime.strptime(from_str, "%Y-%m-%d").date()
        d2 = datetime.strptime(to_str, "%Y-%m-%d").date()
        if d2 < d1:
            return 0
        count = 0
        current = d1
        while current <= d2:
            if current.weekday() < 5:  # Mon=0 … Fri=4
                count += 1
            current += timedelta(days=1)
        return count
    except Exception:
        return 0


def _get_balance(conn, user_id: int) -> list:
    """
    Return leave balance for a user as a list of dicts:
    [{ leave_type, total, used, pending, balance }]
    """
    # Get entitlements
    ent_rows = conn.execute(
        "SELECT leave_type, total_days FROM leave_entitlements WHERE user_id = ?",
        (user_id,)
    ).fetchall()
    entitlements = {r["leave_type"]: r["total_days"] for r in ent_rows}

    # Get approved days used
    used_rows = conn.execute("""
        SELECT leave_type, COALESCE(SUM(days), 0) as used
        FROM leave_applications
        WHERE user_id = ? AND status = 'Approved'
        GROUP BY leave_type
    """, (user_id,)).fetchall()
    used = {r["leave_type"]: r["used"] for r in used_rows}

    # Get pending days
    pending_rows = conn.execute("""
        SELECT leave_type, COALESCE(SUM(days), 0) as pending
        FROM leave_applications
        WHERE user_id = ? AND status = 'Pending'
        GROUP BY leave_type
    """, (user_id,)).fetchall()
    pending = {r["leave_type"]: r["pending"] for r in pending_rows}

    result = []
    for lt in LEAVE_TYPES:
        total = entitlements.get(lt, 0)
        u = used.get(lt, 0)
        p = pending.get(lt, 0)
        result.append({
            "leave_type": lt,
            "total": total,
            "used": u,
            "pending": p,
            "balance": total - u,
        })
    return result


# ---------------------------------------------------------------------------
# Routes – Leave Application
# ---------------------------------------------------------------------------

@app.post("/api/leave")
def apply_leave():
    if "user_id" not in session:
        return jsonify(error="Not logged in"), 401

    data = request.get_json(force=True)
    leave_type = (data.get("leave_type") or "").strip()
    from_date = (data.get("from_date") or "").strip()
    to_date = (data.get("to_date") or "").strip()
    reason = (data.get("reason") or "").strip()

    if not leave_type or not from_date or not to_date:
        return jsonify(error="Leave type and dates are required."), 400
    if leave_type not in LEAVE_TYPES:
        return jsonify(error="Invalid leave type."), 400

    days = _count_weekdays(from_date, to_date)
    if days <= 0:
        return jsonify(error="Invalid date range."), 400

    now = _fmt_sgt(_now_sgt())

    with get_db() as conn:
        # Check balance
        balance = _get_balance(conn, session["user_id"])
        bal_entry = next((b for b in balance if b["leave_type"] == leave_type), None)
        if bal_entry and days > bal_entry["balance"]:
            return jsonify(
                error=f"Insufficient {leave_type} balance. You have {bal_entry['balance']} day(s) left, requesting {days} day(s)."
            ), 400

        cur = conn.cursor()
        cur.execute("""
            INSERT INTO leave_applications
                (user_id, username, leave_type, from_date, to_date, days, reason, submitted_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (session["user_id"], session["username"],
              leave_type, from_date, to_date, days, reason, now))
        conn.commit()
        leave_id = cur.lastrowid

    # Send email notification to boss
    _send_leave_notification(leave_id, session["username"], leave_type,
                             from_date, to_date, days, reason, now)

    return jsonify(ok=True, days=days)


@app.get("/api/leaves")
def get_leaves():
    if "user_id" not in session:
        return jsonify(error="Not logged in"), 401

    with get_db() as conn:
        if _is_admin():
            rows = conn.execute("""
                SELECT * FROM leave_applications ORDER BY id DESC LIMIT 200
            """).fetchall()
        else:
            rows = conn.execute("""
                SELECT * FROM leave_applications WHERE user_id = ? ORDER BY id DESC LIMIT 50
            """, (session["user_id"],)).fetchall()

    return jsonify([dict(r) for r in rows])


@app.get("/api/leave-balance")
def leave_balance():
    """Get leave balance for the current user (or a specific user if admin)."""
    if "user_id" not in session:
        return jsonify(error="Not logged in"), 401

    target_user_id = session["user_id"]

    # Admin can query any user's balance
    if _is_admin() and request.args.get("user_id"):
        target_user_id = int(request.args["user_id"])

    with get_db() as conn:
        balance = _get_balance(conn, target_user_id)
    return jsonify(balance)


# ---------------------------------------------------------------------------
# Routes – Admin: Leave Entitlements
# ---------------------------------------------------------------------------

@app.get("/api/admin/staff")
def admin_staff_list():
    """List all staff (non-admin users) for admin to manage."""
    if "user_id" not in session:
        return jsonify(error="Not logged in"), 401
    if not _is_admin():
        return jsonify(error="Admin only"), 403

    with get_db() as conn:
        rows = conn.execute(
            "SELECT id, username, created_at FROM users ORDER BY username"
        ).fetchall()
    return jsonify([dict(r) for r in rows])


@app.get("/api/admin/entitlements")
def admin_get_entitlements():
    """Get all entitlements for all users."""
    if "user_id" not in session:
        return jsonify(error="Not logged in"), 401
    if not _is_admin():
        return jsonify(error="Admin only"), 403

    with get_db() as conn:
        users = conn.execute(
            "SELECT id, username FROM users ORDER BY username"
        ).fetchall()
        result = []
        for u in users:
            # Skip admin users
            uname_lower = u["username"].lower()
            if "admin" in uname_lower or "shawn" in uname_lower:
                continue
            balance = _get_balance(conn, u["id"])
            result.append({
                "user_id": u["id"],
                "username": u["username"],
                "entitlements": balance,
            })
    return jsonify(result)


@app.post("/api/admin/entitlements")
def admin_set_entitlements():
    """Set leave entitlements for a specific user."""
    if "user_id" not in session:
        return jsonify(error="Not logged in"), 401
    if not _is_admin():
        return jsonify(error="Admin only"), 403

    data = request.get_json(force=True)
    target_user_id = data.get("user_id")
    entitlements = data.get("entitlements", {})  # { "Annual Leave": 18, ... }

    if not target_user_id:
        return jsonify(error="user_id is required."), 400

    with get_db() as conn:
        # Verify user exists
        user = conn.execute("SELECT id, username FROM users WHERE id = ?",
                            (target_user_id,)).fetchone()
        if not user:
            return jsonify(error="User not found."), 404

        for lt, days in entitlements.items():
            if lt not in LEAVE_TYPES:
                continue
            conn.execute("""
                INSERT INTO leave_entitlements (user_id, username, leave_type, total_days)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(user_id, leave_type)
                DO UPDATE SET total_days = ?
            """, (target_user_id, user["username"], lt, days, days))
        conn.commit()

    return jsonify(ok=True)


@app.post("/api/admin/leave-action")
def admin_leave_action():
    """Approve or reject a leave application."""
    if "user_id" not in session:
        return jsonify(error="Not logged in"), 401
    if not _is_admin():
        return jsonify(error="Admin only"), 403

    data = request.get_json(force=True)
    leave_id = data.get("leave_id")
    action = (data.get("action") or "").strip()

    if action not in ("Approved", "Rejected"):
        return jsonify(error="Action must be 'Approved' or 'Rejected'."), 400

    now = _fmt_sgt(_now_sgt())

    with get_db() as conn:
        leave = conn.execute("SELECT * FROM leave_applications WHERE id = ?",
                             (leave_id,)).fetchone()
        if not leave:
            return jsonify(error="Leave application not found."), 404
        if leave["status"] != "Pending":
            return jsonify(error="This leave has already been " + leave["status"].lower() + "."), 400

        conn.execute("""
            UPDATE leave_applications
            SET status = ?, reviewed_by = ?, reviewed_at = ?
            WHERE id = ?
        """, (action, session["username"], now, leave_id))
        conn.commit()

    return jsonify(ok=True)


# ---------------------------------------------------------------------------
# Routes – Email-based leave approval (no login required, uses signed token)
# ---------------------------------------------------------------------------

@app.get("/leave-action/<token>")
def email_leave_action(token):
    """Handle approve/reject clicks from email."""
    data = _verify_leave_token(token)
    if not data:
        return """
        <html><body style="font-family:Arial;text-align:center;padding:60px 20px;">
        <h2 style="color:#dc3545;">Link Expired or Invalid</h2>
        <p>This approval link has expired or is invalid. Please use the dashboard to manage leave requests.</p>
        </body></html>
        """, 400

    leave_id = data["leave_id"]
    action = data["action"]
    now = _fmt_sgt(_now_sgt())

    with get_db() as conn:
        leave = conn.execute("SELECT * FROM leave_applications WHERE id = ?",
                             (leave_id,)).fetchone()
        if not leave:
            return """
            <html><body style="font-family:Arial;text-align:center;padding:60px 20px;">
            <h2 style="color:#dc3545;">Not Found</h2>
            <p>This leave application was not found.</p>
            </body></html>
            """, 404

        if leave["status"] != "Pending":
            color = "#28a745" if leave["status"] == "Approved" else "#dc3545"
            return f"""
            <html><body style="font-family:Arial;text-align:center;padding:60px 20px;">
            <h2 style="color:{color};">Already {leave["status"]}</h2>
            <p>This leave by <strong>{leave["username"]}</strong> has already been {leave["status"].lower()}.</p>
            </body></html>
            """

        conn.execute("""
            UPDATE leave_applications
            SET status = ?, reviewed_by = 'Shawn (via email)', reviewed_at = ?
            WHERE id = ?
        """, (action, now, leave_id))
        conn.commit()

    # Show result page
    if action == "Approved":
        color = "#28a745"
        icon = "✓"
    else:
        color = "#dc3545"
        icon = "✗"

    return f"""
    <html><body style="font-family:Arial;text-align:center;padding:60px 20px;">
    <div style="font-size:60px;">{icon}</div>
    <h2 style="color:{color};">Leave {action}</h2>
    <p>Leave request by <strong>{leave["username"]}</strong> has been <strong>{action.lower()}</strong>.</p>
    <table style="margin:20px auto;text-align:left;font-size:15px;">
      <tr><td style="padding:4px 12px;color:#888;">Type</td><td>{leave["leave_type"]}</td></tr>
      <tr><td style="padding:4px 12px;color:#888;">Dates</td><td>{leave["from_date"]} → {leave["to_date"]} ({leave["days"]} days)</td></tr>
    </table>
    <p style="margin-top:24px;color:#999;font-size:13px;">You can close this page.</p>
    </body></html>
    """


@app.post("/api/logout")
def logout():
    session.clear()
    return jsonify(ok=True)


@app.get("/api/me")
def me():
    if "user_id" not in session:
        return jsonify(logged_in=False), 401
    return jsonify(logged_in=True, user_id=session["user_id"],
                   username=session["username"])


# ---------------------------------------------------------------------------
# Routes – login events
# ---------------------------------------------------------------------------

@app.get("/api/login-events")
def login_events():
    if "user_id" not in session:
        return jsonify(error="Not logged in"), 401

    with get_db() as conn:
        if _is_admin():
            # Admin / Shawn can see ALL users' records
            rows = conn.execute("""
                SELECT id, username, login_time, ip, user_agent,
                       lat, lon, location_source, area, address_text,
                       event_type, is_late, ot_minutes, working_minutes
                FROM login_events
                ORDER BY id DESC
                LIMIT 200
            """).fetchall()
        else:
            # Regular users see only their own records
            rows = conn.execute("""
                SELECT id, username, login_time, ip, user_agent,
                       lat, lon, location_source, area, address_text,
                       event_type, is_late, ot_minutes, working_minutes
                FROM login_events
                WHERE user_id = ?
                ORDER BY id DESC
                LIMIT 50
            """, (session["user_id"],)).fetchall()

    return jsonify([dict(r) for r in rows])


@app.get("/admin/logins")
def admin_logins():
    if "user_id" not in session:
        return "Not logged in", 401
    if not _is_admin():
        return "Access denied — admin only", 403

    with get_db() as conn:
        records = [
            dict(r) for r in conn.execute("""
                SELECT id, username, login_time, ip,
                       lat, lon, location_source,
                       area, address_text, user_agent,
                       event_type, is_late, ot_minutes, working_minutes
                FROM login_events
                ORDER BY login_time DESC
            """).fetchall()
        ]

    return render_template("admin_logins.html", records=records)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

init_db()  # runs on every startup (gunicorn or direct)

if __name__ == "__main__":
    # For local dev only. Use a real WSGI server in production.
    app.run(debug=False)
