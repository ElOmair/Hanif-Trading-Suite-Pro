(() => {
  const TAB_KEY = 'mnt.workspace.active.v1';
  const tabs = ['trade', 'market', 'focus', 'ideas', 'portfolio', 'learning'];

  function normalize(name) {
    const value = String(name || '').toLowerCase();
    return tabs.includes(value) ? value : 'trade';
  }

  function openTab(name, options = {}) {
    const target = normalize(name);
    document.querySelectorAll('[data-mnt-panel]').forEach(panel => {
      const active = panel.dataset.mntPanel === target;
      panel.classList.toggle('is-active', active);
      panel.hidden = !active;
    });
    document.querySelectorAll('[data-mnt-tab]').forEach(button => {
      const active = button.dataset.mntTab === target;
      button.classList.toggle('active', active);
      button.setAttribute('aria-selected', active ? 'true' : 'false');
      button.tabIndex = active ? 0 : -1;
    });

    try { localStorage.setItem(TAB_KEY, target); } catch (_) {}
    if (options.hash !== false && location.hash !== `#${target}`) {
      history.replaceState(null, '', `#${target}`);
    }

    if (target === 'trade') {
      requestAnimationFrame(() => {
        window.dispatchEvent(new Event('resize'));
        setTimeout(() => window.dispatchEvent(new Event('resize')), 120);
      });
    }
    window.dispatchEvent(new CustomEvent('mnt:workspace-changed', { detail: { tab: target } }));
    return target;
  }

  function requestedInitialTab() {
    const hash = normalize((location.hash || '').replace(/^#/, ''));
    if (location.hash && tabs.includes((location.hash || '').replace(/^#/, '').toLowerCase())) return hash;
    try {
      const saved = localStorage.getItem(TAB_KEY);
      if (saved && tabs.includes(saved)) return saved;
    } catch (_) {}
    return 'trade';
  }

  function openCurrentTrade(runAnalysis = false) {
    openTab('trade');
    if (runAnalysis) {
      setTimeout(() => document.getElementById('runFusion')?.click(), 180);
    }
  }

  window.MnTWorkspace = {
    openTab,
    openTrade: openCurrentTrade,
    activeTab: () => document.querySelector('[data-mnt-panel].is-active')?.dataset.mntPanel || 'trade',
  };

  document.addEventListener('click', event => {
    const tab = event.target.closest('[data-mnt-tab]');
    if (tab) {
      event.preventDefault();
      openTab(tab.dataset.mntTab);
      return;
    }
    const jump = event.target.closest('[data-mnt-open-tab]');
    if (jump) {
      event.preventDefault();
      openTab(jump.dataset.mntOpenTab);
      return;
    }
    const analyze = event.target.closest('[data-mnt-analyze-current]');
    if (analyze) {
      event.preventDefault();
      openCurrentTrade(true);
    }
  });

  window.addEventListener('hashchange', () => {
    const raw = (location.hash || '').replace(/^#/, '').toLowerCase();
    if (tabs.includes(raw)) openTab(raw, { hash: false });
  });

  document.addEventListener('keydown', event => {
    if (!event.altKey || event.ctrlKey || event.metaKey) return;
    const index = Number(event.key) - 1;
    if (!Number.isInteger(index) || index < 0 || index >= tabs.length) return;
    event.preventDefault();
    openTab(tabs[index]);
  });

  // Trade is visible in the HTML by default so Lightweight Charts can initialize
  // with real dimensions. Restore the user's last workspace after startup.
  const init = () => setTimeout(() => openTab(requestedInitialTab(), { hash: false }), 0);
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
})();
