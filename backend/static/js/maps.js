/* Bản đồ (Leaflet): chọn vị trí đợt hiến, bản đồ nhỏ ở chi tiết đợt, bản đồ điểm hiến công khai.
   Nạp sau vendor/leaflet/leaflet.js. Không có script inline (tương thích Content-Security-Policy). */
(function () {
  if (!window.L) return;
  var script = document.currentScript;
  var STATIC = script ? script.src.replace(/js\/maps\.js.*$/, '') : '/static/';
  L.Icon.Default.imagePath = STATIC + 'vendor/leaflet/images/';
  // Máy chủ ô bản đồ OSM bắt buộc có Referer. Trang đặt Referrer-Policy: same-origin (không gửi ra ngoài), nên riêng
  // ảnh ô bản đồ được gửi tên miền của hệ thống (không kèm đường dẫn trang) — nếu không OSM trả ô "Access blocked".
  var TILES = 'https://tile.openstreetmap.org/{z}/{x}/{y}.png';
  function tiles(map) {
    L.tileLayer(TILES, {
      maxZoom: 19, referrerPolicy: 'strict-origin-when-cross-origin',
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">OpenStreetMap</a>'
    }).addTo(map);
  }

  /* Chọn vị trí đợt hiến (form tạo/sửa đợt): bấm bản đồ để ghim; dòng trạng thái thay cho ô gõ vĩ độ / kinh độ */
  var picker = document.querySelector('[data-map-picker]');
  if (picker) {
    var lat = document.getElementById(picker.dataset.latInput);
    var lng = document.getElementById(picker.dataset.lngInput);
    var home = [parseFloat(picker.dataset.defaultLat), parseFloat(picker.dataset.defaultLng)];
    var statusEl = document.querySelector('[data-pin-status]');
    var clearBtn = document.querySelector('[data-clear-pin]');
    var start = lat.value ? [parseFloat(lat.value), parseFloat(lng.value)] : home;
    var pmap = L.map(picker).setView(start, lat.value ? 16 : 14);
    tiles(pmap);
    var marker = null;
    function fmt(v) { return v.toFixed(5).replace('.', ','); }
    function show() {
      if (statusEl) statusEl.textContent = lat.value
        ? 'Đã ghim tại ' + fmt(parseFloat(lat.value)) + ', ' + fmt(parseFloat(lng.value))
        : (picker.dataset.emptyText || 'Chưa ghim — sẽ dùng vị trí bệnh viện');
      if (statusEl) statusEl.classList.toggle('is-set', !!lat.value);
      if (clearBtn) clearBtn.hidden = !lat.value;
    }
    function pin(ll) {
      lat.value = ll.lat.toFixed(6); lng.value = ll.lng.toFixed(6);
      if (marker) marker.setLatLng(ll); else marker = L.marker(ll).addTo(pmap);
      show();
    }
    if (lat.value) marker = L.marker(start).addTo(pmap);
    pmap.on('click', function (e) { pin(e.latlng); });
    var homeBtn = document.querySelector('[data-pin-default]');
    if (homeBtn) homeBtn.addEventListener('click', function () {
      var ll = L.latLng(home[0], home[1]); pin(ll); pmap.setView(ll, 16);
    });
    if (clearBtn) clearBtn.addEventListener('click', function () {
      lat.value = ''; lng.value = ''; if (marker) { pmap.removeLayer(marker); marker = null; }
      show();
    });
    show();

    /* Nhập địa chỉ → tự đặt ghim (tra qua máy chủ: /dia-chi/vi-tri/). Vẫn bấm bản đồ để chỉnh lại được. */
    var addrEl = document.getElementById(picker.dataset.addressInput || '');
    var provEl = document.getElementById(picker.dataset.provinceInput || '');
    var findBtn = document.querySelector('[data-geocode]');
    var geoUrl = picker.dataset.geocodeUrl;
    function locate(auto) {
      var a = addrEl.value.trim();
      if (a.length < 4) { if (!auto && statusEl) statusEl.textContent = 'Nhập địa chỉ trước khi tìm.'; return; }
      if (statusEl) statusEl.textContent = 'Đang tìm vị trí theo địa chỉ…';
      var q = '?address=' + encodeURIComponent(a) + '&province=' + encodeURIComponent(provEl ? provEl.value : '');
      fetch(geoUrl + q, { headers: { Accept: 'application/json' }, credentials: 'same-origin' })
        .then(function (r) { return r.json().then(function (d) { return { ok: r.ok, d: d }; }); })
        .then(function (res) {
          if (!res.ok) { show(); if (!auto && statusEl) statusEl.textContent = res.d.error || 'Không tìm thấy địa chỉ.'; return; }
          var ll = L.latLng(res.d.lat, res.d.lng);
          pin(ll); pmap.setView(ll, 16);
          if (statusEl) statusEl.textContent = 'Đã đặt ghim theo địa chỉ — bấm bản đồ nếu cần chỉnh.';
        })
        .catch(function () { show(); });
    }
    if (addrEl && geoUrl) {
      addrEl.addEventListener('change', function () { locate(true); });
      if (provEl) provEl.addEventListener('change', function () { if (addrEl.value.trim()) locate(true); });
      if (findBtn) findBtn.addEventListener('click', function () { locate(false); });
    }
  }

  /* Bản đồ nhỏ ở trang chi tiết đợt hiến */
  var mini = document.getElementById('mini-map');
  if (mini) {
    var mlat = parseFloat(mini.dataset.lat), mlng = parseFloat(mini.dataset.lng);
    var mmap = L.map(mini, { scrollWheelZoom: false }).setView([mlat, mlng], 15);
    tiles(mmap);
    L.marker([mlat, mlng]).addTo(mmap).bindPopup(mini.dataset.label);
  }

  /* Bản đồ điểm hiến công khai: gần tôi (tính trên trình duyệt), đợt hiến theo thời gian */
  var mapEl = document.querySelector('[data-map-src]');
  if (!mapEl) return;
  var listEl = document.querySelector('[data-map-list]');
  var statusEl = document.querySelector('[data-map-status]');
  var layoutEl = document.querySelector('[data-map-layout]');
  var sel = {
    province: document.querySelector('[data-map-province]'), type: document.querySelector('[data-map-type]'),
    when: document.querySelector('[data-map-when]')
  };
  var map = L.map(mapEl).setView([16.0, 106.3], 5);   // toàn Việt Nam; có điểm thì tự thu phóng vừa
  tiles(map);
  var campaignIcon = L.divIcon({ className: '', html: '<span class="blood sm campaign-pin"><span></span></span>', iconSize: [30, 30], iconAnchor: [15, 28] });
  var all = []; var layer = L.layerGroup().addTo(map);
  var me = null, meLayer = null;   // vị trí người dùng: chỉ giữ trong trang, không gửi đi

  function esc(s) { var d = document.createElement('div'); d.textContent = s == null ? '' : s; return d.innerHTML; }
  function km(a, b) {
    var r = Math.PI / 180, dLat = (b.lat - a.lat) * r, dLng = (b.lng - a.lng) * r;
    var h = Math.sin(dLat / 2) * Math.sin(dLat / 2) + Math.cos(a.lat * r) * Math.cos(b.lat * r) * Math.sin(dLng / 2) * Math.sin(dLng / 2);
    return 6371 * 2 * Math.asin(Math.sqrt(h));
  }
  function fmtKm(d) { return d < 10 ? d.toFixed(1).replace('.', ',') + ' km' : Math.round(d) + ' km'; }
  function inWindow(it, when) {
    if (it.type !== 'campaign' || !when) return true;
    var start = new Date(it.start), end = new Date(it.end), now = new Date();
    var limit = new Date(now); limit.setHours(23, 59, 59, 999);
    if (when === 'week') limit.setDate(limit.getDate() + 7);
    return start <= limit && end >= now;
  }

  function render() {
    layer.clearLayers(); listEl.innerHTML = '';
    var p = sel.province.value, t = sel.type.value, when = sel.when.value, shown = [];
    all.forEach(function (it) {
      if ((p && it.province !== p) || (t && it.type !== t) || !inWindow(it, when)) return;
      it.dist = me ? km(me, it) : null;
      shown.push(it);
    });
    // Có vị trí: xếp theo khoảng cách. Không có: đợt đang diễn ra lên trước
    shown.sort(function (a, b) {
      if (me) return a.dist - b.dist;
      return (b.live === true) - (a.live === true);
    });
    shown.forEach(function (it) {
      var popup = '<strong>' + esc(it.name) + '</strong><br>' + esc(it.address) + (it.time ? '<br>' + esc(it.time) : '') +
        (it.dist != null ? '<br>Cách bạn ' + fmtKm(it.dist) : '') +
        (it.url ? '<br><a href="' + esc(it.url) + '">Xem &amp; đăng ký</a>' : '') +
        (it.phone ? '<br><a href="tel:' + esc(it.phone) + '">Gọi ' + esc(it.phone) + '</a>' : '') +
        '<br><a target="_blank" rel="noopener" href="https://www.google.com/maps/dir/?api=1&destination=' + it.lat + ',' + it.lng + '">Chỉ đường</a>';
      var opts = { title: it.name, alt: it.name, keyboard: true };  // tên truy cập được cho trình đọc màn hình
      if (it.type === 'campaign') opts.icon = campaignIcon;
      it.marker = L.marker([it.lat, it.lng], opts).bindPopup(popup).addTo(layer);
      var btn = document.createElement('button');
      btn.type = 'button'; btn.className = 'map-item';
      var sub = it.type === 'campaign' ? (it.live ? '<em class="live-tag">Đang diễn ra</em> · ' : '') + esc(it.time) + ' · ' + esc(it.area) : esc(it.area);
      btn.innerHTML = '<span class="mi-icon ' + (it.type === 'campaign' ? 'c' : 'h') + '"><i data-lucide="' + (it.type === 'campaign' ? 'calendar-heart' : 'hospital') + '"></i></span>' +
        '<span class="mi-body"><strong>' + esc(it.name) + (it.dist != null ? ' <small class="mi-dist">' + fmtKm(it.dist) + '</small>' : '') + '</strong>' +
        '<span>' + sub + '</span><span>' + esc(it.address) + '</span></span>';
      btn.addEventListener('click', function () {
        document.querySelectorAll('.map-item.active').forEach(function (b) { b.classList.remove('active'); });
        btn.classList.add('active'); setView('map'); map.setView([it.lat, it.lng], 15); it.marker.openPopup();
      });
      listEl.appendChild(btn);
    });
    if (!shown.length) {
      listEl.innerHTML = '<div class="empty"><h3>Không có điểm phù hợp</h3><p>Thử chọn tỉnh/thành, loại điểm hoặc thời gian khác.</p></div>';
    } else if (me) {
      var near = shown.slice(0, 5).map(function (s) { return [s.lat, s.lng]; }).concat([[me.lat, me.lng]]);
      map.fitBounds(L.latLngBounds(near).pad(0.2), { maxZoom: 14 });
    } else {
      map.fitBounds(L.latLngBounds(shown.map(function (s) { return [s.lat, s.lng]; })).pad(0.2), { maxZoom: 14 });
    }
    window.renderIcons(listEl);
  }

  function status(msg) { statusEl.textContent = msg || ''; statusEl.hidden = !msg; }
  var nearBtn = document.querySelector('[data-map-near]');
  if (nearBtn) nearBtn.addEventListener('click', function () {
    if (!navigator.geolocation) { status('Trình duyệt không hỗ trợ định vị. Hãy chọn tỉnh/thành.'); return; }
    status('Đang lấy vị trí…');
    navigator.geolocation.getCurrentPosition(function (pos) {
      me = { lat: pos.coords.latitude, lng: pos.coords.longitude };
      if (meLayer) map.removeLayer(meLayer);
      meLayer = L.circleMarker([me.lat, me.lng], { radius: 8, color: '#fff', weight: 3, fillColor: '#2563eb', fillOpacity: 1 })
        .bindTooltip('Vị trí của bạn').addTo(map);
      sel.province.value = '';
      status('Đã xếp theo khoảng cách tới vị trí của bạn (chỉ dùng trên trình duyệt này).');
      render();
    }, function () {
      status('Không lấy được vị trí (bạn chưa cho phép). Hãy chọn tỉnh/thành để lọc.');
    }, { enableHighAccuracy: false, timeout: 10000, maximumAge: 300000 });
  });

  // Điện thoại: chuyển Danh sách / Bản đồ (màn rộng hiện cả hai)
  function setView(v) {
    if (!layoutEl) return;
    layoutEl.dataset.view = v;
    document.querySelectorAll('[data-map-view]').forEach(function (b) {
      var on = b.dataset.mapView === v; b.classList.toggle('is-active', on); b.setAttribute('aria-selected', on ? 'true' : 'false');
    });
    if (v === 'map') setTimeout(function () { map.invalidateSize(); }, 50);
  }
  document.querySelectorAll('[data-map-view]').forEach(function (b) {
    b.addEventListener('click', function () { setView(b.dataset.mapView); });
  });

  fetch(mapEl.dataset.mapSrc).then(function (r) { return r.json(); }).then(function (data) {
    all = data.hospitals.concat(data.campaigns); render();
  }).catch(function () {
    listEl.innerHTML = '<div class="empty"><h3>Không tải được dữ liệu bản đồ</h3><p>Vui lòng tải lại trang.</p></div>';
  });
  ['province', 'type', 'when'].forEach(function (k) { sel[k].addEventListener('change', render); });
})();
