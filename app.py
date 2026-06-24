"""
MMCOE Campus Parking Management System — Web Edition
Created by Pushkar
Hosted on Railway — https://railway.app
"""

import os, datetime
from collections import OrderedDict
from flask import Flask, jsonify, request

app = Flask(__name__)

# ══════════════════════════════════════════════════════════════════════════════
# DATA MODEL  (in-memory — persists while server is running)
# ══════════════════════════════════════════════════════════════════════════════

BRANCH_MAP = {
    "CE": "Computer Engg",   "ME": "Mechanical Engg",
    "EE": "Electrical Engg", "CS": "Computer Science",
    "IT": "Info Technology", "CV": "Civil Engg",
    "ET": "Electronics",     "AI": "AI & ML",
}

class ParkingData:
    def __init__(self):
        self.pools = OrderedDict([
            ("T4W", {f"T4W-{i:02d}": None for i in range(1, 18)}),
            ("T2W", {f"T2W-{i:02d}": None for i in range(1, 24)}),
            ("S4W", {f"S4W-{i:02d}": None for i in range(1, 21)}),
            ("S2W", {f"S2W-{i:02d}": None for i in range(1, 101)}),
            ("G4W", {f"G4W-{i:02d}": None for i in range(1, 8)}),
            ("G2W", {f"G2W-{i:02d}": None for i in range(1, 9)}),
        ])
        self.active  = {}   # uid → {slot, time_in, role, vehicle}
        self.history = []   # list of log dicts

    def pool_key(self, role, vehicle):
        p = {"Student": "S", "Teacher": "T", "Guest": "G"}[role]
        return p + ("4W" if vehicle == "4-Wheeler" else "2W")

    def totals(self):
        return {k: (sum(1 for v in s.values() if v is None), len(s))
                for k, s in self.pools.items()}

    def allocate(self, uid, role, vehicle):
        if uid in self.active:
            return None, f"{uid} is already parked in slot {self.active[uid]['slot']}."
        key = self.pool_key(role, vehicle)
        for slot, occ in self.pools[key].items():
            if occ is None:
                self.pools[key][slot] = uid
                t = datetime.datetime.now()
                self.active[uid] = {"slot": slot, "time_in": t,
                                     "role": role, "vehicle": vehicle}
                self.history.append({
                    "time": t.strftime("%H:%M:%S"), "date": t.strftime("%Y-%m-%d"),
                    "id": uid, "role": role, "vehicle": vehicle,
                    "slot": slot, "status": "PARKED", "duration": ""
                })
                return slot, None
        return None, f"No {vehicle} slots left for {role}s — pool {key} is FULL."

    def release(self, uid):
        if uid not in self.active:
            return None, f"ID '{uid}' not found in active records."
        s   = self.active.pop(uid)
        self.pools[s["slot"][:3]][s["slot"]] = None
        t   = datetime.datetime.now()
        dur = round((t - s["time_in"]).total_seconds() / 60, 1)
        self.history.append({
            "time": t.strftime("%H:%M:%S"), "date": t.strftime("%Y-%m-%d"),
            "id": uid, "role": s["role"], "vehicle": s["vehicle"],
            "slot": s["slot"], "status": "EXITED", "duration": f"{dur} min"
        })
        return {**s, "time_out": t, "duration": dur}, None

    def active_list(self):
        return [{"id": uid, "slot": v["slot"], "role": v["role"],
                 "vehicle": v["vehicle"],
                 "time_in": v["time_in"].strftime("%H:%M:%S")}
                for uid, v in self.active.items()]

def parse_id(raw):
    raw = raw.strip().upper()
    if raw.startswith("B"):
        bc = raw[3:5] if len(raw) >= 5 else "??"
        return {"id": raw, "role": "Student", "branch_code": bc,
                "display": BRANCH_MAP.get(bc, bc)}
    elif raw.startswith("T"):
        return {"id": raw, "role": "Teacher", "branch_code": "", "display": "Faculty"}
    return {"id": raw, "role": "Guest", "branch_code": "", "display": "Visitor"}

db = ParkingData()

# ══════════════════════════════════════════════════════════════════════════════
# API
# ══════════════════════════════════════════════════════════════════════════════

@app.route("/api/status")
def api_status():
    return jsonify({"totals": db.totals(), "active": db.active_list(),
                    "time": datetime.datetime.now().strftime("%A, %d %b %Y  %H:%M:%S")})

@app.route("/api/lookup", methods=["POST"])
def api_lookup():
    raw = (request.json or {}).get("id", "").strip()
    if not raw: return jsonify({"error": "No ID provided."}), 400
    return jsonify(parse_id(raw))

@app.route("/api/entry", methods=["POST"])
def api_entry():
    d = request.json or {}
    raw, vehicle = d.get("id","").strip(), d.get("vehicle","").strip()
    if not raw or vehicle not in ("2-Wheeler","4-Wheeler"):
        return jsonify({"error": "Invalid ID or vehicle type."}), 400
    info = parse_id(raw)
    slot, err = db.allocate(info["id"], info["role"], vehicle)
    if err: return jsonify({"error": err}), 409
    return jsonify({"slot": slot, "role": info["role"],
                    "display": info["display"], "vehicle": vehicle})

@app.route("/api/exit", methods=["POST"])
def api_exit():
    raw = (request.json or {}).get("id","").strip()
    if not raw: return jsonify({"error": "No ID provided."}), 400
    info = parse_id(raw)
    session, err = db.release(info["id"])
    if err: return jsonify({"error": err}), 404
    return jsonify({"slot": session["slot"], "duration": session["duration"]})

@app.route("/api/log")
def api_log():
    return jsonify(list(reversed(db.history[-300:])))

# ══════════════════════════════════════════════════════════════════════════════
# FRONTEND
# ══════════════════════════════════════════════════════════════════════════════

@app.route("/")
def index():
    return HTML

HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>MMCOE Parking — by Pushkar</title>
<link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><text y='.9em' font-size='90'>🅿</text></svg>">
<style>
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
:root{
  --bg:#0D1117;--panel:#161B22;--card:#21262D;--border:#30363D;
  --accent:#58A6FF;--green:#3FB950;--red:#F85149;--yellow:#D29922;
  --text:#E6EDF3;--muted:#8B949E;--hi:#1F6FEB;--r:10px;
}
body{background:var(--bg);color:var(--text);font-family:'Segoe UI',system-ui,sans-serif;min-height:100vh}

/* topbar */
.topbar{background:var(--panel);border-bottom:1px solid var(--border);
  display:flex;align-items:center;justify-content:space-between;
  padding:0 20px;height:54px;position:sticky;top:0;z-index:99}
.topbar-l{display:flex;align-items:center;gap:10px}
.logo{font-size:20px}
.topbar h1{font-size:14px;font-weight:700;color:var(--accent);letter-spacing:.5px}
.topbar-r{display:flex;align-items:center;gap:16px}
#clock{font-family:Consolas,monospace;font-size:12px;color:var(--muted)}
.badge{font-size:11px;color:var(--muted);border:1px solid var(--border);
  border-radius:20px;padding:3px 12px}
.badge b{color:var(--accent)}

/* mode toggle */
#mode-btn{width:100%;border:none;cursor:pointer;font-size:14px;font-weight:700;
  padding:13px 20px;letter-spacing:.3px;transition:background .25s}
.m-entry{background:#0D3320;color:#3FB950}
.m-exit{background:#3A0D0D;color:#F85149}

/* grid */
.grid{display:grid;grid-template-columns:1fr 1fr;gap:14px;padding:14px}
@media(max-width:820px){.grid{grid-template-columns:1fr}}
.col{display:flex;flex-direction:column;gap:14px}

/* panel */
.pnl{background:var(--panel);border-radius:var(--r);border:1px solid var(--border)}
.pnl-title{font-size:10px;font-weight:700;color:var(--muted);letter-spacing:1px;
  text-transform:uppercase;padding:12px 16px 8px;border-bottom:1px solid var(--border)}

/* counters */
.cgrid{display:grid;grid-template-columns:1fr 1fr;gap:10px;padding:12px}
.cc{background:var(--card);border-radius:8px;padding:11px 13px;
  border-left:3px solid var(--border);transition:border-color .3s}
.cc .lbl{font-size:10px;color:var(--muted);margin-bottom:3px}
.cc .val{font-family:Consolas,monospace;font-size:24px;font-weight:700}
.cc .sub{font-size:9px;color:var(--border);margin-top:2px}
.ct{border-color:var(--accent)}.ct .val{color:var(--accent)}
.cs{border-color:var(--green)}.cs .val{color:var(--green)}
.cg{border-color:var(--yellow)}.cg .val{color:var(--yellow)}
.wy .val{color:var(--yellow)!important}
.wr .val{color:var(--red)!important}

/* scan input */
.sinp{padding:14px}
.hint{font-size:11px;color:var(--muted);margin-bottom:8px}
.srow{display:flex;gap:8px}
#idinput{flex:1;background:var(--card);border:2px solid var(--border);border-radius:8px;
  color:var(--text);font-family:Consolas,monospace;font-size:17px;font-weight:700;
  padding:9px 13px;outline:none;transition:border-color .2s}
#idinput:focus{border-color:var(--accent)}
#gobtn{background:var(--hi);color:#fff;border:none;border-radius:8px;
  font-size:13px;font-weight:700;padding:0 20px;cursor:pointer;transition:opacity .2s}
#gobtn:hover{opacity:.85}

/* vehicle picker */
#vpick{display:none;margin-top:12px;background:var(--card);border-radius:10px;
  padding:14px;border:1px solid var(--border)}
#vpick.show{display:block}
.vpid{font-family:Consolas,monospace;font-size:19px;font-weight:700}
.vprole{font-size:12px;margin:3px 0 12px}
.vpbtns{display:flex;gap:8px}
.vpb{flex:1;border:none;border-radius:8px;padding:11px;font-size:13px;
  font-weight:700;cursor:pointer;transition:opacity .2s}
.vpb:hover{opacity:.85}
.v2w{background:#196127;color:#fff}
.v4w{background:var(--hi);color:#fff}
.vcancel{background:var(--border);color:var(--muted);border:none;border-radius:6px;
  padding:7px 14px;font-size:11px;cursor:pointer;margin-top:8px}

/* quick test */
.qrow{display:flex;gap:6px;padding:0 14px 12px;flex-wrap:wrap}
.qbtn{background:var(--card);border:1px solid var(--border);border-radius:6px;
  color:var(--muted);font-size:10px;padding:5px 10px;cursor:pointer;
  font-family:Consolas,monospace;transition:border-color .2s}
.qbtn:hover{border-color:var(--accent);color:var(--text)}

/* output */
#outbox{margin:12px 14px;background:var(--card);border-radius:10px;
  min-height:120px;display:flex;align-items:center;justify-content:center;
  text-align:center;padding:18px;transition:background .3s}
#outtxt{font-size:15px;font-weight:700;color:var(--muted);
  white-space:pre-line;line-height:1.65}
.os{color:var(--green)!important;font-size:18px!important}
.ox{color:var(--yellow)!important;font-size:18px!important}
.oe{color:var(--red)!important}

/* tabs */
.tabs{display:flex;border-bottom:1px solid var(--border)}
.tab{padding:9px 16px;font-size:11px;font-weight:600;cursor:pointer;
  color:var(--muted);border-bottom:2px solid transparent;transition:.2s;user-select:none}
.tab.on{color:var(--accent);border-bottom-color:var(--accent)}
.tc{display:none}.tc.on{display:block}

/* active table */
.tw{padding:0 12px 12px;overflow-y:auto;max-height:240px}
table{width:100%;border-collapse:collapse;font-size:11px}
th{color:var(--muted);text-align:left;padding:6px 7px;
  border-bottom:1px solid var(--border);font-weight:600;font-size:10px}
td{padding:6px 7px;border-bottom:1px solid #1a1f27;font-family:Consolas,monospace}
tr:last-child td{border:none}
.rs{color:var(--green)}.rt{color:var(--accent)}.rg{color:var(--yellow)}
.empty{color:var(--muted);font-size:11px;padding:18px;text-align:center}

/* log */
.lw{padding:8px 12px 12px;overflow-y:auto;max-height:270px}
.lr{display:flex;gap:6px;font-size:10px;font-family:Consolas,monospace;
  padding:4px 0;border-bottom:1px solid #1a1f27;align-items:center;flex-wrap:wrap}
.lr:last-child{border:none}
.lp{color:var(--green);font-weight:700}.le{color:var(--yellow);font-weight:700}
.lid{color:var(--text);min-width:100px}.lsl{color:var(--accent);min-width:72px}
.lro{color:var(--muted);min-width:62px}.ltm{color:var(--muted);min-width:64px}

/* stats bar */
.statsbar{display:flex;gap:20px;padding:10px 16px;border-top:1px solid var(--border);
  flex-wrap:wrap}
.stat{font-size:11px;color:var(--muted)}
.stat b{color:var(--text)}

/* footer */
footer{text-align:center;padding:16px;font-size:11px;color:var(--border);
  border-top:1px solid var(--border);margin-top:4px}
footer span{color:var(--accent)}

/* pulse dot */
.dot{display:inline-block;width:7px;height:7px;border-radius:50%;
  background:var(--green);margin-right:5px;
  animation:pulse 2s infinite}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.3}}
@keyframes flash{0%,100%{opacity:1}50%{opacity:.35}}
.flash{animation:flash .35s ease 2}
</style>
</head>
<body>

<div class="topbar">
  <div class="topbar-l">
    <span class="logo">🅿</span>
    <h1>MMCOE CAMPUS PARKING MANAGEMENT SYSTEM</h1>
  </div>
  <div class="topbar-r">
    <span id="clock"></span>
    <span class="badge">Created by <b>Pushkar</b></span>
  </div>
</div>

<button id="mode-btn" class="m-entry" onclick="toggleMode()">
  🟢&nbsp;&nbsp;ENTRY MODE &nbsp;—&nbsp; Click here to switch to EXIT MODE
</button>

<div class="grid">

  <!-- LEFT -->
  <div class="col">
    <div class="pnl">
      <div class="pnl-title"><span class="dot"></span>Live Slot Availability</div>
      <div class="cgrid" id="cgrid"></div>
      <div class="statsbar">
        <div class="stat">Total Slots: <b>175</b></div>
        <div class="stat">Occupied: <b id="stat-occ">0</b></div>
        <div class="stat">Available: <b id="stat-av">175</b></div>
      </div>
    </div>

    <div class="pnl" style="flex:1">
      <div class="tabs">
        <div class="tab on" onclick="swTab('active',this)">🔒 Currently Parked</div>
        <div class="tab"    onclick="swTab('log',this)">📋 Recent Activity</div>
      </div>
      <div class="tc on" id="tc-active">
        <div class="tw" id="active-wrap"><div class="empty">No vehicles parked yet.</div></div>
      </div>
      <div class="tc" id="tc-log">
        <div class="lw" id="log-wrap"><div class="empty">Loading…</div></div>
      </div>
    </div>
  </div>

  <!-- RIGHT -->
  <div class="col">
    <div class="pnl">
      <div class="pnl-title">⌨ Barcode Scanner / Manual ID Input</div>
      <div class="sinp">
        <div class="hint">USB barcode scanner types here automatically. Press <b>Enter</b> or click GO.</div>
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
            <button class="vpb v2w" onclick="confirm2('2-Wheeler')">🏍 &nbsp;[2] Two-Wheeler</button>
            <button class="vpb v4w" onclick="confirm2('4-Wheeler')">🚗 &nbsp;[4] Four-Wheeler</button>
          </div>
          <button class="vcancel" onclick="cancelPick()">✕ Cancel</button>
        </div>
      </div>
      <div class="qrow">
        <span style="font-size:10px;color:var(--muted);align-self:center">Quick test →</span>
        <button class="qbtn" onclick="inject('B25CE1133')">Student B25CE1133</button>
        <button class="qbtn" onclick="inject('T_SHARMA')">Teacher T_SHARMA</button>
        <button class="qbtn" onclick="inject('GUEST01')">Guest GUEST01</button>
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
let mode='ENTRY', pending=null;

const POOLS=[
  {key:'T4W',lbl:'Teachers 4-Wheeler',cls:'ct',total:17},
  {key:'T2W',lbl:'Teachers 2-Wheeler',cls:'ct',total:23},
  {key:'S4W',lbl:'Students 4-Wheeler',cls:'cs',total:20},
  {key:'S2W',lbl:'Students 2-Wheeler',cls:'cs',total:100},
  {key:'G4W',lbl:'Guests 4-Wheeler',  cls:'cg',total:7},
  {key:'G2W',lbl:'Guests 2-Wheeler',  cls:'cg',total:8},
];

// build counter cards
document.getElementById('cgrid').innerHTML=POOLS.map(p=>`
  <div class="cc ${p.cls}" id="cc-${p.key}">
    <div class="lbl">${p.lbl}</div>
    <div class="val" id="v-${p.key}">--</div>
    <div class="sub">Total: ${p.total}</div>
  </div>`).join('');

// clock
setInterval(()=>{
  document.getElementById('clock').textContent=
    new Date().toLocaleString('en-IN',{weekday:'short',day:'2-digit',
    month:'short',year:'numeric',hour:'2-digit',minute:'2-digit',second:'2-digit'});
},1000);

// refresh every 3s
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
      occ+=t-a; av+=a;
    }
    document.getElementById('stat-occ').textContent=occ;
    document.getElementById('stat-av').textContent=av;
    renderActive(d.active);
  }catch(e){}
}
setInterval(refresh,3000); refresh();

function renderActive(rows){
  const w=document.getElementById('active-wrap');
  if(!rows.length){w.innerHTML='<div class="empty">No vehicles currently parked.</div>';return;}
  w.innerHTML=`<table><thead><tr>
    <th>Slot</th><th>ID</th><th>Role</th><th>Vehicle</th><th>Since</th>
  </tr></thead><tbody>${rows.map(r=>`<tr>
    <td style="color:var(--accent)">${r.slot}</td>
    <td>${r.id}</td>
    <td class="r${r.role[0].toLowerCase()}">${r.role}</td>
    <td>${r.vehicle}</td><td>${r.time_in}</td>
  </tr>`).join('')}</tbody></table>`;
}

// tabs
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
      <span class="lid">${r.id}</span>
      <span class="lsl">${r.slot}</span>
      <span class="lro">${r.role}</span>
      <span class="ltm">${r.time}</span>
      <span style="color:var(--muted)">${r.vehicle}</span>
      ${r.duration?`<span style="color:var(--muted)">${r.duration}</span>`:''}
    </div>`).join('');
  }catch(e){w.innerHTML='<div class="empty">Could not load log.</div>';}
}

// mode toggle
function toggleMode(){
  mode=mode==='ENTRY'?'EXIT':'ENTRY';
  const b=document.getElementById('mode-btn');
  if(mode==='ENTRY'){
    b.textContent='🟢  ENTRY MODE  —  Click here to switch to EXIT MODE';
    b.className='m-entry';
  }else{
    b.textContent='🔴  EXIT MODE  —  Click here to switch to ENTRY MODE';
    b.className='m-exit';
  }
  cancelPick();
  out(`Switched to ${mode} MODE`,'');
  focus();
}

// output
let otimer=null;
function out(msg,cls){
  const el=document.getElementById('outtxt');
  el.textContent=msg; el.className=cls||'';
  el.classList.add('flash');
  if(otimer)clearTimeout(otimer);
  if(cls==='os'||cls==='ox')
    otimer=setTimeout(()=>{el.textContent='Awaiting scan or ID entry…';el.className='';},3000);
}

function focus(){ document.getElementById('idinput').focus(); }

// process input
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
      pending=info; showPick(info);
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

// vehicle picker
function showPick(info){
  const clr={Student:'var(--green)',Teacher:'var(--accent)',Guest:'var(--yellow)'}[info.role]||'var(--text)';
  document.getElementById('vpid').textContent=info.id;
  document.getElementById('vprole').innerHTML=
    `<span style="color:${clr}">● ${info.role}</span> — ${info.display}`;
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
  pending=null; focus();
}
async function confirm2(vehicle){
  if(!pending)return;
  const info=pending; cancelPick();
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
</body>
</html>"""

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print(f"\n{'═'*50}")
    print(f"  MMCOE Parking  —  Created by Pushkar")
    print(f"{'═'*50}")
    print(f"  Open: http://localhost:{port}")
    print(f"{'═'*50}\n")
    app.run(host="0.0.0.0", port=port, debug=False)
