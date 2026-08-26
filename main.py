import os

from backend.logging_config import setup_logging, get_logger

setup_logging()
logger = get_logger(__name__)


def create_app():
    from pathlib import Path
    from contextlib import asynccontextmanager
    from fastapi import FastAPI
    from fastapi.staticfiles import StaticFiles
    from fastapi.responses import HTMLResponse
    from backend.core.operator_auth import enforce_operator_request
    from backend.core.mutation_policy import validate_mutation_route_inventory

    @asynccontextmanager
    async def lifespan(application):
        from backend.data.db import init_db, close_pool
        from backend.core.redis_runtime import close_redis_runtime
        from backend.ingest.scheduler import IngestScheduler

        scheduler = IngestScheduler()

        try:
            try:
                init_db()
                logger.info("Database migrations applied")
            except Exception as exc:
                logger.warning("Database migration failed (non-fatal): %s", exc)

            try:
                scheduler.schedule_all()
                logger.info("Ingest scheduler started")
            except Exception as exc:
                logger.warning("Scheduler start failed (non-fatal): %s", exc)

            yield
        finally:
            try:
                scheduler.stop()
            except Exception:
                logger.warning("Scheduler shutdown failed", exc_info=True)

            try:
                await close_redis_runtime()
            except Exception:
                logger.warning("Redis runtime shutdown failed", exc_info=True)

            close_pool()

    app = FastAPI(title="Tariff Risk Desk", version="0.1.0", lifespan=lifespan)
    app.middleware("http")(enforce_operator_request)

    frontend_dir = Path(__file__).parent / "frontend"
    app.mount("/frontend", StaticFiles(directory=str(frontend_dir)), name="frontend")

    from backend.api.index_routes import router as index_router
    from backend.api.markets_routes import router as markets_router
    from backend.api.divergence_routes import router as divergence_router
    from backend.api.rules_routes import router as rules_router
    from backend.api.execution_routes import router as execution_router
    from backend.api.risk_routes import router as risk_router
    from backend.api.events_routes import router as events_router
    from backend.api.health_routes import router as health_router, probe_router as health_probe_router
    from backend.api.ingestion_routes import router as ingestion_router
    from backend.api.ws_routes import router as ws_router
    from backend.api.stablecoin_routes import router as stablecoin_router
    from backend.api.predict_routes import router as predict_router
    from backend.api.montecarlo_routes import router as montecarlo_router
    from backend.api.yield_routes import router as yield_router
    from backend.api.microstructure_routes import router as microstructure_router
    from backend.api.agents_routes import router as agents_router
    from backend.api.metrics_routes import router as metrics_router
    from backend.api.solana_routes import router as solana_router
    from backend.api.funding_arb_routes import router as funding_arb_router
    from backend.api.basis_routes import router as basis_router
    from backend.api.stable_flow_routes import router as stable_flow_router
    from backend.api.portfolio_routes import router as portfolio_router
    from backend.api.liquidation_routes import router as liquidation_router
    from backend.api.sandbox_routes import router as sandbox_router
    from backend.api.replay_routes import router as replay_router
    from backend.api.slippage_routes import router as slippage_router
    from backend.api.hedge_routes import router as hedge_router
    from backend.api.allocation_routes import router as allocation_router
    from backend.api.ml_routes import router as ml_router
    from backend.api.backtest_routes import router as backtest_router
    from backend.api.heuristic_routes import router as heuristic_router
    from backend.api.volatility_routes import router as volatility_router
    from backend.api.portfolio_risk_routes import router as portfolio_risk_router
    from backend.api.equities_routes import router as equities_router
    from backend.api.strategy_routes import router as strategy_router
    from backend.api.macro_routes import router as macro_router
    from backend.api.macro_sensitivity_routes import router as macro_sensitivity_router
    from backend.api.cross_asset_routes import router as cross_asset_router
    from backend.api.scenario_routes import router as scenario_router
    from backend.api.explain_routes import router as explain_router
    from backend.api.signals_routes import router as signals_router
    from backend.api.watchlists_routes import router as watchlists_router
    from backend.api.reports_routes import router as reports_router

    from backend.api.geopolitical_routes import router as geopolitical_router
    from backend.api.protection_routes import router as protection_router
    from backend.api.decision_routes import router as decision_router


    app.include_router(index_router)
    app.include_router(markets_router)
    app.include_router(divergence_router)
    app.include_router(rules_router)
    app.include_router(execution_router)
    app.include_router(risk_router)
    app.include_router(events_router)
    app.include_router(health_router)
    app.include_router(health_probe_router)
    app.include_router(ingestion_router)
    app.include_router(ws_router)
    app.include_router(stablecoin_router)
    app.include_router(predict_router)
    app.include_router(montecarlo_router)
    app.include_router(yield_router)
    app.include_router(microstructure_router)
    app.include_router(agents_router)
    app.include_router(metrics_router)
    app.include_router(solana_router)
    app.include_router(funding_arb_router)
    app.include_router(basis_router)
    app.include_router(stable_flow_router)
    app.include_router(portfolio_router)
    app.include_router(liquidation_router)
    app.include_router(sandbox_router)
    app.include_router(replay_router)
    app.include_router(slippage_router)
    app.include_router(hedge_router)
    app.include_router(allocation_router)
    app.include_router(ml_router)
    app.include_router(backtest_router)
    app.include_router(heuristic_router)
    app.include_router(volatility_router)
    app.include_router(portfolio_risk_router)
    app.include_router(equities_router)
    app.include_router(strategy_router)
    app.include_router(macro_router)
    app.include_router(macro_sensitivity_router)
    app.include_router(cross_asset_router)
    app.include_router(scenario_router)
    app.include_router(explain_router)
    app.include_router(signals_router)
    app.include_router(watchlists_router)
    app.include_router(reports_router)
    app.include_router(geopolitical_router)
    app.include_router(protection_router)
    app.include_router(decision_router)

    mutation_inventory = validate_mutation_route_inventory(app)
    logger.info(
        "Mutation authorization inventory validated: %s routes (%s external, %s calculation-only)",
        mutation_inventory["mutation_route_count"],
        mutation_inventory["external_state_mutation_count"],
        mutation_inventory["calculation_only_count"],
    )

    @app.get("/", response_class=HTMLResponse)
    def root():
        html = (frontend_dir / "index.html").read_text(encoding="utf-8")
        scripts = (
            '<script src="/frontend/assets/frontend_alignment.js"></script>',
            '<script src="/frontend/assets/operator_access.js"></script>',
            '<script src="/frontend/assets/counterfactual_replay.js"></script>',
            '<script src="/frontend/assets/decision_outcomes.js"></script>',
            '<script src="/frontend/assets/counterfactual_sensitivity.js"></script>',
        )
        for script in scripts:
            if script not in html:
                html = html.replace("</body>", f"  {script}\n</body>")
        return HTMLResponse(html, headers={"Cache-Control": "no-cache"})

    logger.info("Tariff Risk Desk API initialized with all routes")
    return app


app = create_app()

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", "5000"))
    uvicorn.run(app, host="0.0.0.0", port=port)