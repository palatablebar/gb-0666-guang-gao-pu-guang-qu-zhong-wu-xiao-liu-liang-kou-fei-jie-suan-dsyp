import hashlib,json,time
from app.config import SAMPLE_DIR
from app.errors import reject
from app.modules.m3_model.service import run as model_run
from app.modules.m7_batches.service import run as batch_run
from app import store
from .rules import validate_options,build_closure,adjudicate

def _stamp():return time.strftime("%Y-%m-%dT%H:%M:%S%z")

def _read(options):
    if "text" in options:
        if not isinstance(options["text"],str):reject("CONTENT","文件内容须为文本")
        return options["text"].encode("utf-8")
    sample=options.get("sample","late")
    if sample not in {"late","dirty","clean","gb18030"}:reject("SAMPLE","样例不存在")
    return (SAMPLE_DIR/(sample+".csv")).read_bytes()

def close_period(options=None):
    """关账：冻结已发布运行的金额与采信曝光，之后永不回写。"""
    options=validate_options(options or {});period=options["period"]
    existing=next((x for x in store.list_closures() if x["period"]==period),None)
    if existing is not None:return existing
    published=batch_run({"sample":options.get("sample","dirty")})
    closure=build_closure(published)
    material=json.dumps({"period":period,"run_id":published["manifest"]["run_id"],"channels":closure["frozen_channels"]},sort_keys=True,ensure_ascii=False,separators=(",",":"))
    body={
        "period":period,"digest":hashlib.sha256(material.encode()).hexdigest(),"created_at":_stamp(),
        "run_id":published["manifest"]["run_id"],
        "frozen_channels":closure["frozen_channels"],
        "frozen_gross":closure["frozen_gross"],"frozen_credit":closure["frozen_credit"],"frozen_net":closure["frozen_net"],
        "frozen_impressions":closure["frozen_impressions"],"already_reversed":closure["already_reversed"],
        "impression_rows":closure["impression_rows"],
    }
    return store.save_closure(body)

def submit_supplement(options=None):
    """补交：同批内容幂等；处理失败不产生新版本，已通过的旧批次保持不变。"""
    options=validate_options(options or {});period=options["period"]
    closure=store.fetch_closure(period)
    prior=store.list_supplements()
    content=_read(options)
    pipeline=model_run({"text":content.decode("utf-8")} if "text" in options else {"sample":options.get("sample","late")})
    verdict=adjudicate(pipeline,closure,period,options["current_period"],prior)
    material=json.dumps({"content":content.hex(),"period":period,"current_period":options["current_period"],"closure_digest":closure["digest"]},sort_keys=True,separators=(",",":"))
    digest=hashlib.sha256(material.encode()).hexdigest()
    body={**verdict,"supplement_id":digest[:16],"digest":digest,"created_at":_stamp(),
          "closure_period":period,"closure_digest":closure["digest"],"run_id":closure["run_id"]}
    return store.save_supplement(body)

def state(selected_id=None):
    closures=store.list_closures();supplements=store.list_supplements()
    selected=None
    if selected_id:selected=store.fetch_supplement(selected_id)
    elif supplements:selected=supplements[0]
    return {"closures":closures,"supplements":supplements,"selected":selected}
