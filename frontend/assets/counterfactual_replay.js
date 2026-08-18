(() => {
  'use strict';

  const DETAIL_ID = 'decision-audit-detail';
  const RESULT_ID = 'decision-counterfactual-result';
  let selectedDecisionId = null;

  function escapeHtml(value) {
    return String(value == null ? '' : value)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#039;');
  }

  function extractDecisionId(panel) {
    const replayButton = Array.from(panel.querySelectorAll('button')).find(btn =>
      String(btn.getAttribute('onclick') || '').includes('replayDecision(')
    );
    const onclick = replayButton && replayButton.getAttribute('onclick');
    const match = onclick && onclick.match(/replayDecision\('([^']+)'\)/);
    return match ? match[1] : null;
  }

  function field(name, label, type = 'number', extra = '') {
    return `<label style="display:flex;flex-direction:column;gap:4px;font-size:11px;color:var(--text-muted)">${escapeHtml(label)}<input data-cf-field="${escapeHtml(name)}" type="${type}" ${extra} style="background:var(--bg-secondary);color:var(--text-primary);border:1px solid var(--border-color);border-radius:4px;padding:7px"></label>`;
  }

  function selectField(name, label, options) {
    return `<label style="display:flex;flex-direction:column;gap:4px;font-size:11px;color:var(--text-muted)">${escapeHtml(label)}<select data-cf-field="${escapeHtml(name)}" style="background:var(--bg-secondary);color:var(--text-primary);border:1px solid var(--border-color);border-radius:4px;padding:7px"><option value="">UNCHANGED</option>${options.map(v => `<option value="${escapeHtml(v)}">${escapeHtml(v)}</option>`).join('')}</select></label>`;
  }

  function attach(panel) {
    const id = extractDecisionId(panel);
    if (!id) return;
    selectedDecisionId = id;
    if (panel.querySelector('[data-counterfactual-controls]')) return;

    const wrapper = document.createElement('div');
    wrapper.setAttribute('data-counterfactual-controls', 'true');
    wrapper.style.cssText = 'margin-top:16px;padding-top:14px;border-top:1px solid var(--border-color)';
    wrapper.innerHTML = `
      <h4 style="margin:0 0 6px">Counterfactual Scenario</h4>
      <div style="font-size:11px;color:var(--text-muted);margin-bottom:10px">Only fields present in this decision's immutable replay inputs are applied. Unused components remain unused.</div>
      <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:8px">
        ${field('shock_score', 'Shock score', 'number', 'step="any"')}
        ${selectField('vol_regime', 'Vol regime', ['low','normal','high','extreme'])}
        ${field('stable_health', 'Stable health', 'number', 'step="0.01" min="0" max="1"')}
        ${field('tariff_rate_of_change', 'Tariff rate of change', 'number', 'step="any"')}
        ${field('fill_price', 'Fill price', 'number', 'step="any" min="0"')}
        ${field('order_size', 'Order size', 'number', 'step="any" min="0"')}
        ${field('spread_bps', 'Spread (bps)', 'number', 'step="any" min="0"')}
        ${field('liquidity_depth', 'Liquidity depth', 'number', 'step="any" min="0"')}
        ${selectField('integrity_status', 'Price integrity', ['OK','WARNING','ERROR','UNKNOWN'])}
        ${field('daily_pnl', 'Historical daily P&L', 'number', 'step="any"')}
        ${selectField('outcome_horizon', 'Realized outcome horizon', ['1h','4h','24h','7d'])}
      </div>
      <div style="display:flex;gap:8px;align-items:center;margin-top:10px">
        <button type="button" data-run-counterfactual class="btn-primary">Run Counterfactual</button>
        <button type="button" data-clear-counterfactual class="btn">Clear</button>
      </div>
      <div class="audit-only-banner" style="margin-top:10px"><strong>COUNTERFACTUAL RESEARCH ONLY</strong> — No order is routed, no audit row is modified, and no model is retrained.</div>
      <div id="${RESULT_ID}" style="margin-top:12px"></div>`;
    panel.appendChild(wrapper);

    wrapper.querySelector('[data-run-counterfactual]').addEventListener('click', runCounterfactual);
    wrapper.querySelector('[data-clear-counterfactual]').addEventListener('click', () => {
      wrapper.querySelectorAll('[data-cf-field]').forEach(el => { el.value = ''; });
      const result = wrapper.querySelector(`#${RESULT_ID}`);
      if (result) result.innerHTML = '';
    });
  }

  function scenarioFromControls() {
    const panel = document.getElementById(DETAIL_ID);
    const scenario = {};
    panel.querySelectorAll('[data-cf-field]').forEach(el => {
      const name = el.getAttribute('data-cf-field');
      if (name === 'outcome_horizon' || el.value === '') return;
      scenario[name] = el.type === 'number' ? Number(el.value) : el.value;
    });
    return scenario;
  }

  function outcomeHorizonFromControls() {
    const panel = document.getElementById(DETAIL_ID);
    const field = panel && panel.querySelector('[data-cf-field="outcome_horizon"]');
    return field && field.value ? field.value : '4h';
  }

  function finalLabel(finalDecision) {
    const value = finalDecision || {};
    return String(value.decision || (value.allowed === true ? 'allow' : value.allowed === false ? 'block' : 'unknown')).toUpperCase();
  }

  function renderRealizedOutcome(realized) {
    if (!realized || realized.available !== true) {
      return `<h4>Realized Market Context</h4><div style="font-size:11px;color:var(--text-muted)">UNAVAILABLE${realized && realized.reason ? ` — ${escapeHtml(realized.reason)}` : ''}</div>`;
    }
    const original = realized.original || {};
    const counter = realized.counterfactual || {};
    const warnings = realized.warnings || [];
    return `
      <h4>Realized Market Context · ${escapeHtml(realized.horizon || '--')}</h4>
      <div class="card" style="padding:10px">
        <div style="font-size:12px">Requested-side market move: <strong>${(Number(realized.realized_signed_return || 0) * 100).toFixed(2)}%</strong></div>
        <div style="font-size:11px;color:var(--text-muted);margin-top:5px">Original ${escapeHtml(String(original.action || '--').toUpperCase())}: ${escapeHtml(original.interpretation || '--')}</div>
        <div style="font-size:11px;color:var(--text-muted)">Counterfactual ${escapeHtml(String(counter.action || '--').toUpperCase())}: ${escapeHtml(counter.interpretation || '--')}</div>
        <div style="font-size:11px;color:var(--text-muted)">Return basis: ${escapeHtml(realized.return_basis || '--')}</div>
        ${warnings.length ? `<div style="font-size:11px;color:var(--warning);margin-top:5px">${escapeHtml(warnings.join(' '))}</div>` : ''}
      </div>`;
  }

  function renderResult(result) {
    const panel = document.getElementById(RESULT_ID);
    if (!panel) return;
    if (result.error) {
      panel.innerHTML = `<div class="replay-verdict mismatch">UNAVAILABLE</div><p>${escapeHtml(result.error)}</p>`;
      return;
    }
    const originalFinal = result.effects && result.effects.original_final;
    const counterFinal = result.effects && result.effects.counterfactual_final;
    const changed = !!(result.effects && result.effects.final_decision_changed);
    const applied = result.applied_changes || {};
    const notApplicable = result.not_applicable || [];
    panel.innerHTML = `
      <div class="replay-verdict ${changed ? 'mismatch' : 'match'}">${changed ? 'DECISION CHANGED' : 'DECISION UNCHANGED'}</div>
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;margin:10px 0">
        <div class="card" style="padding:10px"><div style="font-size:11px;color:var(--text-muted)">ORIGINAL</div><div style="font-size:20px;font-weight:700">${escapeHtml(finalLabel(originalFinal))}</div><pre style="white-space:pre-wrap;font-size:11px">${escapeHtml(JSON.stringify(originalFinal || {}, null, 2))}</pre></div>
        <div class="card" style="padding:10px"><div style="font-size:11px;color:var(--text-muted)">COUNTERFACTUAL</div><div style="font-size:20px;font-weight:700">${escapeHtml(finalLabel(counterFinal))}</div><pre style="white-space:pre-wrap;font-size:11px">${escapeHtml(JSON.stringify(counterFinal || {}, null, 2))}</pre></div>
      </div>
      ${renderRealizedOutcome(result.realized_outcome)}
      <h4>Applied changes</h4><pre style="white-space:pre-wrap;font-size:11px">${escapeHtml(JSON.stringify(applied, null, 2))}</pre>
      ${notApplicable.length ? `<h4>Not applicable to this decision</h4><p>${escapeHtml(notApplicable.join(', '))}</p>` : ''}
      <div style="font-size:11px;color:var(--text-muted)">Changed canonical fields: ${Number((result.effects || {}).changed_fields || 0)}</div>
      <div class="audit-only-banner" style="margin-top:10px"><strong>RESEARCH / AUDIT ONLY</strong> — orders_submitted=${Number(result.orders_submitted || 0)}, persisted=${String(!!result.persisted)}.</div>`;
  }

  async function runCounterfactual() {
    const scenario = scenarioFromControls();
    const resultPanel = document.getElementById(RESULT_ID);
    if (!selectedDecisionId || Object.keys(scenario).length === 0) {
      renderResult({ error: 'Enter at least one counterfactual value.' });
      return;
    }
    if (resultPanel) resultPanel.textContent = 'Recomputing counterfactual from immutable replay inputs...';
    try {
      const response = await fetch(`/api/decisions/${encodeURIComponent(selectedDecisionId)}/counterfactual`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ scenario, outcome_horizon: outcomeHorizonFromControls() }),
      });
      let payload = null;
      try { payload = await response.json(); } catch (_) { payload = null; }
      if (!response.ok) {
        const detail = payload && payload.detail;
        throw new Error(typeof detail === 'string' ? detail : JSON.stringify(detail || `API ${response.status}`));
      }
      renderResult(payload);
    } catch (error) {
      renderResult({ error: error.message || String(error) });
    }
  }

  function scan() {
    const panel = document.getElementById(DETAIL_ID);
    if (panel) attach(panel);
  }

  const observer = new MutationObserver(scan);
  const start = () => {
    const panel = document.getElementById(DETAIL_ID);
    if (panel) observer.observe(panel, { childList: true, subtree: true });
    scan();
  };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start);
  else start();
})();
