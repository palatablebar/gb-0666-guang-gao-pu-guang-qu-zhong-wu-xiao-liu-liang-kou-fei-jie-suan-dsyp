from fastapi.testclient import TestClient
from app.main import app
from app.config import MODULES

def test_pages_and_api():
    with TestClient(app) as c:
        for slug,_ in MODULES:
            assert c.get("/"+slug).status_code==200
            assert c.get("/api/"+slug).status_code==200
def test_export_and_no_loss_id():
    with TestClient(app) as c:
        data=c.post("/api/runs",json={"sample":"dirty"}).json()
        assert data["rows"][0]["event_id"]=="9007199254740993000"
        assert "BOT" in c.get('/api/runs/'+data["manifest"]["run_id"]+'/evidence.csv').text
def test_wrong_csv():
    with TestClient(app) as c:assert c.post("/api/runs",json={"text":"bad,header\n1,2"}).status_code==422
def test_period_close_and_supplement_flow():
    with TestClient(app) as c:
        assert c.get("/periods").status_code==200
        closed=c.post("/api/periods/close",json={"period":"2026-11","current_period":"2026-12"}).json()
        assert closed["frozen_net"]=="0.69"
        s=c.post("/api/periods/supplements",json={"sample":"late","period":"2026-11","current_period":"2026-12"}).json()
        assert s["totals"]["payable"]=="0.01" and s["totals"]["late_delta"]=="0.01"
        sid=s["supplement_id"]
        page=c.get("/periods?supplement_id="+sid).text
        assert "本次正式应付" in page and "差额来源明细" in page and sid in page
        # 同批重试幂等，不新增待复核版本
        again=c.post("/api/periods/supplements",json={"sample":"late","period":"2026-11","current_period":"2026-12"}).json()
        assert again["supplement_id"]==sid and again["revision"]==1
        # 补交失败保留旧版
        assert c.post("/api/periods/supplements",json={"text":"bad,header\n1,2","period":"2026-11","current_period":"2026-12"}).status_code==422
        kept=c.get("/api/periods/supplements/"+sid).json()["selected"]
        assert kept["revision"]==1 and kept["decision"]=="待复核"
        # 复核与陈旧版本
        assert c.post("/api/periods/supplements/"+sid+"/review",json={"revision":1,"decision":"通过"}).status_code==200
        assert c.post("/api/periods/supplements/"+sid+"/review",json={"revision":1,"decision":"退回"}).status_code==409
