/* Settings page — IBKR sync + snapshot rebuild management */
(function () {
  var snapshotRebuildPollTimer = null;
  var lastSnapshotRebuildStatus = null;
  var hasLoadedIBKRPanel = false;
  var hasLoadedSnapshotPanel = false;

  function applyIBKRConfig(config) {
    var queryId = document.getElementById('settings-flex-query-id');
    var expiresAt = document.getElementById('settings-token-expires-at');
    var enabled = document.getElementById('settings-ibkr-enabled');
    var importedTo = document.getElementById('settings-ibkr-last-import');
    if (queryId) queryId.value = config.flex_query_id || '';
    if (expiresAt) expiresAt.value = config.token_expires_at || '';
    if (enabled) enabled.checked = !!config.is_enabled;
    if (importedTo) {
      importedTo.textContent = config.last_imported_to_display || '尚未导入';
    }
  }

  function applyIBKRSyncStatus(status) {
    var btn = document.getElementById('btn-settings-sync-ibkr');
    var lastSync = document.getElementById('settings-ibkr-last-sync');
    if (!btn || !lastSync || !status) return;
    btn.disabled = !status.can_manual_sync;
    lastSync.textContent = status.last_synced_at_display || '尚未同步';

    var tokenExpiry = document.getElementById('settings-ibkr-token-expiry');
    if (tokenExpiry) {
      tokenExpiry.textContent = status.token_expires_at_display || '未设置';
      tokenExpiry.classList.toggle('negative', !!status.token_is_expired);
    }
  }

  function fetchIBKRPanel() {
    fetch('/api/settings/ibkr-panel', { credentials: 'same-origin' })
      .then(function (r) {
        if (!r.ok) throw new Error('ibkr panel failed');
        return r.json();
      })
      .then(function (data) {
        applyIBKRConfig(data.ibkr_config || {});
        applyIBKRSyncStatus(data.ibkr_status || {});
        hasLoadedIBKRPanel = true;
      })
      .catch(function () {});
  }

  function applySnapshotRebuildStatus(status, options) {
    options = options || {};
    var btn = document.getElementById('btn-rebuild-snapshots');
    var copy = document.getElementById('snapshot-rebuild-copy');
    var spinner = document.getElementById('snapshot-rebuild-spinner');
    var completed = document.getElementById('snapshot-rebuild-last-completed');
    var block = document.getElementById('settings-snapshots');
    var previousStatus = lastSnapshotRebuildStatus;
    if (!btn || !copy || !spinner || !completed || !block || !status) return;

    block.dataset.status = status.status || 'IDLE';
    block.dataset.isRunning = status.is_running ? 'true' : 'false';
    btn.disabled = !!status.is_running;
    spinner.hidden = !status.is_running;
    completed.textContent = status.last_completed_at_display || '尚未执行';

    if (status.is_running) {
      copy.textContent = '正在回填：' + (status.refresh_from || '等待开始');
      startSnapshotRebuildPolling();
    } else {
      copy.textContent = status.message || '等待操作';
      stopSnapshotRebuildPolling();
    }

    if (
      options.notifyCompletion &&
      previousStatus &&
      previousStatus.is_running &&
      !status.is_running
    ) {
      if (status.status === 'SUCCEEDED') {
        alert(status.message || '历史快照回填完成');
      } else if (status.status === 'FAILED') {
        alert(status.message || '历史快照回填失败');
      }
    }

    lastSnapshotRebuildStatus = status;
  }

  function pollSnapshotRebuildStatus(options) {
    fetch('/api/snapshots/rebuild-status', { credentials: 'same-origin' })
      .then(function (r) {
        if (!r.ok) throw new Error('status failed');
        return r.json();
      })
      .then(function (status) {
        applySnapshotRebuildStatus(status, options);
        hasLoadedSnapshotPanel = true;
      })
      .catch(function () {});
  }

  function startSnapshotRebuildPolling() {
    if (snapshotRebuildPollTimer) return;
    snapshotRebuildPollTimer = window.setInterval(function () {
      pollSnapshotRebuildStatus({ notifyCompletion: true });
    }, 3000);
  }

  function stopSnapshotRebuildPolling() {
    if (!snapshotRebuildPollTimer) return;
    window.clearInterval(snapshotRebuildPollTimer);
    snapshotRebuildPollTimer = null;
  }

  window.syncIBKRFromSettings = function () {
    var btn = document.getElementById('btn-settings-sync-ibkr');
    if (!btn || btn.disabled) return;
    var originalText = btn.textContent;
    btn.disabled = true;
    btn.textContent = '同步中...';
    fetch('/api/ibkr/sync', {
      method: 'POST',
      credentials: 'same-origin'
    })
      .then(function (r) {
        return r.json().then(function (data) {
        return { ok: r.ok, data: data };
      });
    })
      .then(function (res) {
        if (!res.ok) throw new Error(res.data.error || '同步失败');
        fetchIBKRPanel();
        if (res.data && res.data.skipped && res.data.reason === 'cooldown') return;
        alert('IBKR 同步完成');
      })
      .catch(function (err) {
        alert(err.message || '同步失败');
      })
      .finally(function () {
        btn.textContent = originalText;
        fetchIBKRPanel();
      });
  };

  window.rebuildSnapshotsFromSettings = function () {
    var btn = document.getElementById('btn-rebuild-snapshots');
    if (!btn || btn.disabled) return;
    btn.disabled = true;
    fetch('/api/snapshots/rebuild', {
      method: 'POST',
      credentials: 'same-origin'
    })
      .then(function (r) {
        return r.json().then(function (data) {
          return { ok: r.ok, data: data };
        });
      })
      .then(function (res) {
        if (!res.ok) throw new Error((res.data && res.data.error) || '启动失败');
        applySnapshotRebuildStatus(res.data.status || {}, { notifyCompletion: false });
        pollSnapshotRebuildStatus({ notifyCompletion: false });
      })
      .catch(function (err) {
        alert(err.message || '启动失败');
        btn.disabled = false;
      });
  };

  window.saveIBKRSettings = function (e) {
    e.preventDefault();
    var btn = document.getElementById('btn-save-ibkr-settings');
    var queryId = document.getElementById('settings-flex-query-id');
    var token = document.getElementById('settings-flex-token');
    var expiresAt = document.getElementById('settings-token-expires-at');
    var enabled = document.getElementById('settings-ibkr-enabled');
    if (!btn || !queryId || !expiresAt || !enabled) return;

    btn.disabled = true;
    fetch('/api/ibkr/config', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'same-origin',
      body: JSON.stringify({
        flex_query_id: queryId.value || '',
        flex_token: token ? token.value : '',
        token_expires_at: expiresAt.value || null,
        is_enabled: enabled.checked
      })
    })
      .then(function (r) {
        return r.json().then(function (data) {
        return { ok: r.ok, data: data };
      });
    })
      .then(function (res) {
        if (!res.ok) throw new Error(res.data.error || '保存失败');
        if (token) token.value = '';
        fetchIBKRPanel();
        alert('IBKR 设置已保存');
      })
      .catch(function (err) {
        alert(err.message || '保存失败');
      })
      .finally(function () {
        btn.disabled = false;
      });
  };

  function togglePanel(panelName) {
    var toggle = document.querySelector('[data-settings-panel-toggle="' + panelName + '"]');
    var body = document.getElementById('settings-panel-body-' + panelName);
    if (!toggle || !body) return;

    var isExpanded = toggle.getAttribute('aria-expanded') === 'true';
    toggle.setAttribute('aria-expanded', isExpanded ? 'false' : 'true');
    body.hidden = isExpanded;

    if (!isExpanded) {
      if (panelName === 'ibkr' && !hasLoadedIBKRPanel) {
        fetchIBKRPanel();
      }
      if (panelName === 'snapshots' && !hasLoadedSnapshotPanel) {
        pollSnapshotRebuildStatus({ notifyCompletion: false });
      }
    } else if (panelName === 'snapshots') {
      stopSnapshotRebuildPolling();
    }
  }

  document.addEventListener('DOMContentLoaded', function () {
    document
      .querySelectorAll('[data-settings-panel-toggle]')
      .forEach(function (toggle) {
        toggle.addEventListener('click', function () {
          togglePanel(toggle.getAttribute('data-settings-panel-toggle'));
        });
      });
  });
})();
