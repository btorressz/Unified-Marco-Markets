import asyncio
from datetime import datetime, timezone
from backend.core import readiness
from backend.core.state_keys import price_integrity_key
from backend.execution.router import ExecutionRouter
from backend.ingest.source_registry import list_sources

class Store:
 def __init__(self): self.values={}; self.read=[]
 def set_snapshot(self,key,value,ttl=None): self.values[key]=value
 def get_snapshot(self,key): self.read.append(key); return self.values.get(key)
class Repo:
 def __init__(self): self.rows=[]
 def save_tick(self,**row): self.rows.append(row); return row
class Response:
 def __init__(self,data): self.data=data
 def raise_for_status(self): pass
 def json(self): return self.data
class Client:
 data=None
 def __init__(self,*a,**k): pass
 async def __aenter__(self): return self
 async def __aexit__(self,*a): pass
 async def get(self,*a,**k): return Response(self.data)
 async def post(self,url,json): return Response(self.data[json["type"]])

def test_readiness_registry_skips_database_only_source_and_reports_missing_snapshots(monkeypatch):
 store=Store(); monkeypatch.setattr(readiness,"StateStore",lambda:store)
 result=readiness._ingestion_check()
 assert "yfinance_crypto_history_research" not in {x["source_id"] for x in result["sources"]}
 assert result["status"] == "degraded"
 assert any(x["status"]=="degraded" for x in result["sources"])

def test_asset_integrity_keys_are_independent_and_router_fails_closed(monkeypatch):
 assert len({price_integrity_key(x) for x in ("BTC/USD","ETH/USD","SOL/USD")})==3
 router=ExecutionRouter(); router._store=Store()
 for market,asset in (("BTC-PERP","BTC_USD"),("ETH-PERP","ETH_USD"),("SOL-PERP","SOL_USD")):
  context=router._get_data_context({"found":False,"integrity_symbol":asset.replace("_", "/")})
  assert context["integrity_status"]=="UNKNOWN"
  assert f"price:integrity:{asset}" in router._store.read

def test_current_provider_normalization_and_partial_isolation(monkeypatch):
 from backend.ingest import pyth_ingest,kraken_ingest,coingecko_ingest
 now=int(datetime.now(timezone.utc).timestamp())
 parsed=[]
 for i,(symbol,feed) in enumerate(pyth_ingest.PRICE_FEEDS.items()):
  if symbol!="BTC/USD": parsed.append({"id":feed[2:],"price":{"price":str((2000+i)*100),"expo":-2,"conf":"2","publish_time":now}})
 Client.data={"parsed":parsed}; monkeypatch.setattr(pyth_ingest.httpx,"AsyncClient",Client)
 ticks=asyncio.run(pyth_ingest.PythIngestor(Store(),Repo()).fetch_prices()); assert [x.symbol for x in ticks]==["ETH/USD","SOL/USD"]
 Client.data={"error":[],"result":{"XXBTZUSD":{"c":["70000"]},"XETHZUSD":{"c":["3000"]}}}; monkeypatch.setattr(kraken_ingest.httpx,"AsyncClient",Client)
 ticks=asyncio.run(kraken_ingest.KrakenIngestor(Store(),Repo()).fetch_tickers()); assert [x.symbol for x in ticks]==["BTC/USD","ETH/USD"]
 Client.data={"bitcoin":{"usd":70000,"last_updated_at":now},"ethereum":{"usd":3000,"last_updated_at":now},"solana":{"usd":150,"last_updated_at":now}}
 monkeypatch.setattr(coingecko_ingest.httpx,"AsyncClient",Client); ticks=asyncio.run(coingecko_ingest.CoinGeckoIngestor(Store(),Repo()).fetch_prices())
 assert [x.symbol for x in ticks]==["BTC/USD","ETH/USD","SOL/USD"]; assert all(int(x.ts.timestamp())==now for x in ticks)

def test_hyperliquid_read_path_keeps_mark_mid_oracle_distinct(monkeypatch):
 from backend.ingest import hyperliquid_ingest
 Client.data={"allMids":{"BTC":"101","ETH":"201","SOL":"301"},"metaAndAssetCtxs":[{"universe":[{"name":"BTC"},{"name":"ETH"},{"name":"SOL"}]},[{"markPx":"102","oraclePx":"103"},{"markPx":"202","oraclePx":"203"},{"markPx":"302","oraclePx":"303"}]]}
 monkeypatch.setattr(hyperliquid_ingest.httpx,"AsyncClient",Client); store=Store(); repo=Repo(); rows=asyncio.run(hyperliquid_ingest.HyperliquidMarketIngestor(store,repo).fetch_market_context())
 assert [x["market"] for x in rows]==["BTC-PERP","ETH-PERP","SOL-PERP"]
 assert rows[0]["mid_price"]==101 and rows[0]["mark_price"]==102 and rows[0]["oracle_price"]==103
 assert all(x["funding_normalized"] is False for x in rows); assert all(x["venue"]=="hyperliquid_mark" for x in repo.rows)

def test_registry_truthfully_declares_current_coverage_and_history_remains_yahoo_only():
 sources={x["source_id"]:x for x in list_sources()}
 for source in ("pyth_sol_usd","kraken_sol_usd","coingecko_sol_usd"):
  assert sources[source]["supported_symbols"]==["BTC/USD","ETH/USD","SOL/USD"]
 assert sources["yfinance_crypto_history_research"]["storage_target"]=="research_market_bars"
