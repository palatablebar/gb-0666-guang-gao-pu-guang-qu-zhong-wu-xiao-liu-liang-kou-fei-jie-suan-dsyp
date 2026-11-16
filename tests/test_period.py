import pytest
from app.errors import DomainError
from app.modules.m8_period import service
from app.store import fetch,list_supplements,list_closures,review_supplement,fetch_supplement

CLOSE={"period":"2026-11","current_period":"2026-12"}
LATE={"sample":"late",**CLOSE}

@pytest.fixture
def closed():
    return service.close_period(CLOSE)

def test_closure_freezes_published_amounts(closed):
    assert closed["period"]=="2026-11"
    assert closed["frozen_net"]=="0.69"
    by={x["channel"]:x for x in closed["frozen_channels"]}
    assert by["DSP-A"]["frozen_net"]=="0.19" and by["DSP-B"]["frozen_net"]=="0.34" and by["DSP-C"]["frozen_net"]=="0.16"
    assert "9007199254740993000" in closed["frozen_impressions"]

def test_closure_idempotent(closed):
    again=service.close_period(CLOSE)
    assert again["digest"]==closed["digest"] and len(list_closures())==1

def test_delta_borne_by_current_period(closed):
    s=service.submit_supplement(LATE)
    a=next(x for x in s["channels"] if x["channel"]=="DSP-A")
    # 迟到曝光 2 条 0.03，迟到冲销 1 条 0.02，差额 0.01 计入本期，原账冻结值不变
    assert a["frozen_net"]=="0.19" and a["late_gross"]=="0.03" and a["late_credit"]=="0.02"
    assert a["late_delta"]=="0.01" and a["payable"]=="0.01"
    assert s["totals"]["frozen_net"]=="0.69"
    assert s["totals"]["late_delta"]=="0.01" and s["totals"]["payable"]=="0.01"
    assert s["amount_ok"] and s["count_ok"]
    # 原发布运行金额未被回写
    assert fetch(closed["run_id"])["reconciliation"]["net"]=="0.69"

def test_sources_trace_every_delta(closed):
    s=service.submit_supplement(LATE)
    kinds={x["kind"] for x in s["sources"]}
    assert {"迟到曝光","迟到冲销","本期曝光","本期冲销"}<=kinds
    reversal=next(x for x in s["sources"] if x["kind"]=="迟到冲销")
    assert reversal["ref"]=="9007199254740993001" and reversal["phase"]=="late"

def test_illegal_records_quarantined_not_lost(closed):
    s=service.submit_supplement(LATE)
    codes={q["code"] for q in s["quarantine"]}
    # 重复冲销、无效引用、对关账期重复补报
    assert {"OVER_REVERSE","REFERENCE","LATE_DUPLICATE"}<=codes
    assert {v["code"] for v in s["invalid"]}=={"BOT"}
    assert s["count_ok"] is True

def test_idempotent_same_batch_single_pending(closed):
    a=service.submit_supplement(LATE);b=service.submit_supplement(LATE)
    assert a["supplement_id"]==b["supplement_id"] and len(list_supplements())==1
    assert a["revision"]==1 and a["decision"]=="待复核"

def test_failure_keeps_old_version_and_no_new_row(closed):
    a=service.submit_supplement(LATE)
    before=len(list_supplements())
    with pytest.raises(DomainError):
        service.submit_supplement({"text":"bad,header\n1,2",**CLOSE})
    rows=list_supplements()
    assert len(rows)==before
    kept=fetch_supplement(a["supplement_id"])
    assert kept["revision"]==1 and kept["decision"]=="待复核"

def test_retry_after_review_does_not_reset_or_duplicate(closed):
    a=service.submit_supplement(LATE)
    reviewed=review_supplement(a["supplement_id"],1,"通过")
    assert reviewed["revision"]==2 and reviewed["decision"]=="通过"
    again=service.submit_supplement(LATE)
    assert again["supplement_id"]==a["supplement_id"] and len(list_supplements())==1
    assert again["revision"]==2 and again["decision"]=="通过"

def test_stale_review_rejected(closed):
    a=service.submit_supplement(LATE)
    review_supplement(a["supplement_id"],1,"通过")
    with pytest.raises(DomainError):review_supplement(a["supplement_id"],1,"退回")

def test_cross_batch_over_reverse_and_duplicate(closed):
    service.submit_supplement(LATE)
    second=service.submit_supplement({"text":"""event_id,at,channel,user_id,ip,kind,ref,bot
LATE-IMP-1,2026-11-05T09:00:00+08:00,DSP-A,U101,192.0.2.20,impression,,0
LATE-REV-AGAIN,2026-11-08T12:00:00+08:00,DSP-A,U002,192.0.2.20,reversal,9007199254740993001,0
""",**CLOSE})
    assert {q["code"] for q in second["quarantine"]}>={"LATE_DUPLICATE","OVER_REVERSE"}
    assert second["totals"]["late_delta"]=="0.00"
    assert len(list_supplements())==2

def test_supplement_requires_closure():
    with pytest.raises(DomainError):service.submit_supplement({"sample":"late","period":"2026-09","current_period":"2026-12"})

def test_period_validation():
    with pytest.raises(DomainError):service.close_period({"period":"2026-13","current_period":"2026-12"})
    with pytest.raises(DomainError):service.close_period({"period":"2026-11","current_period":"2026-11"})

def test_text_and_sample_share_digest(closed):
    a=service.submit_supplement(LATE)
    from app.config import SAMPLE_DIR
    text=(SAMPLE_DIR/"late.csv").read_text(encoding="utf-8")
    b=service.submit_supplement({"text":text,**CLOSE})
    assert a["digest"]==b["digest"]

def test_in_batch_double_reverse_quarantined(closed):
    text="""event_id,at,channel,user_id,ip,kind,ref,bot
NEW-1,2026-11-05T09:00:00+08:00,DSP-A,U901,192.0.2.20,impression,,0
RV-1,2026-11-05T10:00:00+08:00,DSP-A,U901,192.0.2.20,reversal,NEW-1,0
RV-2,2026-11-05T11:00:00+08:00,DSP-A,U901,192.0.2.20,reversal,NEW-1,0
"""
    s=service.submit_supplement({"text":text,**CLOSE})
    codes=[q["code"] for q in s["quarantine"]]
    assert codes.count("OVER_REVERSE")==1
    a=next(x for x in s["channels"] if x["channel"]=="DSP-A")
    assert a["late_impressions"]==1 and a["late_reversed"]==1

def test_out_of_period_records_isolated(closed):
    text="""event_id,at,channel,user_id,ip,kind,ref,bot
OLD-1,2026-10-05T09:00:00+08:00,DSP-A,U902,192.0.2.20,impression,,0
RV-OLD,2026-10-06T09:00:00+08:00,DSP-A,U902,192.0.2.20,reversal,OLD-1,0
"""
    s=service.submit_supplement({"text":text,**CLOSE})
    assert {q["code"] for q in s["quarantine"]}>={"OUT_OF_PERIOD"}
    assert s["totals"]["late_delta"]=="0.00" and s["totals"]["payable"]=="0.00"
    assert s["count_ok"] is True
