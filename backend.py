import os, sqlite3, uuid, threading
from datetime import datetime, timezone
from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
import requests, shutil

DB=os.getenv('CONTACT_DB','contacts.db')
UPLOAD_DIR=os.getenv('UPLOAD_DIR',os.path.join(os.path.dirname(__file__),'uploads'))
PUBLIC_BASE_URL=os.getenv('PUBLIC_BASE_URL','http://127.0.0.1:8931').rstrip('/')
os.makedirs(UPLOAD_DIR,exist_ok=True)
FEISHU=os.getenv('FEISHU_WEBHOOK','')
WECom=os.getenv('WECOM_WEBHOOK','')
app=FastAPI(title='河狸官网联系接口')
app.add_middleware(CORSMiddleware,allow_origins=['*'],allow_methods=['POST','GET'],allow_headers=['*'])
HTML_FILE=os.path.join(os.path.dirname(__file__),'index.html')

@app.get('/',include_in_schema=False)
def homepage():
    return FileResponse(HTML_FILE,media_type='text/html')

@app.get('/api/files/{filename}',include_in_schema=False)
def download_file(filename:str):
    safe=os.path.basename(filename)
    path=os.path.join(UPLOAD_DIR,safe)
    if not os.path.isfile(path): raise HTTPException(404,'文件不存在')
    return FileResponse(path,filename=safe)

@app.get('/api/health')
def health():
    return {'ok':True,'feishu_enabled':bool(FEISHU),'wecom_enabled':bool(WECom),'database':DB}

class Contact(BaseModel):
    identity:str='其他'; province:str='未填写'; demand_type:str='其他'
    description:str=''; contact:str=Field(min_length=2); source:str='官网联系页'; asset_type:str=''

def db():
    c=sqlite3.connect(DB); c.execute('''CREATE TABLE IF NOT EXISTS contacts(
      id INTEGER PRIMARY KEY AUTOINCREMENT, message_id TEXT UNIQUE, identity TEXT, province TEXT,
      demand_type TEXT, description TEXT, contact TEXT, source TEXT, asset_type TEXT,
      status TEXT DEFAULT 'pending', feishu_status TEXT DEFAULT 'pending', wecom_status TEXT DEFAULT 'pending',
      created_at TEXT, last_error TEXT)'''); c.commit(); return c

def format_msg(x):
    return f'''【河狸官网新需求】\n消息编号：{x["message_id"]}\n身份：{x["identity"]}\n省份：{x["province"]}\n需求类型：{x["demand_type"]}\n资产类型：{x["asset_type"] or "未填写"}\n联系方式：{x["contact"]}\n来源：{x["source"]}\n\n问题描述：\n{x["description"] or "未填写"}'''

def push(row):
    text=format_msg(row); results={}
    for channel,url in [('feishu',FEISHU),('wecom',WECom)]:
        if not url: results[channel]='skipped'; continue
        body={'msg_type':'text','content':{'text':text}} if channel=='feishu' else {'msgtype':'text','text':{'content':text}}
        try:
            r=requests.post(url,json=body,timeout=8); results[channel]='success' if r.ok else 'failed'
        except Exception as e: results[channel]='failed'
    c=db(); status='sent' if all(v in ('success','skipped') for v in results.values()) else 'partial'
    c.execute('UPDATE contacts SET status=?,feishu_status=?,wecom_status=? WHERE message_id=?',(status,results['feishu'],results['wecom'],row['message_id'])); c.commit(); c.close()

@app.on_event('startup')
def startup(): db().close()

@app.post('/api/contact')
async def create(identity:str=Form('其他'),province:str=Form('未填写'),demand_type:str=Form('其他'),description:str=Form(''),contact:str=Form(...),source:str=Form('官网联系页'),asset_type:str=Form(''),files:list[UploadFile]=File(default=[])):
    if not contact.strip(): raise HTTPException(400,'联系方式不能为空')
    mid='MSG-'+datetime.now().strftime('%Y%m%d')+'-'+uuid.uuid4().hex[:8].upper()
    now=datetime.now(timezone.utc).isoformat(); c=db()
    c.execute('INSERT INTO contacts(message_id,identity,province,demand_type,description,contact,source,asset_type,created_at) VALUES(?,?,?,?,?,?,?,?,?)',(mid,identity,province,demand_type,description,contact,source,asset_type,now)); c.commit(); c.close()
    saved=[]
    for f in files or []:
        if not f.filename: continue
        safe=os.path.basename(f.filename).replace('..','_')
        dest=os.path.join(UPLOAD_DIR,mid+'_'+safe)
        with open(dest,'wb') as out: shutil.copyfileobj(f.file,out)
        saved.append(safe)
    row={'message_id':mid,'identity':identity,'province':province,'demand_type':demand_type,'description':description,'contact':contact,'source':source,'asset_type':asset_type}
    if saved:
        links='\\n'.join(f'{name}：{PUBLIC_BASE_URL}/api/files/{name}' for name in saved)
        row['description'] += '\\n附件下载：\\n' + links
    threading.Thread(target=push,args=(row,),daemon=True).start()
    return {'success':True,'message_id':mid}

@app.get('/api/contact/{message_id}')
def get_contact(message_id:str):
    c=db(); c.row_factory=sqlite3.Row; row=c.execute('SELECT * FROM contacts WHERE message_id=?',(message_id,)).fetchone(); c.close()
    if not row: raise HTTPException(404,'消息不存在')
    return dict(row)

