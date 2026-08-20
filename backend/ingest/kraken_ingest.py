import logging
from datetime import datetime, timezone
import httpx
from backend.core.models import PriceTick
from backend.core.state_keys import price_snapshot_candidates, price_snapshot_key
from backend.core.state_store import StateStore
from backend.data.repositories.market_repo import MarketRepository
logger=logging.getLogger(__name__)
KRAKEN_TICKER_URL="https://api.kraken.com/0/public/Ticker"
KRAKEN_PAIRS={"XBTUSD":"BTC/USD","ETHUSD":"ETH/USD","SOLUSD":"SOL/USD"}
class KrakenIngestor:
 def __init__(self,state_store=None,market_repo=None): self.state_store=state_store or StateStore(); self.market_repo=market_repo or MarketRepository()
 async def fetch_tickers(self,run_context=None):
  retrieved=datetime.now(timezone.utc)
  try:
   async with httpx.AsyncClient(timeout=10.0) as client:
    response=await client.get(KRAKEN_TICKER_URL,params={"pair":",".join(KRAKEN_PAIRS)}); response.raise_for_status(); data=response.json()
   if data.get("error"): raise ValueError("provider_api_error")
  except Exception as exc:
   if run_context: run_context.mark_failure(exc)
   logger.warning("Kraken current-price request failed",exc_info=True); return []
  result=data.get("result",{}); ticks=[]
  for requested,symbol in KRAKEN_PAIRS.items():
   aliases=(requested,"XXBTZUSD" if requested=="XBTUSD" else f"X{requested[:3]}ZUSD")
   row=next((result.get(k) for k in aliases if result.get(k)),None)
   try:
    price=float(row["c"][0])
    if price<=0: raise ValueError
   except (TypeError,KeyError,IndexError,ValueError):
    logger.warning("Skipping malformed Kraken observation for %s",symbol); continue
   tick=PriceTick(symbol=symbol,venue="kraken",price=price,ts=retrieved); self._store_tick(tick,run_context); ticks.append(tick)
   if run_context: run_context.record_received(1)
  if run_context: (run_context.mark_success() if ticks else run_context.mark_failure(ValueError("provider_empty_response")))
  return ticks
 async def fetch_ticker(self,pair="SOLUSD",run_context=None):
  ticks=await self.fetch_tickers(run_context); symbol=KRAKEN_PAIRS.get(pair,pair)
  return next((t for t in ticks if t.symbol==symbol),None)
 def _store_tick(self,tick,run_context=None):
  payload={**tick.model_dump(mode="json"),"timestamp_semantics":"retrieved_at"}
  for key in reversed(price_snapshot_candidates("kraken",tick.symbol)): self.state_store.set_snapshot(key,payload,ttl=120)
  row=self.market_repo.save_tick(symbol=tick.symbol,venue=tick.venue,price=tick.price,confidence=tick.confidence,ts=tick.ts,ingest_run_id=getattr(run_context,"run_id",None),source_id="kraken_sol_usd",provenance=run_context)
  if run_context and row: run_context.record_persisted(1)
