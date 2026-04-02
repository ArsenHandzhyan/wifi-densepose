import { CsiOperatorApp } from './components/CsiOperatorApp.js?v=20260403-signal-dashboard-01';

let appInstance = null;
let hashListener = null;

function renderBootError(root, error) {
  const message = error instanceof Error ? error.message : String(error || 'неизвестная ошибка');
  root.innerHTML = `
    <div class="operator-boot-error">
      <div class="operator-boot-error__eyebrow">АГЕНТ 7 / CSI ОПЕРАТОР</div>
      <h1>Не удалось поднять операторскую оболочку</h1>
      <p>${message}</p>
    </div>
  `;
}

async function bootstrap() {
  const root = document.getElementById('operatorRoot');
  if (!root) {
    throw new Error('operatorRoot not found');
  }

  document.documentElement.lang = 'ru';
  appInstance = new CsiOperatorApp(root);
  window.agent7OperatorApp = appInstance;
  await appInstance.init();

  const applyHashTab = () => {
    const targetTab = window.location.hash.replace(/^#/, '');
    if (!targetTab) {
      return;
    }
    appInstance?.tabManager?.switchToTab(targetTab);
  };

  hashListener = applyHashTab;
  applyHashTab();
  window.addEventListener('hashchange', hashListener);
  appInstance?.tabManager?.onTabChange?.((tabId) => {
    if (!tabId) {
      return;
    }
    if (window.location.hash !== `#${tabId}`) {
      history.replaceState(null, '', `#${tabId}`);
    }
  });
}

window.addEventListener('beforeunload', () => {
  if (hashListener) {
    window.removeEventListener('hashchange', hashListener);
  }
  appInstance?.dispose();
});

async function startApp() {
  const root = document.getElementById('operatorRoot');
  try {
    await bootstrap();
  } catch (error) {
    console.error('Не удалось запустить UI оператора Agent 7:', error);
    if (root) {
      renderBootError(root, error);
    }
  }
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', startApp);
} else {
  startApp();
}
