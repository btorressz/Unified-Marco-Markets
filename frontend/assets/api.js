const API = (() => {
  const BASE = '';

  async function fetchJSON(path) {
    try {
      const res = await fetch(BASE + path);
      if (!res.ok) {
        const detail = await res.text();
        throw new Error(`API ${res.status}: ${detail}`);
      }
      return await res.json();
    } catch (err) {
      console.error(`[API] Error fetching ${path}:`, err);
      throw err;
    }
  }

  async function writeJSON(path, method, body) {
    try {
      const res = await fetch(BASE + path, {
        method,
        headers: { 'Content-Type': 'application/json' },
        body: body === undefined ? undefined : JSON.stringify(body),
      });
      if (!res.ok) throw new Error(`API ${res.status}: ${await res.text()}`);
      return await res.json();
    } catch (err) {
      console.warn(`[API] ${method} ${path}: ${err.message}`);
      throw err;
    }
  }

  async function putJSON(path, body) { return writeJSON(path, 'PUT', body); }
  async function deleteJSON(path) { return writeJSON(path, 'DELETE'); }

  async function postJSON(path, body) {
    try {
      const res = await fetch(BASE + path, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      if (!res.ok) {
        let msg = `API ${res.status}`;
        try {
          const data = await res.json();
          const detail = data.detail || data;
          if (detail && detail.reasons) {
            msg = detail.reasons.join('; ');
          } else if (detail && detail.message) {
            msg = detail.message;
          } else if (typeof detail === 'string') {
            msg = detail;
          }
        } catch (_) {
          msg = await res.text().catch(() => msg);
        }
        throw new Error(msg);
      }
      return await res.json();
    } catch (err) {
      if (err.message && !err.message.startsWith('[API]')) {
        console.warn(`[API] ${path}: ${err.message}`);
      }
      throw err;
    }
  }

  return {
    getIndexLatest: () => fetchJSON('/api/index/latest'),
    getIndexHistory: (window = '7d') => fetchJSON(`/api/index/history?window=${window}`),
    getIndexComponents: () => fetchJSON('/api/index/components'),

    getMarketLatest: () => fetchJSON('/api/markets/latest'),
    getMarketHistory: (venue = 'hyperliquid', window = '1h') =>
      fetchJSON(`/api/markets/history?venue=${venue}&window=${window}`),
    getFunding: () => fetchJSON('/api/markets/funding'),
    getIntegrity: () => fetchJSON('/api/markets/integrity'),

    getDivergenceSpreads: () => fetchJSON('/api/divergence/spreads'),
    getDivergenceAlerts: () => fetchJSON('/api/divergence/alerts'),

    getStablecoinHealth: () => fetchJSON('/api/stablecoins/health'),
    getStablecoinAlerts: () => fetchJSON('/api/stablecoins/alerts'),

    getPrediction: () => fetchJSON('/api/predict/latest'),

    postMonteCarlo: (params) => postJSON('/api/montecarlo/run', params),

    getCarry: () => fetchJSON('/api/yield/carry'),

    getMicrostructure: () => fetchJSON('/api/microstructure/snapshot'),

    getAgentSignals: () => fetchJSON('/api/agents/signals'),
    getAgentRegistry: () => fetchJSON('/api/agents/status'),

    getRulesEvaluation: () => fetchJSON('/api/rules/evaluate'),
    getRulesStatus: () => fetchJSON('/api/rules/status'),
    getHeuristicRegistry: () => fetchJSON('/api/heuristics/registry'),
    postHeuristicEvaluate: (config) => postJSON('/api/heuristics/evaluate', config),
    getHeuristicPerformance: (params = {}) => fetchJSON(`/api/heuristics/performance?${new URLSearchParams(Object.entries(params).filter(([, value]) => value !== undefined && value !== null)).toString()}`),
    getHeuristicEvaluations: (params = {}) => fetchJSON(`/api/heuristics/evaluations?${new URLSearchParams(Object.entries(params).filter(([, value]) => value !== undefined && value !== null)).toString()}`),

    getPositions: () => fetchJSON('/api/execution/positions'),
    getPaperTrades: () => fetchJSON('/api/execution/paper-trades'),
    postOrder: (order) => postJSON('/api/execution/order', order),

    getRiskStatus: () => fetchJSON('/api/risk/status'),
    postStressTest: (scenario) => postJSON('/api/risk/stress-test', scenario),
    getGuardrails: () => fetchJSON('/api/risk/guardrails'),

    getEvents: (limit = 50) => fetchJSON(`/api/events/?limit=${limit}`),
    getHealth: () => fetchJSON('/api/health/'),

    getEQI: () => fetchJSON('/api/metrics/eqi'),
    getSolanaQuality: () => fetchJSON('/api/solana/quality'),
    getSolanaCongestion: () => fetchJSON('/api/solana/congestion'),
    getFundingArb: () => fetchJSON('/api/funding-arb/latest'),
    getBasisLatest: () => fetchJSON('/api/basis/latest'),
    getBasisFeasibility: () => fetchJSON('/api/basis/feasibility'),
    getStableFlow: () => fetchJSON('/api/stable-flow/latest'),
    getAdaptiveWeights: () => fetchJSON('/api/rules/adaptive-weights'),
    getPortfolioProposal: (method = 'risk_parity') => fetchJSON(`/api/portfolio/proposal?method=${method}`),
    getLiquidationHeatmap: () => fetchJSON('/api/liquidation/heatmap'),
    getRegimeAnalogs: () => fetchJSON('/api/risk/regime-analogs'),
    getMacroTerminal: () => fetchJSON('/api/index/macro-terminal'),
    getFeedStatus: () => fetchJSON('/api/health/feeds'),

    getAllocationLatest: () => fetchJSON('/api/allocation/latest'),
    postRebalancePreview: (body) => postJSON('/api/allocation/rebalance-preview', body),

    getMLFeaturesLatest: () => fetchJSON('/api/ml/features/latest'),
    getMLPredictionLatest: () => fetchJSON('/api/ml/prediction/latest'),
    postMLTrainOffline: (body) => postJSON('/api/ml/train/offline', body),
    getMLTrainingHistory: () => fetchJSON('/api/ml/training/history'),

    postBacktestRun: (config) => postJSON('/api/backtest/run', config),
    getBacktestLatest: () => fetchJSON('/api/backtest/latest'),
    getBacktestHistory: () => fetchJSON('/api/backtest/history'),
    getBacktestDataCoverage: () => fetchJSON('/api/backtest/data-coverage'),
    getBacktestRun: (runId) => fetchJSON(`/api/backtest/${encodeURIComponent(runId)}`),

    getVolRegime: () => fetchJSON('/api/volatility/regime'),
    getVolRecommendations: () => fetchJSON('/api/volatility/recommendations'),

    getPortfolioRiskSummary: () => fetchJSON('/api/portfolio-risk/summary'),
    getPortfolioRiskContributions: () => fetchJSON('/api/portfolio-risk/contributions'),
    getPortfolioRiskExposures: () => fetchJSON('/api/portfolio-risk/exposures'),

    getRedisHealth: () => fetchJSON('/api/health/redis'),

    getDataQuality: () => fetchJSON('/api/health/data-quality'),
    getIngestionRegistry: () => fetchJSON('/api/ingestion/registry'),
    getIngestionStatus: () => fetchJSON('/api/ingestion/status'),
    getIngestionRuns: (params = {}) => fetchJSON(`/api/ingestion/runs?${new URLSearchParams(Object.entries(params).filter(([, value]) => value !== undefined && value !== null && value !== '')).toString()}`),
    getDataProvenance: (params = {}) => fetchJSON(`/api/ingestion/provenance?${new URLSearchParams(Object.entries(params).filter(([, value]) => value !== undefined && value !== null && value !== '')).toString()}`),
    getStrategyPerformance: () => fetchJSON('/api/strategy/performance'),
    postAllocationExecutionPreview: (body) => postJSON('/api/allocation/execution-preview', body),
    postConditionalOrder: (body) => postJSON('/api/execution/conditional-order', body),
    getConditionalOrders: () => fetchJSON('/api/execution/conditional-orders'),
    postEvaluateConditionalOrders: (body) => postJSON('/api/execution/conditional-orders/evaluate', body || {}),
    postSmartOrder: (body) => postJSON('/api/execution/smart-order', body),
    getSmartOrders: () => fetchJSON('/api/execution/smart-orders'),
    postReplayTradeSimulation: (body) => postJSON('/api/replay/trade-simulation', body),
    getAgentsPerformance: () => fetchJSON('/api/agents/performance'),
    getAgentsHistory: () => fetchJSON('/api/agents/history'),
    getEquitiesOverview: () => fetchJSON('/api/equities/overview'),
    getEquityHistory: (ticker = 'SPY') => fetchJSON(`/api/equities/history/${ticker}`),
    getEquityRisk: () => fetchJSON('/api/equities/risk'),
    getEquityTariffExposure: () => fetchJSON('/api/equities/tariff-exposure'),
    getEquitySectorRotation: () => fetchJSON('/api/equities/sector-rotation'),
    getEquityCrossAsset: () => fetchJSON('/api/equities/cross-asset'),

    getMacroEvents: () => fetchJSON('/api/macro/events'),
    getMacroEventsImpact: () => fetchJSON('/api/macro/events/impact'),
    getMacroEventReaction: (id) => fetchJSON(`/api/macro/events/${id}/reaction`),
    getMacroSensitivityAssets: () => fetchJSON('/api/macro-sensitivity/assets'),
    getMacroSensitivityTicker: (ticker) => fetchJSON(`/api/macro-sensitivity/${ticker}`),
    getCrossAssetCorrelations: () => fetchJSON('/api/cross-asset/correlations'),
    getCrossAssetContagion: () => fetchJSON('/api/cross-asset/contagion'),
    getScenarioTemplates: () => fetchJSON('/api/scenario/templates'),
    postScenarioRun: (body) => postJSON('/api/scenario/run', body),
    getCrossAssetHedge: () => fetchJSON('/api/hedge/cross-asset'),
    postHedgePreview: (body) => postJSON('/api/hedge/preview', body),
    getPortfolioExplanation: () => fetchJSON('/api/explain/portfolio'),
    getRecommendationExplanation: (id) => fetchJSON(`/api/explain/recommendation/${id}`),
    getAgentsConsensus: () => fetchJSON('/api/agents/consensus'),
    getSignalOutcomes: () => fetchJSON('/api/signals/outcomes'),
    getSignalAttribution: () => fetchJSON('/api/signals/attribution'),
    getWatchlists: () => fetchJSON('/api/watchlists'),
    postWatchlist: (body) => postJSON('/api/watchlists', body),
    putWatchlist: (id, body) => putJSON(`/api/watchlists/${id}`, body),
    deleteWatchlist: (id) => deleteJSON(`/api/watchlists/${id}`),
    getDailyBriefReport: () => fetchJSON('/api/reports/daily-brief'),
    getTariffRiskReport: () => fetchJSON('/api/reports/tariff-risk'),
    getPortfolioRiskReport: () => fetchJSON('/api/reports/portfolio-risk'),
    getAgentSignalsReport: () => fetchJSON('/api/reports/agent-signals'),
    getGeopoliticalIndex: () => fetchJSON('/api/geopolitical/index'),
    getGeopoliticalEvents: () => fetchJSON('/api/geopolitical/events'),
    getGeopoliticalSanctions: () => fetchJSON('/api/geopolitical/sanctions'),
    getGeopoliticalSanctionsImpact: () => fetchJSON('/api/geopolitical/sanctions/impact'),
    getGeopoliticalSanctionsEntities: () => fetchJSON('/api/geopolitical/sanctions/entities'),
    getGeopoliticalConflicts: () => fetchJSON('/api/geopolitical/conflicts'),
    getGeopoliticalConflictHotspots: () => fetchJSON('/api/geopolitical/conflict/hotspots'),
    getGeopoliticalConflictEscalation: () => fetchJSON('/api/geopolitical/conflict/escalation'),
    getGeopoliticalConflictMarketImpact: () => fetchJSON('/api/geopolitical/conflict/market-impact'),
    getGeopoliticalChokepoints: () => fetchJSON('/api/geopolitical/chokepoints'),
    getGeopoliticalShippingRisk: () => fetchJSON('/api/geopolitical/shipping-risk'),
    getGeopoliticalSupplyChainImpact: () => fetchJSON('/api/geopolitical/supply-chain-impact'),
    getGeopoliticalEnergyShock: () => fetchJSON('/api/geopolitical/energy-shock'),
    getGeopoliticalCommodityImpact: () => fetchJSON('/api/geopolitical/commodity-impact'),
    getGeopoliticalMarketImpact: () => fetchJSON('/api/geopolitical/market-impact'),
    getGeopoliticalScenarioTemplates: () => fetchJSON('/api/geopolitical/scenario-templates'),
    postGeopoliticalScenarioRun: (body) => postJSON('/api/geopolitical/scenario-run', body),
    getProtectionStatus: () => fetchJSON('/api/protection/status'),
    postProtectionPreview: (body) => postJSON('/api/protection/preview', body),
    getGeopoliticalAgentSignals: () => fetchJSON('/api/geopolitical/agents/signals'),
    getGeopoliticalDailyBrief: () => fetchJSON('/api/geopolitical/reports/daily-brief'),
    getGeopoliticalProtectionBrief: () => fetchJSON('/api/geopolitical/reports/protection-brief'),

  };
})();
