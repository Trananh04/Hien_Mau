/* Bản đồ (MapLibre GL + Goong Maps): chọn vị trí (đợt hiến, bệnh viện), bản đồ nhỏ ở chi tiết đợt hiến,
   bản đồ điểm hiến công khai. Nạp sau vendor/maplibre/maplibre-gl.js; cấu hình đọc từ <meta name="map-config">
   (thẻ {% map_head %}). Không có script inline (tương thích Content-Security-Policy).
   API key Goong (tra địa chỉ, gợi ý, chỉ đường) chỉ nằm ở máy chủ — trang gọi qua /dia-chi/… của hệ thống. */
(function () {
  if (!window.maplibregl) return;
  var gl = window.maplibregl;
  var cfgEl = document.querySelector('meta[name="map-config"]');
  var cfg = cfgEl ? cfgEl.dataset : {};

  // Kiểu bản đồ: Goong (cần Map key) → dự phòng ô bản đồ OpenStreetMap khi chưa cấu hình key
  var STYLES = { road: 'goong_map_web', light: 'goong_map_highlight', satellite: 'goong_satellite' };
  function styleUrl(kind) {
    if (cfg.mapKey) return 'https://tiles.goong.io/assets/' + (STYLES[kind] || STYLES.road) + '.json?api_key=' + encodeURIComponent(cfg.mapKey);
    return {
      version: 8,
      sources: { osm: { type: 'raster', tiles: ['https://tile.openstreetmap.org/{z}/{x}/{y}.png'], tileSize: 256,
                        attribution: '&copy; OpenStreetMap' } },
      layers: [{ id: 'osm', type: 'raster', source: 'osm' }]
    };
  }
  var VN = [106.3, 16.0];   // [lng, lat] — MapLibre dùng thứ tự kinh độ trước
  function makeMap(el, center, zoom, opts) {
    var m = new gl.Map(Object.assign({ container: el, style: styleUrl('road'), center: center || VN, zoom: zoom || 5,
                                       attributionControl: { compact: true }, cooperativeGestures: false }, opts || {}));
    m.addControl(new gl.NavigationControl({ showCompass: false }), 'top-right');
    // Kiểu Goong tham chiếu vài icon không có trong sprite → thay ảnh trống để console không báo lỗi liên tục
    m.on('styleimagemissing', function (e) {
      if (!m.hasImage(e.id)) m.addImage(e.id, { width: 1, height: 1, data: new Uint8Array(4) });
    });
    return m;
  }
  function styleSwitcher(map) {
    // Nút đổi kiểu: Đường phố / Vệ tinh (chỉ khi dùng Goong)
    if (!cfg.mapKey) return;
    var box = document.createElement('div');
    box.className = 'maplibregl-ctrl maplibregl-ctrl-group map-style-switch';
    [['road', 'Bản đồ'], ['satellite', 'Vệ tinh']].forEach(function (s, i) {
      var b = document.createElement('button');
      b.type = 'button'; b.textContent = s[1]; b.setAttribute('aria-pressed', i === 0 ? 'true' : 'false');
      b.addEventListener('click', function () {
        map.setStyle(styleUrl(s[0]));
        box.querySelectorAll('button').forEach(function (x) { x.setAttribute('aria-pressed', x === b ? 'true' : 'false'); });
      });
      box.appendChild(b);
    });
    map.addControl({ onAdd: function () { return box; }, onRemove: function () { box.remove(); } }, 'top-left');
  }
  function getJSON(url) {
    return fetch(url, { headers: { Accept: 'application/json' }, credentials: 'same-origin' })
      .then(function (r) { return r.json().then(function (d) { return { ok: r.ok, d: d }; }); });
  }
  function esc(s) { var d = document.createElement('div'); d.textContent = s == null ? '' : s; return d.innerHTML; }

  /* Gợi ý địa chỉ khi gõ (Goong Autocomplete qua máy chủ). onPick({lat, lng, label}) */
  function attachSuggest(input, onPick, nearFn) {
    if (!input || !cfg.suggestUrl || !cfg.mapKey) return;
    var box = document.createElement('div');
    box.className = 'addr-suggest'; box.setAttribute('role', 'listbox'); box.hidden = true;
    input.parentNode.classList.add('addr-suggest-host');
    input.parentNode.appendChild(box);
    input.setAttribute('autocomplete', 'off');
    input.setAttribute('aria-autocomplete', 'list');
    var timer = null, seq = 0, items = [], active = -1, picked = null;
    function close() { box.hidden = true; box.innerHTML = ''; items = []; active = -1; }
    function choose(it) {
      close();
      input.value = picked = it.label;
      getJSON(cfg.placeUrl + '?id=' + encodeURIComponent(it.place_id)).then(function (res) {
        if (res.ok) onPick(res.d);
      }).catch(function () {});
    }
    function paint() {
      box.innerHTML = '';
      items.forEach(function (it, i) {
        var b = document.createElement('button');
        b.type = 'button'; b.className = 'addr-suggest-item' + (i === active ? ' is-active' : '');
        b.setAttribute('role', 'option');
        b.innerHTML = '<strong>' + esc(it.main) + '</strong><span>' + esc(it.secondary) + '</span>';
        b.addEventListener('mousedown', function (e) { e.preventDefault(); choose(it); });
        box.appendChild(b);
      });
      box.hidden = !items.length;
    }
    input.addEventListener('input', function () {
      clearTimeout(timer);
      var q = input.value.trim();
      if (q.length < 3) { close(); return; }
      timer = setTimeout(function () {
        var my = ++seq, near = nearFn ? nearFn() : null;
        var url = cfg.suggestUrl + '?q=' + encodeURIComponent(q) + (near ? '&lat=' + near.lat + '&lng=' + near.lng : '');
        getJSON(url).then(function (res) {
          if (my !== seq) return;            // đã gõ tiếp → bỏ kết quả cũ
          items = res.ok ? res.d.items : []; active = -1; paint();
        }).catch(close);
      }, 300);
    });
    input.addEventListener('keydown', function (e) {
      if (box.hidden) return;
      if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
        e.preventDefault();
        active = (active + (e.key === 'ArrowDown' ? 1 : items.length - 1)) % items.length; paint();
      } else if (e.key === 'Enter' && active >= 0) { e.preventDefault(); choose(items[active]); }
      else if (e.key === 'Escape') close();
    });
    input.addEventListener('blur', function () { setTimeout(close, 150); });
    // picked(): ô đang giữ đúng địa chỉ vừa chọn từ gợi ý → không cần tra lại theo chữ
    return { busy: function () { return !box.hidden || input.value === picked; } };
  }

  /* ---------------------------------------------------------------- Chọn vị trí (form đợt hiến / bệnh viện) */
  var picker = document.querySelector('[data-map-picker]');
  if (picker) {
    var lat = document.getElementById(picker.dataset.latInput);
    var lng = document.getElementById(picker.dataset.lngInput);
    var home = [parseFloat(picker.dataset.defaultLng), parseFloat(picker.dataset.defaultLat)];
    var statusEl = document.querySelector('[data-pin-status]');
    var clearBtn = document.querySelector('[data-clear-pin]');
    var start = lat.value ? [parseFloat(lng.value), parseFloat(lat.value)] : home;
    var pmap = makeMap(picker, start, lat.value ? 16 : 13);
    styleSwitcher(pmap);
    var marker = null;
    var addrEl = document.getElementById(picker.dataset.addressInput || '');
    var provEl = document.getElementById(picker.dataset.provinceInput || '');
    function fmt(v) { return v.toFixed(5).replace('.', ','); }
    function say(msg) { if (statusEl) statusEl.textContent = msg; }
    function show() {
      say(lat.value ? 'Đã ghim tại ' + fmt(parseFloat(lat.value)) + ', ' + fmt(parseFloat(lng.value))
                    : (picker.dataset.emptyText || 'Chưa ghim — sẽ dùng vị trí bệnh viện'));
      if (statusEl) statusEl.classList.toggle('is-set', !!lat.value);
      if (clearBtn) clearBtn.hidden = !lat.value;
    }
    function pin(ll, fly) {
      lat.value = ll.lat.toFixed(6); lng.value = ll.lng.toFixed(6);
      if (marker) marker.setLngLat(ll);
      else {
        marker = new gl.Marker({ color: '#d90429', draggable: true }).setLngLat(ll).addTo(pmap);
        marker.on('dragend', function () { pin(marker.getLngLat()); fillAddress(marker.getLngLat()); });
      }
      if (fly) pmap.flyTo({ center: ll, zoom: 16 });
      show();
    }
    // Bấm / kéo ghim khi ô địa chỉ còn trống → tự điền địa chỉ tại điểm đó (Goong reverse geocode)
    function fillAddress(ll) {
      if (!addrEl || addrEl.value.trim() || !cfg.reverseUrl || !cfg.mapKey) return;
      getJSON(cfg.reverseUrl + '?lat=' + ll.lat + '&lng=' + ll.lng).then(function (res) {
        if (res.ok && !addrEl.value.trim()) { addrEl.value = res.d.label; say('Đã ghim và điền địa chỉ tại điểm này — kiểm tra lại cho đúng.'); }
      }).catch(function () {});
    }
    if (lat.value) pin({ lat: parseFloat(lat.value), lng: parseFloat(lng.value) });
    pmap.on('click', function (e) { pin(e.lngLat); fillAddress(e.lngLat); });
    var homeBtn = document.querySelector('[data-pin-default]');
    if (homeBtn) homeBtn.addEventListener('click', function () { pin({ lng: home[0], lat: home[1] }, true); });
    if (clearBtn) clearBtn.addEventListener('click', function () {
      lat.value = ''; lng.value = ''; if (marker) { marker.remove(); marker = null; }
      show();
    });
    show();

    // Nhập địa chỉ → tự đặt ghim (tra qua máy chủ). Gõ thì hiện gợi ý; chọn gợi ý thì ghim đúng địa điểm đó.
    var findBtn = document.querySelector('[data-geocode]');
    var geoUrl = picker.dataset.geocodeUrl;
    var suggest = attachSuggest(addrEl, function (p) {
      pin({ lat: p.lat, lng: p.lng }, true);
      say('Đã ghim theo địa chỉ đã chọn — kéo ghim nếu cần chỉnh.');
    }, function () { return lat.value ? { lat: lat.value, lng: lng.value } : { lat: home[1], lng: home[0] }; });
    function locate(auto) {
      var a = addrEl.value.trim();
      if (a.length < 4) { if (!auto) say('Nhập địa chỉ trước khi tìm.'); return; }
      say('Đang tìm vị trí theo địa chỉ…');
      var q = '?address=' + encodeURIComponent(a) + '&province=' + encodeURIComponent(provEl ? provEl.value : '');
      getJSON(geoUrl + q).then(function (res) {
        if (!res.ok) { show(); if (!auto) say(res.d.error || 'Không tìm thấy địa chỉ.'); return; }
        pin({ lat: res.d.lat, lng: res.d.lng }, true);
        say('Đã đặt ghim theo địa chỉ — kéo ghim hoặc bấm bản đồ nếu cần chỉnh.');
      }).catch(show);
    }
    if (addrEl && geoUrl) {
      addrEl.addEventListener('change', function () { if (!(suggest && suggest.busy())) locate(true); });
      if (provEl) provEl.addEventListener('change', function () { if (addrEl.value.trim()) locate(true); });
      if (findBtn) findBtn.addEventListener('click', function () { locate(false); });
    }
  }

  /* ---------------------------------------------------------------- Bản đồ nhỏ ở trang chi tiết đợt hiến */
  var mini = document.getElementById('mini-map');
  if (mini) {
    var mll = [parseFloat(mini.dataset.lng), parseFloat(mini.dataset.lat)];
    var mmap = makeMap(mini, mll, 15, { scrollZoom: false });
    new gl.Marker({ color: '#d90429' }).setLngLat(mll)
      .setPopup(new gl.Popup({ offset: 24 }).setText(mini.dataset.label)).addTo(mmap);
  }

  /* ---------------------------------------------------------------- Bản đồ điểm hiến công khai */
  var mapEl = document.querySelector('[data-map-src]');
  if (!mapEl) return;
  var listEl = document.querySelector('[data-map-list]');
  var statusEl2 = document.querySelector('[data-map-status]');
  var layoutEl = document.querySelector('[data-map-layout]');
  var routeEl = document.querySelector('[data-map-route]');
  var sel = {
    province: document.querySelector('[data-map-province]'), type: document.querySelector('[data-map-type]'),
    when: document.querySelector('[data-map-when]')
  };
  var map = makeMap(mapEl, VN, 5);
  styleSwitcher(map);
  var all = [], markers = [];
  var me = null, meMarker = null;   // vị trí người dùng: chỉ gửi lên máy chủ khi bấm "Chỉ đường" (không lưu)

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
  function fit(points) {
    if (!points.length) return;
    var b = new gl.LngLatBounds(points[0], points[0]);
    points.forEach(function (p) { b.extend(p); });
    map.fitBounds(b, { padding: 60, maxZoom: 14, duration: 600 });
  }
  function pinEl(it) {
    // Ghim là <button> để bàn phím và trình đọc màn hình dùng được
    var el = document.createElement('button');
    el.type = 'button';
    el.className = 'map-pin ' + (it.type === 'campaign' ? 'is-campaign' : 'is-hospital') + (it.live ? ' is-live' : '');
    el.setAttribute('aria-label', it.name);
    el.innerHTML = '<i data-lucide="' + (it.type === 'campaign' ? 'calendar-heart' : 'hospital') + '"></i>';
    return el;
  }

  function render() {
    markers.forEach(function (m) { m.remove(); }); markers = [];
    listEl.innerHTML = '';
    var p = sel.province.value, t = sel.type.value, when = sel.when.value, shown = [];
    all.forEach(function (it) {
      if ((p && it.province !== p) || (t && it.type !== t) || !inWindow(it, when)) return;
      it.dist = me ? km(me, it) : null;
      shown.push(it);
    });
    // Có vị trí: xếp theo khoảng cách. Không có: đợt đang diễn ra lên trước
    // Có vị trí: xếp từ gần đến xa theo quãng đường đi thật (Goong), điểm chưa có thì theo đường chim bay
    function meters(x) { return x.road ? x.road.meters : x.dist * 1000; }
    shown.sort(function (a, b) {
      if (me) return meters(a) - meters(b);
      return (b.live === true) - (a.live === true);
    });
    shown.forEach(function (it, idx) {
      var far = it.road ? it.road.distance.replace('.', ',') + ' · ' + it.road.duration : (it.dist != null ? fmtKm(it.dist) : '');
      var html = '<strong>' + esc(it.name) + '</strong><br>' + esc(it.address) + (it.time ? '<br>' + esc(it.time) : '') +
        (far ? '<br>Cách bạn ' + esc(far) + (it.road ? ' đường đi' : '') : '') +
        '<div class="map-popup-actions">' +
        (it.url ? '<a href="' + esc(it.url) + '">Xem &amp; đăng ký</a>' : '') +
        (it.phone ? '<a href="tel:' + esc(it.phone) + '">Gọi ' + esc(it.phone) + '</a>' : '') +
        (cfg.mapKey ? '<button type="button" class="link" data-route-to="' + it.lat + ',' + it.lng + '">Chỉ đường</button>'
                    : '<a target="_blank" rel="noopener" href="https://www.google.com/maps/dir/?api=1&destination=' + it.lat + ',' + it.lng + '">Chỉ đường</a>') +
        '</div>';
      var el = pinEl(it);
      it.marker = new gl.Marker({ element: el, anchor: 'bottom' }).setLngLat([it.lng, it.lat])
        .setPopup(new gl.Popup({ offset: 30, maxWidth: '280px' }).setHTML(html)).addTo(map);
      markers.push(it.marker);
      var btn = document.createElement('button');
      btn.type = 'button'; btn.className = 'map-item';
      var sub = it.type === 'campaign' ? (it.live ? '<em class="live-tag">Đang diễn ra</em> · ' : '') + esc(it.time) + ' · ' + esc(it.area) : esc(it.area);
      btn.innerHTML = (me ? '<span class="mi-rank">' + (idx + 1) + '</span>' : '') +
        '<span class="mi-icon ' + (it.type === 'campaign' ? 'c' : 'h') + '"><i data-lucide="' + (it.type === 'campaign' ? 'calendar-heart' : 'hospital') + '"></i></span>' +
        '<span class="mi-body"><strong>' + esc(it.name) + (far ? ' <small class="mi-dist">' + esc(far) + '</small>' : '') + '</strong>' +
        '<span>' + sub + '</span><span>' + esc(it.address) + '</span></span>';
      it.btn = btn;
      btn.addEventListener('click', function () {
        document.querySelectorAll('.map-item.active').forEach(function (b) { b.classList.remove('active'); });
        btn.classList.add('active'); setView('map');
        map.flyTo({ center: [it.lng, it.lat], zoom: 15 });
        if (!it.marker.getPopup().isOpen()) it.marker.togglePopup();
      });
      listEl.appendChild(btn);
    });
    if (!shown.length) {
      listEl.innerHTML = '<div class="empty"><h3>Không có điểm phù hợp</h3><p>Thử chọn tỉnh/thành, loại điểm hoặc thời gian khác.</p></div>';
    } else if (me) {
      fit(shown.slice(0, 5).map(function (s) { return [s.lng, s.lat]; }).concat([[me.lng, me.lat]]));
    } else {
      fit(shown.map(function (s) { return [s.lng, s.lat]; }));
    }
    if (window.renderIcons) { window.renderIcons(listEl); window.renderIcons(mapEl); }
    return shown;
  }

  // Sau "Tìm nơi gần tôi": chọn sẵn nơi gần nhất — tô sáng trong danh sách, mở thông tin, chỉ đường tới đó
  function pickNearest(shown) {
    var it = shown && shown[0];
    if (!it) return;
    document.querySelectorAll('.map-item.active').forEach(function (b) { b.classList.remove('active'); });
    it.btn.classList.add('active');
    it.btn.scrollIntoView({ block: 'nearest' });
    if (!it.marker.getPopup().isOpen()) it.marker.togglePopup();
    status('Đã xếp từ gần đến xa' + (it.road ? ' theo quãng đường đi' : '') + '. Gần nhất: ' + it.name + '.');
    if (cfg.mapKey) route(it.lat + ',' + it.lng, 'car');
    else fit([[me.lng, me.lat], [it.lng, it.lat]]);
  }

  function status(msg) { statusEl2.textContent = msg || ''; statusEl2.hidden = !msg; }
  function locateMe(then) {
    if (!navigator.geolocation) { status('Trình duyệt không hỗ trợ định vị. Hãy chọn tỉnh/thành.'); return; }
    status('Đang lấy vị trí…');
    navigator.geolocation.getCurrentPosition(function (pos) {
      me = { lat: pos.coords.latitude, lng: pos.coords.longitude };
      if (meMarker) meMarker.remove();
      var dot = document.createElement('span'); dot.className = 'me-pin'; dot.setAttribute('aria-label', 'Vị trí của bạn');
      dot.innerHTML = '<span class="me-pin-label">Bạn ở đây</span><span class="me-dot"></span>';
      meMarker = new gl.Marker({ element: dot, anchor: 'bottom' }).setLngLat([me.lng, me.lat]).addTo(map);
      all.forEach(function (x) { x.road = null; });
      if (then) { then(); return; }
      sel.province.value = '';
      var first = render();
      status('Đang tính quãng đường đi…');
      roadDistances(first).then(function () { pickNearest(render()); });
    }, function () {
      status('Không lấy được vị trí (bạn chưa cho phép). Hãy chọn tỉnh/thành để lọc.');
    }, { enableHighAccuracy: false, timeout: 10000, maximumAge: 300000 });
  }
  // Quãng đường đi thật tới 25 điểm gần nhất (một lượt gọi Goong Distance Matrix qua máy chủ, không lưu vị trí)
  function roadDistances(list) {
    var top = list.slice(0, 25);
    if (!cfg.mapKey || !cfg.distancesUrl || !top.length) return Promise.resolve();
    var url = cfg.distancesUrl + '?from=' + me.lat + ',' + me.lng + '&to=' +
      encodeURIComponent(top.map(function (x) { return x.lat + ',' + x.lng; }).join('|'));
    return getJSON(url).then(function (res) {
      if (res.ok) top.forEach(function (x, i) { x.road = res.d.items[i]; });
    }).catch(function () {});
  }
  var nearBtn = document.querySelector('[data-map-near]');
  if (nearBtn) nearBtn.addEventListener('click', function () { locateMe(); });

  /* Chỉ đường (Goong Directions qua máy chủ): vẽ tuyến đường + quãng đường, thời gian */
  function decode(str) {   // polyline mã hóa (chuẩn Google, độ chính xác 1e-5) → [[lng, lat], …]
    var pts = [], i = 0, la = 0, ln = 0;
    while (i < str.length) {
      [0, 1].forEach(function (k) {
        var b, shift = 0, res = 0;
        do { b = str.charCodeAt(i++) - 63; res |= (b & 0x1f) << shift; shift += 5; } while (b >= 0x20);
        var d = (res & 1) ? ~(res >> 1) : (res >> 1);
        if (k === 0) la += d; else ln += d;
      });
      pts.push([ln / 1e5, la / 1e5]);
    }
    return pts;
  }
  function drawRoute(coords) {
    var data = { type: 'Feature', geometry: { type: 'LineString', coordinates: coords } };
    function add() {
      if (map.getSource('route')) { map.getSource('route').setData(data); return; }
      map.addSource('route', { type: 'geojson', data: data });
      map.addLayer({ id: 'route', type: 'line', source: 'route', layout: { 'line-cap': 'round', 'line-join': 'round' },
                     paint: { 'line-color': '#d90429', 'line-width': 5, 'line-opacity': 0.85 } });
    }
    if (map.isStyleLoaded()) add(); else map.once('idle', add);
    map.__route = coords;
  }
  // Đổi kiểu bản đồ xóa lớp tuyến đường → vẽ lại
  map.on('style.load', function () { if (map.__route) drawRoute(map.__route); });
  function route(to, vehicle) {
    var url = cfg.routeUrl + '?from=' + me.lat + ',' + me.lng + '&to=' + to + '&vehicle=' + (vehicle || 'car');
    if (routeEl) { routeEl.hidden = false; routeEl.innerHTML = '<span class="muted">Đang tìm đường…</span>'; }
    getJSON(url).then(function (res) {
      if (!res.ok) { if (routeEl) routeEl.innerHTML = esc(res.d.error || 'Không tìm được đường đi.'); return; }
      var coords = decode(res.d.polyline);
      drawRoute(coords); fit(coords); setView('map');
      if (routeEl) {
        routeEl.innerHTML = '<strong>' + esc(res.d.distance) + '</strong> · khoảng ' + esc(res.d.duration) +
          ' <span class="route-modes"><button type="button" class="chip-link' + (vehicle === 'bike' ? '' : ' is-active') + '" data-route-mode="car" data-to="' + to + '">Ô tô</button>' +
          '<button type="button" class="chip-link' + (vehicle === 'bike' ? ' is-active' : '') + '" data-route-mode="bike" data-to="' + to + '">Xe máy</button></span>' +
          ' <a class="link" target="_blank" rel="noopener" href="https://www.google.com/maps/dir/?api=1&destination=' + to + '">Mở Google Maps</a>' +
          ' <button type="button" class="link" data-route-clear>Xóa tuyến</button>';
      }
    }).catch(function () { if (routeEl) routeEl.textContent = 'Không tìm được đường đi.'; });
  }
  document.addEventListener('click', function (e) {
    var t = e.target.closest('[data-route-to],[data-route-mode],[data-route-clear]');
    if (!t) return;
    if (t.hasAttribute('data-route-clear')) {
      map.__route = null;
      if (map.getLayer('route')) { map.removeLayer('route'); map.removeSource('route'); }
      if (routeEl) routeEl.hidden = true;
      return;
    }
    var to = t.dataset.routeTo || t.dataset.to, mode = t.dataset.routeMode || 'car';
    if (me) route(to, mode); else locateMe(function () { render(); route(to, mode); });
  });

  // Điện thoại: chuyển Danh sách / Bản đồ (màn rộng hiện cả hai)
  function setView(v) {
    if (!layoutEl) return;
    layoutEl.dataset.view = v;
    document.querySelectorAll('[data-map-view]').forEach(function (b) {
      var on = b.dataset.mapView === v; b.classList.toggle('is-active', on); b.setAttribute('aria-selected', on ? 'true' : 'false');
    });
    if (v === 'map') setTimeout(function () { map.resize(); }, 50);
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
