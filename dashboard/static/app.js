(() => {
  const state = { symbol: 'SPY', timeframe: '5m', socket: null, radar: new Map() };

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

  function setStatus(id, text, ok) {
    const el = document.getElementById(id);
    el.textContent = text;
    el.classList.remove('ok', 'bad');
    if (ok === true) el.classList.add('ok');
    if (ok === false) el.classList.add('bad');
  }

  async function loadSystem() {
    try {
      const res = await fetch('/api/system');
      const data = await res.json();
      setStatus('alpacaStatus', data.alpaca.configured ? 'Alpaca online' : 'Alpaca missing', data.alpaca.configured);
      setStatus('kronosStatus', data.kronos.online ? 'Kronos online' : 'Kronos offline', data.kronos.online);
      setStatus('feedStatus', `${String(data.alpaca.feed).toUpperCase()} feed`, true);
      document.getElementById('kronosAnalysisState').textContent = data.kronos.online ? 'Online' : 'Offline';
    } catch (_) {
      setStatus('alpacaStatus', 'Dashboard API offline', false);
      setStatus('kronosStatus', 'Kronos unknown', false);
    }
  }

  function volumeColor(bar) {
    return bar.close >= bar.open ? 'rgba(55,214,148,.45)' : 'rgba(255,107,120,.45)';
  }

  async function loadBars() {
    document.getElementById('activeSymbol').textContent = state.symbol;
    document.getElementById('symbolInput').value = state.symbol;
    const res = await fetch(`/api/bars/${encodeURIComponent(state.symbol)}?timeframe=${encodeURIComponent(state.timeframe)}&limit=400`);
    if (!res.ok) throw new Error(await res.text() || `HTTP ${res.status}`);
    const data = await res.json();
    candles.setData(data.bars.map(b => ({ time: b.time, open: b.open, high: b.high, low: b.low, close: b.close })));
    volume.setData(data.bars.map(b => ({ time: b.time, value: b.volume, color: volumeColor(b) })));
    if (data.bars.length) document.getElementById('lastPrice').textContent = `$${data.bars[data.bars.length - 1].close.toFixed(2)}`;
    chart.timeScale().fitContent();
    renderAnalysis(state.radar.get(state.symbol));
  }

  function renderAnalysis(item) {
    const values = item || {};
    document.getElementById('technicalScore').textContent = values.score ?? '—';
    document.getElementById('direction').textContent = values.direction ?? '—';
    document.getElementById('momentum').textContent = values.momentum_30m_pct == null ? '—' : `${values.momentum_30m_pct}%`;
    document.getElementById('rvol').textContent = values.rvol ?? '—';
    document.getElementById('atrPct').textContent = values.atr_pct == null ? '—' : `${values.atr_pct}%`;
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
      renderRadarList('longRadar', data.longs, 'long');
      renderRadarList('shortRadar', data.shorts, 'short');
      renderAnalysis(state.radar.get(state.symbol));
    } catch (err) {
      document.getElementById('longRadar').innerHTML = `<div class="muted">Radar unavailable: ${err.message}</div>`;
      document.getElementById('shortRadar').innerHTML = '';
    } finally {
      refreshButton.disabled = false;
    }
  }

  function connectSocket() {
    if (state.socket) {
      state.socket.onclose = null;
      state.socket.close();
    }
    const scheme = location.protocol === 'https:' ? 'wss' : 'ws';
    const socket = new WebSocket(`${scheme}://${location.host}/ws/market/${encodeURIComponent(state.symbol)}`);
    state.socket = socket;
    socket.onmessage = event => {
      if (socket !== state.socket) return;
      const msg = JSON.parse(event.data);
      if (msg.symbol !== state.symbol) return;
      if (msg.quote) {
        const price = msg.quote.mid || msg.quote.ask || msg.quote.bid;
        if (price) document.getElementById('lastPrice').textContent = `$${Number(price).toFixed(2)}`;
        const spread = msg.quote.ask && msg.quote.bid ? msg.quote.ask - msg.quote.bid : 0;
        document.getElementById('spreadText').textContent = spread ? `spread $${spread.toFixed(2)}` : 'live';
      }
      if (msg.bar && state.timeframe === '1m') {
        candles.update({ time: msg.bar.time, open: msg.bar.open, high: msg.bar.high, low: msg.bar.low, close: msg.bar.close });
        volume.update({ time: msg.bar.time, value: msg.bar.volume, color: volumeColor(msg.bar) });
      }
    };
    socket.onclose = () => {
      if (socket !== state.socket) return;
      setTimeout(connectSocket, 2500);
    };
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
  loadSystem();
  loadRadar();
  selectSymbol('SPY');
  setInterval(loadSystem, 30000);
  setInterval(loadRadar, 60000);
  setInterval(() => { if (state.timeframe !== '1m') loadBars().catch(() => {}); }, 15000);
})();
