import sqlite3,json
from contextlib import contextmanager
from app.config import data_dir
from app.errors import reject
@contextmanager
def connect():
    d=data_dir();d.mkdir(parents=True,exist_ok=True)
    c=sqlite3.connect(d/"records.sqlite",timeout=20)
    c.row_factory=sqlite3.Row
    c.execute("CREATE TABLE IF NOT EXISTS runs (id TEXT PRIMARY KEY,digest TEXT UNIQUE,body TEXT NOT NULL,revision INTEGER NOT NULL DEFAULT 1,decision TEXT NOT NULL DEFAULT '待复核')")
    c.execute("CREATE TABLE IF NOT EXISTS period_closures (period TEXT PRIMARY KEY,digest TEXT UNIQUE,body TEXT NOT NULL,created_at TEXT NOT NULL,revision INTEGER NOT NULL DEFAULT 1,decision TEXT NOT NULL DEFAULT '待复核')")
    c.execute("CREATE TABLE IF NOT EXISTS supplement_runs (id TEXT PRIMARY KEY,digest TEXT UNIQUE,body TEXT NOT NULL,created_at TEXT NOT NULL,revision INTEGER NOT NULL DEFAULT 1,decision TEXT NOT NULL DEFAULT '待复核')")
    try:
        yield c
        c.commit()
    except Exception:
        c.rollback()
        raise
    finally:
        c.close()
def save(result):
    m=result["manifest"]
    with connect() as c:
        c.execute("INSERT OR IGNORE INTO runs(id,digest,body) VALUES(?,?,?)",(m["run_id"],m["sha256"],json.dumps(result,ensure_ascii=False)))
    return fetch(m["run_id"])
def fetch(run_id):
    with connect() as c:row=c.execute("SELECT * FROM runs WHERE id=?",(run_id,)).fetchone()
    if row is None:reject("NOT_FOUND","运行不存在")
    data=json.loads(row["body"]);data["revision"]=row["revision"];data["decision"]=row["decision"]
    return data
def history():
    with connect() as c:return [dict(x) for x in c.execute("SELECT id,revision,decision FROM runs ORDER BY rowid DESC LIMIT 100")]
def review(run_id,revision,decision):
    if not isinstance(revision,int) or isinstance(revision,bool) or revision<1:reject("VERSION","修订号须为正整数")
    if decision not in ("通过","退回"):reject("DECISION","复核状态无效")
    with connect() as c:
        changed=c.execute("UPDATE runs SET revision=revision+1,decision=? WHERE id=? AND revision=?",(decision,run_id,revision)).rowcount
        if not changed:reject("STALE_VERSION","数据已更新，请重新载入")
    return fetch(run_id)

def _load(row):
    data=json.loads(row["body"]);data["revision"]=row["revision"];data["decision"]=row["decision"];data["created_at"]=row["created_at"]
    return data
def save_closure(body):
    with connect() as c:
        c.execute("INSERT OR IGNORE INTO period_closures(period,digest,body,created_at) VALUES(?,?,?,?)",(body["period"],body["digest"],json.dumps(body,ensure_ascii=False),body["created_at"]))
        row=c.execute("SELECT * FROM period_closures WHERE period=?",(body["period"],)).fetchone()
    return _load(row)
def fetch_closure(period):
    with connect() as c:row=c.execute("SELECT * FROM period_closures WHERE period=?",(period,)).fetchone()
    if row is None:reject("NOT_FOUND","账期未关账")
    return _load(row)
def list_closures():
    with connect() as c:return [_load(x) for x in c.execute("SELECT * FROM period_closures ORDER BY period DESC LIMIT 100")]
def save_supplement(body):
    with connect() as c:
        c.execute("INSERT OR IGNORE INTO supplement_runs(id,digest,body,created_at) VALUES(?,?,?,?)",(body["supplement_id"],body["digest"],json.dumps(body,ensure_ascii=False),body["created_at"]))
        row=c.execute("SELECT * FROM supplement_runs WHERE id=?",(body["supplement_id"],)).fetchone()
    return _load(row)
def fetch_supplement(supplement_id):
    with connect() as c:row=c.execute("SELECT * FROM supplement_runs WHERE id=?",(supplement_id,)).fetchone()
    if row is None:reject("NOT_FOUND","补交批次不存在")
    return _load(row)
def list_supplements():
    with connect() as c:return [_load(x) for x in c.execute("SELECT * FROM supplement_runs ORDER BY rowid DESC LIMIT 100")]
def review_supplement(supplement_id,revision,decision):
    if not isinstance(revision,int) or isinstance(revision,bool) or revision<1:reject("VERSION","修订号须为正整数")
    if decision not in ("通过","退回"):reject("DECISION","复核状态无效")
    with connect() as c:
        changed=c.execute("UPDATE supplement_runs SET revision=revision+1,decision=? WHERE id=? AND revision=?",(decision,supplement_id,revision)).rowcount
        if not changed:reject("STALE_VERSION","数据已更新，请重新载入")
    return fetch_supplement(supplement_id)
