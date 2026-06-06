/** Lightweight toast — auto-dismiss banner at top of viewport. */
let _container = null;

function ensureContainer() {
  if (_container && document.body.contains(_container)) return _container;
  _container = document.createElement('div');
  _container.id = 'trustbond-toast-root';
  _container.style.cssText =
    'position:fixed;top:16px;right:16px;z-index:99999;display:flex;flex-direction:column;gap:8px;max-width:min(420px,92vw);pointer-events:none;';
  document.body.appendChild(_container);
  return _container;
}

function showToast(message, type = 'info', durationMs = 6000) {
  const root = ensureContainer();
  const el = document.createElement('div');
  const colors = {
    success: { bg: '#dcfce7', border: '#16a34a', text: '#14532d' },
    error: { bg: '#fee2e2', border: '#dc2626', text: '#7f1d1d' },
    warning: { bg: '#fef3c7', border: '#d97706', text: '#78350f' },
    info: { bg: '#e0f2fe', border: '#0284c7', text: '#0c4a6e' },
  };
  const c = colors[type] || colors.info;
  el.style.cssText = `
    pointer-events:auto;
    padding:12px 16px;
    border-radius:8px;
    border:1px solid ${c.border};
    background:${c.bg};
    color:${c.text};
    font-size:13px;
    line-height:1.45;
    box-shadow:0 4px 14px rgba(0,0,0,0.12);
    animation:trustbond-toast-in 0.2s ease;
  `;
  el.textContent = message;
  root.appendChild(el);
  const t = setTimeout(() => {
    el.style.opacity = '0';
    el.style.transition = 'opacity 0.25s';
    setTimeout(() => el.remove(), 280);
  }, durationMs);
  el.addEventListener('click', () => {
    clearTimeout(t);
    el.remove();
  });
  return el;
}

if (typeof document !== 'undefined' && !document.getElementById('trustbond-toast-styles')) {
  const style = document.createElement('style');
  style.id = 'trustbond-toast-styles';
  style.textContent = `@keyframes trustbond-toast-in { from { opacity:0; transform:translateY(-8px); } to { opacity:1; transform:translateY(0); } }`;
  document.head.appendChild(style);
}

export { showToast };
