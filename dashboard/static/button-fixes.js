(() => {
  const refreshButton = document.getElementById('refreshRadar');
  const alertsButton = document.getElementById('enableAlerts');

  function temporaryText(button, text, restore, ms = 1400) {
    if (!button) return;
    button.textContent = text;
    window.setTimeout(() => {
      if (button.textContent === text) button.textContent = restore;
    }, ms);
  }

  if (refreshButton) {
    refreshButton.addEventListener('click', () => {
      const original = 'Refresh';
      refreshButton.textContent = 'Refreshing…';
      window.setTimeout(() => {
        const now = new Date().toLocaleTimeString([], {
          hour: 'numeric', minute: '2-digit', second: '2-digit', timeZone: 'America/New_York'
        });
        refreshButton.textContent = `Updated ${now}`;
        window.setTimeout(() => { refreshButton.textContent = original; }, 1800);
      }, 250);
    }, true);
  }

  if (alertsButton) {
    alertsButton.addEventListener('click', async () => {
      if (!window.isSecureContext) {
        alertsButton.textContent = 'Alerts require HTTPS';
        return;
      }
      if (typeof Notification === 'undefined') {
        alertsButton.textContent = 'Browser alerts unavailable';
        alertsButton.disabled = true;
        return;
      }

      try {
        if (Notification.permission === 'denied') {
          alertsButton.textContent = 'Alerts blocked — allow in browser';
          return;
        }

        const permission = Notification.permission === 'granted'
          ? 'granted'
          : await Notification.requestPermission();

        if (permission === 'granted') {
          alertsButton.textContent = 'Browser alerts on';
          alertsButton.classList.add('enabled');
          try {
            new Notification("Hanif's Trading Suite", {
              body: 'Browser alerts are enabled. Entry, no-chase, and position-state alerts can appear here.'
            });
          } catch (_) {}
        } else {
          alertsButton.textContent = 'Enable browser alerts';
        }
      } catch (err) {
        console.error('Notification setup failed', err);
        temporaryText(alertsButton, 'Alert setup failed', 'Enable browser alerts', 2500);
      }
    }, true);
  }
})();
