(() => {
  function apply() {
    const params = new URLSearchParams(window.location.search);
    const symbol = String(params.get('symbol') || '').trim().toUpperCase();
    if (!/^[A-Z][A-Z0-9.\-]{0,9}$/.test(symbol)) return;
    const input = document.getElementById('symbolInput');
    const form = document.getElementById('symbolForm');
    if (!input || !form) return;
    input.value = symbol;
    form.requestSubmit();
    if (window.location.hash === '#trades') {
      setTimeout(() => document.getElementById('trades')?.scrollIntoView({ behavior: 'smooth', block: 'start' }), 150);
    }
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', () => setTimeout(apply, 50));
  else setTimeout(apply, 50);
})();
