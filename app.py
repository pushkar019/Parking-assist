"""
MMCOE Campus Parking Management System — Web Edition
Created by Pushkar
With persistent SQLite database + Admin Dashboard
"""

import os, datetime, sqlite3, csv, io
from collections import OrderedDict
from flask import Flask, jsonify, request, Response, redirect

app = Flask(__name__)
DB  = os.path.join(os.path.dirname(__file__), "parking.db")

ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "mmcoe2024")

# ══════════════════════════════════════════════════════════════════════════════
# DATABASE
# ══════════════════════════════════════════════════════════════════════════════

def get_db():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with get_db() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS active_parking (
            user_id  TEXT PRIMARY KEY,
            slot     TEXT NOT NULL,
            role     TEXT NOT NULL,
            vehicle  TEXT NOT NULL,
            branch   TEXT DEFAULT '',
            time_in  TEXT NOT NULL,
            date_in  TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS parking_log (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            date       TEXT,
            user_id    TEXT,
            role       TEXT,
            branch     TEXT,
            vehicle    TEXT,
            slot       TEXT,
            time_in    TEXT,
            time_out   TEXT DEFAULT '',
            duration   TEXT DEFAULT '',
            status     TEXT
        );
        """)

init_db()

# ══════════════════════════════════════════════════════════════════════════════
# SLOT POOLS
# ══════════════════════════════════════════════════════════════════════════════

BRANCH_MAP = {
    "CE":"Computer Engg","ME":"Mechanical Engg","EE":"Electrical Engg",
    "CS":"Computer Science","IT":"Info Technology","CV":"Civil Engg",
    "ET":"Electronics","AI":"AI & ML",
}

ALL_SLOTS = OrderedDict([
    ("T4W",[f"T4W-{i:02d}" for i in range(1,18)]),
    ("T2W",[f"T2W-{i:02d}" for i in range(1,24)]),
    ("S4W",[f"S4W-{i:02d}" for i in range(1,21)]),
    ("S2W",[f"S2W-{i:02d}" for i in range(1,101)]),
    ("G4W",[f"G4W-{i:02d}" for i in range(1,8)]),
    ("G2W",[f"G2W-{i:02d}" for i in range(1,9)]),
])

def pool_key(role, vehicle):
    return {"Student":"S","Teacher":"T","Guest":"G"}[role] + ("4W" if vehicle=="4-Wheeler" else "2W")

def get_occupied():
    with get_db() as c:
        return {r["slot"] for r in c.execute("SELECT slot FROM active_parking").fetchall()}

def get_totals():
    occ = get_occupied()
    return {k: (sum(1 for s in v if s not in occ), len(v)) for k,v in ALL_SLOTS.items()}

def next_free(key):
    occ = get_occupied()
    for s in ALL_SLOTS[key]:
        if s not in occ: return s
    return None

def parse_id(raw):
    raw = raw.strip().upper()
    if raw.startswith("B"):
        bc = raw[3:5] if len(raw)>=5 else "??"
        return {"id":raw,"role":"Student","branch_code":bc,"display":BRANCH_MAP.get(bc,bc)}
    elif raw.startswith("T"):
        return {"id":raw,"role":"Teacher","branch_code":"","display":"Faculty"}
    return {"id":raw,"role":"Guest","branch_code":"","display":"Visitor"}

# ══════════════════════════════════════════════════════════════════════════════
# AUTH HELPER
# ══════════════════════════════════════════════════════════════════════════════

def check_auth(request):
    auth = request.cookies.get("admin_auth","")
    return auth == ADMIN_PASSWORD

# ══════════════════════════════════════════════════════════════════════════════
# API ROUTES
# ══════════════════════════════════════════════════════════════════════════════

@app.route("/api/status")
def api_status():
    with get_db() as c:
        rows = c.execute("SELECT user_id,slot,role,vehicle,time_in FROM active_parking ORDER BY time_in").fetchall()
    return jsonify({
        "totals": get_totals(),
        "active": [{"id":r["user_id"],"slot":r["slot"],"role":r["role"],
                    "vehicle":r["vehicle"],"time_in":r["time_in"]} for r in rows],
        "time": datetime.datetime.now().strftime("%A, %d %b %Y  %H:%M:%S"),
    })

@app.route("/api/lookup", methods=["POST"])
def api_lookup():
    raw = (request.json or {}).get("id","").strip()
    if not raw: return jsonify({"error":"No ID provided."}), 400
    return jsonify(parse_id(raw))

@app.route("/api/entry", methods=["POST"])
def api_entry():
    d = request.json or {}
    raw, vehicle = d.get("id","").strip(), d.get("vehicle","").strip()
    if not raw or vehicle not in ("2-Wheeler","4-Wheeler"):
        return jsonify({"error":"Invalid ID or vehicle type."}), 400
    info = parse_id(raw)
    with get_db() as c:
        ex = c.execute("SELECT slot FROM active_parking WHERE user_id=?",(info["id"],)).fetchone()
        if ex: return jsonify({"error":f"{info['id']} already parked in {ex['slot']}."}), 409
        key  = pool_key(info["role"], vehicle)
        slot = next_free(key)
        if not slot: return jsonify({"error":f"No {vehicle} slots left for {info['role']}s — {key} FULL."}), 409
        now = datetime.datetime.now()
        t, dt = now.strftime("%H:%M:%S"), now.strftime("%Y-%m-%d")
        c.execute("INSERT INTO active_parking VALUES (?,?,?,?,?,?,?)",
                  (info["id"],slot,info["role"],vehicle,info["branch_code"],t,dt))
        c.execute("INSERT INTO parking_log (date,user_id,role,branch,vehicle,slot,time_in,status) VALUES (?,?,?,?,?,?,?,?)",
                  (dt,info["id"],info["role"],info["branch_code"],vehicle,slot,t,"PARKED"))
    return jsonify({"slot":slot,"role":info["role"],"display":info["display"],"vehicle":vehicle})

@app.route("/api/exit", methods=["POST"])
def api_exit():
    raw = (request.json or {}).get("id","").strip()
    if not raw: return jsonify({"error":"No ID provided."}), 400
    info = parse_id(raw)
    with get_db() as c:
        row = c.execute("SELECT slot,role,vehicle,branch,time_in,date_in FROM active_parking WHERE user_id=?",(info["id"],)).fetchone()
        if not row: return jsonify({"error":f"ID '{info['id']}' not found in active records."}), 404
        now = datetime.datetime.now()
        t_out, dt = now.strftime("%H:%M:%S"), now.strftime("%Y-%m-%d")
        try:
            base = datetime.datetime.strptime(row["date_in"]+" "+row["time_in"],"%Y-%m-%d %H:%M:%S")
            dur  = round((now-base).total_seconds()/60, 1)
        except: dur = 0
        c.execute("DELETE FROM active_parking WHERE user_id=?",(info["id"],))
        c.execute("INSERT INTO parking_log (date,user_id,role,branch,vehicle,slot,time_in,time_out,duration,status) VALUES (?,?,?,?,?,?,?,?,?,?)",
                  (dt,info["id"],row["role"],row["branch"],row["vehicle"],row["slot"],row["time_in"],t_out,f"{dur} min","EXITED"))
    return jsonify({"slot":row["slot"],"duration":dur})

@app.route("/api/log")
def api_log():
    with get_db() as c:
        rows = c.execute("SELECT * FROM parking_log ORDER BY id DESC LIMIT 300").fetchall()
    return jsonify([dict(r) for r in rows])

# ── Admin API ─────────────────────────────────────────────────────────────────

@app.route("/api/admin/stats")
def api_admin_stats():
    if not check_auth(request): return jsonify({"error":"Unauthorized"}), 401
    with get_db() as c:
        total_sessions = c.execute("SELECT COUNT(*) as n FROM parking_log WHERE status='PARKED'").fetchone()["n"]
        today = datetime.date.today().strftime("%Y-%m-%d")
        today_count    = c.execute("SELECT COUNT(*) as n FROM parking_log WHERE date=? AND status='PARKED'",(today,)).fetchone()["n"]
        by_role        = c.execute("SELECT role, COUNT(*) as n FROM parking_log WHERE status='PARKED' GROUP BY role").fetchall()
        by_vehicle     = c.execute("SELECT vehicle, COUNT(*) as n FROM parking_log WHERE status='PARKED' GROUP BY vehicle").fetchall()
        by_day         = c.execute("SELECT date, COUNT(*) as n FROM parking_log WHERE status='PARKED' GROUP BY date ORDER BY date DESC LIMIT 14").fetchall()
        avg_dur        = c.execute("SELECT AVG(CAST(REPLACE(duration,' min','') AS REAL)) as avg FROM parking_log WHERE status='EXITED' AND duration!=''").fetchone()["avg"]
        currently      = c.execute("SELECT COUNT(*) as n FROM active_parking").fetchone()["n"]
    return jsonify({
        "total_sessions": total_sessions,
        "today_count":    today_count,
        "currently":      currently,
        "avg_duration":   round(avg_dur or 0, 1),
        "by_role":    [dict(r) for r in by_role],
        "by_vehicle": [dict(r) for r in by_vehicle],
        "by_day":     [dict(r) for r in by_day],
    })

@app.route("/api/admin/log")
def api_admin_log():
    if not check_auth(request): return jsonify({"error":"Unauthorized"}), 401
    role    = request.args.get("role","")
    status  = request.args.get("status","")
    date    = request.args.get("date","")
    search  = request.args.get("search","")
    query   = "SELECT * FROM parking_log WHERE 1=1"
    params  = []
    if role:   query += " AND role=?";    params.append(role)
    if status: query += " AND status=?";  params.append(status)
    if date:   query += " AND date=?";    params.append(date)
    if search: query += " AND (user_id LIKE ? OR slot LIKE ?)"; params += [f"%{search}%",f"%{search}%"]
    query += " ORDER BY id DESC LIMIT 500"
    with get_db() as c:
        rows = c.execute(query, params).fetchall()
    return jsonify([dict(r) for r in rows])

@app.route("/api/admin/export")
def api_admin_export():
    if not check_auth(request): return jsonify({"error":"Unauthorized"}), 401
    with get_db() as c:
        rows = c.execute("SELECT * FROM parking_log ORDER BY id DESC").fetchall()
    out = io.StringIO()
    w   = csv.writer(out)
    w.writerow(["ID","Date","Role","Branch","Vehicle","Slot","Time In","Time Out","Duration","Status"])
    for r in rows:
        w.writerow([r["user_id"],r["date"],r["role"],r["branch"],r["vehicle"],
                    r["slot"],r["time_in"],r["time_out"],r["duration"],r["status"]])
    return Response(out.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition":"attachment;filename=parking_log.csv"})

@app.route("/api/admin/clear_active", methods=["POST"])
def api_admin_clear():
    if not check_auth(request): return jsonify({"error":"Unauthorized"}), 401
    with get_db() as c:
        c.execute("DELETE FROM active_parking")
    return jsonify({"ok":True})

# ══════════════════════════════════════════════════════════════════════════════
# ADMIN LOGIN PAGE
# ══════════════════════════════════════════════════════════════════════════════

@app.route("/admin/login", methods=["GET","POST"])
def admin_login():
    error = ""
    if request.method == "POST":
        pw = request.form.get("password","")
        if pw == ADMIN_PASSWORD:
            resp = redirect("/admin")
            resp.set_cookie("admin_auth", pw, max_age=86400*7)
            return resp
        error = "Wrong password. Try again."
    return f"""<!DOCTYPE html><html><head><title>Admin Login</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{background:#0D1117;color:#E6EDF3;font-family:'Segoe UI',sans-serif;
  display:flex;align-items:center;justify-content:center;min-height:100vh}}
.box{{background:#161B22;border:1px solid #30363D;border-radius:12px;
  padding:40px;width:340px;text-align:center}}
.logo{{font-size:40px;margin-bottom:12px}}
h1{{font-size:16px;color:#58A6FF;margin-bottom:6px}}
p{{font-size:12px;color:#8B949E;margin-bottom:24px}}
input{{width:100%;background:#21262D;border:2px solid #30363D;border-radius:8px;
  color:#E6EDF3;font-size:16px;padding:10px 14px;outline:none;margin-bottom:12px}}
input:focus{{border-color:#58A6FF}}
button{{width:100%;background:#1F6FEB;color:#fff;border:none;border-radius:8px;
  font-size:14px;font-weight:700;padding:12px;cursor:pointer}}
.err{{color:#F85149;font-size:12px;margin-bottom:12px}}
a{{color:#8B949E;font-size:11px;display:block;margin-top:16px}}
</style></head><body>
<div class="box">
  <div class="logo">🅿</div>
  <h1>MMCOE Parking — Admin</h1>
  <p>Created by Pushkar</p>
  {"<div class='err'>"+error+"</div>" if error else ""}
  <form method="POST">
    <input type="password" name="password" placeholder="Enter admin password" autofocus>
    <button type="submit">Login →</button>
  </form>
  <a href="/">← Back to main dashboard</a>
</div></body></html>"""

@app.route("/admin/logout")
def admin_logout():
    resp = redirect("/admin/login")
    resp.delete_cookie("admin_auth")
    return resp

# ══════════════════════════════════════════════════════════════════════════════
# ADMIN DASHBOARD PAGE
# ══════════════════════════════════════════════════════════════════════════════

@app.route("/admin")
def admin():
    if not check_auth(request):
        return redirect("/admin/login")
    return ADMIN_HTML

ADMIN_HTML = """<!DOCTYPE html>
<html lang="en"><head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Admin — MMCOE Parking</title>
<link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><text y='.9em' font-size='90'>🅿</text></svg>">
<style>
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
:root{--bg:#0D1117;--panel:#161B22;--card:#21262D;--border:#30363D;
  --accent:#58A6FF;--green:#3FB950;--red:#F85149;--yellow:#D29922;
  --text:#E6EDF3;--muted:#8B949E;--hi:#1F6FEB;--r:10px}
body{background:var(--bg);color:var(--text);font-family:'Segoe UI',system-ui,sans-serif;min-height:100vh}

/* topbar */
.topbar{background:var(--panel);border-bottom:1px solid var(--border);
  display:flex;align-items:center;justify-content:space-between;
  padding:0 20px;height:54px;position:sticky;top:0;z-index:99}
.topbar-l{display:flex;align-items:center;gap:10px}
.topbar h1{font-size:14px;font-weight:700;color:var(--accent)}
.topbar-r{display:flex;gap:10px;align-items:center}
.tbtn{background:var(--card);border:1px solid var(--border);border-radius:6px;
  color:var(--muted);font-size:11px;padding:6px 12px;cursor:pointer;
  text-decoration:none;transition:border-color .2s}
.tbtn:hover{border-color:var(--accent);color:var(--text)}
.tbtn.danger{border-color:var(--red);color:var(--red)}
.tbtn.danger:hover{background:#3A0D0D}

/* stat cards */
.scards{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;padding:16px}
@media(max-width:700px){.scards{grid-template-columns:1fr 1fr}}
.sc{background:var(--panel);border:1px solid var(--border);border-radius:var(--r);
  padding:16px 18px;border-top:3px solid var(--border)}
.sc .slbl{font-size:10px;color:var(--muted);text-transform:uppercase;
  letter-spacing:.8px;margin-bottom:6px}
.sc .sval{font-size:28px;font-weight:700;font-family:Consolas,monospace}
.sc .ssub{font-size:10px;color:var(--muted);margin-top:4px}
.sc.blue{border-top-color:var(--accent)}.sc.blue .sval{color:var(--accent)}
.sc.green{border-top-color:var(--green)}.sc.green .sval{color:var(--green)}
.sc.yellow{border-top-color:var(--yellow)}.sc.yellow .sval{color:var(--yellow)}
.sc.red{border-top-color:var(--red)}.sc.red .sval{color:var(--red)}

/* charts row */
.charts{display:grid;grid-template-columns:1fr 1fr 2fr;gap:12px;padding:0 16px 16px}
@media(max-width:900px){.charts{grid-template-columns:1fr}}
.chart-box{background:var(--panel);border:1px solid var(--border);border-radius:var(--r);padding:16px}
.chart-title{font-size:10px;font-weight:700;color:var(--muted);text-transform:uppercase;
  letter-spacing:.8px;margin-bottom:14px}

/* donut */
.donut-wrap{position:relative;width:120px;height:120px;margin:0 auto 12px}
svg.donut{transform:rotate(-90deg)}
.donut-label{position:absolute;top:50%;left:50%;transform:translate(-50%,-50%);
  text-align:center;font-size:11px;color:var(--muted)}
.donut-label b{font-size:18px;color:var(--text);display:block}

/* bar chart */
.bar-row{display:flex;align-items:center;gap:8px;margin-bottom:8px}
.bar-lbl{font-size:10px;color:var(--muted);width:70px;text-align:right;flex-shrink:0}
.bar-track{flex:1;background:var(--card);border-radius:4px;height:18px;overflow:hidden}
.bar-fill{height:100%;border-radius:4px;transition:width .6s ease;display:flex;align-items:center;padding-left:6px}
.bar-fill span{font-size:10px;font-weight:700;color:#fff}

/* legend */
.legend{display:flex;flex-wrap:wrap;gap:8px;margin-top:10px}
.leg{display:flex;align-items:center;gap:5px;font-size:10px;color:var(--muted)}
.leg-dot{width:8px;height:8px;border-radius:50%;flex-shrink:0}

/* filters */
.filters{display:flex;gap:8px;padding:0 16px 10px;flex-wrap:wrap;align-items:center}
.filters select,.filters input{background:var(--card);border:1px solid var(--border);
  border-radius:6px;color:var(--text);font-size:12px;padding:6px 10px;outline:none}
.filters select:focus,.filters input:focus{border-color:var(--accent)}
.fbtn{background:var(--hi);color:#fff;border:none;border-radius:6px;
  font-size:12px;font-weight:600;padding:6px 14px;cursor:pointer}
.ebtn{background:var(--green);color:#fff;border:none;border-radius:6px;
  font-size:12px;font-weight:600;padding:6px 14px;cursor:pointer;text-decoration:none}

/* log table */
.log-wrap{padding:0 16px 20px;overflow-x:auto}
table{width:100%;border-collapse:collapse;font-size:11px;min-width:600px}
th{color:var(--muted);text-align:left;padding:7px 8px;
  border-bottom:1px solid var(--border);font-weight:600;font-size:10px;
  text-transform:uppercase;letter-spacing:.5px;position:sticky;top:54px;
  background:var(--bg)}
td{padding:7px 8px;border-bottom:1px solid #1a1f27;font-family:Consolas,monospace}
tr:hover td{background:#1a1f27}
tr:last-child td{border:none}
.sp{color:var(--green);font-weight:700}.se{color:var(--yellow);font-weight:700}
.rs{color:var(--green)}.rt{color:var(--accent)}.rg{color:var(--yellow)}
.slot-badge{background:var(--card);border:1px solid var(--border);
  border-radius:4px;padding:1px 6px;color:var(--accent)}
.empty{text-align:center;padding:30px;color:var(--muted);font-size:12px}

.section-title{font-size:10px;font-weight:700;color:var(--muted);text-transform:uppercase;
  letter-spacing:.8px;padding:0 16px 8px}

footer{text-align:center;padding:16px;font-size:11px;color:var(--border);
  border-top:1px solid var(--border);margin-top:8px}
footer span{color:var(--accent)}
</style>
</head><body>

<div class="topbar">
  <div class="topbar-l">
    <span style="font-size:18px">🅿</span>
    <h1>MMCOE Parking — Admin Dashboard</h1>
  </div>
  <div class="topbar-r">
    <a href="/" class="tbtn">← Main Dashboard</a>
    <a href="/api/admin/export" class="tbtn" style="color:var(--green);border-color:var(--green)">⬇ Export CSV</a>
    <button class="tbtn danger" onclick="clearActive()">🗑 Clear Active</button>
    <a href="/admin/logout" class="tbtn">Logout</a>
  </div>
</div>

<!-- Stat Cards -->
<div class="scards">
  <div class="sc blue"><div class="slbl">Total Sessions (All Time)</div>
    <div class="sval" id="s-total">--</div><div class="ssub">Entry records</div></div>
  <div class="sc green"><div class="slbl">Today's Entries</div>
    <div class="sval" id="s-today">--</div><div class="ssub" id="s-today-date">--</div></div>
  <div class="sc yellow"><div class="slbl">Currently Parked</div>
    <div class="sval" id="s-current">--</div><div class="ssub">Active vehicles</div></div>
  <div class="sc red"><div class="slbl">Avg Duration</div>
    <div class="sval" id="s-avg">--</div><div class="ssub">minutes per session</div></div>
</div>

<!-- Charts -->
<div class="charts">
  <!-- Role donut -->
  <div class="chart-box">
    <div class="chart-title">By Role</div>
    <div class="donut-wrap">
      <svg class="donut" width="120" height="120" viewBox="0 0 120 120">
        <circle cx="60" cy="60" r="45" fill="none" stroke="#21262D" stroke-width="18"/>
        <circle id="d-student" cx="60" cy="60" r="45" fill="none"
          stroke="#3FB950" stroke-width="18" stroke-dasharray="0 283"/>
        <circle id="d-teacher" cx="60" cy="60" r="45" fill="none"
          stroke="#58A6FF" stroke-width="18" stroke-dasharray="0 283"/>
        <circle id="d-guest"   cx="60" cy="60" r="45" fill="none"
          stroke="#D29922" stroke-width="18" stroke-dasharray="0 283"/>
      </svg>
      <div class="donut-label"><b id="d-total">0</b>total</div>
    </div>
    <div class="legend" id="role-legend"></div>
  </div>

  <!-- Vehicle donut -->
  <div class="chart-box">
    <div class="chart-title">By Vehicle</div>
    <div class="donut-wrap">
      <svg class="donut" width="120" height="120" viewBox="0 0 120 120">
        <circle cx="60" cy="60" r="45" fill="none" stroke="#21262D" stroke-width="18"/>
        <circle id="d-2w" cx="60" cy="60" r="45" fill="none"
          stroke="#58A6FF" stroke-width="18" stroke-dasharray="0 283"/>
        <circle id="d-4w" cx="60" cy="60" r="45" fill="none"
          stroke="#D29922" stroke-width="18" stroke-dasharray="0 283"/>
      </svg>
      <div class="donut-label"><b id="d-vtotal">0</b>total</div>
    </div>
    <div class="legend" id="vehicle-legend"></div>
  </div>

  <!-- Daily bar chart -->
  <div class="chart-box">
    <div class="chart-title">Last 14 Days — Daily Entries</div>
    <div id="day-bars"></div>
  </div>
</div>

<!-- Log filters -->
<div class="section-title">📋 Full Activity Log</div>
<div class="filters">
  <input type="text"   id="f-search"  placeholder="Search ID or slot…" style="width:160px">
  <select id="f-role">
    <option value="">All Roles</option>
    <option>Student</option><option>Teacher</option><option>Guest</option>
  </select>
  <select id="f-status">
    <option value="">All Status</option>
    <option value="PARKED">Parked</option><option value="EXITED">Exited</option>
  </select>
  <input type="date" id="f-date">
  <button class="fbtn" onclick="loadLog()">Filter</button>
  <button class="fbtn" style="background:var(--card);color:var(--muted);border:1px solid var(--border)"
    onclick="clearFilters()">Clear</button>
  <a href="/api/admin/export" class="ebtn">⬇ Export All to CSV</a>
  <span id="log-count" style="font-size:11px;color:var(--muted)"></span>
</div>

<div class="log-wrap">
  <table>
    <thead><tr>
      <th>#</th><th>Date</th><th>ID</th><th>Role</th><th>Branch</th>
      <th>Vehicle</th><th>Slot</th><th>Time In</th><th>Time Out</th>
      <th>Duration</th><th>Status</th>
    </tr></thead>
    <tbody id="log-body"><tr><td colspan="11" class="empty">Loading…</td></tr></tbody>
  </table>
</div>

<footer>
  MMCOE Campus Parking — Admin Panel &nbsp;•&nbsp;
  Developed by <span>Pushkar</span> &nbsp;•&nbsp;
  Marathwada Mitra Mandal's College of Engineering, Pune
</footer>

<script>
// ── Load stats ────────────────────────────────────────────────────────────
async function loadStats(){
  try{
    const d=await(await fetch('/api/admin/stats')).json();
    document.getElementById('s-total').textContent   = d.total_sessions;
    document.getElementById('s-today').textContent   = d.today_count;
    document.getElementById('s-current').textContent = d.currently;
    document.getElementById('s-avg').textContent     = d.avg_duration;
    document.getElementById('s-today-date').textContent =
      new Date().toLocaleDateString('en-IN',{day:'2-digit',month:'short',year:'numeric'});

    // Role donut
    const RC={Student:'#3FB950',Teacher:'#58A6FF',Guest:'#D29922'};
    const rtotal=d.by_role.reduce((a,r)=>a+r.n,0);
    document.getElementById('d-total').textContent=rtotal;
    let off=0; const C=2*Math.PI*45;
    const roles=['Student','Teacher','Guest'];
    const ids  =['d-student','d-teacher','d-guest'];
    roles.forEach((role,i)=>{
      const row=d.by_role.find(r=>r.role===role)||{n:0};
      const frac=rtotal?row.n/rtotal:0;
      const dash=frac*C;
      const el=document.getElementById(ids[i]);
      el.style.strokeDasharray=`${dash} ${C-dash}`;
      el.style.strokeDashoffset=-off;
      off+=dash;
    });
    document.getElementById('role-legend').innerHTML=
      d.by_role.map(r=>`<div class="leg">
        <div class="leg-dot" style="background:${RC[r.role]||'#888'}"></div>
        ${r.role}: <b style="color:var(--text)">${r.n}</b>
      </div>`).join('');

    // Vehicle donut
    const VC={'2-Wheeler':'#58A6FF','4-Wheeler':'#D29922'};
    const vtotal=d.by_vehicle.reduce((a,r)=>a+r.n,0);
    document.getElementById('d-vtotal').textContent=vtotal;
    let voff=0;
    ['2-Wheeler','4-Wheeler'].forEach((v,i)=>{
      const row=d.by_vehicle.find(r=>r.vehicle===v)||{n:0};
      const frac=vtotal?row.n/vtotal:0;
      const dash=frac*C;
      const el=document.getElementById(['d-2w','d-4w'][i]);
      el.style.strokeDasharray=`${dash} ${C-dash}`;
      el.style.strokeDashoffset=-voff;
      voff+=dash;
    });
    document.getElementById('vehicle-legend').innerHTML=
      d.by_vehicle.map(r=>`<div class="leg">
        <div class="leg-dot" style="background:${VC[r.vehicle]||'#888'}"></div>
        ${r.vehicle}: <b style="color:var(--text)">${r.n}</b>
      </div>`).join('');

    // Day bars
    const max=Math.max(...d.by_day.map(r=>r.n),1);
    document.getElementById('day-bars').innerHTML=
      d.by_day.map(r=>`<div class="bar-row">
        <div class="bar-lbl">${r.date.slice(5)}</div>
        <div class="bar-track">
          <div class="bar-fill" style="width:${Math.round(r.n/max*100)}%;background:var(--hi)">
            <span>${r.n}</span>
          </div>
        </div>
      </div>`).join('') || '<div class="empty">No data yet.</div>';

  }catch(e){console.error(e);}
}

// ── Load log ──────────────────────────────────────────────────────────────
async function loadLog(){
  const search = document.getElementById('f-search').value.trim();
  const role   = document.getElementById('f-role').value;
  const status = document.getElementById('f-status').value;
  const date   = document.getElementById('f-date').value;
  const params = new URLSearchParams();
  if(search) params.set('search',search);
  if(role)   params.set('role',role);
  if(status) params.set('status',status);
  if(date)   params.set('date',date);
  try{
    const rows=await(await fetch('/api/admin/log?'+params)).json();
    document.getElementById('log-count').textContent=`${rows.length} records`;
    const tbody=document.getElementById('log-body');
    if(!rows.length){
      tbody.innerHTML='<tr><td colspan="11" class="empty">No records found.</td></tr>';return;
    }
    tbody.innerHTML=rows.map((r,i)=>`<tr>
      <td style="color:var(--muted)">${r.id}</td>
      <td>${r.date}</td>
      <td style="color:var(--text);font-weight:600">${r.user_id}</td>
      <td class="r${(r.role||'')[0].toLowerCase()}">${r.role}</td>
      <td style="color:var(--muted)">${r.branch||'—'}</td>
      <td>${r.vehicle}</td>
      <td><span class="slot-badge">${r.slot}</span></td>
      <td>${r.time_in}</td>
      <td>${r.time_out||'—'}</td>
      <td>${r.duration||'—'}</td>
      <td><span class="${r.status==='PARKED'?'sp':'se'}">${r.status}</span></td>
    </tr>`).join('');
  }catch(e){document.getElementById('log-body').innerHTML=
    '<tr><td colspan="11" class="empty">Error loading log.</td></tr>';}
}

function clearFilters(){
  ['f-search','f-role','f-status','f-date'].forEach(id=>{
    document.getElementById(id).value='';
  });
  loadLog();
}

async function clearActive(){
  if(!confirm('Clear all active parking records? This cannot be undone.'))return;
  const r=await fetch('/api/admin/clear_active',{method:'POST'});
  if(r.ok){alert('Active records cleared.');loadStats();loadLog();}
  else alert('Failed.');
}

loadStats(); loadLog();
setInterval(loadStats, 10000);
</script>
</body></html>"""

# ══════════════════════════════════════════════════════════════════════════════
# MAIN DASHBOARD (unchanged frontend)
# ══════════════════════════════════════════════════════════════════════════════

@app.route("/")
def index():
    return MAIN_HTML

MAIN_HTML = """<!DOCTYPE html>
<html lang="en"><head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>MMCOE Parking — by Pushkar</title>
<link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><text y='.9em' font-size='90'>🅿</text></svg>">
<style>
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
:root{--bg:#0D1117;--panel:#161B22;--card:#21262D;--border:#30363D;
  --accent:#58A6FF;--green:#3FB950;--red:#F85149;--yellow:#D29922;
  --text:#E6EDF3;--muted:#8B949E;--hi:#1F6FEB;--r:10px}
body{background:var(--bg);color:var(--text);font-family:'Segoe UI',system-ui,sans-serif;min-height:100vh}
.topbar{background:var(--panel);border-bottom:1px solid var(--border);
  display:flex;align-items:center;justify-content:space-between;
  padding:0 20px;height:54px;position:sticky;top:0;z-index:99}
.topbar-l{display:flex;align-items:center;gap:10px}
.logo{font-size:20px}
.topbar h1{font-size:13px;font-weight:700;color:var(--accent);letter-spacing:.5px}
.topbar-r{display:flex;align-items:center;gap:12px}
#clock{font-family:Consolas,monospace;font-size:11px;color:var(--muted)}
.badge{font-size:11px;color:var(--muted);border:1px solid var(--border);border-radius:20px;padding:3px 12px}
.badge b{color:var(--accent)}
.admin-link{font-size:11px;color:var(--muted);border:1px solid var(--border);
  border-radius:6px;padding:4px 10px;text-decoration:none;transition:.2s}
.admin-link:hover{border-color:var(--accent);color:var(--accent)}
.saved-pill{display:inline-flex;align-items:center;gap:5px;font-size:10px;
  background:#0d3320;color:var(--green);border:1px solid #196127;border-radius:20px;padding:3px 10px}
#mode-btn{width:100%;border:none;cursor:pointer;font-size:14px;font-weight:700;
  padding:13px 20px;letter-spacing:.3px;transition:background .25s}
.m-entry{background:#0D3320;color:#3FB950}
.m-exit{background:#3A0D0D;color:#F85149}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:14px;padding:14px}
@media(max-width:820px){.grid{grid-template-columns:1fr}}
.col{display:flex;flex-direction:column;gap:14px}
.pnl{background:var(--panel);border-radius:var(--r);border:1px solid var(--border)}
.pnl-title{font-size:10px;font-weight:700;color:var(--muted);letter-spacing:1px;
  text-transform:uppercase;padding:12px 16px 8px;border-bottom:1px solid var(--border)}
.cgrid{display:grid;grid-template-columns:1fr 1fr;gap:10px;padding:12px}
.cc{background:var(--card);border-radius:8px;padding:11px 13px;border-left:3px solid var(--border)}
.cc .lbl{font-size:10px;color:var(--muted);margin-bottom:3px}
.cc .val{font-family:Consolas,monospace;font-size:24px;font-weight:700}
.cc .sub{font-size:9px;color:var(--border);margin-top:2px}
.ct{border-color:var(--accent)}.ct .val{color:var(--accent)}
.cs{border-color:var(--green)}.cs .val{color:var(--green)}
.cg{border-color:var(--yellow)}.cg .val{color:var(--yellow)}
.wy .val{color:var(--yellow)!important}.wr .val{color:var(--red)!important}
.sinp{padding:14px}
.hint{font-size:11px;color:var(--muted);margin-bottom:8px}
.srow{display:flex;gap:8px}
#idinput{flex:1;background:var(--card);border:2px solid var(--border);border-radius:8px;
  color:var(--text);font-family:Consolas,monospace;font-size:17px;font-weight:700;
  padding:9px 13px;outline:none;transition:border-color .2s}
#idinput:focus{border-color:var(--accent)}
#gobtn{background:var(--hi);color:#fff;border:none;border-radius:8px;
  font-size:13px;font-weight:700;padding:0 20px;cursor:pointer}
#gobtn:hover{opacity:.85}
#vpick{display:none;margin-top:12px;background:var(--card);border-radius:10px;
  padding:14px;border:1px solid var(--border)}
#vpick.show{display:block}
.vpid{font-family:Consolas,monospace;font-size:19px;font-weight:700}
.vprole{font-size:12px;margin:3px 0 12px}
.vpbtns{display:flex;gap:8px}
.vpb{flex:1;border:none;border-radius:8px;padding:11px;font-size:13px;font-weight:700;cursor:pointer}
.vpb:hover{opacity:.85}
.v2w{background:#196127;color:#fff}.v4w{background:var(--hi);color:#fff}
.vcancel{background:var(--border);color:var(--muted);border:none;border-radius:6px;
  padding:7px 14px;font-size:11px;cursor:pointer;margin-top:8px}
.qrow{display:flex;gap:6px;padding:0 14px 12px;flex-wrap:wrap}
.qbtn{background:var(--card);border:1px solid var(--border);border-radius:6px;
  color:var(--muted);font-size:10px;padding:5px 10px;cursor:pointer;font-family:Consolas,monospace}
.qbtn:hover{border-color:var(--accent);color:var(--text)}
#outbox{margin:12px 14px;background:var(--card);border-radius:10px;min-height:120px;
  display:flex;align-items:center;justify-content:center;text-align:center;padding:18px}
#outtxt{font-size:15px;font-weight:700;color:var(--muted);white-space:pre-line;line-height:1.65}
.os{color:var(--green)!important;font-size:18px!important}
.ox{color:var(--yellow)!important;font-size:18px!important}
.oe{color:var(--red)!important}
.tabs{display:flex;border-bottom:1px solid var(--border)}
.tab{padding:9px 16px;font-size:11px;font-weight:600;cursor:pointer;
  color:var(--muted);border-bottom:2px solid transparent;transition:.2s;user-select:none}
.tab.on{color:var(--accent);border-bottom-color:var(--accent)}
.tc{display:none}.tc.on{display:block}
.tw{padding:0 12px 12px;overflow-y:auto;max-height:240px}
table{width:100%;border-collapse:collapse;font-size:11px}
th{color:var(--muted);text-align:left;padding:6px 7px;
  border-bottom:1px solid var(--border);font-weight:600;font-size:10px}
td{padding:6px 7px;border-bottom:1px solid #1a1f27;font-family:Consolas,monospace}
tr:last-child td{border:none}
.rs{color:var(--green)}.rt{color:var(--accent)}.rg{color:var(--yellow)}
.empty{color:var(--muted);font-size:11px;padding:18px;text-align:center}
.lw{padding:8px 12px 12px;overflow-y:auto;max-height:270px}
.lr{display:flex;gap:6px;font-size:10px;font-family:Consolas,monospace;
  padding:4px 0;border-bottom:1px solid #1a1f27;align-items:center;flex-wrap:wrap}
.lr:last-child{border:none}
.lp{color:var(--green);font-weight:700}.le{color:var(--yellow);font-weight:700}
.lid{color:var(--text);min-width:100px}.lsl{color:var(--accent);min-width:72px}
.lro{color:var(--muted);min-width:62px}.ltm{color:var(--muted);min-width:64px}
.statsbar{display:flex;gap:20px;padding:10px 16px;border-top:1px solid var(--border);flex-wrap:wrap}
.stat{font-size:11px;color:var(--muted)}.stat b{color:var(--text)}
.dot{display:inline-block;width:7px;height:7px;border-radius:50%;
  background:var(--green);margin-right:5px;animation:pulse 2s infinite}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.3}}
@keyframes flash{0%,100%{opacity:1}50%{opacity:.35}}
.flash{animation:flash .35s ease 2}
footer{text-align:center;padding:16px;font-size:11px;color:var(--border);
  border-top:1px solid var(--border);margin-top:4px}
footer span{color:var(--accent)}
</style></head><body>

<div class="topbar">
  <div class="topbar-l">
    <span class="logo">🅿</span>
    <h1>MMCOE CAMPUS PARKING MANAGEMENT SYSTEM</h1>
    <span class="saved-pill">💾 Data Saved</span>
  </div>
  <div class="topbar-r">
    <span id="clock"></span>
    <a href="/admin" class="admin-link">⚙ Admin</a>
    <span class="badge">Created by <b>Pushkar</b></span>
  </div>
</div>

<button id="mode-btn" class="m-entry" onclick="toggleMode()">
  🟢&nbsp;&nbsp;ENTRY MODE &nbsp;—&nbsp; Click here to switch to EXIT MODE
</button>

<div class="grid">
  <div class="col">
    <div class="pnl">
      <div class="pnl-title"><span class="dot"></span>Live Slot Availability</div>
      <div class="cgrid" id="cgrid"></div>
      <div class="statsbar">
        <div class="stat">Total: <b>175</b></div>
        <div class="stat">Occupied: <b id="s-occ">0</b></div>
        <div class="stat">Available: <b id="s-av">175</b></div>
      </div>
    </div>
    <div class="pnl" style="flex:1">
      <div class="tabs">
        <div class="tab on" onclick="swTab('active',this)">🔒 Currently Parked</div>
        <div class="tab"    onclick="swTab('log',this)">📋 Activity Log</div>
      </div>
      <div class="tc on" id="tc-active">
        <div class="tw" id="active-wrap"><div class="empty">No vehicles parked yet.</div></div>
      </div>
      <div class="tc" id="tc-log">
        <div class="lw" id="log-wrap"><div class="empty">Loading…</div></div>
      </div>
    </div>
  </div>
  <div class="col">
    <div class="pnl">
      <div class="pnl-title">⌨ Barcode Scanner / Manual ID Input</div>
      <div class="sinp">
        <div class="hint">USB scanner types here automatically. Press <b>Enter</b> or click GO.</div>
        <div class="srow">
          <input id="idinput" type="text" placeholder="e.g. B25CE1133"
            autocomplete="off" spellcheck="false"
            onkeydown="if(event.key==='Enter')go()">
          <button id="gobtn" onclick="go()">GO</button>
        </div>
        <div id="vpick">
          <div class="vpid" id="vpid">—</div>
          <div class="vprole" id="vprole">—</div>
          <div class="vpbtns">
            <button class="vpb v2w" onclick="confirm2('2-Wheeler')">🏍 [2] Two-Wheeler</button>
            <button class="vpb v4w" onclick="confirm2('4-Wheeler')">🚗 [4] Four-Wheeler</button>
          </div>
          <button class="vcancel" onclick="cancelPick()">✕ Cancel</button>
        </div>
      </div>
      <div class="qrow">
        <span style="font-size:10px;color:var(--muted);align-self:center">Quick test →</span>
        <button class="qbtn" onclick="inject('B25CE1133')">Student</button>
        <button class="qbtn" onclick="inject('T_SHARMA')">Teacher</button>
        <button class="qbtn" onclick="inject('GUEST01')">Guest</button>
      </div>
    </div>
    <div class="pnl" style="flex:1">
      <div class="pnl-title">📢 System Output</div>
      <div id="outbox"><div id="outtxt">Awaiting scan or ID entry…</div></div>
    </div>
  </div>
</div>

<footer>
  MMCOE Campus Parking Management System &nbsp;•&nbsp;
  Designed &amp; Developed by <span>Pushkar</span> &nbsp;•&nbsp;
  Marathwada Mitra Mandal's College of Engineering, Pune
</footer>

<script>
let mode='ENTRY',pending=null;
const POOLS=[
  {key:'T4W',lbl:'Teachers 4-Wheeler',cls:'ct',total:17},
  {key:'T2W',lbl:'Teachers 2-Wheeler',cls:'ct',total:23},
  {key:'S4W',lbl:'Students 4-Wheeler',cls:'cs',total:20},
  {key:'S2W',lbl:'Students 2-Wheeler',cls:'cs',total:100},
  {key:'G4W',lbl:'Guests 4-Wheeler',cls:'cg',total:7},
  {key:'G2W',lbl:'Guests 2-Wheeler',cls:'cg',total:8},
];
document.getElementById('cgrid').innerHTML=POOLS.map(p=>`
  <div class="cc ${p.cls}" id="cc-${p.key}">
    <div class="lbl">${p.lbl}</div>
    <div class="val" id="v-${p.key}">--</div>
    <div class="sub">Total: ${p.total}</div>
  </div>`).join('');
setInterval(()=>{
  document.getElementById('clock').textContent=
    new Date().toLocaleString('en-IN',{weekday:'short',day:'2-digit',
    month:'short',year:'numeric',hour:'2-digit',minute:'2-digit',second:'2-digit'});
},1000);
async function refresh(){
  try{
    const d=await(await fetch('/api/status')).json();
    let occ=0,av=0;
    for(const[k,[a,t]] of Object.entries(d.totals)){
      const el=document.getElementById('v-'+k);
      const cc=document.getElementById('cc-'+k);
      if(!el)continue;
      el.textContent=`${a} / ${t}`;
      cc.classList.remove('wy','wr');
      if(a<=3)cc.classList.add('wr');
      else if(a<=10)cc.classList.add('wy');
      occ+=t-a;av+=a;
    }
    document.getElementById('s-occ').textContent=occ;
    document.getElementById('s-av').textContent=av;
    renderActive(d.active);
  }catch(e){}
}
setInterval(refresh,3000);refresh();
function renderActive(rows){
  const w=document.getElementById('active-wrap');
  if(!rows.length){w.innerHTML='<div class="empty">No vehicles currently parked.</div>';return;}
  w.innerHTML=`<table><thead><tr>
    <th>Slot</th><th>ID</th><th>Role</th><th>Vehicle</th><th>Since</th>
  </tr></thead><tbody>${rows.map(r=>`<tr>
    <td style="color:var(--accent)">${r.slot}</td><td>${r.id}</td>
    <td class="r${r.role[0].toLowerCase()}">${r.role}</td>
    <td>${r.vehicle}</td><td>${r.time_in}</td>
  </tr>`).join('')}</tbody></table>`;
}
function swTab(name,el){
  document.querySelectorAll('.tab,.tc').forEach(x=>x.classList.remove('on'));
  el.classList.add('on');
  document.getElementById('tc-'+name).classList.add('on');
  if(name==='log')loadLog();
}
async function loadLog(){
  const w=document.getElementById('log-wrap');
  try{
    const rows=await(await fetch('/api/log')).json();
    if(!rows.length){w.innerHTML='<div class="empty">No activity yet.</div>';return;}
    w.innerHTML=rows.map(r=>`<div class="lr">
      <span class="${r.status==='PARKED'?'lp':'le'}">${r.status}</span>
      <span class="lid">${r.user_id}</span>
      <span class="lsl">${r.slot}</span>
      <span class="lro">${r.role}</span>
      <span class="ltm">${r.time_in}</span>
      <span style="color:var(--muted)">${r.vehicle}</span>
      ${r.duration?`<span style="color:var(--muted)">${r.duration}</span>`:''}
    </div>`).join('');
  }catch(e){w.innerHTML='<div class="empty">Could not load log.</div>';}
}
function toggleMode(){
  mode=mode==='ENTRY'?'EXIT':'ENTRY';
  const b=document.getElementById('mode-btn');
  if(mode==='ENTRY'){b.textContent='🟢  ENTRY MODE  —  Click here to switch to EXIT MODE';b.className='m-entry';}
  else{b.textContent='🔴  EXIT MODE  —  Click here to switch to ENTRY MODE';b.className='m-exit';}
  cancelPick();out(`Switched to ${mode} MODE`,'');focus();
}
let otimer=null;
function out(msg,cls){
  const el=document.getElementById('outtxt');
  el.textContent=msg;el.className=cls||'';el.classList.add('flash');
  if(otimer)clearTimeout(otimer);
  if(cls==='os'||cls==='ox')
    otimer=setTimeout(()=>{el.textContent='Awaiting scan or ID entry…';el.className='';},3000);
}
function focus(){document.getElementById('idinput').focus();}
async function go(){
  const raw=document.getElementById('idinput').value.trim();
  if(!raw)return;
  document.getElementById('idinput').value='';
  if(mode==='ENTRY'){
    try{
      const r=await fetch('/api/lookup',{method:'POST',
        headers:{'Content-Type':'application/json'},body:JSON.stringify({id:raw})});
      const info=await r.json();
      if(info.error){out('⚠ '+info.error,'oe');focus();return;}
      pending=info;showPick(info);
    }catch(e){out('⚠ Network error.','oe');}
  }else{
    try{
      const r=await fetch('/api/exit',{method:'POST',
        headers:{'Content-Type':'application/json'},body:JSON.stringify({id:raw})});
      const d=await r.json();
      if(!r.ok)out('⚠ '+d.error,'oe');
      else{out(`🔓  SLOT FREE\n\n${d.slot}\n\nID: ${raw}\nDuration: ${d.duration} min`,'ox');refresh();}
    }catch(e){out('⚠ Network error.','oe');}
    focus();
  }
}
function showPick(info){
  const clr={Student:'var(--green)',Teacher:'var(--accent)',Guest:'var(--yellow)'}[info.role]||'var(--text)';
  document.getElementById('vpid').textContent=info.id;
  document.getElementById('vprole').innerHTML=`<span style="color:${clr}">● ${info.role}</span> — ${info.display}`;
  document.getElementById('vpick').classList.add('show');
  document.addEventListener('keydown',pkHandler);
}
function pkHandler(e){
  if(e.key==='2')confirm2('2-Wheeler');
  if(e.key==='4')confirm2('4-Wheeler');
  if(e.key==='Escape')cancelPick();
}
function cancelPick(){
  document.getElementById('vpick').classList.remove('show');
  document.removeEventListener('keydown',pkHandler);
  pending=null;focus();
}
async function confirm2(vehicle){
  if(!pending)return;
  const info=pending;cancelPick();
  try{
    const r=await fetch('/api/entry',{method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({id:info.id,vehicle})});
    const d=await r.json();
    if(!r.ok)out('⚠ '+d.error,'oe');
    else{out(`✅  ALLOTTED\n\n${d.slot}\n\nID: ${info.id}\n${d.role}  •  ${d.display}\n${vehicle}`,'os');refresh();}
  }catch(e){out('⚠ Network error.','oe');}
  focus();
}
function inject(v){document.getElementById('idinput').value=v;go();}
window.addEventListener('load',focus);
</script>
</body></html>"""

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print(f"\n  MMCOE Parking — Created by Pushkar")
    print(f"  Open:  http://localhost:{port}")
    print(f"  Admin: http://localhost:{port}/admin  (password: {ADMIN_PASSWORD})\n")
    app.run(host="0.0.0.0", port=port, debug=False)
