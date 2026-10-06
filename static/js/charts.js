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

    drawn.push(new Chart(document.getElementById('statusChart'), {
      type: 'doughnut',
      data: { labels: status.labels, datasets: [{
        data: status.values,
        backgroundColor: status.labels.map(l => statusColours[l]),
        borderColor: css('--surface'), borderWidth: 2 }] },
      options: { cutout: '58%', plugins: { legend: { position: 'right' } } }
    }));

    drawn.push(new Chart(document.getElementById('regionChart'), {
      type: 'bar',
      data: { labels: region.labels, datasets: [{
        label: 'Complaints', data: region.values,
        backgroundColor: css('--accent'), borderRadius: 2, maxBarThickness: 42 }] },
      options: { plugins: { legend: { display: false } }, scales: { y: countAxis, x: noGrid } }
    }));

    drawn.push(new Chart(document.getElementById('severityChart'), {
      type: 'bar',
      data: { labels: severity.labels, datasets: [{
        label: 'Predictions', data: severity.values,
        backgroundColor: severity.labels.map(l => sev[l] || '#999'), borderRadius: 2, maxBarThickness: 42 }] },
      options: { plugins: { legend: { display: false } }, scales: { y: countAxis, x: noGrid } }
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
