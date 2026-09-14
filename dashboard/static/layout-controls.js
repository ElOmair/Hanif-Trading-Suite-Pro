(() => {
  const chartEl = document.getElementById('chart');
  const smaller = document.getElementById('chartSmaller');
  const larger = document.getElementById('chartLarger');
  const focus = document.getElementById('chartFocus');
  const reset = document.getElementById('chartReset');
  if (!chartEl || !smaller || !larger || !focus || !reset) return;

  const KEY = 'hanif-dashboard-chart-height';
  const clamp = value => Math.max(420, Math.min(900, Math.round(value)));

  function setHeight(value, persist = true) {
    if (document.body.classList.contains('chart-focus')) return;
    const height = clamp(Number(value) || 590);
    chartEl.style.height = `${height}px`;
    if (persist) localStorage.setItem(KEY, String(height));
  }

  const saved = Number(localStorage.getItem(KEY));
  if (Number.isFinite(saved) && saved >= 420 && saved <= 900) setHeight(saved, false);

  smaller.addEventListener('click', () => setHeight(chartEl.getBoundingClientRect().height - 80));
  larger.addEventListener('click', () => setHeight(chartEl.getBoundingClientRect().height + 80));
  reset.addEventListener('click', () => setHeight(590));

  focus.addEventListener('click', () => {
    const active = document.body.classList.toggle('chart-focus');
    focus.textContent = active ? 'Exit focus' : 'Focus chart';
    focus.classList.toggle('active', active);
    setTimeout(() => window.dispatchEvent(new Event('resize')), 50);
  });

  let resizeTimer = null;
  const observer = new ResizeObserver(entries => {
    if (document.body.classList.contains('chart-focus')) return;
    const height = entries[0]?.contentRect?.height;
    if (!height || height < 420 || height > 900) return;
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(() => localStorage.setItem(KEY, String(Math.round(height))), 250);
  });
  observer.observe(chartEl);
})();
