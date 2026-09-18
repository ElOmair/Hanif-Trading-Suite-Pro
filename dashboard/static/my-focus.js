(() => {
  const money = value => Number.isFinite(Number(value)) ? `$${Number(value).toFixed(2)}` : '—';
  const pct = value => Number.isFinite(Number(value)) ? `${Number(value) >= 0 ? '+' : ''}${Number(value).toFixed(1)}%` : '—';
  const safe = value => String(value ?? '').replace(/[&<>"']/g, ch => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch]));

  function errorText(body, status) {
    const detail = body?.detail;
    if (typeof detail === 'string') return detail;
    if (detail && typeof detail === 'object') {
      const missing = Array.isArray(detail.missing_fields) ? ` Missing: ${detail.missing_fields.join(', ')}.` : '';
      return `${detail.message || `HTTP ${status}`}${missing}`;
    }
    return `HTTP ${status}`;
  }

  async function requestJson(url, options = {}) {
    const response = await fetch(url, {
      credentials: 'same-origin',
      cache: 'no-store',
      headers: { Accept: 'application/json', 'Content-Type': 'application/json', ...(options.headers || {}) },
      ...options,
    });
    const body = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(errorText(body, response.status));
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
          <p class="muted">Add names you found yourself or positions you already hold. Open options become managed positions using your real fill and live Schwab option data.</p>
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
        <input id="mntFocusNote" maxlength="240" placeholder="Why you're watching it (optional)" aria-label="Note" />
        <button type="submit">Add / update</button>
        <div id="mntOptionFields" class="mnt-focus-option-fields" hidden>
          <select id="mntFocusOptionType" aria-label="Option type">
            <option value="CALL">Call</option>
            <option value="PUT">Put</option>
          </select>
          <input id="mntFocusStrike" type="number" min="0" step="0.01" placeholder="Strike" aria-label="Option strike" />
          <input id="mntFocusExpiration" type="date" aria-label="Option expiration" />
          <input id="mntFocusQuantity" type="number" min="1" max="100" step="1" value="1" placeholder="Qty" aria-label="Option quantity" />
          <input id="mntFocusContract" maxlength="80" placeholder="OCC symbol (optional)" aria-label="Option contract symbol" />
        </div>
      </form>
      <div id="mntFocusMessage" class="mnt-focus-message"></div>
      <div id="mntFocusList" class="mnt-focus-list"><div class="mnt-focus-empty">Loading your focus list…</div></div>
    `;
    const workspaceHost = document.getElementById('mntFocusHost');
    if (workspaceHost) workspaceHost.appendChild(shell);
    else {
      const nav = document.querySelector('.mnt-nav');
      if (nav?.parentNode) nav.parentNode.insertBefore(shell, nav.nextSibling);
      else document.body.prepend(shell);
    }

    const kind = shell.querySelector('#mntFocusKind');
    const entry = shell.querySelector('#mntFocusEntry');
    const optionFields = shell.querySelector('#mntOptionFields');
    const optionType = shell.querySelector('#mntFocusOptionType');
    const strike = shell.querySelector('#mntFocusStrike');
    const expiration = shell.querySelector('#mntFocusExpiration');
    const quantity = shell.querySelector('#mntFocusQuantity');
    const syncOptionState = () => {
      const show = kind.value === 'OPEN_OPTION';
      optionFields.hidden = !show;
      entry.placeholder = show ? 'Premium paid (e.g. 2.35)' : 'Entry / reference $';
      entry.required = show;
      for (const el of [optionType, strike, expiration, quantity]) {
        el.disabled = !show;
        el.required = show;
      }
      if (!show) shell.querySelector('#mntFocusContract').value = '';
    };
    kind.addEventListener('change', syncOptionState);
    syncOptionState();

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

      const analyze = event.target.closest('[data-focus-analyze-option]');
      if (analyze) {
        const symbol = analyze.dataset.focusAnalyzeOption;
        const host = document.querySelector(`[data-option-analysis-host="${CSS.escape(symbol)}"]`);
        analyze.disabled = true;
        analyze.textContent = 'Analyzing…';
        if (host) host.innerHTML = '<div class="mnt-option-manager-loading">Running Kronos + live option review…</div>';
        try {
          const data = await requestJson(`/api/mnt/focus/${encodeURIComponent(symbol)}/option-analysis?deep=true`);
          if (host) host.innerHTML = optionManagerHtml(data, true);
        } catch (error) {
          if (host) host.innerHTML = `<div class="mnt-option-manager-error">${safe(error.message)}</div>`;
        } finally {
          analyze.disabled = false;
          analyze.textContent = 'Analyze position';
        }
        return;
      }

      const open = event.target.closest('[data-focus-open]');
      if (open) {
        const symbol = open.dataset.focusOpen;
        window.MnTWorkspace?.openTab('trade');
        setTimeout(() => {
          const input = document.getElementById('symbolInput');
          const form = document.getElementById('symbolForm');
          if (input) input.value = symbol;
          if (form) form.requestSubmit();
          document.querySelector('.chart-panel')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
          if (open.dataset.runFusion === 'true') setTimeout(() => document.getElementById('runFusion')?.click(), 600);
        }, 80);
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
    const form = event.currentTarget;
    const button = form?.querySelector('button[type="submit"]');
    if (!form || !button) {
      showMessage('My Focus form is unavailable. Refresh the page and try again.', true);
      return;
    }
    button.disabled = true;
    showMessage('');
    const kind = document.getElementById('mntFocusKind').value;
    const openOption = kind === 'OPEN_OPTION';
    const entryRaw = document.getElementById('mntFocusEntry').value;
    const strikeRaw = document.getElementById('mntFocusStrike').value;
    const quantityRaw = document.getElementById('mntFocusQuantity').value;
    const payload = {
      symbol: document.getElementById('mntFocusSymbol').value.trim().toUpperCase(),
      kind,
      direction: document.getElementById('mntFocusDirection').value,
      entry_price: entryRaw ? Number(entryRaw) : null,
      contract: openOption ? document.getElementById('mntFocusContract').value.trim() || null : null,
      option_type: openOption ? document.getElementById('mntFocusOptionType').value : null,
      strike: openOption && strikeRaw ? Number(strikeRaw) : null,
      expiration: openOption ? document.getElementById('mntFocusExpiration').value || null : null,
      quantity: openOption && quantityRaw ? Number(quantityRaw) : null,
      note: document.getElementById('mntFocusNote').value.trim() || null,
    };
    try {
      await requestJson('/api/mnt/focus', { method: 'POST', body: JSON.stringify(payload) });
      form.reset();
      document.getElementById('mntFocusQuantity').value = '1';
      document.getElementById('mntFocusKind')?.dispatchEvent(new Event('change'));
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

  function stateClass(state) {
    const value = String(state || '').toUpperCase();
    if (['WORKING', 'PROTECT_PROFIT', 'TAKE_PROFIT'].includes(value)) return 'good';
    if (['UNDER_PRESSURE', 'TIME_RISK'].includes(value)) return 'caution';
    if (['RISK_OFF', 'EXIT_REVIEW'].includes(value)) return 'danger';
    return 'neutral';
  }

  function optionManagerHtml(data, deep = false) {
    const current = data.current || {};
    const pnl = data.pnl || {};
    const risk = data.risk || {};
    const levels = data.key_levels || {};
    const management = data.management || {};
    const thesis = data.thesis || {};
    const exitPct = Number(pnl.exit_pct);
    const pnlClass = Number.isFinite(exitPct) ? (exitPct >= 0 ? 'positive' : 'negative') : '';
    const recovery = Number(pnl.recovery_needed_pct);
    const flags = Array.isArray(risk.flags) ? risk.flags : [];
    const conflict = Array.isArray(thesis.conflict_reasons) ? thesis.conflict_reasons : [];
    const deepLevels = deep ? `
      <div class="mnt-option-levels">
        <div><span>Underlying invalidation</span><strong>${money(levels.underlying_invalidation)}</strong></div>
        <div><span>Underlying target 1</span><strong>${money(levels.underlying_target_1)}</strong></div>
        <div><span>Underlying target 2</span><strong>${money(levels.underlying_target_2)}</strong></div>
        <div><span>Underlying target 3</span><strong>${money(levels.underlying_target_3)}</strong></div>
      </div>` : '';

    return `
      <div class="mnt-option-manager ${stateClass(management.state)}">
        <div class="mnt-option-manager-head">
          <div><span>MnT POSITION MANAGER</span><strong>${safe(management.state || 'WATCH')}</strong></div>
          <span>${risk.days_to_expiration ?? '—'} DTE</span>
        </div>
        <h4>${safe(management.headline || 'Review the live option position.')}</h4>
        <div class="mnt-option-live-grid">
          <div><span>Your entry</span><strong>${money(data.entry_price)}</strong></div>
          <div><span>Live bid</span><strong>${money(current.bid)}</strong></div>
          <div><span>Live mark</span><strong>${money(current.mark)}</strong></div>
          <div><span>Exit P/L</span><strong class="${pnlClass}">${pct(pnl.exit_pct)} · ${money(pnl.exit_dollars)}</strong></div>
        </div>
        ${Number.isFinite(recovery) && recovery > 0 ? `<div class="mnt-option-recovery"><strong>To get back to your premium breakeven:</strong> the option mark needs to recover about ${pct(recovery)} from here.</div>` : ''}
        <div class="mnt-option-next"><span>NEXT STEP</span><strong>${safe(management.next_step || '')}</strong></div>
        <div class="mnt-option-levels">
          <div><span>Premium breakeven</span><strong>${money(levels.premium_breakeven)}</strong></div>
          <div><span>+20% checkpoint</span><strong>${money(levels.profit_checkpoint_20)}</strong></div>
          <div><span>+40% checkpoint</span><strong>${money(levels.profit_checkpoint_40)}</strong></div>
          <div><span>Protect-profit reference</span><strong>${money(levels.protect_profit_reference)}</strong></div>
          <div><span>Expiry breakeven stock</span><strong>${money(levels.underlying_expiry_breakeven)}</strong></div>
          <div><span>Underlying now</span><strong>${money(current.underlying_price)}</strong></div>
        </div>
        ${deepLevels}
        <div class="mnt-option-greeks">Delta ${safe(risk.delta)} · Theta ${safe(risk.theta)} · IV ${Number.isFinite(Number(risk.iv)) ? `${Number(risk.iv).toFixed(1)}%` : '—'} · Spread ${Number.isFinite(Number(current.spread_pct)) ? `${Number(current.spread_pct).toFixed(1)}%` : '—'}</div>
        ${deep && (thesis.technical_signal || thesis.kronos_bias) ? `<div class="mnt-option-thesis">Underlying thesis: technical ${safe(thesis.technical_signal || '—')} · Kronos ${safe(thesis.kronos_bias || '—')} · decision ${safe(thesis.decision || '—')}</div>` : ''}
        ${[...conflict, ...flags].slice(0, 4).map(flag => `<div class="mnt-option-flag">${safe(flag)}</div>`).join('')}
        <div class="mnt-option-foot">${safe(management.note || 'Research-only position management.')}</div>
      </div>`;
  }

  function optionSpecText(item) {
    if (item.expiration && item.strike && item.option_type) {
      return `${item.expiration} · ${money(item.strike)} ${safe(item.option_type)} · qty ${Number(item.quantity) || 1}`;
    }
    return safe(item.contract || 'Contract details incomplete');
  }

  async function render(items) {
    const host = document.getElementById('mntFocusList');
    if (!host) return;
    if (!items.length) {
      host.innerHTML = '<div class="mnt-focus-empty">Nothing added yet. Add a ticker above and MnT will keep it in your priority pool.</div>';
      return;
    }

    const snapshots = await Promise.all(items.map(async item => {
      const kind = String(item.kind || 'WATCHING').toUpperCase();
      if (kind === 'OPEN_OPTION') {
        try {
          return { option: await requestJson(`/api/mnt/focus/${encodeURIComponent(item.symbol)}/option-analysis`) };
        } catch (error) {
          return { optionError: error.message };
        }
      }
      return { price: await currentUnderlying(item.symbol) };
    }));

    host.innerHTML = items.map((item, index) => {
      const snapshot = snapshots[index] || {};
      const kind = String(item.kind || 'WATCHING').toUpperCase();
      const openPosition = kind === 'OPEN_STOCK' || kind === 'OPEN_OPTION';
      const price = kind === 'OPEN_OPTION' ? snapshot.option?.current?.underlying_price : snapshot.price;
      let performance = '';
      if (kind === 'OPEN_STOCK' && Number.isFinite(Number(item.entry_price)) && Number.isFinite(price)) {
        const move = (price / Number(item.entry_price) - 1) * 100;
        performance = `<span class="${move >= 0 ? 'positive' : 'negative'}">${move >= 0 ? '+' : ''}${move.toFixed(1)}%</span>`;
      }

      const optionBody = kind === 'OPEN_OPTION'
        ? snapshot.option
          ? `<div data-option-analysis-host="${safe(item.symbol)}">${optionManagerHtml(snapshot.option, false)}</div>`
          : `<div data-option-analysis-host="${safe(item.symbol)}" class="mnt-option-manager-error"><strong>Live option management needs more detail.</strong><span>${safe(snapshot.optionError || 'Add expiration, strike, call/put and your premium paid.')}</span><span>Re-enter ${safe(item.symbol)} above as Open option to update the saved position.</span></div>`
        : '';

      const actions = kind === 'OPEN_OPTION'
        ? `<button type="button" data-focus-analyze-option="${safe(item.symbol)}">Analyze position</button>
           <button type="button" data-focus-open="${safe(item.symbol)}">Trade Desk</button>
           <button type="button" class="remove" data-focus-remove="${safe(item.symbol)}">Remove</button>`
        : `<button type="button" data-focus-open="${safe(item.symbol)}" data-run-fusion="true">Open + run MnT</button>
           <button type="button" class="remove" data-focus-remove="${safe(item.symbol)}">Remove</button>`;

      return `
        <article class="mnt-focus-card ${openPosition ? 'position' : ''} ${kind === 'OPEN_OPTION' ? 'option-position' : ''}">
          <div class="mnt-focus-card-top">
            <div><strong>${safe(item.symbol)}</strong><span>${money(price)} ${performance}</span></div>
            <span class="mnt-focus-type">${labelKind(kind)}</span>
          </div>
          <div class="mnt-focus-grid">
            <div><span>Bias</span><strong>${safe(item.direction || 'AUTO')}</strong></div>
            <div><span>${kind === 'OPEN_OPTION' ? 'Premium paid' : 'Entry / reference'}</span><strong>${money(item.entry_price)}</strong></div>
            ${kind === 'OPEN_OPTION' ? `<div class="wide"><span>Your contract</span><strong>${optionSpecText(item)}</strong></div>` : ''}
            ${item.note ? `<div class="wide"><span>Your note</span><strong>${safe(item.note)}</strong></div>` : ''}
          </div>
          ${optionBody}
          <div class="mnt-focus-actions ${kind === 'OPEN_OPTION' ? 'option-actions' : ''}">${actions}</div>
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
