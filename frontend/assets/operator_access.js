(() => {
  'use strict';

  const STORAGE_KEY = 'tariff-risk-desk.operator-token';
  const originalFetch = window.fetch.bind(window);

  const exact = new Set([
    'POST /api/execution/order',
    'POST /api/execution/conditional-order',
    'POST /api/execution/conditional-orders/evaluate',
    'POST /api/execution/smart-order',
    'POST /api/execution/jupiter/swap',
    'POST /api/ml/train/offline',
    'POST /api/decisions',
    'POST /api/heuristics/evaluate',
    'POST /api/backtest/run',
    'POST /api/watchlists',
  ]);

  function protectedMutation(method, path) {
    method = String(method || 'GET').toUpperCase();
    if (exact.has(`${method} ${path}`)) return true;
    if (method === 'DELETE' && /^\/api\/execution\/conditional-order\/[^/]+$/.test(path)) return true;
    if (method === 'POST' && /^\/api\/ml\/models\/[^/]+\/(promote|rollback)$/.test(path)) return true;
    if ((method === 'PUT' || method === 'DELETE') && /^\/api\/watchlists\/[^/]+$/.test(path)) return true;
    return false;
  }

  function token() {
    try { return sessionStorage.getItem(STORAGE_KEY) || ''; }
    catch (_) { return ''; }
  }

  function setToken(value) {
    try {
      const clean = String(value || '').trim();
      if (clean) sessionStorage.setItem(STORAGE_KEY, clean);
      else sessionStorage.removeItem(STORAGE_KEY);
      renderStatus();
    } catch (_) {}
  }

  window.fetch = function(input, init) {
    const options = Object.assign({}, init || {});
    let url;
    try {
      url = new URL(typeof input === 'string' ? input : input.url, window.location.origin);
    } catch (_) {
      return originalFetch(input, init);
    }
    const method = String(options.method || (typeof input !== 'string' && input.method) || 'GET').toUpperCase();
    if (!protectedMutation(method, url.pathname)) return originalFetch(input, init);

    const operatorToken = token();
    if (!operatorToken) return originalFetch(input, init);

    const headers = new Headers(options.headers || (typeof input !== 'string' ? input.headers : undefined) || {});
    headers.set('Authorization', `Bearer ${operatorToken}`);
    options.headers = headers;
    return originalFetch(input, options);
  };

  function renderStatus() {
    const button = document.getElementById('operator-access-toggle');
    if (!button) return;
    const configured = Boolean(token());
    button.textContent = configured ? 'OPERATOR ✓' : 'OPERATOR';
    button.title = configured ? 'Operator token is set for this browser tab/session' : 'Set operator token for protected actions';
  }

  function installControl() {
    if (document.getElementById('operator-access-toggle')) return;
    const host = document.querySelector('.header-right');
    if (!host) return;

    const button = document.createElement('button');
    button.id = 'operator-access-toggle';
    button.type = 'button';
    button.className = 'theme-toggle';
    button.style.minWidth = '92px';
    button.addEventListener('click', () => {
      const current = token();
      if (current) {
        const clear = window.confirm('Clear the operator token for this browser session?');
        if (clear) setToken('');
        return;
      }
      const entered = window.prompt('Operator token (stored only in sessionStorage for this tab/session):');
      if (entered !== null) setToken(entered);
    });

    const connection = document.getElementById('connection-status');
    host.insertBefore(button, connection || null);
    renderStatus();
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', installControl);
  else installControl();

  window.OperatorAccess = Object.freeze({
    setToken,
    clearToken: () => setToken(''),
    hasToken: () => Boolean(token()),
  });
})();
