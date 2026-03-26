/* Chart.js global theme for Finance Hub */
(function () {
  if (typeof Chart === 'undefined') return;

  Chart.defaults.font.family = '"SF Pro Display","PingFang SC","Helvetica Neue",sans-serif';
  Chart.defaults.font.size = 12;
  Chart.defaults.color = '#6a8088';
  Chart.defaults.plugins.legend.display = false;
  Chart.defaults.plugins.tooltip.backgroundColor = 'rgba(24,48,58,0.88)';
  Chart.defaults.plugins.tooltip.cornerRadius = 12;
  Chart.defaults.plugins.tooltip.padding = 10;
  Chart.defaults.plugins.tooltip.titleFont = { weight: '700', size: 13 };
  Chart.defaults.plugins.tooltip.bodyFont = { size: 12 };
  Chart.defaults.elements.line.tension = 0.35;
  Chart.defaults.elements.line.borderWidth = 2.5;
  Chart.defaults.elements.point.radius = 0;
  Chart.defaults.elements.point.hoverRadius = 5;
  Chart.defaults.scale.grid = { color: 'rgba(130,156,168,0.10)' };
})();
