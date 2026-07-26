import { createRoot } from 'react-dom/client';
import App from './App.jsx';
import './styles.css';

// Affiche les erreurs fatales à l'écran (indispensable pour diagnostiquer sur mobile)
function showFatal(msg) {
  const el = document.createElement('pre');
  el.style.cssText = 'position:fixed;inset:auto 8px 8px 8px;z-index:99;background:#7a1f1f;color:#fff;'
    + 'padding:10px;border-radius:8px;font-size:11px;white-space:pre-wrap;max-height:40vh;overflow:auto';
  el.textContent = String(msg);
  document.body.appendChild(el);
}
window.addEventListener('error', (e) => showFatal(`${e.message}\n${e.filename}:${e.lineno}`));
window.addEventListener('unhandledrejection', (e) => showFatal(`Promise: ${e.reason}`));

createRoot(document.getElementById('root')).render(<App />);
