from datetime import datetime, timedelta
import io
import json
import random
import sqlite3
import os
import smtplib
import secrets
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from flask import send_file, session, redirect, url_for, request, flash
from werkzeug.security import generate_password_hash, check_password_hash
from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    session,
    send_file,
    jsonify,
)

app = Flask(__name__)
app.secret_key = "change-this-secret-key"

# Email / OTP configuration
OTP_SENDER_EMAIL    = "societysynced@gmail.com"
OTP_SENDER_PASSWORD = "tvqtykupebrbcfon"   # ← use Gmail App Password here
OTP_EXPIRY_MINUTES  = 10

# ============================================================================
# EMAIL SENDING FUNCTION (PREVIOUSLY MISSING)
# ============================================================================
def _send_otp_email(recipient_email: str, otp_code: str) -> tuple:
    """
    Send an OTP email using Gmail SMTP.
    
    Args:
        recipient_email: Email address to send OTP to
        otp_code: 6-digit OTP code
    
    Returns:
        (success: bool, error_message: str)
        - (True, "") on success
        - (False, error_msg) on failure
    """
    try:
        subject = "Your Color Vision Test OTP"
        
        # HTML email body
        html_body = f"""
        <html>
            <body style="font-family: Arial, sans-serif; background-color: #f5f5f5; padding: 20px;">
                <div style="background-color: white; padding: 30px; border-radius: 8px; max-width: 500px; margin: 0 auto;">
                    <h2 style="color: #1a1a2e;">Color Vision Test - Email Verification</h2>
                    <p style="font-size: 16px; color: #333;">Your one-time password is:</p>
                    <div style="background-color: #f0f0f0; padding: 15px; border-radius: 5px; text-align: center; margin: 20px 0;">
                        <p style="font-size: 36px; font-weight: bold; color: #3949ab; letter-spacing: 8px; margin: 0;">{otp_code}</p>
                    </div>
                    <p style="font-size: 14px; color: #666;">This code will expire in <strong>{OTP_EXPIRY_MINUTES} minutes</strong>.</p>
                    <p style="font-size: 12px; color: #999; margin-top: 20px;">
                        <strong>Security Note:</strong> Never share this code with anyone. Our support team will never ask for it.
                    </p>
                </div>
            </body>
        </html>
        """
        
        # Create email message
        message = MIMEMultipart("alternative")
        message["Subject"] = subject
        message["From"] = OTP_SENDER_EMAIL
        message["To"] = recipient_email
        
        # Attach HTML content
        html_part = MIMEText(html_body, "html")
        message.attach(html_part)
        
        # Connect to Gmail SMTP and send
        with smtplib.SMTP("smtp.gmail.com", 587) as server:
            server.starttls()  # Start TLS encryption
            server.login(OTP_SENDER_EMAIL, OTP_SENDER_PASSWORD)
            server.sendmail(OTP_SENDER_EMAIL, recipient_email, message.as_string())
        
        print(f"[SUCCESS] OTP email sent to {recipient_email}")
        return (True, "")
        
    except smtplib.SMTPAuthenticationError as e:
        error_msg = "Gmail authentication failed. Check your app password."
        print(f"[EMAIL ERROR] {error_msg} - {str(e)}")
        return (False, error_msg)
        
    except smtplib.SMTPException as e:
        error_msg = f"SMTP error while sending email: {str(e)}"
        print(f"[EMAIL ERROR] {error_msg}")
        return (False, error_msg)
        
    except Exception as e:
        error_msg = f"Failed to send email: {type(e).__name__}: {str(e)}"
        print(f"[EMAIL ERROR] {error_msg}")
        return (False, error_msg)


# Database
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "test_results.db")
def init_db():
    """Initialize SQLite database and create tables if they don't exist."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS test_results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            test_type TEXT NOT NULL,
            score INTEGER NOT NULL,
            total_questions INTEGER NOT NULL,
            diagnosis TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            answers_json TEXT,
            report_data TEXT
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            username TEXT UNIQUE NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            age INTEGER,
            gender TEXT,
            country TEXT,
            occupation TEXT,
            glasses TEXT,
            vision_issues TEXT,
            phone TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    # Safely add user_id column to test_results if it doesn't exist
    c.execute("PRAGMA table_info(test_results)")
    columns = [col[1] for col in c.fetchall()]
    if "user_id" not in columns:
        c.execute("ALTER TABLE test_results ADD COLUMN user_id INTEGER")

    conn.commit()
    conn.close()

def save_test_result(test_type: str, score: int, total: int, diagnosis: str, answers_json: str = None, report_data: dict = None) -> int:
    """Save a test result to the database. Returns the new row id."""
    init_db()
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    report_str = json.dumps(report_data) if report_data else None
    user_id = session.get("user_id")

    c.execute(
        "INSERT INTO test_results "
        "(test_type, score, total_questions, diagnosis, timestamp, answers_json, report_data, user_id) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (test_type, score, total, diagnosis, ts, answers_json, report_str, user_id),
    )
    row_id = c.lastrowid
    
    if not user_id:
        # Save this ID to the session so the user can claim it when they log in/sign up
        session["guest_test_id"] = row_id
    
    conn.commit()
    conn.close()
    return row_id

# Session helpers
def store_report(report: dict) -> None:
    """Store the latest report in the session so result.html can display it."""
    session["last_report"] = report

def get_all_test_results(user_id):
    """Fetch all test results from the database."""
    # If there is no user_id (user not logged in), return an empty list immediately
    if user_id is None:
        return []
    init_db()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    if user_id:
        c.execute(
            "SELECT id, test_type, score, total_questions, diagnosis, timestamp, answers_json, report_data "
            "FROM test_results WHERE user_id = ? ORDER BY id DESC",
            (user_id,),
        )
    else:
        c.execute(
            "SELECT id, test_type, score, total_questions, diagnosis, timestamp, answers_json, report_data "
            "FROM test_results ORDER BY id DESC"
        )
    rows = c.fetchall()
    conn.close()
    return [dict(row) for row in rows]


def get_test_result_by_id(result_id: int) -> dict | None:
    """Fetch a single test result by id."""
    init_db()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute(
        "SELECT id, test_type, score, total_questions, diagnosis, timestamp, answers_json, report_data "
        "FROM test_results WHERE id = ?",
        (result_id,),
    )
    row = c.fetchone()
    conn.close()
    return dict(row) if row else None

# Ishihara Test
# Plate types:
#   "vanishing"      – only normal vision sees the digit; CB sees nothing ("")
#   "transformation" – normal and CB see different digits
#   "hidden"         – only CB sees the digit; normal vision sees nothing ("")
#   "diagnostic"     – distinguishes Protan from Deutan (different CB answers)
ISHIHARA_PLATES = [
    # Plate 1 — orange digits on grey background.
    {
        "id": 1,
        "image": "plate1.png",
        "type": "vanishing",
        "normal_answer": "12",
        "protan_answer": "",
        "deutan_answer": "",
        "description": "12",
    },
    # Plate 2 — red/pink digits on yellow-green background.
    {
        "id": 2,
        "image": "plate2.png",
        "type": "transformation",
        "normal_answer": "8",
        "protan_answer": "3",
        "deutan_answer": "3",
        "description": "8",
    },
    # Plate 3 — red digits on yellow-green background.
    {
        "id": 3,
        "image": "plate3.png",
        "type": "transformation",
        "normal_answer": "29",
        "protan_answer": "70",
        "deutan_answer": "70",
        "description": "29",
    },
    # Plate 4 — green on orange/red. Normal: 5.
    {
        "id": 4,
        "image": "plate4.png",
        "type": "vanishing",
        "normal_answer": "5",
        "protan_answer": "2",
        "deutan_answer": "2",
        "description": "5",
    },
    # Plate 5 — green on red/orange.
    {
        "id": 5,
        "image": "plate5.png",
        "type": "transformation",
        "normal_answer": "3",
        "protan_answer": "5",
        "deutan_answer": "5",
        "description": "3",
    },
    # Plate 6 — green/yellow on red-orange.
    {
        "id": 6,
        "image": "plate6.png",
        "type": "transformation",
        "normal_answer": "15",
        "protan_answer": "17",
        "deutan_answer": "17",
        "description": "15",
    },
    # Plate 7 — green on orange/red.
    {
        "id": 7,
        "image": "plate7.png",
        "type": "transformation",
        "normal_answer": "74",
        "protan_answer": "21",
        "deutan_answer": "21",
        "description": "74",
    },
    # Plate 8 — orange digits on yellow-green background.
    {
        "id": 8,
        "image": "plate8.png",
        "type": "vanishing",
        "normal_answer": "6",
        "protan_answer": "",
        "deutan_answer": "",
        "description": "6",
    },
    # Plate 9 — orange digits on olive/grey background.
    {
        "id": 9,
        "image": "plate9.png",
        "type": "vanishing",
        "normal_answer": "45",
        "protan_answer": "",
        "deutan_answer": "",
        "description": "45",
    },
    # Plate 10 — mixed red-green field.
    {
        "id": 10,
        "image": "plate10.png",
        "type": "vanishing",
        "normal_answer": "5",
        "protan_answer": "",
        "deutan_answer": "",
        "description": "5",
    },
    # Plate 11 — green digit on red/yellow background.
    {
        "id": 11,
        "image": "plate11.png",
        "type": "vanishing",
        "normal_answer": "7",
        "protan_answer": "",
        "deutan_answer": "",
        "description": "7",
    },
    # Plate 12 — green digits on red/yellow background.
    {
        "id": 12,
        "image": "plate12.png",
        "type": "vanishing",
        "normal_answer": "16",
        "protan_answer": "",
        "deutan_answer": "",
        "description": "16",
    },
    # Plate 13 — green digits on red/yellow background.
    {
        "id": 13,
        "image": "plate13.png",
        "type": "vanishing",
        "normal_answer": "73",
        "protan_answer": "",
        "deutan_answer": "",
        "description": "73",
    },
    # Plate 14 — diagnostic: red vs purple digits on grey.
    {
        "id": 14,
        "image": "plate14.png",
        "type": "diagnostic",
        "normal_answer": "26",
        "protan_answer": "6",
        "deutan_answer": "2",
        "description": "26",
    },
    # Plate 15 — diagnostic: red vs purple digits on grey.
    {
        "id": 15,
        "image": "plate15.png",
        "type": "diagnostic",
        "normal_answer": "42",
        "protan_answer": "2",
        "deutan_answer": "4",
        "description": "42",
    },
]

# Ishihara diagnosis logic
def _score_plate(plate: dict, user_answer: str) -> dict:
    """
    Evaluate a single plate response and return per-type scoring points.

    Plate types:
        vanishing   – Normal sees the digit; colour-blind see nothing.
        transformation – Normal and colour-blind see different digits.
        hidden      – Only colour-blind see the digit; normal sees nothing.
        diagnostic  – Protan and deutan see different digits; normal sees both.

    Returns a dict:
        normal_point  – 1 if the answer matches normal vision
        protan_point  – 1 if the answer matches a protan response
        deutan_point  – 1 if the answer matches a deutan response
        cb_point      – 1 if the answer matches *any* colour-blind response
        result        – "normal" | "protan" | "deutan" | "colorblind" | "incorrect"
    """
    ua     = user_answer.strip().lower()
    normal = plate["normal_answer"].strip().lower()
    protan = (plate.get("protan_answer") or "").strip().lower()
    deutan = (plate.get("deutan_answer") or "").strip().lower()
    ptype  = plate["type"]
    result = "incorrect"
    normal_point = protan_point = deutan_point = 0
    # Helper: does the user claim to see nothing?
    sees_nothing = ua in ("", "nothing", "none", "0", "x", "-")
    if ptype == "vanishing":
        if ua == normal:
            result = "normal"
            normal_point = 1
        elif protan and ua == protan:
            result = "protan"
            protan_point = 1
        elif deutan and deutan != protan and ua == deutan:
            result = "deutan"
            deutan_point = 1
        elif sees_nothing:
            result = "colorblind"   # red-green deficiency confirmed

    elif ptype == "transformation":
        if ua == normal:
            result = "normal"
            normal_point = 1
        elif protan and ua == protan:
            result = "protan"
            protan_point = 1
        elif deutan and deutan != protan and ua == deutan:
            result = "deutan"
            deutan_point = 1
        elif protan and ua == protan:   # protan == deutan case
            result = "colorblind"

    elif ptype == "hidden":
        if sees_nothing:
            result = "normal"
            normal_point = 1
        elif protan and ua == protan:
            result = "protan"
            protan_point = 1
        elif deutan and ua == deutan:
            result = "deutan"
            deutan_point = 1

    elif ptype == "diagnostic":
        if ua == normal:
            result = "normal"
            normal_point = 1
        elif protan and ua == protan:
            result = "protan"
            protan_point = 1
        elif deutan and ua == deutan:
            result = "deutan"
            deutan_point = 1

    cb_point = 1 if result in ("protan", "deutan", "colorblind") else 0

    return {
        "normal_point": normal_point,
        "protan_point": protan_point,
        "deutan_point": deutan_point,
        "cb_point":     cb_point,
        "result":       result,
    }

def build_ishihara_diagnosis(normal_score: int, protan_score: int,
                            deutan_score: int, total: int,
                            scored_answers: list = None) -> str:
    """
    Produce a clinically-graded diagnosis from aggregated plate scores.

    The Ishihara series primarily screens for RED-GREEN deficiencies
    (Protanopia, Protanomaly, Deuteranopia, Deuteranomaly).  The D15
    test covers blue-yellow (Tritanopia/Tritanomaly) separately.

    Severity thresholds (based on standard 38-plate Ishihara guidelines
    scaled to the number of plates actually shown):

        normal_pct >= 0.90  →  Normal Color Vision
        normal_pct >= 0.70  →  Mild Color Vision Deficiency (borderline)
        normal_pct <  0.70  →  Significant deficiency; classify by type:

            Diagnostic plates give the clearest protan vs deutan split.
            If no diagnostic plates were shown, transformation plates are used.

            protan_score >> deutan_score  →  Protanopia / Protanomaly
            deutan_score >> protan_score  →  Deuteranopia / Deuteranomaly
            protan ≈ deutan               →  Unclassified Red-Green Deficiency

        cb_dominated (many vanishing misses, low normal, low protan/deutan)
            → Possible Red-Green Deficiency (type unclear)

    Note: The Ishihara test cannot detect Tritanopia (blue-yellow); that is
    assessed separately via the D15 test.
    """
    if total <= 0:
        return "Insufficient data to determine result."

    normal_pct = normal_score / total
    cb_score   = (scored_answers and
                    sum(1 for a in scored_answers if a.get("result") == "colorblind")) or 0
    #Normal vision
    if normal_pct >= 0.90:
        return "Normal Color Vision"
    #Borderline / mild
    if normal_pct >= 0.70:
        if protan_score > 0 and protan_score > deutan_score:
            return "Mild Protanomaly (Weak Red Sensitivity)"
        if deutan_score > 0 and deutan_score > protan_score:
            return "Mild Deuteranomaly (Weak Green Sensitivity)"
        return "Mild Color Vision Deficiency (type unclear)"

    #Significant deficiency – classify sub-type
    protan_dominant = protan_score > deutan_score
    deutan_dominant = deutan_score > protan_score

    # Severity within each type: ratio of CB-type score to total questions.
    protan_pct = protan_score / total
    deutan_pct = deutan_score / total

    if protan_dominant:
        if protan_pct >= 0.20:
            return "Protanopia (Severe Red-Green Deficiency — Red blind)"
        return "Protanomaly (Moderate Red-Green Deficiency — Red weak)"

    if deutan_dominant:
        if deutan_pct >= 0.20:
            return "Deuteranopia (Severe Red-Green Deficiency — Green blind)"
        return "Deuteranomaly (Moderate Red-Green Deficiency — Green weak)"

    # Neither protan nor deutan signals dominate but normal score is low →
    # generic red-green deficiency (common when mostly vanishing plates shown).
    if cb_score > 0 or (normal_pct < 0.50):
        return "Red-Green Color Vision Deficiency (type unclear)"

    return "Possible Color Vision Deficiency (borderline result)"

# Farnsworth D-15 — cap definitions & scoring
# Correct arrangement order: 0 → 1 → 2 → … → 15.

D15_CAPS = [
    {"id":  0, "label": "Cap 0",  "hex": "#9351d6"},  # 270° violet-purple   — reference (fixed)
    {"id":  1, "label": "Cap 1",  "hex": "#c44dd4"},  # 293° magenta-purple
    {"id":  2, "label": "Cap 2",  "hex": "#d64daa"},  # 315° hot pink
    {"id":  3, "label": "Cap 3",  "hex": "#d64d72"},  # 338° rose-red
    {"id":  4, "label": "Cap 4",  "hex": "#d64d4d"},  # 0°   pure red
    {"id":  5, "label": "Cap 5",  "hex": "#d6804d"},  # 22°  orange
    {"id":  6, "label": "Cap 6",  "hex": "#d6b94d"},  # 45°  amber-yellow
    {"id":  7, "label": "Cap 7",  "hex": "#b8d64d"},  # 68°  yellow-green
    {"id":  8, "label": "Cap 8",  "hex": "#7ad64d"},  # 90°  lime green
    {"id":  9, "label": "Cap 9",  "hex": "#4dd66b"},  # 112° green
    {"id": 10, "label": "Cap 10", "hex": "#4dd6a6"},  # 135° green-teal
    {"id": 11, "label": "Cap 11", "hex": "#4dd6d6"},  # 158° cyan
    {"id": 12, "label": "Cap 12", "hex": "#4da6d6"},  # 180° sky blue
    {"id": 13, "label": "Cap 13", "hex": "#4d72d6"},  # 202° cobalt blue
    {"id": 14, "label": "Cap 14", "hex": "#6b4dd6"},  # 225° blue-violet
    {"id": 15, "label": "Cap 15", "hex": "#5e4dd6"},  # 248° indigo          — end cap (fixed)
]
# Correct sequence: 0,1,2,…,15
CORRECT_D15_ORDER = list(range(16))

# Confusion-axis vectors (Vingrys & King-Smith 1988)

# Protan  axis: roughly caps 1–2  ↔  caps 9–10  (blue-purple ↔ olive-yellow)
# Deutan  axis: roughly caps 3–4  ↔  caps 11–12 (cyan-blue   ↔ orange-red)
# Tritan  axis: roughly caps 5–6  ↔  caps 13–14 (green-teal  ↔ red-pink)
D15_CONFUSION_AXES = {
    "Protan":  (frozenset({1, 2}),  frozenset({9,  10})),
    "Deutan":  (frozenset({3, 4}),  frozenset({11, 12})),
    "Tritan":  (frozenset({5, 6}),  frozenset({13, 14})),
}

def _step_error(a: int, b: int) -> int:
    """
    Error score for a single connecting step from cap a → cap b.

    The D-15 error score is defined as the absolute difference between
    cap ids minus 1 (adjacent caps score 0, one step away scores 1, etc.).
    Maximum possible error per step = 14 (jumping all the way across).

    Reference: Bowman (1982), Vingrys & King-Smith (1988).
    """
    return max(0, abs(b - a) - 1)

def _count_crossings(user_order: list) -> dict:
    """
    Count how many of the user's connecting lines cross each confusion axis.

    A crossing occurs when a user step (u_a → u_b) spans across the
    midpoint of a named confusion axis (i.e. one pole is on each side
    of the axis boundary in hue space).

    Returns a dict: axis_name → crossing_count.
    """
    crossings = {axis: 0 for axis in D15_CONFUSION_AXES}

    for i in range(len(user_order) - 1):
        a = user_order[i]
        b = user_order[i + 1]
        step_set = frozenset({a, b})

        for axis_name, (pole1, pole2) in D15_CONFUSION_AXES.items():
            def near(cap_id, pole):
                return any(abs(cap_id - p) <= 2 for p in pole)

            if (near(a, pole1) and near(b, pole2)) or \
                (near(a, pole2) and near(b, pole1)):
                crossings[axis_name] += 1
    
    return crossings

def score_d15(user_order: list) -> dict:
    """
    Score a Farnsworth D-15 arrangement.

    Parameters
    ----------
    user_order : list of int
        Full 16-cap sequence as submitted by the user, starting with cap 0
        (reference) and ending with cap 15 (end cap).

    Returns
    -------
    dict with keys:
        total_error_score  – sum of step errors (0 = perfect)
        crossings          – total confusion-axis crossing count
        confusion_axis     – dominant axis name or None
        axis_crossings     – per-axis crossing dict
        sequence           – per-step detail list for the result table
        full_order         – user_order (for the polar diagram)
    """
    cap_map = {c["id"]: c for c in D15_CAPS}

    total_error  = 0
    sequence     = []

    for pos, cap_id in enumerate(user_order):
        step_error = 0
        if pos > 0:
            step_error   = _step_error(user_order[pos - 1], cap_id)
            total_error += step_error

        sequence.append({
            "position":   pos,
            "cap_id":     cap_id,
            "hex":        cap_map[cap_id]["hex"],
            "step_error": step_error,
        })

    axis_crossings = _count_crossings(user_order)
    total_crossings = sum(axis_crossings.values())

    # Dominant confusion axis = whichever axis has the most crossings
    dominant_axis = None
    if total_crossings > 0:
        dominant_axis = max(axis_crossings, key=axis_crossings.get)
        if axis_crossings[dominant_axis] == 0:
            dominant_axis = None

    return {
        "total_error_score": total_error,
        "crossings":         total_crossings,
        "confusion_axis":    dominant_axis,
        "axis_crossings":    axis_crossings,
        "sequence":          sequence,
        "full_order":        user_order,
    }

def diagnose_d15(summary: dict) -> str:
    """
    Produce a diagnosis from the D-15 scoring summary.

    Clinical thresholds (Bowman 1982 / Vingrys & King-Smith 1988):
        total_error_score == 0 and crossings == 0  →  Normal Color Vision
        total_error_score <= 4 and crossings == 0  →  Near Normal (minor errors)
        crossings >= 2 on a single axis             →  Significant deficiency
        crossings == 1                              →  Borderline / mild anomaly
        dominant axis                               →  names the CVD type

    The D-15 can detect Protan, Deutan, AND Tritan axes — it is the only
    common clinical test that covers all three red-green and blue-yellow types.
    """
    error  = summary.get("total_error_score", 0)
    cross  = summary.get("crossings", 0)
    axis   = summary.get("confusion_axis")
    ac     = summary.get("axis_crossings", {})

    #Normal
    if error == 0 and cross == 0:
        return "Normal Color Vision"

    if error <= 4 and cross == 0:
        return "Near Normal Color Vision (minor arrangement errors)"

    #Single crossing — borderline
    if cross == 1:
        if axis == "Protan":
            return "Borderline — Possible Mild Protanomaly (Weak Red Sensitivity)"
        if axis == "Deutan":
            return "Borderline — Possible Mild Deuteranomaly (Weak Green Sensitivity)"
        if axis == "Tritan":
            return "Borderline — Possible Mild Tritanomaly (Weak Blue-Yellow Sensitivity)"
        return "Borderline Color Vision — single confusion-axis crossing detected"

    #Multiple crossings — significant deficiency
    protan_cross = ac.get("Protan", 0)
    deutan_cross = ac.get("Deutan", 0)
    tritan_cross = ac.get("Tritan", 0)

    # Severe = dominant axis has 3+ crossings
    severe_thresh = 3

    if axis == "Protan":
        if protan_cross >= severe_thresh:
            return "Protanopia (Severe Red-Green Deficiency — Red Blind)"
        return "Protanomaly (Moderate Red-Green Deficiency — Red Weak)"

    if axis == "Deutan":
        if deutan_cross >= severe_thresh:
            return "Deuteranopia (Severe Red-Green Deficiency — Green Blind)"
        return "Deuteranomaly (Moderate Red-Green Deficiency — Green Weak)"

    if axis == "Tritan":
        if tritan_cross >= severe_thresh:
            return "Tritanopia (Severe Blue-Yellow Deficiency — Blue Blind)"
        return "Tritanomaly (Moderate Blue-Yellow Deficiency — Blue Weak)"

    # Mixed — errors spread across multiple axes
    if cross >= 4:
        return "General Color Vision Deficiency"

    return "Mild Color Vision Anomaly — axis unclear; clinical testing recommended"

# ---- Mosaic Color Test configuration ----
#
# The Mosaic Test presents a 6×6 grid of 36 coloured tiles spread across
# 4 hidden colour groups.  The user taps tiles to assign them to labelled
# groups.  Their grouping errors are scored against three colour-confusion
# axes (Protan, Deutan, Tritan) to detect and classify colour vision
# deficiency — consistent with the 1929 Mosaic Test paradigm adapted for CVD.
#
# Each plate dict is sent to the browser as JSON and contains:
#   id            – plate number
#   type          – "rg" (red-green), "by" (blue-yellow), "tritan", "control"
#   tiles         – list of 36 {color, true_group} dicts (shuffled before send)
#   group_labels  – 4 display names ("Group A" … "Group D")
#   group_swatches – 4 representative hex values for the group selector buttons
#
# Tile colours within each group vary in lightness/saturation so that
# normal observers group them easily by hue, while colour-deficient observers
# conflate specific pairs of groups along their confusion axis.
#
# Confusion pairs:
#   Protan  — Red ↔ Green  (groups 0 ↔ 1 on rg plates)
#   Deutan  — Red ↔ Green  (groups 0 ↔ 1 on rg plates, different primaries)
#   Tritan  — Blue ↔ Yellow (groups 0 ↔ 1 on by plates)
#
# Each plate is defined as a list of (hue_hex, lightness_variants) tuples;
# the builder function expands them to 9 tiles per group.

def _build_tiles(group_colors):
    """
    group_colors: list of 4 lists, each containing 9 hex strings.
    Returns a flat list of 36 {color, true_group} dicts.
    """
    tiles = []
    for gi, colors in enumerate(group_colors):
        for hex_color in colors:
            tiles.append({"color": hex_color, "true_group": gi})
    return tiles


# Red-Green plate — Protan/Deutan confusion axis
# Groups 0 (reds) and 1 (greens) are confused by red-green deficients.
# Groups 2 (blues) and 3 (purples) are control groups.
_RG_PLATE_GROUPS = [
    # Group 0: Reds / oranges
    ["#c0392b","#e74c3c","#e55039","#d32f2f","#f44336",
     "#b71c1c","#ef9a9a","#ef5350","#c62828"],
    # Group 1: Greens
    ["#27ae60","#2ecc71","#43a047","#388e3c","#66bb6a",
     "#1b5e20","#a5d6a7","#4caf50","#2e7d32"],
    # Group 2: Blues (control — easy for everyone)
    ["#1565c0","#1976d2","#1e88e5","#2196f3","#42a5f5",
     "#0d47a1","#90caf9","#64b5f6","#1565c0"],
    # Group 3: Purples (control)
    ["#6a1b9a","#7b1fa2","#8e24aa","#9c27b0","#ab47bc",
     "#4a148c","#ce93d8","#ba68c8","#7b1fa2"],
]

# Blue-Yellow plate — Tritan confusion axis
# Groups 0 (blues) and 1 (yellows) are confused by tritan deficients.
# Groups 2 (reds) and 3 (greens) are control groups.
_BY_PLATE_GROUPS = [
    # Group 0: Blues
    ["#1565c0","#1976d2","#1e88e5","#2196f3","#42a5f5",
     "#0d47a1","#90caf9","#64b5f6","#1565c0"],
    # Group 1: Yellows / ambers
    ["#f9a825","#f57f17","#ffb300","#ffa000","#ff8f00",
     "#e65100","#ffe082","#ffca28","#ff8f00"],
    # Group 2: Reds (control)
    ["#c0392b","#e74c3c","#e55039","#d32f2f","#f44336",
     "#b71c1c","#ef9a9a","#ef5350","#c62828"],
    # Group 3: Greens (control)
    ["#27ae60","#2ecc71","#43a047","#388e3c","#66bb6a",
     "#1b5e20","#a5d6a7","#4caf50","#2e7d32"],
]

# Control plate — four clearly distinct hue groups; EVERYONE should group
# these correctly. Used to verify the user understands the task.
_CONTROL_PLATE_GROUPS = [
    # Group 0: Reds
    ["#c0392b","#e74c3c","#e55039","#d32f2f","#f44336",
     "#b71c1c","#ef9a9a","#ef5350","#c62828"],
    # Group 1: Blues
    ["#1565c0","#1976d2","#1e88e5","#2196f3","#42a5f5",
     "#0d47a1","#90caf9","#64b5f6","#1565c0"],
    # Group 2: Greens
    ["#27ae60","#2ecc71","#43a047","#388e3c","#66bb6a",
     "#1b5e20","#a5d6a7","#4caf50","#2e7d32"],
    # Group 3: Yellows
    ["#f9a825","#f57f17","#ffb300","#ffa000","#ff8f00",
     "#e65100","#ffe082","#ffca28","#ff8f00"],
]

MOSAIC_PLATES = [
    {
        "id": 1,
        "type": "control",
        "tiles": _build_tiles(_CONTROL_PLATE_GROUPS),
        "group_labels":   ["Group A", "Group B", "Group C", "Group D"],
        "group_swatches": ["#e74c3c", "#2196f3", "#2ecc71", "#ffb300"],
    },
    {
        "id": 2,
        "type": "rg",
        "tiles": _build_tiles(_RG_PLATE_GROUPS),
        "group_labels":   ["Group A", "Group B", "Group C", "Group D"],
        "group_swatches": ["#e74c3c", "#2ecc71", "#2196f3", "#9c27b0"],
    },
    {
        "id": 3,
        "type": "by",
        "tiles": _build_tiles(_BY_PLATE_GROUPS),
        "group_labels":   ["Group A", "Group B", "Group C", "Group D"],
        "group_swatches": ["#2196f3", "#ffb300", "#e74c3c", "#2ecc71"],
    },
]


# ---------------------------------------------------------------------------
# Mosaic scoring helpers
# ---------------------------------------------------------------------------

def _score_mosaic_plate(plate: dict, tile_records: list) -> dict:
    """
    Score one plate.

    For each tile that was assigned, check whether it went to the correct
    true_group (correct) or to a different group (error).

    Confusion errors:
      rg plate:  true_group 0 assigned to group 1, or vice versa  → RG error
      by plate:  true_group 0 assigned to group 1, or vice versa  → Tritan error

    Returns:
      correct          – count of tiles assigned to their true group
      total_assigned   – tiles the user assigned (possibly < 36)
      rg_errors        – red-green confusion count
      tritan_errors    – blue-yellow confusion count
      unassigned       – tiles left ungrouped (-1)
    """
    correct = 0
    rg_errors = 0
    tritan_errors = 0
    unassigned = 0
    total_assigned = 0

    for rec in tile_records:
        tg = rec.get("true_group", -1)
        ag = rec.get("assigned_group", -1)

        if ag == -1:
            unassigned += 1
            continue

        total_assigned += 1

        if ag == tg:
            correct += 1
        else:
            ptype = plate.get("type", "control")
            # RG confusion: groups 0 and 1 swapped on an rg plate
            if ptype == "rg" and {tg, ag} == {0, 1}:
                rg_errors += 1
            # Tritan confusion: groups 0 and 1 swapped on a by plate
            elif ptype == "by" and {tg, ag} == {0, 1}:
                tritan_errors += 1

    return {
        "correct": correct,
        "total_assigned": total_assigned,
        "rg_errors": rg_errors,
        "tritan_errors": tritan_errors,
        "unassigned": unassigned,
    }


def diagnose_mosaic(summary: dict) -> str:
    """
    Produce a diagnosis string from aggregated mosaic scores.
    """
    ctrl_acc = summary.get("control_accuracy", 1.0)

    # If the user couldn't group even the control plate, the test is inconclusive
    if ctrl_acc < 0.5:
        return "Test Inconclusive (user may not have understood the task)"

    rg_err     = summary.get("total_rg_errors", 0)
    trit_err   = summary.get("total_tritan_errors", 0)
    total_tiles = summary.get("total_tiles", 1)

    rg_rate   = rg_err   / total_tiles
    trit_rate = trit_err / total_tiles

    # Both axes significant
    if rg_rate >= 0.20 and trit_rate >= 0.20:
        return "General Color Vision Deficiency (multiple axes affected)"

    # Red-green dominant
    if rg_rate >= 0.25:
        return "Significant Red-Green Color Vision Deficiency (Protan or Deutan)"
    if rg_rate >= 0.12:
        return "Mild Red-Green Color Vision Deficiency"

    # Tritan dominant
    if trit_rate >= 0.25:
        return "Significant Blue-Yellow Color Vision Deficiency (Tritanopia/Tritanomaly)"
    if trit_rate >= 0.12:
        return "Mild Blue-Yellow Color Vision Deficiency"

    # All good
    return "Normal Color Vision"


@app.route("/mosaic", methods=["GET"])
def mosaic():
    import copy
    plates = copy.deepcopy(MOSAIC_PLATES)
    for plate in plates:
        random.shuffle(plate["tiles"])   # randomise tile positions each session
    random.shuffle(plates)               # randomise plate order
    return render_template(
        "mosaic.html",
        questions_json=json.dumps(plates),
        total_questions=len(plates),
    )


@app.route("/submit-mosaic", methods=["POST"])
def submit_mosaic():
    raw = request.form.get("mosaicAnswersJson", "[]")
    try:
        rounds = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        rounds = []

    # Build a lookup from plate id → plate definition
    plate_lookup = {p["id"]: p for p in MOSAIC_PLATES}

    details = []          # per-round breakdown shown in result.html & PDF
    total_rg_errors     = 0
    total_tritan_errors = 0
    total_correct       = 0
    total_tiles         = 0
    rg_correct          = 0
    rg_total            = 0
    by_correct          = 0
    by_total            = 0
    control_correct     = 0
    control_tiles       = 0

    for rnd in rounds:
        pid          = rnd.get("id")
        ptype        = rnd.get("type", "")
        plate        = plate_lookup.get(pid, {"type": ptype, "id": pid})
        tile_records = rnd.get("tiles", [])

        sc = _score_mosaic_plate(plate, tile_records)

        round_tiles   = sc["total_assigned"] + sc["unassigned"]
        total_correct       += sc["correct"]
        total_rg_errors     += sc["rg_errors"]
        total_tritan_errors += sc["tritan_errors"]
        total_tiles         += round_tiles

        # Accumulate per-axis totals for result.html compatibility
        if ptype == "rg":
            rg_correct += sc["correct"]
            rg_total   += round_tiles
        elif ptype == "by":
            by_correct += sc["correct"]
            by_total   += round_tiles
        elif ptype == "control":
            control_correct += sc["correct"]
            control_tiles   += round_tiles

        type_label = {
            "rg":      "Red-Green Plate",
            "by":      "Blue-Yellow Plate",
            "control": "Control Plate",
        }.get(ptype, ptype.title())

        details.append({
            "id":             pid,
            "type":           ptype,
            "label":          type_label,
            "correct":        sc["correct"],
            "total_assigned": sc["total_assigned"],
            "rg_errors":      sc["rg_errors"],
            "tritan_errors":  sc["tritan_errors"],
            "unassigned":     sc["unassigned"],
            # Fields used by result.html answer table
            "is_correct":     sc["correct"] >= (round_tiles * 0.75),
            "user_answer":    f"{sc['correct']} / {round_tiles} tiles correct",
            "correct_answer": "All tiles correctly grouped",
        })

    ctrl_acc = (control_correct / control_tiles) if control_tiles else 1.0

    # Summary dict — keys match BOTH the old digit-test template fields
    # (s.correct, s.total, s.rg_correct …) AND the new mosaic-specific fields.
    summary = {
        # New mosaic fields
        "total_tiles":           total_tiles,
        "total_correct":         total_correct,
        "total_rg_errors":       total_rg_errors,
        "total_tritan_errors":   total_tritan_errors,
        "control_accuracy":      round(ctrl_acc, 3),
        "rounds":                len(rounds),
        # Alias fields so result.html {# mosaic #} block renders without change
        "correct":               total_correct,
        "total":                 total_tiles,
        "rg_correct":            rg_correct,
        "rg_total":              rg_total,
        "by_correct":            by_correct,
        "by_total":              by_total,
    }

    diagnosis = diagnose_mosaic(summary)

    report = {
        "test_name": "Mosaic Color Test",
        "kind":      "mosaic",
        "details":   details,
        "summary":   summary,
        "diagnosis": diagnosis,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }

    store_report(report)
    save_test_result(
        test_type="mosaic",
        score=total_correct,
        total=total_tiles if total_tiles > 0 else 1,
        diagnosis=diagnosis,
        answers_json=json.dumps(details),
        report_data=report,
    )
    return redirect(url_for("result"))

@app.route("/send-otp", methods=["POST"])
def send_otp():
    """Generate a 6-digit OTP, store it in session, and email it."""
    data  = request.get_json(force=True)
    email = (data.get("email") or "").strip().lower()

    if not email or "@" not in email:
        return jsonify(ok=False, error="Invalid email address.")

    # Check if email is already registered
    init_db()
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT id FROM users WHERE email = ?", (email,))
    exists = c.fetchone()
    conn.close()
    if exists:
        return jsonify(ok=False, error="An account with this email already exists.")

    otp  = str(random.randint(100000, 999999))
    expiry = (datetime.now() + timedelta(minutes=OTP_EXPIRY_MINUTES)).isoformat()

    # Store in session (keyed by email so multiple tabs can't interfere)
    session["otp_data"] = {"email": email, "code": otp, "expiry": expiry}

    ok_flag, err_msg = _send_otp_email(email, otp)
    if ok_flag:
        return jsonify(ok=True)
    return jsonify(ok=False, error=err_msg or "Failed to send email. Please try again.")


@app.route("/verify-otp", methods=["POST"])
def verify_otp():
    """Validate the OTP and return a short-lived token the signup form uses."""
    data  = request.get_json(force=True)
    email = (data.get("email") or "").strip().lower()
    code  = (data.get("otp")   or "").strip()

    otp_data = session.get("otp_data")

    if not otp_data:
        return jsonify(ok=False, error="No verification request found. Please send the code first.")

    if otp_data.get("email") != email:
        return jsonify(ok=False, error="Email mismatch. Please start over.")

    if datetime.now() > datetime.fromisoformat(otp_data["expiry"]):
        session.pop("otp_data", None)
        return jsonify(ok=False, error="Code has expired. Please request a new one.")

    if otp_data["code"] != code:
        return jsonify(ok=False, error="Incorrect code. Please try again.")

    # OTP is valid — issue a single-use token so the signup POST can confirm
    token = secrets.token_hex(32)
    session["otp_verified"] = {"email": email, "token": token}
    session.pop("otp_data", None)
    return jsonify(ok=True, token=token)


@app.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "POST":
        name      = request.form.get("name",  "").strip()
        username = request.form.get("username", "").strip().lower()
        email     = request.form.get("email", "").strip().lower()
        password  = request.form.get("password",  "")
        password2 = request.form.get("password2", "")
        age       = request.form.get("age")
        gender    = request.form.get("gender")
        token     = request.form.get("otp_token", "")

        # Basic validation
        if not name or not email or not password:
            return render_template("signup.html", error="Name, email and password are required.")

        if len(password) < 8:
            return render_template("signup.html", error="Password must be at least 8 characters.")

        if password != password2:
            return render_template("signup.html", error="Passwords do not match.")

        # Verify OTP token
        verified = session.get("otp_verified")
        if not verified or verified.get("email") != email or verified.get("token") != token:
            return render_template("signup.html", error="Email not verified. Please complete OTP verification.")

        hashed = generate_password_hash(password)

        init_db()
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        try:
            c.execute(
                "INSERT INTO users (name, username, email, password, age, gender) VALUES (?, ?, ?, ?, ?, ?)",
                (name, username, email, hashed, age or None, gender or None),
            )
            conn.commit()
            session.pop("otp_verified", None)
            return redirect(url_for("login"))
        except sqlite3.IntegrityError as e:
            if "username" in str(e):
                return render_template("signup.html", error="Username already taken.")
            return render_template("signup.html", error="An account with this email already exists.")
        finally:
            conn.close()

    return render_template("signup.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        identity = request.form.get("login_identity", "").strip().lower()
        password = request.form.get("password", "")

        init_db()
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute("SELECT * FROM users WHERE email = ? OR username =?", (identity, identity))
        user_row = c.fetchone()
        
        if user_row and check_password_hash(user_row["password"], password):
            session["user_id"]   = user_row["id"]
            session["user_name"] = user_row["username"]
            
            if "guest_test_id" in session:
                guest_test_id = session.pop("guest_test_id")
                c.execute("UPDATE test_results SET user_id = ? WHERE id = ?", (user_row["id"], guest_test_id))
                conn.commit()
            
            conn.close() # Close connection AFTER adoption
            
            #PDF AUTO-DOWNLOAD LOGIC
            if "pending_download" in session:
                session["auto_download"] = session.pop("pending_download")
                return redirect(url_for("dashboard"))
        
            return redirect(url_for("dashboard"))
            
        conn.close()
        return render_template("login.html", error="Invalid email or password.")
        
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.pop("user_id",   None)
    session.pop("user_name", None)
    return redirect(url_for("index"))

# Forgot Password Routes

@app.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        password2 = request.form.get("password2", "")
        token = request.form.get("reset_token", "")

        if not email or not password:
            return render_template("forgot_password.html", error="Missing fields.")
        if len(password) < 8:
            return render_template("forgot_password.html", error="Password must be at least 8 characters.")
        if password != password2:
            return render_template("forgot_password.html", error="Passwords do not match.")
        
        # Verify the security token to prevent unauthorized password changes
        verified = session.get("reset_verified")
        if not verified or verified.get("email") != email or verified.get("token") != token:
            return render_template("forgot_password.html", error="Session expired or invalid token. Please try again.")

        # Hash the new password and update the database
        hashed = generate_password_hash(password)
        init_db()
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("UPDATE users SET password = ? WHERE email = ?", (hashed, email))
        conn.commit()
        conn.close()
        
        # Clean up session and redirect to login
        session.pop("reset_verified", None)
        flash("Password updated successfully! Please login with your new password.", "success")
        return redirect(url_for("login"))

    return render_template("forgot_password.html")


@app.route("/send-reset-otp", methods=["POST"])
def send_reset_otp():
    """Send an OTP only if the email exists in the database."""
    data = request.get_json(force=True)
    email = (data.get("email") or "").strip().lower()

    if not email or "@" not in email:
        return jsonify(ok=False, error="Invalid email address.")

    init_db()
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT id FROM users WHERE email = ?", (email,))
    exists = c.fetchone()
    conn.close()

    if not exists:
        return jsonify(ok=False, error="No account found with this email address.")

    otp = str(random.randint(100000, 999999))
    expiry = (datetime.now() + timedelta(minutes=OTP_EXPIRY_MINUTES)).isoformat()
    session["reset_otp_data"] = {"email": email, "code": otp, "expiry": expiry}

    ok_flag, err_msg = _send_otp_email(email, otp)
    if ok_flag:
        return jsonify(ok=True)
    return jsonify(ok=False, error=err_msg or "Failed to send email.")


@app.route("/verify-reset-otp", methods=["POST"])
def verify_reset_otp():
    """Validate the reset OTP."""
    data = request.get_json(force=True)
    email = (data.get("email") or "").strip().lower()
    code = (data.get("otp") or "").strip()

    otp_data = session.get("reset_otp_data")

    if not otp_data:
        return jsonify(ok=False, error="No request found. Send code first.")
    if otp_data.get("email") != email:
        return jsonify(ok=False, error="Email mismatch.")
    if datetime.now() > datetime.fromisoformat(otp_data["expiry"]):
        session.pop("reset_otp_data", None)
        return jsonify(ok=False, error="Code expired. Please request a new one.")
    if otp_data["code"] != code:
        return jsonify(ok=False, error="Incorrect code.")

    # Issue a secure token for the password reset form submission
    token = secrets.token_hex(32)
    session["reset_verified"] = {"email": email, "token": token}
    session.pop("reset_otp_data", None)
    return jsonify(ok=True, token=token)

# Main pages
@app.route("/")

def index():
    return render_template("index.html")


@app.route("/dashboard")
def dashboard():
    user_id = session.get("user_id")
    init_db()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    user_history = []
    global_stats = None

    auto_download = session.pop("auto_download", None)

    if user_id:
        # Fetch logged-in user's personal history
        c.execute(
            "SELECT id, test_type, score, total_questions, diagnosis, timestamp "
            "FROM test_results WHERE user_id = ? ORDER BY id DESC LIMIT 5",
            (user_id,),
        )
        user_history = [dict(row) for row in c.fetchall()]
    else:
        # Fetch global statistics for guest users
        c.execute("SELECT COUNT(*) FROM test_results")
        total_tests = c.fetchone()[0]
        
        c.execute("SELECT diagnosis, COUNT(*) as count FROM test_results GROUP BY diagnosis")
        stats_rows = c.fetchall()
        
        # Dictionary to hold merged counts
        merged_stats = {}
        for row in stats_rows:
            raw_diag = row['diagnosis'] if row['diagnosis'] else "Normal Color Vision"
            clean_diag = raw_diag.replace("blind", "Blind").replace("weak", "Weak").strip()
            if clean_diag in merged_stats:
                merged_stats[clean_diag] += row['count']
            else:
                merged_stats[clean_diag] = row['count']
                
        global_stats = {
            "total": total_tests,
            "labels": list(merged_stats.keys()),
            "data": list(merged_stats.values())
        }
    
    conn.close()
    
    return render_template("dashboard.html", 
                           user_history=user_history, 
                           global_stats=global_stats,
                           auto_download=auto_download)

@app.route("/about")
def about():
    return render_template("about.html")


@app.route("/simulation")
def simulation():
    return render_template("simulation.html")


@app.route("/reports")
def reports():
    user_id = session.get("user_id")
    
    # If no one is logged in, 'tests' will be an empty list []
    tests = get_all_test_results(user_id)
    
    # If user is a guest (not logged in), we can force counts to 0
    if not user_id:
        return render_template(
            "reports.html",
            tests=[],
            total_count=0,
            ishihara_count=0,
            d15_count=0,
            mosaic_count=0,
        )

    # Standard logic for logged-in users...
    ishihara_count = sum(1 for t in tests if t.get("test_type") == "ishihara")
    d15_count   = sum(1 for t in tests if t.get("test_type") == "d15")
    mosaic_count = sum(1 for t in tests if t.get("test_type") == "mosaic")
    tests_safe = [
        {
            "id":              t["id"],
            "test_type":       t["test_type"],
            "score":           t["score"],
            "total_questions": t["total_questions"],
            "diagnosis":       t["diagnosis"],
            "timestamp":       t["timestamp"],
        }
        for t in tests
    ]
    
    return render_template(
        "reports.html",
        tests=tests_safe,
        total_count=len(tests_safe),
        ishihara_count=ishihara_count,
        d15_count=d15_count,
        mosaic_count=mosaic_count,
    )

# Ishihara test
@app.route("/test")
def test():
    """
    Select 10 random plates from the full 15-plate bank on every visit.

    Selection strategy (ensures diagnostic quality):
        1. Always include BOTH diagnostic plates (ids 14 & 15).
        2. Always include at least 2 transformation plates for protan/deutan evidence.
        3. Fill remaining slots randomly from vanishing + leftover transformation.
        4. Shuffle the final 10 before sending so question order varies each run.
    """
    TARGET = 10

    diagnostic_plates    = [p for p in ISHIHARA_PLATES if p["type"] == "diagnostic"]
    transformation_plates = [p for p in ISHIHARA_PLATES if p["type"] == "transformation"]
    vanishing_plates     = [p for p in ISHIHARA_PLATES if p["type"] == "vanishing"]

    # Fixed: all diagnostic plates
    selected = list(diagnostic_plates)

    # Guarantee at least 2 transformation plates
    min_transform = 2
    transform_pick = random.sample(transformation_plates,
                                    min(min_transform, len(transformation_plates)))
    selected.extend(transform_pick)

    # Fill remaining slots from unused transformation + vanishing plates
    remaining_pool = (
        [p for p in transformation_plates if p not in transform_pick] + vanishing_plates
    )
    remaining_needed = TARGET - len(selected)
    if remaining_needed > 0:
        selected.extend(random.sample(remaining_pool,
                                        min(remaining_needed, len(remaining_pool))))

    random.shuffle(selected)

    return render_template(
        "test.html",
        plates=selected,
        plates_json=json.dumps(selected),
        total_questions=len(selected),
    )

@app.route("/ishihara-submit", methods=["POST"])
def ishihara_submit():
    """
    Receive per-question answers from the frontend, score each plate
    server-side using _score_plate(), then build a full diagnosis.
    """
    # The frontend now sends answersJson as the primary source of truth.
    # normalScore / protanScore / deutanScore are kept for backward compat.
    answers_list = []
    try:
        raw = request.form.get("answersJson", "[]")
        answers_list = json.loads(raw) if raw else []
    except (json.JSONDecodeError, TypeError):
        pass

    # Build a quick lookup: plate_id → plate definition
    plate_map = {p["id"]: p for p in ISHIHARA_PLATES}

    normal_score = protan_score = deutan_score = 0
    scored_answers = []

    for entry in answers_list:
        plate_id    = entry.get("plateId")
        user_answer = str(entry.get("userAnswer", "")).strip()
        plate       = plate_map.get(plate_id)

        if plate is None:
            # Plate id not found — skip
            scored_answers.append({**entry, "result": "unknown",
                                    "correctAnswer": "?"})
            continue

        pts = _score_plate(plate, user_answer)
        normal_score += pts["normal_point"]
        protan_score += pts["protan_point"]
        deutan_score += pts["deutan_point"]

        scored_answers.append({
            "plateId":      plate_id,
            "question":     plate.get("description", f"Plate {plate_id}"),
            "userAnswer":   user_answer,
            "correctAnswer": plate["normal_answer"] or "(nothing)",
            "result":       pts["result"],
        })

    total_questions = len(scored_answers) or 10

    # Fall back to frontend-tallied scores if no per-answer data arrived
    if not answers_list:
        try:
            normal_score = int(request.form.get("normalScore", "0"))
            protan_score = int(request.form.get("protanScore", "0"))
            deutan_score = int(request.form.get("deutanScore", "0"))
            total_questions = int(request.form.get("totalQuestions", "10"))
        except ValueError:
            pass

    diagnosis  = build_ishihara_diagnosis(
        normal_score, protan_score, deutan_score, total_questions, scored_answers
    )
    percentage = round((normal_score / total_questions) * 100) if total_questions else 0

    report = {
        "test_name": "Ishihara Color Vision Test",
        "kind":      "ishihara",
        "details": {
            "normal_score":     normal_score,
            "protan_score":     protan_score,
            "deutan_score":     deutan_score,
            "total_questions":  total_questions,
            "percentage":       percentage,
            "correct_count":    normal_score,
            "answers":          scored_answers,
        },
        "summary": {
            "correct": normal_score,
            "total":   total_questions,
        },
        "diagnosis": diagnosis,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }

    store_report(report)
    save_test_result(
        test_type="ishihara",
        score=normal_score,
        total=total_questions,
        diagnosis=diagnosis,
        answers_json=json.dumps(scored_answers),
        report_data=report,
    )
    return redirect(url_for("result"))

# Farnsworth D-15 test routes
@app.route("/d15", methods=["GET"])
def d15():
    """Render the Farnsworth D-15 drag-and-drop arrangement test."""
    return render_template("d15.html")


@app.route("/submit-d15", methods=["POST"])
def submit_d15():
    """
    Receive the user's cap arrangement from d15.html, score it using
    the D-15 error-score and confusion-axis crossing algorithm, then
    build a full report and redirect to the result page.
    """
    raw = request.form.get("disc_order", "[]")
    try:
        user_order = json.loads(raw)
        # Validate: must be a list of 16 integers covering ids 0–15
        if not isinstance(user_order, list) or len(user_order) != 16:
            raise ValueError("Invalid order length")
        user_order = [int(x) for x in user_order]
    except (json.JSONDecodeError, ValueError, TypeError):
        # Fallback to correct order if submission is malformed
        user_order = CORRECT_D15_ORDER[:]

    summary   = score_d15(user_order)
    diagnosis = diagnose_d15(summary)

    report = {
        "test_name": "Farnsworth D-15 Color Vision Test",
        "kind":      "d15",
        "details":   summary,          # full_order, sequence, axis_crossings …
        "summary":   summary,          # result.html reads from both keys
        "diagnosis": diagnosis,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }

    store_report(report)
    save_test_result(
        test_type="d15",
        score=max(0, 100 - summary["total_error_score"]),  # normalised score
        total=100,
        diagnosis=diagnosis,
        answers_json=json.dumps(summary["sequence"]),
        report_data=report,
    )
    return redirect(url_for("result"))

# Result & report views
@app.route("/result")
def result():
    report = session.get("last_report")
    if not report:
        return redirect(url_for("index"))
    return render_template("result.html", report=report, from_history=False, report_id=None)


@app.route("/report/<int:report_id>")
def report_detail(report_id):
    """View full report for a specific test result."""
    row = get_test_result_by_id(report_id)
    if not row:
        return redirect(url_for("reports"))

    report_data = None
    if row.get("report_data"):
        try:
            report_data = json.loads(row["report_data"])
        except (json.JSONDecodeError, TypeError):
            pass

    if not report_data:
        kind = row["test_type"]
        report_data = {
            "test_name": f"{row['test_type'].title()} Test",
            "kind":      kind,
            "diagnosis": row["diagnosis"],
            "timestamp": row["timestamp"],
        }

        if kind == "d15":
            # Rebuild summary from answers_json (which stores the sequence list)
            sequence = []
            full_order = list(range(16))  # fallback: correct order
            if row.get("answers_json"):
                try:
                    sequence = json.loads(row["answers_json"])
                    full_order = [item["cap_id"] for item in sequence]
                except (json.JSONDecodeError, TypeError, KeyError):
                    pass

            # Re-score from the stored sequence so all fields exist
            rebuilt_summary = score_d15(full_order)
            report_data["summary"] = rebuilt_summary
            report_data["details"] = rebuilt_summary

        elif kind == "mosaic":
            details_list = []
            if row.get("answers_json"):
                try:
                    details_list = json.loads(row["answers_json"])
                except (json.JSONDecodeError, TypeError):
                    pass
            rg_rounds   = [a for a in details_list if a.get("type") == "rg"]
            by_rounds   = [a for a in details_list if a.get("type") == "by"]
            rg_total    = sum(a.get("total_assigned", 0) + a.get("unassigned", 0) for a in rg_rounds) or len(rg_rounds)
            by_total    = sum(a.get("total_assigned", 0) + a.get("unassigned", 0) for a in by_rounds) or len(by_rounds)
            rg_correct  = sum(a.get("correct", 0) for a in rg_rounds)
            by_correct  = sum(a.get("correct", 0) for a in by_rounds)
            total_correct = sum(a.get("correct", 0) for a in details_list)
            total_tiles   = sum(
                a.get("total_assigned", 0) + a.get("unassigned", 0)
                for a in details_list
            ) or row["total_questions"]
            summary = {
                "correct":             total_correct,
                "total":               total_tiles,
                "rg_correct":          rg_correct,
                "rg_total":            rg_total,
                "by_correct":          by_correct,
                "by_total":            by_total,
                "total_correct":       total_correct,
                "total_tiles":         total_tiles,
                "total_rg_errors":     sum(a.get("rg_errors", 0) for a in details_list),
                "total_tritan_errors": sum(a.get("tritan_errors", 0) for a in details_list),
                "control_accuracy":    1.0,
                "rounds":              len(details_list),
            }
            report_data["summary"] = summary
            report_data["details"] = details_list

        else:
            # Ishihara fallback
            answers = []
            if row.get("answers_json"):
                try:
                    answers = json.loads(row["answers_json"])
                except (json.JSONDecodeError, TypeError):
                    pass
            report_data["details"] = {
                "normal_score":    row["score"],
                "total_questions": row["total_questions"],
                "percentage":      round(
                    (row["score"] / row["total_questions"]) * 100
                ) if row["total_questions"] else 0,
                "answers": answers,
            }
            report_data["summary"] = {"correct": row["score"], "total": row["total_questions"]}

    return render_template(
        "result.html", report=report_data, from_history=True, report_id=report_id
    )

# PDF download routes
@app.route("/download-ishihara-report")
def download_ishihara_report():
    # 1. Enforce login and remember the requested download URL
    if not session.get("user_id"):
        session["pending_download"] = request.url
        return redirect(url_for("login"))

    report_id = request.args.get("id", type=int)
    if report_id:
        row = get_test_result_by_id(report_id)
        if row and row.get("report_data"):
            try:
                report = json.loads(row["report_data"])
                if report.get("kind") == "ishihara":
                    return _generate_pdf_report(report, "ishihara_report.pdf")
            except (json.JSONDecodeError, TypeError):
                pass
        return redirect(url_for("reports"))
    report = session.get("last_report")
    if report and report.get("kind") == "ishihara":
        return _generate_pdf_report(report, "ishihara_report.pdf")
    return redirect(url_for("index"))


@app.route("/download-report")
def download_report():
    # 1. Enforce login and remember the requested download URL
    if not session.get("user_id"):
        session["pending_download"] = request.url
        return redirect(url_for("login"))

    report_id = request.args.get("id", type=int)
    if report_id:
        row = get_test_result_by_id(report_id)
        if row and row.get("report_data"):
            try:
                report = json.loads(row["report_data"])
                return _generate_pdf_report(report, "color_vision_report.pdf")
            except (json.JSONDecodeError, TypeError):
                pass
        return redirect(url_for("reports"))
    report = session.get("last_report")
    if not report:
        return redirect(url_for("index"))
    return _generate_pdf_report(report, "d15_report.pdf")


@app.route("/download-mosaic-report")
def download_mosaic_report():
    # 1. Enforce login and remember the requested download URL
    if not session.get("user_id"):
        session["pending_download"] = request.url
        return redirect(url_for("login"))

    report_id = request.args.get("id", type=int)
    if report_id:
        row = get_test_result_by_id(report_id)
        if row and row.get("report_data"):
            try:
                report = json.loads(row["report_data"])
                if report.get("kind") == "mosaic":
                    return _generate_pdf_report(report, "mosaic_report.pdf")
            except (json.JSONDecodeError, TypeError):
                pass
        return redirect(url_for("reports"))
    
    report = session.get("last_report")
    if report and report.get("kind") == "mosaic":
        return _generate_pdf_report(report, "mosaic_report.pdf")
    
    return redirect(url_for("index"))

# PDF generation
def _generate_pdf_report(report: dict, filename: str):
    """Generate a PDF report using reportlab."""
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import inch
    from reportlab.lib import colors
    from reportlab.platypus import (
        SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable,
    )

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        rightMargin=inch * 0.75,
        leftMargin=inch * 0.75,
        topMargin=inch * 0.75,
        bottomMargin=inch * 0.75,
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "ReportTitle",
        parent=styles["Title"],
        fontSize=18,
        spaceAfter=6,
        textColor=colors.HexColor("#1a1a2e"),
    )
    heading_style = ParagraphStyle(
        "SectionHeading",
        parent=styles["Heading2"],
        fontSize=13,
        spaceBefore=12,
        spaceAfter=4,
        textColor=colors.HexColor("#16213e"),
    )

    story = []

    # Title block
    story.append(Paragraph("Color Blindness Detection System", title_style))
    story.append(Paragraph(f"Test: {report.get('test_name', 'Unknown')}", styles["Heading2"]))
    story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#cccccc")))
    story.append(Spacer(1, 8))

    #Patient Information Block
    user_id = session.get("user_id")
    if user_id:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute("SELECT name, username, email, age, gender FROM users WHERE id = ?", (user_id,))
        user_info = c.fetchone()
        conn.close()

        if user_info:
            story.append(Paragraph("Patient Information", heading_style))
            patient_data = [
                ["Name", user_info["name"] or "-"],
                ["Username", user_info["username"] or "-"],
                ["Email", user_info["email"] or "-"],
                ["Age", str(user_info["age"]) if user_info["age"] else "-"],
                ["Gender", user_info["gender"] or "-"],
            ]
            patient_table = Table(patient_data, colWidths=[1.8 * inch, 5 * inch])
            patient_table.setStyle(TableStyle([
                ("BACKGROUND",   (0, 0), (0, -1), colors.HexColor("#e8eaf6")),
                ("FONTNAME",     (0, 0), (0, -1), "Helvetica-Bold"),
                ("FONTSIZE",     (0, 0), (-1, -1), 11),
                ("ROWBACKGROUNDS", (1, 0), (-1, -1), [colors.white, colors.HexColor("#f5f5f5")]),
                ("GRID",         (0, 0), (-1, -1), 0.5, colors.HexColor("#cccccc")),
                ("TOPPADDING",   (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING",(0, 0), (-1, -1), 6),
                ("LEFTPADDING",  (0, 0), (-1, -1), 8),
            ]))
            story.append(patient_table)
            story.append(Spacer(1, 14))

    # Summary info table
    story.append(Paragraph("Diagnosis Overview", heading_style))
    diagnosis = report.get("diagnosis", "-")
    timestamp = report.get("timestamp", "-")
    kind      = report.get("kind", "")

    summary_data = [
        ["Diagnosis", diagnosis],
        ["Date / Time", timestamp],
    ]
    summary_table = Table(summary_data, colWidths=[1.8 * inch, 5 * inch])
    summary_table.setStyle(TableStyle([
        ("BACKGROUND",   (0, 0), (0, -1), colors.HexColor("#e8eaf6")),
        ("FONTNAME",     (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTSIZE",     (0, 0), (-1, -1), 11),
        ("ROWBACKGROUNDS", (1, 0), (-1, -1), [colors.white, colors.HexColor("#f5f5f5")]),
        ("GRID",         (0, 0), (-1, -1), 0.5, colors.HexColor("#cccccc")),
        ("TOPPADDING",   (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING",(0, 0), (-1, -1), 6),
        ("LEFTPADDING",  (0, 0), (-1, -1), 8),
    ]))
    story.append(summary_table)
    story.append(Spacer(1, 14))

    #Farnsworth D-15 detail
    if kind == "d15":
        summary = report.get("summary", {})
        story.append(Paragraph("Score Summary", heading_style))
        score_data = [
            ["Metric",              "Result"],
            ["Total Error Score",   str(summary.get("total_error_score", 0))],
            ["Confusion Crossings", str(summary.get("crossings", 0))],
            ["Dominant Axis",       summary.get("confusion_axis") or "None"],
        ]
        ax = summary.get("axis_crossings", {})
        for axis_name, cnt in ax.items():
            score_data.append([f"  {axis_name} axis crossings", str(cnt)])

        score_table = Table(score_data, colWidths=[2.5 * inch, 4.3 * inch])
        score_table.setStyle(TableStyle([
            ("BACKGROUND",   (0, 0), (-1, 0), colors.HexColor("#3949ab")),
            ("TEXTCOLOR",    (0, 0), (-1, 0), colors.white),
            ("FONTNAME",     (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE",     (0, 0), (-1, -1), 11),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f5f5f5")]),
            ("GRID",         (0, 0), (-1, -1), 0.5, colors.HexColor("#cccccc")),
            ("TOPPADDING",   (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING",(0, 0), (-1, -1), 6),
            ("LEFTPADDING",  (0, 0), (-1, -1), 8),
        ]))
        story.append(score_table)
        story.append(Spacer(1, 14))

        story.append(Paragraph("Arrangement Sequence", heading_style))
        seq = summary.get("sequence", [])
        q_data = [["Position", "Cap ID", "Step Error"]]
        for item in seq:
            q_data.append([
                str(item.get("position", "")),
                f"Cap {item.get('cap_id', '')}",
                str(item.get("step_error", 0)),
            ])
        col_w = [1.2 * inch, 2.0 * inch, 1.5 * inch]
        q_table = Table(q_data, colWidths=col_w)
        result_colors = [
            ("TEXTCOLOR", (2, i + 1), (2, i + 1),
             colors.HexColor("#2e7d32") if row[2] == "0" else colors.HexColor("#c62828"))
            for i, row in enumerate(q_data[1:])
        ]
        q_table.setStyle(TableStyle([
            ("BACKGROUND",   (0, 0), (-1, 0), colors.HexColor("#3949ab")),
            ("TEXTCOLOR",    (0, 0), (-1, 0), colors.white),
            ("FONTNAME",     (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE",     (0, 0), (-1, -1), 10),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f5f5f5")]),
            ("GRID",         (0, 0), (-1, -1), 0.5, colors.HexColor("#cccccc")),
            ("TOPPADDING",   (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING",(0, 0), (-1, -1), 5),
            ("LEFTPADDING",  (0, 0), (-1, -1), 6),
        ] + result_colors))
        story.append(q_table)

    #Ishihara detail
    elif kind == "ishihara":
        details     = report.get("details", {})
        total_q     = details.get("total_questions", 0)
        correct     = details.get("normal_score", details.get("correct_count", 0))
        percentage  = details.get("percentage", 0)

        story.append(Paragraph("Score Summary", heading_style))
        score_data = [
            ["Metric",          "Result"],
            ["Total Questions",  str(total_q)],
            ["Correct Answers",  str(correct)],
            ["Score",            f"{correct} / {total_q}"],
            ["Accuracy",         f"{percentage}%"],
            ["Protan Matches",   str(details.get("protan_score", 0))],
            ["Deutan Matches",   str(details.get("deutan_score", 0))],
        ]
        score_table = Table(score_data, colWidths=[2.5 * inch, 4.3 * inch])
        score_table.setStyle(TableStyle([
            ("BACKGROUND",   (0, 0), (-1, 0), colors.HexColor("#3949ab")),
            ("TEXTCOLOR",    (0, 0), (-1, 0), colors.white),
            ("FONTNAME",     (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE",     (0, 0), (-1, -1), 11),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f5f5f5")]),
            ("GRID",         (0, 0), (-1, -1), 0.5, colors.HexColor("#cccccc")),
            ("TOPPADDING",   (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING",(0, 0), (-1, -1), 6),
            ("LEFTPADDING",  (0, 0), (-1, -1), 8),
        ]))
        story.append(score_table)
        story.append(Spacer(1, 14))

        answers = details.get("answers", [])
        if answers:
            story.append(Paragraph("Answer Table", heading_style))
            a_data = [["Question", "Your Answer", "Correct Answer", "Result"]]
            for a in answers:
                user_ans    = str(a.get("userAnswer", ""))
                correct_ans = str(a.get("correctAnswer", ""))
                is_right    = a.get("result", "") == "normal"
                a_data.append([
                    str(a.get("question", "")),
                    user_ans,
                    correct_ans,
                    "Correct" if is_right else "Incorrect",
                ])
            col_w = [1.5 * inch, 1.8 * inch, 1.8 * inch, 1.7 * inch]
            a_table = Table(a_data, colWidths=col_w)
            result_colors = [
                ("TEXTCOLOR", (3, i + 1), (3, i + 1),
                 colors.HexColor("#2e7d32") if row[3] == "Correct" else colors.HexColor("#c62828"))
                for i, row in enumerate(a_data[1:])
            ]
            a_table.setStyle(TableStyle([
                ("BACKGROUND",   (0, 0), (-1, 0), colors.HexColor("#3949ab")),
                ("TEXTCOLOR",    (0, 0), (-1, 0), colors.white),
                ("FONTNAME",     (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE",     (0, 0), (-1, -1), 10),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f5f5f5")]),
                ("GRID",         (0, 0), (-1, -1), 0.5, colors.HexColor("#cccccc")),
                ("TOPPADDING",   (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING",(0, 0), (-1, -1), 5),
                ("LEFTPADDING",  (0, 0), (-1, -1), 6),
            ] + result_colors))
            story.append(a_table)
            
    #Mosaic detail
    elif kind == "mosaic":
        summary = report.get("summary", {})
        story.append(Paragraph("Score Summary", heading_style))

        total_tiles  = summary.get("total_tiles", summary.get("total", 0))
        total_correct = summary.get("total_correct", summary.get("correct", 0))
        rg_correct   = summary.get("rg_correct", 0)
        rg_total     = summary.get("rg_total", 0)
        by_correct   = summary.get("by_correct", 0)
        by_total     = summary.get("by_total", 0)
        rg_errors    = summary.get("total_rg_errors", 0)
        trit_errors  = summary.get("total_tritan_errors", 0)
        ctrl_acc     = summary.get("control_accuracy", 1.0)

        score_data = [
            ["Metric", "Result"],
            ["Total Tiles",            str(total_tiles)],
            ["Correctly Grouped",      str(total_correct)],
            ["Red-Green Plate",        f"{rg_correct} / {rg_total} correct"],
            ["Blue-Yellow Plate",      f"{by_correct} / {by_total} correct"],
            ["Red-Green Confusions",   str(rg_errors)],
            ["Blue-Yellow Confusions", str(trit_errors)],
            ["Control Accuracy",       f"{round(ctrl_acc * 100)}%"],
        ]
        score_table = Table(score_data, colWidths=[2.5 * inch, 4.3 * inch])
        score_table.setStyle(TableStyle([
            ("BACKGROUND",   (0, 0), (-1, 0), colors.HexColor("#3949ab")),
            ("TEXTCOLOR",    (0, 0), (-1, 0), colors.white),
            ("FONTNAME",     (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE",     (0, 0), (-1, -1), 11),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f5f5f5")]),
            ("GRID",         (0, 0), (-1, -1), 0.5, colors.HexColor("#cccccc")),
            ("TOPPADDING",   (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING",(0, 0), (-1, -1), 6),
            ("LEFTPADDING",  (0, 0), (-1, -1), 8),
        ]))
        story.append(score_table)
        story.append(Spacer(1, 14))

        details = report.get("details", [])
        if details:
            story.append(Paragraph("Round Breakdown", heading_style))
            a_data = [["Round", "Plate Type", "Correct Tiles", "RG Errors", "BY Errors", "Unassigned"]]
            for item in details:
                a_data.append([
                    f"Round {item.get('id', '')}",
                    item.get("label", item.get("type", "")),
                    f"{item.get('correct', 0)} / {item.get('total_assigned', 0) + item.get('unassigned', 0)}",
                    str(item.get("rg_errors", 0)),
                    str(item.get("tritan_errors", 0)),
                    str(item.get("unassigned", 0)),
                ])

            col_w = [0.8*inch, 1.4*inch, 1.2*inch, 1.0*inch, 1.0*inch, 1.0*inch]
            a_table = Table(a_data, colWidths=col_w)
            a_table.setStyle(TableStyle([
                ("BACKGROUND",   (0, 0), (-1, 0), colors.HexColor("#3949ab")),
                ("TEXTCOLOR",    (0, 0), (-1, 0), colors.white),
                ("FONTNAME",     (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE",     (0, 0), (-1, -1), 9),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f5f5f5")]),
                ("GRID",         (0, 0), (-1, -1), 0.5, colors.HexColor("#cccccc")),
                ("TOPPADDING",   (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING",(0, 0), (-1, -1), 5),
                ("LEFTPADDING",  (0, 0), (-1, -1), 6),
            ]))
            story.append(a_table)
            
    doc.build(story)
    buffer.seek(0)
    return send_file(
        buffer,
        mimetype="application/pdf",
        as_attachment=True,
        download_name=filename,
    )

# Entry point
@app.route("/test-email")
def test_email():
    """Test email configuration."""
    try:
        with smtplib.SMTP("smtp.gmail.com", 587) as server:
            server.starttls()
            server.login(OTP_SENDER_EMAIL, OTP_SENDER_PASSWORD)
            return f"<h2 style='color:green'>✓ Email Login SUCCESS for {OTP_SENDER_EMAIL}</h2>"
    except smtplib.SMTPAuthenticationError as e:
        error = e.smtp_error.decode() if hasattr(e.smtp_error, 'decode') else str(e)
        return f"<h2 style='color:red'>✗ Authentication Failed</h2><p>Error: {error}</p><p style='color:#666;'><strong>Fix:</strong> Use a Gmail App Password, not your regular password. <a href='https://support.google.com/accounts/answer/185833' target='_blank'>Create one here</a></p>"
    except Exception as e:
        return f"<h2 style='color:red'>✗ Error</h2><pre>{type(e).__name__}: {str(e)}</pre>"

if __name__ == "__main__":
    app.run(debug=True)