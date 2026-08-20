import logging
from datetime import datetime, timezone
import httpx
from backend.core.models import PriceTick
from backend.core.state_keys import price_snapshot_candidates, price_snapshot_key
from backend.core.state_store import StateStore
from backend.data.repositories.market_repo import MarketRepository
logger=logging.getLogger(__name__)
COINGECKO_PRICE_URL="https://api.coingecko.com/api/v3/simple/price"
COINS={"bitcoin":"BTC/USD","ethereum":"ETH/USD","solana":"SOL/USD"}
class CoinGeckoIngestor:
 def __init__(self,state_store=None,market_repo=None): self.state_store=state_store or StateStore(); self.market_repo=market_repo or MarketRepository()
 async def fetch_prices(self,run_context=None):
  try:
   async with httpx.AsyncClient(timeout=10.0) as client:
    response=await client.get(COINGECKO_PRICE_URL,params={"ids":",".join(COINS),"vs_currencies":"usd","include_last_updated_at":"true"}); response.raise_for_status(); data=response.json()
  except Exception as exc:
   if run_context: run_context.mark_failure(exc)
   logger.warning("CoinGecko current-price request failed",exc_info=True); return []
  ticks=[]
  for coin,symbol in COINS.items():
   row=data.get(coin)
   try:
    price=float(row["usd"]); updated=int(row["last_updated_at"])
    if price<=0 or updated<=0: raise ValueError
   except (TypeError,KeyError,ValueError):
    logger.warning("Skipping malformed CoinGecko observation for %s",symbol); continue
   tick=PriceTick(symbol=symbol,venue="coingecko",price=price,ts=datetime.fromtimestamp(updated,tz=timezone.utc)); self._store_tick(tick,run_context); ticks.append(tick)
   if run_context: run_context.record_received(1); run_context.set_provider_timestamp(tick.ts)
  if run_context: (run_context.mark_success() if ticks else run_context.mark_failure(ValueError("provider_empty_response")))
  return ticks
 async def fetch_price(self,coin_id="solana",vs_currency="usd",run_context=None):
  ticks=await self.fetch_prices(run_context); symbol=COINS.get(coin_id,f"{coin_id.upper()}/{vs_currency.upper()}")
  return next((t for t in ticks if t.symbol==symbol),None)
 def _store_tick(self,tick,run_context=None):
  payload={**tick.model_dump(mode="json"),"timestamp_semantics":"provider_last_updated_at"}
  for key in reversed(price_snapshot_candidates("coingecko",tick.symbol)): self.state_store.set_snapshot(key,payload,ttl=120)
  row=self.market_repo.save_tick(symbol=tick.symbol,venue=tick.venue,price=tick.price,confidence=tick.confidence,ts=tick.ts,ingest_run_id=getattr(run_context,"run_id",None),source_id="coingecko_sol_usd",provenance=run_context)
  if run_context and row: run_context.record_persisted(1)
