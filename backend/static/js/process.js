/* Quy trình tham gia: cuộn trang → ống thời gian đầy dần, giọt máu chạy theo, đồng hồ đếm phút; ảnh mỗi chặng hé lộ khi tới.
   Nội dung luôn hiển thị khi không có JS; mọi style gán qua CSSOM (CSP không cho thuộc tính style inline). */
(function () {
  'use strict';
  var session = document.querySelector('[data-session]');
  var timeline = session && session.querySelector('[data-timeline]');
  if (!timeline) return;

  var reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  var steps = Array.prototype.slice.call(timeline.querySelectorAll('[data-step]'));
  var fill = timeline.querySelector('[data-rail-fill]');
  var drop = timeline.querySelector('[data-drop]');
  var rail = fill.parentNode;
  var clockMin = session.querySelector('[data-clock-min]');
  var clockStep = session.querySelector('[data-clock-step]');
  var clockBar = session.querySelector('[data-clock-bar]');
  var END_MINUTE = 60;
  session.classList.add('is-enhanced');

  /* Ảnh hé lộ khi chặng vào khung nhìn (một lần) */
  var reveals = timeline.querySelectorAll('[data-reveal]');
  if (reduce || !('IntersectionObserver' in window)) {
    Array.prototype.forEach.call(reveals, function (el) { el.classList.add('is-in'); });
  } else {
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (e) {
        if (e.isIntersecting) { e.target.classList.add('is-in'); io.unobserve(e.target); }
      });
    }, { rootMargin: '0px 0px -12% 0px', threshold: 0.15 });
    Array.prototype.forEach.call(reveals, function (el) { io.observe(el); });
    /* Hiệu ứng lặp (máu chảy, bóp bóng, tim đập) chỉ chạy khi hình đang trong khung nhìn */
    var play = new IntersectionObserver(function (entries) {
      entries.forEach(function (e) { e.target.classList.toggle('is-playing', e.isIntersecting); });
    });
    Array.prototype.forEach.call(reveals, function (el) { play.observe(el); });
  }

  /* Mốc phút của mỗi chặng tại vị trí nút trên trục; nội suy theo điểm đọc (40% chiều cao màn hình) */
  function marks() {
    var top = rail.getBoundingClientRect().top + window.scrollY;
    var list = steps.map(function (s) {
      var node = s.querySelector('.pq-node');
      var r = node.getBoundingClientRect();
      return { y: r.top + window.scrollY + r.height / 2 - top, min: +s.getAttribute('data-minute'), step: s };
    });
    list.push({ y: rail.offsetHeight, min: END_MINUTE, step: null });
    return { top: top, list: list };
  }

  var m = marks();
  var lastMin = -1;
  var ticking = false;

  function update() {
    ticking = false;
    var h = rail.offsetHeight || 1;
    var y = Math.max(0, Math.min(h, window.scrollY + window.innerHeight * 0.4 - m.top));
    var p = y / h;
    fill.style.transform = 'scaleY(' + p.toFixed(4) + ')';
    if (drop && !reduce) drop.style.transform = 'translate3d(0,' + y.toFixed(1) + 'px,0)';

    var minute = 0, current = null;
    for (var i = 0; i < m.list.length - 1; i++) {
      var a = m.list[i], b = m.list[i + 1];
      if (y >= a.y) {
        current = a.step;
        minute = a.min + (b.min - a.min) * Math.min(1, (y - a.y) / Math.max(1, b.y - a.y));
      }
    }
    steps.forEach(function (s) {
      var node = m.list[steps.indexOf(s)];
      s.classList.toggle('is-current', s === current);
      s.classList.toggle('is-passed', y >= node.y && s !== current);
    });
    var whole = Math.round(minute);
    if (whole !== lastMin) {
      lastMin = whole;
      clockMin.textContent = (whole < 10 ? '0' : '') + whole;
      clockBar.style.transform = 'scaleX(' + (whole / END_MINUTE).toFixed(3) + ')';
    }
    var label = current ? current.getAttribute('data-label') : steps[0].getAttribute('data-label');
    if (clockStep.textContent !== label) clockStep.textContent = label;
  }

  function onScroll() {
    if (!ticking) { ticking = true; window.requestAnimationFrame(update); }
  }
  window.addEventListener('scroll', onScroll, { passive: true });
  window.addEventListener('resize', function () { m = marks(); onScroll(); });
  window.addEventListener('load', function () { m = marks(); onScroll(); });   // ảnh tải xong → vị trí đổi
  update();
})();
