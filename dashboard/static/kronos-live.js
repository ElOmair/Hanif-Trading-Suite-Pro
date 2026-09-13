(() => {
  const card = document.querySelector('.analysis-card');
  if (!card || document.getElementById('runKronos')) return;

  const heading = card.querySelector('h2');
  const controls = document.createElement('div');
  controls.className = 'kronos-live-controls';
  controls.innerHTML = `
    <button id="runKronos" type="button" class="ghost-button">Run Kronos</button>
    <span id="kronosLiveMessage" class="muted">Manual GPU analysis</span>
  `;
  heading.insertAdjacentElement('afterend', controls);

  const metrics = document.createElement('div');
  metrics.id = 'kronosLiveMetrics';
  metrics.className = 'metric-grid kronos-live-metrics';
  metrics.innerHTML = `
    <div><span>Kronos score</span><strong id="kronosScore">—</strong></div>
    <div><span>1H forecast</span><strong id="kronos1h">—</strong></div>
    <div><span>2H forecast</span><strong id="kronos2h">—</strong></div>
    <div><span>Paths</span><strong id="kronosPaths">—</strong></div>
    <div><span>Stability</span><strong id="kronosStability">—</strong></div>
    <div><span>Final bias</span><strong id="kronosBias">—</strong></div>
    <div><span>Action</span><strong id="kronosAction">—</strong></div>
  `;
  const firstMetrics = card.querySelector('.metric-grid');
  if (firstMetrics) firstMetrics.insertAdjacentElement('afterend', metrics);
  else controls.insertAdjacentElement('afterend', metrics);

  const button = document.getElementById('runKronos');
  const message = document.getElementById('kronosLiveMessage');

  function put(id, value) {
    const el = document.getElementById(id);
    if (el) el.textContent = value ?? '—';
  }

  function pct(value) {
    return Number.isFinite(Number(value)) ? `${Number(value) >= 0 ? '+' : ''}${Number(value).toFixed(2)}%` : '—';
  }

  function toast(title, body, css = 'watch') {
    const stack = document.getElementById('toastStack');
    if (!stack) return;
    const node = document.createElement('div');
    node.className = `trade-toast ${css}`;
    node.innerHTML = `<button class="toast-close" aria-label="Dismiss">×</button><div class="toast-title">${title}</div><div class="toast-body">${body}</div>`;
    node.querySelector('.toast-close')?.addEventListener('click', () => node.remove());
    stack.prepend(node);
    setTimeout(() => node.remove(), 14000);
  }

  async function run() {
    const symbol = (document.getElementById('activeSymbol')?.textContent || '').trim().toUpperCase();
    if (!symbol) return;

    button.disabled = true;
    button.textContent = 'Running Kronos…';
    message.textContent = `${symbol} GPU forecast in progress`;
    put('kronosAnalysisState', 'Running…');

    try {
      const res = await fetch(`/api/kronos/analyze/${encodeURIComponent(symbol)}`, { method: 'POST' });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);

      put('kronosScore', data.average_score == null ? '—' : `${Number(data.average_score).toFixed(1)}/100`);
      put('kronos1h', pct(data.median_1h_move_pct));
      put('kronos2h', pct(data.median_2h_move_pct));
      put('kronosPaths', `${data.bullish_paths ?? 0}B / ${data.bearish_paths ?? 0}S / ${data.neutral_paths ?? 0}N`);
      put('kronosStability', data.stability || '—');
      put('kronosBias', data.final_bias || '—');
      put('kronosAction', data.action || '—');
      put('kronosAnalysisState', `${data.final_bias || '—'} · ${data.action || '—'}`);

      const css = data.final_bias === 'BULLISH' ? 'ready' : data.final_bias === 'BEARISH' ? 'too-late' : 'watch';
      const option = data.final_bias === 'BULLISH' ? 'CALL bias' : data.final_bias === 'BEARISH' ? 'PUT bias' : 'NO OPTION — WAIT';
      message.textContent = `${option} · ${data.stability || '—'} stability · ${Number(data.runtime_seconds || 0).toFixed(2)}s`;
      toast(
        `${symbol} — Kronos ${data.final_bias || 'UNKNOWN'}`,
        `${option}. 1H ${pct(data.median_1h_move_pct)}, 2H ${pct(data.median_2h_move_pct)}, stability ${data.stability || '—'}, action ${data.action || '—'}.`,
        css,
      );
    } catch (err) {
      put('kronosAnalysisState', 'Error');
      message.textContent = err.message;
      toast(`${symbol} — Kronos error`, err.message, 'too-late');
      console.error(err);
    } finally {
      button.disabled = false;
      button.textContent = 'Run Kronos';
    }
  }

  button.addEventListener('click', run);
})();
