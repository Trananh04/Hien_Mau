/* Tương tác dùng chung (Lucide cho icon, HTMX cho điều hướng không tải lại trang).

   Cấu trúc:
   - Phần GẮN MỘT LẦN: sự kiện ở mức document (hộp thoại, xác nhận, menu, phím Esc) — vẫn đúng sau khi HTMX thay nội dung.
   - init(root): gắn hành vi cho phần tử trong `root`. Chạy khi tải trang và sau mỗi lần HTMX thay nội dung.
     Mỗi phần tử chỉ được gắn một lần (once) — phần tử được giữ lại qua các trang (hx-preserve) không bị gắn trùng.
*/
(function () {
  'use strict';
  document.documentElement.classList.add('js');   // CSS biết có JS (vd ẩn nút "Lọc" vì bộ lọc tự áp dụng)

  function renderIcons(root) {
    if (window.lucide && window.lucide.createIcons) {
      window.lucide.createIcons({ attrs: { 'stroke-width': 2 }, root: root || document });
    }
  }
  window.renderIcons = renderIcons;

  function $$(root, sel) {
    var list = Array.prototype.slice.call(root.querySelectorAll(sel));
    if (root.matches && root.matches(sel)) list.unshift(root);
    return list;
  }
  function once(el, key) {
    var k = 'init' + key;
    if (el.dataset[k]) return false;
    el.dataset[k] = '1';
    return true;
  }
  function getCookie(name) {
    var match = document.cookie.match(new RegExp('(?:^|; )' + name + '=([^;]*)'));
    return match ? decodeURIComponent(match[1]) : '';
  }
  function setPref(k, v) { document.cookie = k + '=' + v + '; path=/; max-age=31536000; SameSite=Lax'; }

  /* =====================================================================================  GẮN MỘT LẦN */

  /* ---------- Menu tài khoản: đóng khi bấm ra ngoài / Esc */
  document.addEventListener('click', function (e) {
    document.querySelectorAll('[data-menu]').forEach(function (menu) {
      if (!menu.contains(e.target)) {
        menu.querySelector('[data-menu-panel]').setAttribute('hidden', '');
        menu.querySelector('[data-menu-trigger]').setAttribute('aria-expanded', 'false');
      }
    });
  });
  document.addEventListener('keydown', function (e) {
    if (e.key !== 'Escape') return;
    document.querySelectorAll('[data-menu-panel]').forEach(function (p) { p.setAttribute('hidden', ''); });
    var shell = document.querySelector('[data-ws-shell]');
    if (shell && shell.classList.contains('nav-open')) setDrawer(shell, false);
  });

  /* ---------- Phím "/" (như phần mềm kho): nhảy tới ô tìm kiếm của màn hình */
  document.addEventListener('keydown', function (e) {
    if (e.key !== '/' || e.ctrlKey || e.metaKey || e.altKey) return;
    var t = e.target;
    if (t.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName)) return;
    var box = document.querySelector('.ws-content input[type="search"], .ws-content input[name="q"]');
    if (!box) return;
    e.preventDefault();
    box.focus();
    box.select();
  });

  /* ---------- Hộp thoại */
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

  /* ---------- Xác nhận thao tác không hoàn tác được.
     Bắt ở pha capture để chặn TRƯỚC khi HTMX (hx-boost) gửi form; xác nhận xong mới gửi lại (requestSubmit). */
  var pendingForm = null;
  document.addEventListener('submit', function (e) {
    var form = e.target;
    if (!form.hasAttribute('data-confirm') || form.dataset.confirmed) return;
    e.preventDefault();
    e.stopImmediatePropagation();
    if (!form.reportValidity()) return;
    var confirmDialog = document.getElementById('confirm-dialog');
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
    confirmDialog.querySelector('[data-confirm-ok]').textContent = form.getAttribute('data-confirm-label') || 'Xác nhận';
    confirmDialog.showModal();
  }, true);
  document.addEventListener('click', function (e) {
    if (!e.target.closest('[data-confirm-ok]') || !pendingForm) return;
    var form = pendingForm;
    form.dataset.confirmed = '1';
    document.getElementById('confirm-dialog').close();
    var submitter = form._submitter;
    if (submitter && submitter.name) {
      var hidden = document.createElement('input');
      hidden.type = 'hidden'; hidden.name = submitter.name; hidden.value = submitter.value;
      form.appendChild(hidden);
    }
    if (typeof form.requestSubmit === 'function') { form.requestSubmit(); } else { form.submit(); }
  });

  /* ---------- Chống bấm lặp: khóa nút gửi tới khi có phản hồi (hỗ trợ BR-11) */
  document.addEventListener('submit', function (e) {
    var form = e.target;
    if ((form.method || '').toLowerCase() !== 'post' || e.defaultPrevented) return;
    var buttons = form.querySelectorAll('button[type="submit"], button:not([type])');
    setTimeout(function () {
      buttons.forEach(function (b) { b.disabled = true; b.classList.add('is-loading'); });
    }, 0);
  });
  function unlockButtons() {
    document.querySelectorAll('.is-loading').forEach(function (b) { b.disabled = false; b.classList.remove('is-loading'); });
  }
  // Quay lại trang bằng nút Back: mở khóa các nút đã khóa
  window.addEventListener('pageshow', function (e) { if (e.persisted) unlockButtons(); });

  /* ---------- Form kết quả xét nghiệm: chỉ hiện nhóm máu / quy cách khi chọn "Đạt" */
  document.addEventListener('change', function (e) {
    var form = e.target.closest && e.target.closest('[data-lab-form]');
    if (!form || e.target.name !== 'result') return;
    form.querySelectorAll('[data-when]').forEach(function (el) {
      el.hidden = el.getAttribute('data-when') !== e.target.value;
      // trường đang ẩn không bắt buộc, không gửi đi (vd "Không đạt" thì không cần nhóm máu)
      el.querySelectorAll('input, select, textarea').forEach(function (i) { i.disabled = el.hidden; });
    });
  });

  /* ---------- Tự gửi form khi đổi lựa chọn (requestSubmit để đi qua HTMX, không tải lại cả trang).
     Bộ lọc (form.filters, GET) trong khu làm việc: đổi danh sách chọn / ngày là lọc ngay, không cần bấm "Lọc". */
  document.addEventListener('change', function (e) {
    var el = e.target;
    if (!el.form) return;
    var isFilter = el.form.matches('.ws-shell form.filters') && (el.form.method || '').toLowerCase() === 'get' &&
      (el.tagName === 'SELECT' || el.type === 'date' || el.type === 'checkbox');
    var auto = isFilter || el.hasAttribute('data-autosubmit-field') ||
      (el.form.hasAttribute('data-autosubmit') && (el.tagName === 'SELECT' || el.type === 'checkbox'));
    if (!auto) return;
    if (typeof el.form.requestSubmit === 'function') el.form.requestSubmit(); else el.form.submit();
  });

  /* ---------- HTMX: thanh tiến độ khi chuyển trang; khởi tạo lại nội dung mới */
  document.addEventListener('htmx:beforeRequest', function () { document.documentElement.classList.add('is-navigating'); });
  document.addEventListener('htmx:afterRequest', function () { document.documentElement.classList.remove('is-navigating'); });
  document.addEventListener('htmx:sendError', function () {
    unlockButtons();
    alert('Không kết nối được máy chủ. Vui lòng kiểm tra mạng và thử lại.');
  });
  document.addEventListener('htmx:afterSettle', function (e) { init(e.detail.elt || document.body); });

  /* =====================================================================================  init(root) */

  function setDrawer(shell, open) {
    shell.classList.toggle('nav-open', open);
    document.querySelectorAll('[data-ws-toggle]').forEach(function (b) { b.setAttribute('aria-expanded', String(open)); });
  }

  function init(root) {
    root = root || document;
    renderIcons(root);

    /* Tin tức trang chủ: dải chạy ngang dừng khi khuất khỏi màn hình */
    $$(root, '[data-news]').forEach(function (band) {
      if (!once(band, 'News') || !('IntersectionObserver' in window)) return;
      new IntersectionObserver(function (entries) {
        entries.forEach(function (e) { band.classList.toggle('is-paused', !e.isIntersecting); });
      }).observe(band);
    });

    /* Form vừa gửi có lỗi: đưa con trỏ tới trường sai đầu tiên */
    var firstBad = root.querySelector('.field.has-error input:not([type=hidden]), .field.has-error select, .field.has-error textarea');
    if (firstBad) {
      firstBad.scrollIntoView({ block: 'center' });
      firstBad.focus({ preventScroll: true });
    }

    /* Thanh tiến độ: độ rộng từ data-pct (gán qua CSSOM — CSP không cho thuộc tính style inline) */
    $$(root, '[data-pct]').forEach(function (el) {
      var v = parseFloat(String(el.getAttribute('data-pct')).replace(',', '.'));
      el.style.width = (isFinite(v) ? Math.max(0, Math.min(100, v)) : 0) + '%';
    });

    /* Menu điện thoại */
    $$(root, '[data-toggle="mobile-nav"]').forEach(function (btn) {
      if (!once(btn, 'Nav')) return;
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

    /* Menu tài khoản */
    $$(root, '[data-menu]').forEach(function (menu) {
      if (!once(menu, 'Menu')) return;
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

    /* Thanh bên khu làm việc: mở trên điện thoại, thu nhỏ trên máy tính, nhớ nhóm menu đã đóng (cookie) */
    $$(root, '[data-ws-shell]').forEach(function (shell) {
      if (!once(shell, 'Shell')) return;
      shell.querySelectorAll('[data-ws-toggle]').forEach(function (b) {
        b.setAttribute('aria-expanded', 'false');
        b.addEventListener('click', function () { setDrawer(shell, !shell.classList.contains('nav-open')); });
      });
      shell.querySelectorAll('[data-ws-close]').forEach(function (b) {
        b.addEventListener('click', function () { setDrawer(shell, false); });
      });
      var collapseBtn = shell.querySelector('[data-ws-collapse]');
      if (collapseBtn) collapseBtn.addEventListener('click', function () {
        var on = !shell.classList.contains('is-collapsed');
        shell.classList.toggle('is-collapsed', on);
        collapseBtn.setAttribute('aria-pressed', String(on));
        collapseBtn.setAttribute('aria-label', on ? 'Mở rộng menu' : 'Thu gọn menu');
        setPref('ws_collapsed', on ? '1' : '0');
      });
      shell.querySelectorAll('[data-ws-sec]').forEach(function (sec) {
        sec.addEventListener('toggle', function () {
          var closed = [].map.call(document.querySelectorAll('[data-ws-sec]:not([open])'),
            function (s) { return s.getAttribute('data-ws-sec'); });
          setPref('ws_closed', closed.join('.'));
        });
      });
    });

    /* Hộp xác nhận đóng mà không xác nhận → trả form về giá trị cũ (vd ô chọn vai trò vừa đổi) */
    $$(root, '#confirm-dialog').forEach(function (d) {
      if (!once(d, 'Confirm')) return;
      d.addEventListener('close', function () {
        if (pendingForm && !pendingForm.dataset.confirmed) { pendingForm.reset(); pendingForm = null; }
      });
    });

    /* Hộp thoại: bấm ra ngoài để đóng; mở sẵn khi trang cần (form có lỗi / đang sửa) */
    $$(root, 'dialog').forEach(function (d) {
      if (!once(d, 'Dialog')) return;
      d.addEventListener('click', function (e) { if (e.target === d) d.close(); });
      if (d.hasAttribute('data-open-on-load') && typeof d.showModal === 'function') d.showModal();
    });

    /* Toast */
    $$(root, '[data-toast]').forEach(function (t) {
      if (!once(t, 'Toast')) return;
      var close = function () { t.style.transition = 'opacity .25s'; t.style.opacity = '0'; setTimeout(function () { t.remove(); }, 250); };
      t.querySelector('[data-toast-close]').addEventListener('click', close);
      if (!t.classList.contains('error')) setTimeout(close, 6500);
    });

    /* Hiện/ẩn mật khẩu */
    $$(root, '[data-pw-toggle]').forEach(function (btn) {
      if (!once(btn, 'Pw')) return;
      btn.addEventListener('click', function () {
        var input = btn.parentElement.querySelector('input');
        var show = input.type === 'password';
        input.type = show ? 'text' : 'password';
        btn.setAttribute('aria-label', show ? 'Ẩn mật khẩu' : 'Hiện mật khẩu');
      });
    });

    /* Select phụ thuộc: chế phẩm → quy cách */
    $$(root, '[data-product-select]').forEach(function (productSel) {
      var specSel = document.getElementById(productSel.getAttribute('data-product-select'));
      if (!specSel || !once(productSel, 'Product')) return;
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

    /* Xem trước tồn trước/sau cho phiếu kho */
    $$(root, '[data-stock-preview]').forEach(function (form) {
      if (!once(form, 'Preview')) return;
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
        if (hint) hint.textContent = 'Tối đa ' + available + ' (khả dụng)';
      }
      form.addEventListener('input', update);
      form.addEventListener('change', update);
      update();
    });

    /* Điểm hiến: form ghi nhận lượt hiến — hiện/ẩn và bắt buộc trường theo hình thức hiến */
    $$(root, '#record-form').forEach(function (form) {
      if (!once(form, 'Record')) return;
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
    });

    /* Bảng cuộn ngang: cho phép dùng bàn phím để cuộn (WCAG — scrollable-region-focusable) */
    $$(root, '.table-wrap').forEach(function (el) {
      if (el.scrollWidth > el.clientWidth && !el.hasAttribute('tabindex')) {
        el.setAttribute('tabindex', '0');
        el.setAttribute('role', 'region');
        var title = el.closest('section') && el.closest('section').querySelector('.panel-title');
        el.setAttribute('aria-label', title ? title.textContent.trim() : 'Bảng dữ liệu');
      }
    });

    $$(root, '#bot-panel').forEach(function (panel) { if (once(panel, 'Bot')) initChatbot(panel); });
  }

  /* ---------- Trợ lý (khung chat được giữ lại khi chuyển trang: hx-preserve) */
  function initChatbot(panel) {
    var log = panel.querySelector('[data-bot-log]');
    var form = panel.querySelector('[data-bot-form]');
    var input = form.querySelector('input[name="q"]');
    var url = panel.getAttribute('data-bot-url');
    var streamUrl = panel.getAttribute('data-bot-stream-url');
    var sendBtn = form.querySelector('button[type="submit"]');
    var busy = null;     // AbortController của câu đang trả lời (bấm nút gửi lần nữa = Dừng)
    var convUrl = panel.getAttribute('data-bot-conv-url');
    var coords = null;   // vị trí chỉ giữ trong trang, gửi kèm câu hỏi — không lưu ở máy chủ
    var convId = null;   // cuộc trò chuyện hiện tại (chỉ khi đã đăng nhập — lưu ở máy chủ)
    var loaded = false;

    function el(tag, cls, text) {
      var n = document.createElement(tag);
      if (cls) n.className = cls;
      if (text != null) n.textContent = text;
      return n;
    }
    /* Mọi nội dung từ máy chủ được gán bằng textContent / thuộc tính (không innerHTML) → không có XSS */
    function add(text, who, data) {
      var div = el('div', 'bot-msg ' + who, text);
      fill(div, text, data);
      log.appendChild(div);
      log.scrollTop = log.scrollHeight;
      return div;
    }
    function fill(div, text, data) {
      data = data || {};
      div.textContent = text;
      (data.cards || []).forEach(function (c) {
        var card = el('a', 'bot-card');
        card.href = c.url;
        card.appendChild(el('strong', null, c.name));
        card.appendChild(el('span', null, c.time));
        card.appendChild(el('span', null, c.place + ' · ' + c.hospital));
        if (c.distance_km != null) card.appendChild(el('span', 'bot-card-dist', 'Cách ~' + String(c.distance_km).replace('.', ',') + ' km'));
        card.appendChild(el('span', 'bot-card-cta', 'Xem và đăng ký'));
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
    }
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
          add('Cuộc trò chuyện trước', 'bot pending');
          d.messages.slice(-10).forEach(function (m) { add(m.text, m.role === 'user' ? 'me' : 'bot', m); });
        })
        .catch(function () { /* không tải được lịch sử: vẫn trò chuyện mới bình thường */ });
    }
    function setBusy(ctrl) {
      busy = ctrl;
      panel.classList.toggle('is-busy', !!ctrl);
      sendBtn.setAttribute('aria-label', ctrl ? 'Dừng trả lời' : 'Gửi câu hỏi');
      sendBtn.title = ctrl ? 'Dừng' : '';
    }
    function body(q) {
      var b = new FormData();
      b.append('q', q);
      if (convId) b.append('conversation_id', convId);
      if (coords) { b.append('lat', coords.lat); b.append('lng', coords.lng); }
      return b;
    }
    function finish(div, data) {
      div.classList.remove('pending', 'streaming');
      if (data.conversation_id) convId = data.conversation_id;
      fill(div, data.answer, data);
      log.scrollTop = log.scrollHeight;
    }
    var FAIL = 'Xin lỗi, trợ lý đang gặp sự cố. Vui lòng thử lại sau ít phút.';
    // Một lần (JSON) — dùng khi trình duyệt không đọc được luồng
    function askOnce(q, div, ctrl) {
      return fetch(url, { method: 'POST', body: body(q), headers: { 'X-CSRFToken': getCookie('csrftoken') },
                          credentials: 'same-origin', signal: ctrl.signal })
        .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); })
        .then(function (data) { finish(div, data); });
    }
    // Trả lời dần dần (Server-Sent Events qua fetch POST): delta → nối chữ, reset → xóa, done → thay bằng bản cuối
    function askStream(q, div, ctrl) {
      return fetch(streamUrl, { method: 'POST', body: body(q), headers: { 'X-CSRFToken': getCookie('csrftoken') },
                                credentials: 'same-origin', signal: ctrl.signal })
        .then(function (r) {
          if (!r.ok || !r.body) throw new Error(r.status);
          var reader = r.body.getReader(), dec = new TextDecoder(), buf = '', text = '', done = false;
          function handle(block) {
            var ev = 'message', data = '';
            block.split('\n').forEach(function (line) {
              if (line.indexOf('event: ') === 0) ev = line.slice(7);
              else if (line.indexOf('data: ') === 0) data += line.slice(6);
            });
            var d = data ? JSON.parse(data) : {};
            if (ev === 'delta') {
              if (!text) { div.classList.remove('pending'); div.classList.add('streaming'); }
              text += d.text; div.textContent = text; log.scrollTop = log.scrollHeight;
            } else if (ev === 'reset') {
              text = ''; div.textContent = 'Đang tra cứu…'; div.classList.add('pending');
            } else if (ev === 'done') { done = true; finish(div, d); }
            else if (ev === 'error') { done = true; finish(div, { answer: d.message || FAIL }); }
          }
          function pump() {
            return reader.read().then(function (res) {
              if (res.done) { if (!done) throw new Error('cut'); return; }
              buf += dec.decode(res.value, { stream: true });
              var k;
              while ((k = buf.indexOf('\n\n')) >= 0) { handle(buf.slice(0, k)); buf = buf.slice(k + 2); }
              return pump();
            });
          }
          return pump();
        });
    }
    function ask(q) {
      add(q, 'me');
      var div = add('Đang trả lời…', 'bot pending');
      var ctrl = new AbortController();
      setBusy(ctrl);
      var run = streamUrl && window.ReadableStream && window.TextDecoder ? askStream : askOnce;
      run(q, div, ctrl)
        .catch(function () {
          div.classList.remove('pending', 'streaming');
          if (ctrl.signal.aborted) {
            div.textContent = (div.textContent === 'Đang trả lời…' ? '' : div.textContent + ' ') + '(đã dừng)';
          } else {
            fill(div, FAIL);
          }
        })
        .then(function () { if (busy === ctrl) setBusy(null); input.focus(); });
    }

    // Nút mở trợ lý nằm ngoài panel (cũng được giữ lại) — bắt ở document để không gắn trùng
    document.addEventListener('click', function (e) {
      if (!e.target.closest('[data-bot-toggle]')) return;
      var open = panel.hasAttribute('hidden');
      panel.toggleAttribute('hidden', !open);
      var fab = document.querySelector('.bot-fab');
      if (fab) fab.setAttribute('aria-expanded', String(open));
      if (open) { input.focus(); loadLatest(); }
    });
    form.addEventListener('submit', function (e) {
      e.preventDefault();
      e.stopPropagation();
      if (busy) { busy.abort(); return; }         // đang trả lời: nút gửi thành nút Dừng
      var q = input.value.trim();
      if (!q) return;
      input.value = '';
      ask(q);
    }, true);
    panel.querySelectorAll('[data-bot-suggest] button').forEach(function (b) {
      b.addEventListener('click', function () {
        var q = b.textContent.trim();
        if (busy) return;
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
      if (busy) busy.abort();
      var body = new FormData(); body.append('reset', '1');
      fetch(url, { method: 'POST', body: body, headers: { 'X-CSRFToken': getCookie('csrftoken') }, credentials: 'same-origin' });
      while (log.children.length > 1) log.removeChild(log.lastChild);
      coords = null;
      convId = null;   // câu hỏi tiếp theo tạo cuộc trò chuyện mới (cuộc cũ vẫn lưu, xem qua API)
      input.focus();
    });
  }

  init(document);
})();
