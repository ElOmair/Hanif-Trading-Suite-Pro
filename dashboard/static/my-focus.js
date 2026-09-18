(() => {
  const money = value => Number.isFinite(Number(value)) ? `$${Number(value).toFixed(2)}` : '—';
  const safe = value => String(value ?? '').replace(/[&<>"']/g, ch => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch]));

  async function requestJson(url, options = {}) {
    const response = await fetch(url, {
      credentials: 'same-origin',
      cache: 'no-store',
      headers: { Accept: 'application/json', 'Content-Type': 'application/json', ...(options.headers || {}) },
      ...options,
    });
    const body = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(body.detail || `HTTP ${response.status}`);
    return body;
  }

  function labelKind(kind) {
    if (kind === 'OPEN_STOCK') return 'OPEN STOCK';
    if (kind === 'OPEN_OPTION') return 'OPEN OPTION';
    return 'WATCHING';
  }

  function ensurePanel() {
    let shell = document.getElementById('mntMyFocus');
    if (shell) return shell;
    shell = document.createElement('section');
    shell.id = 'mntMyFocus';
    shell.className = 'mnt-focus-shell';
    shell.innerHTML = `
      <div class="mnt-focus-head">
        <div>
          <div class="eyebrow">YOUR PRIORITY LIST</div>
          <h2>My Focus</h2>
          <p class="muted">Add stocks you found yourself or positions you already hold. MnT gives these names priority in the Kronos review queue.</p>
        </div>
        <span class="mnt-focus-badge">UP TO 4 PRIORITY SCAN SLOTS</span>
      </div>
      <form id="mntFocusForm" class="mnt-focus-form">
        <input id="mntFocusSymbol" maxlength="10" placeholder="Ticker" aria-label="Ticker" required />
        <select id="mntFocusKind" aria-label="Focus type">
          <option value="WATCHING">Watching</option>
          <option value="OPEN_STOCK">Open stock</option>
          <option value="OPEN_OPTION">Open option</option>
        </select>
        <select id="mntFocusDirection" aria-label="Direction">
          <option value="AUTO">Auto bias</option>
          <option value="LONG">Long / bullish</option>
          <option value="SHORT">Short / bearish</option>
        </select>
        <input id="mntFocusEntry" type="number" min="0" step="0.01" placeholder="Entry / reference $" aria-label="Entry or reference price" />
        <input id="mntFocusContract" maxlength="80" placeholder="Option contract (optional)" aria-label="Option contract" />
        <input id="mntFocusNote" maxlength="240" placeholder="Why you're watching it (optional)" aria-label="Note" />
        <button type="submit">Add / update</button>
      </form>
      <div id="mntFocusMessage" class="mnt-focus-message"></div>
      <div id="mntFocusList" class="mnt-focus-list"><div class="mnt-focus-empty">Loading your focus list…</div></div>
    `;
    const nav = document.querySelector('.mnt-nav');
    if (nav?.parentNode) nav.parentNode.insertBefore(shell, nav.nextSibling);
    else document.body.prepend(shell);

    const kind = shell.querySelector('#mntFocusKind');
    const contract = shell.querySelector('#mntFocusContract');
    const syncContractState = () => {
      const show = kind.value === 'OPEN_OPTION';
      contract.disabled = !show;
      contract.style.display = show ? '' : 'none';
      if (!show) contract.value = '';
    };
    kind.addEventListener('change', syncContractState);
    syncContractState();

    shell.querySelector('#mntFocusForm').addEventListener('submit', saveItem);
    shell.addEventListener('click', async event => {
      const remove = event.target.closest('[data-focus-remove]');
      if (remove) {
        remove.disabled = true;
        try {
          await requestJson(`/api/mnt/focus/${encodeURIComponent(remove.dataset.focusRemove)}`, { method: 'DELETE' });
          await load();
        } catch (error) {
          showMessage(error.message, true);
          remove.disabled = false;
        }
        return;
      }
      const open = event.target.closest('[data-focus-open]');
      if (open) {
        const symbol = open.dataset.focusOpen;
        const input = document.getElementById('symbolInput');
        const form = document.getElementById('symbolForm');
        if (input) input.value = symbol;
        if (form) form.requestSubmit();
        document.querySelector('.chart-panel')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
        setTimeout(() => document.getElementById('runFusion')?.click(), 700);
      }
    });
    return shell;
  }

  function showMessage(text, error = false) {
    const el = document.getElementById('mntFocusMessage');
    if (!el) return;
    el.textContent = text || '';
    el.className = `mnt-focus-message${error ? ' error' : ''}`;
  }

  async function saveItem(event) {
    event.preventDefault();
    const button = event.currentTarget.querySelector('button[type="submit"]');
    button.disabled = true;
    showMessage('');
    const entryRaw = document.getElementById('mntFocusEntry').value;
    const payload = {
      symbol: document.getElementById('mntFocusSymbol').value.trim().toUpperCase(),
      kind: document.getElementById('mntFocusKind').value,
      direction: document.getElementById('mntFocusDirection').value,
      entry_price: entryRaw ? Number(entryRaw) : null,
      contract: document.getElementById('mntFocusContract').value.trim() || null,
      note: document.getElementById('mntFocusNote').value.trim() || null,
    };
    try {
      await requestJson('/api/mnt/focus', { method: 'POST', body: JSON.stringify(payload) });
      event.currentTarget.reset();
      document.getElementById('mntFocusKind').dispatchEvent(new Event('change'));
      showMessage(`${payload.symbol} saved to My Focus.`);
      await load();
    } catch (error) {
      showMessage(error.message, true);
    } finally {
      button.disabled = false;
    }
  }

  async function currentUnderlying(symbol) {
    try {
      const payload = await requestJson(`/api/tick/${encodeURIComponent(symbol)}`);
      const mid = Number(payload.quote?.mid);
      const close = Number(payload.bar?.close);
      return Number.isFinite(mid) && mid > 0 ? mid : Number.isFinite(close) && close > 0 ? close : null;
    } catch (_) {
      return null;
    }
  }

  async function render(items) {
    const host = document.getElementById('mntFocusList');
    if (!host) return;
    if (!items.length) {
      host.innerHTML = '<div class="mnt-focus-empty">Nothing added yet. Add a ticker above and MnT will keep it in your priority pool.</div>';
      return;
    }
    const prices = await Promise.all(items.map(item => currentUnderlying(item.symbol)));
    host.innerHTML = items.map((item, index) => {
      const price = prices[index];
      const kind = String(item.kind || 'WATCHING').toUpperCase();
      const openPosition = kind === 'OPEN_STOCK' || kind === 'OPEN_OPTION';
      let performance = '';
      if (kind === 'OPEN_STOCK' && Number.isFinite(Number(item.entry_price)) && Number.isFinite(price)) {
        const pct = (price / Number(item.entry_price) - 1) * 100;
        performance = `<span class="${pct >= 0 ? 'positive' : 'negative'}">${pct >= 0 ? '+' : ''}${pct.toFixed(1)}%</span>`;
      }
      return `
        <article class="mnt-focus-card ${openPosition ? 'position' : ''}">
          <div class="mnt-focus-card-top">
            <div><strong>${safe(item.symbol)}</strong><span>${money(price)} ${performance}</span></div>
            <span class="mnt-focus-type">${labelKind(kind)}</span>
          </div>
          <div class="mnt-focus-grid">
            <div><span>Bias</span><strong>${safe(item.direction || 'AUTO')}</strong></div>
            <div><span>Entry / reference</span><strong>${money(item.entry_price)}</strong></div>
            ${kind === 'OPEN_OPTION' ? `<div class="wide"><span>Contract</span><strong>${safe(item.contract || 'Not entered')}</strong></div>` : ''}
            ${item.note ? `<div class="wide"><span>Your note</span><strong>${safe(item.note)}</strong></div>` : ''}
          </div>
          <div class="mnt-focus-actions">
            <button type="button" data-focus-open="${safe(item.symbol)}">Open + run MnT</button>
            <button type="button" class="remove" data-focus-remove="${safe(item.symbol)}">Remove</button>
          </div>
        </article>`;
    }).join('');
  }

  async function load() {
    ensurePanel();
    try {
      const payload = await requestJson('/api/mnt/focus');
      await render(Array.isArray(payload.items) ? payload.items : []);
    } catch (error) {
      const host = document.getElementById('mntFocusList');
      if (host) host.innerHTML = `<div class="mnt-focus-empty">Could not load My Focus: ${safe(error.message)}</div>`;
    }
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', load);
  else load();
})();
