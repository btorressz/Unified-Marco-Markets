const App = (() => {
  let activeTab = 'index';
  let refreshInterval = null;
  let initialized = false;
  let autoRefresh = true;
  let tabVisible = true;
  let wsMessageBuffer = [];
  let wsFlushTimer = null;
  let currentTheme = 'dark';
  const chartTimeframes = { index: '7d' };

  function init() {
    if (initialized) return;
    initialized = true;

    initTheme();
    initTabs();
    initCharts();
    initWebSocket();
    initOrderForm();
    initStressTestForm();
    initMCForm();
    initBacktestForm();
    initHeuristicPerformanceLab();
    initReplaySimForm();
    initScenarioForm();
    initGeoScenarioForm();
    initEquityControls();
    initProvenanceInspector();
    initFeedStatusToggle();
    initAutoRefreshToggle();
    initTimeframeSelectors();
    initVisibilityListener();

    refresh();
    refreshInterval = setInterval(refresh, 5000);

    console.log('[App] Tariff Risk Desk initialized');
  }

  function initTheme() {
    const saved = localStorage.getItem('theme') || 'dark';
    applyTheme(saved);
    const btn = document.getElementById('theme-toggle');
    if (btn) {
      btn.addEventListener('click', () => {
        const next = currentTheme === 'dark' ? 'light' : 'dark';
        applyTheme(next);
        localStorage.setItem('theme', next);
      });
    }
  }

  function applyTheme(theme) {
    currentTheme = theme;
    if (theme === 'light') {
      document.documentElement.setAttribute('data-theme', 'light');
    } else {
      document.documentElement.removeAttribute('data-theme');
    }
    const moonIcon = document.getElementById('theme-icon-moon');
    const sunIcon = document.getElementById('theme-icon-sun');
    const label = document.getElementById('theme-label');
    if (moonIcon) moonIcon.style.display = theme === 'dark' ? 'inline-block' : 'none';
    if (sunIcon) sunIcon.style.display = theme === 'light' ? 'inline-block' : 'none';
    if (label) label.textContent = theme === 'dark' ? 'DARK' : 'LIGHT';
    if (typeof Charts !== 'undefined' && Charts.reThemeAllCharts) {
      setTimeout(() => Charts.reThemeAllCharts(), 50);
    }
  }

  function initAutoRefreshToggle() {
    const btn = document.getElementById('auto-refresh-toggle');
    if (!btn) return;
    btn.addEventListener('click', () => {
      autoRefresh = !autoRefresh;
      btn.className = 'auto-refresh-toggle' + (autoRefresh ? ' on' : '');
      btn.innerHTML = `<span class="refresh-dot"></span> ${autoRefresh ? 'AUTO' : 'PAUSED'}`;
      if (autoRefresh) {
        refresh();
      }
    });
  }

  function initTimeframeSelectors() {
    document.querySelectorAll('.timeframe-selector').forEach(container => {
      const chartName = container.dataset.chart;
      container.querySelectorAll('.tf-btn').forEach(btn => {
        btn.addEventListener('click', () => {
          container.querySelectorAll('.tf-btn').forEach(b => b.classList.remove('active'));
          btn.classList.add('active');
          chartTimeframes[chartName] = btn.dataset.tf;
          refreshActiveTab();
        });
      });
    });
  }

  function initVisibilityListener() {
    document.addEventListener('visibilitychange', () => {
      tabVisible = !document.hidden;
      if (tabVisible && autoRefresh) {
        refresh();
      }
    });
  }

  function initTabs() {
    document.querySelectorAll('.tab-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        const tab = btn.dataset.tab;
        if (tab) switchTab(tab);
      });
    });
  }

  function switchTab(tab) {
    activeTab = tab;
    document.querySelectorAll('.tab-btn').forEach(b => b.classList.toggle('active', b.dataset.tab === tab));
    document.querySelectorAll('.tab-panel').forEach(p => p.classList.toggle('active', p.id === 'tab-' + tab));
    refreshActiveTab();
  }

  function initCharts() {
    window._indexChart = Charts.createIndexChart('index-chart');
    window._fundingChart = Charts.createFundingChart('funding-chart');
    window._divergenceChart = Charts.createDivergenceChart('divergence-chart');
    window._mcChart = Charts.createMCChart('mc-chart');
    window._equityChart = Charts.createEquityChart('equity-chart');
    window._geoRiskChart = Charts.createGeoRiskChart('geo-risk-chart');

  }

  function initWebSocket() {
    WS.on('connectionChange', (connected) => {
      UI.updateConnectionStatus(connected);
    });

    WS.on('message', (data) => {
      if (data.type === 'snapshot') {
        UI.addEventToTimeline({ event_type: 'CONNECTED', source: 'ws', ts: data.ts, payload: { message: data.message } }, true);
      } else if (data.type === 'pong') {
        return;
      } else {
        wsMessageBuffer.push(data);
        if (!wsFlushTimer) {
          wsFlushTimer = setTimeout(flushWsMessages, 200);
        }
      }
    });

    WS.connect();
  }

  function flushWsMessages() {
    wsFlushTimer = null;
    const batch = wsMessageBuffer.splice(0);
    batch.forEach(msg => UI.addEventToTimeline(msg, true));
  }

  function initOrderForm() {
    const form = document.getElementById('order-form');
    if (!form) return;
    form.addEventListener('submit', async (e) => {
      e.preventDefault();
      const btn = form.querySelector('button[type="submit"]');
      btn.disabled = true; btn.textContent = 'Submitting...';
      const order = {
        venue: form.venue.value, market: form.market.value, side: form.side.value,
        size: Number(form.size.value), price: form.price.value ? Number(form.price.value) : null,
        order_type: form.order_type.value, slippage_bps: Number(form.slippage_bps.value),
      };
      try {
        const result = await API.postOrder(order);
        UI.renderLastOrderResult(result);
        UI.addEventToTimeline({ event_type: 'ORDER_SUBMITTED', source: 'user', ts: new Date().toISOString(), payload: { message: `${order.side} ${order.size} ${order.market} on ${order.venue}`, order_id: result.order_id, request_id: result.request_id } }, true);
        refreshActiveTab();
      } catch (err) {
        UI.renderLastOrderResult({ status: 'rejected', error: err.message });
        UI.addEventToTimeline({ event_type: 'ORDER_REJECTED', source: 'user', ts: new Date().toISOString(), payload: { message: err.message } }, true);
      } finally { btn.disabled = false; btn.textContent = 'Submit Order'; }
    });
  }

  function initStressTestForm() {
    const form = document.getElementById('stress-form');
    if (!form) return;
    form.addEventListener('submit', async (e) => {
      e.preventDefault();
      const btn = form.querySelector('button[type="submit"]');
      btn.disabled = true;
      btn.textContent = 'Running...';

      try {
        const scenario = form.scenario.value;
        const result = await API.postStressTest({ scenario });
        UI.renderRiskTab({ stressResult: result });
      } catch (err) {
        UI.addEventToTimeline({ event_type: 'ERROR', source: 'stress_test', ts: new Date().toISOString(), payload: { message: 'Stress test failed: ' + err.message } }, true);
      } finally {
        btn.disabled = false;
        btn.textContent = 'Run Test';
      }
    });
  }

  function convertHorizonToHours(value, unit) {
    switch (unit) {
      case 'minutes': return Math.max(0.02, Math.round(value / 60 * 100) / 100);
      case 'days': return Math.min(48, value * 24);
      default: return value;
    }
  }

  function formatHorizonSummary(value, unit) {
    const label = value === 1 ? unit.replace(/s$/, '') : unit;
    return `Horizon: ${value} ${label}`;
  }

  function initMCForm() {
    const form = document.getElementById('mc-form');
    if (!form) return;
    form.addEventListener('submit', async (e) => {
      e.preventDefault();
      const btn = form.querySelector('button[type="submit"]');
      btn.disabled = true;
      btn.textContent = 'Running...';

      try {
        const horizonValue = parseFloat(form.horizon_value.value);
        const horizonUnit = form.horizon_unit.value;
        const horizonHours = convertHorizonToHours(horizonValue, horizonUnit);

        const summaryEl = document.getElementById('mc-horizon-summary');
        if (summaryEl) {
          summaryEl.textContent = formatHorizonSummary(horizonValue, horizonUnit);
          summaryEl.style.display = 'block';
        }

        const params = {
          symbol: form.symbol.value,
          position_size: parseFloat(form.position_size.value),
          horizon_hours: horizonHours,
          n_paths: parseInt(form.n_paths.value),
        };
        const result = await API.postMonteCarlo(params);
        UI.renderRiskTab({ mcResult: result });
      } catch (err) {
        UI.addEventToTimeline({ event_type: 'ERROR', source: 'monte_carlo', ts: new Date().toISOString(), payload: { message: 'MC simulation failed: ' + err.message } }, true);
      } finally {
        btn.disabled = false;
        btn.textContent = 'Run MC';
      }
    });
  }

  const HISTORICAL_SYMBOL_FALLBACK = { drift: 'SOL-PERP', pyth: 'SOL/USD', kraken: 'SOLUSD', coingecko: 'SOLANA/USD' };
  let historicalSymbolDefaults = { ...HISTORICAL_SYMBOL_FALLBACK };

  function initBacktestForm() {
    const form = document.getElementById('backtest-form');
    if (!form) return;
    const mode = form.elements.mode;
    const syntheticVenues = Array.from(form.venue.options).map(o => ({ value: o.value, label: o.textContent }));
    const historicalVenues = ['drift', 'pyth', 'kraken', 'coingecko'];
    let advanced = false;
    const setVenues = (historical) => {
      const previous = form.venue.value;
      const choices = historical ? historicalVenues.map(value => ({ value, label: value[0].toUpperCase() + value.slice(1) })) : syntheticVenues;
      form.venue.innerHTML = choices.map(o => `<option value="${o.value}">${o.label}</option>`).join('');
      form.venue.value = choices.some(o => o.value === previous) ? previous : choices[0].value;
    };
    const suggestSymbol = () => { if (mode.value === 'historical' && historicalSymbolDefaults[form.venue.value]) form.symbol.value = historicalSymbolDefaults[form.venue.value]; };
    const syncMode = () => {
      const historical = mode.value === 'historical';
      document.querySelectorAll('#backtest-form [data-historical-only]').forEach(el => { el.hidden = !historical || (el.hasAttribute('data-advanced-only') && !advanced); });
      document.querySelectorAll('#backtest-form [data-synthetic-only]').forEach(el => { el.hidden = historical; });
      form.querySelector('[data-historical-strategy]').disabled = !historical;
      if (!historical && form.strategy.value === 'recorded_orders') form.strategy.value = 'momentum';
      setVenues(historical); suggestSymbol();
      document.getElementById('backtest-mode-banner').innerHTML = historical
        ? '<span class="backtest-mode-badge historical-badge">HISTORICAL EVENT-TIME REPLAY</span> Persisted observations only. No synthetic fallback.'
        : '<span class="backtest-mode-badge">SYNTHETIC RESEARCH SIMULATION</span> Uses the deterministic seeded research price path. This is not historical market replay.';
    };
    mode.addEventListener('change', syncMode);
    form.venue.addEventListener('change', suggestSymbol);
    document.getElementById('backtest-advanced-toggle').addEventListener('click', e => { advanced = !advanced; e.currentTarget.textContent = advanced ? 'Hide Advanced' : 'Advanced'; syncMode(); });
    form.addEventListener('submit', async (e) => {
      e.preventDefault(); const btn = form.querySelector('button[type="submit"]'); const panel = document.getElementById('backtest-result-panel');
      const number = name => Number(form.elements[name].value);
      const historical = mode.value === 'historical';
      const config = { mode: historical ? 'historical' : 'synthetic', strategy: form.strategy.value, window_days: number('window_days'), initial_capital: number('initial_capital'), venue: form.venue.value, slippage_bps: number('slippage_bps') };
      try {
        if (!(config.initial_capital > 0) || config.slippage_bps < 0) throw new Error('Capital must be positive and slippage cannot be negative.');
        if (!historical) config.fee_bps = number('fee_bps');
        else {
          Object.assign(config, { market: form.market.value.trim(), symbol: form.symbol.value.trim(), latency_ms: number('latency_ms'), maker_fee_bps: number('maker_fee_bps'), taker_fee_bps: number('taker_fee_bps'), fill_model: form.fill_model.value, partial_fill_ratio: number('partial_fill_ratio'), allocation_limit: number('allocation_limit'), max_gross_leverage: number('max_gross_leverage'), decision_interval_seconds: number('decision_interval_seconds'), walk_forward: form.walk_forward.checked, train_window_days: number('train_window_days'), test_window_days: number('test_window_days'), step_days: number('step_days'), close_at_end: form.close_at_end.checked });
          if (form.start_ts.value) config.start_ts = new Date(form.start_ts.value).toISOString();
          if (form.end_ts.value) config.end_ts = new Date(form.end_ts.value).toISOString();
          if (config.start_ts && config.end_ts && new Date(config.start_ts) >= new Date(config.end_ts)) throw new Error('Start date/time must be before end date/time.');
          if (config.latency_ms < 0 || config.maker_fee_bps < 0 || config.taker_fee_bps < 0) throw new Error('Latency and fees cannot be negative.');
          if (!(config.partial_fill_ratio > 0 && config.partial_fill_ratio <= 1)) throw new Error('Partial fill ratio must be greater than 0 and at most 1.');
          if (!(config.allocation_limit > 0 && config.allocation_limit <= 1) || !(config.max_gross_leverage > 0)) throw new Error('Allocation limit must be in (0, 1] and max leverage must be positive.');
        }
        btn.disabled = true; btn.textContent = 'Running...'; panel.innerHTML = '<div class="empty-state-text">Running backtest...</div>';
        const result = await API.postBacktestRun(config); UI.renderBacktestPanel(result); await refreshBacktestSupport();
      } catch (err) { UI.renderBacktestError(err.message); }
      finally { btn.disabled = false; btn.textContent = 'Run Backtest'; }
    });
    syncMode(); refreshBacktestSupport();
  }

  async function refreshBacktestSupport() {
    const [coverage, history] = await Promise.allSettled([API.getBacktestDataCoverage(), API.getBacktestHistory()]);
    if (coverage.status === 'fulfilled') {
      historicalSymbolDefaults = { ...HISTORICAL_SYMBOL_FALLBACK, ...(coverage.value.historical_symbol_defaults || {}) };
      UI.renderBacktestCoverage(coverage.value);
    } else UI.renderBacktestCoverage(null);
    UI.renderBacktestHistory(history.status === 'fulfilled' ? history.value : null, async runId => {
      try { UI.renderBacktestPanel(await API.getBacktestRun(runId)); } catch (err) { UI.renderBacktestError(err.message); }
    });
  }

  function initFeedStatusToggle() {
    const btn = document.getElementById('feed-status-toggle');
    const panel = document.getElementById('feed-status-panel');
    if (btn && panel) {
      btn.addEventListener('click', () => {
        const hidden = panel.style.display === 'none';
        panel.style.display = hidden ? 'block' : 'none';
        btn.textContent = hidden ? 'Hide' : 'Show';
      });
    }
  }

  async function refresh() {
    if (!autoRefresh || !tabVisible) return;
    refreshHealth();
    refreshTimeline();
    refreshActiveTab();
  }

  async function refreshActiveTab() {
    try {
      switch (activeTab) {
        case 'index': await refreshIndex(); break;
        case 'markets': await refreshMarkets(); break;
        case 'divergence': await refreshDivergence(); break;
        case 'stablecoins': await refreshStablecoins(); break;
        case 'strategy': await refreshStrategy(); break;
        case 'execution': await refreshExecution(); break;
        case 'equities': await refreshEquities(); break;
        case 'geopolitics': await refreshGeopolitics(); break;
        case 'risk': await refreshRisk(); break;
        case 'agents': await refreshAgents(); break;
        case 'decisions': await refreshDecisionAudit(); break;
      }
    } catch (err) {
      console.error(`[App] Error refreshing ${activeTab}:`, err);
    }
  }

  async function refreshIndex() {
    const tf = chartTimeframes.index || '7d';
    const [latest, history, components, prediction, macroTerminal, macroEvents, macroImpact] = await Promise.allSettled([
      API.getIndexLatest(),
      API.getIndexHistory(tf),
      API.getIndexComponents(),
      API.getPrediction(),
      API.getMacroTerminal(),
      API.getMacroEvents(),
      API.getMacroEventsImpact(),
    ]);
    UI.renderIndexTab({
      latest: latest.status === 'fulfilled' ? latest.value : null,
      history: history.status === 'fulfilled' ? history.value : null,
      components: components.status === 'fulfilled' ? components.value : null,
      prediction: prediction.status === 'fulfilled' ? prediction.value : null,
      macroTerminal: macroTerminal.status === 'fulfilled' ? macroTerminal.value : null,
    });
    if (macroEvents.status === 'fulfilled') UI.renderMacroEvents(macroEvents.value, macroImpact.status === 'fulfilled' ? macroImpact.value : null);
  }

  async function refreshMarkets() {
    const [latest, funding, carry, microstructure, integrity, solanaQuality, fundingArb, basis, feedStatus, researchHistoryCoverage] = await Promise.allSettled([
      API.getMarketLatest(),
      API.getFunding(),
      API.getCarry(),
      API.getMicrostructure(),
      API.getIntegrity(),
      API.getSolanaQuality(),
      API.getFundingArb(),
      API.getBasisLatest(),
      API.getFeedStatus(),
      API.getResearchHistoryCoverage(),
    ]);
    UI.renderMarketsTab({
      latest: latest.status === 'fulfilled' ? latest.value : null,
      funding: funding.status === 'fulfilled' ? funding.value : null,
      carry: carry.status === 'fulfilled' ? carry.value : null,
      microstructure: microstructure.status === 'fulfilled' ? microstructure.value : null,
      integrity: integrity.status === 'fulfilled' ? integrity.value : null,
      solanaQuality: solanaQuality.status === 'fulfilled' ? solanaQuality.value : null,
      fundingArb: fundingArb.status === 'fulfilled' ? fundingArb.value : null,
      basis: basis.status === 'fulfilled' ? basis.value : null,
      researchHistoryCoverage: researchHistoryCoverage.status === 'fulfilled' ? researchHistoryCoverage.value : null,
    });
    if (feedStatus.status === 'fulfilled') {
      UI.renderFeedStatus(feedStatus.value);
    }
  }

  async function refreshDivergence() {
    const [spreads, alerts] = await Promise.allSettled([
      API.getDivergenceSpreads(),
      API.getDivergenceAlerts(),
    ]);
    UI.renderDivergenceTab({
      spreads: spreads.status === 'fulfilled' ? spreads.value : null,
      alerts: alerts.status === 'fulfilled' ? alerts.value : null,
    });
  }

  async function refreshStablecoins() {
    const [health, alerts, stableFlow] = await Promise.allSettled([
      API.getStablecoinHealth(),
      API.getStablecoinAlerts(),
      API.getStableFlow(),
    ]);
    UI.renderStablecoinsTab({
      health: health.status === 'fulfilled' ? health.value : null,
      alerts: alerts.status === 'fulfilled' ? alerts.value : null,
      stableFlow: stableFlow.status === 'fulfilled' ? stableFlow.value : null,
    });
  }

  function populateHeuristicRegistry(data) {
    const selector = document.getElementById('heuristic-selector');
    if (!selector || selector.dataset.loaded) return;
    (data.heuristics || []).filter(rule => rule.active).forEach(rule => selector.add(new Option(`${rule.id}:v${rule.version}`, rule.id)));
    selector.dataset.loaded = 'true';
  }

  function initHeuristicPerformanceLab() {
    const form = document.getElementById('heuristic-performance-form');
    if (!form) return;
    form.venue.addEventListener('change', () => { if (historicalSymbolDefaults[form.venue.value]) form.symbol.value = historicalSymbolDefaults[form.venue.value]; });
    form.addEventListener('submit', async event => {
      event.preventDefault(); const button = form.querySelector('button[type="submit"]');
      const config = { heuristic_ids: form.heuristic_id.value ? [form.heuristic_id.value] : [], venue: form.venue.value,
        market: form.market.value.trim(), symbol: form.symbol.value.trim(), window_days: Number(form.window_days.value),
        primary_horizon: form.primary_horizon.value, decision_interval_seconds: Number(form.decision_interval_seconds.value), persist: true };
      if (form.start_ts.value) config.start_ts = new Date(form.start_ts.value).toISOString();
      if (form.end_ts.value) config.end_ts = new Date(form.end_ts.value).toISOString();
      try {
        button.disabled = true; button.textContent = 'Validating...';
        UI.renderHeuristicPerformance(await API.postHeuristicEvaluate(config));
        await refreshHeuristicPerformance();
      } catch (error) { UI.renderHeuristicPerformanceError(error.message); }
      finally { button.disabled = false; button.textContent = 'Run Historical Validation'; }
    });
  }

  async function refreshHeuristicPerformance() {
    try { UI.renderHeuristicPerformance(await API.getHeuristicPerformance()); } catch (_) { /* Optional persisted research read. */ }
  }

  async function refreshStrategy() {
    const [evaluation, status, adaptiveWeights, portfolio, allocation, mlPrediction, strategyPerformance, backtestResult, heuristicRegistry, heuristicPerformance, mlModels, mlActive, mlRuns, mlHealth, mlComparison] = await Promise.allSettled([
      API.getRulesEvaluation(),
      API.getRulesStatus(),
      API.getAdaptiveWeights(),
      API.getPortfolioProposal(),
      API.getAllocationLatest(),
      API.getMLPredictionLatest(),
      API.getStrategyPerformance(),
      API.getBacktestLatest(),
      API.getHeuristicRegistry(),
      API.getHeuristicPerformance(),
      API.getMLModels(), API.getMLActiveModel(), API.getMLTrainingRuns(), API.getMLModelHealth(), API.getMLComparison(),
    ]);
    UI.renderStrategyTab({
      evaluation: evaluation.status === 'fulfilled' ? evaluation.value : null,
      status: status.status === 'fulfilled' ? status.value : null,
      adaptiveWeights: adaptiveWeights.status === 'fulfilled' ? adaptiveWeights.value : null,
      portfolio: portfolio.status === 'fulfilled' ? portfolio.value : null,
      allocation: allocation.status === 'fulfilled' ? allocation.value : null,
      mlPrediction: mlPrediction.status === 'fulfilled' ? mlPrediction.value : null,
      backtestResult: backtestResult.status === 'fulfilled' ? backtestResult.value : undefined,
    });
    if (strategyPerformance.status === 'fulfilled') UI.renderStrategyPerformance(strategyPerformance.value);
    if (heuristicRegistry.status === 'fulfilled') populateHeuristicRegistry(heuristicRegistry.value);
    if (heuristicPerformance.status === 'fulfilled') UI.renderHeuristicPerformance(heuristicPerformance.value);
    UI.renderMLGovernance({
      models: mlModels.status === 'fulfilled' ? mlModels.value.models : [], active: mlActive.status === 'fulfilled' ? mlActive.value.model : null,
      runs: mlRuns.status === 'fulfilled' ? mlRuns.value.runs : [], health: mlHealth.status === 'fulfilled' ? mlHealth.value : {status:'unknown'},
      comparison: mlComparison.status === 'fulfilled' ? mlComparison.value : {comparable:false,reason:'Unavailable'}
    });
  }

  async function refreshExecution() {
    const [positions, trades, eqi, integrity, health, indexData, preview, conditional, smart, guardrails, events] = await Promise.allSettled([
      API.getPositions(),
      API.getPaperTrades(),
      API.getEQI(),
      API.getIntegrity(),
      API.getHealth(),
      API.getIndexLatest(),
      API.postAllocationExecutionPreview({ venue: 'paper', market: 'SOL-PERP', side: 'buy', size: 1, price: 150 }),
      API.getConditionalOrders(),
      API.getSmartOrders(),
      API.getGuardrails(),
      API.getEvents(100),
    ]);
    UI.renderDecisionDataPanel({
      integrity: integrity.status === 'fulfilled' ? integrity.value : null,
      health: health.status === 'fulfilled' ? health.value : null,
      indexData: indexData.status === 'fulfilled' ? indexData.value : null,
    });
    UI.renderExecutionTab({
      positions: positions.status === 'fulfilled' ? positions.value : null,
      trades: trades.status === 'fulfilled' ? trades.value : null,
      eqi: eqi.status === 'fulfilled' ? eqi.value : null,
      guardrails: guardrails.status === 'fulfilled' ? guardrails.value : null,
      events: events.status === 'fulfilled' ? events.value : null,
    });
    UI.renderExecutionEnhancements({ preview: preview.status === 'fulfilled' ? preview.value : null, conditional: conditional.status === 'fulfilled' ? conditional.value : null, smart: smart.status === 'fulfilled' ? smart.value : null });
  }





  function initReplaySimForm() {
    const form = document.getElementById('replay-sim-form');
    if (!form) return;
    form.addEventListener('submit', async (e) => {
      e.preventDefault();
      try {
        const result = await API.postReplayTradeSimulation({ scenario: form.scenario.value, initial_capital: parseFloat(form.initial_capital.value || '100000') });
        UI.renderReplaySimulation(result);
      } catch (err) {
        UI.addEventToTimeline({ event_type: 'ERROR', source: 'replay_sim', ts: new Date().toISOString(), payload: { message: err.message } }, true);
      }
    });
  }

  function initEquityControls() {
    const select = document.getElementById('equity-ticker-select');
    if (select) select.addEventListener('change', () => refreshEquities());
  }


  function initScenarioForm() {
    const form = document.getElementById('scenario-form');
    if (!form) return;
    form.addEventListener('submit', async (e) => {
      e.preventDefault();
      try {
        const body = {
          tariff_index_change: parseFloat(form.tariff_index_change.value || '0'),
          gdelt_shock_change: parseFloat(form.gdelt_shock_change.value || '0'),
          equity_drawdown: parseFloat(form.equity_drawdown.value || '0'),
          crypto_drawdown: parseFloat(form.crypto_drawdown.value || '0'),
        };
        const result = await API.postScenarioRun(body);
        UI.renderScenarioResult(result);
      } catch (err) {
        UI.addEventToTimeline({ event_type: 'ERROR', source: 'scenario', ts: new Date().toISOString(), payload: { message: err.message } }, true);
      }
    });
  }



  function initGeoScenarioForm() {
    const form = document.getElementById('geo-scenario-form');
    if (!form) return;
    form.addEventListener('submit', async (e) => {
      e.preventDefault();
      const btn = form.querySelector('button[type="submit"]');
      if (btn) {
        btn.disabled = true;
        btn.textContent = 'Running...';
      }
      try {
        const fieldNumber = (name, fallback = '0') => parseFloat((form.elements[name] || {}).value || fallback);
        const body = {
          scenario_name: (form.elements.scenario_name || {}).value || 'Middle East escalation',
          severity: fieldNumber('severity', '55'),
          regions: ['Middle East', 'Asia-Pacific'],
          affected_assets: ['SPY', 'QQQ', 'SMH', 'XLE', 'BTC', 'ETH'],
          conflict_shock: fieldNumber('conflict_shock'),
          energy_shock: fieldNumber('energy_shock'),
          sanctions_shock: fieldNumber('sanctions_shock'),
          shipping_shock: fieldNumber('shipping_shock'),
          cyber_policy_shock: fieldNumber('cyber_policy_shock'),
          stablecoin_stress: fieldNumber('stablecoin_stress'),
          volatility_spike: fieldNumber('volatility_spike'),
          liquidity_depth_drop: fieldNumber('liquidity_depth_drop'),
        };
        const result = await API.postGeopoliticalScenarioRun(body);
        UI.renderGeoScenarioResult(result);
      } catch (err) {
        UI.addEventToTimeline({ event_type: 'ERROR', source: 'geopolitical_scenario', ts: new Date().toISOString(), payload: { message: err.message } }, true);
      } finally {
        if (btn) {
          btn.disabled = false;
          btn.textContent = 'Run Geopolitical Scenario';
        }
      }
    });
  }


  async function refreshEquities() {
    const ticker = (document.getElementById('equity-ticker-select') || {}).value || 'SPY';
    const [overview, history, risk, tariff, cross, quality, sensitivity, correlations, contagion, watchlists, dailyBrief, tariffReport] = await Promise.allSettled([
      API.getEquitiesOverview(),
      API.getEquityHistory(ticker),
      API.getEquityRisk(),
      API.getEquityTariffExposure(),
      API.getEquityCrossAsset(),
      API.getDataQuality(),
      API.getMacroSensitivityAssets(),
      API.getCrossAssetCorrelations(),
      API.getCrossAssetContagion(),
      API.getWatchlists(),
      API.getDailyBriefReport(),
      API.getTariffRiskReport(),
    ]);
    UI.renderEquitiesTab({
      overview: overview.status === 'fulfilled' ? overview.value : null,
      history: history.status === 'fulfilled' ? history.value : null,
      risk: risk.status === 'fulfilled' ? risk.value : null,
      tariff: tariff.status === 'fulfilled' ? tariff.value : null,
      cross: cross.status === 'fulfilled' ? cross.value : null,
      quality: quality.status === 'fulfilled' ? quality.value : null,
    });
    UI.renderInstitutionalLayer({ sensitivity: sensitivity.status === 'fulfilled' ? sensitivity.value : null, correlations: correlations.status === 'fulfilled' ? correlations.value : null, contagion: contagion.status === 'fulfilled' ? contagion.value : null, watchlists: watchlists.status === 'fulfilled' ? watchlists.value : null, dailyBrief: dailyBrief.status === 'fulfilled' ? dailyBrief.value : null, tariffReport: tariffReport.status === 'fulfilled' ? tariffReport.value : null });

  }

  async function refreshIngestionStatus() {
    const [registry, status] = await Promise.allSettled([API.getIngestionRegistry(), API.getIngestionStatus()]);
    if (registry.status === 'fulfilled') UI.renderIngestionRegistry(registry.value);
    if (status.status === 'fulfilled') UI.renderIngestionStatus(status.value);
  }
  async function refreshIngestionRuns() { try { UI.renderIngestionRuns(await API.getIngestionRuns({limit: 30})); } catch (_) {} }
  function initProvenanceInspector() {
    const form=document.getElementById('provenance-form'); if(!form)return;
    form.addEventListener('submit', async event => { event.preventDefault(); const params=Object.fromEntries(new FormData(form)); UI.renderDataProvenance(await API.getDataProvenance(params)); });
    refreshIngestionStatus(); refreshIngestionRuns();
    setInterval(refreshIngestionStatus, 30000); setInterval(refreshIngestionRuns, 60000);
  }


  async function refreshGeopolitics() {
    const [index, events, reactionEvents, reactionStatistics, sanctions, conflicts, chokepoints, energy, impact, protection, agentSignals, dailyBrief, protectionBrief] = await Promise.allSettled([
      API.getGeopoliticalIndex(),
      API.getGeopoliticalEvents(),
      API.getGeopoliticalReactionEvents(),
      API.getGeopoliticalReactionStatistics({limit: 100}),
      API.getGeopoliticalSanctions(),
      API.getGeopoliticalConflicts(),
      API.getGeopoliticalChokepoints(),
      API.getGeopoliticalEnergyShock(),
      API.getGeopoliticalMarketImpact(),
      API.getProtectionStatus(),
      API.getGeopoliticalAgentSignals(),
      API.getGeopoliticalDailyBrief(),
      API.getGeopoliticalProtectionBrief(),
    ]);
    let reactionStudy = null;
    const catalog = reactionEvents.status === 'fulfilled' ? reactionEvents.value : null;
    const firstEligible = ((catalog || {}).events || []).find(event => event.study_eligible);
    if (firstEligible) {
      try { reactionStudy = await API.getGeopoliticalReactionStudy(firstEligible.event_id); } catch (_) { /* strict history may be unavailable */ }
    }
    UI.renderGeopoliticsTab({
      index: index.status === 'fulfilled' ? index.value : null,
      events: events.status === 'fulfilled' ? events.value : null,
      reactionEvents: catalog,
      reactionStudy,
      reactionStatistics: reactionStatistics.status === 'fulfilled' ? reactionStatistics.value : null,
      sanctions: sanctions.status === 'fulfilled' ? sanctions.value : null,
      conflicts: conflicts.status === 'fulfilled' ? conflicts.value : null,
      chokepoints: chokepoints.status === 'fulfilled' ? chokepoints.value : null,
      energy: energy.status === 'fulfilled' ? energy.value : null,
      impact: impact.status === 'fulfilled' ? impact.value : null,
      protection: protection.status === 'fulfilled' ? protection.value : null,
      agentSignals: agentSignals.status === 'fulfilled' ? agentSignals.value : null,
      dailyBrief: dailyBrief.status === 'fulfilled' ? dailyBrief.value : null,
      protectionBrief: protectionBrief.status === 'fulfilled' ? protectionBrief.value : null,
    });

  }

  async function refreshRisk() {
    const [status, guardrails, heatmap, analogs, portfolioRisk, contributions, exposures, redis, volRegime, volRecs, hedge, explain] = await Promise.allSettled([
      API.getRiskStatus(), API.getGuardrails(), API.getLiquidationHeatmap(), API.getRegimeAnalogs(),
      API.getPortfolioRiskSummary(), API.getPortfolioRiskContributions(), API.getPortfolioRiskExposures(), API.getRedisHealth(),
      API.getVolRegime(), API.getVolRecommendations(), API.getCrossAssetHedge(), API.getPortfolioExplanation(),
    ]);
    UI.renderRiskTab({
      status: status.status === 'fulfilled' ? status.value : null, guardrails: guardrails.status === 'fulfilled' ? guardrails.value : null,
      heatmap: heatmap.status === 'fulfilled' ? heatmap.value : null, analogs: analogs.status === 'fulfilled' ? analogs.value : null,
      portfolioRisk: portfolioRisk.status === 'fulfilled' ? portfolioRisk.value : null,
      portfolioContributions: contributions.status === 'fulfilled' ? contributions.value : null,
      portfolioExposures: exposures.status === 'fulfilled' ? exposures.value : null,
      redis: redis.status === 'fulfilled' ? redis.value : null,
      volRegime: volRegime.status === 'fulfilled' ? volRegime.value : null, volRecommendations: volRecs.status === 'fulfilled' ? volRecs.value : null,
    });
    UI.renderRiskIntelligence({ hedge: hedge.status === 'fulfilled' ? hedge.value : null, explain: explain.status === 'fulfilled' ? explain.value : null });
  }

  async function refreshAgents() {
    const [signals, registry, perf, hist, consensus, attribution] = await Promise.allSettled([
      API.getAgentSignals(),
      API.getAgentRegistry(),
      API.getAgentsPerformance(),
      API.getAgentsHistory(),
      API.getAgentsConsensus(),
      API.getSignalAttribution(),
    ]);
    UI.renderAgentsTab({
      signals: signals.status === 'fulfilled' ? signals.value : null,
      registry: registry.status === 'fulfilled' ? registry.value : null,
    });
    UI.renderAgentMemory(perf.status === 'fulfilled' ? perf.value : null, hist.status === 'fulfilled' ? hist.value : null);
    UI.renderAgentConsensusAndAttribution(consensus.status === 'fulfilled' ? consensus.value : null, attribution.status === 'fulfilled' ? attribution.value : null);
  }

  async function refreshDecisionAudit() {
    try { UI.renderDecisionList(await API.getDecisions({limit: 50})); }
    catch (error) { UI.renderDecisionList({decisions: [], error: error.message}); }
  }

  async function showDecision(id) {
    try { UI.renderDecisionDetail(await API.getDecision(id)); }
    catch (error) { UI.renderDecisionDetail({error: error.message}); }
  }

  async function replayDecision(id) {
    const panel=document.getElementById('decision-replay-result');
    if(panel) panel.textContent='Reconstructing stored decision...';
    try { UI.renderDecisionReplay(await API.postDecisionReplay(id)); }
    catch (error) { UI.renderDecisionReplay({replay_status:'unavailable', reason:error.message}); }
  }

  async function refreshHealth() {
    try {
      const health = await API.getHealth();
      const el = document.getElementById('health-info');
      if (el) {
        const dbIcon = health.database ? '\u25CF' : '\u25CB';
        const dbColor = health.database ? 'var(--accent-green)' : 'var(--accent-red)';
        el.innerHTML = `<span style="color:${dbColor}">${dbIcon}</span> DB &nbsp; <span style="color:var(--text-muted)">v${health.version || '0.1.0'}</span>`;
      }
    } catch {}
  }

  async function refreshTimeline() {
    try {
      const events = await API.getEvents(50);
      UI.renderTimeline(events);
    } catch {}
  }

  return { init, switchTab, showDecision, replayDecision, refreshDecisionAudit };
})();

document.addEventListener('DOMContentLoaded', App.init);
