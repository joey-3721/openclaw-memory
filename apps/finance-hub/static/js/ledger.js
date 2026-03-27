(function () {
  window.openLedgerModal = function (id) {
    var el = document.getElementById(id);
    if (el) {
      el.style.display = 'flex';
      el.querySelectorAll('[data-default-now]').forEach(setDefaultNow);
    }
  };

  window.closeLedgerModal = function (id) {
    var el = document.getElementById(id);
    if (el) el.style.display = 'none';
  };

  window.closeLedgerModalOnOverlay = function (event) {
    if (event.target.classList.contains('modal-overlay')) {
      event.target.style.display = 'none';
    }
  };

  window.openRenameModal = function (bookId, bookName) {
    var modal = document.getElementById('rename-book-modal');
    var form = document.getElementById('rename-book-form');
    var input = document.getElementById('rename-book-input');
    if (!modal || !form || !input) return;
    form.action = '/ledger/books/' + bookId + '/rename';
    input.value = bookName || '';
    modal.style.display = 'flex';
  };

  function debounce(fn, delay) {
    var timer = null;
    return function () {
      var args = arguments;
      clearTimeout(timer);
      timer = setTimeout(function () {
        fn.apply(null, args);
      }, delay);
    };
  }

  function updateSubcategoryOptions(selectEl) {
    if (!selectEl) return;
    var targetId = selectEl.getAttribute('data-subcategory-target');
    var subcategorySelect = targetId ? document.getElementById(targetId) : null;
    if (!subcategorySelect) return;
    var option = selectEl.options[selectEl.selectedIndex];
    var payload = option ? option.getAttribute('data-subcategories') : '[]';
    var items = [];
    try {
      items = JSON.parse(payload || '[]');
    } catch (err) {
      items = [];
    }
    subcategorySelect.innerHTML = '';
    items.forEach(function (item) {
      var opt = document.createElement('option');
      opt.value = item.name;
      opt.textContent = item.name;
      subcategorySelect.appendChild(opt);
    });
  }

  function initCategorySelects() {
    document.querySelectorAll('.ledger-category-select').forEach(function (selectEl) {
      updateSubcategoryOptions(selectEl);
      selectEl.addEventListener('change', function () {
        updateSubcategoryOptions(selectEl);
      });
    });
  }

  function renderSelectedUsers(root, selectedMap, isSingle) {
    var container = root.querySelector('.ledger-selected-users');
    var hiddenInput = root.querySelector('input[type="hidden"]');
    if (!container || !hiddenInput) return;
    container.innerHTML = '';
    var ids = Object.keys(selectedMap);
    hiddenInput.value = isSingle ? (ids[0] || '') : ids.join(',');
    ids.forEach(function (id) {
      var user = selectedMap[id];
      var chip = document.createElement('button');
      chip.type = 'button';
      chip.className = 'ledger-user-chip';
      chip.textContent = user.display_name + ' @' + user.username + ' ×';
      chip.addEventListener('click', function () {
        delete selectedMap[id];
        renderSelectedUsers(root, selectedMap, isSingle);
      });
      container.appendChild(chip);
    });
  }

  function initUserPicker(root) {
    var input = root.querySelector('.ledger-user-search-input');
    var results = root.querySelector('.ledger-user-search-results');
    var isSingle = root.hasAttribute('data-single-user');
    var selectedMap = {};
    if (!input || !results) return;

    function clearResults() {
      results.innerHTML = '';
      results.style.display = 'none';
    }

    var search = debounce(function (keyword) {
      if (!keyword || keyword.trim().length < 1) {
        clearResults();
        return;
      }
      fetch('/api/ledger/users/search?q=' + encodeURIComponent(keyword), {
        credentials: 'same-origin'
      })
        .then(function (r) { return r.json(); })
        .then(function (data) {
          var users = (data && data.users) || [];
          results.innerHTML = '';
          if (!users.length) {
            clearResults();
            return;
          }
          users.forEach(function (user) {
            if (selectedMap[String(user.id)]) return;
            var btn = document.createElement('button');
            btn.type = 'button';
            btn.className = 'ledger-user-result';
            btn.textContent = user.display_name + ' @' + user.username;
            btn.addEventListener('click', function () {
              if (isSingle) {
                Object.keys(selectedMap).forEach(function (key) {
                  delete selectedMap[key];
                });
              }
              selectedMap[String(user.id)] = user;
              renderSelectedUsers(root, selectedMap, isSingle);
              input.value = '';
              clearResults();
            });
            results.appendChild(btn);
          });
          results.style.display = 'grid';
        })
        .catch(clearResults);
    }, 180);

    input.addEventListener('input', function () {
      search(input.value);
    });
    document.addEventListener('click', function (event) {
      if (!root.contains(event.target)) {
        clearResults();
      }
    });
    renderSelectedUsers(root, selectedMap, isSingle);
  }

  function setDefaultNow(input) {
    if (!input || input.value) return;
    var now = new Date();
    var offset = now.getTimezoneOffset();
    var local = new Date(now.getTime() - offset * 60000);
    input.value = local.toISOString().slice(0, 16);
  }

  function renderSubcategories(container, hiddenInput, items) {
    if (!container || !hiddenInput) return;
    container.innerHTML = '';
    items.forEach(function (item, index) {
      var btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'ledger-subcategory-choice' + (index === 0 ? ' is-active' : '');
      btn.setAttribute('data-subcategory-choice', '');
      btn.setAttribute('data-name', item.name);
      btn.innerHTML = (
        '<span class="ledger-subcategory-choice-icon"></span>' +
        '<span>' + item.name + '</span>'
      );
      var iconHost = btn.querySelector('.ledger-subcategory-choice-icon');
      if (iconHost && window.ledgerSubcategoryIcons && window.ledgerSubcategoryIcons[item.icon]) {
        iconHost.innerHTML = window.ledgerSubcategoryIcons[item.icon];
      }
      btn.addEventListener('click', function () {
        container.querySelectorAll('.ledger-subcategory-choice').forEach(function (node) {
          node.classList.remove('is-active');
        });
        btn.classList.add('is-active');
        hiddenInput.value = item.name;
      });
      container.appendChild(btn);
    });
    if (items[0]) hiddenInput.value = items[0].name;
  }

  function selectSubcategoryChoice(container, hiddenInput, subcategoryName) {
    if (!container || !hiddenInput) return;
    var choices = Array.from(container.querySelectorAll('.ledger-subcategory-choice'));
    var matched = choices.find(function (node) {
      return (node.getAttribute('data-name') || '') === subcategoryName;
    }) || choices[0];
    choices.forEach(function (node) { node.classList.remove('is-active'); });
    if (matched) {
      matched.classList.add('is-active');
      hiddenInput.value = matched.getAttribute('data-name') || '';
    }
  }

  function selectCategoryChoice(categoryGrid, categoryCode) {
    if (!categoryGrid) return null;
    var choices = Array.from(categoryGrid.querySelectorAll('[data-category-choice]'));
    return choices.find(function (node) {
      return (node.getAttribute('data-code') || '') === categoryCode;
    }) || choices[0] || null;
  }

  function initEntryModalForm(form) {
    var nowInput = form.querySelector('[data-default-now]');
    setDefaultNow(nowInput);

    var categoryHidden = form.querySelector('[data-category-hidden]');
    var categoryGrid = form.querySelector('[data-category-grid]');
    if (!categoryHidden || !categoryGrid) return;
    var subcategoryTargetId = categoryGrid.getAttribute('data-subcategory-target');
    var subcategoryHiddenId = categoryGrid.getAttribute('data-subcategory-hidden');
    var subcategoryContainer = subcategoryTargetId ? document.getElementById(subcategoryTargetId) : null;
    var subcategoryHidden = subcategoryHiddenId ? document.getElementById(subcategoryHiddenId) : null;

    categoryGrid.querySelectorAll('[data-category-choice]').forEach(function (btn) {
      btn.addEventListener('click', function () {
        categoryGrid.querySelectorAll('[data-category-choice]').forEach(function (node) {
          node.classList.remove('is-active');
        });
        btn.classList.add('is-active');
        categoryHidden.value = btn.getAttribute('data-code') || '';
        var items = [];
        try {
          items = JSON.parse(btn.getAttribute('data-subcategories') || '[]');
        } catch (err) {
          items = [];
        }
        renderSubcategories(subcategoryContainer, subcategoryHidden, items);
      });
    });

    form.addEventListener('submit', function (event) {
      event.preventDefault();
      var submitButton = form.querySelector('button[type="submit"]');
      var modal = form.closest('.modal-overlay');
      if (submitButton) {
        submitButton.disabled = true;
        submitButton.textContent = '保存中...';
      }
      if (modal) {
        modal.style.display = 'none';
      }

      fetch('/api' + form.getAttribute('action'), {
        method: 'POST',
        body: new FormData(form),
        credentials: 'same-origin'
      })
        .then(function (r) { return r.json().then(function (data) { return { ok: r.ok, data: data }; }); })
        .then(function (result) {
          if (!result.ok || !result.data || result.data.ok === false) {
            throw new Error((result.data && result.data.error) || '保存失败');
          }
          window.location.replace((result.data && result.data.redirect_url) || window.location.href);
        })
        .catch(function (err) {
          if (modal) {
            modal.style.display = 'flex';
          }
          window.alert(err.message || '保存失败，请重试');
        })
        .finally(function () {
          if (submitButton) {
            submitButton.disabled = false;
            submitButton.textContent = '保存';
          }
        });
    });
  }

  function initEntryEditModal() {
    var modal = document.querySelector('[data-ledger-edit-form]');
    if (!modal) return;
    document.querySelectorAll('[data-entry-edit]').forEach(function (button) {
      button.addEventListener('click', function () {
        var payload = {};
        try {
          payload = JSON.parse(button.getAttribute('data-entry') || '{}');
        } catch (err) {
          payload = {};
        }
        var form = document.querySelector('[data-ledger-edit-form]');
        if (!form) return;
        var bookId = form.getAttribute('data-book-id');
        form.action = '/ledger/books/' + bookId + '/entries/' + payload.id + '/update';
        var amountInput = form.querySelector('input[name="amount"]');
        var titleInput = form.querySelector('input[name="title"]');
        var noteInput = form.querySelector('input[name="note"]');
        var occurredInput = form.querySelector('input[name="occurred_at"]');
        var settledInput = form.querySelector('input[name="mark_settled"]');
        if (amountInput) amountInput.value = payload.amount || '';
        if (titleInput) titleInput.value = payload.title || '';
        if (noteInput) noteInput.value = payload.note || '';
        if (occurredInput) occurredInput.value = payload.occurred_at || '';
        if (settledInput) settledInput.checked = !!payload.is_settled;

        var categoryGrid = form.querySelector('[data-category-grid]');
        var categoryHidden = form.querySelector('[data-category-hidden]');
        var targetId = categoryGrid ? categoryGrid.getAttribute('data-subcategory-target') : null;
        var hiddenId = categoryGrid ? categoryGrid.getAttribute('data-subcategory-hidden') : null;
        var subcategoryContainer = targetId ? document.getElementById(targetId) : null;
        var subcategoryHidden = hiddenId ? document.getElementById(hiddenId) : null;
        var categoryChoice = selectCategoryChoice(categoryGrid, payload.category_code || 'OTHER');
        if (categoryGrid) {
          categoryGrid.querySelectorAll('[data-category-choice]').forEach(function (node) {
            node.classList.remove('is-active');
          });
        }
        if (categoryChoice) {
          categoryChoice.classList.add('is-active');
          if (categoryHidden) {
            categoryHidden.value = categoryChoice.getAttribute('data-code') || '';
          }
          var items = [];
          try {
            items = JSON.parse(categoryChoice.getAttribute('data-subcategories') || '[]');
          } catch (err) {
            items = [];
          }
          renderSubcategories(subcategoryContainer, subcategoryHidden, items);
          selectSubcategoryChoice(subcategoryContainer, subcategoryHidden, payload.subcategory_name || '');
        }

        form.querySelectorAll('input[name="payer_user_id"]').forEach(function (input) {
          input.checked = String(input.value) === String(payload.payer_user_id || '');
        });
        var participantIds = (payload.participant_user_ids || []).map(String);
        form.querySelectorAll('input[name="participant_user_ids"]').forEach(function (input) {
          input.checked = participantIds.indexOf(String(input.value)) !== -1;
        });

        openLedgerModal('edit-entry-modal-' + bookId);
      });
    });
  }

  function initEntryDetailModal() {
    document.querySelectorAll('[data-entry-detail]').forEach(function (button) {
      button.addEventListener('click', function () {
        if (button.getAttribute('data-swipe-skip-click') === '1') {
          button.setAttribute('data-swipe-skip-click', '0');
          return;
        }
        var payload = {};
        try {
          payload = JSON.parse(button.getAttribute('data-entry') || '{}');
        } catch (err) {
          payload = {};
        }
        var modal = document.querySelector('[id^="entry-detail-modal-"]');
        if (!modal) return;
        var setText = function (selector, value, fallback) {
          var node = modal.querySelector(selector);
          if (node) node.textContent = value || fallback || '未填写';
        };
        setText('[data-entry-detail-title]', payload.title, '未命名账单');
        setText('[data-entry-detail-amount]', payload.amount, 'CNY 0.00');
        setText(
          '[data-entry-detail-category]',
          (payload.category || '其他') + (payload.subcategory_name ? (' / ' + payload.subcategory_name) : ''),
          '其他'
        );
        setText('[data-entry-detail-payer]', payload.payer_name, '未知付款人');
        setText(
          '[data-entry-detail-participants]',
          (payload.participant_names || []).join('、'),
          '仅自己'
        );
        setText('[data-entry-detail-time]', payload.occurred_at_display, '未记录');
        setText('[data-entry-detail-merchant]', payload.merchant_name, '未填写');
        setText('[data-entry-detail-note]', payload.note, '未填写');
        setText('[data-entry-detail-status]', payload.is_settled ? '已结清' : '未结清', '未结清');
        openLedgerModal(modal.id);
      });
    });
  }

  function initEntrySwipeActions() {
    var activeSwipe = null;
    var maxReveal = 130;
    var wheelLockTimer = null;

    function setSwipeOffset(item, offset) {
      var card = item.querySelector('.ledger-entry-swipe-card');
      if (!card) return;
      card.style.transform = 'translateX(' + offset + 'px)';
    }

    function closeSwipe(item) {
      if (!item) return;
      item.classList.remove('is-revealed', 'is-dragging');
      setSwipeOffset(item, 0);
      if (activeSwipe === item) activeSwipe = null;
    }

    function openSwipe(item) {
      if (!item) return;
      document.querySelectorAll('[data-entry-swipe].is-revealed').forEach(function (node) {
        if (node !== item) {
          closeSwipe(node);
        }
      });
      item.classList.remove('is-dragging');
      item.classList.add('is-revealed');
      setSwipeOffset(item, -maxReveal);
      activeSwipe = item;
    }

    document.querySelectorAll('[data-entry-swipe]').forEach(function (item) {
      var startX = 0;
      var currentX = 0;
      var startOffset = 0;
      var dragging = false;
      var moved = false;
      var detailButton = item.querySelector('[data-entry-detail]');
      var card = item.querySelector('.ledger-entry-swipe-card');
      if (!card) return;

      function beginSwipe(clientX) {
        startX = clientX;
        currentX = startX;
        startOffset = item.classList.contains('is-revealed') ? -maxReveal : 0;
        document.querySelectorAll('[data-entry-swipe].is-revealed').forEach(function (node) {
          if (node !== item) {
            closeSwipe(node);
          }
        });
        item.classList.add('is-dragging');
        dragging = true;
        moved = false;
      }

      function moveSwipe(clientX) {
        if (!dragging) return;
        currentX = clientX;
        var deltaX = currentX - startX;
        if (Math.abs(deltaX) > 6) {
          moved = true;
          if (detailButton) {
            detailButton.setAttribute('data-swipe-skip-click', '1');
          }
        }
        var nextOffset = Math.min(0, Math.max(-maxReveal, startOffset + deltaX));
        setSwipeOffset(item, nextOffset);
      }

      function endSwipe() {
        if (!dragging) return;
        dragging = false;
        item.classList.remove('is-dragging');
        var deltaX = currentX - startX;
        var finalOffset = startOffset + deltaX;
        if (finalOffset <= -88 || deltaX < -36) {
          openSwipe(item);
        } else {
          closeSwipe(item);
        }
      }

      item.addEventListener('touchstart', function (event) {
        if (!event.touches || !event.touches[0]) return;
        beginSwipe(event.touches[0].clientX);
      }, { passive: true });

      item.addEventListener('touchmove', function (event) {
        if (!event.touches || !event.touches[0]) return;
        moveSwipe(event.touches[0].clientX);
      }, { passive: true });

      item.addEventListener('touchend', endSwipe);

      card.addEventListener('mousedown', function (event) {
        if (event.button !== 0) return;
        beginSwipe(event.clientX);
      });

      window.addEventListener('mousemove', function (event) {
        if (!dragging) return;
        moveSwipe(event.clientX);
      });

      window.addEventListener('mouseup', function () {
        endSwipe();
      });

      item.addEventListener('wheel', function (event) {
        if (Math.abs(event.deltaX) < 6 || Math.abs(event.deltaX) < Math.abs(event.deltaY)) {
          return;
        }
        event.preventDefault();
        if (wheelLockTimer) clearTimeout(wheelLockTimer);
        var currentOffset = item.classList.contains('is-revealed') ? -maxReveal : 0;
        var nextOffset = Math.min(0, Math.max(-maxReveal, currentOffset - event.deltaX));
        setSwipeOffset(item, nextOffset);
        if (nextOffset <= -88) {
          openSwipe(item);
        } else if (nextOffset >= -20) {
          closeSwipe(item);
        } else {
          item.classList.add('is-dragging');
        }
        wheelLockTimer = setTimeout(function () {
          item.classList.remove('is-dragging');
          if (nextOffset <= -88) {
            openSwipe(item);
          } else {
            closeSwipe(item);
          }
        }, 90);
      }, { passive: false });
    });

    document.querySelectorAll('[data-entry-delete]').forEach(function (button) {
      button.addEventListener('click', function () {
        var swipe = button.closest('[data-entry-swipe]');
        if (swipe && swipe.classList.contains('is-revealed')) {
          swipe.classList.remove('is-revealed');
        }
        var modal = document.querySelector('[data-delete-entry-form]');
        var titleNode = document.querySelector('[data-delete-entry-title]');
        if (!modal || !titleNode) return;
        modal.action = button.getAttribute('data-entry-delete-action') || modal.action;
        titleNode.textContent = '确定删除“' + (button.getAttribute('data-entry-title') || '这条账单') + '”吗？';
        openLedgerModal('delete-entry-modal-' + (modal.getAttribute('data-book-id') || ''));
      });
    });

    document.addEventListener('click', function (event) {
      if (activeSwipe && !activeSwipe.contains(event.target)) {
        closeSwipe(activeSwipe);
      }
    });
  }

  function renderAiResults(container, payload) {
    if (!container) return;
    var items = (payload && payload.items) || [];
    if (!items.length) {
      container.innerHTML = (
        '<div class="ledger-outline-item ledger-outline-item-compact">' +
        '<strong>没有识别到可用账单</strong>' +
        '<p>你可以换一段更完整的文字，或者点右边更多按钮手动录入。</p>' +
        '</div>'
      );
      return;
    }
    container.innerHTML = '';
    items.forEach(function (item, index) {
      var card = document.createElement('article');
      card.className = 'ledger-ai-result-card';
      card.innerHTML =
        '<strong>' + (item.title || ('第 ' + (index + 1) + ' 条记录')) + '</strong>' +
        '<p class="ledger-ai-result-meta">' +
          (item.amount || '0.00') + ' ' + (item.currency || 'CNY') +
          ' · ' + (item.category_code || 'OTHER') +
          ' / ' + (item.subcategory_name || '其他杂项') +
        '</p>' +
        '<p class="ledger-ai-result-note">' +
          '时间：' + ((item.occurred_at || '').trim() || '未识别') +
          ' · 商户：' + ((item.merchant_name || '').trim() || '未识别') +
          ' · 置信度：' + String(item.confidence || 0) +
        '</p>';
      container.appendChild(card);
    });
  }

  function renderAiStatus(container, title, message, tone) {
    if (!container) return;
    container.innerHTML =
      '<div class="ledger-outline-item ledger-outline-item-compact ledger-ai-status-card' +
      (tone ? (' ledger-ai-status-' + tone) : '') +
      '">' +
      '<strong>' + title + '</strong>' +
      '<p>' + message + '</p>' +
      '</div>';
  }

  function initAiQuickForm(form) {
    var bookId = form.getAttribute('data-book-id');
    var textInput = form.querySelector('input[name="text"]');
    var imageButton = form.querySelector('[data-ai-image-button]');
    var imageInput = form.querySelector('[data-ai-image-input]');
    var resultList = form.parentElement.querySelector('[data-ai-result-list]');
    var modal = form.closest('.modal-overlay');
    if (!bookId || !textInput || !resultList) return;

    function setLoading(loading) {
      textInput.disabled = loading;
      if (imageButton) imageButton.disabled = loading;
    }

    function pollJob(jobId) {
      var startedAt = Date.now();
      var interval = window.setInterval(function () {
        fetch('/api/ledger/ai/jobs/' + encodeURIComponent(jobId), {
          method: 'GET',
          credentials: 'same-origin'
        })
          .then(function (r) { return r.json().then(function (data) { return { ok: r.ok, data: data }; }); })
          .then(function (result) {
            if (!result.ok || !result.data || result.data.ok === false) {
              throw new Error((result.data && result.data.error) || '任务查询失败');
            }
            var job = result.data.job || {};
            if (job.status === 'QUEUED' || job.status === 'RUNNING') {
              var elapsed = Math.max(1, Math.floor((Date.now() - startedAt) / 1000));
              renderAiStatus(
                resultList,
                'AI 处理中',
                '已经提交到后台，正在识别并写入账本… ' + elapsed + 's',
                'loading'
              );
              return;
            }
            window.clearInterval(interval);
            if (job.status === 'SUCCEEDED') {
              if (modal) {
                modal.style.display = 'none';
              }
              window.location.replace('/ledger/books/' + bookId);
              return;
            }
            throw new Error(job.error_message || '未检测到有效内容');
          })
          .catch(function (err) {
            window.clearInterval(interval);
            setLoading(false);
            renderAiStatus(resultList, '未检测到有效内容', err.message || 'AI 任务失败，请稍后重试。', 'empty');
          });
      }, 1200);
    }

    function handleAiRecordResult(result, emptyMessage) {
      if (!result.ok || !result.data || result.data.ok === false) {
        throw new Error((result.data && result.data.error) || emptyMessage);
      }
      pollJob(result.data.job_id);
    }

    form.addEventListener('submit', function (event) {
      event.preventDefault();
      var text = (textInput.value || '').trim();
      if (!text) return;
      setLoading(true);
      renderAiStatus(resultList, 'AI 已提交', '文字已经发到后台，正在开始识别…', 'loading');
      fetch('/api/ledger/books/' + bookId + '/ai/record-text', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'same-origin',
        body: JSON.stringify({ text: text })
      })
        .then(function (r) { return r.json().then(function (data) { return { ok: r.ok, data: data }; }); })
        .then(function (result) { handleAiRecordResult(result, '未检测到有效内容'); })
        .catch(function (err) {
          renderAiStatus(resultList, '未检测到有效内容', err.message || '这段文字暂时没识别出可记账内容，你可以换个说法再试一次。', 'empty');
        })
        .finally(function () {
          setLoading(false);
        });
    });

    textInput.addEventListener('keydown', function (event) {
      if (event.key === 'Enter') {
        event.preventDefault();
        form.requestSubmit();
      }
    });

    if (imageButton && imageInput) {
      imageButton.addEventListener('click', function () {
        imageInput.click();
      });
      imageInput.addEventListener('change', function () {
        if (!imageInput.files || !imageInput.files[0]) return;
        var payload = new FormData();
        payload.append('image', imageInput.files[0]);
        setLoading(true);
        renderAiStatus(resultList, '图片已提交', '图片已经发到后台，正在开始识别…', 'loading');
        fetch('/api/ledger/books/' + bookId + '/ai/record-image', {
          method: 'POST',
          body: payload,
          credentials: 'same-origin'
        })
          .then(function (r) { return r.json().then(function (data) { return { ok: r.ok, data: data }; }); })
          .then(function (result) { handleAiRecordResult(result, '未检测到有效内容'); })
          .catch(function (err) {
            renderAiStatus(resultList, '未检测到有效内容', err.message || '这张图片里暂时没识别出可记账内容，你可以换一张截图或手动输入。', 'empty');
          })
          .finally(function () {
            imageInput.value = '';
            setLoading(false);
          });
      });
    }
  }

  initCategorySelects();
  document.querySelectorAll('[data-user-picker]').forEach(initUserPicker);
  document.querySelectorAll('[data-ledger-entry-form]').forEach(initEntryModalForm);
  document.querySelectorAll('[data-ai-text-form]').forEach(initAiQuickForm);
  initEntryEditModal();
  initEntryDetailModal();
  initEntrySwipeActions();
})();
