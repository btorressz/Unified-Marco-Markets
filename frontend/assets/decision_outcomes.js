(() => {
  'use strict';

  const DETAIL_ID = 'decision-audit-detail';
  const TAB_ID = 'tab-decisions';
  let selectedDecisionId = null;

  function escapeHtml(value) {
    return String(value == null ? '' : value)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#039;');
  }

  function pct(value) {
    return value == null ? '--' : `${(Number(value) * 100).toFixed(2)}%`;
  }

  function number(value, digits = 2) {
    return value == null ? '--' : Number(value).toFixed(digits);
  }

  function extractDecisionId(panel) {
    const replayButton = Array.from(panel.querySelectorAll('button')).find(btn =>
      String(btn.getAttribute('onclick') || '').includes('replayDecision(')
    );
    const onclick = replayButton && replayButton.getAttribute('onclick');
    const match = onclick && onclick.match(/replayDecision\('([^']+)'\)/);
    return match ? match[1] : null;
  }

  function outcomeRows(outcomes) {
    return ['1h', '4h', '24h', '7d'].map(horizon => {
      const row = outcomes && outcomes[horizon];
      if (!row) {
        return `<tr><td>${horizon}</td><td colspan="5">UNAVAILABLE</td></tr>`;
      }
      return `<tr>
        <td>${horizon}</td>
        <td>${escapeHtml(row.source && `${row.source.venue || '--'} / ${row.source.symbol || '--'}`)}</td>
        <td>${number(row.price)}</td>
        <td>${pct(row.raw_return)}</td>
        <td>${pct(row.signed_return)}</td>
        <td>${escapeHtml(row.classification || '--')}</td>
      </tr>`;
    }).join('');
  }

  function renderOutcome(result, target) {
    if (!target) return;
    if (result.error) {
      target.innerHTML = `<div class="replay-verdict mismatch">UNAVAILABLE</div><p>${escapeHtml(result.error)}</p>`;
      return;
    }
    const decision = result.decision || {};
    const actual = result.actual_execution || {};
    target.innerHTML = `
      <div class="replay-verdict ${result.outcome_status === 'available' ? 'match' : 'mismatch'}">${escapeHtml(String(result.outcome_status || 'unavailable').toUpperCase())}</div>
      <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:8px;margin:10px 0">
        <div class="card" style="padding:9px"><div class="metric-label">Decision</div><strong>${escapeHtml(String(decision.action || '--').toUpperCase())}</strong></div>
        <div class="card" style="padding:9px"><div class="metric-label">Side</div><strong>${escapeHtml(String(decision.side || '--').toUpperCase())}</strong></div>
        <div class="card" style="padding:9px"><div class="metric-label">Reference Price</div><strong>${number(decision.entry_price)}</strong></div>
        <div class="card" style="padding:9px"><div class="metric-label">Actual Lifecycle</div><strong>${escapeHtml(actual.status || '--')}</strong></div>
      </div>
      <div class="table-scroll"><table>
        <thead><tr><th>Horizon</th><th>Source</th><th>Price</th><th>Raw Return</th><th>Side-Signed</th><th>Interpretation</th></tr></thead>
        <tbody>${outcomeRows(result.outcomes || {})}</tbody>
      </table></div>
      <div style="font-size:11px;color:var(--text-muted);margin-top:8px">${escapeHtml(result.interpretation || result.reason || '')}</div>
      <div style="font-size:11px;color:var(--text-muted);margin-top:4px">Actual fill linkage: ${Number(actual.fill_count || 0)} fill(s), average fill ${number(actual.average_fill_price)}, fees ${number(actual.fees, 4)}.</div>
      <div class="audit-only-banner" style="margin-top:10px"><strong>REALIZED OUTCOME RESEARCH ONLY</strong> — Later market moves are not automatically realized P&amp;L. Blocked decisions are evaluated as counterfactual avoidance/opportunity observations.</div>`;
  }

  async function loadSelectedOutcomes() {
    const result = document.getElementById('decision-outcomes-result');
    if (!selectedDecisionId || !result) return;
    result.textContent = 'Loading persisted post-decision market observations...';
    try {
      const response = await fetch(`/api/decisions/${encodeURIComponent(selectedDecisionId)}/outcomes`);
      const payload = await response.json();
      if (!response.ok) throw new Error(typeof payload.detail === 'string' ? payload.detail : JSON.stringify(payload.detail || `API ${response.status}`));
      renderOutcome(payload, result);
    } catch (error) {
      renderOutcome({ error: error.message || String(error) }, result);
    }
  }

  function attachDecisionControls(panel) {
    const id = extractDecisionId(panel);
    if (!id) return;
    selectedDecisionId = id;
    if (panel.querySelector('[data-decision-outcome-controls]')) return;

    const wrapper = document.createElement('div');
    wrapper.setAttribute('data-decision-outcome-controls', 'true');
    wrapper.style.cssText = 'margin-top:16px;padding-top:14px;border-top:1px solid var(--border-color)';
    wrapper.innerHTML = `
      <h4 style="margin:0 0 6px">Realized Decision Outcomes</h4>
      <div style="font-size:11px;color:var(--text-muted);margin-bottom:8px">Evaluate the requested execution side against persisted market observations at 1h, 4h, 24h and 7d.</div>
      <button type="button" class="btn btn-primary" data-load-decision-outcomes>Load Outcomes</button>
      <div id="decision-outcomes-result" style="margin-top:12px"></div>`;
    panel.appendChild(wrapper);
    wrapper.querySelector('[data-load-decision-outcomes]').addEventListener('click', loadSelectedOutcomes);
  }

  function sampleBadge(metric) {
    if (!metric || !metric.sample_warning) return '';
    return `<span style="display:inline-block;margin-left:6px;padding:2px 6px;border:1px solid var(--border-color);border-radius:999px;font-size:10px;font-weight:700">${escapeHtml(metric.sample_warning.replaceAll('_', ' '))}</span>`;
  }

  function summaryCards(metric) {
    metric = metric || {};
    return `
      <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:8px;margin:10px 0">
        <div class="card" style="padding:9px"><div class="metric-label">Evaluated ${sampleBadge(metric)}</div><strong>${Number(metric.evaluated_count || 0)} / ${Number(metric.sample_count || 0)}</strong></div>
        <div class="card" style="padding:9px"><div class="metric-label">Coverage</div><strong>${pct(metric.coverage_rate)}</strong></div>
        <div class="card" style="padding:9px"><div class="metric-label">Missing</div><strong>${Number(metric.missing_count || 0)} (${pct(metric.missing_rate)})</strong></div>
        <div class="card" style="padding:9px"><div class="metric-label">Decision Quality</div><strong>${pct(metric.decision_quality_rate)}</strong></div>
        <div class="card" style="padding:9px"><div class="metric-label">Mean Signed Return</div><strong>${pct(metric.average_signed_return)}</strong></div>
        <div class="card" style="padding:9px"><div class="metric-label">Median Signed Return</div><strong>${pct(metric.median_signed_return)}</strong></div>
        <div class="card" style="padding:9px"><div class="metric-label">25th Percentile</div><strong>${pct(metric.signed_return_p25)}</strong></div>
        <div class="card" style="padding:9px"><div class="metric-label">75th Percentile</div><strong>${pct(metric.signed_return_p75)}</strong></div>
        <div class="card" style="padding:9px"><div class="metric-label">Std Dev</div><strong>${pct(metric.signed_return_stddev)}</strong></div>
        <div class="card" style="padding:9px"><div class="metric-label">ALLOW</div><strong>${Number(metric.allow_count || 0)}</strong></div>
        <div class="card" style="padding:9px"><div class="metric-label">BLOCK</div><strong>${Number(metric.block_count || 0)}</strong></div>
        <div class="card" style="padding:9px"><div class="metric-label">BLOCK Avoided Adverse</div><strong>${pct(metric.block_avoided_adverse_move_rate)}</strong></div>
        <div class="card" style="padding:9px"><div class="metric-label">BLOCK Opportunity Cost</div><strong>${pct(metric.block_opportunity_cost_rate)}</strong></div>
      </div>`;
  }

  function groupTable(title, groups) {
    const rows = Object.entries(groups || {}).map(([key, metric]) => `<tr>
      <td>${escapeHtml(key)}${sampleBadge(metric)}</td>
      <td>${Number(metric.evaluated_count || 0)} / ${Number(metric.sample_count || 0)}</td>
      <td>${pct(metric.coverage_rate)}</td>
      <td>${pct(metric.decision_quality_rate)}</td>
      <td>${pct(metric.average_signed_return)}</td>
      <td>${pct(metric.median_signed_return)}</td>
      <td>${pct(metric.signed_return_p25)}</td>
      <td>${pct(metric.signed_return_p75)}</td>
      <td>${pct(metric.signed_return_stddev)}</td>
      <td>${pct(metric.block_avoided_adverse_move_rate)}</td>
      <td>${pct(metric.block_opportunity_cost_rate)}</td>
    </tr>`).join('');
    if (!rows) return '';
    return `<h4 style="margin:12px 0 6px">${escapeHtml(title)}</h4><div class="table-scroll"><table>
      <thead><tr><th>Group</th><th>Evaluated / n</th><th>Coverage</th><th>Decision Quality</th><th>Mean</th><th>Median</th><th>P25</th><th>P75</th><th>Std Dev</th><th>BLOCK Avoided</th><th>BLOCK Opp Cost</th></tr></thead>
      <tbody>${rows}</tbody></table></div>`;
  }

  function coveragePanel(coverage, governance) {
    coverage = coverage || {}; governance = governance || {};
    const available = coverage.available_counts || {}; const stale = coverage.stale_counts || {}; const unavailable = coverage.unavailable_counts || {}; const recorded = coverage.recorded_decision_counts || {};
    const total = Number(coverage.decision_count || 0);
    const contexts = Array.from(new Set([...Object.keys(available), ...Object.keys(stale), ...Object.keys(unavailable), ...Object.keys(recorded)])).sort();
    const rows = contexts.map(field => {
      const usable = Number(available[field] || 0); const immutable = Number(recorded[field] || 0); const reconstructed = Math.max(0, usable - immutable);
      return `<tr><td>${escapeHtml(field)}</td><td>${usable} / ${total}</td><td>${immutable}</td><td>${reconstructed}</td><td>${Number(stale[field] || 0)}</td><td>${Number(unavailable[field] || 0)}</td></tr>`;
    }).join('');
    const freshness = governance.freshness_policy || {};
    const policyRows = Object.entries(freshness).map(([source, policy]) => `<div class="provenance-field"><label>${escapeHtml(source)}</label>≤ ${Number((policy || {}).max_age_seconds || 0).toLocaleString()}s</div>`).join('');
    const warnings = [];
    if (Object.keys(coverage.source_errors || {}).length) warnings.push(`Source errors: ${JSON.stringify(coverage.source_errors)}`);
    if (Object.values(coverage.truncated || {}).some(Boolean)) warnings.push(`Historical context was bounded: ${JSON.stringify(coverage.truncated)}`);
    return `<details style="margin-top:12px" open>
      <summary style="cursor:pointer;font-size:12px;font-weight:600">Cohort Context Coverage &amp; Governance</summary>
      <div class="research-warning">Immutable recorded decision context takes precedence. Fallback reconstruction is freshness governed; stale fallback observations are labeled unavailable and are not silently included in named cohorts.</div>
      ${rows ? `<div class="table-scroll"><table><thead><tr><th>Context</th><th>Usable</th><th>Recorded</th><th>Reconstructed</th><th>Stale</th><th>Unavailable</th></tr></thead><tbody>${rows}</tbody></table></div>` : ''}
      <div class="provenance-grid"><div class="provenance-field"><label>Definition version</label>${escapeHtml(governance.cohort_definition_version || '--')}</div><div class="provenance-field"><label>Freshness-policy version</label>${escapeHtml(governance.freshness_policy_version || '--')}</div>${policyRows}</div>
      ${warnings.length ? `<pre style="white-space:pre-wrap;font-size:11px">${escapeHtml(warnings.join('\n'))}</pre>` : ''}
    </details>`;
  }

  function renderPerformance(payload, result) {
    if (payload.error) {
      result.innerHTML = `<div class="replay-verdict mismatch">UNAVAILABLE</div><p>${escapeHtml(payload.error)}</p>`;
      return;
    }
    const primary = payload.primary_horizon || '4h';
    const metric = (payload.horizons || {})[primary] || {};
    const decay = payload.performance_decay || {};
    const regimes = payload.performance_by_regime || {};
    const cohorts = payload.performance_by_cohort || {};
    const batching = payload.outcome_evaluation || {};
    result.innerHTML = `
      <div class="replay-verdict ${payload.status === 'available' ? 'match' : 'mismatch'}">${escapeHtml(String(payload.status || 'unavailable').toUpperCase())}</div>
      <div style="font-size:11px;color:var(--text-muted);margin-top:6px">Primary horizon: ${escapeHtml(primary)} · Final execution decisions scanned: ${Number(payload.decision_count || 0)} · Outcome market queries: ${Number(batching.query_count || 0)}${batching.batch_fallback ? ' (bounded fallback)' : ''}</div>
      ${summaryCards(metric)}
      ${groupTable('By Volatility Regime', regimes.vol_regime || payload.performance_by_vol_regime)}
      ${groupTable('By Funding Regime', regimes.funding_regime)}
      ${groupTable('By Shock State', regimes.shock_state)}
      ${groupTable('By Combined Regime Signature', payload.performance_by_regime_signature)}
      ${groupTable('Tariff Escalation Cohort', cohorts.tariff_escalation)}
      ${groupTable('Stablecoin Health Cohort', cohorts.stablecoin_health)}
      ${groupTable('Liquidity State Cohort', cohorts.liquidity_state)}
      ${groupTable('By Market', payload.performance_by_market)}
      ${groupTable('By Venue', payload.performance_by_venue)}
      ${groupTable('By Heuristic Version', payload.performance_by_heuristic_version)}
      ${groupTable('By Model Version', payload.performance_by_model_version)}
      ${coveragePanel(payload.context_coverage, payload.cohort_governance)}
      <h4 style="margin:12px 0 6px">Performance Decay</h4>
      <pre style="white-space:pre-wrap;font-size:11px">${escapeHtml(JSON.stringify(decay, null, 2))}</pre>
      <div style="font-size:11px;color:var(--text-muted);margin-top:8px">Decision Quality = ALLOW followed by a favorable requested-side move, or BLOCK followed by an adverse requested-side move. Flat outcomes do not count as favorable decisions. LOW SAMPLE warnings are descriptive guardrails, not significance tests.</div>
      <div class="audit-only-banner" style="margin-top:10px"><strong>DECISION PERFORMANCE RESEARCH ONLY</strong> — Cohorts describe persisted decision-time context and later market moves. Distribution statistics are descriptive only; they do not rewrite decisions, optimize thresholds, or claim blocked trades produced realized P&amp;L.</div>`;
  }

  async function loadPerformance() {
    const panel = document.getElementById('decision-performance-result');
    const select = document.getElementById('decision-performance-horizon');
    if (!panel || !select) return;
    panel.textContent = 'Evaluating final decisions and reconstructing persisted decision-time cohorts...';
    try {
      const response = await fetch(`/api/decisions/performance?primary_horizon=${encodeURIComponent(select.value)}&limit=100`);
      const payload = await response.json();
      if (!response.ok) throw new Error(typeof payload.detail === 'string' ? payload.detail : JSON.stringify(payload.detail || `API ${response.status}`));
      renderPerformance(payload, panel);
    } catch (error) {
      renderPerformance({ error: error.message || String(error) }, panel);
    }
  }

  function attachPerformanceLab() {
    const tab = document.getElementById(TAB_ID);
    if (!tab || tab.querySelector('[data-decision-performance-lab]')) return;
    const wrapper = document.createElement('div');
    wrapper.setAttribute('data-decision-performance-lab', 'true');
    wrapper.innerHTML = `
      <div class="section-title">Decision Performance Lab</div>
      <div class="card">
        <div style="display:flex;gap:8px;align-items:end;flex-wrap:wrap">
          <label style="display:flex;flex-direction:column;gap:4px;font-size:11px;color:var(--text-muted)">Primary horizon
            <select id="decision-performance-horizon" class="form-select">
              <option value="1h">1h</option><option value="4h" selected>4h</option><option value="24h">24h</option><option value="7d">7d</option>
            </select>
          </label>
          <button type="button" class="btn btn-primary" id="decision-performance-load">Evaluate Decisions</button>
        </div>
        <div id="decision-performance-result" style="margin-top:12px"><div class="empty-state-text">Performance and cohort analytics are calculated on demand from immutable decisions and persisted historical context.</div></div>
      </div>`;
    tab.appendChild(wrapper);
    wrapper.querySelector('#decision-performance-load').addEventListener('click', loadPerformance);
  }

  function scan() {
    attachPerformanceLab();
    const panel = document.getElementById(DETAIL_ID);
    if (panel) attachDecisionControls(panel);
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