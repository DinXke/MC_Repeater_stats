/* Relatieve tijden, gauges en grafieken voor MC Repeater Stats. */
(function () {
  "use strict";

  // --- relatieve tijdstippen -------------------------------------------------
  function relTime(iso) {
    var d = new Date(iso);
    if (isNaN(d)) return iso;
    var s = Math.round((Date.now() - d.getTime()) / 1000);
    if (s < 0) s = 0;
    if (s < 60) return "zonet";
    if (s < 3600) return Math.round(s / 60) + " min geleden";
    if (s < 86400) return Math.round(s / 3600) + " u geleden";
    return Math.round(s / 86400) + " d geleden";
  }
  function updateTimes() {
    document.querySelectorAll("time.reltime").forEach(function (el) {
      var iso = el.getAttribute("datetime");
      el.textContent = relTime(iso);
      el.title = new Date(iso).toLocaleString();
    });
  }
  updateTimes();
  setInterval(updateTimes, 30000);

  // --- gauges (halve cirkel met naald) --------------------------------------
  document.querySelectorAll("[data-gauge]").forEach(function (tile) {
    var canvas = tile.querySelector("canvas");
    var ctx = canvas.getContext("2d");
    var min = parseFloat(tile.dataset.min), max = parseFloat(tile.dataset.max);
    var value = Math.min(max, Math.max(min, parseFloat(tile.dataset.value)));
    var segments = JSON.parse(tile.dataset.segments); // [[vanaf, kleur], ...]
    var w = canvas.width, h = canvas.height, cx = w / 2, cy = h - 8, r = Math.min(w / 2 - 8, h - 16);

    function angle(v) { return Math.PI + ((v - min) / (max - min)) * Math.PI; }
    for (var i = 0; i < segments.length; i++) {
      var from = segments[i][0];
      var to = i + 1 < segments.length ? segments[i + 1][0] : max;
      ctx.beginPath();
      ctx.arc(cx, cy, r, angle(from), angle(to));
      ctx.lineWidth = 14;
      ctx.strokeStyle = segments[i][1];
      ctx.stroke();
    }
    var a = angle(value);
    ctx.beginPath();
    ctx.moveTo(cx, cy);
    ctx.lineTo(cx + (r - 20) * Math.cos(a), cy + (r - 20) * Math.sin(a));
    ctx.lineWidth = 3;
    ctx.strokeStyle = getComputedStyle(document.body).color;
    ctx.stroke();
    ctx.beginPath();
    ctx.arc(cx, cy, 4, 0, 2 * Math.PI);
    ctx.fillStyle = getComputedStyle(document.body).color;
    ctx.fill();
  });

  // --- linkgrafiek per buur --------------------------------------------------
  document.querySelectorAll("tr.nbrow").forEach(function (row) {
    row.style.cursor = "pointer";
    row.addEventListener("click", function () {
      var next = row.nextElementSibling;
      if (next && next.classList.contains("linkchart-row")) {
        next.remove();
        return;
      }
      var cfg = JSON.parse(row.dataset.linkchart);
      var tr = document.createElement("tr");
      tr.className = "linkchart-row";
      var td = document.createElement("td");
      td.colSpan = row.children.length;
      var wrap = document.createElement("div");
      wrap.style.height = "180px";
      var canvas = document.createElement("canvas");
      wrap.appendChild(canvas);
      td.appendChild(wrap);
      tr.appendChild(td);
      row.after(tr);
      fetch("/api/v1/repeaters/" + encodeURIComponent(cfg.slug) +
            "/history?metric=" + encodeURIComponent(cfg.metric) + "&hours=168")
        .then(function (r) { return r.json(); })
        .then(function (res) {
          if (!res.points.length) {
            td.innerHTML = '<span class="muted">Nog geen linkhistoriek voor deze buur.</span>';
            return;
          }
          new Chart(canvas, {
            type: "line",
            data: { datasets: [{
              label: cfg.label,
              data: res.points.map(function (p) { return { x: p[0], y: p[1] }; }),
              borderColor: "#35e08c", backgroundColor: "#35e08c26",
              borderWidth: 2, pointRadius: 1.5, tension: 0.2, fill: true,
            }]},
            options: {
              responsive: true, maintainAspectRatio: false, animation: false,
              scales: {
                x: { type: "time", time: { tooltipFormat: "dd/MM HH:mm" },
                     ticks: { maxTicksLimit: 8 }, grid: { display: false } },
                y: { title: { display: true, text: "dB" } },
              },
              plugins: { legend: { display: true } },
            },
          });
        });
    });
  });

  // --- grafieken -------------------------------------------------------------
  var palette = ["#35e08c", "#ffb454", "#4cc9f0", "#c77dff"];
  if (typeof Chart !== "undefined") {
    Chart.defaults.color = "#7d8fa0";
    Chart.defaults.borderColor = "rgba(125, 143, 160, .15)";
  }
  document.querySelectorAll("[data-chart]").forEach(function (canvas) {
    if (typeof Chart === "undefined") return;
    var cfg = JSON.parse(canvas.dataset.chart);
    Promise.all(cfg.metrics.map(function (m) {
      return fetch("/api/v1/repeaters/" + encodeURIComponent(cfg.slug) +
                   "/history?metric=" + encodeURIComponent(m) + "&hours=" + cfg.hours)
        .then(function (r) { return r.json(); });
    })).then(function (results) {
      var datasets = results.map(function (res, i) {
        return {
          label: cfg.labels[i],
          data: res.points.map(function (p) { return { x: p[0], y: p[1] }; }),
          borderColor: palette[i % palette.length],
          backgroundColor: palette[i % palette.length] + "33",
          borderWidth: 2, pointRadius: 0, tension: 0.2, fill: cfg.metrics.length === 1,
        };
      });
      new Chart(canvas, {
        type: "line",
        data: { datasets: datasets },
        options: {
          responsive: true, maintainAspectRatio: false, animation: false,
          interaction: { mode: "nearest", axis: "x", intersect: false },
          scales: {
            x: {
              type: "time",
              time: { tooltipFormat: "dd/MM HH:mm" },
              ticks: { maxTicksLimit: 8 },
              grid: { display: false },
            },
            y: { title: { display: !!cfg.unit, text: cfg.unit || "" } },
          },
          plugins: { legend: { display: cfg.metrics.length > 1 } },
        },
      });
    });
  });
})();
