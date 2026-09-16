(() => {
  const state = { loading: false, loadedAt: 0 };

  const clamp = (value, min, max) => Math.max(min, Math.min(max, value));
  const fmtMoney = value => Number.isFinite(Number(value)) ? `$${Number(value).toFixed(2)}` : '—';
  const fmtPct = value => Number.isFinite(Number(value)) ? `${Number(value) >= 0 ? '+' : ''}${Number(value).toFixed(1)}%` : '—';

  function ema(values, span) {
    if (!Array.isArray(values) || !values.length) return null;
    const k = 2 / (span + 1);
    let result = Number(values[0]);
    for (let i = 1; i < values.length; i += 1) result = Number(values[i]) * k + result * (1 - k);
    return result;
  }

  function stdev(values) {
    if (!values.length) return 0;
    const mean = values.reduce((sum, value) => sum + value, 0) / values.length;
    const variance = values.reduce((sum, value) => sum + ((value - mean) ** 2), 0) / values.length;
    return Math.sqrt(variance);
  }

  function analyzeDaily(symbol, bars) {
    if (!Array.isArray(bars) || bars.length < 80) return null;
    const closes = bars.map(bar => Number(bar.close)).filter(Number.isFinite);
    const highs = bars.map(bar => Number(bar.high)).filter(Number.isFinite);
    if (closes.length < 80) return null;

    const last = closes[closes.length - 1];
    const ema20 = ema(closes.slice(-120), 20);
    const ema50 = ema(closes.slice(-180), 50);
    const ema200 = closes.length >= 200 ? ema(closes.slice(-260), 200) : null;
    const ret20 = closes.length > 20 ? (last / closes[closes.length - 21] - 1) * 100 : 0;
    const ret60 = closes.length > 60 ? (last / closes[closes.length - 61] - 1) * 100 : 0;
    const high252 = Math.max(...highs.slice(-Math.min(252, highs.length)));
    const fromHigh = high252 > 0 ? (last / high252 - 1) * 100 : 0;
    const returns = [];
    for (let i = Math.max(1, closes.length - 21); i < closes.length; i += 1) {
      returns.push(closes[i] / closes[i - 1] - 1);
    }
    const annualVol = stdev(returns) * Math.sqrt(252) * 100;

    let score = 50;
    if (ema20 && last > ema20) score += 9; else score -= 7;
    if (ema20 && ema50 && ema20 > ema50) score += 10; else score -= 6;
    if (ema50 && ema200) score += ema50 > ema200 ? 10 : -10;
    score += clamp(ret20 * 0.45, -9, 9);
    score += clamp(ret60 * 0.32, -13, 13);
    if (fromHigh <= -2 && fromHigh >= -12 && ema50 && last > ema50) score += 4;
    if (fromHigh < -20) score -= 7;
    score = clamp(score, 0, 100);

    const risk = annualVol < 30 ? 'Lower' : annualVol < 50 ? 'Medium' : 'Higher';
    const trend = ema20 && ema50 && last > ema20 && ema20 > ema50 ? 'Uptrend' : ema50 && last > ema50 ? 'Improving' : 'Weak';
    const watchLow = ema20 ? Math.min(last, ema20) * 0.985 : last * 0.97;
    const watchHigh = ema20 ? Math.max(last, ema20) * 1.01 : last * 1.01;

    let simpleWhy = 'The longer-term price trend is mixed, so patience matters.';
    if (score >= 82) simpleWhy = 'The stock has a strong multi-week uptrend and has held above important longer-term averages.';
    else if (score >= 72) simpleWhy = 'The larger trend is healthy, but MnT would rather see a good entry than chase a fast move.';
    else if (score >= 64) simpleWhy = 'The stock has some positive longer-term signs, but the setup is not strong enough to rush into.';

    return {
      symbol,
      price: last,
      score: Math.round(score),
      ret20,
      ret60,
      fromHigh,
      annualVol,
      risk,
      trend,
      ema20,
      ema50,
      ema200,
      watchLow,
      watchHigh,
      simpleWhy,
    };
  }

  async function getJson(url) {
    const res = await fetch(url, { credentials: 'same-origin', headers: { Accept: 'application/json' } });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);
    return data;
  }

  async function mapLimit(items, limit, worker) {
    const results = new Array(items.length);
    let next = 0;
    async function run() {
      while (next < items.length) {
        const index = next++;
        try { results[index] = await worker(items[index], index); }
        catch (error) { results[index] = { error, item: items[index] }; }
      }
    }
    await Promise.all(Array.from({ length: Math.min(limit, items.length) }, run));
    return results;
  }

  function ensureShell() {
    let shell = document.getElementById('mntOpportunityShell');
    if (shell) return shell;

    shell = document.createElement('section');
    shell.id = 'mntOpportunityShell';
    shell.className = 'mnt-opportunity-shell';
    shell.innerHTML = `
      <div class="mnt-opportunity-head">
        <div>
          <div class="eyebrow">MNT OPPORTUNITY DESK</div>
          <h2>Different ways to participate</h2>
          <p class="muted">MnT separates quick option ideas from multi-week swings and 3–4 month stock holds, then explains which approach fits the setup best.</p>
        </div>
        <button id="mntRefreshOpportunities" class="ghost-button mnt-refresh" type="button">Refresh ideas</button>
      </div>
      <div class="mnt-opportunity-grid">
        <section class="mnt-lane">
          <div class="mnt-lane-head"><h3>⚡ Fast trades</h3><p>Minutes to a few days. These are option setups worth watching, not automatic entries.</p></div>
          <div id="mntFastLane" class="mnt-lane-list"><div class="mnt-lane-empty">Loading short-term ideas…</div></div>
        </section>
        <section class="mnt-lane">
          <div class="mnt-lane-head"><h3>📈 Swing ideas</h3><p>Several days to several weeks. Timing matters, but the move does not need to happen today.</p></div>
          <div id="mntSwingLane" class="mnt-lane-list"><div class="mnt-lane-empty">Checking daily trends…</div></div>
        </section>
        <section class="mnt-lane">
          <div class="mnt-lane-head"><h3>🏦 3–4 month stock holds</h3><p>Share-based position ideas for moves that may need more time than an option gives them.</p></div>
          <div id="mntHoldLane" class="mnt-lane-list"><div class="mnt-lane-empty">Checking longer-term trends…</div></div>
        </section>
      </div>
      <div class="mnt-desk-note">Current v1 position scores use real Alpaca daily price/volume history. Fundamental quality, options flow and gamma are intentionally not guessed; those layers will only appear after real data feeds are connected.</div>
    `;

    const topbar = document.querySelector('.topbar');
    if (topbar?.parentNode) topbar.parentNode.insertBefore(shell, topbar.nextSibling);
    else document.body.prepend(shell);

    shell.querySelector('#mntRefreshOpportunities')?.addEventListener('click', () => load(true));
    shell.addEventListener('click', event => {
      const button = event.target.closest('[data-mnt-symbol]');
      if (!button) return;
      const symbol = button.getAttribute('data-mnt-symbol');
      const input = document.getElementById('symbolInput');
      const form = document.getElementById('symbolForm');
      if (input) input.value = symbol;
      if (form) form.requestSubmit();
      document.querySelector('.chart-panel')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    });
    return shell;
  }

  function fastCard(item) {
    const direction = String(item.direction || '').toUpperCase();
    const isLong = direction === 'LONG';
    const option = isLong ? 'Call option watch' : 'Put option watch';
    const action = Number(item.score) >= 86 && Number(item.rvol) >= 1.15
      ? `Get ready — ${option.toLowerCase()}, but wait for the full MnT setup to confirm.`
      : `Keep an eye on it — do not enter until the full setup confirms.`;
    const why = isLong
      ? 'Short-term buyers currently have the advantage.'
      : 'Short-term sellers currently have the advantage.';
    return `
      <article class="mnt-idea">
        <div class="mnt-idea-top"><div class="mnt-symbol"><strong>${item.symbol}</strong><span class="mnt-price">${fmtMoney(item.price)}</span></div><span class="mnt-score">${Math.round(Number(item.score) || 0)}/100</span></div>
        <div class="mnt-action">${action}</div>
        <p class="mnt-why">${why} MnT also sees ${Number(item.rvol) >= 1.2 ? 'stronger-than-normal trading activity' : 'normal trading activity'}, so timing still matters.</p>
        <div class="mnt-mini-grid">
          <div><span>Direction</span><strong>${isLong ? 'Higher' : 'Lower'}</strong></div>
          <div><span>Best fit</span><strong>${option}</strong></div>
          <div><span>Activity</span><strong>${Number(item.rvol || 0).toFixed(2)}× normal</strong></div>
          <div><span>Risk</span><strong>High / short-term</strong></div>
        </div>
        <button class="mnt-open-idea" type="button" data-mnt-symbol="${item.symbol}">Open ${item.symbol} and analyze</button>
      </article>`;
  }

  function swingCard(item) {
    const action = item.score >= 80
      ? 'Strong swing watch — look for a controlled pullback or a clean breakout before entering.'
      : 'Watch for a better entry — the bigger trend is positive, but there is no need to chase.';
    return `
      <article class="mnt-idea">
        <div class="mnt-idea-top"><div class="mnt-symbol"><strong>${item.symbol}</strong><span class="mnt-price">${fmtMoney(item.price)}</span></div><span class="mnt-score">${item.swingScore}/100</span></div>
        <div class="mnt-action">${action}</div>
        <p class="mnt-why">${item.simpleWhy} For a swing, MnT cares more about the multi-week trend than the next five-minute candle.</p>
        <div class="mnt-mini-grid">
          <div><span>1 month</span><strong>${fmtPct(item.ret20)}</strong></div>
          <div><span>3 months</span><strong>${fmtPct(item.ret60)}</strong></div>
          <div><span>Best fit</span><strong>Shares / 30–60D option watch</strong></div>
          <div><span>Risk</span><strong>${item.risk}</strong></div>
        </div>
        <button class="mnt-open-idea" type="button" data-mnt-symbol="${item.symbol}">Open ${item.symbol}</button>
      </article>`;
  }

  function holdCard(item) {
    const action = item.score >= 82
      ? 'Stock-hold candidate — this setup may be better suited to shares than a short-dated option.'
      : 'Stock watchlist candidate — wait for a better entry instead of forcing a trade.';
    return `
      <article class="mnt-idea">
        <div class="mnt-idea-top"><div class="mnt-symbol"><strong>${item.symbol}</strong><span class="mnt-price">${fmtMoney(item.price)}</span></div><span class="mnt-score">${item.score}/100</span></div>
        <div class="mnt-action">${action}</div>
        <p class="mnt-why">${item.simpleWhy}</p>
        <div class="mnt-mini-grid">
          <div><span>3 month move</span><strong>${fmtPct(item.ret60)}</strong></div>
          <div><span>Trend</span><strong>${item.trend}</strong></div>
          <div><span>Watch area</span><strong>${fmtMoney(item.watchLow)}–${fmtMoney(item.watchHigh)}</strong></div>
          <div><span>Risk</span><strong>${item.risk}</strong></div>
        </div>
        <button class="mnt-open-idea" type="button" data-mnt-symbol="${item.symbol}">Open ${item.symbol}</button>
      </article>`;
  }

  function renderList(id, items, renderer, emptyText) {
    const host = document.getElementById(id);
    if (!host) return;
    host.innerHTML = items.length ? items.map(renderer).join('') : `<div class="mnt-lane-empty">${emptyText}</div>`;
  }

  async function load(force = false) {
    ensureShell();
    if (state.loading) return;
    if (!force && Date.now() - state.loadedAt < 60000) return;
    state.loading = true;

    const refresh = document.getElementById('mntRefreshOpportunities');
    if (refresh) { refresh.disabled = true; refresh.textContent = 'Refreshing…'; }

    try {
      const radar = await getJson('/api/radar?limit=12');
      const longs = Array.isArray(radar.longs) ? radar.longs : [];
      const shorts = Array.isArray(radar.shorts) ? radar.shorts : [];
      const fast = [...longs.slice(0, 3), ...shorts.slice(0, 2)]
        .sort((a, b) => Number(b.rank_score || b.score || 0) - Number(a.rank_score || a.score || 0));
      renderList('mntFastLane', fast, fastCard, 'No strong short-term setup is standing out right now. Waiting is a valid trading decision.');

      const dailySymbols = [...new Set(longs.slice(0, 10).map(item => item.symbol))];
      const dailyResults = await mapLimit(dailySymbols, 3, async symbol => {
        const payload = await getJson(`/api/bars/${encodeURIComponent(symbol)}?timeframe=1d&limit=260`);
        return analyzeDaily(symbol, payload.bars || []);
      });
      const daily = dailyResults.filter(item => item && !item.error && Number.isFinite(item.score));

      const intradayBySymbol = new Map(longs.map(item => [item.symbol, item]));
      const swing = daily.map(item => {
        const intraday = intradayBySymbol.get(item.symbol) || {};
        return {
          ...item,
          swingScore: Math.round(clamp(item.score * 0.68 + Number(intraday.rank_score || intraday.score || 50) * 0.32, 0, 100)),
        };
      }).filter(item => item.swingScore >= 66).sort((a, b) => b.swingScore - a.swingScore).slice(0, 4);

      const holds = daily.filter(item => item.score >= 68 && item.ret60 > -4)
        .sort((a, b) => b.score - a.score)
        .slice(0, 4);

      renderList('mntSwingLane', swing, swingCard, 'No multi-week setup is strong enough yet. MnT will keep watching rather than manufacture a trade.');
      renderList('mntHoldLane', holds, holdCard, 'No 3–4 month stock candidate from today’s momentum list clears the current filter.');
      state.loadedAt = Date.now();
    } catch (error) {
      ['mntFastLane', 'mntSwingLane', 'mntHoldLane'].forEach(id => {
        const host = document.getElementById(id);
        if (host) host.innerHTML = `<div class="mnt-lane-empty">Could not refresh opportunities: ${error.message}</div>`;
      });
    } finally {
      state.loading = false;
      if (refresh) { refresh.disabled = false; refresh.textContent = 'Refresh ideas'; }
    }
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', () => load(true));
  else load(true);
})();
