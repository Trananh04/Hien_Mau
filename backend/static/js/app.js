/* Tương tác dùng chung — không phụ thuộc thư viện ngoài (trừ Lucide cho icon). */
(function () {
  'use strict';

  function renderIcons(root) {
    if (window.lucide && window.lucide.createIcons) {
      window.lucide.createIcons({ attrs: { 'stroke-width': 2 }, root: root || document });
    }
  }
  window.renderIcons = renderIcons;
  renderIcons();

  /* ---------- Thanh tiến độ: độ rộng từ data-pct (gán qua CSSOM — CSP không cho thuộc tính style inline) */
  document.querySelectorAll('[data-pct]').forEach(function (el) {
    var v = parseFloat(String(el.getAttribute('data-pct')).replace(',', '.'));
    el.style.width = (isFinite(v) ? Math.max(0, Math.min(100, v)) : 0) + '%';
  });

  function getCookie(name) {
    var match = document.cookie.match(new RegExp('(?:^|; )' + name + '=([^;]*)'));
    return match ? decodeURIComponent(match[1]) : '';
  }

  /* ---------- Menu điện thoại ---------- */
  document.querySelectorAll('[data-toggle="mobile-nav"]').forEach(function (btn) {
    btn.addEventListener('click', function () {
      var drawer = document.getElementById(btn.getAttribute('aria-controls'));
      if (!drawer) return;
      var open = drawer.hasAttribute('hidden');
      drawer.toggleAttribute('hidden', !open);
      btn.setAttribute('aria-expanded', String(open));
      btn.querySelector('[data-icon-open]').toggleAttribute('hidden', open);
      btn.querySelector('[data-icon-close]').toggleAttribute('hidden', !open);
    });
  });

  /* ---------- Menu tài khoản ---------- */
  document.querySelectorAll('[data-menu]').forEach(function (menu) {
    var trigger = menu.querySelector('[data-menu-trigger]');
    var panel = menu.querySelector('[data-menu-panel]');
    trigger.addEventListener('click', function (e) {
      e.stopPropagation();
      var open = panel.hasAttribute('hidden');
      document.querySelectorAll('[data-menu-panel]').forEach(function (p) { p.setAttribute('hidden', ''); });
      panel.toggleAttribute('hidden', !open);
      trigger.setAttribute('aria-expanded', String(open));
    });
  });
  document.addEventListener('click', function (e) {
    document.querySelectorAll('[data-menu]').forEach(function (menu) {
      if (!menu.contains(e.target)) {
        menu.querySelector('[data-menu-panel]').setAttribute('hidden', '');
        menu.querySelector('[data-menu-trigger]').setAttribute('aria-expanded', 'false');
      }
    });
  });
  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape') {
      document.querySelectorAll('[data-menu-panel]').forEach(function (p) { p.setAttribute('hidden', ''); });
    }
  });

  /* ---------- Thanh bên khu làm việc trên điện thoại ---------- */
  var shell = document.querySelector('[data-ws-shell]');
  if (shell) {
    document.querySelectorAll('[data-ws-toggle]').forEach(function (b) {
      b.addEventListener('click', function () { shell.classList.toggle('nav-open'); });
    });
    document.querySelectorAll('[data-ws-close]').forEach(function (b) {
      b.addEventListener('click', function () { shell.classList.remove('nav-open'); });
    });
  }

  /* ---------- Dialog ---------- */
  function openDialog(id) {
    var d = document.getElementById(id);
    if (d && typeof d.showModal === 'function') { d.showModal(); }
    return d;
  }
  window.openDialog = openDialog;
  document.addEventListener('click', function (e) {
    var opener = e.target.closest('[data-open-dialog]');
    if (opener) {
      e.preventDefault();
      var drawer = document.getElementById('mobile-nav-drawer');
      if (drawer && !drawer.hasAttribute('hidden')) {
        var toggle = document.querySelector('[data-toggle="mobile-nav"]');
        if (toggle) toggle.click();
      }
      openDialog(opener.getAttribute('data-open-dialog'));
      return;
    }
    var closer = e.target.closest('[data-close-dialog]');
    if (closer) {
      var dlg = closer.closest('dialog');
      if (dlg) dlg.close();
    }
  });
  document.querySelectorAll('dialog').forEach(function (d) {
    d.addEventListener('click', function (e) {
      if (e.target === d) d.close();  // bấm ra ngoài để đóng
    });
  });

  /* ---------- Xác nhận thao tác không hoàn tác được ---------- */
  var confirmDialog = document.getElementById('confirm-dialog');
  var pendingForm = null;
  document.addEventListener('submit', function (e) {
    var form = e.target;
    if (form.hasAttribute('data-confirm') && !form.dataset.confirmed) {
      e.preventDefault();
      if (!form.reportValidity()) return;
      pendingForm = form;
      pendingForm._submitter = e.submitter || null;
      confirmDialog.querySelector('[data-confirm-message]').textContent = form.getAttribute('data-confirm');
      var detail = confirmDialog.querySelector('[data-confirm-detail]');
      var text = form.getAttribute('data-confirm-detail');
      if (form.hasAttribute('data-confirm-summary')) {
        // Tóm tắt dữ liệu sắp ghi để người dùng kiểm tra lần cuối
        var lines = [];
        form.querySelectorAll('[data-summary-label]').forEach(function (el) {
          if (el.disabled || el.closest('[hidden]')) return;
          if (el.type === 'radio' && !el.checked) return;
          var v = el.type === 'radio' ? el.getAttribute('data-summary-text')
            : (el.tagName === 'SELECT' ? (el.value ? el.selectedOptions[0].textContent : '') : el.value);
          if (el.type === 'datetime-local' && v) v = v.replace('T', ' ');
          if (v) lines.push(el.getAttribute('data-summary-label') + ': ' + v);
        });
        text = lines.join(' · ') + '. Sau khi ghi nhận, chỉ Quản trị bệnh viện mới sửa/hủy được.';
      }
      detail.textContent = text || '';
      detail.toggleAttribute('hidden', !text);
      var ok = confirmDialog.querySelector('[data-confirm-ok]');
      ok.textContent = form.getAttribute('data-confirm-label') || 'Xác nhận';
      confirmDialog.showModal();
      return;
    }
    // Chống bấm lặp: khóa nút gửi ngay khi bấm tới khi có phản hồi (hỗ trợ BR-11)
    if ((form.method || '').toLowerCase() === 'post' && !e.defaultPrevented) {
      var buttons = form.querySelectorAll('button[type="submit"], button:not([type])');
      setTimeout(function () {
        buttons.forEach(function (b) { b.disabled = true; b.classList.add('is-loading'); });
      }, 0);
    }
  });
  if (confirmDialog) {
    confirmDialog.querySelector('[data-confirm-ok]').addEventListener('click', function () {
      if (!pendingForm) return;
      var form = pendingForm;
      form.dataset.confirmed = '1';
      confirmDialog.close();
      var submitter = form._submitter;
      if (submitter && submitter.name) {
        var hidden = document.createElement('input');
        hidden.type = 'hidden'; hidden.name = submitter.name; hidden.value = submitter.value;
        form.appendChild(hidden);
      }
      if (typeof form.requestSubmit === 'function') { form.requestSubmit(); } else { form.submit(); }
    });
    confirmDialog.addEventListener('close', function () {
      if (pendingForm && !pendingForm.dataset.confirmed) pendingForm = null;
    });
  }

  // Quay lại trang bằng nút Back: mở khóa các nút đã khóa
  window.addEventListener('pageshow', function (e) {
    if (e.persisted) {
      document.querySelectorAll('.is-loading').forEach(function (b) { b.disabled = false; b.classList.remove('is-loading'); });
    }
  });

  /* ---------- Tự gửi form khi đổi lựa chọn ---------- */
  document.querySelectorAll('form[data-autosubmit] select, form[data-autosubmit] input[type="checkbox"]').forEach(function (el) {
    el.addEventListener('change', function () { el.form.submit(); });
  });

  /* ---------- Toast ---------- */
  document.querySelectorAll('[data-toast]').forEach(function (t) {
    var close = function () { t.style.transition = 'opacity .25s'; t.style.opacity = '0'; setTimeout(function () { t.remove(); }, 250); };
    t.querySelector('[data-toast-close]').addEventListener('click', close);
    if (!t.classList.contains('error')) setTimeout(close, 6500);
  });

  /* ---------- Hiện/ẩn mật khẩu ---------- */
  document.querySelectorAll('[data-pw-toggle]').forEach(function (btn) {
    btn.addEventListener('click', function () {
      var input = btn.parentElement.querySelector('input');
      var show = input.type === 'password';
      input.type = show ? 'text' : 'password';
      btn.setAttribute('aria-label', show ? 'Ẩn mật khẩu' : 'Hiện mật khẩu');
    });
  });

  /* ---------- Select phụ thuộc: chế phẩm → quy cách ---------- */
  document.querySelectorAll('[data-product-select]').forEach(function (productSel) {
    var specSel = document.getElementById(productSel.getAttribute('data-product-select'));
    if (!specSel) return;
    function sync() {
      var pid = productSel.value;
      var firstVisible = null; var keep = false;
      Array.prototype.forEach.call(specSel.options, function (o) {
        if (!o.value) return;
        var match = !pid || o.getAttribute('data-product') === pid;
        o.hidden = !match; o.disabled = !match;
        if (match && !firstVisible) firstVisible = o;
        if (match && o.getAttribute('data-default') === '1' && !keep) firstVisible = o;
        if (match && o.selected) keep = true;
      });
      if (!keep && firstVisible) firstVisible.selected = true;
      specSel.dispatchEvent(new Event('change'));
    }
    productSel.addEventListener('change', sync);
    sync();
  });

  /* ---------- Xem trước tồn trước/sau cho phiếu kho ---------- */
  document.querySelectorAll('[data-stock-preview]').forEach(function (form) {
    var box = form.querySelector('[data-preview-box]');
    function update() {
      var sel = form.querySelector('[name="stock_id"]');
      var before = 0; var available = 0;
      if (sel && sel.selectedOptions.length) {
        before = parseInt(sel.selectedOptions[0].getAttribute('data-on-hand') || '0', 10);
        available = parseInt(sel.selectedOptions[0].getAttribute('data-available') || '0', 10);
      } else if (form.dataset.onHand) {
        before = parseInt(form.dataset.onHand, 10);
      }
      var qty = parseInt((form.querySelector('[name="quantity"]') || {}).value || '0', 10) || 0;
      var sign = form.getAttribute('data-stock-preview');
      if (sign === 'adjust') {
        var dir = form.querySelector('[name="direction"]:checked');
        sign = dir && dir.value === 'decrease' ? '-' : '+';
        var counted = form.querySelector('[name="counted"]');
        if (dir && dir.value === 'count' && counted) {
          var c = parseInt(counted.value || '', 10);
          if (!isNaN(c)) { qty = Math.abs(c - before); sign = c >= before ? '+' : '-'; }
        }
      }
      var after = sign === '-' ? before - qty : before + qty;
      box.querySelector('[data-before]').textContent = before;
      box.querySelector('[data-change]').textContent = (sign === '-' ? '−' : '+') + qty;
      box.querySelector('[data-after]').textContent = after;
      var hint = form.querySelector('[data-available-hint]');
      if (hint) hint.textContent = 'Tối đa ' + available + ' — khả dụng';
    }
    form.addEventListener('input', update);
    form.addEventListener('change', update);
    update();
  });

  /* ---------- Chatbot ---------- */
  var panel = document.getElementById('bot-panel');
  if (panel) {
    var log = panel.querySelector('[data-bot-log]');
    var form = panel.querySelector('[data-bot-form]');
    var input = form.querySelector('input[name="q"]');
    var url = panel.getAttribute('data-bot-url');
    document.querySelectorAll('[data-bot-toggle]').forEach(function (b) {
      b.addEventListener('click', function () {
        var open = panel.hasAttribute('hidden');
        panel.toggleAttribute('hidden', !open);
        document.querySelector('.bot-fab').setAttribute('aria-expanded', String(open));
        if (open) input.focus();
      });
    });
    function el(tag, cls, text) {
      var n = document.createElement(tag);
      if (cls) n.className = cls;
      if (text != null) n.textContent = text;
      return n;
    }
    /* Mọi nội dung từ máy chủ được gán bằng textContent / thuộc tính (không innerHTML) → không có XSS */
    function add(text, who, data) {
      data = data || {};
      var div = el('div', 'bot-msg ' + who, text);
      (data.cards || []).forEach(function (c) {
        var card = el('a', 'bot-card');
        card.href = c.url;
        card.appendChild(el('strong', null, c.name));
        card.appendChild(el('span', null, c.time));
        card.appendChild(el('span', null, c.place + ' · ' + c.hospital));
        if (c.distance_km != null) card.appendChild(el('span', 'bot-card-dist', 'Cách ~' + String(c.distance_km).replace('.', ',') + ' km'));
        card.appendChild(el('span', 'bot-card-cta', 'Xem & đăng ký →'));
        div.appendChild(card);
      });
      if ((data.links || []).length) {
        var row = el('div', 'bot-links');
        data.links.forEach(function (l) {
          if (!l.url || l.url.charAt(0) !== '/') return;   // chỉ đường dẫn nội bộ
          var a = el('a', 'btn ghost sm', l.label);
          a.href = l.url;
          row.appendChild(a);
        });
        div.appendChild(row);
      }
      if (data.source) div.appendChild(el('span', 'src', 'Nguồn: ' + data.source));
      log.appendChild(div);
      log.scrollTop = log.scrollHeight;
      return div;
    }
    var coords = null;   // vị trí chỉ giữ trong trang, gửi kèm câu hỏi — không lưu ở máy chủ
    var convId = null;   // cuộc trò chuyện hiện tại (chỉ khi đã đăng nhập — lưu ở máy chủ)
    var convUrl = panel.getAttribute('data-bot-conv-url');
    var loaded = false;
    // Đã đăng nhập: mở trợ lý lần đầu → tải lại cuộc trò chuyện gần nhất (ghi nhớ hội thoại)
    function loadLatest() {
      if (loaded || !convUrl) return;
      loaded = true;
      fetch(convUrl, { credentials: 'same-origin' })
        .then(function (r) { return r.ok ? r.json() : { conversations: [] }; })
        .then(function (d) {
          var c = (d.conversations || [])[0];
          if (!c) return null;
          convId = c.id;
          return fetch(convUrl + '/' + c.id, { credentials: 'same-origin' }).then(function (r) { return r.json(); });
        })
        .then(function (d) {
          if (!d || !d.messages || !d.messages.length) return;
          add('— Tiếp tục cuộc trò chuyện trước —', 'bot pending');
          d.messages.slice(-10).forEach(function (m) { add(m.text, m.role === 'user' ? 'me' : 'bot', m); });
        })
        .catch(function () { /* không tải được lịch sử: vẫn trò chuyện mới bình thường */ });
    }
    document.querySelectorAll('[data-bot-toggle]').forEach(function (b) { b.addEventListener('click', loadLatest); });
    function ask(q) {
      add(q, 'me');
      var pending = add('Đang trả lời…', 'bot pending');
      var body = new FormData();
      body.append('q', q);
      if (convId) body.append('conversation_id', convId);
      if (coords) { body.append('lat', coords.lat); body.append('lng', coords.lng); }
      fetch(url, { method: 'POST', body: body, headers: { 'X-CSRFToken': getCookie('csrftoken') }, credentials: 'same-origin' })
        .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); })
        .then(function (data) { pending.remove(); if (data.conversation_id) convId = data.conversation_id; add(data.answer, 'bot', data); })
        .catch(function () { pending.remove(); add('Xin lỗi, trợ lý đang gặp sự cố. Vui lòng thử lại sau ít phút.', 'bot'); });
    }
    form.addEventListener('submit', function (e) {
      e.preventDefault();
      e.stopPropagation();
      var q = input.value.trim();
      if (!q) return;
      input.value = '';
      ask(q);
    }, true);
    panel.querySelectorAll('[data-bot-suggest] button').forEach(function (b) {
      b.addEventListener('click', function () {
        var q = b.textContent.trim();
        if (!b.hasAttribute('data-bot-geo') || !navigator.geolocation) { ask(q); return; }
        // Xin vị trí khi người dùng chủ động bấm; từ chối → vẫn gợi ý theo tỉnh/thành trong hồ sơ
        navigator.geolocation.getCurrentPosition(function (p) {
          coords = { lat: p.coords.latitude.toFixed(5), lng: p.coords.longitude.toFixed(5) };
          ask(q);
        }, function () { ask(q); }, { timeout: 8000, maximumAge: 600000 });
      });
    });
    var reset = panel.querySelector('[data-bot-reset]');
    if (reset) reset.addEventListener('click', function () {
      var body = new FormData(); body.append('reset', '1');
      fetch(url, { method: 'POST', body: body, headers: { 'X-CSRFToken': getCookie('csrftoken') }, credentials: 'same-origin' });
      while (log.children.length > 1) log.removeChild(log.lastChild);
      coords = null;
      convId = null;   // câu hỏi tiếp theo tạo cuộc trò chuyện mới (cuộc cũ vẫn lưu, xem qua API)
      input.focus();
    });
  }

  /* ---------- Tin tức trang chủ: mở chi tiết ---------- */
  var newsData = document.getElementById('news-data');
  if (newsData) {
    var items = JSON.parse(newsData.textContent);
    var dlg = document.getElementById('news-dialog');
    document.addEventListener('click', function (e) {
      var card = e.target.closest('[data-news-id]');
      if (!card) return;
      showNews(card.getAttribute('data-news-id'));
    });
    document.addEventListener('keydown', function (e) {
      var card = e.target.closest && e.target.closest('[data-news-id]');
      if (card && (e.key === 'Enter' || e.key === ' ')) { e.preventDefault(); showNews(card.getAttribute('data-news-id')); }
    });
    function showNews(id) {
      var item = items.find(function (n) { return String(n.id) === String(id); });
      if (!item) return;
      dlg.querySelector('[data-news-date]').textContent = item.date;
      dlg.querySelector('[data-news-img]').src = item.image;
      dlg.querySelector('[data-news-img]').alt = item.title;
      dlg.querySelector('[data-news-title]').textContent = item.title;
      dlg.querySelector('[data-news-excerpt]').textContent = item.excerpt;
      dlg.querySelector('[data-news-content]').textContent = item.fullContent;
      dlg.showModal();
    }
    var share = document.querySelector('[data-news-share]');
    if (share) share.addEventListener('click', function () {
      var done = function () { share.querySelector('span').textContent = 'Đã sao chép liên kết'; };
      if (navigator.clipboard) { navigator.clipboard.writeText(location.href).then(done, done); } else { done(); }
    });
  }
})();

/* Form kết quả xét nghiệm: chỉ hiện nhóm máu / quy cách khi chọn "Đạt" */
(function () {
  document.addEventListener('change', function (e) {
    var form = e.target.closest && e.target.closest('[data-lab-form]');
    if (!form || e.target.name !== 'result') return;
    form.querySelectorAll('[data-when]').forEach(function (el) {
      el.hidden = el.getAttribute('data-when') !== e.target.value;
    });
  });
})();

/* Điểm hiến: form ghi nhận lượt hiến — hiện/ẩn và bắt buộc trường theo hình thức hiến */
(function () {
  var form = document.getElementById('record-form');
  if (!form) return;
  function sync() {
    var t = (form.querySelector('[name="donation_type"]:checked') || {}).value || 'whole_blood';
    form.querySelectorAll('[data-show-for]').forEach(function (el) {
      var show = el.getAttribute('data-show-for').split(' ').indexOf(t) >= 0;
      el.hidden = !show;
      el.querySelectorAll('input,select').forEach(function (i) { i.disabled = !show; });
    });
    form.querySelectorAll('[data-req-for]').forEach(function (el) { el.hidden = el.getAttribute('data-req-for') !== t; });
    var ml = form.querySelector('[name="volume_ml"]'); if (ml) ml.required = t === 'whole_blood';
    ['component_product_id', 'component_quantity', 'component_unit'].forEach(function (n) {
      var el = form.querySelector('[name="' + n + '"]'); if (el) el.required = t === 'component';
    });
  }
  form.addEventListener('change', sync); sync();
})();

/* Bảng cuộn ngang: cho phép dùng bàn phím để cuộn (WCAG — scrollable-region-focusable) */
(function () {
  document.querySelectorAll('.table-wrap').forEach(function (el) {
    if (el.scrollWidth > el.clientWidth && !el.hasAttribute('tabindex')) {
      el.setAttribute('tabindex', '0');
      el.setAttribute('role', 'region');
      var title = el.closest('section') && el.closest('section').querySelector('.panel-title');
      el.setAttribute('aria-label', title ? title.textContent.trim() : 'Bảng dữ liệu');
    }
  });
})();
