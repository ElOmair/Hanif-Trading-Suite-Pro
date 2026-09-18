(() => {
  const state = {
    symbol: 'SPY', timeframe: '5m', socket: null, radar: new Map(), currentAnalysis: null,
    currentSetup: null, lastAlertState: new Map(), notificationsEnabled: false,
  };

  const chartEl = document.getElementById('chart');
  const chart = LightweightCharts.createChart(chartEl, {
    autoSize: true,
    layout: { background: { type: 'solid', color: '#0a151f' }, textColor: '#8298aa', attributionLogo: false },
    grid: { vertLines: { color: 'rgba(120,150,170,.08)' }, horzLines: { color: 'rgba(120,150,170,.08)' } },
    rightPriceScale: { borderColor: '#1c3142' },
    timeScale: { borderColor: '#1c3142', timeVisible: true, secondsVisible: false },
    crosshair: { mode: LightweightCharts.CrosshairMode.Normal },
  });

  const candles = chart.addSeries(LightweightCharts.CandlestickSeries, {
    upColor: '#37d694', downColor: '#ff6b78', borderVisible: false,
    wickUpColor: '#37d694', wickDownColor: '#ff6b78',
  });
  const volume = chart.addSeries(LightweightCharts.HistogramSeries, {
    priceFormat: { type: 'volume' }, priceScaleId: '',
  });
  volume.priceScale().applyOptions({ scaleMargins: { top: 0.82, bottom: 0 } });
  const ema9Series = chart.addSeries(LightweightCharts.LineSeries, {
    color: '#4db6ff', lineWidth: 1, priceLineVisible: false, lastValueVisible: false, title: 'EMA 9',
  });
  const ema21Series = chart.addSeries(LightweightCharts.LineSeries, {
    color: '#c58cff', lineWidth: 1, priceLineVisible: false, lastValueVisible: false, title: 'EMA 21',
  });
  const vwapSeries = chart.addSeries(LightweightCharts.LineSeries, {
    color: '#f3bf5b', lineWidth: 1, priceLineVisible: false, lastValueVisible: false, title: 'RTH VWAP',
  });

  function setStatus(id, text, ok) {
    const el = document.getElementById(id);
    el.textContent = text;
    el.classList.remove('ok', 'bad');
    if (ok === true) el.classList.add('ok');
    if (ok === false) el.classList.add('bad');
  }

  function providerLabel(provider) {
    const value = String(provider || '').toLowerCase();
    if (value === 'schwab') return 'Schwab primary';
    if (value === 'mixed') return 'Mixed feed';
    if (value.includes('alpaca_sip')) return 'Alpaca SIP fallback';
    if (value.includes('alpaca_iex')) return 'Alpaca IEX fallback';
    return provider ? String(provider) : 'Market data unavailable';
  }

  async function loadSystem() {
    try {
      const res = await fetch('/api/system');
      const data = await res.json();
      const market = data.market_data || {};
      const active = market.active_provider || (data.alpaca?.feed ? `alpaca_${data.alpaca.feed}` : 'unavailable');
      const fallbackReady = Boolean(market.fallback?.configured ?? data.alpaca?.configured);
      setStatus('alpacaStatus', fallbackReady ? 'Fallback ready' : 'Fallback missing', fallbackReady);
      setStatus('kronosStatus', data.kronos.online ? 'Kronos online' : 'Kronos offline', data.kronos.online);
      setStatus('feedStatus', providerLabel(active), active !== 'unavailable' && !market.degraded);
      document.getElementById('kronosAnalysisState').textContent = data.kronos.online ? 'Online' : 'Offline';
    } catch (_) {
      setStatus('alpacaStatus', 'Fallback unknown', false);
      setStatus('feedStatus', 'Market data offline', false);
      setStatus('kronosStatus', 'Kronos unknown', false);
    }
  }

  function volumeColor(bar) {
    return bar.close >= bar.open ? 'rgba(55,214,148,.45)' : 'rgba(255,107,120,.45)';
  }

  function ema(rows, period) {
    if (!rows.length) return [];
    const k = 2 / (period + 1);
    let value = Number(rows[0].close);
    return rows.map((row, index) => {
      if (index) value = Number(row.close) * k + value * (1 - k);
      return { time: row.time, value };
    });
  }

  const etFormatter = new Intl.DateTimeFormat('en-US', {
    timeZone: 'America/New_York', year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', hourCycle: 'h23',
  });

  function etParts(epochSeconds) {
    const parts = Object.fromEntries(etFormatter.formatToParts(new Date(epochSeconds * 1000)).map(p => [p.type, p.value]));
    return { day: `${parts.year}-${parts.month}-${parts.day}`, minutes: Number(parts.hour) * 60 + Number(parts.minute) };
  }

  function rthVwap(rows) {
    let currentDay = '';
    let pv = 0;
    let vol = 0;
    return rows.map(row => {
      const et = etParts(row.time);
      if (et.day !== currentDay) { currentDay = et.day; pv = 0; vol = 0; }
      const inRth = et.minutes >= 570 && et.minutes < 960;
      if (!inRth || !Number(row.volume)) return { time: row.time };
      const typical = (Number(row.high) + Number(row.low) + Number(row.close)) / 3;
      pv += typical * Number(row.volume);
      vol += Number(row.volume);
      return { time: row.time, value: pv / vol };
    });
  }

  function barStats(rows) {
    const clean = rows.filter(r => Number.isFinite(Number(r.close)) && Number.isFinite(Number(r.volume)));
    if (clean.length < 25) return null;
    const frame = clean.slice(-120);
    const closes = frame.map(r => Number(r.close));
    const highs = frame.map(r => Number(r.high));
    const lows = frame.map(r => Number(r.low));
    const volumes = frame.map(r => Number(r.volume));
    const ema9 = ema(frame, 9).map(x => x.value);
    const ema21 = ema(frame, 21).map(x => x.value);
    const tr = frame.map((r, i) => {
      if (!i) return highs[i] - lows[i];
      const prev = closes[i - 1];
      return Math.max(highs[i] - lows[i], Math.abs(highs[i] - prev), Math.abs(lows[i] - prev));
    });
    const avg = values => values.reduce((a, b) => a + b, 0) / values.length;
    const last = closes.at(-1);
    const momentum = closes.length >= 7 ? (last / closes.at(-7) - 1) * 100 : 0;
    const priorVol = volumes.slice(-21, -1).filter(v => v > 0);
    const avgVol = priorVol.length ? avg(priorVol) : 0;
    const rvol = avgVol > 0 ? volumes.at(-1) / avgVol : 0;
    const atr14 = tr.length >= 14 ? avg(tr.slice(-14)) : 0;
    const atrPct = last > 0 ? atr14 / last * 100 : 0;
    const emaSpread = ema21.at(-1) ? (ema9.at(-1) / ema21.at(-1) - 1) * 100 : 0;
    return { frame, closes, highs, lows, volumes, ema9, ema21, last, momentum, rvol, atr14, atrPct, emaSpread };
  }

  function analyzeBars(rows) {
    const stats = barStats(rows);
    if (!stats) return null;
    let score = 50;
    score += Math.max(-18, Math.min(18, stats.emaSpread * 45));
    score += Math.max(-18, Math.min(18, stats.momentum * 9));
    if (stats.rvol >= 1.5) score += stats.momentum >= 0 ? 8 : -8;
    else if (stats.rvol >= 1.1) score += stats.momentum >= 0 ? 4 : -4;
    score = Math.max(0, Math.min(100, score));
    const direction = score >= 62 ? 'LONG' : score <= 38 ? 'SHORT' : 'NEUTRAL';
    return {
      symbol: state.symbol, score: Number(score.toFixed(1)), direction,
      momentum_30m_pct: Number(stats.momentum.toFixed(2)), rvol: Number(stats.rvol.toFixed(2)),
      atr_pct: Number(stats.atrPct.toFixed(2)), atr_abs: stats.atr14,
    };
  }

  function money(value) {
    return Number.isFinite(Number(value)) ? `$${Number(value).toFixed(2)}` : '—';
  }

  function buildTechnicalPreview(rows, analysis) {
    const stats = barStats(rows);
    if (!stats || !analysis || analysis.direction === 'NEUTRAL' || !stats.atr14) {
      return { state: 'WAITING', css: 'waiting', direction: analysis?.direction || '—', note: 'No directional setup yet. Kronos confirmation is still required.' };
    }
    const direction = analysis.direction;
    const atr = stats.atr14;
    const current = stats.last;
    const recent = stats.frame.slice(-7, -1);
    const trigger = direction === 'LONG'
      ? Math.max(...recent.map(r => Number(r.high)))
      : Math.min(...recent.map(r => Number(r.low)));
    const entryLow = trigger - atr * 0.10;
    const entryHigh = trigger + atr * 0.10;
    const midpoint = (entryLow + entryHigh) / 2;
    const noChase = direction === 'LONG' ? entryHigh + atr * 0.25 : entryLow - atr * 0.25;
    const stop = direction === 'LONG' ? midpoint - atr : midpoint + atr;
    const risk = Math.abs(midpoint - stop);
    const tp1 = direction === 'LONG' ? midpoint + risk : midpoint - risk;
    const tp2 = direction === 'LONG' ? midpoint + risk * 2 : midpoint - risk * 2;
    const tp3 = direction === 'LONG' ? midpoint + risk * 3 : midpoint - risk * 3;

    let setupState = 'WATCH';
    let css = 'watch';
    if (current >= entryLow && current <= entryHigh) { setupState = 'PREVIEW ENTRY ZONE'; css = 'ready'; }
    if (direction === 'LONG' && current > noChase) { setupState = 'DO NOT CHASE'; css = 'too-late'; }
    if (direction === 'SHORT' && current < noChase) { setupState = 'DO NOT CHASE'; css = 'too-late'; }

    return {
      state: setupState, css, direction, current, entryLow, entryHigh, noChase, stop, tp1, tp2, tp3,
      note: setupState === 'DO NOT CHASE'
        ? 'Price has moved beyond the preliminary chase limit. Wait for a retest/re-entry condition.'
        : 'Technical preview only. Do not treat this as CONFIRM until the Kronos ensemble and risk gates agree.',
    };
  }

  function renderAnalysis(item) {
    const values = item || {};
    document.getElementById('technicalScore').textContent = values.score ?? '—';
    document.getElementById('direction').textContent = values.direction ?? '—';
    document.getElementById('momentum').textContent = values.momentum_30m_pct == null ? '—' : `${values.momentum_30m_pct}%`;
    document.getElementById('rvol').textContent = values.rvol ?? '—';
    document.getElementById('atrPct').textContent = values.atr_pct == null ? '—' : `${values.atr_pct}%`;
  }

  function renderSetup(setup) {
    state.currentSetup = setup;
    const card = document.getElementById('setupCard');
    card.className = `setup-card ${setup.css || 'waiting'}`;
    document.getElementById('setupState').textContent = setup.state || 'WAITING';
    document.getElementById('setupDirection').textContent = setup.direction || '—';
    document.getElementById('entryZone').textContent = setup.entryLow == null ? '—' : `${money(setup.entryLow)} – ${money(setup.entryHigh)}`;
    document.getElementById('noChase').textContent = money(setup.noChase);
    document.getElementById('stopLevel').textContent = money(setup.stop);
    document.getElementById('tp1Level').textContent = money(setup.tp1);
    document.getElementById('tp2Level').textContent = money(setup.tp2);
    document.getElementById('tp3Level').textContent = money(setup.tp3);
    document.getElementById('setupNote').textContent = setup.note || '';
    maybeAlertSetup(setup);
  }

  function showToast(title, body, css = 'ready') {
    const stack = document.getElementById('toastStack');
    const toast = document.createElement('div');
    toast.className = `trade-toast ${css}`;
    toast.innerHTML = `<button class="toast-close" aria-label="Dismiss">×</button><div class="toast-title">${title}</div><div class="toast-body">${body}</div>`;
    toast.querySelector('.toast-close').addEventListener('click', () => toast.remove());
    stack.prepend(toast);
    setTimeout(() => toast.remove(), 12000);
  }

  function maybeDesktopNotification(title, body) {
    if (!state.notificationsEnabled || typeof Notification === 'undefined' || Notification.permission !== 'granted') return;
    try { new Notification(title, { body, tag: `hanif-${state.symbol}` }); } catch (_) {}
  }

  function maybeAlertSetup(setup) {
    if (!['PREVIEW ENTRY ZONE', 'DO NOT CHASE'].includes(setup.state)) return;
    const previous = state.lastAlertState.get(state.symbol);
    if (previous === setup.state) return;
    state.lastAlertState.set(state.symbol, setup.state);
    const title = setup.state === 'DO NOT CHASE' ? `⚠ ${state.symbol} — DO NOT CHASE` : `◉ ${state.symbol} — Entry zone preview`;
    const body = setup.state === 'DO NOT CHASE'
      ? `${setup.direction} moved beyond ${money(setup.noChase)}. Wait for a retest. No Kronos confirmation yet.`
      : `${setup.direction} technical zone ${money(setup.entryLow)}–${money(setup.entryHigh)}. No-chase ${money(setup.noChase)}. Kronos confirmation pending.`;
    showToast(title, body, setup.css);
    maybeDesktopNotification(title.replace(/[⚠◉]/g, '').trim(), body);
  }

  async function configureNotifications() {
    const button = document.getElementById('enableAlerts');
    if (typeof Notification === 'undefined') {
      button.textContent = 'Browser alerts unavailable';
      button.disabled = true;
      return;
    }
    if (Notification.permission === 'granted') {
      state.notificationsEnabled = true;
      button.textContent = 'Browser alerts on';
      button.classList.add('enabled');
      return;
    }
    if (Notification.permission === 'denied') {
      button.textContent = 'Alerts blocked in browser';
      return;
    }
    const permission = await Notification.requestPermission();
    state.notificationsEnabled = permission === 'granted';
    button.textContent = state.notificationsEnabled ? 'Browser alerts on' : 'Enable browser alerts';
    button.classList.toggle('enabled', state.notificationsEnabled);
  }

  async function loadBars() {
    document.getElementById('activeSymbol').textContent = state.symbol;
    document.getElementById('symbolInput').value = state.symbol;
    const res = await fetch(`/api/bars/${encodeURIComponent(state.symbol)}?timeframe=${encodeURIComponent(state.timeframe)}&limit=400`);
    if (!res.ok) throw new Error(await res.text() || `HTTP ${res.status}`);
    const data = await res.json();
    if (data.provider) setStatus('feedStatus', providerLabel(data.provider), data.provider === 'schwab' && !data.fallback);
    candles.setData(data.bars.map(b => ({ time: b.time, open: b.open, high: b.high, low: b.low, close: b.close })));
    volume.setData(data.bars.map(b => ({ time: b.time, value: b.volume, color: volumeColor(b) })));
    ema9Series.setData(ema(data.bars, 9));
    ema21Series.setData(ema(data.bars, 21));
    vwapSeries.setData(rthVwap(data.bars));
    if (data.bars.length) document.getElementById('lastPrice').textContent = `$${data.bars[data.bars.length - 1].close.toFixed(2)}`;
    const localAnalysis = analyzeBars(data.bars);
    const radarAnalysis = state.radar.get(state.symbol);
    state.currentAnalysis = radarAnalysis ? { ...localAnalysis, ...radarAnalysis, atr_abs: localAnalysis?.atr_abs } : localAnalysis;
    renderAnalysis(state.currentAnalysis);
    renderSetup(buildTechnicalPreview(data.bars, state.currentAnalysis));
    chart.timeScale().fitContent();
  }

  function renderRadarList(containerId, rows, side) {
    const container = document.getElementById(containerId);
    container.innerHTML = '';
    if (!rows.length) {
      container.innerHTML = '<div class="muted">No candidates passed the fast filter.</div>';
      return;
    }
    for (const row of rows) {
      state.radar.set(row.symbol, row);
      const button = document.createElement('button');
      button.className = `radar-row ${side}`;
      button.title = `Market data: ${providerLabel(row.provider)}`;
      button.innerHTML = `<span><strong>${row.symbol}</strong><br><small>${row.momentum_30m_pct}% · RVOL ${row.rvol}</small></span><span>$${Number(row.price).toFixed(2)}</span><span class="score">${row.score}</span>`;
      button.addEventListener('click', () => selectSymbol(row.symbol));
      container.appendChild(button);
    }
  }

  async function loadRadar() {
    const refreshButton = document.getElementById('refreshRadar');
    refreshButton.disabled = true;
    try {
      const res = await fetch('/api/radar?limit=8');
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);
      state.radar.clear();
      renderRadarList('longRadar', data.longs, 'long');
      renderRadarList('shortRadar', data.shorts, 'short');
      if (data.feed) setStatus('feedStatus', providerLabel(data.feed), data.feed === 'schwab');
      if (state.radar.has(state.symbol)) {
        const radar = state.radar.get(state.symbol);
        state.currentAnalysis = { ...(state.currentAnalysis || {}), ...radar };
        renderAnalysis(state.currentAnalysis);
      }
    } catch (err) {
      document.getElementById('longRadar').innerHTML = `<div class="muted">Radar unavailable: ${err.message}</div>`;
      document.getElementById('shortRadar').innerHTML = '';
    } finally {
      refreshButton.disabled = false;
    }
  }

  function connectSocket() {
    if (state.socket) { state.socket.onclose = null; state.socket.close(); }
    const scheme = location.protocol === 'https:' ? 'wss' : 'ws';
    const socket = new WebSocket(`${scheme}://${location.host}/ws/market/${encodeURIComponent(state.symbol)}`);
    state.socket = socket;
    socket.onmessage = event => {
      if (socket !== state.socket) return;
      const msg = JSON.parse(event.data);
      if (msg.symbol !== state.symbol) return;
      if (msg.provider) setStatus('feedStatus', providerLabel(msg.provider), msg.provider === 'schwab' && !msg.fallback);
      if (msg.quote) {
        const price = msg.quote.mid || msg.quote.ask || msg.quote.bid;
        if (price) document.getElementById('lastPrice').textContent = `$${Number(price).toFixed(2)}`;
        const spread = msg.quote.ask && msg.quote.bid ? msg.quote.ask - msg.quote.bid : 0;
        const stamp = msg.quote.timestamp ? new Date(msg.quote.timestamp).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit', timeZone: 'America/New_York' }) : '';
        document.getElementById('spreadText').textContent = `${spread ? `spread $${spread.toFixed(2)}` : 'live'}${stamp ? ` · ${stamp} ET` : ''}`;
      }
      if (msg.bar && state.timeframe === '1m') {
        candles.update({ time: msg.bar.time, open: msg.bar.open, high: msg.bar.high, low: msg.bar.low, close: msg.bar.close });
        volume.update({ time: msg.bar.time, value: msg.bar.volume, color: volumeColor(msg.bar) });
      }
    };
    socket.onclose = () => { if (socket === state.socket) setTimeout(connectSocket, 2500); };
  }

  async function selectSymbol(symbol) {
    state.symbol = String(symbol).trim().toUpperCase();
    connectSocket();
    try { await loadBars(); }
    catch (err) { document.getElementById('lastPrice').textContent = 'Load failed'; console.error(err); }
  }

  document.getElementById('symbolForm').addEventListener('submit', event => {
    event.preventDefault();
    selectSymbol(document.getElementById('symbolInput').value);
  });
  document.getElementById('timeframes').addEventListener('click', async event => {
    const button = event.target.closest('button[data-tf]');
    if (!button) return;
    state.timeframe = button.dataset.tf;
    document.querySelectorAll('#timeframes button').forEach(b => b.classList.toggle('active', b === button));
    await loadBars();
  });
  document.getElementById('refreshRadar').addEventListener('click', loadRadar);
  document.getElementById('enableAlerts').addEventListener('click', configureNotifications);

  if (typeof Notification !== 'undefined' && Notification.permission === 'granted') {
    state.notificationsEnabled = true;
    document.getElementById('enableAlerts').textContent = 'Browser alerts on';
    document.getElementById('enableAlerts').classList.add('enabled');
  }

  loadSystem();
  loadRadar();
  selectSymbol('SPY');
  setInterval(loadSystem, 30000);
  setInterval(loadRadar, 60000);
  // Schwab live quotes arrive through the websocket. Re-fetch candles every 15s
  // for every timeframe so 1-minute bars remain current without polling price
  // history every second.
  setInterval(() => loadBars().catch(() => {}), 15000);
})();
