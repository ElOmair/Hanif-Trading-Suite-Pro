(() => {
  const state = { symbol: null, score: null, loading: false };

  function number(value) {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
  }

  function ensurePanel() {
    let panel = document.getElementById('mntCalibrationPanel');
    if (panel) return panel;
    const coach = document.getElementById('mntBeginnerCoach');
    const card = document.querySelector('.analysis-card');
    const anchor = coach || card;
    if (!anchor) return null;
    panel = document.createElement('section');
    panel.id = 'mntCalibrationPanel';
    panel.className = 'mnt-calibration';
    panel.innerHTML = `
      <div class="mnt-calibration-head">
        <div><div class="eyebrow">MNT LEARNING HISTORY</div><h4>How has this score range behaved?</h4></div>
        <span id="mntCalibrationSamples" class="mnt-calibration-samples">NO HISTORY YET</span>
      </div>
      <div id="mntCalibrationBody" class="mnt-calibration-body">MnT will compare this setup with its own stored, later-graded signals after enough history accumulates.</div>
    `;
    anchor.insertAdjacentElement('afterend', panel);
    return panel;
  }

  function bucketKey(score) {
    const value = number(score);
    if (value == null) return null;
    const lower = Math.max(0, Math.min(100, Math.floor(value / 10) * 10));
    const upper = Math.min(100, lower + 9);
    return `${lower}-${upper}`;
  }

  function rate(value) {
    const n = number(value);
    return n == null ? '—' : `${n.toFixed(1)}%`;
  }

  function render(summary) {
    const panel = ensurePanel();
    if (!panel) return;
    const body = document.getElementById('mntCalibrationBody');
    const samples = document.getElementById('mntCalibrationSamples');
    const evaluated = Number(summary?.evaluated_count || 0);
    const key = bucketKey(state.score);
    const bucket = key ? summary?.score_buckets?.[key] : null;

    if (samples) samples.textContent = `${evaluated} GRADED SIGNAL${evaluated === 1 ? '' : 'S'}`;

    if (!evaluated) {
      body.innerHTML = '<strong>Learning mode:</strong> no completed signals have enough future data yet. MnT will start grading them automatically as 1-hour and 2-hour bars become available.';
      return;
    }

    if (!bucket || !bucket.count) {
      body.innerHTML = `<strong>History exists, but not for this score bucket yet.</strong> Current score is ${number(state.score)?.toFixed(0) || '—'}/100. MnT will not borrow statistics from a different score range just to make the panel look complete.`;
      return;
    }

    const count = Number(bucket.count || 0);
    const targetRate = rate(bucket.target_first_win_rate_pct);
    const followRate = rate(bucket.positive_2h_rate_pct);
    const sampleLabel = count < 10 ? 'VERY SMALL SAMPLE' : count < 30 ? 'SMALL SAMPLE' : count < 75 ? 'BUILDING SAMPLE' : 'LARGER SAMPLE';
    const caution = count < 30
      ? 'There are not enough observations to treat these percentages as stable. Use them only as descriptive history.'
      : 'These are descriptive historical results, not a forecast or guarantee for the current trade.';

    body.innerHTML = `
      <div class="mnt-calibration-grid">
        <div><span>Current bucket</span><strong>${key}</strong></div>
        <div><span>Sample</span><strong>${count}</strong></div>
        <div><span>Target before stop</span><strong>${targetRate}</strong></div>
        <div><span>Positive after 2h</span><strong>${followRate}</strong></div>
      </div>
      <div class="mnt-calibration-caution"><strong>${sampleLabel}:</strong> ${caution}</div>
    `;
  }

  async function load(symbol, score) {
    state.symbol = String(symbol || '').trim().toUpperCase();
    state.score = score;
    if (!state.symbol || state.loading) return;
    ensurePanel();
    state.loading = true;
    const body = document.getElementById('mntCalibrationBody');
    if (body) body.textContent = `Checking ${state.symbol} signal history…`;
    try {
      const response = await fetch(`/api/kronos/signals/calibration?symbol=${encodeURIComponent(state.symbol)}&limit=500`, {
        credentials: 'same-origin',
        headers: { Accept: 'application/json' },
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(payload.detail || `HTTP ${response.status}`);
      render(payload);
    } catch (error) {
      if (body) body.textContent = `Calibration history is unavailable right now: ${error.message || error}`;
    } finally {
      state.loading = false;
    }
  }

  window.addEventListener('mnt:fusion-result', event => {
    const data = event.detail || {};
    load(data.symbol, data.fusion_score?.score);
  });

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', ensurePanel);
  else ensurePanel();
})();
