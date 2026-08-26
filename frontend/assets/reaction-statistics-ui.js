(function () {
  'use strict';

  const HORIZONS = ['1h', '4h', '24h', '7d'];
  const object = value => value && typeof value === 'object' && !Array.isArray(value) ? value : {};
  const entries = value => Object.entries(object(value));
  const present = value => value !== null && value !== undefined && value !== '';
  const count = value => Number.isFinite(Number(value)) ? Number(value) : null;
  const number = (value, digits = 0) => present(value) && Number.isFinite(Number(value)) ? Number(value).toFixed(digits) : '--';
  const percent = value => present(value) && Number.isFinite(Number(value)) ? `${(Number(value) * 100).toFixed(0)}%` : '--';
  const label = (value, escape) => escape(String(value || 'UNKNOWN').replaceAll('_', ' ').toUpperCase());
  const quality = n => n === null || n <= 0 ? 'UNAVAILABLE' : n < 5 ? 'VERY LOW SAMPLE' : n < 20 ? 'LOW SAMPLE' : n < 50 ? 'MODERATE SAMPLE' : 'ESTABLISHED SAMPLE';
  const badge = (text, kind = 'research') => `<span class="quality-badge ${kind}">${text}</span>`;
  const emptyRow = (columns, message) => `<tr><td colspan="${columns}" class="empty-state-text">${message}</td></tr>`;
  const metric = (name, value) => `<div class="research-stat"><small>${name}</small><strong>${value}</strong></div>`;
  const table = (head, body) => `<div class="table-scroll"><table class="reaction-matrix"><thead><tr>${head.map(x => `<th>${x}</th>`).join('')}</tr></thead><tbody>${body}</tbody></table></div>`;
  const breakdown = (title, values, escape) => `<details><summary>${title}</summary>${entries(values).length ? table(['Group', 'Events'], entries(values).map(([key, value]) => `<tr><td title="${escape(key)}">${escape(key)}</td><td>${number(value)}</td></tr>`).join('')) : '<p class="empty-state-text">UNAVAILABLE</p>'}</details>`;

  function statisticsDetail(row) {
    const raw = object(row.raw_statistics);
    const fields = [['Mean', raw.mean], ['Median', raw.median], ['P25', raw.p25], ['P75', raw.p75], ['IQR', raw.iqr], ['Sample stddev', raw.sample_stddev], ['Min', raw.min], ['Max', raw.max]];
    const bootstrap = object(raw.bootstrap_interval || row.bootstrap_interval);
    const winsorized = object(raw.winsorized_sensitivity || row.winsorized_sensitivity);
    return `<details><summary>Raw descriptive detail</summary><div class="research-stat-grid">${fields.map(([key, value]) => metric(key, number(value, 4))).join('')}${metric('Descriptive bootstrap interval', entries(bootstrap).length ? `${number(bootstrap.lower, 4)} – ${number(bootstrap.upper, 4)}` : 'UNAVAILABLE')}${metric('Winsorized sensitivity', present(winsorized.median) ? number(winsorized.median, 4) : 'UNAVAILABLE')}</div></details>`;
  }

  function priceTable(series) {
    const rows = ['BTC', 'ETH', 'SOL'].map(asset => `<tr><td><strong>${asset}</strong></td>${HORIZONS.map(horizon => {
      const row = object(object(series[asset])[horizon]);
      const n = count(row.observed_n);
      if (!present(row.median)) return `<td><strong>--</strong><small>UNAVAILABLE</small>${badge('UNAVAILABLE', 'unavailable')}</td>`;
      return `<td><strong>${number(Number(row.median) * 100, 2)}%</strong><small>n=${number(n)} / ${number(row.coverage_denominator_n)} · ${percent(row.coverage_rate)}</small>${badge(quality(n))}${statisticsDetail(row)}</td>`;
    }).join('')}</tr>`).join('');
    return table(['Asset', ...HORIZONS.map(x => x.toUpperCase())], rows);
  }

  function scalarTable(title, series, kind, escape) {
    const rows = entries(series).map(([name, horizons]) => `<tr><td><strong>${escape(name)}</strong></td>${HORIZONS.map(horizon => {
      const row = object(horizons[horizon]); const n = count(row.observed_n);
      if (!present(row.median)) return `<td><strong>--</strong><small>UNAVAILABLE</small>${badge('UNAVAILABLE', 'unavailable')}</td>`;
      const detail = kind === 'funding' ? object(row.funding_reaction_counts) : object(row.basis_reaction_counts);
      const transitions = kind === 'funding'
        ? `${metric('Increased', number(detail.increased_count))}${metric('Decreased', number(detail.decreased_count))}${metric('Unchanged', number(detail.unchanged_count))}${metric('Increase rate', percent(detail.increase_rate))}${metric('Decrease rate', percent(detail.decrease_rate))}${metric('Sign flips', `${number(detail.sign_flip_count)} · ${percent(detail.sign_flip_rate)}`)}`
        : `${metric('Premium → discount', number(detail.premium_to_discount_count))}${metric('Discount → premium', number(detail.discount_to_premium_count))}${metric('Sign flips', `${number(detail.sign_flip_count)} · ${percent(detail.sign_flip_rate)}`)}`;
      return `<td><strong>${number(row.median, 3)} bps</strong><small>n=${number(n)} / ${number(row.coverage_denominator_n)} · ${percent(row.coverage_rate)}</small>${badge(quality(n))}<details><summary>Reaction counts</summary><div class="research-stat-grid">${transitions}</div></details></td>`;
    }).join('')}</tr>`).join('') || emptyRow(HORIZONS.length + 1, `${title} UNAVAILABLE`);
    return `<details><summary>${title}</summary>${table(['Market · Venue', ...HORIZONS.map(x => x.toUpperCase())], rows)}</details>`;
  }

  function regimeView(regimes, escape) {
    const rows = entries(regimes).flatMap(([field, horizons]) => HORIZONS.map(horizon => {
      const row = object(horizons[horizon]);
      const transitions = Array.isArray(row.cells) ? row.cells.map(cell => `${escape(cell.from)} → ${escape(cell.to)}: ${number(cell.count)} (${percent(cell.rate)})`).join('<br>') : entries(row.transitions || row.transition_counts || row.matrix).map(([key, value]) => `${escape(key)}: ${number(value)}`).join('<br>') || 'UNAVAILABLE';
      return `<tr><td>${label(field, escape)}</td><td>${horizon.toUpperCase()}</td><td>${number(row.transition_observed_n)}</td><td>${number(row.reference_available_n)} / ${number(row.target_available_n)}</td><td>${number(row.missing_n)}</td><td>${percent(row.coverage_rate)}</td><td>${number(row.overlap_excluded_count)}</td><td>${transitions}</td></tr>`;
    })).join('') || emptyRow(8, 'REGIME TRANSITIONS UNAVAILABLE');
    return table(['Regime', 'Horizon', 'Observed n', 'Reference / target', 'Missing', 'Coverage', 'Overlap excluded', 'Observed transitions'], rows);
  }

  function subgroupSummary(group, escape) {
    group = object(group); const n = count(group.event_count || group.sample_count || group.sample_size || group.included_event_count || object(group.sample).included_event_count);
    const available = group.statistics_available !== false;
    return `<div class="research-subgroup-meta">${badge(quality(n), available ? 'research' : 'unavailable')} <strong>n=${number(n)}</strong>${available ? '' : ` · ${label(group.reason || 'statistics unavailable', escape)}`}</div>${priceTable(object(group.price_statistics))}${scalarTable('Funding medians', object(group.funding_statistics), 'funding', escape)}${scalarTable('Basis medians', object(group.basis_statistics), 'basis', escape)}<details><summary>Regime summary</summary>${regimeView(object(group.regime_statistics), escape)}</details>`;
  }

  function strata(data, escape) {
    const sets = [['TIME BASIS', data.results_by_event_time_basis, object(data.stratification_metadata).event_time_basis], ['EVENT TYPE', data.results_by_event_type, object(data.stratification_metadata).event_type], ['EVENT FAMILY', data.results_by_event_family, object(data.stratification_metadata).event_family]];
    return sets.map(([title, groups, meta]) => {
      groups = object(groups); meta = object(meta);
      const warning = meta.truncated ? `<div class="reaction-warning"><strong>SHOWING ${number(meta.returned_group_count)} OF ${number(meta.group_count)} GROUPS</strong> · maximum ${number(meta.max_groups)}</div>` : '';
      const content = entries(groups).map(([name, group]) => `<details><summary>${escape(name)}</summary>${subgroupSummary(group, escape)}</details>`).join('') || '<p class="empty-state-text">No strata returned.</p>';
      return `<details class="strata-kind"><summary>${title}</summary>${warning}${content}</details>`;
    }).join('');
  }

  function decisionGroup(title, groups, escape) {
    const body = entries(groups).map(([name, row]) => `<details><summary>${escape(name)} · n=${number(row.decision_count)}</summary>${decisionSummary(row, escape, false)}</details>`).join('') || '<p class="empty-state-text">No decision strata returned.</p>';
    return `<details><summary>${title}</summary>${body}</details>`;
  }

  function decisionSummary(decision, escape, includeGroups = true) {
    decision = object(decision);
    const horizons = HORIZONS.map(horizon => { const row = object(object(decision.horizons)[horizon]); const classifications = entries(row.classification_counts).map(([name, value]) => `<span title="${escape(name)}">${label(name, escape)}: ${number(value)}</span>`).join('<br>') || 'UNAVAILABLE'; return `<tr><td>${horizon.toUpperCase()}</td><td>${number(row.evaluated_n)}</td><td>${number(row.missing_n)}</td><td>${classifications}</td></tr>`; }).join('');
    return `<div class="research-stat-grid">${metric('Decisions', number(decision.decision_count))}${metric('ALLOW', number(decision.allow_count))}${metric('BLOCK', number(decision.block_count))}${metric('Explicit recorded link', number(object(decision.link_type_counts).explicit_recorded_link))}${metric('Temporal proximity', number(object(decision.link_type_counts).temporal_proximity_only))}</div>${table(['Horizon', 'Evaluated', 'Missing', 'Classification counts'], horizons)}${includeGroups ? `${decisionGroup('LINK TYPE RESULTS', decision.results_by_link_type, escape)}${decisionGroup('REGIME SIGNATURE RESULTS', decision.results_by_regime_signature, escape)}${decisionGroup('DECISION EVENT TYPE RESULTS', decision.results_by_event_type, escape)}${decisionGroup('DECISION EVENT FAMILY RESULTS', decision.results_by_event_family, escape)}` : ''}`;
  }

  function missingnessView(data, escape) {
    const missing = object(object(data.missingness).all_events_by_metric);
    const rows = entries(missing).flatMap(([metricName, reasons]) => entries(reasons).filter(([, value]) => Number(value) > 0).map(([reason, value]) => `<tr><td>${label(metricName, escape)}</td><td title="${escape(reason)}">${label(reason, escape)}</td><td>${number(value)}</td></tr>`)).join('') || emptyRow(3, 'No non-zero missingness reasons returned.');
    return table(['Metric', 'Backend reason', 'Count'], rows);
  }

  function queryIntegrity(data, escape) {
    const rows = entries(data).flatMap(([category, series]) => {
      if (category === 'decisions' && !entries(series).length) return [];
      const values = entries(series).length && !present(series.query_mode) && !present(series.truncated) ? entries(series) : [[category, series]];
      return values.map(([name, raw]) => { const row = object(raw); const coverage = object(row.dataset_coverage || row.coverage); return `<tr><td>${label(category, escape)}</td><td>${escape(name)}</td><td>${escape(row.query_mode || '--')}</td><td>${row.truncated === true ? badge('QUERY TRUNCATED', 'unavailable') : badge('COMPLETE', 'observed')}</td><td>${number(row.requested_target_count)}</td><td>${number(row.max_expected_rows)}</td><td>${escape(coverage.first_timestamp || row.first_timestamp || '--')} → ${escape(coverage.latest_timestamp || row.latest_timestamp || '--')}</td><td>${escape(row.error || '--')}</td></tr>`; });
    }).join('') || emptyRow(8, 'DATA QUERY INTEGRITY UNAVAILABLE');
    return table(['Area', 'Series', 'Query mode', 'Bound', 'Targets', 'Max rows', 'Dataset coverage', 'Error'], rows);
  }

  function render(panel, data, escape) {
    escape = typeof escape === 'function' ? escape : value => String(value).replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
    if (!data || typeof data !== 'object') { panel.innerHTML = '<div class="card-header"><span class="card-title">MULTI-EVENT STATISTICAL VALIDATION</span></div><div class="empty-state-text">UNAVAILABLE — durable study observations are required.</div>'; return; }
    const sample = object(data.sample), study = object(data.study), manifest = object(data.study_manifest), filters = object(data.filters), contract = object(data.statistics_contract), bootstrap = object(contract.bootstrap), winsor = object(contract.winsorization), decision = object(data.decision_statistics);
    const heterogeneous = sample.heterogeneous_event_time_basis === true;
    const warning = heterogeneous ? '<div class="reaction-warning"><strong>HETEROGENEOUS EVENT-TIME BASIS</strong><br>Combined headline statistics are intentionally suppressed. Use the event-time-basis strata below for like-for-like comparisons.</div>' : '';
    const headline = heterogeneous || object(data.headline_statistics).available === false ? `<div class="empty-state-text">COMBINED HEADLINE REACTIONS UNAVAILABLE — ${label(object(data.headline_statistics).reason || 'backend suppressed', escape)}</div>` : priceTable(object(data.price_statistics));
    const decisionState = decision.truncated === true ? `<div class="reaction-warning"><strong>DECISION COHORT TRUNCATED</strong><br>Complete-cohort statistics are unavailable. ${label(decision.reason, escape)}</div>` : decision.statistics_available === false ? `<div class="empty-state-text">DECISION STATISTICS UNAVAILABLE — ${label(decision.reason || 'no eligible decisions', escape)}</div>` : decisionSummary(decision, escape);
    panel.innerHTML = `<div class="card-header"><span class="card-title">MULTI-EVENT STATISTICAL VALIDATION</span></div>
      <div class="reaction-warning"><strong>DESCRIPTIVE · NON-CAUSAL · RESEARCH ONLY</strong><br>Observed patterns after selected events do not establish a causal relationship.</div>${warning}
      <section class="reaction-v2"><h3>STUDY / SAMPLE OVERVIEW</h3><div class="research-stat-grid">${metric('Candidate', number(sample.candidate_event_count))}${metric('Included', number(sample.included_event_count))}${metric('Excluded', number(sample.excluded_event_count))}${metric('Contract', escape(study.contract_version || manifest.study_contract_version || '--'))}${metric('Requested range', `${escape(filters.start_ts || filters.start || '--')} → ${escape(filters.end_ts || filters.end || '--')}`)}${metric('Evaluated', escape(manifest.evaluated_at || '--'))}${metric('Overlap policy', escape(manifest.overlap_policy || object(data.overlap).policy || '--'))}</div>${breakdown('EVENT-TIME-BASIS COMPOSITION', sample.event_time_basis_counts, escape)}${breakdown('EVENT-TYPE COMPOSITION', sample.event_type_counts, escape)}${breakdown('EVENT-FAMILY COMPOSITION', sample.event_family_counts, escape)}${breakdown('SOURCE COMPOSITION', sample.source_counts, escape)}<details><summary>Study identity</summary><p>Sample ID: <code>${escape(study.sample_id || '--')}</code><br>Sample hash: <code>${escape(study.sample_hash || '--')}</code></p></details></section>
      <section class="reaction-v2"><h3>HEADLINE PRICE REACTIONS · MEDIAN</h3>${headline}</section>${scalarTable('REALIZED FUNDING REACTIONS · MEDIAN Δ BPS', object(data.funding_statistics), 'funding', escape)}${scalarTable('PERPETUAL BASIS REACTIONS · MEDIAN Δ BPS', object(data.basis_statistics), 'basis', escape)}
      <section class="reaction-v2"><h3>STRATIFIED RESULTS</h3>${strata(data, escape)}</section>
      <details><summary>OBSERVED TRANSITIONS AFTER EVENTS · NOT CAUSAL</summary>${regimeView(object(data.regime_statistics), escape)}</details>
      <details><summary>EVENT-LINKED DECISION OUTCOMES</summary><p><strong>BLOCK outcomes describe counterfactual subsequent market movement, not realized portfolio profit/loss.</strong></p><p><strong>EXPLICIT RECORDED LINK</strong> requires immutable recorded evidence. <strong>TEMPORAL PROXIMITY</strong> means the decision occurred within the governed event window and is not evidence that the event determined the decision.</p>${decisionState}</details>
      <details><summary>SAMPLE FUNNEL · ATTRITION · MISSINGNESS · OVERLAP</summary><div class="sample-funnel">Candidate → Eligible → Matured → Non-overlap → Valid pre-event reference → Valid target → Observed</div>${missingnessView(data, escape)}<p><strong>Overlap policy:</strong> ${escape(object(data.overlap).policy || '--')}. Overlapping windows are excluded to reduce repeated counting of the same market interval; this does not establish statistically independent samples.</p></details>
      <details><summary>DATA QUERY INTEGRITY</summary>${queryIntegrity(object(data.data_query_integrity), escape)}</details>
      <details><summary>METHODOLOGY / LIMITATIONS</summary><div class="research-stat-grid">${metric('Bootstrap method', escape(bootstrap.method || '--'))}${metric('Bootstrap seed', number(bootstrap.seed))}${metric('Bootstrap iterations', number(bootstrap.iterations))}${metric('Bootstrap minimum n', number(bootstrap.minimum_n))}${metric('Winsorization policy', escape(winsor.policy || '--'))}${metric('Significance testing', contract.significance_testing === false ? 'FALSE — NOT PERFORMED' : 'UNAVAILABLE')}</div><p><strong>DESCRIPTIVE BOOTSTRAP INTERVAL</strong> does not estimate a causal effect.</p><div class="reaction-warning">Many descriptive slices are shown. Apparent patterns may arise by chance and require independent validation.</div><p>${escape(contract.warning || '')}</p><div class="limitations">${(Array.isArray(data.limitations) ? data.limitations : []).map(item => escape(item)).join('<br>') || 'No additional limitations returned.'}</div></details>`;
  }

  window.ReactionStatisticsUI = { render };
}());

import('/frontend/assets/price-integrity-ui.js').catch(error => {
  console.warn('[PriceIntegrityUI] diagnostics module unavailable:', error);
});
