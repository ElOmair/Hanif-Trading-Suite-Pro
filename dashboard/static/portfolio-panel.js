(() => {
  const money = (value) => {
    const n = Number(value);
    return Number.isFinite(n) ? n.toLocaleString(undefined, { style: 'currency', currency: 'USD', maximumFractionDigits: 2 }) : '—';
  };
  const pct = (value) => {
    const n = Number(value);
    return Number.isFinite(n) ? `${n >= 0 ? '+' : ''}${n.toFixed(1)}%` : '—';
  };
  const safe = (value, fallback = '—') => value === undefined || value === null || value === '' ? fallback : String(value);

  async function getJson(url) {
    const response = await fetch(url, { credentials: 'same-origin', cache: 'no-store', headers: { Accept: 'application/json' } });
    const body = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(body.detail || `HTTP ${response.status}`);
    return body;
  }

  function underlying(row) {
    const symbol = String(row?.symbol || '').trim().toUpperCase();
    if (!symbol) return '';
    return String(row?.asset_type || '').toUpperCase() === 'OPTION' ? symbol.split(/\s+/)[0] : symbol;
  }

  function ensureHost() {
    const card = document.querySelector('.positions-card');
    if (!card) return null;
    let host = document.getElementById('mntBrokerLive');
    if (host) return host;
    host = document.createElement('section');
    host.id = 'mntBrokerLive';
    host.className = 'mnt-broker-live';
    const insertBefore = document.getElementById('setupJournalNote') || card.firstChild;
    card.insertBefore(host, insertBefore);
    return host;
  }

  function loadSymbol(symbol) {
    const input = document.getElementById('symbolInput');
    const form = document.getElementById('symbolForm');
    if (input) input.value = symbol;
    if (form) form.requestSubmit();
    document.querySelector('.chart-panel')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }

  function renderDisconnected(host, status) {
    const configured = Boolean(status?.configured);
    host.innerHTML = `
      <div class="mnt-broker-live-head">
        <div><div class="eyebrow">LIVE SCHWAB / THINKORSWIM</div><strong>Portfolio awareness</strong></div>
        <span class="mnt-broker-badge warning">${configured ? 'AUTH REQUIRED' : 'NOT CONFIGURED'}</span>
      </div>
      <div class="fineprint">${configured ? 'Connect Schwab to let MnT see actual positions, balances, and buying power.' : 'Schwab is not enabled on this server yet.'}</div>
      <div style="display:flex;gap:7px;flex-wrap:wrap;margin-top:9px">
        ${configured ? '<a class="ghost-button" href="/api/schwab/authorize">Connect Schwab</a>' : ''}
        <a class="ghost-button" href="/broker">Open Broker Desk</a>
      </div>`;
  }

  function renderPortfolio(host, payload) {
    const accounts = payload.accounts || [];
    let liquidation = 0;
    let cash = 0;
    let buyingPower = 0;
    const positions = [];
    for (const account of accounts) {
      const balances = account.balances || {};
      liquidation += Number(balances.liquidation_value) || 0;
      cash += Number(balances.cash_balance) || 0;
      buyingPower += Number(balances.buying_power) || 0;
      for (const row of account.positions || []) positions.push(row);
    }

    const topRows = positions
      .slice()
      .sort((a, b) => Math.abs(Number(b.market_value) || 0) - Math.abs(Number(a.market_value) || 0))
      .slice(0, 5);

    host.innerHTML = `
      <div class="mnt-broker-live-head">
        <div><div class="eyebrow">LIVE SCHWAB / THINKORSWIM</div><strong>Portfolio awareness</strong></div>
        <span class="mnt-broker-badge connected">CONNECTED</span>
      </div>
      <div class="mnt-broker-metrics">
        <div><span>Account value</span><strong>${money(liquidation)}</strong></div>
        <div><span>Buying power</span><strong>${money(buyingPower)}</strong></div>
        <div><span>Cash</span><strong>${money(cash)}</strong></div>
        <div><span>Positions</span><strong>${positions.length}</strong></div>
      </div>
      <div class="mnt-live-position-list">
        ${topRows.length ? topRows.map(row => {
          const pnl = Number(row.current_day_profit_loss);
          const cls = Number.isFinite(pnl) ? (pnl >= 0 ? 'positive' : 'negative') : '';
          const u = underlying(row);
          return `<div class="mnt-live-position" data-underlying="${u}">
            <div class="mnt-live-position-top"><strong>${safe(row.symbol)}</strong><span class="${cls}">${pct(row.current_day_profit_loss_pct)}</span></div>
            <small>${safe(row.asset_type)} · value ${money(row.market_value)} · avg ${money(row.average_price)}</small>
          </div>`;
        }).join('') : '<div class="fineprint">No open positions returned.</div>'}
      </div>
      <div style="display:flex;gap:7px;flex-wrap:wrap;margin-top:9px">
        <button id="mntRefreshBroker" class="ghost-button" type="button">Refresh</button>
        <a class="ghost-button" href="/broker">Full Broker Desk</a>
      </div>`;

    host.querySelectorAll('[data-underlying]').forEach(row => row.addEventListener('click', () => loadSymbol(row.dataset.underlying)));
    host.querySelector('#mntRefreshBroker')?.addEventListener('click', refresh);
  }

  async function refresh() {
    const host = ensureHost();
    if (!host) return;
    try {
      const status = await getJson('/api/schwab/status');
      const connected = Boolean(status.authorized && status.refresh_token_valid);
      if (!connected) {
        renderDisconnected(host, status);
        return;
      }
      const payload = await getJson('/api/schwab/positions');
      renderPortfolio(host, payload);
    } catch (error) {
      host.innerHTML = `<div class="mnt-broker-live-head"><div><div class="eyebrow">LIVE SCHWAB / THINKORSWIM</div><strong>Portfolio awareness</strong></div><span class="mnt-broker-badge warning">OFFLINE</span></div><div class="fineprint">${safe(error.message)}</div><div style="margin-top:8px"><a class="ghost-button" href="/broker">Open Broker Desk</a></div>`;
    }
  }

  function start() {
    const wait = setInterval(() => {
      if (document.getElementById('setupJournalList')) {
        clearInterval(wait);
        refresh();
        setInterval(refresh, 60000);
      }
    }, 250);
    setTimeout(() => clearInterval(wait), 10000);
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start);
  else start();
})();
