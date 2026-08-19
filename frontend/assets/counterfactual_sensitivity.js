(() => {
  'use strict';

  const DETAIL_ID = 'decision-audit-detail';
  const RESULT_ID = 'decision-sensitivity-result';
  const NUMERIC_FIELDS = [
    'spread_bps', 'liquidity_depth', 'order_size', 'fill_price', 'daily_pnl',
    'shock_score', 'stable_health', 'predictor_confidence', 'tariff_index',
    'tariff_delta', 'tariff_rate_of_change', 'funding_skew', 'basis_spread',
    'divergence_score', 'orderbook_imbalance', 'liquidity_score',
    'slippage_score', 'exec_quality', 'funding_arb_score', 'basis_opportunity',
    'tariff_shock'
  ];
  let selectedDecisionId = null;

  function escapeHtml(value) {
    return String(value == null ? '' : value)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#039;');
  }

  function pct(value) {
    return value == null ? '--' : `${(Number(value) * 100).toFixed(2)}%`;
  }

  function extractDecisionId(panel) {
    const replayButton = Array.from(panel.querySelectorAll('button')).find(btn =>
      String(btn.getAttribute('onclick') || '').includes('replayDecision(')
    );
    const onclick = replayButton && replayButton.getAttribute('onclick');
    const match = onclick && onclick.match(/replayDecision\('([^']+)'\)/);
    return match ? match[1] : null;
  }

  function fieldOptions(includeNone = false) {
    return `${includeNone ? '<option value="">NONE (1-D)</option>' : ''}${NUMERIC_FIELDS.map(field => `<option value="${field}">${field.replace(/_/g, ' ')}</option>`).join('')}`;
  }

  function axisMeta(payload, axisName) {
    const axis = payload[axisName] || {};
    return axis.metadata || { label: axis.field || '--', unit: 'unspecified' };
  }

  function valueWithUnit(value, unit) {
    return `${escapeHtml(value)}${unit && unit !== 'unspecified' ? ` ${escapeHtml(unit)}` : ''}`;
  }

  function parseValues(raw, label) {
    const values = String(raw || '').split(',').map(v => v.trim()).filter(Boolean).map(Number);
    if (!values.length || values.some(v => !Number.isFinite(v))) {
      throw new Error(`${label} values must be comma-separated finite numbers.`);
    }
    if (new Set(values).size !== values.length) throw new Error(`${label} values must be unique.`);
    return values;
  }

  function parseFixed(raw) {
    if (!String(raw || '').trim()) return {};
    const value = JSON.parse(raw);
    if (!value || Array.isArray(value) || typeof value !== 'object') throw new Error('Fixed scenario must be a JSON object.');
    return value;
  }

  function decisionClass(decision) {
    return String(decision || '').toLowerCase() === 'allow' ? 'match' : 'mismatch';
  }

  function renderBoundary(boundary, unit) {
    if (!boundary) return '';
    const transitions = (boundary.transitions || []).map(item =>
      `<tr><td>${valueWithUnit(item.lower_value, unit)}</td><td>${valueWithUnit(item.upper_value, unit)}</td><td>${escapeHtml(String(item.from_decision || '').toUpperCase())} → ${escapeHtml(String(item.to_decision || '').toUpperCase())}</td></tr>`
    ).join('');
    return `
      <h4 style="margin:12px 0 6px">Decision Boundary Analysis</h4>
      <div style="font-size:11px;color:var(--text-muted);margin-bottom:6px">${escapeHtml(boundary.monotonicity || '--')} · ${Number(boundary.transition_count || 0)} transition(s) · analyzed in ascending numeric order.</div>
      ${transitions ? `<div class="table-scroll"><table><thead><tr><th>Lower</th><th>Upper</th><th>Transition</th></tr></thead><tbody>${transitions}</tbody></table></div>` : '<div class="empty-state-text">No ALLOW/BLOCK transition was observed in the supplied values.</div>'}`;
  }

  function renderRobustness(payload) {
    const robustness = payload.robustness || {};
    const baseline = robustness.baseline || {};
    const boundary = robustness.nearest_sampled_boundary || {};
    const distance = robustness.distance || {};
    const local = robustness.local_robustness || {};
    const meta = axisMeta(payload, 'x');
    const boundaryText = boundary.available
      ? `${valueWithUnit(boundary.boundary_bracket[0], robustness.unit)}–${valueWithUnit(boundary.boundary_bracket[1], robustness.unit)}<br><small>${escapeHtml(String(boundary.from_decision).toUpperCase())} → ${escapeHtml(String(boundary.to_decision).toUpperCase())}</small>`
      : 'NOT OBSERVED IN SAMPLED RANGE';
    return `<div class="card" style="padding:10px;margin-bottom:10px">
      <div class="metric-label">COUNTERFACTUAL ROBUSTNESS</div>
      <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(145px,1fr));gap:8px;margin-top:7px">
        <div><span class="metric-label">Original decision</span><br><strong>${escapeHtml(String(baseline.decision || '--').toUpperCase())}</strong></div>
        <div><span class="metric-label">Original ${escapeHtml(meta.label)}</span><br><strong>${baseline.value == null ? '--' : valueWithUnit(baseline.value, robustness.unit)}</strong></div>
        <div><span class="metric-label">Nearest sampled boundary</span><br><strong>${boundaryText}</strong></div>
        <div><span class="metric-label">Distance to sampled boundary</span><br><strong>${distance.available ? `${valueWithUnit(distance.min, distance.unit)}–${valueWithUnit(distance.max, distance.unit)}` : '--'}</strong></div>
        <div><span class="metric-label">Sampled local robustness</span><br><strong>${escapeHtml(String(local.classification || 'UNAVAILABLE').replace(/_/g, ' '))}</strong></div>
      </div>
      <div style="font-size:11px;color:var(--text-muted);margin-top:8px">Robustness is descriptive within the sampled values only. Boundary brackets are observed sampled transitions, not interpolated thresholds.</div>
    </div>`;
  }

  function render1D(payload) {
    const field = payload.x && payload.x.field;
    const meta = axisMeta(payload, 'x');
    const rows = (payload.points || []).map(point => {
      const overlay = point.realized_outcome || {};
      return `<tr${point.is_baseline ? ' style="outline:2px solid var(--accent-color);outline-offset:-2px"' : ''}>
        <td>${valueWithUnit(point.scenario && point.scenario[field], meta.unit)}${point.is_baseline ? ' <strong>BASELINE</strong>' : ''}</td>
        <td><span class="replay-verdict ${decisionClass(point.decision)}" style="display:inline-block;padding:3px 6px">${escapeHtml(String(point.decision || '--').toUpperCase())}</span></td>
        <td>${escapeHtml(point.stage || '--')}</td>
        <td>${escapeHtml((point.reasons || []).join('; ') || '--')}</td>
        <td>${overlay.available ? `${pct(overlay.realized_signed_return)} · ${escapeHtml(overlay.interpretation || '--')}` : 'UNAVAILABLE'}</td>
      </tr>`;
    }).join('');
    return `
      ${renderRobustness(payload)}
      <div class="table-scroll"><table>
        <thead><tr><th>${escapeHtml(meta.label)}${meta.unit !== 'unspecified' ? ` (${escapeHtml(meta.unit)})` : ''}</th><th>Decision</th><th>Stage</th><th>Reason</th><th>Realized Context</th></tr></thead>
        <tbody>${rows}</tbody>
      </table></div>
      ${renderBoundary(payload.boundary_analysis, meta.unit)}`;
  }

  function render2D(payload) {
    const x = payload.x || {};
    const y = payload.y || {};
    const xMeta = axisMeta(payload, 'x');
    const yMeta = axisMeta(payload, 'y');
    const header = (x.values || []).map(value => `<th>${valueWithUnit(value, xMeta.unit)}</th>`).join('');
    const rows = (payload.matrix || []).map((row, index) => `<tr>
      <th>${valueWithUnit((y.values || [])[index], yMeta.unit)}</th>
      ${row.map(point => {
        const overlay = point.realized_outcome || {};
        const title = `${point.stage || '--'}${(point.reasons || []).length ? ` — ${(point.reasons || []).join('; ')}` : ''}${overlay.available ? ` — ${overlay.interpretation}` : ''}`;
        return `<td title="${escapeHtml(title)}"${point.is_baseline ? ' style="outline:2px solid var(--accent-color);outline-offset:-2px"' : ''}><span class="replay-verdict ${decisionClass(point.decision)}" style="display:inline-block;padding:4px 6px">${escapeHtml(String(point.decision || '--').toUpperCase())}${point.is_baseline ? ' · BASELINE' : ''}</span></td>`;
      }).join('')}
    </tr>`).join('');
    const nonMonotonicRows = (payload.row_boundary_analysis || []).filter(item => item.monotonicity === 'non_monotonic').length;
    const nonMonotonicCols = (payload.column_boundary_analysis || []).filter(item => item.monotonicity === 'non_monotonic').length;
    return `
      <div style="font-size:11px;color:var(--text-muted);margin-bottom:6px">Rows: ${escapeHtml(yMeta.label)} (${escapeHtml(yMeta.unit)}) · Columns: ${escapeHtml(xMeta.label)} (${escapeHtml(xMeta.unit)}) · Surface: ${escapeHtml(payload.surface_monotonicity || '--')}</div>
      <div class="table-scroll"><table>
        <thead><tr><th>${escapeHtml(y.field)} \\ ${escapeHtml(x.field)}</th>${header}</tr></thead>
        <tbody>${rows}</tbody>
      </table></div>
      <div style="font-size:11px;color:var(--text-muted);margin-top:8px">Non-monotonic row analyses: ${nonMonotonicRows} · non-monotonic column analyses: ${nonMonotonicCols}. Hover a cell for stage/reason/outcome context.</div>`;
  }

  function renderResult(payload) {
    const target = document.getElementById(RESULT_ID);
    if (!target) return;
    if (payload.error) {
      target.innerHTML = `<div class="replay-verdict mismatch">UNAVAILABLE</div><p>${escapeHtml(payload.error)}</p>`;
      return;
    }
    const overlay = payload.realized_outcome_overlay || {};
    const warnings = payload.warnings || [];
    target.innerHTML = `
      <div class="replay-verdict match">SENSITIVITY COMPUTED</div>
      <div style="font-size:11px;color:var(--text-muted);margin:6px 0 10px">${Number(payload.dimensions || 1)}-D · ${Number(payload.cell_count || 0)} deterministic replay cell(s) · baseline exact_match=${String(!!(payload.baseline && payload.baseline.exact_match))}</div>
      ${overlay.available ? `<div class="card" style="padding:9px;margin-bottom:10px"><div class="metric-label">Realized ${escapeHtml(overlay.horizon)} requested-side move</div><strong>${pct(overlay.realized_signed_return)}</strong><div style="font-size:11px;color:var(--text-muted)">Same historical move is overlaid on every cell; BLOCK cells are avoidance/opportunity observations, not realized P&amp;L.</div></div>` : ''}
      ${Number(payload.dimensions) === 2 ? render2D(payload) : render1D(payload)}
      ${warnings.length ? `<div style="font-size:11px;color:var(--warning);margin-top:8px">${escapeHtml(warnings.join(' '))}</div>` : ''}
      <div class="audit-only-banner" style="margin-top:10px"><strong>SENSITIVITY RESEARCH ONLY</strong> — No parameters are changed, no decision is persisted, and no order is routed. orders_submitted=${Number(payload.orders_submitted || 0)}, persisted=${String(!!payload.persisted)}.</div>`;
  }

  async function runSensitivity(wrapper) {
    try {
      if (!selectedDecisionId) throw new Error('Select a decision first.');
      const xField = wrapper.querySelector('[data-sens-x-field]').value;
      const yField = wrapper.querySelector('[data-sens-y-field]').value;
      const samplingMode = wrapper.querySelector('[data-sens-mode]').value;
      const body = {
        x: samplingMode === 'manual' ? { field: xField, values: parseValues(wrapper.querySelector('[data-sens-x-values]').value, 'X') } : { field: xField, preset: samplingMode },
        fixed_scenario: parseFixed(wrapper.querySelector('[data-sens-fixed]').value),
        outcome_horizon: wrapper.querySelector('[data-sens-horizon]').value || '4h'
      };
      if (yField) body.y = samplingMode === 'manual' ? { field: yField, values: parseValues(wrapper.querySelector('[data-sens-y-values]').value, 'Y') } : { field: yField, preset: samplingMode };
      const target = document.getElementById(RESULT_ID);
      if (target) target.textContent = 'Running bounded deterministic sensitivity replay...';
      const response = await fetch(`/api/decisions/${encodeURIComponent(selectedDecisionId)}/sensitivity`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body)
      });
      let payload = null;
      try { payload = await response.json(); } catch (_) { payload = null; }
      if (!response.ok) throw new Error(typeof (payload && payload.detail) === 'string' ? payload.detail : JSON.stringify((payload && payload.detail) || `API ${response.status}`));
      renderResult(payload);
    } catch (error) {
      renderResult({ error: error.message || String(error) });
    }
  }

  function attach(panel) {
    const id = extractDecisionId(panel);
    if (!id) return;
    selectedDecisionId = id;
    if (panel.querySelector('[data-sensitivity-controls]')) return;

    const wrapper = document.createElement('div');
    wrapper.setAttribute('data-sensitivity-controls', 'true');
    wrapper.style.cssText = 'margin-top:16px;padding-top:14px;border-top:1px solid var(--border-color)';
    wrapper.innerHTML = `
      <h4 style="margin:0 0 6px">Counterfactual Sensitivity / Decision Boundary Map</h4>
      <div style="font-size:11px;color:var(--text-muted);margin-bottom:10px">Run bounded numeric sweeps over this decision's immutable replay inputs. Values are replayed exactly as supplied; boundary intervals are observed brackets, not interpolated thresholds.</div>
      <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:8px">
        <label class="metric-label">Sampling mode<select data-sens-mode class="form-select"><option value="local">LOCAL PRESET</option><option value="standard" selected>STANDARD PRESET</option><option value="wide">WIDE PRESET</option><option value="manual">MANUAL</option></select></label>
        <label class="metric-label">X field<select data-sens-x-field class="form-select">${fieldOptions(false)}</select></label>
        <label class="metric-label">X values<input data-sens-x-values class="form-input" value="10,20,30,40,50,60,70,80"></label>
        <label class="metric-label">Y field (optional)<select data-sens-y-field class="form-select">${fieldOptions(true)}</select></label>
        <label class="metric-label">Y values<input data-sens-y-values class="form-input" value="100,75,50,25"></label>
        <label class="metric-label">Realized outcome<select data-sens-horizon class="form-select"><option>1h</option><option selected>4h</option><option>24h</option><option>7d</option></select></label>
        <label class="metric-label">Fixed scenario JSON<input data-sens-fixed class="form-input" placeholder='{"daily_pnl": -5000}'></label>
      </div>
      <div style="display:flex;gap:8px;align-items:center;margin-top:10px">
        <button type="button" class="btn btn-primary" data-run-sensitivity>Run Sensitivity</button>
        <span style="font-size:11px;color:var(--text-muted)">Maximum 100 cells.</span>
      </div>
      <div id="${RESULT_ID}" style="margin-top:12px"></div>`;
    panel.appendChild(wrapper);
    const mode = wrapper.querySelector('[data-sens-mode]');
    const syncMode = () => {
      const manual = mode.value === 'manual';
      wrapper.querySelector('[data-sens-x-values]').disabled = !manual;
      wrapper.querySelector('[data-sens-y-values]').disabled = !manual;
    };
    mode.addEventListener('change', syncMode);
    syncMode();
    wrapper.querySelector('[data-run-sensitivity]').addEventListener('click', () => runSensitivity(wrapper));
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
