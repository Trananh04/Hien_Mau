/* Bản đồ (Leaflet): chọn vị trí đợt hiến, bản đồ nhỏ ở chi tiết đợt, bản đồ điểm hiến công khai.
   Nạp sau vendor/leaflet/leaflet.js. Không có script inline (tương thích Content-Security-Policy). */
(function () {
  if (!window.L) return;
  var script = document.currentScript;
  var STATIC = script ? script.src.replace(/js\/maps\.js.*$/, '') : '/static/';
  L.Icon.Default.imagePath = STATIC + 'vendor/leaflet/images/';
  var TILES = 'https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png';
  function tiles(map) { L.tileLayer(TILES, { maxZoom: 19, attribution: '&copy; OpenStreetMap' }).addTo(map); }

  /* Chọn vị trí đợt hiến (form tạo/sửa đợt) */
  var picker = document.querySelector('[data-map-picker]');
  if (picker) {
    var lat = document.getElementById(picker.dataset.latInput);
    var lng = document.getElementById(picker.dataset.lngInput);
    var start = [parseFloat(lat.value) || parseFloat(picker.dataset.defaultLat),
                 parseFloat(lng.value) || parseFloat(picker.dataset.defaultLng)];
    var pmap = L.map(picker).setView(start, 14);
    tiles(pmap);
    var marker = lat.value ? L.marker(start).addTo(pmap) : null;
    pmap.on('click', function (e) {
      lat.value = e.latlng.lat.toFixed(6); lng.value = e.latlng.lng.toFixed(6);
      if (marker) marker.setLatLng(e.latlng); else marker = L.marker(e.latlng).addTo(pmap);
    });
    var clear = document.querySelector('[data-clear-pin]');
    if (clear) clear.addEventListener('click', function () {
      lat.value = ''; lng.value = ''; if (marker) { pmap.removeLayer(marker); marker = null; }
    });
  }

  /* Bản đồ nhỏ ở trang chi tiết đợt hiến */
  var mini = document.getElementById('mini-map');
  if (mini) {
    var mlat = parseFloat(mini.dataset.lat), mlng = parseFloat(mini.dataset.lng);
    var mmap = L.map(mini, { scrollWheelZoom: false }).setView([mlat, mlng], 15);
    tiles(mmap);
    L.marker([mlat, mlng]).addTo(mmap).bindPopup(mini.dataset.label);
  }

  /* Bản đồ điểm hiến công khai */
  var mapEl = document.querySelector('[data-map-src]');
  if (!mapEl) return;
  var listEl = document.querySelector('[data-map-list]');
  var provinceSel = document.querySelector('[data-map-province]');
  var typeSel = document.querySelector('[data-map-type]');
  var map = L.map(mapEl).setView([16.0, 106.3], 5);   // toàn Việt Nam; có điểm thì tự thu phóng vừa
  tiles(map);
  var campaignIcon = L.divIcon({ className: '', html: '<span class="blood sm campaign-pin"><span></span></span>', iconSize: [30, 30], iconAnchor: [15, 28] });
  var all = []; var layer = L.layerGroup().addTo(map);

  function esc(s) { var d = document.createElement('div'); d.textContent = s || ''; return d.innerHTML; }
  function render() {
    layer.clearLayers(); listEl.innerHTML = '';
    var p = provinceSel.value, t = typeSel.value, shown = [];
    all.forEach(function (it) {
      if ((p && it.province !== p) || (t && it.type !== t)) return;
      shown.push(it);
      var popup = '<strong>' + esc(it.name) + '</strong><br>' + esc(it.address) + (it.time ? '<br>' + esc(it.time) : '') +
        (it.url ? '<br><a href="' + esc(it.url) + '">Xem &amp; đăng ký</a>' : '') +
        '<br><a target="_blank" rel="noopener" href="https://www.google.com/maps/dir/?api=1&destination=' + it.lat + ',' + it.lng + '">Chỉ đường</a>';
      var opts = { title: it.name, alt: it.name, keyboard: true };  // tên truy cập được cho trình đọc màn hình
      if (it.type === 'campaign') opts.icon = campaignIcon;
      it.marker = L.marker([it.lat, it.lng], opts).bindPopup(popup).addTo(layer);
      var btn = document.createElement('button');
      btn.type = 'button'; btn.className = 'map-item';
      btn.innerHTML = '<span class="mi-icon ' + (it.type === 'campaign' ? 'c' : 'h') + '"><i data-lucide="' + (it.type === 'campaign' ? 'calendar-heart' : 'hospital') + '"></i></span>' +
        '<span><strong>' + esc(it.name) + '</strong><span>' + esc(it.type === 'campaign' ? it.time + ' · ' + it.area : it.area) + '</span><span>' + esc(it.address) + '</span></span>';
      btn.addEventListener('click', function () {
        document.querySelectorAll('.map-item.active').forEach(function (b) { b.classList.remove('active'); });
        btn.classList.add('active'); map.setView([it.lat, it.lng], 15); it.marker.openPopup();
      });
      listEl.appendChild(btn);
    });
    if (!shown.length) {
      listEl.innerHTML = '<div class="empty"><h3>Không có điểm phù hợp</h3><p>Thử chọn tỉnh/thành hoặc loại điểm khác.</p></div>';
    } else {
      map.fitBounds(L.latLngBounds(shown.map(function (s) { return [s.lat, s.lng]; })).pad(0.2), { maxZoom: 14 });
    }
    window.renderIcons(listEl);
  }
  fetch(mapEl.dataset.mapSrc).then(function (r) { return r.json(); }).then(function (data) {
    all = data.hospitals.concat(data.campaigns); render();
  }).catch(function () {
    listEl.innerHTML = '<div class="empty"><h3>Không tải được dữ liệu bản đồ</h3><p>Vui lòng tải lại trang.</p></div>';
  });
  provinceSel.addEventListener('change', render); typeSel.addEventListener('change', render);
})();
