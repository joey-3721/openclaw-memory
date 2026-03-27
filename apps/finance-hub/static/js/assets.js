/* Assets page — add asset, transactions, ticker validation */
(function () {
  var tickerTimer = null;
  var snapshotRebuildPollTimer = null;
  var lastSnapshotRebuildStatus = null;
  var ASSETS_CONTENT_CACHE_KEY = 'financeHub.assets.liveContent.v3';
  var IBKR_SYNC_CACHE_KEY = 'financeHub.assets.ibkrSyncStatus.v1';
  var SNAPSHOT_REBUILD_CACHE_KEY = 'financeHub.assets.snapshotRebuildStatus.v1';
  var ASSET_SUMMARY_EXPANDED_KEY = 'financeHub.assets.summaryExpanded.v1';
  var ASSET_EXPANDED_IDS_KEY = 'financeHub.assets.expandedIds.v1';
  var LOCAL_CACHE_MAX_AGE_MS = 24 * 60 * 60 * 1000;
  var LOCAL_CACHE_REFRESH_AFTER_MS = 60 * 1000;

  function readCache(key) {
    try {
      var raw = window.localStorage.getItem(key);
      return raw ? JSON.parse(raw) : null;
    } catch (e) {
      return null;
    }
  }

  function writeCache(key, value) {
    try {
      window.localStorage.setItem(key, JSON.stringify(value));
    } catch (e) {}
  }

  function clearCache(key) {
    try {
      window.localStorage.removeItem(key);
    } catch (e) {}
  }

  function readExpandedAssetIds() {
    var cached = readCache(ASSET_EXPANDED_IDS_KEY);
    if (!cached || !Array.isArray(cached.value)) return [];
    return cached.value
      .map(function (id) { return String(id); })
      .filter(Boolean);
  }

  function writeExpandedAssetIds(ids) {
    writeCache(ASSET_EXPANDED_IDS_KEY, {
      value: ids.map(function (id) { return String(id); }),
      savedAt: Date.now()
    });
  }

  function getExpandedAssetIdsFromDom() {
    return Array.prototype.slice.call(
      document.querySelectorAll('.asset-detail[id^="detail-"]')
    )
      .filter(function (el) { return el.style.display !== 'none'; })
      .map(function (el) { return el.id.replace('detail-', ''); });
  }

  function restoreExpandedAssetDetails() {
    var expandedIds = readExpandedAssetIds();
    if (!expandedIds.length) return;
    expandedIds.forEach(function (id) {
      var el = document.getElementById('detail-' + id);
      if (el) {
        el.style.display = '';
      }
    });
  }

  function applyAssetSummaryExpanded(isExpanded) {
    var more = document.getElementById('asset-summary-more');
    var btn = document.getElementById('asset-summary-toggle');
    if (!more || !btn) return;
    more.hidden = !isExpanded;
    btn.setAttribute('aria-expanded', isExpanded ? 'true' : 'false');
    btn.classList.toggle('is-expanded', !!isExpanded);
    var label = btn.querySelector('span');
    if (label) {
      label.textContent = isExpanded ? '收起更多指标' : '查看更多指标';
    }
  }

  function initAssetSummaryToggle() {
    var cached = readCache(ASSET_SUMMARY_EXPANDED_KEY);
    applyAssetSummaryExpanded(!!(cached && cached.value));
  }

  window.toggleAssetSummaryMore = function () {
    var btn = document.getElementById('asset-summary-toggle');
    var expanded = btn && btn.getAttribute('aria-expanded') === 'true';
    var next = !expanded;
    applyAssetSummaryExpanded(next);
    writeCache(ASSET_SUMMARY_EXPANDED_KEY, {
      value: next,
      savedAt: Date.now()
    });
  };

  function afterAssetMutation() {
    clearCache(ASSETS_CONTENT_CACHE_KEY);
    pollSnapshotRebuildStatus({ notifyCompletion: false });
    refreshAssetsPageContent();
  }

  /* ── Modal helpers ───────────────────────────── */
  window.openAddAssetModal = function () {
    document.getElementById('add-asset-form').reset();
    onAssetTypeChange();
    showModal('add-asset-modal');
  };

  window.closeModal = function (id) {
    document.getElementById(id).style.display = 'none';
  };

  window.closeModalOnOverlay = function (e) {
    if (e.target.classList.contains('modal-overlay')) {
      e.target.style.display = 'none';
    }
  };

  function showModal(id) {
    document.getElementById(id).style.display = 'flex';
  }

  /* ── Asset type change ───────────────────────── */
  window.onAssetTypeChange = function () {
    var type = document.getElementById('asset-type-select').value;
    var tickerGroup = document.getElementById('ticker-group');
    var priceGroup = document.getElementById('price-group');
    var qtyLabel = document.getElementById('quantity-label');
    var dateLabel = document.getElementById('date-label');

    if (type === 'STOCK') {
      tickerGroup.style.display = '';
      priceGroup.style.display = '';
      qtyLabel.textContent = '股数';
    } else if (type === 'BOND') {
      tickerGroup.style.display = 'none';
      priceGroup.style.display = '';
      qtyLabel.textContent = '份数';
    } else if (type === 'CASH') {
      tickerGroup.style.display = 'none';
      priceGroup.style.display = 'none';
      qtyLabel.textContent = '金额 (USD)';
    } else {
      tickerGroup.style.display = 'none';
      priceGroup.style.display = '';
      qtyLabel.textContent = '数量';
    }
  };

  /* ── Ticker validation (debounced) ───────────── */
  window.onTickerInput = function (val) {
    clearTimeout(tickerTimer);
    var status = document.getElementById('ticker-status');
    var nameInput = document.getElementById('asset-name-input');
    val = val.trim().toUpperCase();
    if (val.length < 1) { status.textContent = ''; return; }
    status.textContent = '验证中...';
    status.className = 'input-status';
    tickerTimer = setTimeout(function () {
      fetch('/api/stock/validate/' + encodeURIComponent(val))
        .then(function (r) { return r.json(); })
        .then(function (d) {
          if (d.valid) {
            status.textContent = d.name || '有效';
            status.className = 'input-status valid';
            if (!nameInput.value) nameInput.value = d.name || val;
          } else {
            status.textContent = '无效代码';
            status.className = 'input-status invalid';
          }
        })
        .catch(function () {
          status.textContent = '验证失败';
          status.className = 'input-status invalid';
        });
    }, 600);
  };

  /* ── Submit new asset ────────────────────────── */
  window.submitAsset = function (e) {
    e.preventDefault();
    var form = document.getElementById('add-asset-form');
    var fd = new FormData(form);
    var body = {
      asset_type_code: fd.get('asset_type_code'),
      ticker_symbol: fd.get('ticker_symbol') || null,
      asset_name: fd.get('asset_name'),
      quantity: fd.get('quantity'),
      price_per_unit: fd.get('price_per_unit') || null,
      buy_date: fd.get('buy_date'),
      note: fd.get('note') || null
    };
    var btn = document.getElementById('submit-asset-btn');
    btn.disabled = true;
    btn.textContent = '提交中...';
    fetch('/api/assets', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body)
    })
      .then(function (r) { return r.json().then(function (d) { return { ok: r.ok, data: d }; }); })
      .then(function (res) {
        if (res.ok) {
          closeModal('add-asset-modal');
          afterAssetMutation();
        } else {
          alert(res.data.error || '添加失败');
        }
      })
      .catch(function () { alert('网络错误'); })
      .finally(function () { btn.disabled = false; btn.textContent = '确认添加'; });
  };

  /* ── Toggle asset detail ─────────────────────── */
  window.toggleAssetDetail = function (id) {
    var el = document.getElementById('detail-' + id);
    if (!el) return;
    el.style.display = el.style.display === 'none' ? '' : 'none';
    writeExpandedAssetIds(getExpandedAssetIdsFromDom());
  };

  /* ── Transaction modal ───────────────────────── */
  window.openTransactionModal = function (assetId, direction) {
    document.getElementById('tx-asset-id').value = assetId;
    document.getElementById('tx-direction').value = direction;
    document.getElementById('tx-modal-title').textContent = direction === 'BUY' ? '买入' : '卖出';
    document.getElementById('transaction-form').reset();
    document.getElementById('tx-asset-id').value = assetId;
    document.getElementById('tx-direction').value = direction;
    showModal('transaction-modal');
  };

  window.submitTransaction = function (e) {
    e.preventDefault();
    var form = document.getElementById('transaction-form');
    var fd = new FormData(form);
    var assetId = fd.get('asset_id');
    var body = {
      direction: fd.get('direction'),
      quantity: fd.get('quantity'),
      price_per_unit: fd.get('price_per_unit') || null,
      transaction_date: fd.get('transaction_date'),
      fee: fd.get('fee') || '0',
      note: fd.get('note') || null
    };
    var btn = document.getElementById('submit-tx-btn');
    btn.disabled = true;
    fetch('/api/assets/' + assetId + '/transactions', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body)
    })
      .then(function (r) { return r.json().then(function (d) { return { ok: r.ok, data: d }; }); })
      .then(function (res) {
        if (res.ok) {
          closeModal('transaction-modal');
          afterAssetMutation();
        } else {
          alert(res.data.error || '操作失败');
        }
      })
      .catch(function () { alert('网络错误'); })
      .finally(function () { btn.disabled = false; });
  };

  window.saveInterest = function (assetId) {
    var amountInput = document.getElementById('interest-amount-input-' + assetId);
    var dateInput = document.getElementById('interest-date-input-' + assetId);
    var amount = amountInput ? (amountInput.value || '').trim() : '';
    var flowDate = dateInput ? dateInput.value : '';
    if (!amount) {
      alert('请输入利息金额');
      return;
    }
    fetch('/api/assets/' + assetId + '/interest', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        amount: amount,
        flow_date: flowDate || null
      })
    })
      .then(function (r) { return r.json().then(function (d) { return { ok: r.ok, data: d }; }); })
      .then(function (res) {
        if (!res.ok) {
          alert(res.data.error || '保存失败');
          return;
        }
        afterAssetMutation();
      })
      .catch(function () { alert('网络错误'); });
  };
  /* ── Load transactions ────────────────────────── */
  window.loadTransactions = function (assetId) {
    var container = document.getElementById('tx-list-' + assetId);
    container.innerHTML = '<span class="text-soft">加载中...</span>';
    fetch('/api/assets/' + assetId + '/transactions', { credentials: 'same-origin' })
      .then(function (r) {
        // If the asset isn't found / not accessible, treat it as "no transactions"
        // instead of showing an unfriendly "加载失败".
        if (!r.ok) {
          if (r.status === 404) {
            container.innerHTML = '<span class="text-soft">暂无交易记录</span>';
            return null;
          }
          if (r.status === 401) {
            container.innerHTML = '<span class="text-soft">请先登录</span>';
            return null;
          }
          throw new Error('HTTP ' + r.status);
        }
        // If the server redirected to login or another page, don't try to parse JSON.
        if (r.redirected) {
          container.innerHTML = '<span class="text-soft">请先登录</span>';
          return null;
        }
        return r.json();
      })
      .then(function (d) {
        if (!d) return;
        if (!Array.isArray(d.transactions)) {
          // Unexpected payload; don't silently treat it as empty.
          throw new Error('Invalid response payload');
        }
        var txs = d.transactions;
        if (!txs.length) {
          container.innerHTML = '<span class="text-soft">暂无交易记录</span>';
          return;
        }
        var html = '<table class="mini-table"><thead><tr><th>日期</th><th>方向</th><th>来源</th><th>数量</th><th>单价</th><th>总额</th></tr></thead><tbody>';
        txs.forEach(function (tx) {
          var sourceLabel = tx.source_system === 'IBKR'
            ? '<span class="record-badge record-badge-auto">自动</span>'
            : '<span class="record-badge record-badge-manual">手动</span>';
          html += '<tr>'
            + '<td>' + (tx.transaction_date || '') + '</td>'
            + '<td class="' + (tx.direction === 'BUY' ? 'positive' : 'negative') + '">' + (tx.direction === 'BUY' ? '买入' : '卖出') + '</td>'
            + '<td>' + sourceLabel + '</td>'
            + '<td>' + tx.quantity + '</td>'
            + '<td>' + (tx.price_per_unit != null ? '$' + tx.price_per_unit : '-') + '</td>'
            + '<td>$' + tx.total_amount + '</td>'
            + '</tr>';
        });
        html += '</tbody></table>';
        container.innerHTML = html;
      })
      .catch(function () { container.innerHTML = '<span class="text-soft">加载失败</span>'; });
  };

  window.loadCashFlows = function (assetId) {
    var container = document.getElementById('tx-list-' + assetId);
    container.innerHTML = '<span class="text-soft">加载中...</span>';
    fetch('/api/assets/' + assetId + '/cash-flows', { credentials: 'same-origin' })
      .then(function (r) {
        if (!r.ok) {
          if (r.status === 404) {
            container.innerHTML = '<span class="text-soft">暂无股息记录</span>';
            return null;
          }
          if (r.status === 401) {
            container.innerHTML = '<span class="text-soft">请先登录</span>';
            return null;
          }
          throw new Error('HTTP ' + r.status);
        }
        if (r.redirected) {
          container.innerHTML = '<span class="text-soft">请先登录</span>';
          return null;
        }
        return r.json();
      })
      .then(function (d) {
        if (!d) return;
        if (!Array.isArray(d.cash_flows)) {
          throw new Error('Invalid response payload');
        }
        var flows = d.cash_flows;
        if (!flows.length) {
          container.innerHTML = '<span class="text-soft">暂无股息记录</span>';
          return;
        }
        var html = '<table class="mini-table"><thead><tr><th>日期</th><th>类型</th><th>金额</th><th>说明</th></tr></thead><tbody>';
        flows.forEach(function (flow) {
          var label = flow.flow_type;
          if (flow.flow_type === 'DISTRIBUTION') label = '股息';
          if (flow.flow_type === 'WITHHOLDING_TAX') label = '预扣税/退税';
          if (flow.flow_type === 'BROKER_INTEREST' || flow.flow_type === 'INTEREST') label = '利息';
          html += '<tr>'
            + '<td>' + (flow.flow_date || '') + '</td>'
            + '<td class="' + (flow.amount >= 0 ? 'positive' : 'negative') + '">' + label + '</td>'
            + '<td class="' + (flow.amount >= 0 ? 'positive' : 'negative') + '">'
            + (flow.amount >= 0 ? '+' : '') + '$' + Number(flow.amount).toFixed(2)
            + '</td>'
            + '<td>' + (flow.description || '-') + '</td>'
            + '</tr>';
        });
        html += '</tbody></table>';
        container.innerHTML = html;
      })
      .catch(function () { container.innerHTML = '<span class="text-soft">加载失败</span>'; });
  };

  /* ── Delete asset ────────────────────────────── */
  window.deleteAsset = function (assetId) {
    if (!confirm('确定要删除这个资产吗？')) return;
    fetch('/api/assets/' + assetId, { method: 'DELETE' })
      .then(function (r) {
        if (r.ok) afterAssetMutation();
        else alert('删除失败');
      })
      .catch(function () { alert('网络错误'); });
  };

  window.syncIBKR = function () {
    var btn = document.getElementById('btn-sync-ibkr');
    if (!btn || btn.disabled) return;
    btn.disabled = true;
    var shouldRestore = true;
    var originalText = btn.textContent;
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
        if (!res.ok) {
          throw new Error(res.data.error || '同步失败');
        }
        shouldRestore = false;
        if (res.data && res.data.skipped && res.data.reason === 'cooldown') {
          location.reload();
          return;
        }
        location.reload();
      })
      .catch(function (err) {
        alert(err.message || '同步失败');
      })
      .finally(function () {
        if (btn && shouldRestore) {
          btn.disabled = false;
          btn.textContent = originalText;
        }
      });
  };

  function applyIBKRSyncStatus(status) {
    var btn = document.getElementById('btn-sync-ibkr');
    var copy = document.getElementById('ibkr-sync-status-copy');
    if (!btn || !copy || !status) return;
    btn.disabled = !status.can_manual_sync;
    copy.textContent = '上次同步：' + (status.last_synced_at_display || '尚未同步');
    writeCache(IBKR_SYNC_CACHE_KEY, {
      value: status,
      savedAt: Date.now()
    });
  }

  function fetchIBKRSyncStatus() {
    fetch('/api/ibkr/sync-status', { credentials: 'same-origin' })
      .then(function (r) {
        if (!r.ok) throw new Error('sync status failed');
        return r.json();
      })
      .then(applyIBKRSyncStatus)
      .catch(function () {});
  }

  function applySnapshotRebuildStatus(status, options) {
    options = options || {};
    var btn = document.getElementById('btn-rebuild-snapshots');
    var copy = document.getElementById('snapshot-rebuild-copy');
    var spinner = document.getElementById('snapshot-rebuild-spinner');
    var block = document.getElementById('snapshot-rebuild-block');
    var historyStatus = document.getElementById('assets-history-status');
    var historyText = document.getElementById('assets-history-status-text');
    var previousStatus = lastSnapshotRebuildStatus;
    if (!status) return;

    if (btn && copy && spinner && block) {
      block.dataset.status = status.status || 'IDLE';
      block.dataset.isRunning = status.is_running ? 'true' : 'false';
      btn.disabled = !!status.is_running;
      spinner.hidden = !status.is_running;

      if (status.is_running) {
        copy.textContent = '正在回填：' + (status.refresh_from || '等待开始');
      } else if (status.status === 'FAILED') {
        copy.textContent = status.message || '历史回填失败';
      } else {
        copy.textContent = '上次回填：' + (status.last_completed_at_display || '尚未执行');
      }
    }

    if (historyStatus && historyText) {
      historyStatus.hidden = !status.is_running;
      if (status.is_running) {
        var fromText = status.refresh_from || status.pending_refresh_from || '';
        var currentText = status.last_snapshot_date || '';
        var progressText = '';
        if (status.rebuilt_days && status.total_days) {
          progressText = '（' + status.rebuilt_days + '/' + status.total_days + '，' + (status.progress_pct || 0) + '%）';
        }
        if (fromText && currentText) {
          historyText.textContent = '历史趋势更新中：从 ' + fromText + ' 开始，当前已回填到 ' + currentText + ' ' + progressText;
        } else if (fromText) {
          historyText.textContent = '历史趋势更新中：从 ' + fromText + ' 开始回填' + progressText;
        } else {
          historyText.textContent = '历史趋势更新中' + progressText;
        }
      }
    }

    if (status.is_running) {
      startSnapshotRebuildPolling();
    } else {
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
        refreshAssetsPageContent();
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
        writeCache(SNAPSHOT_REBUILD_CACHE_KEY, {
          value: status,
          savedAt: Date.now()
        });
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

  window.rebuildSnapshots = function () {
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
        if (!res.ok) {
          throw new Error((res.data && res.data.error) || '启动失败');
        }
        applySnapshotRebuildStatus(res.data.status || {}, { notifyCompletion: false });
        pollSnapshotRebuildStatus({ notifyCompletion: false });
      })
      .catch(function (err) {
        alert(err.message || '启动失败');
        btn.disabled = false;
      });
  };

  function refreshAssetsPageContent() {
    var container = document.getElementById('assets-page-content');
    if (!container) return;
    var url = container.getAttribute('data-refresh-url');
    if (!url) return;

    fetch(url, { credentials: 'same-origin' })
      .then(function (r) {
        if (!r.ok) {
          throw new Error('Failed to refresh assets content');
        }
        return r.text();
      })
      .then(function (html) {
        container.innerHTML = html;
        writeCache(ASSETS_CONTENT_CACHE_KEY, {
          html: html,
          savedAt: Date.now()
        });
        initAssetSummaryToggle();
        restoreExpandedAssetDetails();
      })
      .catch(function () {});
  }

  document.addEventListener('DOMContentLoaded', function () {
    var contentCache = readCache(ASSETS_CONTENT_CACHE_KEY);
    var rebuildCache = readCache(SNAPSHOT_REBUILD_CACHE_KEY);
    var now = Date.now();
    if (contentCache && contentCache.html) {
      var container = document.getElementById('assets-page-content');
      if (container) {
        container.innerHTML = contentCache.html;
      }
    }

    initAssetSummaryToggle();
    restoreExpandedAssetDetails();

    if (rebuildCache && rebuildCache.value) {
      applySnapshotRebuildStatus(rebuildCache.value, {
        notifyCompletion: false
      });
    }

    pollSnapshotRebuildStatus({ notifyCompletion: false });
    if (
      !contentCache ||
      !contentCache.savedAt ||
      (now - contentCache.savedAt) > LOCAL_CACHE_MAX_AGE_MS
    ) {
      setTimeout(refreshAssetsPageContent, 0);
      return;
    }

    if ((now - contentCache.savedAt) > LOCAL_CACHE_REFRESH_AFTER_MS) {
      setTimeout(refreshAssetsPageContent, 0);
    }
  });
})();
