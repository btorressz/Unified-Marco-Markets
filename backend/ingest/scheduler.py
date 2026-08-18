import asyncio
import logging
import socket
from collections.abc import Awaitable, Callable

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from backend.config import REDIS_LEASE_TTL_S
from backend.core.event_bus import EventBus
from backend.core.state_store import StateStore
from backend.ingest.wits_ingest import WITSIngestor
from backend.ingest.gdelt_ingest import GDELTIngestor
from backend.ingest.kraken_ingest import KrakenIngestor
from backend.ingest.coingecko_ingest import CoinGeckoIngestor
from backend.ingest.pyth_ingest import PythIngestor
from backend.ingest.drift_ingest import DriftIngestor
from backend.ingest.yfinance_ingest import YFinanceIngestor
from backend.data.repositories.ingest_repo import IngestRepository
from backend.ingest.provenance import IngestRunContext
from backend.ingest.source_registry import get_source

logger = logging.getLogger(__name__)


class IngestScheduler:

    def __init__(self, event_bus: EventBus | None = None, state_store: StateStore | None = None):
        self.event_bus = event_bus or EventBus()
        self.state_store = state_store or StateStore()
        self.scheduler = AsyncIOScheduler()
        self.ingest_repo = IngestRepository()
        self.worker_id = socket.gethostname()

        self.wits = WITSIngestor(event_bus=self.event_bus, state_store=self.state_store)
        self.gdelt = GDELTIngestor(event_bus=self.event_bus, state_store=self.state_store)
        self.kraken = KrakenIngestor(state_store=self.state_store)
        self.coingecko = CoinGeckoIngestor(state_store=self.state_store)
        self.pyth = PythIngestor(state_store=self.state_store)
        self.drift = DriftIngestor(state_store=self.state_store)
        self.yfinance = YFinanceIngestor(state_store=self.state_store)

    def schedule_all(self) -> None:
        self.scheduler.add_job(
            self._run_wits, "interval", hours=6, id="wits_ingest",
            name="WITS Tariff Ingest", replace_existing=True,
        )
        self.scheduler.add_job(
            self._run_gdelt, "interval", minutes=5, id="gdelt_ingest",
            name="GDELT News Ingest", replace_existing=True,
        )
        self.scheduler.add_job(
            self._run_kraken, "interval", seconds=30, id="kraken_ingest",
            name="Kraken Price Ingest", replace_existing=True,
        )
        self.scheduler.add_job(
            self._run_coingecko, "interval", seconds=60, id="coingecko_ingest",
            name="CoinGecko Price Ingest", replace_existing=True,
        )
        self.scheduler.add_job(
            self._run_pyth, "interval", seconds=30, id="pyth_ingest",
            name="Pyth Price Ingest", replace_existing=True,
        )
        self.scheduler.add_job(
            self._run_drift, "interval", seconds=60, id="drift_ingest",
            name="Drift Market Ingest", replace_existing=True,
        )
        self.scheduler.add_job(
            self._run_yfinance_crypto, "interval", seconds=60, id="yfinance_crypto_ingest",
            name="Yahoo Finance Crypto Research Fallback", replace_existing=True,
        )

        self.scheduler.start()
        logger.info("IngestScheduler started with %d jobs", len(self.scheduler.get_jobs()))

    def stop(self) -> None:
        self.scheduler.shutdown(wait=False)
        logger.info("IngestScheduler stopped")

    async def _run_with_lease(
        self,
        lease_name: str,
        job: Callable[[], Awaitable[None]],
    ) -> bool:
        """Run one ingest job once across workers when Redis is available.

        Redis is coordination, not a hard dependency for data availability. If
        Redis is unavailable, preserve the existing fail-soft behavior and run
        the job locally. When Redis is healthy and another worker owns the
        lease, this worker skips the duplicate run.
        """
        if self.state_store.get_redis() is None:
            await job()
            return True

        token = self.state_store.claim_lease(
            f"scheduler:{lease_name}",
            ttl=REDIS_LEASE_TTL_S,
        )
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
        """Wrap the existing provider/lease flow in a fail-soft durable ledger."""
        source = get_source(source_id); run_id = None
        context = IngestRunContext(source_id)
        try:
            try:
                row = self.ingest_repo.start_run(source_id, source["provider"], source["category"], self.worker_id)
                run_id = str(row["id"]) if row else None; context.run_id = run_id
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
            try: self.ingest_repo.mark_failure(run_id, exc)
            except Exception: logger.warning("Could not mark ingest failure for %s", source_id, exc_info=True)
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

    async def _run_kraken(self) -> None:
        try:
            ran = await self._run_source("kraken_sol_usd", "kraken", lambda context: self.kraken.fetch_ticker(run_context=context))
            if ran:
                logger.debug("Kraken ingest completed")
        except Exception:
            logger.error("Kraken ingest job failed", exc_info=True)

    async def _run_coingecko(self) -> None:
        try:
            ran = await self._run_source("coingecko_sol_usd", "coingecko", lambda context: self.coingecko.fetch_price(run_context=context))
            if ran:
                logger.debug("CoinGecko ingest completed")
        except Exception:
            logger.error("CoinGecko ingest job failed", exc_info=True)

    async def _run_pyth(self) -> None:
        try:
            ran = await self._run_source("pyth_sol_usd", "pyth", lambda context: self.pyth.fetch_price(run_context=context))
            if ran:
                logger.debug("Pyth ingest completed")
        except Exception:
            logger.error("Pyth ingest job failed", exc_info=True)

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
            ran = await self._run_source(
                "yfinance_crypto_research",
                "yfinance-crypto-research",
                lambda context: self.yfinance.fetch_crypto_prices(run_context=context),
            )
            if ran:
                logger.debug("Yahoo Finance crypto research ingest completed")
        except Exception:
            logger.error("Yahoo Finance crypto research ingest job failed", exc_info=True)
