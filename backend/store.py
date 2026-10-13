"""SQLite is the only persistence writer. All service writes use transactions."""
import json, sqlite3, threading
from contextlib import contextmanager
from pathlib import Path
from datetime import datetime, timezone
from uuid import uuid4

def now(): return datetime.now(timezone.utc).isoformat()
def uid(): return str(uuid4())
def dumps(v): return json.dumps(v,ensure_ascii=False,separators=(',',':'))
class DomainError(Exception):
    def __init__(self,code,message,status=400,retryable=False):
        self.code,self.message,self.status,self.retryable=code,message,status,retryable
class Store:
    def __init__(self,data_dir):
        self.path=Path(data_dir).resolve();self.path.mkdir(parents=True,exist_ok=True)
        self.db_path=self.path/'studio.sqlite3';self.lock=threading.RLock()
        self.conn=sqlite3.connect(self.db_path,check_same_thread=False)
        version=self.conn.execute('PRAGMA user_version').fetchone()[0]
        tables={x[0] for x in self.conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
        if version>1 or tables and tables!={'entities'}:
            self.conn.close();raise RuntimeError('Unsupported database schema; restore or migrate explicitly')
        self.conn.execute('PRAGMA journal_mode=WAL');self.conn.execute('PRAGMA foreign_keys=ON')
        self.conn.execute('CREATE TABLE IF NOT EXISTS entities (kind TEXT NOT NULL,id TEXT NOT NULL,project_id TEXT,value TEXT NOT NULL,PRIMARY KEY(kind,id))')
        self.conn.execute('CREATE INDEX IF NOT EXISTS by_project ON entities(kind,project_id)')
        self.conn.execute('PRAGMA user_version=1');self.conn.commit()
        with self.tx():
            if not self.get('profile','owner',False):
                self.put('profile',{'id':'owner','owner_id':'local-owner','display_name':'创作者','language':'zh','default_duration_seconds':30,'default_aspect_ratio':'9:16','default_style':'电影感'})
            for r in self.list('run'):
                if r['status'] in ('queued','running','validating'):
                    r.update(status='interrupted',error={'code':'INTERRUPTED','message':'服务重启，请手动重试','retryable':True},updated_at=now());self.put('run',r)
    @contextmanager
    def tx(self):
        with self.lock:
            try:
                self.conn.execute('BEGIN IMMEDIATE');yield;self.conn.commit()
            except Exception:
                self.conn.rollback();raise
    def get(self,kind,id,required=True):
        with self.lock:
            row=self.conn.execute('SELECT value FROM entities WHERE kind=? AND id=?',(kind,str(id))).fetchone()
        if row:return json.loads(row[0])
        if required:raise DomainError('NOT_FOUND',f'{kind} 不存在',404)
    def list(self,kind,project_id=None):
        with self.lock:
            rows=self.conn.execute('SELECT value FROM entities WHERE kind=?'+(' AND project_id=?' if project_id is not None else '')+' ORDER BY rowid',(kind,project_id) if project_id is not None else (kind,)).fetchall()
        return [json.loads(x[0]) for x in rows]
    def put(self,kind,value):
        self.conn.execute('INSERT INTO entities(kind,id,project_id,value) VALUES(?,?,?,?) ON CONFLICT(kind,id) DO UPDATE SET project_id=excluded.project_id,value=excluded.value',(kind,str(value['id']),value.get('project_id'),dumps(value)))
    def delete(self,kind,id):self.conn.execute('DELETE FROM entities WHERE kind=? AND id=?',(kind,str(id)))
    def project(self,id):return self.get('project',id)
    def match_version(self,p,base):
        if p['current_revision']!=base:raise DomainError('REVISION_CONFLICT','当前版本已改变，请刷新并比较',409)
    def write_revision(self,p,document,source,brief=None,title=None):
        parent=p['current_revision'];version=parent+1
        p.update(current_revision=version,document=document,updated_at=now())
        if brief is not None:p['brief']=brief
        if title is not None:p['title']=title
        self.put('project',p)
        self.put('revision',{'id':f"{p['id']}:{version}",'project_id':p['id'],'version':version,'parent_version':parent,'source':source,'document':document,'brief':p['brief'],'title':p['title'],'created_at':now()})
        return p
