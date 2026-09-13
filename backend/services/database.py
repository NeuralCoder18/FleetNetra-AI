import sqlite3, json, os
from datetime import datetime, timezone

DB_PATH=os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'data', 'urban.db'))

def conn():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    c=sqlite3.connect(DB_PATH)
    c.row_factory=sqlite3.Row
    return c

def init_db():
    c=conn()
    c.executescript('''
    CREATE TABLE IF NOT EXISTS detections(
      id TEXT PRIMARY KEY,event_type TEXT,road TEXT,bus TEXT,camera TEXT,confidence REAL,
      lat REAL,lng REAL,severity TEXT,time TEXT,timestamp TEXT,bbox TEXT,evidence_url TEXT,source TEXT,status TEXT DEFAULT 'DETECTED'
    );
    CREATE TABLE IF NOT EXISTS telemetry(
      bus_id TEXT PRIMARY KEY,lat REAL,lng REAL,speed_kmh REAL,route TEXT,status TEXT,updated_at TEXT
    );
    CREATE TABLE IF NOT EXISTS complaints(
      id TEXT PRIMARY KEY,user_id TEXT,issue_type TEXT,location TEXT,description TEXT,lat REAL,lng REAL,status TEXT,created_at TEXT
    );
    CREATE TABLE IF NOT EXISTS assignments(
      id TEXT PRIMARY KEY,event_id TEXT,inspector_id TEXT,status TEXT,remarks TEXT,updated_at TEXT,target_type TEXT DEFAULT 'DETECTION'
    );
    CREATE TABLE IF NOT EXISTS community_ideas(
      id TEXT PRIMARY KEY,user_id TEXT,title TEXT,category TEXT,description TEXT,votes INTEGER DEFAULT 0,created_at TEXT,complaint_id TEXT
    );
    CREATE TABLE IF NOT EXISTS complaint_evidence(
      complaint_id TEXT PRIMARY KEY,evidence_url TEXT
    );
    ''')
    # Safe migration for databases created by the earlier prototype.
    cols={r['name'] for r in c.execute('PRAGMA table_info(detections)').fetchall()}
    if 'status' not in cols: c.execute("ALTER TABLE detections ADD COLUMN status TEXT DEFAULT 'DETECTED'")
    cols={r['name'] for r in c.execute('PRAGMA table_info(complaints)').fetchall()}
    if 'user_id' not in cols: c.execute("ALTER TABLE complaints ADD COLUMN user_id TEXT DEFAULT 'legacy-citizen'")
    cols={r['name'] for r in c.execute('PRAGMA table_info(assignments)').fetchall()}
    if 'target_type' not in cols: c.execute("ALTER TABLE assignments ADD COLUMN target_type TEXT DEFAULT 'DETECTION'")
    cols={r['name'] for r in c.execute('PRAGMA table_info(community_ideas)').fetchall()}
    if 'complaint_id' not in cols: c.execute("ALTER TABLE community_ideas ADD COLUMN complaint_id TEXT")
    c.commit(); c.close()

def insert_detection(e):
    c=conn(); c.execute("""INSERT OR REPLACE INTO detections VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
      (e['id'],e['event_type'],e['road'],e['bus'],e['camera'],e['confidence'],e['lat'],e['lng'],e['severity'],e['time'],e['timestamp'],json.dumps(e['bbox']),e['evidence_url'],e['source'],e.get('status','DETECTED')))
    c.commit(); c.close()

def list_detections(limit=100, status=None):
    c=conn()
    if status:
        rows=c.execute("SELECT * FROM detections WHERE status=? ORDER BY timestamp DESC LIMIT ?",(status,limit)).fetchall()
    else:
        rows=c.execute("SELECT * FROM detections ORDER BY timestamp DESC LIMIT ?",(limit,)).fetchall()
    c.close(); out=[]
    for r in rows:
        d=dict(r); d['bbox']=json.loads(d['bbox']); out.append(d)
    return out

def update_detection_status(event_id,status):
    c=conn(); c.execute("UPDATE detections SET status=? WHERE id=?",(status,event_id)); c.commit(); c.close()

def update_complaint_status(complaint_id,status):
    c=conn(); c.execute("UPDATE complaints SET status=? WHERE id=?",(status,complaint_id)); c.commit(); c.close()

def insert_telemetry(t):
    c=conn(); c.execute("INSERT OR REPLACE INTO telemetry VALUES(?,?,?,?,?,?,?)",
      (t['bus_id'],t['lat'],t['lng'],t.get('speed_kmh',0),t.get('route','Unknown'),t.get('status','ACTIVE'),datetime.now(timezone.utc).isoformat()))
    c.commit(); c.close()

def list_telemetry():
    c=conn(); rows=c.execute("SELECT * FROM telemetry ORDER BY bus_id").fetchall(); c.close(); return [dict(r) for r in rows]

def insert_complaint(x):
    c=conn(); c.execute("INSERT INTO complaints VALUES(?,?,?,?,?,?,?,?,?)",
      (x['id'],x.get('user_id','citizen'),x['issue_type'],x['location'],x.get('description',''),x.get('lat'),x.get('lng'),x['status'],x['created_at']))
    c.commit(); c.close()

def list_complaints(user_id=None):
    c=conn()
    if user_id:
        rows=c.execute("SELECT * FROM complaints WHERE user_id=? ORDER BY created_at DESC",(user_id,)).fetchall()
    else:
        rows=c.execute("SELECT * FROM complaints ORDER BY created_at DESC").fetchall()
    c.close(); return [dict(r) for r in rows]

def insert_assignment(a):
    c=conn(); c.execute("INSERT OR REPLACE INTO assignments(id,event_id,inspector_id,status,remarks,updated_at,target_type) VALUES(?,?,?,?,?,?,?)",
      (a['id'],a['event_id'],a['inspector_id'],a['status'],a.get('remarks',''),a['updated_at'],a.get('target_type','DETECTION')))
    c.commit(); c.close()

def list_assigned_detections(inspector_id):
    c=conn()
    rows=c.execute("""SELECT d.* FROM detections d JOIN assignments a ON a.event_id=d.id WHERE a.inspector_id=? ORDER BY d.timestamp DESC""",(inspector_id,)).fetchall()
    c.close(); out=[]
    for r in rows:
        d=dict(r); d['bbox']=json.loads(d['bbox']); out.append(d)
    return out

def list_assignments(inspector_id=None):
    c=conn()
    where=''
    params=()
    if inspector_id:
        where='WHERE a.inspector_id=?'
        params=(inspector_id,)
    rows=c.execute(f"""SELECT a.*,
        COALESCE(d.road, c.location) AS road, COALESCE(d.bus, 'CITIZEN') AS bus, COALESCE(d.camera, 'CITIZEN REPORT') AS camera,
        COALESCE(d.confidence, 0) AS confidence, COALESCE(d.lat, c.lat) AS lat, COALESCE(d.lng, c.lng) AS lng,
        COALESCE(d.severity, CASE WHEN c.issue_type LIKE '%Pothole%' THEN 'HIGH' ELSE 'MEDIUM' END) AS severity,
        COALESCE(d.time, substr(c.created_at,12,8)) AS time, COALESCE(d.evidence_url, ce.evidence_url) AS evidence_url,
        COALESCE(d.status, c.status) AS event_status, COALESCE(d.event_type, c.issue_type) AS case_type,
        c.issue_type, c.description AS complaint_description
        FROM assignments a
        LEFT JOIN detections d ON a.event_id=d.id
        LEFT JOIN complaints c ON a.event_id=c.id
        LEFT JOIN complaint_evidence ce ON a.event_id=ce.complaint_id
        {where} ORDER BY a.updated_at DESC""",params).fetchall()
    c.close(); return [dict(r) for r in rows]

def tick_simulated_telemetry():
    import math, time
    c=conn(); rows=c.execute("SELECT * FROM telemetry").fetchall(); now=time.time()
    for i,r in enumerate(rows):
        lat=r['lat'] + math.sin(now/18+i)*0.00008
        lng=r['lng'] + math.cos(now/20+i)*0.00008
        c.execute("UPDATE telemetry SET lat=?,lng=?,updated_at=? WHERE bus_id=?",
                  (lat,lng,datetime.now(timezone.utc).isoformat(),r['bus_id']))
    c.commit(); c.close()


def insert_idea(x):
    c=conn(); c.execute("INSERT INTO community_ideas(id,user_id,title,category,description,votes,created_at,complaint_id) VALUES(?,?,?,?,?,?,?,?)",(x['id'],x['user_id'],x['title'],x['category'],x['description'],x.get('votes',0),x['created_at'],x.get('complaint_id'))); c.commit(); c.close()

def list_ideas():
    c=conn(); rows=c.execute("SELECT * FROM community_ideas ORDER BY votes DESC, created_at DESC").fetchall(); c.close(); return [dict(r) for r in rows]

def vote_idea(idea_id):
    c=conn(); c.execute("UPDATE community_ideas SET votes=votes+1 WHERE id=?",(idea_id,)); changed=c.total_changes; c.commit(); c.close(); return changed
