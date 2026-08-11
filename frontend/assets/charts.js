const Charts = (() => {
  const gridColor = 'rgba(48, 54, 61, 0.6)';
  const tickColor = '#8b949e';
  const tooltipBg = '#1c2333';
  const tooltipBorder = '#30363d';

  const baseOptions = {
    responsive: true,
    maintainAspectRatio: false,
    animation: { duration: 300 },
    plugins: {
      legend: {
        labels: { color: tickColor, font: { size: 11 }, usePointStyle: true, pointStyle: 'circle' },
      },
      tooltip: {
        backgroundColor: tooltipBg,
        borderColor: tooltipBorder,
        borderWidth: 1,
        titleColor: '#e6edf3',
        bodyColor: '#8b949e',
        titleFont: { size: 12 },
        bodyFont: { size: 11, family: "'SF Mono', monospace" },
        padding: 10,
        cornerRadius: 6,
      },
    },
    scales: {
      x: {
        grid: { color: gridColor, drawBorder: false },
        ticks: { color: tickColor, font: { size: 10 }, maxRotation: 0 },
      },
      y: {
        grid: { color: gridColor, drawBorder: false },
        ticks: { color: tickColor, font: { size: 10 } },
      },
    },
  };

  function mergeOptions(custom) {
    return JSON.parse(JSON.stringify({
      ...baseOptions,
      ...custom,
      plugins: { ...baseOptions.plugins, ...(custom.plugins || {}) },
      scales: {
        x: { ...baseOptions.scales.x, ...((custom.scales && custom.scales.x) || {}) },
        y: { ...baseOptions.scales.y, ...((custom.scales && custom.scales.y) || {}) },
      },
    }));
  }

  function createIndexChart(canvasId) {
    const ctx = document.getElementById(canvasId);
    if (!ctx) return null;
    return new Chart(ctx, {
      type: 'line',
      data: {
        labels: [],
        datasets: [
          {
            label: 'Tariff Index',
            data: [],
            borderColor: '#58a6ff',
            backgroundColor: 'rgba(88, 166, 255, 0.1)',
            fill: true,
            tension: 0.3,
            pointRadius: 0,
            borderWidth: 2,
          },
          {
            label: 'Shock Score',
            data: [],
            borderColor: '#f85149',
            backgroundColor: 'rgba(248, 81, 73, 0.08)',
            fill: true,
            tension: 0.3,
            pointRadius: 0,
            borderWidth: 2,
            yAxisID: 'y1',
          },
        ],
      },
      options: mergeOptions({
        scales: {
          y: { position: 'left', title: { display: true, text: 'Index Level', color: tickColor } },
          y1: {
            position: 'right',
            grid: { drawOnChartArea: false, color: gridColor },
            ticks: { color: tickColor, font: { size: 10 } },
            title: { display: true, text: 'Shock Score', color: tickColor },
          },
        },
      }),
    });
  }

  function createFundingChart(canvasId) {
    const ctx = document.getElementById(canvasId);
    if (!ctx) return null;
    return new Chart(ctx, {
      type: 'bar',
      data: {
        labels: [],
        datasets: [{
          label: 'Funding Rate (bps)',
          data: [],
          backgroundColor: [],
          borderRadius: 3,
          barPercentage: 0.6,
        }],
      },
      options: mergeOptions({
        scales: {
          y: { title: { display: true, text: 'Rate (bps)', color: tickColor } },
        },
        plugins: { legend: { display: false } },
      }),
    });
  }

  function createDivergenceChart(canvasId) {
    const ctx = document.getElementById(canvasId);
    if (!ctx) return null;
    return new Chart(ctx, {
      type: 'bar',
      data: {
        labels: [],
        datasets: [{
          label: 'Spread (bps)',
          data: [],
          backgroundColor: [],
          borderRadius: 3,
          barPercentage: 0.5,
        }],
      },
      options: mergeOptions({
        indexAxis: 'y',
        scales: {
          x: { title: { display: true, text: 'Spread (bps)', color: tickColor } },
          y: { ticks: { color: tickColor, font: { size: 11 } } },
        },
        plugins: { legend: { display: false } },
      }),
    });
  }

  function createMCChart(canvasId) {
    const ctx = document.getElementById(canvasId);
    if (!ctx) return null;
    return new Chart(ctx, {
      type: 'bar',
      data: {
        labels: [],
        datasets: [{
          label: 'P&L Distribution',
          data: [],
          backgroundColor: 'rgba(88, 166, 255, 0.5)',
          borderColor: '#58a6ff',
          borderWidth: 1,
          borderRadius: 2,
          barPercentage: 1.0,
          categoryPercentage: 1.0,
        }],
      },
      options: mergeOptions({
        scales: {
          x: { title: { display: true, text: 'P&L ($)', color: tickColor } },
          y: { title: { display: true, text: 'Frequency', color: tickColor } },
        },
        plugins: { legend: { display: false } },
      }),
    });
  }



  function createEquityChart(canvasId) {
    const ctx = document.getElementById(canvasId);
    if (!ctx) return null;
    return new Chart(ctx, {
      type: 'line',
      data: { labels: [], datasets: [{ label: 'Close', data: [], borderColor: '#3fb950', backgroundColor: 'rgba(63,185,80,0.10)', fill: true, tension: 0.25, pointRadius: 0, borderWidth: 2 }] },
      options: mergeOptions({ plugins: { legend: { display: true, labels: { color: tickColor } } }, scales: { y: { title: { display: true, text: 'Price', color: tickColor } } } }),
    });
  }




  function createGeoRiskChart(canvasId) {
    const ctx = document.getElementById(canvasId);
    if (!ctx) return null;
    return new Chart(ctx, {
      type: 'bar',
      data: { labels: [], datasets: [{ label: 'Risk Score', data: [], backgroundColor: 'rgba(248,81,73,0.55)', borderColor: '#f85149', borderWidth: 1, borderRadius: 4 }] },
      options: mergeOptions({ plugins: { legend: { display: false } }, scales: { y: { min: 0, max: 100, title: { display: true, text: 'Score', color: tickColor } } } }),
    });
  }


  function updateChart(chart, newData) {
    if (!chart) return;
    if (newData.labels) chart.data.labels = newData.labels;
    if (newData.datasets) {
      newData.datasets.forEach((ds, i) => {
        if (chart.data.datasets[i]) {
          Object.assign(chart.data.datasets[i], ds);
        }
      });
    }
    chart.update('none');
  }

  function getThemeColors() {
    const style = getComputedStyle(document.documentElement);
    return {
      gridColor: style.getPropertyValue('--border-color').trim() + '99',
      tickColor: style.getPropertyValue('--text-secondary').trim(),
      tooltipBg: style.getPropertyValue('--bg-card').trim(),
      tooltipBorder: style.getPropertyValue('--border-color').trim(),
      titleColor: style.getPropertyValue('--text-primary').trim(),
      bodyColor: style.getPropertyValue('--text-secondary').trim(),
    };
  }

  function reThemeAllCharts() {
    const c = getThemeColors();

    const allCharts = [window._indexChart, window._fundingChart, window._divergenceChart, window._mcChart, window._equityChart, window._geoRiskChart].filter(Boolean);

    allCharts.forEach(chart => {
      if (chart.options.plugins.tooltip) {
        chart.options.plugins.tooltip.backgroundColor = c.tooltipBg;
        chart.options.plugins.tooltip.borderColor = c.tooltipBorder;
        chart.options.plugins.tooltip.titleColor = c.titleColor;
        chart.options.plugins.tooltip.bodyColor = c.bodyColor;
      }
      if (chart.options.plugins.legend && chart.options.plugins.legend.labels) {
        chart.options.plugins.legend.labels.color = c.tickColor;
      }
      Object.keys(chart.options.scales || {}).forEach(axis => {
        const s = chart.options.scales[axis];
        if (s.grid) s.grid.color = c.gridColor;
        if (s.ticks) s.ticks.color = c.tickColor;
        if (s.title) s.title.color = c.tickColor;
      });
      chart.update('none');
    });
  }

  return {
    createIndexChart,
    createFundingChart,
    createDivergenceChart,
    createMCChart,
    createEquityChart,

    createGeoRiskChart,
    updateChart,
    reThemeAllCharts,
  };
})();
