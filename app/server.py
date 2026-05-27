
from flask import Flask, request, jsonify, Response, send_file, make_response
from flask_cors import CORS
import sqlite3, os, subprocess, threading, time
from datetime import datetime as dt, timedelta as td

app = Flask(__name__)
CORS(app)

DB = os.environ.get('DB_PATH', '/data/dashboard.db')

CITY_MAP = {
    "深圳":"Shenzhen","广州":"Guangzhou","北京":"Beijing","上海":"Shanghai",
    "成都":"Chengdu","武汉":"Wuhan","杭州":"Hangzhou","南京":"Nanjing",
    "西安":"Xian","重庆":"Chongqing","天津":"Tianjin","苏州":"Suzhou",
    "东莞":"Dongguan","佛山":"Foshan","珠海":"Zhuhai","厦门":"Xiamen",
    "福州":"Fuzhou","济南":"Jinan","青岛":"Qingdao","大连":"Dalian",
    "沈阳":"Shenyang","长沙":"Changsha","昆明":"Kunming","贵阳":"Guiyang",
    "南昌":"Nanchang","合肥":"Hefei","郑州":"Zhengzhou","哈尔滨":"Harbin",
    "南宁":"Nanning","海口":"Haikou","三亚":"Sanya","宁波":"Ningbo",
    "惠州":"Huizhou","中山":"Zhongshan","汕头":"Shantou",
}

def get_db():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    os.makedirs(os.path.dirname(DB), exist_ok=True)
    conn = get_db()
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS energy_entries (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        date TEXT UNIQUE NOT NULL,
        elec_huanbei_raw REAL, elec_datieguan_raw REAL,
        dik1_raw REAL, dik2_raw REAL, dik5_raw REAL,
        water_raw REAL, gas_raw REAL,
        elec_huanbei_usage REAL DEFAULT 0, elec_datieguan_usage REAL DEFAULT 0,
        dik1_usage REAL DEFAULT 0, dik2_usage REAL DEFAULT 0, dik5_usage REAL DEFAULT 0,
        elec_usage REAL DEFAULT 0,
        water_usage REAL DEFAULT 0, gas_usage REAL DEFAULT 0,
        ac_hours REAL DEFAULT 0, notes TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS ac_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        date TEXT NOT NULL, time TEXT NOT NULL,
        device TEXT NOT NULL, status TEXT NOT NULL,
        operator TEXT DEFAULT "", notes TEXT DEFAULT "",
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS boiler_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        date TEXT NOT NULL, time TEXT NOT NULL,
        device TEXT NOT NULL DEFAULT "5楼平台锅炉",
        status TEXT NOT NULL,
        operator TEXT DEFAULT "", notes TEXT DEFAULT "",
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);
    CREATE TABLE IF NOT EXISTS operators (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE NOT NULL,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password TEXT NOT NULL,
        role TEXT DEFAULT "admin",
        permissions TEXT DEFAULT "{}",
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    );
    INSERT OR IGNORE INTO settings VALUES("city","深圳");
    INSERT OR IGNORE INTO settings VALUES("city_lat","22.5431");
    INSERT OR IGNORE INTO settings VALUES("city_lon","114.0579");
    INSERT OR IGNORE INTO settings VALUES("admin_password","kami2024");
    INSERT OR IGNORE INTO users(username,password,role,permissions) VALUES("admin","kami2024","superadmin",'{"energy":true,"ac_log":true,"boiler_log":true,"users":true,"export":true,"settings":true}');
    """)
    # 兼容旧库
    for col_sql in [
        "ALTER TABLE boiler_logs ADD COLUMN device TEXT NOT NULL DEFAULT '5楼平台锅炉'",
        "ALTER TABLE energy_entries ADD COLUMN elec_huanbei_raw REAL",
        "ALTER TABLE energy_entries ADD COLUMN elec_datieguan_raw REAL",
        "ALTER TABLE energy_entries ADD COLUMN dik1_raw REAL",
        "ALTER TABLE energy_entries ADD COLUMN dik2_raw REAL",
        "ALTER TABLE energy_entries ADD COLUMN dik5_raw REAL",
        "ALTER TABLE energy_entries ADD COLUMN elec_huanbei_usage REAL DEFAULT 0",
        "ALTER TABLE energy_entries ADD COLUMN elec_datieguan_usage REAL DEFAULT 0",
        "ALTER TABLE energy_entries ADD COLUMN dik1_usage REAL DEFAULT 0",
        "ALTER TABLE energy_entries ADD COLUMN dik2_usage REAL DEFAULT 0",
        "ALTER TABLE energy_entries ADD COLUMN dik5_usage REAL DEFAULT 0",
    ]:
        try: conn.execute(col_sql)
        except: pass
    conn.commit()
    conn.close()

def calc_usage(cur, prev, mult=1):
    if cur is None or prev is None: return 0
    d = (float(cur) - float(prev)) * mult
    return round(d, 2) if d >= 0 else 0

def calc_ac_hours(conn, date):
    logs = conn.execute(
        "SELECT time,device,status FROM ac_logs WHERE date=? ORDER BY time", (date,)
    ).fetchall()
    devs = {}
    for r in logs:
        dev = r["device"]
        if dev not in devs: devs[dev] = {"on": None, "total": 0.0}
        if r["status"] == "开":
            devs[dev]["on"] = r["time"]
        elif r["status"] == "关" and devs[dev]["on"]:
            try:
                on = dt.strptime(f"{date} {devs[dev]['on']}", "%Y-%m-%d %H:%M")
                off = dt.strptime(f"{date} {r['time']}", "%Y-%m-%d %H:%M")
                diff = (off - on).total_seconds() / 3600
                if diff > 0: devs[dev]["total"] += diff
            except: pass
            devs[dev]["on"] = None
    return round(sum(v["total"] for v in devs.values()), 2)

# Weather cache
_wx = {}; _wx_lock = threading.Lock()

def fetch_wx(city_en):
    import json as J
    url = f"https://wttr.in/{city_en}?format=j1"
    script = "\n".join([
        "import requests,warnings,sys",
        "warnings.filterwarnings('ignore')",
        "try:",
        f"    r=requests.get('{url}',headers={{'User-Agent':'curl/7.88'}},verify=False,timeout=12)",
        "    sys.stdout.buffer.write(r.content)",
        "except Exception as e:",
        "    import json; sys.stdout.write(json.dumps({'error':str(e)}))",
    ])
    res = subprocess.run(["python3","-c",script], capture_output=True, timeout=20)
    raw = res.stdout
    try:
        d = J.loads(raw)
        return raw if "current_condition" in d else J.dumps({"error":"城市未找到"}).encode()
    except:
        return J.dumps({"error":"天气服务异常"}).encode()

@app.route("/")
def index():
    r = make_response(send_file("/app/index.html"))
    r.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    return r

@app.route("/api/settings", methods=["GET"])
def get_settings():
    conn = get_db()
    rows = conn.execute("SELECT key,value FROM settings").fetchall()
    conn.close()
    return jsonify({r["key"]:r["value"] for r in rows})

@app.route("/api/settings", methods=["POST"])
def save_settings():
    conn = get_db()
    for k,v in (request.json or {}).items():
        conn.execute("INSERT OR REPLACE INTO settings VALUES(?,?)", (k,str(v)))
    conn.commit(); conn.close()
    return jsonify({"ok":True})

@app.route("/api/weather")
def weather():
    city = request.args.get("city","深圳")
    city_en = CITY_MAP.get(city, city)
    now = time.time()
    with _wx_lock:
        cached = _wx.get(city_en)
    if cached and now - cached[1] < 1800:
        return Response(cached[0], mimetype="application/json")
    try:
        data = fetch_wx(city_en)
        if data and len(data) > 10:
            with _wx_lock: _wx[city_en] = (data, now)
        return Response(data, mimetype="application/json")
    except Exception as e:
        return jsonify({"error":str(e)}), 502

@app.route("/api/operators")
def get_operators():
    conn = get_db()
    rows = conn.execute("SELECT id,name FROM operators ORDER BY id").fetchall()
    conn.close()
    return jsonify([{"id":r["id"],"name":r["name"]} for r in rows])

@app.route("/api/operators", methods=["POST"])
def add_operator():
    d = request.json or {}
    name = d.get("name","").strip()
    if not name: return jsonify({"error":"姓名不能为空"}), 400
    conn = get_db()
    try:
        conn.execute("INSERT INTO operators(name) VALUES(?)", (name,))
        conn.commit()
        oid = conn.execute("SELECT id FROM operators WHERE name=?", (name,)).fetchone()["id"]
        conn.close()
        return jsonify({"ok":True,"id":oid,"name":name})
    except:
        conn.close()
        return jsonify({"error":"操作员已存在"}), 409

@app.route("/api/operators/<int:oid>", methods=["DELETE"])
def del_operator(oid):
    conn = get_db()
    conn.execute("DELETE FROM operators WHERE id=?", (oid,))
    conn.commit()
    conn.close()
    return jsonify({"ok":True})

@app.route("/api/entries")
def get_entries():
    s,e = request.args.get("start",""), request.args.get("end","")
    conn = get_db(); q = "SELECT * FROM energy_entries WHERE 1=1"; p = []
    if s: q += " AND date>=?"; p.append(s)
    if e: q += " AND date<=?"; p.append(e)
    rows = conn.execute(q+" ORDER BY date ASC",p).fetchall()
    conn.close(); return jsonify([dict(r) for r in rows])

@app.route("/api/entries", methods=["POST"])
def save_entry():
    d = request.json; date = d.get("date")
    if not date: return jsonify({"error":"日期必填"}), 400
    conn = get_db()

    # 如果当天已有记录，用已有值填补新提交里的 null，避免覆盖未填字段
    existing = conn.execute("SELECT * FROM energy_entries WHERE date=?",(date,)).fetchone()
    def pick(field, multiplier=None):
        """新提交有值用新值，否则保留已有值"""
        v = d.get(field)
        if v is not None:
            return v
        return existing[field] if existing else None

    hb  = pick("elec_huanbei_raw")
    dtg = pick("elec_datieguan_raw")
    dk1 = pick("dik1_raw")
    dk2 = pick("dik2_raw")
    dk5 = pick("dik5_raw")
    wat = pick("water_raw")
    gas = pick("gas_raw")

    # 全部字段都是 null（新提交+已有都没有）则跳过
    if all(v is None for v in [hb,dtg,dk1,dk2,dk5,wat,gas]):
        # 仅更新 ac_hours（空调/锅炉开关刚录入时触发）
        if existing:
            ac_h = calc_ac_hours(conn, date)
            conn.execute("UPDATE energy_entries SET ac_hours=?,updated_at=? WHERE date=?",
                (ac_h, dt.now().isoformat(), date))
            conn.commit()
        conn.close(); return jsonify({"ok":True})

    # 每个字段各自找最近一条有值的历史记录作为基准（避免中间某天只填了部分字段导致基准为null）
    def prev_val(field):
        row = conn.execute(
            f"SELECT {field} FROM energy_entries WHERE date<? AND {field} IS NOT NULL ORDER BY date DESC LIMIT 1",
            (date,)
        ).fetchone()
        return row[field] if row else None

    hb_u  = calc_usage(hb,  prev_val("elec_huanbei_raw"),  1500)
    dtg_u = calc_usage(dtg, prev_val("elec_datieguan_raw"), 1500)
    dk1_u = calc_usage(dk1, prev_val("dik1_raw"),           120)
    dk2_u = calc_usage(dk2, prev_val("dik2_raw"),           120)
    dk5_u = calc_usage(dk5, prev_val("dik5_raw"),           40)
    wat_u = calc_usage(wat, prev_val("water_raw"))
    gas_u = calc_usage(gas, prev_val("gas_raw"))
    ac_h  = calc_ac_hours(conn, date)
    notes = d.get("notes", existing["notes"] if existing else "") or ""

    conn.execute("""INSERT INTO energy_entries(date,elec_huanbei_raw,elec_datieguan_raw,
        dik1_raw,dik2_raw,dik5_raw,water_raw,gas_raw,
        elec_huanbei_usage,elec_datieguan_usage,dik1_usage,dik2_usage,dik5_usage,
        elec_usage,water_usage,gas_usage,ac_hours,notes,updated_at)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(date) DO UPDATE SET
        elec_huanbei_raw=excluded.elec_huanbei_raw,elec_datieguan_raw=excluded.elec_datieguan_raw,
        dik1_raw=excluded.dik1_raw,dik2_raw=excluded.dik2_raw,dik5_raw=excluded.dik5_raw,
        water_raw=excluded.water_raw,gas_raw=excluded.gas_raw,
        elec_huanbei_usage=excluded.elec_huanbei_usage,elec_datieguan_usage=excluded.elec_datieguan_usage,
        dik1_usage=excluded.dik1_usage,dik2_usage=excluded.dik2_usage,dik5_usage=excluded.dik5_usage,
        elec_usage=excluded.elec_usage,water_usage=excluded.water_usage,gas_usage=excluded.gas_usage,
        ac_hours=excluded.ac_hours,notes=excluded.notes,updated_at=excluded.updated_at""",
        (date,hb,dtg,dk1,dk2,dk5,wat,gas,hb_u,dtg_u,dk1_u,dk2_u,dk5_u,
         round((hb_u or 0)+(dtg_u or 0),2),wat_u,gas_u,ac_h,notes,dt.now().isoformat()))
    conn.commit(); conn.close(); return jsonify({"ok":True})

@app.route("/api/entries/<int:eid>", methods=["PUT"])
def update_entry(eid):
    d = request.json; conn = get_db()
    row = conn.execute("SELECT * FROM energy_entries WHERE id=?",(eid,)).fetchone()
    if not row: conn.close(); return jsonify({"error":"不存在"}), 404
    date = d.get("date",row["date"])
    # 编辑时：新提交有值用新值，否则保留记录原值
    hb  = d.get("elec_huanbei_raw",  row["elec_huanbei_raw"])
    dtg = d.get("elec_datieguan_raw", row["elec_datieguan_raw"])
    dk1 = d.get("dik1_raw",           row["dik1_raw"])
    dk2 = d.get("dik2_raw",           row["dik2_raw"])
    dk5 = d.get("dik5_raw",           row["dik5_raw"])
    wat = d.get("water_raw",           row["water_raw"])
    gas = d.get("gas_raw",             row["gas_raw"])

    # 每个字段各自找最近一条有值的历史记录作为基准
    def prev_val_edit(field):
        r2 = conn.execute(
            f"SELECT {field} FROM energy_entries WHERE date<? AND id!=? AND {field} IS NOT NULL ORDER BY date DESC LIMIT 1",
            (date, eid)
        ).fetchone()
        return r2[field] if r2 else None

    hb_u  = calc_usage(hb,  prev_val_edit("elec_huanbei_raw"),  1500)
    dtg_u = calc_usage(dtg, prev_val_edit("elec_datieguan_raw"), 1500)
    dk1_u = calc_usage(dk1, prev_val_edit("dik1_raw"),           120)
    dk2_u = calc_usage(dk2, prev_val_edit("dik2_raw"),           120)
    dk5_u = calc_usage(dk5, prev_val_edit("dik5_raw"),           40)
    wat_u = calc_usage(wat, prev_val_edit("water_raw"))
    gas_u = calc_usage(gas, prev_val_edit("gas_raw"))
    ac_h  = calc_ac_hours(conn, date)
    conn.execute("""UPDATE energy_entries SET date=?,elec_huanbei_raw=?,elec_datieguan_raw=?,
        dik1_raw=?,dik2_raw=?,dik5_raw=?,water_raw=?,gas_raw=?,
        elec_huanbei_usage=?,elec_datieguan_usage=?,dik1_usage=?,dik2_usage=?,dik5_usage=?,
        elec_usage=?,water_usage=?,gas_usage=?,ac_hours=?,notes=?,updated_at=? WHERE id=?""",
        (date,hb,dtg,dk1,dk2,dk5,wat,gas,hb_u,dtg_u,dk1_u,dk2_u,dk5_u,
         round((hb_u or 0)+(dtg_u or 0),2),wat_u,gas_u,ac_h,d.get("notes",row["notes"]),dt.now().isoformat(),eid))
    conn.commit(); conn.close(); return jsonify({"ok":True})

@app.route("/api/entries/<int:eid>", methods=["DELETE"])
def del_entry(eid):
    conn = get_db(); conn.execute("DELETE FROM energy_entries WHERE id=?",(eid,))
    conn.commit(); conn.close(); return jsonify({"ok":True})

@app.route("/api/d1k")
def get_ac():
    s,e = request.args.get("start",""), request.args.get("end","")
    conn = get_db(); q = "SELECT * FROM ac_logs WHERE 1=1"; p = []
    if s: q += " AND date>=?"; p.append(s)
    if e: q += " AND date<=?"; p.append(e)
    rows = conn.execute(q+" ORDER BY date DESC,time DESC",p).fetchall()
    conn.close(); return jsonify([dict(r) for r in rows])

@app.route("/api/d1k", methods=["POST"])
def save_ac():
    items = request.json
    if not isinstance(items, list): items = [items]
    conn = get_db()
    for it in items:
        conn.execute("INSERT INTO ac_logs(date,time,device,status,operator,notes) VALUES(?,?,?,?,?,?)",
            (it["date"],it["time"],it["device"],it["status"],it.get("operator",""),it.get("notes","")))
    conn.commit()
    for date in set(i["date"] for i in items):
        conn.execute("UPDATE energy_entries SET ac_hours=? WHERE date=?",(calc_ac_hours(conn,date),date))
    conn.commit(); conn.close(); return jsonify({"ok":True})

@app.route("/api/d1k/<int:lid>", methods=["PUT"])
def update_ac(lid):
    d = request.json; conn = get_db()
    old = conn.execute("SELECT date FROM ac_logs WHERE id=?",(lid,)).fetchone()
    conn.execute("UPDATE ac_logs SET date=?,time=?,device=?,status=?,operator=?,notes=? WHERE id=?",
        (d["date"],d["time"],d["device"],d["status"],d.get("operator",""),d.get("notes",""),lid))
    conn.commit()
    for date in set([old["date"] if old else d["date"], d["date"]]):
        conn.execute("UPDATE energy_entries SET ac_hours=? WHERE date=?",(calc_ac_hours(conn,date),date))
    conn.commit(); conn.close(); return jsonify({"ok":True})

@app.route("/api/d1k/<int:lid>", methods=["DELETE"])
def del_ac(lid):
    conn = get_db()
    old = conn.execute("SELECT date FROM ac_logs WHERE id=?",(lid,)).fetchone()
    conn.execute("DELETE FROM ac_logs WHERE id=?",(lid,)); conn.commit()
    if old:
        conn.execute("UPDATE energy_entries SET ac_hours=? WHERE date=?",(calc_ac_hours(conn,old["date"]),old["date"]))
        conn.commit()
    conn.close(); return jsonify({"ok":True})

@app.route("/api/boiler")
def get_boiler():
    s,e = request.args.get("start",""), request.args.get("end","")
    conn = get_db(); q = "SELECT * FROM boiler_logs WHERE 1=1"; p = []
    if s: q += " AND date>=?"; p.append(s)
    if e: q += " AND date<=?"; p.append(e)
    rows = conn.execute(q+" ORDER BY date DESC,time DESC",p).fetchall()
    conn.close(); return jsonify([dict(r) for r in rows])

@app.route("/api/boiler", methods=["POST"])
def save_boiler():
    it = request.json
    if isinstance(it, list): it = it[0]
    conn = get_db()
    conn.execute("INSERT INTO boiler_logs(date,time,device,status,operator,notes) VALUES(?,?,?,?,?,?)",
        (it["date"],it["time"],it.get("device","5楼平台锅炉"),it["status"],it.get("operator",""),it.get("notes","")))
    conn.commit(); conn.close(); return jsonify({"ok":True})

@app.route("/api/boiler/<int:lid>", methods=["PUT"])
def update_boiler(lid):
    d = request.json; conn = get_db()
    conn.execute("UPDATE boiler_logs SET date=?,time=?,device=?,status=?,operator=?,notes=? WHERE id=?",
        (d["date"],d["time"],d.get("device","5楼平台锅炉"),d["status"],d.get("operator",""),d.get("notes",""),lid))
    conn.commit(); conn.close(); return jsonify({"ok":True})

@app.route("/api/boiler/<int:lid>", methods=["DELETE"])
def del_boiler(lid):
    conn = get_db(); conn.execute("DELETE FROM boiler_logs WHERE id=?",(lid,))
    conn.commit(); conn.close(); return jsonify({"ok":True})

@app.route("/api/users")
def list_users():
    conn = get_db()
    rows = conn.execute("SELECT id,username,role,permissions,created_at FROM users ORDER BY id").fetchall()
    conn.close(); return jsonify([dict(r) for r in rows])

@app.route("/api/users", methods=["POST"])
def create_user():
    import json as J
    d = request.json or {}
    uname,upass,role = d.get("username","").strip(),d.get("password",""),d.get("role","admin")
    if not uname or len(upass)<4: return jsonify({"error":"账号不能为空，密码至少4位"}), 400
    perms = d.get("permissions", {})
    if role == "superadmin":
        perms = {"energy":True,"ac_log":True,"boiler_log":True,"users":True,"export":True,"settings":True}
    conn = get_db()
    try:
        conn.execute("INSERT INTO users(username,password,role,permissions) VALUES(?,?,?,?)",(uname,upass,role,J.dumps(perms)))
        conn.commit()
    except: conn.close(); return jsonify({"error":"账号已存在"}), 400
    conn.close(); return jsonify({"ok":True})

@app.route("/api/users/<int:uid>", methods=["PUT"])
def update_user(uid):
    import json as J
    d = request.json or {}; conn = get_db()
    row = conn.execute("SELECT * FROM users WHERE id=?",(uid,)).fetchone()
    if not row: conn.close(); return jsonify({"error":"不存在"}), 404
    pw = d.get("password","").strip()
    role = d.get("role", row["role"])
    if pw and len(pw)<4: conn.close(); return jsonify({"error":"密码至少4位"}), 400
    perms = d.get("permissions")
    perms_str = J.dumps(perms) if perms is not None else None
    if pw and perms_str:
        conn.execute("UPDATE users SET password=?,role=?,permissions=? WHERE id=?",(pw,role,perms_str,uid))
    elif pw:
        conn.execute("UPDATE users SET password=?,role=? WHERE id=?",(pw,role,uid))
    elif perms_str:
        conn.execute("UPDATE users SET role=?,permissions=? WHERE id=?",(role,perms_str,uid))
    else:
        conn.execute("UPDATE users SET role=? WHERE id=?",(role,uid))
    conn.commit(); conn.close(); return jsonify({"ok":True})

@app.route("/api/users/<int:uid>", methods=["DELETE"])
def delete_user(uid):
    conn = get_db()
    row = conn.execute("SELECT * FROM users WHERE id=?",(uid,)).fetchone()
    if not row: conn.close(); return jsonify({"error":"不存在"}), 404
    if row["role"]=="superadmin": conn.close(); return jsonify({"error":"超管不可删除"}), 403
    conn.execute("DELETE FROM users WHERE id=?",(uid,))
    conn.commit(); conn.close(); return jsonify({"ok":True})

@app.route("/api/verify_password", methods=["POST"])
def verify_password():
    import json as J
    d = request.json or {}
    conn = get_db()
    row = conn.execute("SELECT * FROM users WHERE username=? AND password=?",
        (d.get("username",""),d.get("password",""))).fetchone()
    conn.close()
    if row:
        try: perms = J.loads(row["permissions"] or "{}")
        except: perms = {}
        # superadmin 拥有全部权限
        if row["role"] == "superadmin":
            perms = {"energy":True,"ac_log":True,"boiler_log":True,"users":True,"export":True,"settings":True}
        return jsonify({"ok":True,"role":row["role"],"permissions":perms})
    return jsonify({"ok":False,"error":"账号或密码错误"}), 401

@app.route("/api/change_password", methods=["POST"])
def change_pw():
    d = request.json or {}
    conn = get_db()
    row = conn.execute("SELECT * FROM users WHERE username=? AND password=?",
        (d.get("username",""),d.get("old_password",""))).fetchone()
    if not row: conn.close(); return jsonify({"error":"原密码错误"}), 401
    new_pw = d.get("new_password","")
    if len(new_pw)<4: conn.close(); return jsonify({"error":"新密码至少4位"}), 400
    conn.execute("UPDATE users SET password=? WHERE username=?",(new_pw,d.get("username","")))
    conn.commit(); conn.close(); return jsonify({"ok":True})

@app.route("/api/export/csv")
def export_csv():
    from datetime import datetime as _dt2
    s = request.args.get("start", "")
    e = request.args.get("end", "")
    type_ = request.args.get("type", "elec")
    conn = get_db()

    q = "SELECT * FROM energy_entries WHERE 1=1"; p = []
    if s: q += " AND date>=?"; p.append(s)
    if e: q += " AND date<=?"; p.append(e)
    rows = conn.execute(q + " ORDER BY date", p).fetchall()
    conn.close()

    if type_ == "elec":
        header = "\ufeff日期,总用电量(kWh),环北线(kWh),打铁关线(kWh),DIK-1(kWh),DIK-2(kWh),DIK-5(kWh)"
        lines = [header]
        for r in rows:
            lines.append(f"{r['date']},{r['elec_usage'] or 0},{r['elec_huanbei_usage'] or 0},{r['elec_datieguan_usage'] or 0},{r['dik1_usage'] or 0},{r['dik2_usage'] or 0},{r['dik5_usage'] or 0}")
        fname = f"energy_elec_{s}_{e}.csv"
    elif type_ == "water":
        header = "\ufeff日期,总用水量(m³),水表读数"
        lines = [header]
        for r in rows:
            lines.append(f"{r['date']},{r['water_usage'] or 0},{r['water_raw'] or ''}")
        fname = f"energy_water_{s}_{e}.csv"
    elif type_ == "gas":
        header = "\ufeff日期,总用气量(m³),气表读数"
        lines = [header]
        for r in rows:
            lines.append(f"{r['date']},{r['gas_usage'] or 0},{r['gas_raw'] or ''}")
        fname = f"energy_gas_{s}_{e}.csv"
    else:
        # 全部导出：能耗记录 + 空调开关 + 锅炉开关
        conn2 = get_db()
        q_ac = "SELECT * FROM ac_logs WHERE 1=1"; p_ac = []
        q_bl = "SELECT * FROM boiler_logs WHERE 1=1"; p_bl = []
        if s:
            q_ac += " AND date>=?"; p_ac.append(s)
            q_bl += " AND date>=?"; p_bl.append(s)
        if e:
            q_ac += " AND date<=?"; p_ac.append(e)
            q_bl += " AND date<=?"; p_bl.append(e)
        ac_rows = conn2.execute(q_ac + " ORDER BY date,time", p_ac).fetchall()
        bl_rows = conn2.execute(q_bl + " ORDER BY date,time", p_bl).fetchall()
        conn2.close()

        from datetime import datetime as _dt3
        lines = [
            "\ufeff工程部能耗管理系统 - 完整数据导出",
            f"导出时间,{_dt3.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"时间范围,{s or '全部'} 至 {e or '全部'}",
            "",
            "【能耗记录】",
            "日期,总用电量(kWh),环北线(kWh),打铁关线(kWh),DIK-1(kWh),DIK-2(kWh),DIK-5(kWh),总用水量(m3),总用气量(m3),环北线读数,打铁关线读数,DIK-1读数,DIK-2读数,DIK-5读数,水表读数,气表读数"
        ]
        for r in rows:
            lines.append(",".join([
                str(r["date"]),
                str(r["elec_usage"] or 0),
                str(r["elec_huanbei_usage"] or 0),
                str(r["elec_datieguan_usage"] or 0),
                str(r["dik1_usage"] or 0),
                str(r["dik2_usage"] or 0),
                str(r["dik5_usage"] or 0),
                str(r["water_usage"] or 0),
                str(r["gas_usage"] or 0),
                str(r["elec_huanbei_raw"] or ""),
                str(r["elec_datieguan_raw"] or ""),
                str(r["dik1_raw"] or ""),
                str(r["dik2_raw"] or ""),
                str(r["dik5_raw"] or ""),
                str(r["water_raw"] or ""),
                str(r["gas_raw"] or ""),
            ]))

        lines += [
            "",
            "【空调开关记录】",
            "日期,时间,设备,状态,操作人,备注"
        ]
        for r in ac_rows:
            lines.append(",".join([
                str(r["date"]), str(r["time"]), str(r["device"]),
                str(r["status"]), str(r["operator"] or ""), str(r["notes"] or "")
            ]))

        lines += [
            "",
            "【锅炉开关记录】",
            "日期,时间,设备,状态,操作人,备注"
        ]
        for r in bl_rows:
            lines.append(",".join([
                str(r["date"]), str(r["time"]), str(r["device"]),
                str(r["status"]), str(r["operator"] or ""), str(r["notes"] or "")
            ]))

        range_str = f"_{s}_{e}" if (s or e) else ""
        fname = f"dashboard_all{range_str}_{_dt3.now().strftime('%Y%m%d_%H%M%S')}.csv"

    return Response("\n".join(lines), mimetype="text/csv",
        headers={"Content-Disposition": f"attachment;filename={fname}"})


if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=5000, debug=False)
