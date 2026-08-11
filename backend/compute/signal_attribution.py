from __future__ import annotations
from datetime import datetime, timezone
from typing import Any
HORIZONS = ["1h", "4h", "24h", "7d"]

def compute_signal_outcomes(signals: list[dict[str, Any]]) -> dict[str, Any]:
    rows=[]
    for idx,s in enumerate(signals):
        realized=s.get("realized_outcomes")
        if not isinstance(realized,dict):
            rows.append({"signal_id":s.get("id",idx),"agent":s.get("agent","unknown"),"available":False,"data_status":"no_realized_outcomes","outcomes":{}}); continue
        outcomes={h:float(realized[h]) for h in HORIZONS if realized.get(h) is not None}
        if not outcomes:
            rows.append({"signal_id":s.get("id",idx),"agent":s.get("agent","unknown"),"available":False,"data_status":"no_realized_outcomes","outcomes":{}}); continue
        direction=s.get("direction","neutral"); hit=any(v>0 for v in outcomes.values()) if direction=="bullish" else any(v<0 for v in outcomes.values()) if direction=="bearish" else None
        rows.append({"signal_id":s.get("id",idx),"agent":s.get("agent","unknown"),"signal":s.get("signal"),"direction":direction,"available":True,"data_status":"realized","outcomes":outcomes,"hit":hit,"pnl_impact":round(sum(outcomes.values())*10000,2)})
    return {"outcomes":rows,"horizons":HORIZONS,"available":any(r["available"] for r in rows),"data_status":"realized" if any(r["available"] for r in rows) else "no_realized_outcomes","ts":datetime.now(timezone.utc).isoformat()}

def attribution_summary(signals: list[dict[str, Any]]) -> dict[str, Any]:
    all_rows=compute_signal_outcomes(signals)["outcomes"]; rows=[r for r in all_rows if r["available"]]; n=len(rows)
    hits=sum(1 for r in rows if r.get("hit") is True); avg=sum(sum(r["outcomes"].values())/len(r["outcomes"]) for r in rows)/n if n else None
    return {"signal_count":len(all_rows),"evaluated_count":n,"unevaluated_count":len(all_rows)-n,"available":bool(n),"data_status":"realized" if n else "no_realized_outcomes","hit_rate":round(hits/n,4) if n else None,"false_positives":sum(1 for r in rows if r.get("hit") is False),"false_negatives":0,"average_return_after_signal":round(avg,6) if avg is not None else None,"pnl_impact":round(sum(r["pnl_impact"] for r in rows),2) if n else None,"by_signal":all_rows,"ts":datetime.now(timezone.utc).isoformat()}
