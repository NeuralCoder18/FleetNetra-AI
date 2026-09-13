from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Header, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from services.detector import detect_potholes
from services.database import init_db, insert_detection, list_detections, list_assigned_detections, insert_telemetry, list_telemetry, insert_complaint, list_complaints, tick_simulated_telemetry, insert_assignment, list_assignments, update_detection_status, update_complaint_status, insert_idea, list_ideas, vote_idea
from services.reporter import generate_report
import os, uuid, json, hmac, hashlib, base64
from datetime import datetime, timezone

app=FastAPI(title='FleetNetra AI API',version='2.0.0')
app.add_middleware(CORSMiddleware,allow_origins=['*'],allow_credentials=True,allow_methods=['*'],allow_headers=['*'])
os.makedirs('evidence',exist_ok=True); os.makedirs('data',exist_ok=True)
app.mount('/evidence',StaticFiles(directory='evidence'),name='evidence')
init_db()

@app.on_event('startup')
def warm_edge_model():
    # Load the YOLO model once when the backend starts so the first bus detection
    # does not pay the model-loading/download cost. Failure here is non-fatal;
    # detection will retry lazily on the first request.
    try:
        from services.detector import get_model
        get_model()
    except Exception as exc:
        print(f'[FleetNetra] Edge model warmup deferred: {exc}')

SECRET=os.getenv('AUTH_SECRET','hackathon-demo-secret-change-me').encode()
USERS={
  'authority': {'password':'authority123','role':'AUTHORITY','name':'Command Authority','initials':'CA'},
  'inspector': {'password':'inspector123','role':'INSPECTOR','name':'Regional Road Officer','initials':'RO'},
  'citizen': {'password':'citizen123','role':'CITIZEN','name':'Citizen User','initials':'CU'},
}

def make_token(username,role):
    payload=json.dumps({'u':username,'r':role},separators=(',',':')).encode()
    body=base64.urlsafe_b64encode(payload).decode().rstrip('=')
    sig=hmac.new(SECRET,body.encode(),hashlib.sha256).hexdigest()
    return body+'.'+sig

def current_user(authorization: str|None = Header(default=None)):
    if not authorization or not authorization.startswith('Bearer '): raise HTTPException(401,'Authentication required.')
    token=authorization[7:]
    try:
        body,sig=token.split('.',1)
        expected=hmac.new(SECRET,body.encode(),hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig,expected): raise ValueError()
        payload=json.loads(base64.urlsafe_b64decode(body+'='*((4-len(body)%4)%4)))
        if payload.get('u') not in USERS: raise ValueError()
        return payload
    except Exception: raise HTTPException(401,'Invalid or expired session.')

def require(*roles):
    def dep(user=Depends(current_user)):
        if user['r'] not in roles: raise HTTPException(403,'This workspace is not available for your role.')
        return user
    return dep

class Login(BaseModel): username:str; password:str
class Telemetry(BaseModel): bus_id:str; lat:float; lng:float; speed_kmh:float=0; route:str='Unknown'; status:str='ACTIVE'
class Complaint(BaseModel): issue_type:str; location:str; description:str=''; lat:float|None=None; lng:float|None=None
class Assignment(BaseModel): event_id:str; inspector_id:str='inspector'
class Verify(BaseModel): event_id:str; status:str; remarks:str=''

@app.get('/api/health')
def health(): return {'status':'ok','model':'YOLOv8 edge pothole detector','database':'SQLite','auth':'RBAC','time':datetime.now(timezone.utc).isoformat()}

@app.post('/api/auth/login')
def login(data:Login):
    u=USERS.get(data.username)
    if not u or data.password!=u['password']: raise HTTPException(401,'Invalid demo credentials.')
    return {'token':make_token(data.username,u['role']),'user':{'username':data.username,'role':u['role'],'name':u['name'],'initials':u['initials']}}

@app.get('/api/auth/me')
def me(user=Depends(current_user)): return {'username':user['u'],'role':user['r'],'name':USERS[user['u']]['name'],'initials':USERS[user['u']]['initials']}

@app.post('/api/edge/detect')
async def edge_detect(file:UploadFile=File(...),bus_id:str=Form('DEMO-BUS-01'),camera:str=Form('FRONT-01'),lat:float=Form(26.8467),lng:float=Form(80.9462),road:str=Form('Lucknow District'),x_device_key:str|None=Header(default=None)):
    if x_device_key != os.getenv('DEVICE_API_KEY','urbanai-bus-device-demo'): raise HTTPException(401,'Invalid bus device key.')
    if not file.content_type or not file.content_type.startswith('image/'): raise HTTPException(400,'Please upload an image.')
    raw=await file.read()
    if len(raw)>15*1024*1024: raise HTTPException(413,'Image too large. Maximum 15 MB.')
    try: result=detect_potholes(raw,file.filename or 'frame.jpg')
    except Exception as e: raise HTTPException(500,f'Model inference failed: {e}')
    created=[]
    for d in result['detections']:
        event_id='P-'+uuid.uuid4().hex[:8].upper(); area=max(0,d['bbox'][2]-d['bbox'][0])*max(0,d['bbox'][3]-d['bbox'][1]); frame_area=max(1,result['width']*result['height'])
        severity='HIGH' if area/frame_area>0.08 or d['confidence']>=0.88 else ('MEDIUM' if d['confidence']>=0.60 else 'LOW')
        event={'id':event_id,'event_type':'POTHOLE','road':road,'bus':bus_id,'camera':camera,'confidence':round(d['confidence']*100,2),'lat':lat,'lng':lng,'severity':severity,'time':datetime.now().strftime('%H:%M:%S'),'timestamp':datetime.now(timezone.utc).isoformat(),'bbox':d['bbox'],'evidence_url':f"/evidence/{os.path.basename(result['annotated_path'])}",'source':'EDGE_AI','status':'DETECTED'}
        insert_detection(event); created.append(event)
    return {'model':'peterhdd/pothole-detection-yolov8','detections':created,'annotated_url':f"/evidence/{os.path.basename(result['annotated_path'])}",'image_width':result['width'],'image_height':result['height'],'inference_ms':result['inference_ms']}

@app.get('/api/detections')
def detections(user=Depends(require('AUTHORITY','INSPECTOR'))):
    rows=list_detections(200) if user['r']=='AUTHORITY' else list_assigned_detections(user['u'])
    assignments=list_assignments()
    latest={}
    for a in assignments:
        if a.get('target_type','DETECTION')=='DETECTION':
            latest[a['event_id']]=a
    for d in rows:
        a=latest.get(d['id'])
        if a:
            d['assigned_officer']='Regional Road Officer'
            d['assignment_status']=a['status']
    return rows

@app.post('/api/telemetry')
def telemetry(t:Telemetry,x_device_key:str|None=Header(default=None)):
    if x_device_key != os.getenv('DEVICE_API_KEY','urbanai-bus-device-demo'): raise HTTPException(401,'Invalid bus device key.')
    insert_telemetry(t.model_dump()); return {'ok':True}

@app.get('/api/fleet/live')
def fleet_live(user=Depends(require('AUTHORITY'))):
    tick_simulated_telemetry(); return list_telemetry()

@app.post('/api/community')
async def community(issue_type:str=Form(...),location:str=Form(...),description:str=Form(''),file:UploadFile|None=File(default=None),user=Depends(require('CITIZEN'))):
    if not location.strip(): raise HTTPException(400,'Location is required.')
    evidence_url=None
    if file:
        if not file.content_type or file.content_type not in {'image/jpeg','image/png','image/webp'}: raise HTTPException(400,'Evidence must be JPG, PNG or WEBP.')
        raw=await file.read()
        if len(raw)>10*1024*1024: raise HTTPException(413,'Evidence image is too large. Maximum 10 MB.')
        ext={'image/jpeg':'.jpg','image/png':'.png','image/webp':'.webp'}[file.content_type]
        name='community-'+uuid.uuid4().hex+ext
        with open(os.path.join('evidence',name),'wb') as out: out.write(raw)
        evidence_url=f'/evidence/{name}'
    cid='CMP-'+uuid.uuid4().hex[:7].upper()
    insert_complaint({'id':cid,'user_id':user['u'],'issue_type':issue_type,'location':location.strip(),'description':description,'lat':None,'lng':None,'status':'SUBMITTED','created_at':datetime.now(timezone.utc).isoformat()})
    # Keep evidence attached to the complaint without changing the existing schema shape.
    if evidence_url:
        import sqlite3
        c=sqlite3.connect(os.path.abspath(os.path.join(os.path.dirname(__file__),'data','urban.db')))
        c.execute('CREATE TABLE IF NOT EXISTS complaint_evidence (complaint_id TEXT PRIMARY KEY,evidence_url TEXT)')
        c.execute('INSERT OR REPLACE INTO complaint_evidence VALUES(?,?)',(cid,evidence_url)); c.commit(); c.close()
    return {'ok':True,'id':cid,'evidence_url':evidence_url}

@app.get('/api/community')
def community_list(user=Depends(current_user)):
    rows=list_complaints() if user['r'] in ('CITIZEN','AUTHORITY','INSPECTOR') else None
    if rows is None: raise HTTPException(403,'Forbidden')
    try:
        import sqlite3
        c=sqlite3.connect(os.path.abspath(os.path.join(os.path.dirname(__file__),'data','urban.db'))); c.row_factory=sqlite3.Row
        ev={r['complaint_id']:r['evidence_url'] for r in c.execute('SELECT complaint_id,evidence_url FROM complaint_evidence').fetchall()}; c.close()
        assignments_by_case={}
        for a in list_assignments():
            if a.get('target_type')=='CITIZEN_REPORT':
                assignments_by_case[a['event_id']]=a
        for row in rows:
            row['evidence_url']=ev.get(row['id'])
            a=assignments_by_case.get(row['id'])
            if a:
                row['assigned_officer']='Regional Road Officer'
                # The complaint status is the source of truth; expose the assignment too.
                row['assignment_status']=a['status']
    except Exception: pass
    return rows

@app.get('/api/community/ideas')
def community_ideas(user=Depends(current_user)):
    if user['r'] not in ('CITIZEN','AUTHORITY','INSPECTOR'): raise HTTPException(403,'Forbidden')
    return list_ideas()

class Idea(BaseModel): title:str; category:str='Road safety'; description:str; complaint_id:str|None=None

@app.post('/api/community/ideas')
def create_idea(data:Idea,user=Depends(require('CITIZEN'))):
    item={'id':'IDEA-'+uuid.uuid4().hex[:7].upper(),'user_id':user['u'],**data.model_dump(),'votes':0,'created_at':datetime.now(timezone.utc).isoformat()}
    insert_idea(item); return item

@app.post('/api/community/ideas/{idea_id}/vote')
def support_idea(idea_id:str,user=Depends(current_user)):
    if user['r'] not in ('CITIZEN','AUTHORITY','INSPECTOR'): raise HTTPException(403,'Forbidden')
    if vote_idea(idea_id)==0: raise HTTPException(404,'Solution not found.')
    return {'ok':True,'id':idea_id}

@app.post('/api/assign')
def assign(a:Assignment,user=Depends(require('AUTHORITY'))):
    is_detection=any(d['id']==a.event_id for d in list_detections(500))
    is_complaint=any(c['id']==a.event_id for c in list_complaints())
    if not is_detection and not is_complaint: raise HTTPException(404,'Registered case not found.')
    existing=[x for x in list_assignments() if x['event_id']==a.event_id and x['status'] not in {'RESOLVED','REJECTED'}]
    if existing:
        return {**existing[0],'regional_officer':'Regional Road Officer'}
    target='DETECTION' if is_detection else 'CITIZEN_REPORT'
    x={'id':'A-'+uuid.uuid4().hex[:8].upper(),'event_id':a.event_id,'inspector_id':a.inspector_id,'status':'ASSIGNED','remarks':'Assigned by Traffic Authority','updated_at':datetime.now(timezone.utc).isoformat(),'target_type':target}
    insert_assignment(x)
    if is_detection: update_detection_status(a.event_id,'ASSIGNED')
    else: update_complaint_status(a.event_id,'ASSIGNED')
    return {**x,'regional_officer':'Regional Road Officer'}

@app.get('/api/assignments')
def assignments(user=Depends(current_user)):
    if user['r']=='AUTHORITY': return [{**x,'regional_officer':'Regional Road Officer'} for x in list_assignments()]
    if user['r']=='INSPECTOR': return [{**x,'regional_officer':'Regional Road Officer'} for x in list_assignments(user['u'])]
    raise HTTPException(403,'Forbidden')

def sync_related_detection_status(event_id: str, status: str):
    """For a clustered pothole case, keep all close observations at the same lifecycle stage."""
    import sqlite3, math
    rows=list_detections(500)
    target=next((d for d in rows if d['id']==event_id), None)
    if not target:
        return
    for d in rows:
        if d['road'] != target['road']:
            continue
        # Approximate distance in metres; good enough for the prototype cluster radius.
        dy=(d['lat']-target['lat'])*111_000
        dx=(d['lng']-target['lng'])*111_000*math.cos(math.radians(target['lat']))
        distance=(dx*dx+dy*dy)**0.5
        try:
            from datetime import datetime
            t1=datetime.fromisoformat(str(target['timestamp']).replace('Z','+00:00'))
            t2=datetime.fromisoformat(str(d['timestamp']).replace('Z','+00:00'))
            time_ok=abs((t1-t2).total_seconds()) <= 45*60
        except Exception:
            time_ok=True
        if distance <= 180 and time_ok:
            update_detection_status(d['id'], status)

@app.post('/api/assignments/verify')
def verify(v:Verify,user=Depends(require('INSPECTOR','AUTHORITY'))):
    status=v.status.upper()
    if status not in {'VERIFIED','REJECTED','WORK_INITIATED','RESOLVED'}: raise HTTPException(400,'Invalid workflow status.')
    rows=list_assignments(user['u'] if user['r']=='INSPECTOR' else None)
    matches=[a for a in rows if a['event_id']==v.event_id]
    if user['r']=='INSPECTOR' and not matches: raise HTTPException(403,'This case is not assigned to you.')
    if not matches:
        if not any(d['id']==v.event_id for d in list_detections(500)) and not any(c['id']==v.event_id for c in list_complaints()):
            raise HTTPException(404,'Registered case not found.')
    target=matches[0]['target_type'] if matches else ('DETECTION' if any(d['id']==v.event_id for d in list_detections(500)) else 'CITIZEN_REPORT')
    if target=='CITIZEN_REPORT':
        update_complaint_status(v.event_id,status)
    else:
        sync_related_detection_status(v.event_id,status)
    if matches:
        # Update the assignment row itself so both Authority and Officer see the same state.
        for a in matches:
            insert_assignment({'id':a['id'],'event_id':a['event_id'],'inspector_id':a['inspector_id'],'status':status,'remarks':v.remarks,'updated_at':datetime.now(timezone.utc).isoformat(),'target_type':target})
    return {'ok':True,'event_id':v.event_id,'status':status,'target_type':target}

@app.post('/api/reports/generate')
def report(user=Depends(require('AUTHORITY'))):
    data={'detections':list_detections(200),'fleet':list_telemetry(),'community':list_complaints(),'assignments':list_assignments()}
    return {'report':generate_report(data),'generated_at':datetime.now(timezone.utc).isoformat()}
