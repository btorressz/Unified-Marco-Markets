const UI = (() => {
  function formatTimestamp(ts) {
    if (!ts) return '--';
    try {
      const d = new Date(ts);
      return d.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false });
    } catch { return '--'; }
  }

  function formatNumber(n, decimals = 2) {
    if (n === null || n === undefined || isNaN(n)) return '--';
    return Number(n).toFixed(decimals);
  }

  function formatPrice(n) {
    if (n === null || n === undefined || isNaN(n)) return '--';
    return Number(n).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 4 });
  }

  function classForValue(val) {
    if (val > 0) return 'green';
    if (val < 0) return 'red';
    return '';
  }

  function renderFreshnessBadge(elementId, ts, thresholds) {
    const el = document.getElementById(elementId);
    if (!el) return;
    if (!ts) {
      el.className = 'freshness-badge nodata';
      el.innerHTML = '<span class="freshness-dot"></span> NO DATA';
      return;
    }
    const stale = (thresholds && thresholds.stale) || 120;
    const degraded = (thresholds && thresholds.degraded) || 300;
    const age = (Date.now() - new Date(ts).getTime()) / 1000;
    let level, label;
    if (age < 10) { level = 'live'; label = 'LIVE'; }
    else if (age < stale) { level = 'fresh'; label = 'FRESH'; }
    else if (age < degraded) { level = 'stale'; label = 'STALE'; }
    else { level = 'degraded'; label = 'DEGRADED'; }
    const ageText = age < 60 ? Math.round(age) + 's' : Math.round(age / 60) + 'm';
    el.className = 'freshness-badge ' + level;
    el.innerHTML = `<span class="freshness-dot"></span> ${label} <span style="opacity:0.7">${ageText} ago</span>`;
  }

  function renderDecisionDataPanel(data) {
    const panel = document.getElementById('decision-data-panel');
    if (!panel) return;
    const items = [];
    let worstLevel = 'ok';

    function addItem(label, ts, source) {
      if (!ts) {
        items.push({ label, status: 'nodata', age: '--', source: source || '--' });
        if (worstLevel !== 'degraded') worstLevel = 'degraded';
        return;
      }
      const age = (Date.now() - new Date(ts).getTime()) / 1000;
      let status = 'ok';
      if (age > 300) { status = 'degraded'; worstLevel = 'degraded'; }
      else if (age > 120) { status = 'stale'; if (worstLevel === 'ok') worstLevel = 'stale'; }
      const ageText = age < 60 ? Math.round(age) + 's' : Math.round(age / 60) + 'm';
      items.push({ label, status, age: ageText, source: source || '--' });
    }

    if (data.health) {
      addItem('System Health', data.health.ts || new Date().toISOString(), 'health');
    }
    if (data.integrity) {
      addItem('Price Integrity', data.integrity.ts, data.integrity.status || 'OK');
    }
    if (data.indexData) {
      addItem('Tariff Index', data.indexData.ts, 'index');
    }

    const panelCls = worstLevel === 'degraded' ? 'degraded' : worstLevel === 'stale' ? 'warning' : '';
    panel.className = 'decision-data-panel ' + panelCls;

    let html = '';
    if (worstLevel !== 'ok') {
      const warnMsg = worstLevel === 'degraded' ? 'Some data sources are degraded — trade with caution' : 'Some data is stale — verify before trading';
      html += `<div style="color:var(--accent-${worstLevel === 'degraded' ? 'red' : 'yellow'});font-size:12px;margin-bottom:8px;font-weight:600">&#9888; ${warnMsg}</div>`;
    }
    items.forEach(item => {
      const dotCls = item.status === 'ok' ? 'ok' : item.status === 'stale' ? 'warning' : 'error';
      html += `<div class="decision-data-row"><span><span class="feed-status-dot ${dotCls}"></span>${item.label}</span><span style="color:var(--text-muted)">${item.age} ago</span><span style="color:var(--text-muted)">${item.source}</span></div>`;
    });
    panel.innerHTML = html || '<div style="font-size:12px;color:var(--text-muted)">No data quality info available</div>';
  }

  function renderIndexTab(data) {
    const el = document.getElementById('index-value');
    const shockEl = document.getElementById('shock-value');
    const rocEl = document.getElementById('roc-value');
    const tsEl = document.getElementById('index-ts');

    if (data.latest) {
      if (el) el.textContent = formatNumber(data.latest.tariff_index, 4);
      if (shockEl) {
        shockEl.textContent = formatNumber(data.latest.shock_score, 4);
        shockEl.className = 'metric-value ' + (data.latest.shock_score > 0.5 ? 'red' : data.latest.shock_score > 0.2 ? 'yellow' : 'green');
      }
      if (tsEl) tsEl.textContent = 'Updated: ' + formatTimestamp(data.latest.ts);
      renderFreshnessBadge('index-freshness', data.latest.ts);
    }

    if (data.history && data.history.points && window._indexChart) {
      const pts = data.history.points;
      Charts.updateChart(window._indexChart, {
        labels: pts.map(p => formatTimestamp(p.ts)),
        datasets: [
          { data: pts.map(p => p.index_level) },
          { data: pts.map(p => p.shock_score) },
        ],
      });
      if (rocEl && pts.length > 0) {
        const lastRoc = pts[pts.length - 1].rate_of_change || 0;
        rocEl.textContent = formatNumber(lastRoc, 4);
        rocEl.className = 'metric-value ' + classForValue(lastRoc);
      }
    }

    if (data.components) {
      const tbody = document.getElementById('components-tbody');
      if (tbody) {
        const comps = data.components.components || {};
        tbody.innerHTML = '';
        Object.entries(comps).forEach(([name, value]) => {
          const tr = document.createElement('tr');
          tr.innerHTML = `<td>${name}</td><td>${formatNumber(value, 4)}</td>`;
          tbody.appendChild(tr);
        });
        if (data.components.wits_weight !== undefined) {
          ['wits_weight', 'gdelt_weight', 'funding_weight'].forEach(k => {
            if (data.components[k] !== undefined && !comps[k]) {
              const tr = document.createElement('tr');
              tr.innerHTML = `<td>${k}</td><td>${formatNumber(data.components[k], 4)}</td>`;
              tbody.appendChild(tr);
            }
          });
        }
      }
    }

    if (data.prediction) {
      const pred = data.prediction;
      const upEl = document.getElementById('pred-up');
      const confEl = document.getElementById('pred-confidence');
      const drvEl = document.getElementById('pred-drivers');
      if (upEl) {
        const pct = (pred.probability_up * 100).toFixed(1);
        upEl.textContent = pct + '%';
        upEl.className = 'metric-value ' + (pred.probability_up > 0.5 ? 'green' : 'red');
      }
      if (confEl) confEl.textContent = formatNumber(pred.confidence, 4);
      if (drvEl && pred.top_drivers) {
        drvEl.innerHTML = pred.top_drivers.map(d =>
          `<span class="badge badge-blue" style="margin:2px">${d[0]}: ${formatNumber(d[1], 3)}</span>`
        ).join('');
      }
    }

    if (data.macroTerminal) {
      renderMacroTerminal(data.macroTerminal);
    }
  }

  function renderMacroTerminal(mt) {
    const freshnessEl = document.getElementById('macro-terminal-freshness');
    if (freshnessEl) {
      if (mt.ts) {
        freshnessEl.textContent = 'As of: ' + formatTimestamp(mt.ts);
      } else {
        freshnessEl.textContent = '';
      }
    }

    const seriesEl = document.getElementById('macro-wits-series');
    if (seriesEl) {
      const series = mt.tariff_series || [];
      if (series.length === 0) {
        seriesEl.innerHTML = '<div class="empty-state"><div class="empty-state-text">No WITS series data available</div></div>';
      } else {
        const rows = series.slice(-20).map(s =>
          `<div class="guardrail-row"><span class="guardrail-label">${formatTimestamp(s.ts)}</span><span class="guardrail-value">${formatNumber(s.index_level, 4)}</span></div>`
        ).join('');
        seriesEl.innerHTML = `<div style="max-height:200px;overflow-y:auto">${rows}</div>`;
      }
    }

    const deltaEl = document.getElementById('macro-rolling-delta');
    if (deltaEl) {
      const deltas = mt.rolling_delta || [];
      if (deltas.length === 0) {
        deltaEl.innerHTML = '<div class="empty-state"><div class="empty-state-text">No rolling delta data available</div></div>';
      } else {
        const rows = deltas.slice(-20).map(d => {
          const cls = d.delta > 0 ? 'green' : d.delta < 0 ? 'red' : '';
          const arrow = d.delta > 0 ? '▲' : d.delta < 0 ? '▼' : '—';
          return `<div class="guardrail-row"><span class="guardrail-label">${formatTimestamp(d.ts)}</span><span class="guardrail-value ${cls}">${arrow} ${formatNumber(d.delta, 4)}</span></div>`;
        }).join('');
        deltaEl.innerHTML = `<div style="max-height:200px;overflow-y:auto">${rows}</div>`;
      }
    }

    const weightsEl = document.getElementById('macro-country-weights');
    if (weightsEl) {
      const weights = mt.country_weights || [];
      if (weights.length === 0) {
        weightsEl.innerHTML = '<div class="empty-state"><div class="empty-state-text">No country weight data available</div></div>';
      } else {
        const header = '<div class="guardrail-row" style="font-weight:600;border-bottom:1px solid var(--border-color)"><span class="guardrail-label">Country</span><span style="flex:1;text-align:right;font-size:12px">Tariff Rate</span><span style="flex:1;text-align:right;font-size:12px">Weight %</span></div>';
        const rows = weights.map(w => {
          const barW = Math.min(w.weight_pct || 0, 100);
          return `<div class="guardrail-row"><span class="guardrail-label">${w.country || w.code}</span><span style="flex:1;text-align:right;font-size:13px">${formatNumber(w.tariff_rate, 2)}%</span><span style="flex:1;text-align:right;font-size:13px">${formatNumber(w.weight_pct, 1)}%</span></div><div style="height:3px;background:var(--bg-tertiary);border-radius:2px;margin-bottom:4px"><div style="height:3px;width:${barW}%;background:var(--accent-blue);border-radius:2px"></div></div>`;
        }).join('');
        weightsEl.innerHTML = header + rows;
      }
    }

    const heatmapEl = document.getElementById('macro-heatmap');
    if (heatmapEl) {
      const corr = mt.correlations || {};
      const keys = Object.keys(corr);
      if (keys.length === 0) {
        heatmapEl.innerHTML = '<div class="empty-state"><div class="empty-state-text">No correlation data available</div></div>';
      } else {
        const rows = keys.map(k => {
          const v = corr[k];
          const abs = Math.abs(v);
          const bg = abs > 0.7 ? 'rgba(248,81,73,0.3)' : abs > 0.3 ? 'rgba(210,153,34,0.3)' : 'rgba(63,185,80,0.2)';
          const label = k.replace(/_/g, ' ').replace('tariff delta vs ', '');
          return `<div class="guardrail-row" style="background:${bg};border-radius:4px;margin-bottom:4px;padding:6px 8px"><span class="guardrail-label" style="font-size:12px;text-transform:capitalize">${label}</span><span class="guardrail-value" style="font-size:14px;font-weight:600">${formatNumber(v, 4)}</span></div>`;
        }).join('');
        heatmapEl.innerHTML = rows;
      }
    }
  }

  function renderMarketsTab(data) {
    if (data.latest) {
      const tbody = document.getElementById('markets-tbody');
      if (tbody) {
        tbody.innerHTML = '';
        data.latest.forEach(m => {
          const tr = document.createElement('tr');
          tr.innerHTML = `<td>${m.symbol || '--'}</td><td>${m.source || '--'}</td><td>${formatPrice(m.price)}</td><td>${formatNumber(m.confidence, 2)}</td><td>${formatTimestamp(m.ts)}</td>`;
          tbody.appendChild(tr);
        });
      }
      const latestTs = data.latest.length > 0 ? data.latest[0].ts : null;
      renderFreshnessBadge('markets-freshness', latestTs);
    }

    if (data.funding && data.funding.funding_rates && window._fundingChart) {
      const rates = data.funding.funding_rates;
      Charts.updateChart(window._fundingChart, {
        labels: rates.map(r => r.symbol || r.market || 'Unknown'),
        datasets: [{
          data: rates.map(r => (r.funding_rate || r.rate || 0) * 10000),
          backgroundColor: rates.map(r => {
            const v = r.funding_rate || r.rate || 0;
            return v >= 0 ? 'rgba(63, 185, 80, 0.7)' : 'rgba(248, 81, 73, 0.7)';
          }),
        }],
      });
    }

    if (data.carry) {
      const panel = document.getElementById('carry-panel');
      if (panel) {
        const scores = data.carry.scores || [];
        if (scores.length === 0) {
          panel.innerHTML = '<div style="font-size:13px;color:var(--text-muted);text-align:center;padding:20px">No carry data</div>';
        } else {
          panel.innerHTML = scores.map(s => {
            const cls = s.annualized_carry > 0 ? 'green' : s.annualized_carry < 0 ? 'red' : '';
            return `<div class="guardrail-row"><span class="guardrail-label">${s.market || s.symbol || '--'}</span><span class="guardrail-value ${cls}">${formatNumber(s.annualized_carry * 100, 2)}% APR</span></div>`;
          }).join('');
        }
      }
    }

    if (data.microstructure) {
      const ms = data.microstructure;
      const obEl = document.getElementById('ob-imbalance');
      const biasEl = document.getElementById('ob-bias');
      const basisEl = document.getElementById('basis-info');
      if (obEl) {
        obEl.textContent = formatNumber(ms.ob_imbalance, 4);
        obEl.className = 'card-value ' + (ms.ob_imbalance > 0.1 ? 'positive' : ms.ob_imbalance < -0.1 ? 'negative' : '');
      }
      if (biasEl) biasEl.textContent = ms.ob_bias || '--';
      if (basisEl) {
        if (ms.basis_bps !== undefined) {
          basisEl.innerHTML = `<div><strong>${formatNumber(ms.basis_bps, 2)} bps</strong> basis</div><div style="margin-top:4px">${ms.basis_opportunity || 'None'}</div>`;
        }
      }
    }

    if (data.integrity) {
      const el = document.getElementById('integrity-detail');
      const badge = document.getElementById('price-integrity-badge');
      if (el) {
        const devs = data.integrity.deviations || {};
        const entries = Object.entries(devs);
        if (entries.length === 0) {
          el.innerHTML = `<span class="badge badge-green">${data.integrity.status || 'OK'}</span> ${data.integrity.reason || ''}`;
        } else {
          el.innerHTML = entries.map(([venue, pct]) => {
            const cls = Math.abs(pct) > 1 ? 'badge-red' : Math.abs(pct) > 0.5 ? 'badge-yellow' : 'badge-green';
            return `<span class="badge ${cls}" style="margin:2px">${venue}: ${formatNumber(pct, 3)}%</span>`;
          }).join('');
        }
      }
      if (badge) {
        const st = (data.integrity.status || 'OK').toUpperCase();
        badge.textContent = 'Price: ' + st;
        badge.className = 'integrity-badge ' + (st === 'OK' ? 'ok' : st === 'WARNING' ? 'warn' : 'alert');
      }
    }

    if (data.solanaQuality) {
      const sq = data.solanaQuality;
      const scoreEl = document.getElementById('solana-quality-score');
      const riskEl = document.getElementById('solana-slippage-risk');
      const latEl = document.getElementById('solana-rpc-latency');
      const congEl = document.getElementById('solana-congestion');
      const routeEl = document.getElementById('solana-route-info');
      if (scoreEl) {
        scoreEl.textContent = formatNumber(sq.execution_quality_score, 1);
        scoreEl.className = 'card-value ' + (sq.execution_quality_score >= 80 ? 'green' : sq.execution_quality_score >= 50 ? 'yellow' : 'red');
      }
      if (riskEl) riskEl.textContent = 'Slippage: ' + (sq.slippage_risk || '--');
      if (latEl) latEl.textContent = formatNumber(sq.components?.latency_score || 0, 0) + ' ms';
      if (congEl) congEl.textContent = sq.congestion_warning ? 'CONGESTED' : 'Normal';
      if (routeEl) {
        const c = sq.components || {};
        routeEl.innerHTML = `<div>Spread Score: ${formatNumber(c.spread_score, 1)}</div><div>Impact Score: ${formatNumber(c.impact_score, 1)}</div><div>Depth Score: ${formatNumber(c.depth_score, 1)}</div>`;
      }
    }

    if (data.fundingArb) {
      const fa = data.fundingArb;
      const panel = document.getElementById('funding-arb-panel');
      if (panel) {
        const sigCls = fa.arb_signal === 'none' ? 'blue' : 'green';
        panel.innerHTML = `
          <div class="metric-row">
            <div class="metric-box" style="flex:1"><div class="metric-label">Signal</div><div class="metric-value ${sigCls}" style="font-size:14px">${fa.arb_signal || 'none'}</div></div>
            <div class="metric-box" style="flex:1"><div class="metric-label">Spread</div><div class="metric-value" style="font-size:16px">${formatNumber(fa.spread_bps, 2)} bps</div></div>
            <div class="metric-box" style="flex:1"><div class="metric-label">Persistence</div><div class="metric-value" style="font-size:16px">${formatNumber(fa.persistence_minutes, 0)} min</div></div>
            <div class="metric-box" style="flex:1"><div class="metric-label">Net Carry</div><div class="metric-value" style="font-size:16px">${formatNumber(fa.expected_net_carry * 100, 2)}%</div></div>
          </div>
        `;
      }
    }

    if (data.basis) {
      const b = data.basis;
      const panel = document.getElementById('basis-monitor-panel');
      if (panel) {
        panel.innerHTML = `
          <div class="metric-row">
            <div class="metric-box" style="flex:1"><div class="metric-label">HL-Spot Basis</div><div class="metric-value" style="font-size:14px">${formatNumber(b.hl_spot_basis_bps, 2)} bps</div></div>
            <div class="metric-box" style="flex:1"><div class="metric-label">Drift-Spot Basis</div><div class="metric-value" style="font-size:14px">${formatNumber(b.drift_spot_basis_bps, 2)} bps</div></div>
            <div class="metric-box" style="flex:1"><div class="metric-label">HL-Drift Spread</div><div class="metric-value" style="font-size:14px">${formatNumber(b.hl_drift_spread_bps, 2)} bps</div></div>
            <div class="metric-box" style="flex:1"><div class="metric-label">Ann. Basis</div><div class="metric-value" style="font-size:14px">${formatNumber(b.annualized_basis_bps, 2)} bps</div></div>
            <div class="metric-box" style="flex:1"><div class="metric-label">Net Carry</div><div class="metric-value" style="font-size:14px">${formatNumber(b.net_carry, 4)}</div></div>
          </div>
        `;
      }
    }
  }

  function renderDivergenceTab(data) {
    if (data.spreads && data.spreads.length > 0) {
      renderFreshnessBadge('divergence-freshness', data.spreads[0].ts || new Date().toISOString());
    }
    if (data.spreads && window._divergenceChart) {
      Charts.updateChart(window._divergenceChart, {
        labels: data.spreads.map(s => `${s.venue_a}/${s.venue_b}`),
        datasets: [{
          data: data.spreads.map(s => s.spread_bps),
          backgroundColor: data.spreads.map(s => {
            const abs = Math.abs(s.spread_bps);
            if (abs > 50) return 'rgba(248, 81, 73, 0.7)';
            if (abs > 20) return 'rgba(210, 153, 34, 0.7)';
            return 'rgba(63, 185, 80, 0.7)';
          }),
        }],
      });

      const tbody = document.getElementById('spreads-tbody');
      if (tbody) {
        tbody.innerHTML = '';
        data.spreads.forEach(s => {
          const abs = Math.abs(s.spread_bps);
          const cls = abs > 50 ? 'badge-red' : abs > 20 ? 'badge-yellow' : 'badge-green';
          const tr = document.createElement('tr');
          tr.innerHTML = `<td>${s.market || '--'}</td><td>${s.venue_a}</td><td>${formatPrice(s.price_a)}</td><td>${s.venue_b}</td><td>${formatPrice(s.price_b)}</td><td><span class="badge ${cls}">${formatNumber(s.spread_bps, 2)} bps</span></td>`;
          tbody.appendChild(tr);
        });
      }
    }

    if (data.alerts) {
      const container = document.getElementById('divergence-alerts');
      if (container) {
        container.innerHTML = '';
        if (data.alerts.length === 0) {
          container.innerHTML = '<div class="empty-state"><div class="empty-state-text">No divergence alerts</div></div>';
        } else {
          data.alerts.forEach(a => {
            const div = document.createElement('div');
            div.className = `alert-item ${a.severity || 'info'}`;
            div.innerHTML = `<span class="alert-message">${a.message}</span><span class="alert-time">${formatTimestamp(a.ts)}</span>`;
            container.appendChild(div);
          });
        }
      }
    }
  }

  function renderStablecoinsTab(data) {
    if (data.health) {
      const h = data.health;
      const stables = h.stablecoins || [];
      stables.forEach(s => {
        const sym = (s.symbol || '').toLowerCase();
        const box = document.getElementById('stable-' + sym);
        if (box) {
          const depeg = Math.abs(s.depeg_bps || 0);
          const color = depeg > 50 ? 'red' : depeg > 10 ? 'yellow' : 'green';
          box.querySelector('.metric-value').textContent = '$' + formatNumber(s.price, 4);
          box.querySelector('.metric-value').className = 'metric-value ' + color;
          box.querySelector('.metric-sublabel').textContent = formatNumber(depeg, 1) + ' bps depeg';
        }
      });

      const heatTbody = document.querySelector('#depeg-heatmap tbody');
      if (heatTbody) {
        heatTbody.innerHTML = '';
        stables.forEach(s => {
          const depeg = Math.abs(s.depeg_bps || 0);
          const cls = depeg > 50 ? 'badge-red' : depeg > 10 ? 'badge-yellow' : 'badge-green';
          const status = depeg > 50 ? 'DEPEGGING' : depeg > 10 ? 'STRESSED' : 'STABLE';
          const tr = document.createElement('tr');
          tr.innerHTML = `<td>${s.symbol}</td><td>${formatPrice(s.price)}</td><td>${formatNumber(depeg, 1)}</td><td><span class="badge ${cls}">${status}</span></td>`;
          heatTbody.appendChild(tr);
        });
      }

      const stressPanel = document.getElementById('stable-stress-panel');
      if (stressPanel) {
        const stress = h.stress_level || 'LOW';
        const pegBreak = h.peg_break_probability || 0;
        const stressCls = stress === 'HIGH' || stress === 'CRITICAL' ? 'red' : stress === 'MEDIUM' ? 'yellow' : 'green';
        stressPanel.innerHTML = `
          <div class="guardrail-row"><span class="guardrail-label">Stress Level</span><span class="guardrail-value ${stressCls}">${stress}</span></div>
          <div class="guardrail-row"><span class="guardrail-label">Peg Break Probability</span><span class="guardrail-value">${formatNumber(pegBreak * 100, 2)}%</span></div>
          <div class="guardrail-row"><span class="guardrail-label">Composite Score</span><span class="guardrail-value">${formatNumber(h.composite_health, 4)}</span></div>
        `;
      }
    }

    if (data.alerts) {
      const container = document.getElementById('stable-alerts');
      if (container) {
        container.innerHTML = '';
        if (data.alerts.length === 0) {
          container.innerHTML = '<div class="empty-state"><div class="empty-state-text">No stablecoin alerts</div></div>';
        } else {
          data.alerts.forEach(a => {
            const div = document.createElement('div');
            div.className = `alert-item ${a.severity || 'warning'}`;
            div.innerHTML = `<span class="alert-message">${a.message || a.alert_type || '--'}</span><span class="alert-time">${formatTimestamp(a.ts)}</span>`;
            container.appendChild(div);
          });
        }
      }
    }

    if (data.stableFlow) {
      const panel = document.getElementById('stable-flow-panel');
      if (panel) {
        const sf = data.stableFlow;
        const momCls = sf.stable_flow_momentum > 0.2 ? 'green' : sf.stable_flow_momentum < -0.2 ? 'red' : 'blue';
        const indCls = sf.risk_on_off_indicator === 'risk_on' ? 'green' : sf.risk_on_off_indicator === 'risk_off' ? 'red' : 'blue';
        const drivers = (sf.drivers || []).map(d => `<div style="font-size:12px;color:var(--text-muted);margin-top:2px">- ${d}</div>`).join('');
        panel.innerHTML = `
          <div class="metric-row">
            <div class="metric-box" style="flex:1"><div class="metric-label">Flow Momentum</div><div class="metric-value ${momCls}" style="font-size:18px">${formatNumber(sf.stable_flow_momentum, 4)}</div></div>
            <div class="metric-box" style="flex:1"><div class="metric-label">Risk Signal</div><div class="metric-value ${indCls}" style="font-size:14px">${sf.risk_on_off_indicator || 'neutral'}</div></div>
          </div>
          <div style="margin-top:8px">${drivers}</div>
        `;
      }
    }
  }

  function renderStrategyTab(data) {
    const container = document.getElementById('rules-container');
    if (!container) return;
    container.innerHTML = '';

    if (data.evaluation && data.evaluation.length > 0) {
      data.evaluation.forEach(rule => {
        const div = document.createElement('div');
        div.className = 'rule-card';
        const actionColor = rule.action_type === 'open_short' || rule.action_type === 'reduce' || rule.action_type === 'rotate_to_stables' ? 'red' : rule.action_type === 'open_long' ? 'green' : 'blue';
        div.innerHTML = `
          <div class="rule-name">${rule.rule_name}</div>
          <div class="rule-action"><span class="badge badge-${actionColor}">${rule.action_type}</span> ${rule.venue} ${rule.market} ${rule.side} ${rule.size > 0 ? formatNumber(rule.size, 4) : ''}</div>
          <div class="rule-reason">${rule.reason}</div>
        `;
        container.appendChild(div);
      });
    } else {
      container.innerHTML = '<div class="empty-state"><div class="empty-state-icon">&#9889;</div><div class="empty-state-text">No active rule signals</div></div>';
    }

    if (data.status && data.status.rules) {
      const listEl = document.getElementById('rules-list');
      if (listEl) {
        listEl.innerHTML = '';
        data.status.rules.forEach(r => {
          const div = document.createElement('div');
          div.className = 'rule-card';
          div.innerHTML = `<div class="rule-name">${r.name}</div><div class="rule-action"><span class="badge badge-blue">${r.action_type}</span></div><div class="rule-reason">${r.explanation || ''}</div>`;
          listEl.appendChild(div);
        });
      }
    }

    if (data.adaptiveWeights) {
      const panel = document.getElementById('adaptive-weights-panel');
      if (panel) {
        const aw = data.adaptiveWeights;
        const wt = aw.weights || {};
        const adjustments = (aw.adjustments || []).map(a => `<div style="font-size:12px;color:var(--text-muted);margin-top:2px">- ${a}</div>`).join('');
        panel.innerHTML = `
          <div class="metric-row">
            ${Object.entries(wt).map(([k, v]) => `<div class="metric-box" style="flex:1"><div class="metric-label">${k}</div><div class="metric-value blue" style="font-size:16px">${formatNumber(v * 100, 1)}%</div></div>`).join('')}
          </div>
          <div style="margin-top:6px;font-size:12px;color:var(--text-secondary)">Adaptive: ${aw.adaptive_enabled ? 'ON' : 'OFF'}</div>
          ${adjustments}
        `;
      }
    }

    if (data.portfolio) {
      const panel = document.getElementById('portfolio-proposal-panel');
      if (panel) {
        const p = data.portfolio;
        const alloc = p.allocation || {};
        const reasoning = (p.reasoning || []).map(r => `<div style="font-size:12px;color:var(--text-muted);margin-top:2px">- ${r}</div>`).join('');
        panel.innerHTML = `
          <div style="margin-bottom:8px;font-size:12px;color:var(--text-secondary)">Method: ${p.method || 'risk_parity'}</div>
          <div class="metric-row">
            ${Object.entries(alloc).map(([k, v]) => {
              const pct = (v * 100).toFixed(1);
              const barW = Math.min(pct, 100);
              return `<div class="metric-box" style="flex:1"><div class="metric-label">${k.replace(/_/g, ' ')}</div><div class="metric-value" style="font-size:14px">${pct}%</div><div style="height:4px;background:var(--bg-tertiary);border-radius:2px;margin-top:4px"><div style="height:4px;width:${barW}%;background:var(--accent-blue);border-radius:2px"></div></div></div>`;
            }).join('')}
          </div>
          <div style="margin-top:8px">${reasoning}</div>
        `;
      }
    }

    if (data.allocation) {
      renderAllocationPanel(data.allocation);
    }

    if (data.mlPrediction) {
      renderMLPanel(data.mlPrediction);
    }

    const btResult = document.getElementById('backtest-result-panel');
    if (btResult && data.backtestResult === null) {
      renderBacktestPanel(null);
    }
    if (data.backtestResult) {
      renderBacktestPanel(data.backtestResult);
    }
  }

  function renderExecutionTab(data) {
    if (data.positions) {
      const tbody = document.getElementById('positions-tbody');
      if (tbody) {
        tbody.innerHTML = '';
        const live = data.positions.live_positions || [];
        const db = data.positions.db_positions || [];
        const all = live.length ? live : db;
        if (all.length === 0) {
          tbody.innerHTML = '<tr><td colspan="6" class="empty-state-text" style="text-align:center;padding:20px">No positions</td></tr>';
        } else {
          all.forEach(p => {
            const tr = document.createElement('tr');
            tr.innerHTML = `<td>${p.venue || '--'}</td><td>${p.market || p.symbol || '--'}</td><td><span class="badge ${p.side === 'long' ? 'badge-green' : 'badge-red'}">${p.side || '--'}</span></td><td>${formatNumber(p.size, 4)}</td><td>${formatPrice(p.entry_price || p.price)}</td><td>${formatTimestamp(p.ts || p.opened_at)}</td>`;
            tbody.appendChild(tr);
          });
        }
      }
    }

    if (data.trades) {
      const tbody = document.getElementById('trades-tbody');
      if (tbody) {
        tbody.innerHTML = '';
        const trades = data.trades.trades || [];
        if (trades.length === 0) {
          tbody.innerHTML = '<tr><td colspan="7" class="empty-state-text" style="text-align:center;padding:20px">No paper trades</td></tr>';
        } else {
          trades.forEach(t => {
            const tr = document.createElement('tr');
            tr.innerHTML = `<td>${t.venue || '--'}</td><td>${t.market || '--'}</td><td><span class="badge ${t.side === 'buy' ? 'badge-green' : 'badge-red'}">${t.side || '--'}</span></td><td>${formatNumber(t.size, 4)}</td><td>${formatPrice(t.price)}</td><td><span class="badge badge-blue">${t.status || '--'}</span></td><td>${formatTimestamp(t.ts || t.created_at)}</td>`;
            tbody.appendChild(tr);
          });
        }
      }
    }

    renderExecutionSafety(data.guardrails);
    renderAccounting(data.positions);
    if (data.events) renderLifecycle(data.events);

    if (data.eqi) {
      const panel = document.getElementById('eqi-panel');
      if (panel) {
        const e = data.eqi;
        const scoreCls = e.eqi_score >= 80 ? 'green' : e.eqi_score >= 50 ? 'yellow' : 'red';
        const anomalies = (e.anomalies || []).map(a => `<div style="font-size:12px;color:var(--accent-red);margin-top:2px">- ${a}</div>`).join('');
        panel.innerHTML = `
          <div class="metric-row">
            <div class="metric-box"><div class="metric-label">EQI Score</div><div class="metric-value ${scoreCls}">${formatNumber(e.eqi_score, 1)}</div></div>
            <div class="metric-box"><div class="metric-label">Latency p50</div><div class="metric-value">${formatNumber(e.latency_p50_ms, 0)} ms</div></div>
            <div class="metric-box"><div class="metric-label">Latency p95</div><div class="metric-value">${formatNumber(e.latency_p95_ms, 0)} ms</div></div>
            <div class="metric-box"><div class="metric-label">Avg Slippage</div><div class="metric-value">${formatNumber(e.avg_slippage_bps, 2)} bps</div></div>
            <div class="metric-box"><div class="metric-label">Fill Count</div><div class="metric-value blue">${e.fill_count || 0}</div></div>
          </div>
          ${anomalies}
        `;
      }
    }
  }

  function renderRiskTab(data) {
    if (data.status) {
      const s = data.status;
      const banner = document.getElementById('throttle-banner');
      if (banner) {
        if (s.throttle_active) {
          banner.className = 'throttle-banner';
          banner.innerHTML = `<span>&#9888;</span> <strong>THROTTLE ACTIVE</strong> &mdash; ${s.throttle_reason || 'Risk limits reached'}`;
        } else {
          banner.className = 'throttle-banner inactive';
          banner.innerHTML = `<span>&#10003;</span> <strong>THROTTLE OFF</strong> &mdash; Trading enabled`;
        }
      }

      const setVal = (id, val, cls) => {
        const el = document.getElementById(id);
        if (el) {
          el.textContent = val;
          if (cls) el.className = 'metric-value ' + cls;
        }
      };
      setVal('risk-leverage', formatNumber(s.current_leverage, 2) + 'x');
      setVal('risk-margin', formatNumber(s.margin_usage * 100, 1) + '%');
      setVal('risk-pnl', '$' + formatNumber(s.daily_pnl, 2), classForValue(s.daily_pnl));
    }

    if (data.guardrails) {
      const g = data.guardrails;
      const container = document.getElementById('guardrails-container');
      if (container) {
        container.innerHTML = '';
        const items = [
          ['Max Leverage', g.max_leverage + 'x'],
          ['Max Margin Usage', (g.max_margin_usage * 100).toFixed(0) + '%'],
          ['Max Daily Loss', '$' + g.max_daily_loss],
          ['Cooldown', g.cooldown_seconds + 's'],
          ['Execution Mode', g.execution_mode || 'paper'],
        ];
        items.forEach(([label, value]) => {
          const div = document.createElement('div');
          div.className = 'guardrail-row';
          div.innerHTML = `<span class="guardrail-label">${label}</span><span class="guardrail-value">${value}</span>`;
          container.appendChild(div);
        });
      }
    }

    if (data.stressResult) {
      const r = data.stressResult;
      const container = document.getElementById('stress-result');
      if (container) {
        container.innerHTML = `
          <div class="card" style="margin-top:12px">
            <div class="card-header"><span class="card-title">Stress Test Result: ${r.scenario || '--'}</span></div>
            <div class="metric-row">
              <div class="metric-box"><div class="metric-label">Total P&amp;L Impact</div><div class="metric-value ${classForValue(r.total_pnl_impact)}">$${formatNumber(r.total_pnl_impact, 2)}</div></div>
              <div class="metric-box"><div class="metric-label">Max Drawdown</div><div class="metric-value red">$${formatNumber(r.max_drawdown, 2)}</div></div>
              <div class="metric-box"><div class="metric-label">Margin Call</div><div class="metric-value ${r.margin_call ? 'red' : 'green'}">${r.margin_call ? 'YES' : 'NO'}</div></div>
            </div>
          </div>
        `;
      }
    }

    if (data.mcResult) {
      renderMCResult(data.mcResult);
    }

    if (data.heatmap) {
      const panel = document.getElementById('liquidation-heatmap-panel');
      if (panel) {
        const hm = data.heatmap;
        const grid = hm.grid || {};
        const leverages = hm.leverage_levels || [];
        const drops = hm.price_drops_pct || hm.price_drops || [];
        if (leverages.length === 0 || drops.length === 0) {
          panel.innerHTML = '<div class="empty-state"><div class="empty-state-text">No heatmap data</div></div>';
        } else {
          let html = '<div style="overflow-x:auto"><table style="width:100%;border-collapse:collapse;font-size:11px">';
          html += '<tr><th style="padding:4px;text-align:left">Lev \\ Drop</th>';
          drops.forEach(d => { html += `<th style="padding:4px;text-align:center">${d}%</th>`; });
          html += '</tr>';
          leverages.forEach(lev => {
            html += `<tr><td style="padding:4px;font-weight:bold">${lev}x</td>`;
            const row = grid[String(lev)] || {};
            drops.forEach(drop => {
              const prob = row[String(drop)] || 0;
              const pct = (prob * 100).toFixed(0);
              const bg = prob >= 0.8 ? 'rgba(248,81,73,0.8)' : prob >= 0.5 ? 'rgba(248,81,73,0.5)' : prob >= 0.2 ? 'rgba(227,179,65,0.4)' : 'rgba(63,185,80,0.2)';
              html += `<td style="padding:4px;text-align:center;background:${bg};border:1px solid var(--border-color)">${pct}%</td>`;
            });
            html += '</tr>';
          });
          html += '</table></div>';
          panel.innerHTML = html;
        }
      }
    }

    if (data.analogs) {
      const panel = document.getElementById('regime-replay-panel');
      if (panel && data.analogs.analogs) {
        const analogs = data.analogs.analogs || [];
        if (analogs.length === 0) {
          panel.innerHTML = '<div class="empty-state"><div class="empty-state-text">No regime analogs found</div></div>';
        } else {
          const dist = data.analogs.outcome_distribution || {};
          let html = '<div class="metric-row">';
          html += `<div class="metric-box"><div class="metric-label">Avg 4h Return</div><div class="metric-value ${classForValue(dist.avg_return_4h)}">${formatNumber((dist.avg_return_4h || 0) * 100, 2)}%</div></div>`;
          html += `<div class="metric-box"><div class="metric-label">Avg 24h Return</div><div class="metric-value ${classForValue(dist.avg_return_24h)}">${formatNumber((dist.avg_return_24h || 0) * 100, 2)}%</div></div>`;
          html += `<div class="metric-box"><div class="metric-label">Win Rate 4h</div><div class="metric-value">${formatNumber((dist.win_rate_4h || 0) * 100, 1)}%</div></div>`;
          html += `<div class="metric-box"><div class="metric-label">Sample Count</div><div class="metric-value blue">${dist.count || 0}</div></div>`;
          html += '</div>';
          panel.innerHTML = html;
        }
      }
    }

    if (data.portfolioRisk !== undefined) {
      renderPortfolioRiskPanel(data.portfolioRisk);
    }

    renderPortfolioRiskBreakdown(data.portfolioContributions, data.portfolioExposures);
    renderRedisHealth(data.redis);

    if (data.volRegime !== undefined || data.volRecommendations !== undefined) {
      renderVolRegimePanel(data.volRegime, data.volRecommendations);
    }
  }

  function renderMCResult(mc) {
    const container = document.getElementById('mc-result');
    if (!container) return;
    container.innerHTML = `
      <div class="metric-row" style="margin-top:12px">
        <div class="metric-box"><div class="metric-label">VaR (95%)</div><div class="metric-value red">$${formatNumber(mc.var_95, 2)}</div></div>
        <div class="metric-box"><div class="metric-label">CVaR (95%)</div><div class="metric-value red">$${formatNumber(mc.cvar_95, 2)}</div></div>
        <div class="metric-box"><div class="metric-label">Mean P&amp;L</div><div class="metric-value ${classForValue(mc.mean_pnl)}">$${formatNumber(mc.mean_pnl, 2)}</div></div>
        <div class="metric-box"><div class="metric-label">Paths</div><div class="metric-value blue">${mc.n_paths || '--'}</div></div>
      </div>
    `;

    if (mc.distribution && window._mcChart) {
      const wrap = document.getElementById('mc-chart-wrap');
      if (wrap) wrap.style.display = 'block';
      Charts.updateChart(window._mcChart, {
        labels: mc.distribution.bins || mc.distribution.map((_, i) => i),
        datasets: [{
          data: mc.distribution.counts || mc.distribution,
        }],
      });
    }
  }

  function renderFeedStatus(data) {
    const panel = document.getElementById('feed-status-panel');
    if (!panel) return;
    const feeds = data.feeds || [];
    if (feeds.length === 0) {
      panel.innerHTML = '<div class="empty-state"><div class="empty-state-text">No feed data available</div></div>';
      return;
    }
    const statusBadge = (s) => {
      const cls = s === 'ok' ? 'badge-green' : s === 'warning' ? 'badge-yellow' : s === 'fallback' ? 'badge-blue' : 'badge-red';
      return `<span class="badge ${cls}">${s.toUpperCase()}</span>`;
    };
    const formatAge = (sec) => {
      if (sec === null || sec === undefined) return '--';
      if (sec < 60) return Math.round(sec) + 's';
      if (sec < 3600) return Math.round(sec / 60) + 'm';
      if (sec < 86400) return (sec / 3600).toFixed(1) + 'h';
      return (sec / 86400).toFixed(1) + 'd';
    };
    let html = '<div style="overflow-x:auto"><table style="width:100%;border-collapse:collapse;font-size:12px">';
    html += '<thead><tr><th style="padding:6px 8px;text-align:left">Feed</th><th style="padding:6px 8px;text-align:center">Status</th><th style="padding:6px 8px;text-align:center">Age</th><th style="padding:6px 8px;text-align:center">Last Update</th><th style="padding:6px 8px;text-align:center">Auth</th></tr></thead><tbody>';
    feeds.forEach(f => {
      const ts = f.last_update_ts ? formatTimestamp(f.last_update_ts) : '--';
      const auth = f.is_authoritative ? '<span class="badge badge-purple" style="font-size:10px">AUTH</span>' : '';
      html += `<tr style="border-bottom:1px solid var(--border-color)"><td style="padding:6px 8px;font-weight:500">${f.name}</td><td style="padding:6px 8px;text-align:center">${statusBadge(f.status)}</td><td style="padding:6px 8px;text-align:center">${formatAge(f.age_seconds)}</td><td style="padding:6px 8px;text-align:center;font-family:var(--font-mono);font-size:11px">${ts}</td><td style="padding:6px 8px;text-align:center">${auth}</td></tr>`;
    });
    html += '</tbody></table></div>';
    const summary = `<div style="margin-top:8px;font-size:11px;color:var(--text-muted)">${data.ok_count}/${data.total} feeds healthy &mdash; Overall: <span class="badge ${data.status === 'ok' ? 'badge-green' : data.status === 'degraded' ? 'badge-yellow' : 'badge-red'}" style="font-size:10px">${(data.status || 'unknown').toUpperCase()}</span></div>`;
    panel.innerHTML = html + summary;
  }

  function renderAgentsTab(data) {
    if (data.signals) {
      const sigs = data.signals.signals || data.signals;
      const sigList = Array.isArray(sigs) ? sigs : [];
      const container = document.getElementById('agent-signals-container');
      const countEl = document.getElementById('agent-signal-count');
      const tsEl = document.getElementById('agent-last-updated');
      const agentCountEl = document.getElementById('agent-count');
      if (countEl) countEl.textContent = sigList.length;
      if (tsEl) tsEl.textContent = formatTimestamp(data.signals.ts || null);
      if (agentCountEl) agentCountEl.textContent = data.signals.agent_count || 6;

      if (container) {
        container.innerHTML = '';
        if (sigList.length === 0) {
          container.innerHTML = '<div class="empty-state"><div class="empty-state-text">No active agent signals</div></div>';
        } else {
          sigList.forEach((sig, idx) => {
            const div = document.createElement('div');
            const severityCls = sig.severity === 'high' ? 'red' : sig.severity === 'medium' ? 'yellow' : 'green';
            const dirCls = sig.direction === 'bullish' ? 'green' : sig.direction === 'bearish' ? 'red' : 'blue';
            const conf = sig.confidence || 0;
            const confPct = (conf * 100).toFixed(0);
            const confCls = conf >= 0.85 ? 'red' : conf >= 0.75 ? 'yellow' : 'green';
            const actionBadge = sig.proposed_action ? `<span class="badge badge-${sig.proposed_action === 'block_execution' ? 'red' : sig.proposed_action === 'reduce_size' ? 'yellow' : 'blue'}">${(sig.proposed_action || '').replace(/_/g, ' ')}</span>` : '';
            const reasonId = 'agent-reason-' + idx;
            div.className = 'agent-signal-card';
            div.innerHTML = `
              <div class="agent-signal-header">
                <span class="badge badge-purple">${sig.agent || '--'}</span>
                <span class="badge badge-${severityCls}">${sig.severity || 'low'}</span>
                <span class="badge badge-${dirCls}">${sig.direction || 'neutral'}</span>
                ${actionBadge}
                <span class="agent-confidence-badge ${confCls}" title="Confidence">${confPct}%</span>
              </div>
              <div class="agent-signal-action">${sig.signal || sig.action || '--'}</div>
              <div class="agent-signal-reason-toggle" onclick="document.getElementById('${reasonId}').classList.toggle('expanded')">
                <span class="agent-toggle-icon">&#9654;</span> Reasoning
              </div>
              <div id="${reasonId}" class="agent-signal-reason-detail">${sig.reason || '--'}</div>
              <div class="agent-signal-meta">
                <span>Signal: ${formatTimestamp(sig.ts)}</span>
                <span>Data: ${formatTimestamp(sig.data_ts_used)}</span>
              </div>
            `;
            container.appendChild(div);
          });
        }
      }
    }

    if (data.registry) {
      const container = document.getElementById('agent-registry');
      if (container) {
        container.innerHTML = '';
        (data.registry.agents || []).forEach(agent => {
          const div = document.createElement('div');
          div.className = 'agent-registry-card';
          const statusCls = agent.status === 'active' ? 'green' : 'yellow';
          div.innerHTML = `
            <div class="agent-registry-header">
              <span class="agent-registry-name">${(agent.name || '').replace(/_/g, ' ')}</span>
              <span class="badge badge-${statusCls}">${agent.status || 'active'}</span>
            </div>
            <div class="agent-registry-desc">${agent.description || ''}</div>
          `;
          container.appendChild(div);
        });
      }
    }
  }

  function getEventClass(eventType) {
    if (!eventType) return 'event-info';
    const t = eventType.toUpperCase();
    if (t.includes('FILL') || t.includes('TRADE') || t.includes('EXECUTED')) return 'event-fill';
    if (t.includes('ERROR') || t.includes('FAIL')) return 'event-error';
    if (t.includes('ALERT') || t.includes('SHOCK') || t.includes('DIVERGENCE') || t.includes('WARN') || t.includes('DEPEG') || t.includes('STRESS') || t.includes('BREACH') || t.includes('DISLOCATION')) return 'event-alert';
    if (t.includes('ORDER') || t.includes('POSITION') || t.includes('AGENT')) return 'event-trade';
    return 'event-info';
  }

  function getTypeClass(eventType) {
    if (!eventType) return 'info';
    const t = eventType.toUpperCase();
    if (t.includes('FILL') || t.includes('TRADE') || t.includes('EXECUTED')) return 'fill';
    if (t.includes('ERROR') || t.includes('FAIL')) return 'error';
    if (t.includes('ALERT') || t.includes('SHOCK') || t.includes('DIVERGENCE') || t.includes('WARN') || t.includes('DEPEG') || t.includes('STRESS') || t.includes('BREACH') || t.includes('DISLOCATION')) return 'alert';
    if (t.includes('ORDER') || t.includes('POSITION') || t.includes('AGENT')) return 'trade';
    return 'info';
  }

  function addEventToTimeline(event, isNew = false) {
    const body = document.getElementById('timeline-body');
    if (!body) return;

    const div = document.createElement('div');
    div.className = `timeline-event ${getEventClass(event.event_type)}${isNew ? ' new' : ''}`;

    const payload = event.payload || {};
    const msg = payload.message || event.message || JSON.stringify(payload).substring(0, 120);

    div.innerHTML = `
      <span class="timeline-ts">${formatTimestamp(event.ts)}</span>
      <span class="timeline-type ${getTypeClass(event.event_type)}">${event.event_type || 'INFO'}</span>
      <span class="timeline-msg" title="${msg}">${msg}</span>
      <span class="timeline-source">${event.source || '--'}</span>
    `;

    body.prepend(div);

    while (body.children.length > 50) {
      body.removeChild(body.lastChild);
    }
  }

  function renderTimeline(events) {
    const body = document.getElementById('timeline-body');
    if (!body) return;
    body.innerHTML = '';
    events.forEach(e => addEventToTimeline(e, false));
    renderLifecycle(events);
  }

  function updateConnectionStatus(connected) {
    const badge = document.getElementById('connection-status');
    if (!badge) return;
    if (connected) {
      badge.className = 'status-badge connected';
      badge.innerHTML = '<span class="dot"></span> LIVE';
    } else {
      badge.className = 'status-badge disconnected';
      badge.innerHTML = '<span class="dot"></span> OFFLINE';
    }
  }

  function renderAllocationPanel(data) {
    const panel = document.getElementById('capital-allocation-panel');
    if (!panel) return;
    if (!data) {
      panel.innerHTML = '<div class="empty-state"><div class="empty-state-text">No allocation data</div></div>';
      return;
    }
    const weights = data.weights || {};
    const maxCap = data.max_capital_per_venue || {};
    const rar = data.risk_adjusted_expected_returns || {};
    const conf = data.confidence || 0;
    const confCls = conf >= 0.7 ? 'green' : conf >= 0.5 ? 'yellow' : 'red';
    const venueLabels = { hyperliquid: 'Hyperliquid', drift: 'Drift', jupiter_spot: 'Jupiter Spot', stablecoins: 'Stablecoins', cash: 'Cash' };
    const venueColors = { hyperliquid: 'var(--accent-blue)', drift: 'var(--accent-green)', jupiter_spot: 'var(--accent-yellow)', stablecoins: 'var(--accent-purple)', cash: 'var(--text-muted)' };

    let barsHtml = Object.entries(weights).map(([venue, w]) => {
      const pct = (w * 100).toFixed(1);
      const maxPct = ((maxCap[venue] || 1) * 100).toFixed(0);
      const rarPct = ((rar[venue] || 0) * 100).toFixed(2);
      const color = venueColors[venue] || 'var(--accent-blue)';
      return `
        <div style="margin-bottom:10px">
          <div style="display:flex;justify-content:space-between;margin-bottom:3px;font-size:12px">
            <span style="font-weight:500">${venueLabels[venue] || venue}</span>
            <span style="color:var(--text-muted)">${pct}% &nbsp;<span style="font-size:10px;opacity:0.6">max ${maxPct}% | RAR ${rarPct}%</span></span>
          </div>
          <div style="background:var(--bg-secondary);border-radius:4px;height:8px;overflow:hidden">
            <div style="width:${Math.min(parseFloat(pct),100)}%;height:100%;background:${color};border-radius:4px;transition:width 0.4s"></div>
          </div>
        </div>`;
    }).join('');

    const reasoning = (data.reasoning || []).map(r => `<div style="font-size:11px;color:var(--text-muted);padding:2px 0">• ${r}</div>`).join('');

    panel.innerHTML = `
      <div style="display:flex;align-items:center;gap:12px;margin-bottom:12px">
        <div><div style="font-size:11px;color:var(--text-muted)">Confidence</div><div class="metric-value ${confCls}" style="font-size:18px">${(conf*100).toFixed(0)}%</div></div>
        <div style="font-size:11px;color:var(--text-muted);flex:1">Proposal only — no auto-trade</div>
        <div style="font-size:11px;color:var(--text-muted)">${formatTimestamp(data.ts)}</div>
      </div>
      ${barsHtml}
      <details style="margin-top:10px">
        <summary style="font-size:11px;color:var(--text-muted);cursor:pointer">Reasoning</summary>
        <div style="margin-top:6px">${reasoning}</div>
      </details>
    `;
  }

  function renderMLPanel(data) {
    const panel = document.getElementById('ml-signal-panel');
    if (!panel) return;
    if (!data) {
      panel.innerHTML = '<div class="empty-state"><div class="empty-state-text">No ML prediction data</div></div>';
      return;
    }
    const pred = data.prediction || {};
    const prob = pred.probability || 0;
    const conf = pred.prediction_strength || 0;
    const modelType = pred.model_type || 'heuristic';
    const probCls = prob >= 0.6 ? 'green' : prob <= 0.4 ? 'red' : 'yellow';
    const confCls = conf >= 0.7 ? 'green' : conf >= 0.5 ? 'yellow' : 'red';
    const drivers = data.top_drivers || [];

    const driversHtml = drivers.slice(0, 5).map(d => {
      const contrib = d.contribution || 0;
      const dirCls = contrib > 0 ? 'green' : 'red';
      const bar = Math.min(Math.abs(contrib) * 500, 100).toFixed(0);
      return `
        <div style="display:flex;align-items:center;gap:8px;margin-bottom:4px;font-size:11px">
          <span style="width:120px;color:var(--text-secondary);white-space:nowrap;overflow:hidden;text-overflow:ellipsis" title="${d.description || d.feature}">${d.feature}</span>
          <div style="flex:1;background:var(--bg-secondary);border-radius:3px;height:6px;overflow:hidden">
            <div style="width:${bar}%;height:100%;background:${contrib>0?'var(--accent-green)':'var(--accent-red)'};border-radius:3px"></div>
          </div>
          <span class="${dirCls}" style="width:50px;text-align:right">${contrib>0?'+':''}${(contrib*100).toFixed(2)}%</span>
        </div>`;
    }).join('');

    panel.innerHTML = `
      <div class="metric-row">
        <div class="metric-box"><div class="metric-label">BTC Up Prob</div><div class="metric-value ${probCls}">${(prob*100).toFixed(1)}%</div></div>
        <div class="metric-box"><div class="metric-label">Prediction Strength</div><div class="metric-value ${confCls}">${(conf*100).toFixed(0)}%</div></div>
        <div class="metric-box"><div class="metric-label">Model</div><div class="metric-value blue" style="font-size:11px">${modelType.replace(/_/g,' ')}</div></div>
      </div>
      <div style="margin-top:10px;font-size:11px;color:var(--text-muted);margin-bottom:6px">Top Feature Drivers</div>
      ${driversHtml || '<div class="empty-state-text" style="font-size:11px">No driver data</div>'}
      <div style="margin-top:8px;font-size:10px;color:var(--text-muted)">${formatTimestamp(data.ts)}</div>
    `;
  }

  function renderMLGovernance(data) {
    const panel=document.getElementById('ml-governance-panel'); if (!panel) return;
    const active=data.active||{}, models=data.models||[], health=data.health||{}, comparison=data.comparison||{};
    const rows=models.map(m=>`<tr><td>${safeValue(m.model_version)}</td><td><span class="status-badge ${m.lifecycle_state}">${safeValue(m.lifecycle_state).toUpperCase()}</span></td><td>${safeValue(m.model_type)}</td><td>${safeValue(m.dataset_id)}</td><td>${safeValue((m.validation_metrics||{}).brier)}</td><td>${safeValue(m.created_at)}</td></tr>`).join('');
    panel.innerHTML=`<section><h3>Active Model</h3><strong>${safeValue(active.model_key)}:${safeValue(active.model_version)}</strong> <span class="status-badge active">${active.lifecycle_state?'ACTIVE':'NONE'}</span><div class="governance-detail">${safeValue(active.model_type)} · ${safeValue(active.feature_schema_id)} v${safeValue(active.feature_schema_version)} · label v${safeValue(active.label_definition_version)}<br>Dataset ${safeValue(active.dataset_id)} · run ${safeValue(active.training_run_id)}<br>Artifact ${safeValue(active.artifact_sha256)} · promoted ${safeValue(active.promoted_at)}</div></section>
    <section><h3>Model Health</h3><div class="metric-value ${health.status==='healthy'?'green':health.status==='degraded'?'red':'yellow'}">${safeValue(health.status).toUpperCase()}</div><div class="governance-detail">Monitoring is read-only and never changes lifecycle state.</div></section>
    <section class="governance-wide"><h3>Model Registry · Temporal Validation · Calibration</h3><div class="table-scroll"><table><thead><tr><th>Version</th><th>State</th><th>Method</th><th>Dataset</th><th>Brier</th><th>Created</th></tr></thead><tbody>${rows||'<tr><td colspan="6">No governed models</td></tr>'}</tbody></table></div></section>
    <section><h3>Training Runs</h3><div class="governance-detail">${(data.runs||[]).length} durable governed run(s)</div></section><section><h3>Heuristic vs ML</h3><div class="governance-detail">${comparison.comparable?'Comparable aligned 24h window':safeValue(comparison.reason)}</div></section>`;
  }

  function renderBacktestPanel(data) {
    const panel = document.getElementById('backtest-result-panel');
    if (!panel) return;
    if (!data || data.available === false) {
      panel.innerHTML = '<div class="empty-state"><div class="empty-state-text">Run a backtest to see results</div></div>';
      return;
    }
    const retCls = (data.total_return_pct || 0) >= 0 ? 'green' : 'red';
    const ddCls = 'red';
    const sharpeCls = (data.sharpe_ratio || 0) >= 1 ? 'green' : (data.sharpe_ratio || 0) >= 0 ? 'yellow' : 'red';
    const cfg = data.config || {};

    const eqCurve = data.equity_curve || [];
    let chartHtml = '';
    if (eqCurve.length > 1) {
      const min = Math.min(...eqCurve);
      const max = Math.max(...eqCurve);
      const range = max - min || 1;
      const points = eqCurve.map((v, i) => {
        const x = (i / (eqCurve.length - 1) * 100).toFixed(1);
        const y = (100 - ((v - min) / range * 80 + 10)).toFixed(1);
        return `${x},${y}`;
      }).join(' ');
      chartHtml = `
        <div style="margin-top:12px">
          <div style="font-size:11px;color:var(--text-muted);margin-bottom:4px">Equity Curve</div>
          <svg width="100%" height="80" viewBox="0 0 100 100" preserveAspectRatio="none" style="border:1px solid var(--border-color);border-radius:4px;background:var(--bg-secondary)">
            <polyline points="${points}" fill="none" stroke="var(--accent-blue)" stroke-width="0.8"/>
          </svg>
        </div>`;
    }

    const stratPnl = data.per_strategy_pnl || {};
    const stratHtml = Object.entries(stratPnl).map(([s, v]) =>
      `<span style="margin-right:12px;font-size:11px">${s}: <span class="${v>=0?'green':'red'}">${v>=0?'+':''}$${formatNumber(v,2)}</span></span>`
    ).join('');

    panel.innerHTML = `
      <div class="metric-row" style="flex-wrap:wrap">
        <div class="metric-box"><div class="metric-label">Total Return</div><div class="metric-value ${retCls}">${(data.total_return_pct||0)>=0?'+':''}${formatNumber(data.total_return_pct,2)}%</div></div>
        <div class="metric-box"><div class="metric-label">Sharpe</div><div class="metric-value ${sharpeCls}">${formatNumber(data.sharpe_ratio,3)}</div></div>
        <div class="metric-box"><div class="metric-label">Max DD</div><div class="metric-value ${ddCls}">${formatNumber(data.max_drawdown_pct,2)}%</div></div>
        <div class="metric-box"><div class="metric-label">Win Rate</div><div class="metric-value">${formatNumber((data.win_rate||0)*100,1)}%</div></div>
        <div class="metric-box"><div class="metric-label">Trades</div><div class="metric-value blue">${data.trade_count||0}</div></div>
        <div class="metric-box"><div class="metric-label">Avg Slip</div><div class="metric-value">${formatNumber(data.avg_slippage_bps,1)} bps</div></div>
        <div class="metric-box"><div class="metric-label">VaR 95%</div><div class="metric-value red">${formatNumber((data.var_95||0)*100,2)}%</div></div>
        <div class="metric-box"><div class="metric-label">CVaR 95%</div><div class="metric-value red">${formatNumber((data.cvar_95||0)*100,2)}%</div></div>
      </div>
      <div style="margin-top:8px;font-size:11px;color:var(--text-muted)">${cfg.strategy||'momentum'} | ${cfg.window_days||30}d | ${cfg.venue||'paper'} | fee ${cfg.fee_bps||10}bps</div>
      ${stratHtml ? `<div style="margin-top:6px">${stratHtml}</div>` : ''}
      ${chartHtml}
      <div style="margin-top:6px;font-size:10px;color:var(--text-muted)">${formatTimestamp(data.ts)}</div>
    `;
  }

  function renderVolRegimePanel(volRegime, volRecs) {
    const panel = document.getElementById('vol-regime-panel');
    if (!panel) return;

    if (!volRegime) {
      panel.innerHTML = '<div class="empty-state"><div class="empty-state-text">No volatility regime data</div></div>';
      return;
    }

    const regime = volRegime.regime || 'normal_volatility';
    const conf = volRegime.confidence || 0;
    const regimeLabel = regime.replace(/_/g, ' ').toUpperCase();
    const regimeCls = {
      low_volatility: 'green', normal_volatility: 'blue',
      high_volatility: 'yellow', shock_regime: 'red', liquidity_crunch: 'red'
    }[regime] || 'blue';

    const scores = volRegime.scores || {};
    const scoresHtml = Object.entries(scores).sort((a,b) => b[1]-a[1]).map(([r, s]) => {
      const bar = Math.min(s * 200, 100).toFixed(0);
      return `
        <div style="display:flex;align-items:center;gap:6px;margin-bottom:3px;font-size:11px">
          <span style="width:130px;color:var(--text-secondary)">${r.replace(/_/g,' ')}</span>
          <div style="flex:1;background:var(--bg-secondary);border-radius:3px;height:5px">
            <div style="width:${bar}%;height:100%;background:var(--accent-blue);border-radius:3px"></div>
          </div>
          <span style="width:40px;text-align:right;color:var(--text-muted)">${(s*100).toFixed(0)}%</span>
        </div>`;
    }).join('');

    let recHtml = '';
    if (volRecs) {
      const summary = volRecs.summary || '';
      const levAdj = volRecs.leverage_adjustment || '--';
      const slippage = volRecs.slippage_tolerance || '--';
      const hedgeAgg = volRecs.hedge_aggressiveness || '--';
      const execStyle = volRecs.execution_style || '--';
      recHtml = `
        <div style="margin-top:10px;padding:8px;background:var(--bg-secondary);border-radius:4px;font-size:11px">
          <div style="font-weight:600;margin-bottom:6px;color:var(--text-primary)">${summary}</div>
          <div class="metric-row" style="flex-wrap:wrap">
            <div class="metric-box" style="flex:1;min-width:100px"><div class="metric-label">Leverage</div><div class="metric-value" style="font-size:12px">${levAdj.replace(/_/g,' ')}</div></div>
            <div class="metric-box" style="flex:1;min-width:100px"><div class="metric-label">Slippage Tol</div><div class="metric-value" style="font-size:12px">${slippage.replace(/_/g,' ')}</div></div>
            <div class="metric-box" style="flex:1;min-width:100px"><div class="metric-label">Hedge Agg</div><div class="metric-value" style="font-size:12px">${hedgeAgg}</div></div>
          </div>
          <div style="margin-top:4px;color:var(--text-muted)">Exec style: ${execStyle.replace(/_/g,' ')}</div>
        </div>`;
    }

    panel.innerHTML = `
      <div style="display:flex;align-items:center;gap:16px;margin-bottom:12px">
        <div>
          <div style="font-size:11px;color:var(--text-muted)">Current Regime</div>
          <div class="metric-value ${regimeCls}" style="font-size:20px">${regimeLabel}</div>
        </div>
        <div>
          <div style="font-size:11px;color:var(--text-muted)">Confidence</div>
          <div class="metric-value" style="font-size:16px">${(conf*100).toFixed(0)}%</div>
        </div>
        <div style="font-size:10px;color:var(--text-muted);margin-left:auto">${formatTimestamp(volRegime.ts)}</div>
      </div>
      <div style="font-size:11px;color:var(--text-muted);margin-bottom:4px">Regime Scores</div>
      ${scoresHtml}
      ${recHtml}
    `;
  }

  function renderPortfolioRiskPanel(data) {
    const panel = document.getElementById('portfolio-risk-panel');
    if (!panel) return;
    if (!data) {
      panel.innerHTML = '<div class="empty-state"><div class="empty-state-text">No portfolio risk data</div></div>';
      return;
    }

    const warnings = (data.warnings || []).filter(w => !w.includes('No open positions'));
    const warningsHtml = warnings.map(w =>
      `<div style="font-size:11px;color:var(--accent-yellow);padding:2px 0">⚠ ${w}</div>`
    ).join('');

    const venueExp = data.venue_exposure || {};
    const totalExp = data.total_exposure || 0;
    const venueHtml = Object.entries(venueExp).map(([venue, exp]) => {
      const pct = totalExp > 0 ? ((exp / totalExp) * 100).toFixed(1) : '0';
      return `<tr><td style="padding:4px 8px">${venue}</td><td style="padding:4px 8px;text-align:right">$${formatNumber(exp,2)}</td><td style="padding:4px 8px;text-align:right">${pct}%</td></tr>`;
    }).join('');

    panel.innerHTML = `
      <div class="metric-row" style="flex-wrap:wrap">
        <div class="metric-box"><div class="metric-label">Total Exposure</div><div class="metric-value">$${formatNumber(data.total_exposure,2)}</div></div>
        <div class="metric-box"><div class="metric-label">Long</div><div class="metric-value green">$${formatNumber(data.long_exposure,2)}</div></div>
        <div class="metric-box"><div class="metric-label">Short</div><div class="metric-value red">$${formatNumber(data.short_exposure,2)}</div></div>
        <div class="metric-box"><div class="metric-label">Net</div><div class="metric-value ${classForValue(data.net_exposure)}">$${formatNumber(data.net_exposure,2)}</div></div>
        <div class="metric-box"><div class="metric-label">VaR 95%</div><div class="metric-value red">$${formatNumber(data.var_95,2)}</div></div>
        <div class="metric-box"><div class="metric-label">CVaR 95%</div><div class="metric-value red">$${formatNumber(data.cvar_95,2)}</div></div>
        <div class="metric-box"><div class="metric-label">Conc Risk</div><div class="metric-value ${(data.concentration_risk_venue||0)>0.6?'red':(data.concentration_risk_venue||0)>0.4?'yellow':'green'}">${formatNumber((data.concentration_risk_venue||0)*100,1)}%</div></div>
        <div class="metric-box"><div class="metric-label">Total P&amp;L</div><div class="metric-value ${classForValue(data.total_pnl)}">$${formatNumber(data.total_pnl,2)}</div></div>
      </div>
      ${warningsHtml}
      ${venueHtml ? `
        <div style="margin-top:10px;font-size:11px;color:var(--text-muted);margin-bottom:4px">Venue Exposure</div>
        <table style="width:100%;font-size:12px;border-collapse:collapse">
          <thead><tr style="border-bottom:1px solid var(--border-color)"><th style="padding:4px 8px;text-align:left">Venue</th><th style="padding:4px 8px;text-align:right">Notional</th><th style="padding:4px 8px;text-align:right">Share</th></tr></thead>
          <tbody>${venueHtml}</tbody>
        </table>` : ''}
      <div style="margin-top:6px;font-size:10px;color:var(--text-muted)">${formatTimestamp(data.ts)}</div>
    `;
  }

  function renderRedisHealth(data) {
    const panel = document.getElementById('redis-health-panel');
    if (!panel) return;
    if (!data) {
      panel.innerHTML = '<div style="font-size:12px;color:var(--text-muted)">Redis status unavailable</div>';
      return;
    }
    const statusCls = data.connected ? 'badge-green' : 'badge-red';
    const statusLabel = data.connected ? 'CONNECTED' : 'OFFLINE';
    const fallbackLabel = data.fallback_mode ? '<span class="badge badge-yellow" style="font-size:10px">FALLBACK</span>' : '';
    panel.innerHTML = `
      <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap">
        <span class="badge ${statusCls}">${statusLabel}</span>
        ${fallbackLabel}
        ${data.ping_latency_ms !== null && data.ping_latency_ms !== undefined ? `<span style="font-size:11px;color:var(--text-muted)">Ping: ${data.ping_latency_ms}ms</span>` : ''}
        ${data.memory_used_mb !== null && data.memory_used_mb !== undefined ? `<span style="font-size:11px;color:var(--text-muted)">Mem: ${data.memory_used_mb}MB</span>` : ''}
        ${data.key_count_estimate !== null && data.key_count_estimate !== undefined ? `<span style="font-size:11px;color:var(--text-muted)">Keys: ${data.key_count_estimate}</span>` : ''}
        ${data.last_error ? `<span style="font-size:10px;color:var(--accent-red)">${data.last_error.substring(0,60)}</span>` : ''}
      </div>
    `;
  }



  function renderMacroEvents(data, impact) {
    const panel = document.getElementById('macro-events-panel');
    if (!panel) return;
    const events = (data || {}).events || [];
    const summary = (impact || {}).summary || {};
    panel.innerHTML = `<div class="card-header"><span class="card-title">Macro/Trade Timeline</span><span class="badge ${data && data.degraded ? 'badge-yellow' : 'badge-green'}">${data && data.degraded ? 'DEGRADED' : 'LIVE'}</span></div><div class="metric-row"><div class="metric-box"><div class="metric-label">Events</div><div class="metric-value blue">${events.length}</div></div><div class="metric-box"><div class="metric-label">Risk Bias</div><div class="metric-value ${summary.risk_bias === 'risk_off' ? 'red' : 'green'}">${summary.risk_bias || '--'}</div></div><div class="metric-box"><div class="metric-label">Avg SPY Reaction</div><div class="metric-value">${((summary.avg_spy_reaction || 0) * 100).toFixed(2)}%</div></div></div><div class="table-scroll"><table><thead><tr><th>Time</th><th>Type</th><th>Title</th><th>Severity</th><th>Source</th></tr></thead><tbody>${events.slice(0,8).map(e => `<tr><td>${formatTimestamp(e.ts)}</td><td>${e.type}</td><td>${e.title}</td><td><span class="badge ${e.severity === 'high' ? 'badge-red' : e.severity === 'medium' ? 'badge-yellow' : 'badge-green'}">${e.severity}</span></td><td>${e.source}</td></tr>`).join('') || '<tr><td colspan="5">No macro events</td></tr>'}</tbody></table></div>`;
  }

  function renderInstitutionalLayer(data) {
    data = data || {};
    const sensitivity = document.getElementById('macro-sensitivity-panel');
    if (sensitivity) {
      const rows = ((data.sensitivity || {}).assets || []).slice(0, 10);
      sensitivity.innerHTML = `<div class="card-header"><span class="card-title">Tariff Beta / Macro Sensitivity</span></div><div class="table-scroll"><table><thead><tr><th>Ticker</th><th>Beta</th><th>Score</th><th>Reason</th></tr></thead><tbody>${rows.map(r => `<tr><td>${r.ticker}</td><td>${formatNumber(r.tariff_beta, 2)}</td><td>${formatNumber(r.macro_sensitivity_score, 1)}</td><td style="font-size:11px;color:var(--text-muted)">${(r.reasoning || []).slice(0,1).join('')}</td></tr>`).join('') || '<tr><td colspan="4">No sensitivity data</td></tr>'}</tbody></table></div>`;
    }
    const corr = document.getElementById('cross-asset-correlation-panel');
    if (corr) {
      const matrix = (data.correlations || {}).matrix || [];
      const contagion = data.contagion || {};
      corr.innerHTML = `<div class="card-header"><span class="card-title">Correlation / Contagion Map</span></div><div class="metric-row"><div class="metric-box"><div class="metric-label">Contagion</div><div class="metric-value ${contagion.regime === 'contagion' ? 'red' : 'yellow'}">${contagion.regime || '--'}</div></div><div class="metric-box"><div class="metric-label">Score</div><div class="metric-value blue">${formatNumber(contagion.contagion_score, 1)}</div></div></div><div class="table-scroll"><table><thead><tr><th>Asset</th><th>Tariff</th><th>SPY</th><th>BTC</th><th>Stable</th></tr></thead><tbody>${matrix.slice(0,8).map(r => `<tr><td>${r.asset}</td><td>${formatNumber(r.tariff_index,2)}</td><td>${formatNumber(r.SPY,2)}</td><td>${formatNumber(r.BTC,2)}</td><td>${formatNumber(r.stablecoin_stress,2)}</td></tr>`).join('') || '<tr><td colspan="5">No correlation data</td></tr>'}</tbody></table></div>`;
    }
    const watch = document.getElementById('watchlist-builder-panel');
    if (watch) {
      const rows = (data.watchlists || {}).watchlists || [];
      watch.innerHTML = `<div class="card-header"><span class="card-title">Watchlist Builder</span></div><div style="font-size:12px;color:var(--text-muted);margin-bottom:8px">In-memory fallback active when DB is unavailable.</div>${rows.slice(0,8).map(w => `<div style="padding:6px;border-bottom:1px solid var(--border-color)"><b>${w.name}</b> <span style="font-size:11px;color:var(--text-muted)">${(w.assets || []).join(', ')}</span></div>`).join('')}`;
    }
    const reports = document.getElementById('institutional-reports-panel');
    if (reports) {
      const reps = [data.dailyBrief, data.tariffReport].filter(Boolean);
      reports.innerHTML = `<div class="card-header"><span class="card-title">Institutional Reports</span></div>${reps.map(r => { const payload = escapeAttr(JSON.stringify(r)); return `<div style="padding:8px;border-bottom:1px solid var(--border-color)"><b>${r.title}</b><button class="btn btn-secondary" style="float:right" data-report='${payload}' onclick="navigator.clipboard && navigator.clipboard.writeText(this.dataset.report || '')">Copy</button><div style="font-size:11px;color:var(--text-muted)">${(r.sections || []).map(s => s.title).join(' · ')}</div></div>`; }).join('') || '<div class="empty-state-text">No reports</div>'}`;
    }
  }

  function renderScenarioResult(data) {
    const panel = document.getElementById('scenario-result-panel');
    if (!panel || !data) return;
    panel.innerHTML = `<div class="metric-row"><div class="metric-box"><div class="metric-label">PnL Impact</div><div class="metric-value ${Number(data.portfolio_pnl_impact || 0) >= 0 ? 'green' : 'red'}">${formatPrice(data.portfolio_pnl_impact)}</div></div><div class="metric-box"><div class="metric-label">Triggered</div><div class="metric-value blue">${(data.conditional_orders_triggered || []).length}</div></div></div><div style="font-size:12px;color:var(--text-muted)">Hedges: ${(data.hedge_recommendations || []).join('; ')}</div>`;
  }

  function renderRiskIntelligence(data) {
    data = data || {};
    const hedge = document.getElementById('cross-asset-hedge-panel');
    if (hedge) {
      const rows = (data.hedge || {}).recommendations || [];
      hedge.innerHTML = `<div class="card-header"><span class="card-title">Cross-Asset Hedge Recommendations</span></div>${rows.map(r => `<div style="padding:8px;border-bottom:1px solid var(--border-color)"><span class="badge badge-blue">${r.action}</span> <b>${r.asset}</b><div style="font-size:11px;color:var(--text-muted)">${r.reason}</div></div>`).join('') || '<div class="empty-state-text">No hedge recommendations</div>'}`;
    }
    const exp = document.getElementById('portfolio-explain-panel');
    if (exp) {
      const e = data.explain || {};
      exp.innerHTML = `<div class="card-header"><span class="card-title">Portfolio Explainability</span></div><div class="metric-row"><div class="metric-box"><div class="metric-label">Confidence</div><div class="metric-value blue">${(Number(e.confidence || 0) * 100).toFixed(0)}%</div></div><div class="metric-box"><div class="metric-label">Expected Upside</div><div class="metric-value green">${(Number(e.expected_upside || 0) * 100).toFixed(2)}%</div></div><div class="metric-box"><div class="metric-label">Expected Downside</div><div class="metric-value red">${(Number(e.expected_downside || 0) * 100).toFixed(2)}%</div></div></div><div style="font-size:12px;color:var(--text-muted)">Drivers: ${(e.drivers || []).join('; ')}</div><div style="font-size:12px;color:var(--text-muted)">Invalidation: ${(e.invalidation_conditions || []).join('; ')}</div>`;
    }
  }

  function renderAgentConsensusAndAttribution(consensus, attribution) {
    const cp = document.getElementById('agent-consensus-panel');
    if (cp) {
      const c = consensus || {};
      cp.innerHTML = `<div class="metric-row"><div class="metric-box"><div class="metric-label">Consensus</div><div class="metric-value ${c.confidence_weighted_consensus === 'bearish' ? 'red' : c.confidence_weighted_consensus === 'bullish' ? 'green' : 'yellow'}">${c.confidence_weighted_consensus || '--'}</div></div><div class="metric-box"><div class="metric-label">Risk Score</div><div class="metric-value blue">${formatNumber(c.risk_on_risk_off_score, 1)}</div></div><div class="metric-box"><div class="metric-label">Disagreement</div><div class="metric-value">${(Number(c.disagreement_level || 0) * 100).toFixed(0)}%</div></div></div><div style="font-size:12px;color:var(--text-muted)">Action: ${c.proposed_action || '--'} · Agents: ${(c.top_agreeing_agents || []).join(', ')}</div>`;
    }
    const ap = document.getElementById('signal-attribution-panel');
    if (ap) {
      const a = attribution || {};
      ap.innerHTML = `<div class="metric-row"><div class="metric-box"><div class="metric-label">Hit Rate</div><div class="metric-value green">${(Number(a.hit_rate || 0) * 100).toFixed(0)}%</div></div><div class="metric-box"><div class="metric-label">Signals</div><div class="metric-value blue">${a.signal_count || 0}</div></div><div class="metric-box"><div class="metric-label">PnL Impact</div><div class="metric-value ${Number(a.pnl_impact || 0) >= 0 ? 'green' : 'red'}">${formatPrice(a.pnl_impact)}</div></div></div>`;
    }
  }

  function escapeAttr(v) {
    return String(v || '').replace(/&/g, '&amp;').replace(/'/g, '&#39;').replace(/"/g, '&quot;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  }

  function pctBadge(v) {
    const n = Number(v || 0);
    const cls = n >= 0 ? 'badge-green' : 'badge-red';
    return `<span class="badge ${cls}">${(n * 100).toFixed(2)}%</span>`;
  }


  function renderStrategyPerformance(data) {
    data = data || {};
    const panel = document.getElementById('strategy-performance-panel');
    if (!panel) return;
    const rows = Object.values((data || {}).strategies || {});
    panel.innerHTML = `<div class="card-header"><span class="card-title">Strategy Comparison</span></div><div class="metric-row">${rows.slice(0,4).map(r => `<div class="metric-box"><div class="metric-label">${r.strategy_id}</div><div class="metric-value ${Number(r.total_pnl || 0) >= 0 ? 'green' : 'red'}">${formatPrice(r.total_pnl || 0)}</div><div style="font-size:11px;color:var(--text-muted)">Sharpe ${formatNumber(r.sharpe, 2)} · DD ${(Number(r.max_drawdown || 0) * 100).toFixed(1)}% · Win ${(Number(r.win_rate || 0) * 100).toFixed(0)}%</div></div>`).join('')}</div><div class="table-scroll"><table><thead><tr><th>Strategy</th><th>PnL</th><th>Sharpe</th><th>Max DD</th><th>Win</th><th>Trades</th><th>Avg Slip</th></tr></thead><tbody>${rows.map(r => `<tr><td>${r.strategy_id}</td><td>${formatPrice(r.total_pnl)}</td><td>${formatNumber(r.sharpe, 2)}</td><td>${(Number(r.max_drawdown || 0) * 100).toFixed(1)}%</td><td>${(Number(r.win_rate || 0) * 100).toFixed(0)}%</td><td>${r.trade_count}</td><td>${formatNumber(r.avg_slippage_bps, 1)} bps</td></tr>`).join('') || '<tr><td colspan="7">No strategy data</td></tr>'}</tbody></table></div><div style="font-size:11px;color:var(--text-muted);margin-top:6px">Best: ${(data.summary || {}).best_strategy || '--'} · Worst: ${(data.summary || {}).worst_strategy || '--'} · ${data.capital_allocation_feedback || ''}</div>`;
  }

  function renderExecutionEnhancements(data) {
    data = data || {};
    const preview = document.getElementById('allocation-preview-panel');
    if (preview) {
      const p = data.preview || {};
      preview.innerHTML = `<div class="card-header"><span class="card-title">Pre-Trade Sizing Preview</span></div><div class="metric-row"><div class="metric-box"><div class="metric-label">Target Allocation</div><div class="metric-value blue">${(Number(p.target_allocation || 0) * 100).toFixed(1)}%</div></div><div class="metric-box"><div class="metric-label">Current Allocation</div><div class="metric-value">${(Number(p.current_allocation || 0) * 100).toFixed(1)}%</div></div><div class="metric-box"><div class="metric-label">Allowed Size</div><div class="metric-value green">${formatNumber(p.allowed_size, 4)}</div></div></div>${(p.warnings || []).map(w => `<div class="badge badge-yellow" style="margin:2px">${w}</div>`).join('')}<div style="font-size:12px;color:var(--text-muted);margin-top:6px">${(p.reasoning || []).join('; ') || 'No preview yet'}</div>`;
    }
    const adv = document.getElementById('advanced-orders-panel');
    if (adv) {
      const cond = (data.conditional || {}).orders || [];
      const smart = (data.smart || {}).orders || [];
      adv.innerHTML = `<div class="card-header"><span class="card-title">Advanced Paper Orders</span></div><div style="font-size:12px;color:var(--text-muted);margin-bottom:8px">Stop loss, take profit, trailing stop, bracket, TWAP and VWAP are paper-mode/proposal-safe.</div><b>Conditional Orders</b><div class="table-scroll"><table><thead><tr><th>ID</th><th>Market</th><th>Type</th><th>Status</th><th>Trigger</th><th>Parent</th></tr></thead><tbody>${cond.slice(0,5).map(o => `<tr><td>${String(o.id || '').slice(0,8)}</td><td>${o.market}</td><td>${o.order_type}</td><td>${o.status}</td><td>${formatNumber(o.current_trigger_level || o.trigger_price, 2)}</td><td>${o.parent_id ? String(o.parent_id).slice(0,8) : '--'}</td></tr>`).join('') || '<tr><td colspan="6">No active conditional orders</td></tr>'}</tbody></table></div><b>Smart Orders</b><div class="table-scroll"><table><thead><tr><th>ID</th><th>Mode</th><th>Market</th><th>Progress</th><th>Est Slip</th><th>Status</th></tr></thead><tbody>${smart.slice(0,5).map(o => `<tr><td>${String(o.exec_id || '').slice(0,8)}</td><td>${o.mode || o.execution_style}</td><td>${o.market}</td><td>${o.completed_slices || 0}/${o.n_slices || 0}</td><td>${formatNumber(o.estimated_slippage_bps, 1)} bps</td><td>${o.status}</td></tr>`).join('') || '<tr><td colspan="6">No smart orders</td></tr>'}</tbody></table></div>`;
    }
  }

  function renderReplaySimulation(data) {
    const panel = document.getElementById('replay-sim-panel');
    if (!panel || !data) return;
    const timeline = data.simulated_timeline || [];
    panel.innerHTML = `<div class="metric-row"><div class="metric-box"><div class="metric-label">Final Value</div><div class="metric-value green">${formatPrice(data.final_portfolio_value)}</div></div><div class="metric-box"><div class="metric-label">Max Drawdown</div><div class="metric-value red">${(Number(data.max_drawdown || 0) * 100).toFixed(1)}%</div></div></div><div class="table-scroll"><table><thead><tr><th>Step</th><th>Value</th><th>Actions</th><th>Decision</th></tr></thead><tbody>${timeline.slice(-8).map(t => `<tr><td>${t.step}</td><td>${formatPrice(t.portfolio_value)}</td><td>${(t.proposed_actions || []).join(', ')}</td><td>${t.decision_log}</td></tr>`).join('')}</tbody></table></div>`;
  }

  function renderAgentMemory(perf, hist) {
    const p = document.getElementById('agent-performance-panel');
    if (p) {
      const rows = (perf || {}).agents || [];
      p.innerHTML = `<div class="metric-row">${rows.map(r => `<div class="metric-box"><div class="metric-label">${r.agent}</div><div class="metric-value blue">${(Number(r.hit_rate || 0) * 100).toFixed(0)}%</div><div style="font-size:11px;color:var(--text-muted)">${r.signal_count} signals · conf ${(Number(r.average_confidence || 0) * 100).toFixed(0)}%</div></div>`).join('') || '<div class="empty-state-text">No memory records yet</div>'}</div>`;
    }
    const h = document.getElementById('agent-history-panel');
    if (h) {
      const rows = (hist || {}).history || [];
      h.innerHTML = `<div class="table-scroll"><table><thead><tr><th>Agent</th><th>Ticker</th><th>Signal</th><th>Conf</th><th>Outcome</th></tr></thead><tbody>${rows.slice(0,25).map(r => `<tr><td>${r.agent}</td><td>${r.ticker || '--'}</td><td>${r.signal}</td><td>${(Number(r.confidence || 0) * 100).toFixed(0)}%</td><td>${formatNumber(r.realized_outcome, 4)}</td></tr>`).join('') || '<tr><td colspan="5">No signal history</td></tr>'}</tbody></table></div>`;
    }
  }

  function renderEquitiesTab(data) {
    data = data || {};
    const overview = data.overview || {};
    const cards = document.getElementById('equity-overview-cards');
    if (cards) {
      const rows = overview.market_overview || [];
      cards.innerHTML = rows.map(r => `<div class="metric-box"><div class="metric-label">${r.ticker}</div><div class="metric-value ${Number(r.daily_return || 0) >= 0 ? 'green' : 'red'}">${formatPrice(r.price)}</div><div style="font-size:11px;color:var(--text-muted)">1D ${(Number(r.daily_return || 0) * 100).toFixed(2)}% · Vol ${(Number(r.realized_volatility || 0) * 100).toFixed(1)}%</div></div>`).join('') || '<div class="empty-state-text">No equity overview data</div>';
    }
    const sectorBody = document.getElementById('equity-sector-tbody');
    if (sectorBody) {
      const rows = overview.sector_etfs || [];
      sectorBody.innerHTML = rows.map(r => `<tr><td>${r.ticker}</td><td>${r.sector || '--'}</td><td>${pctBadge(r.return_5d)}</td><td>${(Number(r.realized_volatility || 0) * 100).toFixed(1)}%</td><td>${pctBadge(r.relative_strength_vs_spy)}</td></tr>`).join('') || '<tr><td colspan="5" class="empty-state-text">No sector data</td></tr>';
    }
    const watchBody = document.getElementById('equity-watchlist-tbody');
    if (watchBody) {
      const rows = overview.tariff_watchlist || [];
      watchBody.innerHTML = rows.map(r => `<tr><td>${r.ticker}</td><td>${r.sector || '--'}</td><td>${formatPrice(r.price)}</td><td>${pctBadge(r.return_1m)}</td><td>${formatNumber(r.volume_vs_avg, 2)}x</td></tr>`).join('') || '<tr><td colspan="5" class="empty-state-text">No watchlist data</td></tr>';
    }
    const provider = document.getElementById('equity-provider-badge');
    if (provider) {
      const degraded = overview.status !== 'ok';
      provider.className = `freshness-badge ${degraded ? 'stale' : 'fresh'}`;
      provider.innerHTML = `<span class="freshness-dot"></span> ${degraded ? 'DEGRADED FALLBACK' : 'FRESH'}`;
    }
    if (data.history && window._equityChart && typeof Charts !== 'undefined') {
      const hist = data.history.history || [];
      Charts.updateChart(window._equityChart, { labels: hist.map(x => formatTimestamp(x.ts).slice(0, 10)), datasets: [{ label: `${data.history.ticker || 'SPY'} Close`, data: hist.map(x => x.close) }] });
    }
    const tariffPanel = document.getElementById('equity-tariff-panel');
    if (tariffPanel) {
      const scores = (data.tariff || {}).scores || [];
      tariffPanel.innerHTML = `<div class="card-header"><span class="card-title">Equity Tariff Exposure</span></div>${((data.tariff || {}).warnings || []).map(w => `<div class="badge badge-yellow" style="margin:2px">${w}</div>`).join('')}<div class="table-scroll"><table><thead><tr><th>Ticker</th><th>Score</th><th>Severity</th><th>Reasoning</th></tr></thead><tbody>${scores.slice(0, 12).map(s => `<tr><td>${s.ticker}</td><td>${formatNumber(s.score, 1)}</td><td><span class="badge ${s.severity === 'high' ? 'badge-red' : s.severity === 'medium' ? 'badge-yellow' : 'badge-green'}">${s.severity}</span></td><td style="font-size:11px;color:var(--text-muted)">${(s.reasoning || []).slice(0,2).join('; ')}</td></tr>`).join('') || '<tr><td colspan="4">No exposure scores</td></tr>'}</tbody></table></div>`;
    }
    const agentPanel = document.getElementById('equity-agent-panel');
    if (agentPanel) {
      const sigs = (data.risk || {}).signals || [];
      agentPanel.innerHTML = `<div class="card-header"><span class="card-title">Equity Risk Agent Signals</span></div>${sigs.slice(0, 10).map(s => `<div style="padding:8px;border-bottom:1px solid var(--border-color)"><span class="badge badge-blue">${s.signal}</span> <b>${s.ticker}</b> <span style="color:var(--text-muted);font-size:12px">${s.reason}</span></div>`).join('') || '<div class="empty-state-text">No active equity signals</div>'}`;
    }
    const cross = document.getElementById('equity-cross-asset-panel');
    if (cross) {
      const c = data.cross || {};
      cross.innerHTML = `<div class="card-header"><span class="card-title">Cross-Asset Risk On/Off</span></div><div class="metric-row"><div class="metric-box"><div class="metric-label">Regime</div><div class="metric-value ${c.regime === 'risk_off' ? 'red' : 'green'}">${c.regime || '--'}</div></div><div class="metric-box"><div class="metric-label">Risk-On Score</div><div class="metric-value blue">${formatNumber(c.risk_on_off_score, 1)}</div></div></div><div style="font-size:12px;color:var(--text-muted)">Equity vol ${(Number(c.equity_volatility || 0) * 100).toFixed(1)}% vs crypto proxy ${(Number(c.crypto_volatility_proxy || 0) * 100).toFixed(1)}%; tariff index ${formatNumber(c.tariff_index, 1)}</div>`;
    }
    const dq = document.getElementById('data-quality-panel');
    if (dq) {
      const sources = (data.quality || {}).sources || [];
      dq.innerHTML = `<div class="card-header"><span class="card-title">Data Quality Dashboard</span></div><div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:8px">${sources.map(s => `<div class="metric-box"><div class="metric-label">${s.name}</div><div><span class="badge ${s.status === 'ok' ? 'badge-green' : 'badge-yellow'}">${s.status}</span></div><div style="font-size:11px;color:var(--text-muted)">confidence ${(Number(s.confidence_score || 0) * 100).toFixed(0)}% · fallback ${s.fallback_source || '--'}</div></div>`).join('')}</div>`;
    }
  }



  function renderGeopoliticsTab(data) {
    data = data || {};
    const idx = data.index || {};
    const components = [
      ['Sanctions', idx.sanctions_score], ['Conflict', idx.conflict_score], ['Shipping', idx.shipping_score], ['Energy', idx.energy_score], ['Cyber/Policy', idx.cyber_policy_score], ['Tariff', idx.tariff_score], ['Market Stress', idx.market_stress_score],
    ];
    const cards = document.getElementById('geo-risk-cards');
    if (cards) {
      const regimeCls = idx.regime === 'crisis' || idx.regime === 'high_risk' ? 'red' : idx.regime === 'elevated' ? 'yellow' : 'green';
      cards.innerHTML = `<div class="metric-box"><div class="metric-label">Geo Risk Index</div><div class="metric-value ${regimeCls}">${formatNumber(idx.overall_score,1)}</div></div><div class="metric-box"><div class="metric-label">Regime</div><div class="metric-value ${regimeCls}">${idx.regime || '--'}</div></div><div class="metric-box"><div class="metric-label">Confidence</div><div class="metric-value blue">${(Number(idx.confidence || 0) * 100).toFixed(0)}%</div></div><div class="metric-box"><div class="metric-label">Data Quality</div><div><span class="badge ${(idx.data_quality === 'ok' || idx.data_quality === 'healthy') ? 'badge-green' : 'badge-yellow'}">${idx.data_quality || 'degraded'}</span></div></div>`;
    }
    const comp = document.getElementById('geo-component-panel');
    if (comp) comp.innerHTML = `<div class="table-scroll"><table><thead><tr><th>Component</th><th>Score</th></tr></thead><tbody>${components.map(c => `<tr><td>${c[0]}</td><td>${formatNumber(c[1],1)}</td></tr>`).join('')}</tbody></table></div>`;
    if (window._geoRiskChart && typeof Charts !== 'undefined') Charts.updateChart(window._geoRiskChart, { labels: components.map(c => c[0]), datasets: [{ data: components.map(c => Number(c[1] || 0)) }] });
    const regional = document.getElementById('geo-regional-panel');
    if (regional) {
      const rows = Object.entries(idx.regional_breakdown || {});
      regional.innerHTML = `<div class="card-header"><span class="card-title">Regional Risk Table</span></div><div class="table-scroll"><table><thead><tr><th>Region</th><th>Risk</th></tr></thead><tbody>${rows.map(([k,v]) => `<tr><td>${k}</td><td>${formatNumber(v,1)}</td></tr>`).join('') || '<tr><td colspan="2">No regional data</td></tr>'}</tbody></table></div>`;
    }
    const events = document.getElementById('geo-events-panel');
    if (events) {
      const rows = (data.events || {}).events || [];
      events.innerHTML = `<div class="card-header"><span class="card-title">Geopolitical Events Feed</span></div><div class="table-scroll"><table><thead><tr><th>Type</th><th>Title</th><th>Region</th><th>Severity</th></tr></thead><tbody>${rows.slice(0,10).map(e => `<tr><td>${e.event_type}</td><td>${e.title}</td><td>${e.region}</td><td><span class="badge ${e.severity === 'critical' || e.severity === 'crisis' || e.severity === 'high' ? 'badge-red' : 'badge-yellow'}">${e.severity}</span></td></tr>`).join('') || '<tr><td colspan="4">No events</td></tr>'}</tbody></table></div>`;
    }
    const sanctions = document.getElementById('geo-sanctions-panel');
    if (sanctions) {
      const s = data.sanctions || {}; const programs = s.programs || [];
      sanctions.innerHTML = `<div class="card-header"><span class="card-title">Sanctions Monitor</span></div><div class="metric-row"><div class="metric-box"><div class="metric-label">Score</div><div class="metric-value red">${formatNumber(s.sanctions_score,1)}</div></div><div class="metric-box"><div class="metric-label">Quality</div><span class="badge ${s.data_quality === 'ok' ? 'badge-green' : 'badge-yellow'}">${s.data_quality || 'degraded'}</span></div></div>${programs.slice(0,5).map(p => `<div style="padding:6px;border-bottom:1px solid var(--border-color)"><b>${p.program}</b> <span style="font-size:11px;color:var(--text-muted)">${(p.affected_assets || []).join(', ')}</span></div>`).join('')}`;
    }
    const conflict = document.getElementById('geo-conflict-panel');
    if (conflict) {
      const c = data.conflicts || {}; const rows = c.hotspots || [];
      conflict.innerHTML = `<div class="card-header"><span class="card-title">Conflict / Escalation Monitor</span></div><div class="table-scroll"><table><thead><tr><th>Hotspot</th><th>Score</th><th>Assets</th></tr></thead><tbody>${rows.slice(0,6).map(h => `<tr><td>${h.region}</td><td>${formatNumber(h.risk_score,1)}</td><td>${(h.assets || []).slice(0,4).join(', ')}</td></tr>`).join('') || '<tr><td colspan="3">No hotspots</td></tr>'}</tbody></table></div>`;
    }
    const shipping = document.getElementById('geo-shipping-panel');
    if (shipping) {
      const rows = (data.chokepoints || {}).chokepoints || [];
      shipping.innerHTML = `<div class="card-header"><span class="card-title">Shipping / Chokepoint Risk</span></div><div class="table-scroll"><table><thead><tr><th>Chokepoint</th><th>Region</th><th>Score</th></tr></thead><tbody>${rows.map(c => `<tr><td>${c.name}</td><td>${c.region}</td><td>${formatNumber(c.risk_score,1)}</td></tr>`).join('') || '<tr><td colspan="3">No chokepoint data</td></tr>'}</tbody></table></div>`;
    }
    const energy = document.getElementById('geo-energy-panel');
    if (energy) {
      const e = data.energy || {};
      energy.innerHTML = `<div class="card-header"><span class="card-title">Energy / Commodity Shock</span></div><div class="metric-row"><div class="metric-box"><div class="metric-label">Oil</div><div class="metric-value red">${formatNumber(e.oil_shock_score,1)}</div></div><div class="metric-box"><div class="metric-label">Gas</div><div class="metric-value yellow">${formatNumber(e.natural_gas_shock_score,1)}</div></div><div class="metric-box"><div class="metric-label">Food/Fertilizer</div><div class="metric-value">${formatNumber(e.fertilizer_food_shock,1)}</div></div></div><div style="font-size:12px;color:var(--text-muted)">Assets: ${(e.affected_assets || []).slice(0,12).join(', ')}</div>`;
    }
    const impact = document.getElementById('geo-impact-panel');
    if (impact) {
      const rows = (data.impact || data.marketImpact || {}).impacts || [];
      impact.innerHTML = `<div class="card-header"><span class="card-title">Market Impact Table</span></div><div class="table-scroll"><table><thead><tr><th>Asset</th><th>Class</th><th>Impact</th><th>Direction</th><th>Action</th></tr></thead><tbody>${rows.slice(0,18).map(r => `<tr><td>${r.asset}</td><td>${r.asset_class}</td><td>${formatNumber(r.impact_score,1)}</td><td>${r.direction}</td><td>${r.suggested_risk_action}</td></tr>`).join('') || '<tr><td colspan="5">No impact data</td></tr>'}</tbody></table></div>`;
    }
    renderGeoScenarioResult(data.scenarioResult);
    const prot = document.getElementById('geo-protection-panel');
    if (prot) {
      const p = data.protection || {};
      prot.innerHTML = `<div class="card-header"><span class="card-title">Portfolio Protection Protocol</span></div><div class="metric-row"><div class="metric-box"><div class="metric-label">Mode</div><div class="metric-value ${p.protection_mode === 'CRISIS' || p.protection_mode === 'DEFENSIVE' ? 'red' : 'green'}">${p.protection_mode || '--'}</div></div><div class="metric-box"><div class="metric-label">Auto Trade</div><div class="metric-value green">${p.auto_trade === false ? 'NO' : '--'}</div></div></div>${(p.recommended_actions || []).map(a => `<div style="font-size:12px;color:var(--text-muted);padding:2px 0">- ${a}</div>`).join('')}`;
    }
    const agent = document.getElementById('geo-agent-panel');
    if (agent) {
      const sigs = (data.agentSignals || {}).signals || [];
      agent.innerHTML = `<div class="card-header"><span class="card-title">Geopolitical Agent Signals</span></div>${sigs.slice(0,8).map(s => `<div style="padding:8px;border-bottom:1px solid var(--border-color)"><span class="badge badge-blue">${s.signal}</span> <b>${s.agent}</b><div style="font-size:11px;color:var(--text-muted)">${s.reason}</div></div>`).join('') || '<div class="empty-state-text">No geopolitical signals</div>'}`;
    }
    const report = document.getElementById('geo-report-panel');
    if (report) {
      const r = data.dailyBrief || {};
      report.innerHTML = `<div class="card-header"><span class="card-title">Daily Geopolitical Risk Brief</span></div><b>${r.headline || '--'}</b><div style="font-size:12px;color:var(--text-muted)">Regime: ${r.risk_regime || '--'} · Quality: ${r.data_quality || 'degraded'}</div>${(r.limitations || []).map(x => `<div style="font-size:11px;color:var(--text-muted)">• ${x}</div>`).join('')}`;
    }
  }

  function renderGeoScenarioResult(data) {
    const panel = document.getElementById('geo-scenario-result');
    if (!panel || !data) return;
    panel.innerHTML = `<div class="metric-row"><div class="metric-box"><div class="metric-label">PnL Impact</div><div class="metric-value red">${formatPrice(data.portfolio_pnl_impact)}</div></div><div class="metric-box"><div class="metric-label">Protection</div><div class="metric-value blue">${data.protection_mode || '--'}</div></div></div><div style="font-size:12px;color:var(--text-muted)">Posture: ${data.suggested_risk_posture || '--'} · Hedges: ${(data.hedge_suggestions || []).join('; ')}</div>`;
  }


  function escapeHtml(value) {
    return String(value ?? '').replace(/[&<>'"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;' }[c]));
  }
  const safeMoney = value => Number.isFinite(Number(value)) ? `${Number(value) < 0 ? '-' : ''}$${Math.abs(Number(value)).toLocaleString(undefined, { maximumFractionDigits: 2 })}` : '--';
  const safeValue = value => value === null || value === undefined || value === '' ? '--' : escapeHtml(value);
  const stat = (label, value) => `<div class="alignment-stat"><div class="alignment-label">${escapeHtml(label)}</div><div class="alignment-value">${value}</div></div>`;

  function renderBacktestError(message) {
    const panel = document.getElementById('backtest-result-panel');
    if (panel) panel.innerHTML = `<div class="alignment-note alignment-danger"><strong>Backtest failed:</strong> ${escapeHtml(message)}</div>`;
  }

  function renderBacktestCoverage(data) {
    const panel = document.getElementById('backtest-coverage-panel'); if (!panel) return;
    if (!data) { panel.innerHTML = '<div class="empty-state-text">Historical coverage unavailable.</div>'; return; }
    const coverage = data.coverage || data;
    const names = ['market_ticks','funding_ticks','index_history','stablecoin_ticks','regime_snapshots','events','orders','fills'];
    const rows = names.map(name => { const value = coverage[name] || {}; return `<tr><td>${escapeHtml(name)}</td><td>${Number(value.count || 0).toLocaleString()}</td><td>${safeValue(value.earliest)}</td><td>${safeValue(value.latest)}</td></tr>`; }).join('');
    const total = names.reduce((sum, name) => sum + Number((coverage[name] || {}).count || 0), 0);
    panel.innerHTML = `${total ? '' : '<div class="alignment-note">No persisted history available.</div>'}<div class="table-scroll"><table class="data-coverage-table"><thead><tr><th>Dataset</th><th>Count</th><th>Earliest</th><th>Latest</th></tr></thead><tbody>${rows}</tbody></table></div>`;
  }

  function renderBacktestHistory(data, inspect) {
    const panel = document.getElementById('backtest-history-panel'); if (!panel) return;
    if (!data) { panel.innerHTML = '<div class="empty-state-text">Backtest history unavailable.</div>'; return; }
    const rows = (data.history || data.runs || (Array.isArray(data) ? data : [])).slice(0, 15);
    if (!rows.length) { panel.innerHTML = '<div class="empty-state-text">No durable backtest runs yet.</div>'; return; }
    panel.innerHTML = `<div class="table-scroll"><table class="run-history-table"><thead><tr><th>Timestamp</th><th>Mode</th><th>Strategy</th><th>Venue</th><th>Market</th><th>Status</th><th>Return</th><th>Sharpe</th><th>Max Drawdown</th></tr></thead><tbody>${rows.map(r => { const m=r.metrics||r.result||r, c=r.config||{}; const id=r.id||r.run_id||''; return `<tr ${id?'class="run-history-row"':''} data-run-id="${escapeHtml(id)}"><td>${safeValue(r.created_at||r.ts||r.timestamp)}</td><td>${safeValue(r.mode||c.mode)}</td><td>${safeValue(r.strategy||c.strategy)}</td><td>${safeValue(r.venue||c.venue)}</td><td>${safeValue(r.market||c.market)}</td><td>${safeValue(r.status||'completed')}</td><td>${Number.isFinite(Number(m.total_return_pct))?formatNumber(m.total_return_pct,2)+'%':'--'}</td><td>${Number.isFinite(Number(m.sharpe_ratio??m.sharpe))?formatNumber(m.sharpe_ratio??m.sharpe,2):'--'}</td><td>${Number.isFinite(Number(m.max_drawdown_pct??m.max_drawdown))?formatNumber(m.max_drawdown_pct??m.max_drawdown,2)+'%':'--'}</td></tr>`; }).join('')}</tbody></table></div>`;
    panel.querySelectorAll('[data-run-id]').forEach(row => row.addEventListener('click', () => row.dataset.runId && inspect(row.dataset.runId)));
  }

  function renderBacktestPanel(data) {
    const panel=document.getElementById('backtest-result-panel'); if(!panel)return;
    if(!data||data.available===false){panel.innerHTML='<div class="empty-state"><div class="empty-state-text">Run a backtest to see results</div></div>';return;}
    const metrics=data.metrics?{...data.metrics,...data}:data, cfg=metrics.config||data.config||{}, historical=(metrics.mode||cfg.mode)==='historical';
    const fields=[['Mode',historical?'Historical':'Synthetic'],['Total Return',Number.isFinite(Number(metrics.total_return_pct))?`${formatNumber(metrics.total_return_pct,2)}%`:'--'],['Final Capital',safeMoney(metrics.final_capital)],['Sharpe',safeValue(metrics.sharpe_ratio??metrics.sharpe)],['Max Drawdown',Number.isFinite(Number(metrics.max_drawdown_pct))?`${formatNumber(metrics.max_drawdown_pct,2)}%`:'--'],['Win Rate',Number.isFinite(Number(metrics.win_rate))?`${formatNumber(Number(metrics.win_rate)*100,1)}%`:'--'],['Trades',safeValue(metrics.trade_count)],['Fills',safeValue(metrics.fill_count)],['Average Slippage',Number.isFinite(Number(metrics.avg_slippage_bps))?`${formatNumber(metrics.avg_slippage_bps,2)} bps`:'--'],['VaR',safeValue(metrics.var_95)],['CVaR',safeValue(metrics.cvar_95)]];
    if(historical) fields.push(['Run ID',safeValue(data.run_id||data.id||metrics.run_id)],['Persistence Status',safeValue(data.persistence_status||metrics.persistence_status)],['Fees Paid',safeMoney(metrics.fees_paid)],['Funding P&L',safeMoney(metrics.funding_pnl)],['Slippage Cost',safeMoney(metrics.slippage_cost)],['Realized P&L',safeMoney(metrics.realized_pnl)],['Unrealized P&L',safeMoney(metrics.unrealized_pnl)],['Venue',safeValue(cfg.venue||metrics.venue)],['Market',safeValue(cfg.market||metrics.market)],['Symbol',safeValue(cfg.symbol||metrics.symbol)],['Start',safeValue(cfg.start_ts||metrics.start_ts)],['End',safeValue(cfg.end_ts||metrics.end_ts)],['Latency',Number.isFinite(Number(cfg.latency_ms))?`${cfg.latency_ms} ms`:'--'],['Fill Model',safeValue(cfg.fill_model)]);
    const guard=metrics.look_ahead_guard||{}, capital=metrics.capital_constraints||{}, warnings=metrics.warnings||[], manifest=metrics.data_manifest||{}, windows=metrics.walk_forward_windows||[];
    const detail=(title,value)=>`<details><summary>${escapeHtml(title)}</summary><pre>${escapeHtml(JSON.stringify(value,null,2))}</pre></details>`;
    panel.innerHTML=`<div class="research-warning"><span class="backtest-mode-badge ${historical?'historical-badge':''}">${historical?'HISTORICAL EVENT-TIME REPLAY':'SYNTHETIC RESEARCH'}</span></div><div class="alignment-grid">${fields.map(([l,v])=>stat(l,v)).join('')}</div>${historical?`<div class="alignment-note alignment-success"><strong>Look-ahead prevention:</strong> ${safeValue(guard.rule||guard.enabled||'enabled')}</div><div class="alignment-note"><strong>Capital constraints:</strong> ${safeValue(JSON.stringify(capital))}</div>`:''}${Object.keys(manifest).length?detail('Data Manifest',manifest):''}${windows.length?detail('Walk-Forward Windows',windows):''}${warnings.length?detail('Warnings / Assumptions',warnings):''}`;
  }

  function renderExecutionSafety(g) {
    const panel=document.getElementById('execution-safety-panel'); if(!panel)return;
    if(!g){panel.innerHTML='<div class="empty-state-text">Execution safety unavailable.</div>';return;}
    const values=[['Mode',safeValue(g.execution_mode||'paper')],['Live Gate',g.live_execution_enabled?'ENABLED':'DISABLED'],['Max Notional',safeMoney(g.max_order_notional)],['Max Slippage',g.max_order_slippage_bps==null?'--':`${formatNumber(g.max_order_slippage_bps,0)} bps`],['Supported Venues',safeValue((g.supported_execution_venues||[]).join(' · '))],['Supported Markets',safeValue((g.supported_execution_markets||[]).join(' · '))],['Order Types',safeValue((g.supported_order_types||[]).join(' · '))]];
    panel.innerHTML=`${!g.live_execution_enabled?'<div class="reconciliation-warning">LIVE GATE DISABLED</div>':''}<div class="execution-safety-grid">${values.map(([l,v])=>stat(l,v)).join('')}</div>`;
  }

  function renderLastOrderResult(result) {
    const panel=document.getElementById('last-order-result-panel'); if(!panel)return;
    const unknown=result&&(result.requires_reconciliation===true||result.status==='execution_state_unknown');
    const fields=['status','execution_mode','venue','market','side','size','fill_price','order_id','durable_order_id','request_id','client_order_id','idempotency_status','persistence_status'];
    panel.innerHTML=`${unknown?'<div class="reconciliation-warning">RECONCILIATION REQUIRED</div>':''}<div class="alignment-grid">${fields.map(k=>stat(k.replaceAll('_',' '),safeValue(result?.[k]))).join('')}</div>${result?.portfolio_metrics?`<details><summary>Portfolio Metrics</summary><pre>${escapeHtml(JSON.stringify(result.portfolio_metrics,null,2))}</pre></details>`:''}${result?.error?`<div class="alignment-note alignment-danger">${escapeHtml(result.error)}</div>`:''}`;
  }

  function renderAccounting(response) {
    const panel=document.getElementById('execution-accounting-panel'); if(!panel)return;
    if(!response){panel.innerHTML='<div class="empty-state-text">Position accounting unavailable.</div>';return;}
    const live=response.live_positions||[], positions=live.length?live:(response.db_positions||[]);
    const totals=positions.reduce((a,p)=>{a.r+=Number(p.realized_pnl||0);a.u+=Number(p.unrealized_pnl??p.pnl??0);a.f+=Number(p.fees||p.fees_paid||0);a.fu+=Number(p.funding||p.funding_pnl||0);a.s+=Number(p.slippage||p.slippage_cost||0);return a;},{r:0,u:0,f:0,fu:0,s:0});
    panel.innerHTML=`<div class="accounting-grid">${[['Realized P&L',totals.r],['Unrealized P&L',totals.u],['Fees',totals.f],['Funding',totals.fu],['Slippage',totals.s]].map(([l,v])=>stat(l,safeMoney(v))).join('')}</div><div class="table-scroll"><table><thead><tr><th>Venue</th><th>Market</th><th>Side</th><th>Size</th><th>Entry</th><th>Mark</th><th>Realized</th><th>Unrealized</th><th>Fees</th><th>Funding</th><th>Slippage</th></tr></thead><tbody>${positions.map(p=>`<tr><td>${safeValue(p.venue)}</td><td>${safeValue(p.market||p.symbol)}</td><td>${safeValue(p.side||(Number(p.size)>=0?'long':'short'))}</td><td>${safeValue(p.size)}</td><td>${safeMoney(p.entry_price||p.price)}</td><td>${safeMoney(p.mark_price)}</td><td>${safeMoney(p.realized_pnl)}</td><td>${safeMoney(p.unrealized_pnl??p.pnl)}</td><td>${safeMoney(p.fees||p.fees_paid)}</td><td>${safeMoney(p.funding||p.funding_pnl)}</td><td>${safeMoney(p.slippage||p.slippage_cost)}</td></tr>`).join('')||'<tr><td colspan="11">No open positions.</td></tr>'}</tbody></table></div>`;
  }

  const lifecycleTypes=new Set(['ORDER_INTENT_CREATED','ORDER_RISK_APPROVED','ORDER_SUBMITTED','ORDER_ACKNOWLEDGED','ORDER_OPEN','ORDER_PARTIALLY_FILLED','ORDER_FILLED','ORDER_REJECTED','ORDER_SUBMISSION_UNKNOWN','ORDER_CANCEL_PENDING','ORDER_CANCELLED']);
  function renderLifecycle(data) {
    const panel=document.getElementById('execution-lifecycle-panel');if(!panel)return;const events=(Array.isArray(data)?data:(data?.events||[])).filter(e=>lifecycleTypes.has(String(e.event_type).toUpperCase())).slice(0,20);
    panel.innerHTML=events.map(e=>{const type=String(e.event_type).toUpperCase(),p=e.payload||{},cls=type.includes('UNKNOWN')?'unknown':type.includes('REJECT')?'rejected':type.includes('FILLED')&&!type.includes('PARTIALLY')?'filled':type.includes('PARTIAL')||type.includes('OPEN')?'open':type.includes('CANCEL')?'cancelled':'progress';return `<div class="lifecycle-step ${cls}"><span>${safeValue(e.ts)}</span><strong>${escapeHtml(type)}</strong><span>${safeValue(e.source)}</span><span>${safeValue(p.message)}</span><small>Order ${safeValue(p.order_id||p.durable_order_id)} · Request ${safeValue(p.request_id)}</small></div>`;}).join('')||'<div class="empty-state-text">No order lifecycle events yet.</div>';
  }

  function renderPortfolioRiskPanel(data) {
    const panel=document.getElementById('portfolio-risk-panel');if(!panel)return;
    if(!data){panel.innerHTML='<div class="empty-state-text">Portfolio exposure analytics unavailable.</div>';return;}
    const fields=[['Gross Exposure',safeMoney(data.total_exposure)],['Long Exposure',safeMoney(data.long_exposure)],['Short Exposure',safeMoney(data.short_exposure)],['Net Exposure',safeMoney(data.net_exposure)],['Stablecoin Allocation',safeValue(data.stablecoin_allocation)],['Total P&L',safeMoney(data.total_pnl)],['VaR 95%',safeMoney(data.var_95)],['CVaR 95%',safeMoney(data.cvar_95)],['Venue Concentration',safeValue(data.concentration_risk_venue)],['Asset Concentration',safeValue(data.concentration_risk_asset)],['Liquidity-adjusted Risk',safeValue(data.liquidity_adjusted_risk)],['Position Count',safeValue(data.position_count)]];
    panel.innerHTML=`<div class="card-header"><span class="card-title">Portfolio Exposure Analytics</span></div><div class="alignment-grid">${fields.map(([l,v])=>stat(l,v)).join('')}</div>${(data.warnings||[]).map(w=>`<div class="alignment-note">${escapeHtml(w)}</div>`).join('')}`;
  }

  function renderRedisHealth(data) {
    const panel=document.getElementById('redis-health-panel');if(!panel)return;
    if(!data){panel.innerHTML='<div class="empty-state-text">Redis status unavailable.</div>';return;}
    const fields=[['Redis',data.connected?'CONNECTED':data.degraded?'DEGRADED':'DISCONNECTED'],['Mode',data.fallback_mode?'FALLBACK':'NORMAL'],['Ping',data.ping_latency_ms==null?'--':`${formatNumber(data.ping_latency_ms,2)} ms`],['Pub/Sub',safeValue(data.pubsub_status)],['Namespace',safeValue(data.key_namespace??data.key_prefix)],['Sync Pool',`${safeValue(data.sync_pool_in_use)} / ${safeValue(data.max_connections)}`],['Sync Created',safeValue(data.sync_pool_created)],['Available',safeValue(data.sync_pool_available)],['Async Created / In Use',`${safeValue(data.async_pool_created)} / ${safeValue(data.async_pool_in_use)}`],['Reconnects',safeValue(data.reconnect_count)],['Connection Failures',safeValue(data.connection_failures)],['Publish Failures',safeValue(data.publish_failures)],['Memory',data.memory_used_mb==null?'--':`${formatNumber(data.memory_used_mb,2)} MB`],['Keys',safeValue(data.key_count_estimate)],['Last Successful Ping',safeValue(data.last_successful_ping)]];
    panel.innerHTML=`<div class="telemetry-grid">${fields.map(([l,v])=>stat(l,v)).join('')}</div>${data.last_error?`<div class="alignment-note alignment-danger">${escapeHtml(data.last_error)}</div>`:''}`;
  }

  function renderPortfolioRiskBreakdown(contrib, exposures) {
    const panel=document.getElementById('portfolio-risk-breakdown-panel');if(!panel)return;const byVenue=exposures?.by_venue||{},byAsset=exposures?.by_asset||{},rows=contrib?.contributions||[];
    panel.innerHTML=`<div class="risk-breakdown-grid"><div>${stat('Venue Exposure',Object.entries(byVenue).map(([k,v])=>`${escapeHtml(k)} ${safeMoney(v)}`).join('<br>')||'--')}</div><div>${stat('Asset Exposure',Object.entries(byAsset).map(([k,v])=>`${escapeHtml(k)} ${safeMoney(v)}`).join('<br>')||'--')}</div></div><div class="table-scroll"><table><thead><tr><th>Market</th><th>Venue</th><th>Side</th><th>Notional</th><th>Risk Contribution</th><th>Risk Contribution %</th><th>Vol Estimate</th></tr></thead><tbody>${rows.map(c=>`<tr><td>${safeValue(c.market)}</td><td>${safeValue(c.venue)}</td><td>${safeValue(c.side)}</td><td>${safeMoney(c.notional)}</td><td>${safeValue(c.risk_contribution)}</td><td>${safeValue(c.risk_contribution_pct)}</td><td>${safeValue(c.vol_estimate)}</td></tr>`).join('')||'<tr><td colspan="7">No risk contributions available.</td></tr>'}</tbody></table></div>`;
  }

  function renderHeuristicPerformance(data) {
    const panel = document.getElementById('heuristic-performance-panel'); if (!panel) return;
    const rows = data.heuristics || data.performance || [];
    const pct = value => value === null || value === undefined ? 'N/A' : `${(Number(value) * 100).toFixed(1)}%`;
    const num = value => value === null || value === undefined ? 'N/A' : Number(value).toFixed(2);
    const table = `<div class="table-scroll"><table><thead><tr><th>Heuristic</th><th>Ver</th><th>Status</th><th>Accuracy</th><th>Precision</th><th>Recall</th><th>Hit Rate</th><th>Avg Return</th><th>Sharpe</th><th>Max DD</th><th>Samples</th></tr></thead><tbody>${rows.map(row => { const m=row.metrics||{}; const n=m.fired_count||0; const badge=n<10?'LOW SAMPLE':n<100?'MODERATE SAMPLE':'STRONG SAMPLE'; return `<tr class="heuristic-row"><td>${escapeHtml(row.id||row.name)}</td><td>v${row.version}</td><td>${escapeHtml(row.evaluation_status||'N/A')}</td><td>${pct(m.directional_accuracy)}</td><td>${pct(m.precision)}</td><td>${pct(m.recall)}</td><td>${pct(m.hit_rate)}</td><td>${pct(m.average_signed_return)}</td><td>${num(m.signal_return_sharpe)}</td><td>${pct(m.signal_return_max_drawdown)}</td><td><span class="sample-badge">${badge}</span> n=${n}<br>${m.evaluable_count||0} opportunities</td></tr>`; }).join('') || '<tr><td colspan="11">No persisted evaluations. Run historical validation manually.</td></tr>'}</tbody></table></div>`;
    const detail = rows.map(row => { const m=row.metrics||{}; const regimes=m.performance_by_regime||{}; const decay=m.performance_decay||{}; return `<details class="heuristic-detail"><summary>${escapeHtml(row.id||row.name)}:v${row.version} — ${escapeHtml(row.evaluation_status||'N/A')}</summary><div class="metric-row"><div class="metric-box"><div class="metric-label">Decision Opportunities</div><div class="metric-value">${m.opportunity_count||0}</div></div><div class="metric-box"><div class="metric-label">Evaluable Opportunities</div><div class="metric-value">${m.evaluable_count||0}</div></div><div class="metric-box"><div class="metric-label">Signals Fired</div><div class="metric-value">${m.fired_count||0}</div></div><div class="metric-box"><div class="metric-label">Brier Score</div><div class="metric-value">${num(m.brier_score)}</div><small>${m.brier_score==null?'Rule does not emit a calibrated probability.':`${m.calibration_sample_count} calibration samples`}</small></div></div><p><strong>Required Context:</strong> ${(row.required_context||[]).map(escapeHtml).join(', ')||'N/A'} · <strong>Missing:</strong> ${(row.missing_context||[]).map(escapeHtml).join(', ')||'none'}</p><h4>Outcome by Horizon</h4>${Object.entries(m.outcome_by_horizon||{}).map(([h,s])=>`${h}: n=${s.fired_count||0}, hit ${pct(s.hit_rate)}, avg signed ${pct(s.average_signed_return)}`).join('<br>')||'N/A'}<h4>Performance by Regime</h4>${Object.entries(regimes).map(([field,groups])=>`<strong>${escapeHtml(field)}</strong>: ${Object.entries(groups).map(([name,s])=>`${escapeHtml(name)} n=${s.fired_count||0}, hit ${pct(s.hit_rate)}`).join(' · ')||'N/A'}`).join('<br>')||'N/A'}<h4>Performance Decay</h4>${decay.available?`Recent 30d ${pct(decay.recent_30d?.hit_rate)} vs prior 30d ${pct(decay.prior_30d?.hit_rate)}`:'Insufficient history for decay analysis'}</details>`; }).join('');
    panel.innerHTML = table + detail;
  }
  function renderHeuristicPerformanceError(message) { const panel=document.getElementById('heuristic-performance-panel'); if(panel) panel.innerHTML=`<div class="research-warning error">${escapeHtml(message)}<br>No synthetic fallback was used.</div>`; }

  const auditTable = (headers, rows) => `<div class="table-scroll"><table><thead><tr>${headers.map(h=>`<th>${h}</th>`).join('')}</tr></thead><tbody>${rows.join('')||`<tr><td colspan="${headers.length}">No durable history available.</td></tr>`}</tbody></table></div>`;
  const auditValue = value => value === null || value === undefined || value === '' ? 'N/A' : escapeHtml(String(value));
  function renderIngestionRegistry(data) { const p=document.getElementById('ingestion-registry-panel'); if(!p)return; p.innerHTML=auditTable(['Source','Provider','Category','Cadence','Authoritative','Fallback Chain','Storage'],(data.sources||[]).map(s=>`<tr><td>${auditValue(s.source_id)}</td><td>${auditValue(s.provider)}</td><td>${auditValue(s.category)}</td><td>${auditValue(s.expected_cadence_seconds)}s</td><td>${s.authoritative?'Yes':'No'}</td><td>${auditValue((s.fallback_chain||[]).join(' → '))}</td><td>${auditValue(s.storage_target)}</td></tr>`)); }
  function renderIngestionStatus(data) { const p=document.getElementById('ingestion-status-panel'); if(!p)return; p.innerHTML=auditTable(['Source','Status','Freshness','Last Attempt','Last Success','Latency','Success Rate','Failure Streak','Received','Persisted','Fallback'],(data.sources||[]).map(s=>{const badge=s.status==='success'?'HEALTHY':s.status==='fallback'?'FALLBACK':s.status==='failure'?'FAILING':s.status?'DEGRADED':'NO HISTORY';return `<tr><td>${auditValue(s.source_id)}<br><small>${auditValue(s.provider)}</small></td><td><span class="source-status-badge ${badge.toLowerCase().replace(' ','-')}">${badge}</span></td><td>${s.freshness_age_seconds==null?'N/A':auditValue(s.freshness_age_seconds)+'s'}</td><td>${auditValue(s.last_attempt)}</td><td>${auditValue(s.last_success)}</td><td>${s.last_duration_ms==null?'N/A':auditValue(Number(s.last_duration_ms).toFixed(0))+'ms'}</td><td>${s.recent_success_rate==null?'N/A':(Number(s.recent_success_rate)*100).toFixed(1)+'%'}</td><td><span class="failure-streak-badge">${auditValue(s.failure_streak)}</span></td><td>${auditValue(s.records_received)}</td><td>${auditValue(s.records_persisted)}</td><td>${s.fallback_used?`<span class="fallback-badge">${auditValue(s.fallback_source_id||'sample')}</span>`:'None'}</td></tr>`;})); }
  function renderIngestionRuns(data) { const p=document.getElementById('ingestion-runs-panel');if(!p)return;p.innerHTML=auditTable(['Time','Source','Status','Duration','Received','Persisted','Fallback','Error'],(data.runs||[]).map(r=>`<tr><td>${auditValue(r.started_at)}</td><td>${auditValue(r.source_id)}</td><td>${auditValue(r.status)}</td><td>${r.duration_ms==null?'N/A':auditValue(Number(r.duration_ms).toFixed(0))+'ms'}</td><td>${auditValue(r.records_received)}</td><td>${auditValue(r.records_persisted)}</td><td>${r.fallback_used?auditValue(r.fallback_source_id||r.fallback_type):'None'}</td><td>${auditValue(r.error_message)}</td></tr>`)); }
  function renderDataProvenance(data) { const p=document.getElementById('provenance-results');if(!p)return;p.innerHTML=auditTable(['Source / Run','Artifact','Provider / Received / Persisted','Fallback','Lineage'],(data.provenance||[]).map(r=>`<tr><td>${auditValue(r.source_id)}<br><small>${auditValue(r.ingest_run_id)}</small></td><td>${auditValue(r.artifact_type)} #${auditValue(r.artifact_id)}</td><td>${auditValue(r.provider_timestamp)}<br>${auditValue(r.received_at)}<br>${auditValue(r.persisted_at)}</td><td>${r.fallback_used?auditValue(r.fallback_source_id||'sample'):'None'}</td><td><details><summary>JSON lineage</summary><pre>${auditValue(JSON.stringify(r.lineage||{},null,2))}</pre></details></td></tr>`)); }

  return {
    formatTimestamp,
    formatNumber,
    formatPrice,
    renderFreshnessBadge,
    renderDecisionDataPanel,
    renderIndexTab,
    renderMarketsTab,
    renderDivergenceTab,
    renderStablecoinsTab,
    renderStrategyTab,
    renderExecutionTab,
    renderRiskTab,
    renderMCResult,
    renderAgentsTab,
    renderFeedStatus,
    renderAllocationPanel,
    renderMLPanel,
    renderMLGovernance,
    renderBacktestPanel,
    renderBacktestError,
    renderBacktestCoverage,
    renderBacktestHistory,
    renderLastOrderResult,
    renderVolRegimePanel,
    renderPortfolioRiskPanel,
    renderRedisHealth,
    renderMacroEvents,
    renderInstitutionalLayer,
    renderScenarioResult,
    renderRiskIntelligence,
    renderAgentConsensusAndAttribution,

    renderGeopoliticsTab,
    renderGeoScenarioResult,
    renderEquitiesTab,
    renderStrategyPerformance,
    renderHeuristicPerformance,
    renderHeuristicPerformanceError,
    renderIngestionRegistry,
    renderIngestionStatus,
    renderIngestionRuns,
    renderDataProvenance,
    renderExecutionEnhancements,
    renderReplaySimulation,
    renderAgentMemory,
    addEventToTimeline,
    renderTimeline,
    updateConnectionStatus,
  };
})();
