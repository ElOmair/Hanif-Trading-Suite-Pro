(() => {
  const TAB_KEY = 'mnt.workspace.active.v1';
  const tabs = ['trade', 'market', 'focus', 'ideas', 'portfolio', 'learning'];
  const legacyHashTabs = {
    trades: 'trade',
    mntmyfocus: 'focus',
    mntopportunityshell: 'ideas',
    mntbrokerlive: 'portfolio',
    mntlearninglab: 'learning',
  };

  function normalize(name) {
    const value = String(name || '').toLowerCase();
    if (tabs.includes(value)) return value;
    return legacyHashTabs[value] || 'trade';
  }

  function moveDynamicShells() {
    const mounts = [
      ['mntMyFocus', 'mntFocusHost'],
      ['mntOpportunityShell', 'mntOpportunityHost'],
    ];
    for (const [shellId, hostId] of mounts) {
      const shell = document.getElementById(shellId);
      const host = document.getElementById(hostId);
      if (shell && host && shell.parentElement !== host) host.appendChild(shell);
    }
  }

  function openTab(name, options = {}) {
    moveDynamicShells();
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
    const rawHash = (location.hash || '').replace(/^#/, '').toLowerCase();
    if (tabs.includes(rawHash) || legacyHashTabs[rawHash]) return normalize(rawHash);
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
      return;
    }

    // Existing modules already know how to load their symbol. This layer only
    // makes sure the destination workspace is visible before their action completes.
    if (event.target.closest('.radar-row, [data-mnt-symbol], [data-underlying]')) {
      openTab('trade');
    }
  });

  document.addEventListener('submit', event => {
    if (event.target?.id === 'symbolForm') openTab('trade');
  });

  window.addEventListener('hashchange', () => {
    const raw = (location.hash || '').replace(/^#/, '').toLowerCase();
    if (tabs.includes(raw) || legacyHashTabs[raw]) openTab(normalize(raw), { hash: false });
  });

  document.addEventListener('keydown', event => {
    if (!event.altKey || event.ctrlKey || event.metaKey) return;
    const index = Number(event.key) - 1;
    if (!Number.isInteger(index) || index < 0 || index >= tabs.length) return;
    event.preventDefault();
    openTab(tabs[index]);
  });

  const init = () => {
    moveDynamicShells();
    const observer = new MutationObserver(moveDynamicShells);
    observer.observe(document.body, { childList: true, subtree: true });
    // Trade is visible in HTML so Lightweight Charts gets real startup dimensions.
    setTimeout(() => openTab(requestedInitialTab(), { hash: false }), 0);
  };

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
})();
