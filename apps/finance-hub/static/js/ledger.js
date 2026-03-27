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
  }

  initCategorySelects();
  document.querySelectorAll('[data-user-picker]').forEach(initUserPicker);
  document.querySelectorAll('[data-ledger-entry-form]').forEach(initEntryModalForm);
})();
