const PriceIntegrityUI = (() => {
  'use strict';

  const SYMBOLS = ['BTC/USD', 'ETH/USD', 'SOL/USD'];
  const SOURCES = ['pyth', 'kraken', 'coingecko'];
  let refreshTimer = null;

  const escapeHtml = value => String(value ?? '').replace(/[&<>'"]/g, char => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;',
  }[char]));

  const presentNumber = value =>
    value !== null && value !== undefined && value !== '' && Number.isFinite(Number(value));

  const number = (value, digits = 2) =>
    presentNumber(value) ? Number(value).toFixed(digits) : '--';

  const price = value =>
    presentNumber(value)
      ? Number(value).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 4 })
      : '--';

  const age = value => {
    if (!presentNumber(value)) return '--';
    const seconds = Number(value);
    if (seconds < 60) return `${Math.round(seconds)}s`;
    if (seconds < 3600) return `${Math.round(seconds / 60)}m`;
    return `${(seconds / 3600).toFixed(1)}h`;
  };

  const statusBadge = status => {
    const value = String(status || 'UNKNOWN').toUpperCase();
    const cls = value === 'OK' ? 'badge-green' : value === 'WARNING' ? 'badge-yellow' : 'badge-red';
    return `<span class="badge ${cls}">${escapeHtml(value)}</span>`;
  };

  function ensurePanel() {
    let panel = document.getElementById('price-integrity-diagnostics-panel');
    if (panel) return panel;
    const anchor = document.getElementById('integrity-detail');
    const grid = anchor && anchor.closest('.grid-3');
    if (!grid) return null;
    panel = document.createElement('div');
    panel.id = 'price-integrity-diagnostics-panel';
    panel.className = 'card';
    panel.style.marginTop = '12px';
    panel.innerHTML = '<div class="empty-state"><div class="empty-state-text">Loading canonical price diagnostics...</div></div>';
    grid.insertAdjacentElement('afterend', panel);
    return panel;
  }

  function sourceRows(symbolData) {
    const sources = symbolData.source_diagnostics || {};
    return SOURCES.map(source => {
      const row = sources[source] || {};
      const reason = row.reason ? String(row.reason).replaceAll('_', ' ').toUpperCase() : '--';
      const status = row.usable_for_integrity === true
        ? '<span class="badge badge-green">USABLE</span>'
        : `<span class="badge badge-red">${escapeHtml(reason === '--' ? 'UNAVAILABLE' : reason)}</span>`;
      const outlier = row.outlier === true
        ? '<span class="badge badge-yellow">OUTLIER</span>'
        : '<span style="color:var(--text-muted)">--</span>';
      return `<tr>
        <td><strong>${escapeHtml(source)}</strong></td>
        <td>${row.available === true ? '$' + price(row.price) : '--'}</td>
        <td>${escapeHtml(row.timestamp || '--')}</td>
        <td>${age(row.age_seconds)}</td>
        <td>${row.fresh === true ? '<span class="badge badge-green">FRESH</span>' : row.fresh === false ? '<span class="badge badge-red">NOT FRESH</span>' : '--'}</td>
        <td>${status}</td>
        <td>${presentNumber(row.deviation_from_median_bps) ? `${number(row.deviation_from_median_bps, 2)} bps` : '--'}</td>
        <td>${outlier}</td>
      </tr>`;
    }).join('');
  }

  function symbolCard(symbol, raw) {
    const data = raw || {};
    const selected = data.selected_execution_price || {};
    const outliers = Array.isArray(data.outlier_sources) ? data.outlier_sources : [];
    const reason = data.reason ? `<div style="font-size:11px;color:var(--text-muted);margin-top:6px">${escapeHtml(data.reason)}</div>` : '';
    const selectedFresh = selected.diagnostic_fresh === true
      ? '<span class="badge badge-green">SELECTED FRESH</span>'
      : selected.diagnostic_fresh === false
      ? '<span class="badge badge-red">SELECTED NOT FRESH</span>'
      : '<span class="badge badge-yellow">SELECTED FRESHNESS UNKNOWN</span>';

    return `<article style="padding:10px 0;border-top:1px solid var(--border-color)">
      <div class="card-header">
        <span class="card-title">${escapeHtml(symbol)}</span>
        ${statusBadge(data.status)}
      </div>
      <div class="metric-row" style="flex-wrap:wrap">
        <div class="metric-box"><div class="metric-label">Selected Source</div><div class="metric-value blue" style="font-size:15px">${escapeHtml(selected.source || '--')}</div><small>${selected.found === true ? '$' + price(selected.price) : 'UNAVAILABLE'}</small></div>
        <div class="metric-box"><div class="metric-label">Fresh Quorum</div><div class="metric-value" style="font-size:15px">${number(data.usable_source_count, 0)} / ${number(data.required_quorum, 0)}</div><small>${data.quorum_met === true ? 'PASS' : 'INSUFFICIENT'}</small></div>
        <div class="metric-box"><div class="metric-label">Median Reference</div><div class="metric-value" style="font-size:15px">${presentNumber(data.median_reference_price) ? '$' + price(data.median_reference_price) : '--'}</div><small>diagnostic only</small></div>
        <div class="metric-box"><div class="metric-label">Max Disagreement</div><div class="metric-value" style="font-size:15px">${presentNumber(data.max_disagreement_bps) ? number(data.max_disagreement_bps, 2) + ' bps' : '--'}</div><small>threshold ${number(data.deviation_threshold_bps, 0)} bps</small></div>
        <div class="metric-box"><div class="metric-label">Dispersion</div><div class="metric-value" style="font-size:15px">${presentNumber(data.dispersion_bps) ? number(data.dispersion_bps, 2) + ' bps' : '--'}</div></div>
        <div class="metric-box"><div class="metric-label">Outliers</div><div class="metric-value" style="font-size:13px">${outliers.length ? outliers.map(escapeHtml).join(', ') : 'NONE'}</div></div>
      </div>
      <div class="quality-strip" style="margin-top:8px">${selectedFresh}${data.consensus_is_diagnostic_only === true ? '<span class="quality-badge research">CONSENSUS DIAGNOSTIC ONLY</span>' : ''}<span class="quality-badge observed">SELECTION UNCHANGED</span></div>
      ${reason}
      <details style="margin-top:8px">
        <summary>Source freshness / disagreement matrix</summary>
        <div class="table-scroll">
          <table>
            <thead><tr><th>Source</th><th>Price</th><th>Timestamp</th><th>Age</th><th>Freshness</th><th>Integrity Use</th><th>vs Median</th><th>Outlier</th></tr></thead>
            <tbody>${sourceRows(data)}</tbody>
          </table>
        </div>
      </details>
    </article>`;
  }

  function render(payload) {
    const panel = ensurePanel();
    if (!panel) return;
    if (!payload || typeof payload !== 'object') {
      panel.innerHTML = '<div class="empty-state"><div class="empty-state-text">Price integrity diagnostics unavailable.</div></div>';
      return;
    }

    const authority = payload.execution_authority || {};
    const symbols = payload.symbols || {};
    const priority = Array.isArray(authority.priority) ? authority.priority : SOURCES;
    panel.innerHTML = `
      <div class="card-header">
        <span class="card-title">Canonical Price Integrity · Freshness · Consensus Diagnostics</span>
        ${statusBadge(payload.status)}
      </div>
      <div class="research-warning">
        <strong>DIAGNOSTIC CONSENSUS ONLY — EXECUTION PRICE SELECTION UNCHANGED</strong><br>
        Execution authority remains deterministic ${priority.map(escapeHtml).join(' → ')} priority. Median, quorum, disagreement and outlier measurements explain source quality; they do not replace the selected execution price.
      </div>
      <div class="quality-strip" style="margin-bottom:10px">
        ${payload.read_only === true ? '<span class="quality-badge observed">READ ONLY</span>' : '<span class="quality-badge stale">MUTABLE</span>'}
        ${payload.provider_io === false ? '<span class="quality-badge research">NO PROVIDER I/O</span>' : '<span class="quality-badge stale">PROVIDER I/O</span>'}
        ${payload.research_sources_can_establish_integrity === false ? '<span class="quality-badge research">YAHOO CANNOT ESTABLISH INTEGRITY</span>' : ''}
      </div>
      ${SYMBOLS.map(symbol => symbolCard(symbol, symbols[symbol])).join('')}
      <div style="font-size:10px;color:var(--text-muted)">As of ${escapeHtml(payload.ts || '--')}</div>`;
  }

  async function refresh() {
    const tab = document.getElementById('tab-markets');
    if (!tab || !tab.classList.contains('active')) return;
    const panel = ensurePanel();
    if (!panel) return;
    try {
      const response = await fetch('/api/markets/integrity/diagnostics');
      if (!response.ok) throw new Error(`API ${response.status}`);
      render(await response.json());
    } catch (error) {
      panel.innerHTML = `<div class="card-header"><span class="card-title">Canonical Price Integrity · Freshness · Consensus Diagnostics</span></div><div class="empty-state-text">UNAVAILABLE — ${escapeHtml(error.message)}</div>`;
    }
  }

  function init() {
    ensurePanel();
    const marketsButton = document.querySelector('.tab-btn[data-tab="markets"]');
    if (marketsButton) marketsButton.addEventListener('click', () => setTimeout(refresh, 0));
    refresh();
    if (!refreshTimer) refreshTimer = setInterval(refresh, 5000);
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();

  return { render, refresh };
})();
