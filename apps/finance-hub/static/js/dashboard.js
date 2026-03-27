/* Dashboard — charts + widget edit/add/remove management */
(function () {
  var D = window.__DASHBOARD_DATA__ || {};
  var layoutState = (window.__DASHBOARD_LAYOUT__ || []).slice();
  var DASHBOARD_LIVE_CACHE_KEY = 'financeHub.dashboard.livePage.v5';
  var trendChart = null;
  var allocationChart = null;
  var grid = null;
  var editing = false;
  var dragEl = null;
  var touchLiftTimer = null;
  var autoScrollFrame = null;
  var autoScrollVelocity = 0;
  var trendRebuildPollTimer = null;
  var lastTrendRebuildStatus = null;
  var LOCAL_CACHE_MAX_AGE_MS = 24 * 60 * 60 * 1000;
  var LOCAL_CACHE_REFRESH_AFTER_MS = 60 * 1000;

  function debounce(fn, wait) {
    var timer = null;
    return function () {
      var ctx = this;
      var args = arguments;
      clearTimeout(timer);
      timer = setTimeout(function () {
        fn.apply(ctx, args);
      }, wait);
    };
  }

  function formatNumber(value, digits) {
    return Number(value || 0).toLocaleString('zh-CN', {
      minimumFractionDigits: digits,
      maximumFractionDigits: digits
    });
  }

  function createElementFromHTML(html) {
    var wrapper = document.createElement('div');
    wrapper.innerHTML = html.trim();
    return wrapper.firstElementChild;
  }

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

  function refreshDashboardLivePage() {
    if (!grid || editing) return;
    var url = grid.getAttribute('data-live-url');
    if (!url) return;

    fetch(url)
      .then(function (r) {
        if (!r.ok) throw new Error('Failed to load dashboard');
        return r.json();
      })
      .then(function (payload) {
        D = payload.dashboard_data || {};
        grid.innerHTML = payload.html || '';
        writeCache(DASHBOARD_LIVE_CACHE_KEY, {
          html: payload.html || '',
          dashboard_data: D,
          savedAt: Date.now()
        });
        document.querySelectorAll('.widget').forEach(applyEditStateToWidget);
        initTrend();
        initAllocation();
        ensureEmptyState();
        setTimeout(resizeCharts, 20);
      })
      .catch(function () {});
  }

  function getLayoutItem(id) {
    return layoutState.find(function (item) {
      return item.id === id;
    }) || null;
  }

  function getVisibleLayout() {
    return layoutState
      .filter(function (item) { return item.is_visible; })
      .sort(function (a, b) { return a.sort_order - b.sort_order; });
  }

  function getHiddenLayout() {
    return layoutState
      .filter(function (item) { return !item.is_visible; })
      .sort(function (a, b) { return a.sort_order - b.sort_order; });
  }

  function syncLayoutStateFromDom() {
    var visibleIds = Array.prototype.map.call(
      document.querySelectorAll('#widget-grid .widget'),
      function (widget) {
        return parseInt(widget.dataset.widgetId, 10);
      }
    );

    visibleIds.forEach(function (id, index) {
      var item = getLayoutItem(id);
      if (item) {
        item.is_visible = 1;
        item.sort_order = index;
      }
    });

    var nextSort = visibleIds.length;
    getHiddenLayout().forEach(function (item) {
      item.sort_order = nextSort;
      nextSort += 1;
    });
  }

  function persistLayoutState() {
    syncLayoutStateFromDom();
    clearCache(DASHBOARD_LIVE_CACHE_KEY);
    return fetch('/api/dashboard/layout', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(layoutState.map(function (item) {
        return {
          id: item.id,
          sort_order: item.sort_order,
          is_visible: item.is_visible ? 1 : 0
        };
      }))
    }).catch(function () {});
  }

  function resizeCharts() {
    try {
      if (trendChart && typeof trendChart.resize === 'function') {
        trendChart.resize();
      }
      if (allocationChart && typeof allocationChart.resize === 'function') {
        allocationChart.resize();
      }
    } catch (e) {}
  }

  function stopAutoScroll() {
    autoScrollVelocity = 0;
    if (autoScrollFrame) {
      window.cancelAnimationFrame(autoScrollFrame);
      autoScrollFrame = null;
    }
  }

  function clearDraggingState() {
    if (touchLiftTimer) {
      clearTimeout(touchLiftTimer);
      touchLiftTimer = null;
    }
    document.querySelectorAll('.widget.dragging, .widget.drag-lifted, .widget.drag-armed').forEach(function (node) {
      node.classList.remove('dragging');
      node.classList.remove('drag-lifted');
      node.classList.remove('drag-armed');
    });
  }

  function runAutoScroll() {
    if (!autoScrollVelocity) {
      autoScrollFrame = null;
      return;
    }
    window.scrollBy(0, autoScrollVelocity);
    autoScrollFrame = window.requestAnimationFrame(runAutoScroll);
  }

  function updateAutoScroll(pointerY) {
    var edgeThreshold = Math.min(140, Math.max(80, window.innerHeight * 0.16));
    var nextVelocity = 0;

    if (pointerY < edgeThreshold) {
      nextVelocity = -Math.max(8, Math.round((edgeThreshold - pointerY) / 7));
    } else if (pointerY > window.innerHeight - edgeThreshold) {
      nextVelocity = Math.max(
        8,
        Math.round((pointerY - (window.innerHeight - edgeThreshold)) / 7)
      );
    }

    autoScrollVelocity = nextVelocity;
    if (autoScrollVelocity && !autoScrollFrame) {
      autoScrollFrame = window.requestAnimationFrame(runAutoScroll);
    }
    if (!autoScrollVelocity) {
      stopAutoScroll();
    }
  }

  function buildTrendChart(el, labels, values) {
    return new Chart(el, {
      type: 'line',
      data: {
        labels: labels,
        datasets: [{
          label: '总资产 (CNY)',
          data: values,
          borderColor: '#15b79e',
          backgroundColor: 'rgba(21,183,158,0.08)',
          fill: true,
          pointRadius: 0,
          pointHoverRadius: 5,
          pointHoverBackgroundColor: '#15b79e',
          pointHoverBorderColor: '#fff',
          pointHoverBorderWidth: 2,
          tension: 0.3
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: {
          mode: 'index',
          intersect: false
        },
        plugins: {
          tooltip: {
            backgroundColor: 'rgba(24,48,58,0.92)',
            titleFont: { size: 12 },
            bodyFont: { size: 14, weight: 'bold' },
            padding: 10,
            cornerRadius: 10,
            displayColors: false,
            callbacks: {
              title: function (items) {
                return items[0].label;
              },
              label: function (item) {
                return '¥ ' + Number(item.raw).toLocaleString('zh-CN', {
                  minimumFractionDigits: 2,
                  maximumFractionDigits: 2
                });
              }
            }
          },
          crosshair: false,
          legend: { display: false }
        },
        scales: {
          x: {
            ticks: { maxTicksLimit: 7, font: { size: 11 } },
            grid: { display: false }
          },
          y: {
            beginAtZero: false,
            ticks: {
              font: { size: 11 },
              callback: function (v) {
                if (v >= 10000) return (v / 10000).toFixed(1) + '万';
                return v;
              }
            },
            grid: { color: 'rgba(130,156,168,0.08)' }
          }
        }
      }
    });
  }

  function bindTrendRangeButtons(scope) {
    var btns = (scope || document).querySelectorAll('.range-btn');
    btns.forEach(function (btn) {
      if (btn.dataset.bound === '1') return;
      btn.dataset.bound = '1';
      btn.addEventListener('click', function () {
        btns.forEach(function (other) {
          other.classList.remove('active');
        });
        btn.classList.add('active');
        fetchTrendData(
          btn.getAttribute('data-range') || btn.getAttribute('data-days') || '30'
        );
      });
    });
  }

  function initTrend() {
    var el = document.getElementById('chart-trend');
    if (!el || !D.trend_chart) return;
    if (trendChart) {
      trendChart.destroy();
    }
    trendChart = buildTrendChart(el, D.trend_chart.labels, D.trend_chart.values);
    bindTrendRangeButtons(document);
  }

  function getActiveTrendRange() {
    var active = document.querySelector('.range-btn.active');
    return (
      (active && (active.getAttribute('data-range') || active.getAttribute('data-days'))) ||
      '30'
    );
  }

  function applyTrendRebuildStatus(status) {
    var badge = document.getElementById('trend-rebuild-status');
    var text = badge ? badge.querySelector('.trend-status-text') : null;
    if (!badge || !text || !status) return;

    var isRunning = !!status.is_running;
    badge.hidden = !isRunning;
    if (isRunning) {
      var fromText = status.refresh_from || status.pending_refresh_from || '';
      var currentText = status.last_snapshot_date || '';
      var progressText = '';
      if (status.rebuilt_days && status.total_days) {
        progressText = '（' + status.rebuilt_days + '/' + status.total_days + '，' + (status.progress_pct || 0) + '%）';
      }
      text.textContent = fromText && currentText
        ? ('历史趋势更新中：从 ' + fromText + ' 开始，当前已回填到 ' + currentText + ' ' + progressText)
        : (fromText
          ? ('历史趋势更新中：从 ' + fromText + ' 回填' + progressText)
          : ('历史趋势更新中' + progressText));
      startTrendRebuildPolling();
    } else {
      stopTrendRebuildPolling();
    }

    if (
      lastTrendRebuildStatus &&
      lastTrendRebuildStatus.is_running &&
      !isRunning
    ) {
      fetchTrendData(getActiveTrendRange());
    }
    lastTrendRebuildStatus = status;
  }

  function fetchTrendRebuildStatus() {
    fetch('/api/snapshots/rebuild-status')
      .then(function (r) {
        if (!r.ok) throw new Error('Failed to load rebuild status');
        return r.json();
      })
      .then(applyTrendRebuildStatus)
      .catch(function () {});
  }

  function startTrendRebuildPolling() {
    if (trendRebuildPollTimer) return;
    trendRebuildPollTimer = window.setInterval(fetchTrendRebuildStatus, 3000);
  }

  function stopTrendRebuildPolling() {
    if (!trendRebuildPollTimer) return;
    window.clearInterval(trendRebuildPollTimer);
    trendRebuildPollTimer = null;
  }

  function fetchTrendData(rangeValue) {
    fetch('/api/assets/daily-values?days=' + encodeURIComponent(rangeValue))
      .then(function (r) {
        if (!r.ok) throw new Error('Failed to load trend data');
        return r.json();
      })
      .then(function (data) {
        var items = data.values || [];
        D.trend_chart = {
          labels: items.map(function (item) { return item.date; }),
          values: items.map(function (item) { return item.total_cny; }),
          stock: items.map(function (item) { return item.stock_cny; }),
          bond: items.map(function (item) { return item.bond_cny; }),
          cash: items.map(function (item) { return item.cash_cny; })
        };
        initTrend();
      })
      .catch(function () {});
  }

  function initAllocation() {
    var el = document.getElementById('chart-allocation');
    if (!el || !D.allocation_pie) return;
    var items = D.allocation_pie.items || [];
    if (!items.length) return;
    if (allocationChart) {
      allocationChart.destroy();
    }
    allocationChart = new Chart(el, {
      type: 'doughnut',
      data: {
        labels: items.map(function (item) { return item.type_name; }),
        datasets: [{
          data: items.map(function (item) { return item.value_cny; }),
          backgroundColor: items.map(function (item) { return item.color; }),
          borderWidth: 0
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        cutout: '62%',
        plugins: { legend: { display: false } }
      }
    });
  }

  function renderAssetList(items) {
    var el = document.getElementById('dashboard-asset-list');
    if (!el) return;
    if (!items || !items.length) {
      el.innerHTML = '<p class="text-soft">暂无资产，请先添加</p>';
      return;
    }

    var html = ''
      + '<table class="mini-table">'
      + '<thead><tr><th>名称</th><th>现价</th><th>价值(CNY)</th><th>日涨跌</th></tr></thead>'
      + '<tbody>';

    items.forEach(function (asset) {
      html += '<tr>';
      html += '<td>' + asset.asset_name;
      if (asset.ticker_symbol) {
        html += ' <small class="text-soft">' + asset.ticker_symbol + '</small>';
      }
      html += '</td>';

      html += '<td>';
      if (asset.latest_price_usd != null) {
        html += '$' + formatNumber(asset.latest_price_usd, 2);
        if (asset.price_change_pct != null) {
          html += ' <small class="'
            + (asset.price_change_pct >= 0 ? 'positive' : 'negative')
            + '">'
            + (asset.price_change_pct >= 0 ? '+' : '')
            + asset.price_change_pct
            + '%</small>';
        }
      } else {
        html += '—';
      }
      html += '</td>';

      html += '<td>¥ ' + formatNumber(asset.value_cny, 0) + '</td>';
      html += '<td class="' + (asset.change_pct >= 0 ? 'positive' : 'negative') + '">'
        + (asset.change_pct >= 0 ? '+' : '')
        + asset.change_pct
        + '%</td>';
      html += '</tr>';
    });

    html += '</tbody></table>';
    el.innerHTML = html;
  }

  function refreshDashboardAssetList() {
    var el = document.getElementById('dashboard-asset-list');
    if (!el) return;
    var url = el.getAttribute('data-refresh-url');
    if (!url) return;

    fetch(url)
      .then(function (r) {
        if (!r.ok) throw new Error('Failed to refresh asset list');
        return r.json();
      })
      .then(function (data) {
        D.asset_list = { assets: data.assets || [] };
        renderAssetList(data.assets || []);
      })
      .catch(function () {});
  }

  function ensureEmptyState() {
    var visibleCount = document.querySelectorAll('#widget-grid .widget').length;
    var empty = document.querySelector('#widget-grid .empty-state');
    if (!visibleCount && !empty) {
      var node = document.createElement('div');
      node.className = 'empty-state';
      node.innerHTML = '<p>暂无组件数据</p><p class="text-soft">进入编辑模式后，可以重新添加想看的模块</p>';
      grid.appendChild(node);
    }
    if (visibleCount && empty) {
      empty.remove();
    }
  }

  function renderWidgetPicker() {
    var list = document.getElementById('widget-picker-list');
    if (!list) return;
    var hidden = getHiddenLayout();
    if (!hidden.length) {
      list.innerHTML = (
        '<div class="widget-picker-empty">'
        + '<strong>已经全部添加到首页了</strong>'
        + '<p>现在可以直接拖动卡片调整顺序。</p>'
        + '</div>'
      );
      return;
    }

    list.innerHTML = hidden.map(function (item) {
      return (
        '<article class="widget-picker-card">'
        + '<div class="widget-picker-meta">'
        + '<span class="widget-picker-name">' + item.display_name + '</span>'
        + '<p>' + (item.description || '可随时添加到首页') + '</p>'
        + '</div>'
        + '<button class="btn btn-primary btn-sm" type="button" data-widget-add="' + item.id + '">添加</button>'
        + '</article>'
      );
    }).join('');
  }

  function openWidgetPicker() {
    if (!editing) return;
    renderWidgetPicker();
    var panel = document.getElementById('widget-picker-panel');
    if (!panel) return;
    panel.hidden = false;
  }

  function closeWidgetPicker() {
    var panel = document.getElementById('widget-picker-panel');
    if (!panel) return;
    panel.hidden = true;
  }

  function applyEditStateToWidget(node) {
    if (!node) return;
    node.draggable = editing;
    var handle = node.querySelector('.widget-drag-handle');
    var removeBtn = node.querySelector('.widget-remove-btn');
    if (handle) {
      handle.style.display = editing ? 'inline' : 'none';
    }
    if (removeBtn) {
      removeBtn.hidden = !editing;
    }
  }

  function hydrateWidget(widget) {
    D[widget.widget_type] = widget.data || {};
    if (widget.widget_type === 'trend_chart') {
      initTrend();
    } else if (widget.widget_type === 'allocation_pie') {
      initAllocation();
    } else if (widget.widget_type === 'asset_list') {
      renderAssetList((widget.data && widget.data.assets) || []);
    }
    setTimeout(resizeCharts, 20);
  }

  function addWidget(layoutId) {
    fetch('/api/dashboard/layout-items/' + layoutId + '/show', { method: 'POST' })
      .then(function (r) {
        if (!r.ok) throw new Error('Failed to show widget');
        return r.json();
      })
      .then(function (payload) {
        var item = getLayoutItem(layoutId);
        if (item) {
          item.is_visible = 1;
          item.width = payload.widget.width;
          item.sort_order = getVisibleLayout().length;
        }

        var node = createElementFromHTML(payload.html);
        grid.appendChild(node);
        applyEditStateToWidget(node);
        hydrateWidget(payload.widget);
        ensureEmptyState();
        renderWidgetPicker();
        return persistLayoutState();
      })
      .catch(function () {});
  }

  function removeWidget(layoutId) {
    fetch('/api/dashboard/layout-items/' + layoutId + '/hide', { method: 'POST' })
      .then(function (r) {
        if (!r.ok) throw new Error('Failed to hide widget');
        return r.json();
      })
      .then(function () {
        var item = getLayoutItem(layoutId);
        if (item) {
          item.is_visible = 0;
        }
        var node = document.querySelector('.widget[data-widget-id="' + layoutId + '"]');
        if (node) {
          var type = node.dataset.widgetType;
          if (type === 'trend_chart' && trendChart) {
            trendChart.destroy();
            trendChart = null;
          }
          if (type === 'allocation_pie' && allocationChart) {
            allocationChart.destroy();
            allocationChart = null;
          }
          node.remove();
        }
        ensureEmptyState();
        renderWidgetPicker();
        return persistLayoutState();
      })
      .catch(function () {});
  }

  function toggleEditMode() {
    editing = !editing;
    document.body.classList.toggle('dashboard-editing', editing);

    var editBtn = document.getElementById('btn-edit-dashboard');
    var addBtn = document.getElementById('btn-open-widget-picker');
    if (editBtn) {
      editBtn.textContent = editing ? '完成编辑' : '编辑布局';
    }
    if (addBtn) {
      addBtn.hidden = !editing;
    }

    document.querySelectorAll('.widget').forEach(applyEditStateToWidget);

    if (editing) {
      renderWidgetPicker();
    } else {
      closeWidgetPicker();
      persistLayoutState();
    }
  }

  function initDrag() {
    grid = document.getElementById('widget-grid');
    if (!grid) return;

    grid.addEventListener('dragstart', function (e) {
      if (!editing) return;
      dragEl = e.target.closest('.widget');
      if (dragEl) {
        dragEl.classList.add('drag-lifted');
        dragEl.classList.add('dragging');
      }
    });

    grid.addEventListener('dragend', function () {
      clearDraggingState();
      dragEl = null;
      stopAutoScroll();
      if (editing) persistLayoutState();
    });

    grid.addEventListener('dragover', function (e) {
      if (!editing) return;
      e.preventDefault();
      updateAutoScroll(e.clientY);
      var target = e.target.closest('.widget');
      if (target && dragEl && target !== dragEl) {
        var rect = target.getBoundingClientRect();
        var mid = rect.top + rect.height / 2;
        if (e.clientY < mid) {
          grid.insertBefore(dragEl, target);
        } else {
          grid.insertBefore(dragEl, target.nextSibling);
        }
      }
    });

    var touchTarget = null;
    grid.addEventListener('touchstart', function (e) {
      if (!editing) return;
      dragEl = e.target.closest('.widget');
      if (!dragEl) return;
      dragEl.classList.add('drag-armed');
      dragEl.classList.add('drag-lifted');
      touchLiftTimer = window.setTimeout(function () {
        if (dragEl) {
          dragEl.classList.remove('drag-armed');
          dragEl.classList.add('dragging');
        }
      }, 80);
    }, { passive: true });

    grid.addEventListener('touchmove', function (e) {
      if (!editing || !dragEl) return;
      e.preventDefault();
      dragEl.classList.remove('drag-armed');
      dragEl.classList.add('dragging');
      var touch = e.touches[0];
      updateAutoScroll(touch.clientY);
      var el = document.elementFromPoint(touch.clientX, touch.clientY);
      touchTarget = el ? el.closest('.widget') : null;
      if (touchTarget && touchTarget !== dragEl) {
        var rect = touchTarget.getBoundingClientRect();
        var mid = rect.top + rect.height / 2;
        if (touch.clientY < mid) {
          grid.insertBefore(dragEl, touchTarget);
        } else {
          grid.insertBefore(dragEl, touchTarget.nextSibling);
        }
      }
    }, { passive: false });

    grid.addEventListener('touchend', function () {
      clearDraggingState();
      dragEl = null;
      touchTarget = null;
      stopAutoScroll();
      if (editing) persistLayoutState();
    });

    grid.addEventListener('touchcancel', function () {
      clearDraggingState();
      dragEl = null;
      touchTarget = null;
      stopAutoScroll();
    });

    grid.addEventListener('click', function (e) {
      var removeBtn = e.target.closest('[data-widget-remove]');
      if (removeBtn) {
        removeWidget(parseInt(removeBtn.getAttribute('data-widget-remove'), 10));
      }
    });
  }

  function initWidgetPicker() {
    var list = document.getElementById('widget-picker-list');
    if (!list) return;

    list.addEventListener('click', function (e) {
      var addBtn = e.target.closest('[data-widget-add]');
      if (addBtn) {
        addWidget(parseInt(addBtn.getAttribute('data-widget-add'), 10));
      }
    });
  }

  document.addEventListener('DOMContentLoaded', function () {
    grid = document.getElementById('widget-grid');
    var cache = readCache(DASHBOARD_LIVE_CACHE_KEY);
    var now = Date.now();
    if (grid && cache && cache.html) {
      D = cache.dashboard_data || {};
      grid.innerHTML = cache.html;
    }
    initTrend();
    initAllocation();
    initDrag();
    initWidgetPicker();
    ensureEmptyState();
    fetchTrendRebuildStatus();
    if (
      !cache ||
      !cache.savedAt ||
      (now - cache.savedAt) > LOCAL_CACHE_MAX_AGE_MS
    ) {
      setTimeout(refreshDashboardLivePage, 0);
    } else if ((now - cache.savedAt) > LOCAL_CACHE_REFRESH_AFTER_MS) {
      setTimeout(refreshDashboardLivePage, 0);
    }

    var onResize = debounce(resizeCharts, 150);
    window.addEventListener('resize', onResize);

    if (window.ResizeObserver) {
      var trendEl = document.getElementById('chart-trend');
      var allocEl = document.getElementById('chart-allocation');
      if (trendEl) {
        var ro1 = new ResizeObserver(function () { onResize(); });
        ro1.observe(trendEl);
      }
      if (allocEl) {
        var ro2 = new ResizeObserver(function () { onResize(); });
        ro2.observe(allocEl);
      }
    }

    setTimeout(resizeCharts, 50);
  });

  window.toggleEditMode = toggleEditMode;
  window.openWidgetPicker = openWidgetPicker;
  window.closeWidgetPicker = closeWidgetPicker;
})();
