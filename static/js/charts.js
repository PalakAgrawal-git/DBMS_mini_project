// Draws the four report charts. Used by templates/reports.html (data from
// /api/*) and by the browser demo (data straight from sql.js) -- both pass
// the same shape: { status, region, severity, trend }, each { labels, values }.
//
// Pulling this out of reports.html and index.html's drawCharts() removes a
// second, slowly-drifting copy of the same chart styling -- same idea as
// the shared heatguard.css and the sev_tag/status_tag macros.
const HeatCharts = (() => {
  let drawn = [];

  const css = name => getComputedStyle(document.documentElement).getPropertyValue(name).trim();

  function setup() {
    Chart.defaults.font.family = css('--font-sans');
    Chart.defaults.font.size = 12;
    Chart.defaults.color = css('--muted');
    Chart.defaults.borderColor = css('--rule');
    Chart.defaults.maintainAspectRatio = false;   // .chartbox decides the height
    Chart.defaults.responsive = true;
    Chart.defaults.plugins.legend.labels.boxWidth = 10;
    Chart.defaults.plugins.legend.labels.boxHeight = 10;
  }

  // Bar charts with whole-number counts shouldn't show 0.5, 1.5 ...
  const countAxis = { beginAtZero: true, ticks: { precision: 0 } };
  const noGrid = { grid: { display: false } };

  // Draws the value above each bar -- no extra plugin needed for this.
  const barValueLabels = {
    id: 'barValueLabels',
    afterDatasetsDraw(chart) {
      const { ctx } = chart;
      chart.data.datasets.forEach((ds, i) => {
        const meta = chart.getDatasetMeta(i);
        if (meta.type !== 'bar') return;
        ctx.save();
        ctx.fillStyle = css('--ink') || '#212529';
        ctx.font = '600 11px ' + css('--font-sans');
        ctx.textAlign = 'center';
        meta.data.forEach((bar, idx) => {
          const v = ds.data[idx];
          if (v === 0 || v == null) return;
          ctx.fillText(v, bar.x, bar.y - 6);
        });
        ctx.restore();
      });
    }
  };

  // Puts the total in the middle of the doughnut, like a simple KPI.
  const doughnutTotal = {
    id: 'doughnutTotal',
    afterDraw(chart) {
      if (chart.config.type !== 'doughnut') return;
      const total = chart.data.datasets[0].data.reduce((a, b) => a + b, 0);
      const { ctx, chartArea: { left, right, top, bottom } } = chart;
      const x = (left + right) / 2, y = (top + bottom) / 2;
      ctx.save();
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      ctx.fillStyle = css('--ink') || '#212529';
      ctx.font = '700 20px ' + css('--font-sans');
      ctx.fillText(total, x, y - 8);
      ctx.fillStyle = css('--muted') || '#6c757d';
      ctx.font = '11px ' + css('--font-sans');
      ctx.fillText('total', x, y + 12);
      ctx.restore();
    }
  };

  // '2026-10-03' -> '3 Oct'
  const shortDate = d => {
    const t = new Date(d + 'T00:00:00');
    return isNaN(t) ? d : t.toLocaleDateString('en-GB', { day: 'numeric', month: 'short' });
  };

  function draw({ status, region, severity, trend }) {
    drawn.forEach(c => c.destroy());
    drawn = [];
    setup();

    const sev = { Low: css('--sev-low'), Moderate: css('--sev-moderate'),
                  High: css('--sev-high'), Extreme: css('--sev-extreme') };
    const statusColours = {
      'Open': css('--status-open'),
      'In Progress': css('--status-progress'),
      'Resolved': css('--status-resolved'),
    };

    const total = status.values.reduce((a, b) => a + b, 0);
    drawn.push(new Chart(document.getElementById('statusChart'), {
      type: 'doughnut',
      data: { labels: status.labels, datasets: [{
        data: status.values,
        backgroundColor: status.labels.map(l => statusColours[l]),
        borderColor: css('--surface'), borderWidth: 2 }] },
      options: { cutout: '62%', plugins: { legend: { position: 'right' },
        title: { display: true, text: `Complaints by status (${total} total)`, font: { size: 12 } } } },
      plugins: [doughnutTotal]
    }));

    // region chart: a different colour per bar so it reads differently from the severity chart
    const regionPalette = ['#0d6efd', '#6610f2', '#20c997', '#fd7e14', '#6f42c1', '#0dcaf0'];
    drawn.push(new Chart(document.getElementById('regionChart'), {
      type: 'bar',
      data: { labels: region.labels, datasets: [{
        label: 'Complaints', data: region.values,
        backgroundColor: region.labels.map((_, i) => regionPalette[i % regionPalette.length]),
        borderRadius: 2, maxBarThickness: 42 }] },
      options: { plugins: { legend: { display: false } }, scales: { y: countAxis, x: noGrid } },
      plugins: [barValueLabels]
    }));

    drawn.push(new Chart(document.getElementById('severityChart'), {
      type: 'bar',
      data: { labels: severity.labels, datasets: [{
        label: 'Predictions', data: severity.values,
        backgroundColor: severity.labels.map(l => sev[l] || '#999'), borderRadius: 2, maxBarThickness: 42 }] },
      options: { plugins: { legend: { display: false } }, scales: { y: countAxis, x: noGrid } },
      plugins: [barValueLabels]
    }));

    drawn.push(new Chart(document.getElementById('trendChart'), {
      type: 'line',
      data: { labels: trend.labels.map(shortDate), datasets: [{
        label: 'Predictions', data: trend.values,
        borderColor: css('--sev-extreme'), backgroundColor: 'rgba(158, 28, 28, .08)',
        pointBackgroundColor: css('--sev-extreme'), pointRadius: 3,
        fill: true, tension: 0 }] },
      options: { plugins: { legend: { display: false } }, scales: { y: countAxis, x: noGrid } }
    }));
  }

  return { draw };
})();
