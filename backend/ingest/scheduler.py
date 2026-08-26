import asyncio
import logging
import socket
from collections.abc import Awaitable, Callable

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from backend.config import REDIS_LEASE_TTL_S
from backend.core.event_bus import EventBus
from backend.core.price_validator import PriceValidator
from backend.core.state_keys import PRICE_INTEGRITY, PRICE_INTEGRITY_LEGACY_LATEST, price_integrity_key
from backend.core.state_store import StateStore
from backend.ingest.wits_ingest import WITSIngestor
from backend.ingest.gdelt_ingest import GDELTIngestor
from backend.ingest.ofac_ingest import OFACIngestor
from backend.ingest.wto_ingest import WTOIngestor
from backend.ingest.kraken_ingest import KrakenIngestor
from backend.ingest.coingecko_ingest import CoinGeckoIngestor
from backend.ingest.pyth_ingest import PythIngestor
from backend.ingest.drift_ingest import DriftIngestor
from backend.ingest.hyperliquid_ingest import HyperliquidMarketIngestor
from backend.ingest.yfinance_ingest import YFinanceHistoryIngestor, YFinanceIngestor
from backend.data.repositories.ingest_repo import IngestRepository
from backend.ingest.provenance import IngestRunContext
from backend.ingest.source_registry import get_source
from backend.compute.basis_materializer import BasisMaterializer

logger = logging.getLogger(__name__)

PRICE_INTEGRITY_SYMBOLS = ("BTC/USD", "ETH/USD", "SOL/USD")


class IngestScheduler:

    def __init__(self, event_bus: EventBus | None = None, state_store: StateStore | None = None):
        self.event_bus = event_bus or EventBus()
        self.state_store = state_store or StateStore()
        self.scheduler = AsyncIOScheduler()
        self.ingest_repo = IngestRepository()
        self.worker_id = socket.gethostname()

        self.wits = WITSIngestor(event_bus=self.event_bus, state_store=self.state_store)
        self.gdelt = GDELTIngestor(event_bus=self.event_bus, state_store=self.state_store)
        self.ofac = OFACIngestor(state_store=self.state_store)
        self.wto = WTOIngestor(state_store=self.state_store)
        self.kraken = KrakenIngestor(state_store=self.state_store)
        self.coingecko = CoinGeckoIngestor(state_store=self.state_store)
        self.pyth = PythIngestor(state_store=self.state_store)
        self.drift = DriftIngestor(state_store=self.state_store)
        self.hyperliquid_market = HyperliquidMarketIngestor(state_store=self.state_store)
        self.yfinance = YFinanceIngestor(state_store=self.state_store)
        self.yfinance_history = YFinanceHistoryIngestor()
        self.price_validator = PriceValidator(state_store=self.state_store)
        self.basis_materializer = BasisMaterializer(state_store=self.state_store)

    def schedule_all(self) -> None:
        self.scheduler.add_job(self._run_wits, "interval", hours=6, id="wits_ingest", name="WITS Tariff Ingest", replace_existing=True)
        self.scheduler.add_job(self._run_gdelt, "interval", minutes=5, id="gdelt_ingest", name="GDELT News Ingest", replace_existing=True)
        self.scheduler.add_job(self._run_gdelt_events, "interval", minutes=15, id="gdelt_events_ingest", name="GDELT Events Ingest", replace_existing=True)
        self.scheduler.add_job(self._run_ofac, "interval", hours=6, id="ofac_ingest", name="OFAC Sanctions Ingest", replace_existing=True)
        self.scheduler.add_job(self._run_wto, "interval", hours=24, id="wto_ingest", name="WTO Trade Ingest", replace_existing=True)
        self.scheduler.add_job(self._run_kraken, "interval", seconds=30, id="kraken_ingest", name="Kraken Price Ingest", replace_existing=True)
        self.scheduler.add_job(self._run_coingecko, "interval", seconds=60, id="coingecko_ingest", name="CoinGecko Price Ingest", replace_existing=True)
        self.scheduler.add_job(self._run_pyth, "interval", seconds=30, id="pyth_ingest", name="Pyth Price Ingest", replace_existing=True)
        self.scheduler.add_job(self._run_hyperliquid_market, "interval", seconds=60, id="hyperliquid_market_ingest", name="Hyperliquid Perp Context", replace_existing=True)
        self.scheduler.add_job(self._run_hyperliquid_funding_history, "interval", hours=1, id="hyperliquid_funding_history_ingest", name="Hyperliquid Funding History", replace_existing=True)
        self.scheduler.add_job(self._run_drift, "interval", seconds=60, id="drift_ingest", name="Drift Market Ingest", replace_existing=True)
        self.scheduler.add_job(self._run_basis_materializer, "interval", seconds=60, id="basis_materializer", name="Derivatives Basis Materializer", replace_existing=True)
        self.scheduler.add_job(self._run_yfinance_crypto, "interval", seconds=60, id="yfinance_crypto_ingest", name="Yahoo Finance Crypto Research Fallback", replace_existing=True)
        self.scheduler.add_job(self._run_yfinance_crypto_history, "interval", hours=1, id="yfinance_crypto_history_ingest", name="Yahoo Finance Crypto Research History", replace_existing=True)

        self.scheduler.start()
        logger.info("IngestScheduler started with %d jobs", len(self.scheduler.get_jobs()))

    def stop(self) -> None:
        self.scheduler.shutdown(wait=False)
        logger.info("IngestScheduler stopped")

    def _refresh_price_integrity(self) -> None:
        for symbol in PRICE_INTEGRITY_SYMBOLS:
            try:
                result = self.price_validator.validate_symbol(symbol)
                self.state_store.set_snapshot(price_integrity_key(symbol), result, ttl=60)
                if symbol == "SOL/USD":
                    self.state_store.set_snapshot(PRICE_INTEGRITY, result, ttl=60)
                    self.state_store.set_snapshot(PRICE_INTEGRITY_LEGACY_LATEST, result, ttl=60)
            except Exception:
                logger.warning("Could not refresh price integrity for %s", symbol, exc_info=True)

    async def _run_with_lease(self, lease_name: str, job: Callable[[], Awaitable[None]]) -> bool:
        if self.state_store.get_redis() is None:
            await job()
            return True
        token = self.state_store.claim_lease(f"scheduler:{lease_name}", ttl=REDIS_LEASE_TTL_S)
        if token is None:
            if self.state_store.get_redis() is None:
                await job()
                return True
            logger.debug("Skipping duplicate ingest job; lease held: %s", lease_name)
            return False
        try:
            await job()
            return True
        finally:
            self.state_store.release_lease(f"scheduler:{lease_name}", token)

    async def _run_source(self, source_id: str, lease_name: str, job) -> bool:
        source = get_source(source_id)
        run_id = None
        context = IngestRunContext(source_id)
        try:
            try:
                row = self.ingest_repo.start_run(source_id, source["provider"], source["category"], self.worker_id)
                run_id = str(row["id"]) if row else None
                context.run_id = run_id
            except Exception:
                logger.warning("Ingest run ledger unavailable for %s", source_id, exc_info=True)
            ran = await self._run_with_lease(lease_name, lambda: job(context))
            facts = context.finish_fields()
            if not ran:
                facts.update(status="skipped_lease", lease_skipped=True, lease_acquired=False)
            else:
                facts["lease_acquired"] = self.state_store.get_redis() is not None
            try:
                self.ingest_repo.finish_run(run_id, **facts)
            except Exception:
                logger.warning("Could not finish ingest run for %s", source_id, exc_info=True)
            return ran
        except Exception as exc:
            context.mark_failure(exc)
            try:
                self.ingest_repo.mark_failure(run_id, exc)
            except Exception:
                logger.warning("Could not mark ingest failure for %s", source_id, exc_info=True)
            raise

    async def _run_wits(self) -> None:
        try:
            ran = await self._run_source("wits_tariffs", "wits", lambda context: self.wits.fetch_all(run_context=context))
            if ran:
                logger.debug("WITS ingest completed")
        except Exception:
            logger.error("WITS ingest job failed", exc_info=True)

    async def _run_gdelt(self) -> None:
        try:
            ran = await self._run_source("gdelt_macro_news", "gdelt", lambda context: self.gdelt.fetch_articles(run_context=context))
            if ran:
                logger.debug("GDELT ingest completed")
        except Exception:
            logger.error("GDELT ingest job failed", exc_info=True)

    async def _run_gdelt_events(self) -> None:
        try:
            await self._run_source("gdelt_events", "gdelt_events", lambda context: self.gdelt.fetch_events(run_context=context))
        except Exception:
            logger.error("GDELT Events ingest job failed", exc_info=True)

    async def _run_ofac(self) -> None:
        try:
            await self._run_source("ofac_sanctions", "ofac", lambda context: self.ofac.fetch(run_context=context))
        except Exception:
            logger.error("OFAC ingest job failed", exc_info=True)

    async def _run_wto(self) -> None:
        try:
            await self._run_source("wto_trade", "wto", lambda context: self.wto.fetch(run_context=context))
        except Exception:
            logger.error("WTO ingest job failed", exc_info=True)

    async def _run_kraken(self) -> None:
        try:
            ran = await self._run_source("kraken_sol_usd", "kraken", lambda context: self.kraken.fetch_tickers(run_context=context))
            if ran:
                self._refresh_price_integrity()
                logger.debug("Kraken ingest completed")
        except Exception:
            logger.error("Kraken ingest job failed", exc_info=True)

    async def _run_coingecko(self) -> None:
        try:
            ran = await self._run_source("coingecko_sol_usd", "coingecko", lambda context: self.coingecko.fetch_prices(run_context=context))
            if ran:
                self._refresh_price_integrity()
                logger.debug("CoinGecko ingest completed")
        except Exception:
            logger.error("CoinGecko ingest job failed", exc_info=True)

    async def _run_pyth(self) -> None:
        try:
            ran = await self._run_source("pyth_sol_usd", "pyth", lambda context: self.pyth.fetch_prices(run_context=context))
            if ran:
                self._refresh_price_integrity()
                logger.debug("Pyth ingest completed")
        except Exception:
            logger.error("Pyth ingest job failed", exc_info=True)

    async def _run_hyperliquid_market(self) -> None:
        try:
            await self._run_source("hyperliquid_sol_usd", "hyperliquid-market", lambda context: self.hyperliquid_market.fetch_market_context(run_context=context))
        except Exception:
            logger.error("Hyperliquid market ingest job failed", exc_info=True)

    async def _run_hyperliquid_funding_history(self) -> None:
        try:
            await self._run_source("hyperliquid_funding_history_research", "hyperliquid-funding-history", lambda context: self.hyperliquid_market.fetch_funding_history(run_context=context))
        except Exception:
            logger.error("Hyperliquid funding history ingest job failed", exc_info=True)

    async def _run_drift(self) -> None:
        try:
            ran = await self._run_source("drift_sol_perp", "drift-market", lambda context: self.drift.fetch_market_data(run_context=context))
            await self._run_source("drift_funding_sol_perp", "drift-funding", lambda context: self.drift.fetch_funding(run_context=context))
            if ran:
                logger.debug("Drift ingest completed")
        except Exception:
            logger.error("Drift ingest job failed", exc_info=True)

    async def _run_yfinance_crypto(self) -> None:
        try:
            ran = await self._run_source("yfinance_crypto_research", "yfinance-crypto-research", lambda context: self.yfinance.fetch_crypto_prices(run_context=context))
            if ran:
                self._refresh_price_integrity()
                logger.debug("Yahoo Finance crypto research ingest completed")
        except Exception:
            logger.error("Yahoo Finance crypto research ingest job failed", exc_info=True)

    async def _run_basis_materializer(self) -> None:
        try:
            await self._run_source("basis_materializer_v1", "basis-materializer",
                lambda context: self.basis_materializer.materialize(run_context=context))
        except Exception:
            logger.error("Basis materialization job failed", exc_info=True)

    async def _run_yfinance_crypto_history(self) -> None:
        try:
            await self._run_source("yfinance_crypto_history_research", "yfinance-crypto-history", lambda context: self.yfinance_history.fetch_crypto_history(run_context=context))
        except Exception:
            logger.error("Yahoo Finance crypto research history ingest job failed", exc_info=True)
