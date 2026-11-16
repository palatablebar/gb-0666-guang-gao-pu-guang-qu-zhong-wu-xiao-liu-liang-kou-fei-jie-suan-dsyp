import re
from decimal import Decimal,ROUND_HALF_UP
from app.errors import reject

PERIOD_RE=re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
CENT=Decimal("0.01")

def validate_options(options):
    options=options or {}
    if set(options)-{"sample","text","period","run_id","current_period"}:reject("PARAMETER","存在未知运行参数")
    sample=options.get("sample","late")
    if sample not in {"late","dirty","clean","gb18030"}:reject("SAMPLE","样例不存在")
    if "text" in options and not isinstance(options["text"],str):reject("CONTENT","文件内容须为文本")
    period=options.get("period","2026-11")
    if not isinstance(period,str) or not PERIOD_RE.match(period):reject("PERIOD","账期须为 YYYY-MM")
    current=options.get("current_period","2026-12")
    if not isinstance(current,str) or not PERIOD_RE.match(current):reject("PERIOD","当前账期须为 YYYY-MM")
    if current<=period:reject("PERIOD","当前账期须晚于关账账期")
    return options

def money(value):
    return Decimal(value).quantize(CENT,rounding=ROUND_HALF_UP)

def period_of(day):
    return day[:7]

def build_closure(result):
    """关账快照：从已发布运行冻结金额，原账期此后不再变动。"""
    channels={}
    for row in result["results"]:
        item=channels.setdefault(row["channel"],{"channel":row["channel"],"frozen_gross":Decimal(0),"frozen_credit":Decimal(0),"frozen_net":Decimal(0)})
        item["frozen_gross"]+=Decimal(row["gross"]);item["frozen_credit"]+=Decimal(row["credit"]);item["frozen_net"]+=Decimal(row["net"])
    for item in channels.values():
        for key in ("frozen_gross","frozen_credit","frozen_net"):item[key]=str(money(item[key]))
    accepted={x["event_id"]:x for x in result["rows"] if x["kind"]=="impression"}
    already_reversed={x["ref"] for x in result["rows"] if x["kind"]=="reversal"}
    return {
        "frozen_channels":sorted(channels.values(),key=lambda x:x["channel"]),
        "frozen_gross":str(sum((Decimal(x["frozen_gross"]) for x in channels.values()),Decimal(0))),
        "frozen_credit":str(sum((Decimal(x["frozen_credit"]) for x in channels.values()),Decimal(0))),
        "frozen_net":str(sum((Decimal(x["frozen_net"]) for x in channels.values()),Decimal(0))),
        "frozen_impressions":sorted(accepted.keys()),
        "already_reversed":sorted(already_reversed),
        "impression_rows":{k:v for k,v in accepted.items()},
    }

def adjudicate(result,closure,period,current_period,prior_supplements):
    """裁决补交批次。
    关账账期内的迟到记录/冲销不回写原账期，差额全部计入当前账期；
    不合法记录进隔离，保留来源行，不产生金额。
    """
    rows=result["rows"]
    # 流水线隔离（m1/m2）保留在 result["quarantine"]；无效曝光（m3）在 result["invalid"]；
    # 本函数只追加 M8 账期裁决产生的隔离，避免同一行被重复计数
    pipeline_quarantine=list(result["quarantine"])
    quarantine=list(pipeline_quarantine)
    late_impr={};current_impr={};out_impr=set()
    for row in rows:
        if row["kind"]!="impression":continue
        belong=period_of(row["day"])
        if belong==period:late_impr[row["event_id"]]=row
        elif belong==current_period:current_impr[row["event_id"]]=row
        else:
            out_impr.add(row["event_id"])
            quarantine.append({"line":row["line"],"code":"OUT_OF_PERIOD","raw":row.get("source",row)});continue
    prior_late=set(closure["frozen_impressions"])
    for old in prior_supplements:prior_late|=set(old.get("late_impressions",[]))
    rejected_late=set()
    for event_id in sorted(late_impr):
        if event_id in prior_late:
            quarantine.append({"line":late_impr[event_id]["line"],"code":"LATE_DUPLICATE","raw":late_impr[event_id].get("source",late_impr[event_id])});rejected_late.add(event_id)
    for event_id in rejected_late:late_impr.pop(event_id)
    prior_reversed=set(closure["already_reversed"])
    for old in prior_supplements:prior_reversed|=set(old.get("late_reversed",[]))
    late_reversed=[];batch_reversed=set()
    buckets={}
    def bucket(channel,phase):
        key=(channel,phase)
        return buckets.setdefault(key,{"channel":channel,"phase":phase,"impressions":0,"reversed":0,"gross_raw":Decimal(0),"credit_raw":Decimal(0),"lines":[]})
    sources=[]
    frozen_rows=closure["impression_rows"]
    for event_id,row in sorted(late_impr.items()):
        target=bucket(row["channel"],"late");target["impressions"]+=1
        target["gross_raw"]+=Decimal(row["cpm"])/1000;target["lines"].append(row["line"])
        sources.append({"line":row["line"],"event_id":event_id,"channel":row["channel"],"kind":"迟到曝光","phase":"late","delta_raw":str(Decimal(row["cpm"])/1000)})
    for event_id,row in sorted(current_impr.items()):
        target=bucket(row["channel"],"current");target["impressions"]+=1
        target["gross_raw"]+=Decimal(row["cpm"])/1000;target["lines"].append(row["line"])
        sources.append({"line":row["line"],"event_id":event_id,"channel":row["channel"],"kind":"本期曝光","phase":"current","delta_raw":str(Decimal(row["cpm"])/1000)})
    for row in sorted((x for x in rows if x["kind"]=="reversal"),key=lambda x:(x["at"],x["event_id"])):
        ref=row["ref"];code=None
        if ref in frozen_rows:
            if row["channel"]!=frozen_rows[ref]["channel"]:code="CHANNEL"
            elif row["at"]<frozen_rows[ref]["at"]:code="REVERSE_TIME"
            elif ref in prior_reversed:code="OVER_REVERSE"
            if code:
                quarantine.append({"line":row["line"],"code":code,"raw":row.get("source",row)});continue
            prior_reversed.add(ref);late_reversed.append(ref)
            original=frozen_rows[ref];target=bucket(original["channel"],"late");target["reversed"]+=1
            target["credit_raw"]+=Decimal(original["cpm"])/1000;target["lines"].append(row["line"])
            sources.append({"line":row["line"],"event_id":row["event_id"],"channel":original["channel"],"kind":"迟到冲销","phase":"late","ref":ref,"delta_raw":str(-Decimal(original["cpm"])/1000)})
            continue
        if ref in late_impr:
            original=late_impr[ref]
            if row["channel"]!=original["channel"]:code="CHANNEL"
            elif row["at"]<original["at"]:code="REVERSE_TIME"
            elif ref in batch_reversed:code="OVER_REVERSE"
            if code:
                quarantine.append({"line":row["line"],"code":code,"raw":row.get("source",row)});continue
            batch_reversed.add(ref)
            target=bucket(original["channel"],"late");target["reversed"]+=1
            target["credit_raw"]+=Decimal(original["cpm"])/1000;target["lines"].append(row["line"])
            sources.append({"line":row["line"],"event_id":row["event_id"],"channel":original["channel"],"kind":"迟到冲销","phase":"late","ref":ref,"delta_raw":str(-Decimal(original["cpm"])/1000)})
            continue
        if ref in current_impr:
            original=current_impr[ref]
            if row["channel"]!=original["channel"]:code="CHANNEL"
            elif row["at"]<original["at"]:code="REVERSE_TIME"
            elif ref in batch_reversed:code="OVER_REVERSE"
            if code:
                quarantine.append({"line":row["line"],"code":code,"raw":row.get("source",row)});continue
            batch_reversed.add(ref)
            target=bucket(original["channel"],"current");target["reversed"]+=1
            target["credit_raw"]+=Decimal(original["cpm"])/1000;target["lines"].append(row["line"])
            sources.append({"line":row["line"],"event_id":row["event_id"],"channel":original["channel"],"kind":"本期冲销","phase":"current","ref":ref,"delta_raw":str(-Decimal(original["cpm"])/1000)})
            continue
        code="OUT_OF_PERIOD" if ref in out_impr else "REFERENCE"
        quarantine.append({"line":row["line"],"code":code,"raw":row.get("source",row)})
    frozen_map={x["channel"]:x for x in closure["frozen_channels"]}
    channels=[]
    for channel in sorted(set(list(frozen_map)+[k[0] for k in buckets])):
        late=buckets.get((channel,"late"));cur=buckets.get((channel,"current"))
        late_gross=money(late["gross_raw"]) if late else Decimal("0.00")
        late_net=money((late["gross_raw"]-late["credit_raw"]) if late else Decimal(0))
        late_credit=money(late_gross-late_net)
        cur_gross=money(cur["gross_raw"]) if cur else Decimal("0.00")
        cur_net=money((cur["gross_raw"]-cur["credit_raw"]) if cur else Decimal(0))
        cur_credit=money(cur_gross-cur_net)
        frozen=frozen_map.get(channel)
        frozen_net=Decimal(frozen["frozen_net"]) if frozen else Decimal("0.00")
        channels.append({
            "channel":channel,
            "frozen_net":str(frozen_net),
            "late_gross":str(late_gross),"late_credit":str(late_credit),"late_delta":str(late_net),
            "current_gross":str(cur_gross),"current_credit":str(cur_credit),"current_net":str(cur_net),
            "payable":str(money(cur_net+late_net)),
            "late_impressions":late["impressions"] if late else 0,"late_reversed":late["reversed"] if late else 0,
            "current_impressions":cur["impressions"] if cur else 0,"current_reversed":cur["reversed"] if cur else 0,
        })
    totals={
        "frozen_net":str(sum((Decimal(x["frozen_net"]) for x in channels),Decimal(0))),
        "late_delta":str(sum((Decimal(x["late_delta"]) for x in channels),Decimal(0))),
        "current_net":str(sum((Decimal(x["current_net"]) for x in channels),Decimal(0))),
        "payable":str(sum((Decimal(x["payable"]) for x in channels),Decimal(0))),
    }
    totals["delta_borne_by_current"]=totals["late_delta"]
    totals["conservation_ok"]=money(Decimal(totals["current_net"])+Decimal(totals["late_delta"]))==Decimal(totals["payable"])
    total_in=result["input_count"]
    # rows（含被 M8 隔离的采信行，隔离只是改判不丢行）+ invalid + 流水线隔离 + 空行 = 输入总数
    accounted=len(rows)+len(result.get("invalid",[]))+len(pipeline_quarantine)+result["blank_count"]
    return {
        "period":period,"current_period":current_period,
        "channels":channels,"totals":totals,"sources":sorted(sources,key=lambda x:x["line"]),
        "quarantine":quarantine,"invalid":result.get("invalid",[]),
        "late_impressions":sorted(late_impr.keys()),"late_reversed":sorted(late_reversed),
        "current_impressions":sorted(current_impr.keys()),
        "input_count":total_in,"blank_count":result["blank_count"],
        "count_ok":accounted==total_in,
        "amount_ok":totals["conservation_ok"],
    }
