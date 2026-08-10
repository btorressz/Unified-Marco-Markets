import asyncio
import logging
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

logger = logging.getLogger(__name__)


class IngestScheduler:

    def __init__(self, event_bus: EventBus | None = None, state_store: StateStore | None = None):
        self.event_bus = event_bus or EventBus()
        self.state_store = state_store or StateStore()
        self.scheduler = AsyncIOScheduler()

        self.wits = WITSIngestor(event_bus=self.event_bus, state_store=self.state_store)
        self.gdelt = GDELTIngestor(event_bus=self.event_bus, state_store=self.state_store)
        self.kraken = KrakenIngestor(state_store=self.state_store)
        self.coingecko = CoinGeckoIngestor(state_store=self.state_store)
        self.pyth = PythIngestor(state_store=self.state_store)
        self.drift = DriftIngestor(state_store=self.state_store)

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

    async def _run_wits(self) -> None:
        try:
            ran = await self._run_with_lease("wits", self.wits.fetch_all)
            if ran:
                logger.debug("WITS ingest completed")
        except Exception:
            logger.error("WITS ingest job failed", exc_info=True)

    async def _run_gdelt(self) -> None:
        try:
            ran = await self._run_with_lease("gdelt", self.gdelt.fetch_articles)
            if ran:
                logger.debug("GDELT ingest completed")
        except Exception:
            logger.error("GDELT ingest job failed", exc_info=True)

    async def _run_kraken(self) -> None:
        try:
            ran = await self._run_with_lease("kraken", self.kraken.fetch_ticker)
            if ran:
                logger.debug("Kraken ingest completed")
        except Exception:
            logger.error("Kraken ingest job failed", exc_info=True)

    async def _run_coingecko(self) -> None:
        try:
            ran = await self._run_with_lease("coingecko", self.coingecko.fetch_price)
            if ran:
                logger.debug("CoinGecko ingest completed")
        except Exception:
            logger.error("CoinGecko ingest job failed", exc_info=True)

    async def _run_pyth(self) -> None:
        try:
            ran = await self._run_with_lease("pyth", self.pyth.fetch_price)
            if ran:
                logger.debug("Pyth ingest completed")
        except Exception:
            logger.error("Pyth ingest job failed", exc_info=True)

    async def _run_drift(self) -> None:
        async def fetch_drift() -> None:
            await self.drift.fetch_market_data()
            await self.drift.fetch_funding()

        try:
            ran = await self._run_with_lease("drift", fetch_drift)
            if ran:
                logger.debug("Drift ingest completed")
        except Exception:
            logger.error("Drift ingest job failed", exc_info=True)
