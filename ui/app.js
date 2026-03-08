// Aqara FP2 Monitor - Main Entry Point

import { TabManager } from './components/TabManager.js';
import { DashboardTab } from './components/DashboardTab.js?v=20260308-v2';
import { FP2Tab } from './components/FP2Tab.js?v=20260308-v2';
import { apiService } from './services/api.service.js';
import { wsService } from './services/websocket.service.js';
import { healthService } from './services/health.service.js';

// Internationalization (i18n) translations
const i18n = {
  en: {
    subtitle: 'Complete telemetry from Aqara FP2 sensor in real-time',
    tab_dashboard: 'Dashboard',
    tab_fp2: 'FP2 Monitor'
  },
  ru: {
    subtitle: 'Полная телеметрия с сенсора Aqara FP2 в реальном времени',
    tab_dashboard: 'Панель управления',
    tab_fp2: 'Монитор FP2'
  }
};

class WiFiDensePoseApp {
  constructor() {
    this.components = {};
    this.isInitialized = false;
    this.lastBackendToastState = null;
    this.currentLang = localStorage.getItem('fp2_lang') || 'en'; // Default to English
  }

  // Initialize application
  async init() {
    try {
      console.log('Initializing Aqara FP2 Monitor...');
      
      // Set up error handling
      this.setupErrorHandling();
      
      // Initialize services
      await this.initializeServices();
      
      // Initialize UI components
      this.initializeComponents();
      
      // Set up global event listeners
      this.setupEventListeners();
      
      // Setup language toggle
      this.setupLanguageToggle();
      
      // Apply initial language
      this.applyLanguage(this.currentLang);
      
      this.isInitialized = true;
      console.log('Aqara FP2 Monitor initialized successfully');
      
    } catch (error) {
      console.error('Failed to initialize application:', error);
      this.showGlobalError('Failed to initialize application. Please refresh the page.');
    }
  }

  // Initialize services
  async initializeServices() {
    // Compatibility shim: older cached websocket module may call clearPingInterval().
    if (typeof wsService.clearPingInterval !== 'function') {
      wsService.clearPingInterval = (url) => {
        if (typeof wsService.clearConnectionTimers === 'function') {
          wsService.clearConnectionTimers(url);
        }
      };
    }

    // Add request interceptor for error handling
    apiService.addResponseInterceptor(async (response, url) => {
      if (!response.ok && response.status === 401) {
        console.warn('Authentication required for:', url);
        // Handle authentication if needed
      }
      return response;
    });

    console.log('🔌 Initializing with real backend');

    try {
      const health = await healthService.checkLiveness();
      console.log('✅ Backend is available and responding:', health);
      this.showBackendStatus('Connected to real backend', 'success');
    } catch (error) {
      console.error('❌ Backend check failed:', error);
      this.showBackendStatus('Backend connection failed', 'error');
    }

    healthService.subscribeToHealth((health) => {
      if (health?.status === 'alive' || health?.status === 'healthy') {
        this.showBackendStatus('Connected to real backend', 'success');
        return;
      }

      this.showBackendStatus('Backend connection failed', 'error');
    });

    healthService.startHealthMonitoring(10000);
  }

  // Initialize UI components
  initializeComponents() {
    const container = document.querySelector('.container');
    if (!container) {
      throw new Error('Main container not found');
    }

    // Initialize tab manager
    this.components.tabManager = new TabManager(container);
    this.components.tabManager.init();

    // Initialize tab components
    this.initializeTabComponents();

    // Set up tab change handling
    this.components.tabManager.onTabChange((newTab, oldTab) => {
      this.handleTabChange(newTab, oldTab);
    });
  }

  // Initialize individual tab components
  initializeTabComponents() {
    // Dashboard tab
    const dashboardContainer = document.getElementById('dashboard');
    if (dashboardContainer) {
      this.components.dashboard = new DashboardTab(dashboardContainer);
      this.components.dashboard.init().catch(error => {
        console.error('Failed to initialize dashboard:', error);
      });
    }

    // FP2 tab
    const fp2Container = document.getElementById('fp2');
    if (fp2Container) {
      this.components.fp2 = new FP2Tab(fp2Container);
      this.components.fp2.init().catch(error => {
        console.error('Failed to initialize FP2 tab:', error);
      });
    }
  }

  // Handle tab changes
  handleTabChange(newTab, oldTab) {
    console.log(`Tab changed from ${oldTab} to ${newTab}`);
  }

  // Set up global event listeners
  setupEventListeners() {
    // Handle window resize
    window.addEventListener('resize', () => {
      this.handleResize();
    });

    // Handle visibility change
    document.addEventListener('visibilitychange', () => {
      this.handleVisibilityChange();
    });

    // Handle before unload
    window.addEventListener('beforeunload', () => {
      this.cleanup();
    });
  }

  // Handle window resize
  handleResize() {
    // Update canvas sizes if needed
    const canvases = document.querySelectorAll('canvas');
    canvases.forEach(canvas => {
      const rect = canvas.parentElement.getBoundingClientRect();
      if (canvas.width !== rect.width || canvas.height !== rect.height) {
        canvas.width = rect.width;
        canvas.height = rect.height;
      }
    });
  }

  // Handle visibility change
  handleVisibilityChange() {
    if (document.hidden) {
      // Pause updates when page is hidden
      console.log('Page hidden, pausing updates');
      healthService.stopHealthMonitoring();
    } else {
      // Resume updates when page is visible
      console.log('Page visible, resuming updates');
      healthService.startHealthMonitoring();
    }
  }

  // Set up error handling
  setupErrorHandling() {
    window.addEventListener('error', (event) => {
      if (event.error) {
        console.error('Global error:', event.error);
        this.showGlobalError('An unexpected error occurred');
      }
    });

    window.addEventListener('unhandledrejection', (event) => {
      if (event.reason) {
        console.error('Unhandled promise rejection:', event.reason);
        this.showGlobalError('An unexpected error occurred');
      }
    });
  }

  // Show backend status notification
  showBackendStatus(message, type) {
    const toastState = `${type}:${message}`;
    if (this.lastBackendToastState === toastState) {
      return;
    }
    this.lastBackendToastState = toastState;

    // Create status notification if it doesn't exist
    let statusToast = document.getElementById('backendStatusToast');
    if (!statusToast) {
      statusToast = document.createElement('div');
      statusToast.id = 'backendStatusToast';
      statusToast.className = 'backend-status-toast';
      document.body.appendChild(statusToast);
    }

    statusToast.textContent = message;
    statusToast.className = `backend-status-toast ${type}`;
    statusToast.classList.add('show');

    // Auto-hide success messages, keep warnings and errors longer
    const timeout = type === 'success' ? 3000 : 8000;
    setTimeout(() => {
      statusToast.classList.remove('show');
    }, timeout);
  }

  // Show global error message
  showGlobalError(message) {
    // Create error toast if it doesn't exist
    let errorToast = document.getElementById('globalErrorToast');
    if (!errorToast) {
      errorToast = document.createElement('div');
      errorToast.id = 'globalErrorToast';
      errorToast.className = 'error-toast';
      document.body.appendChild(errorToast);
    }

    errorToast.textContent = message;
    errorToast.classList.add('show');

    setTimeout(() => {
      errorToast.classList.remove('show');
    }, 5000);
  }

  // Setup language toggle button
  setupLanguageToggle() {
    const langToggle = document.getElementById('lang-toggle');
    if (!langToggle) return;
    
    langToggle.addEventListener('click', () => {
      const newLang = this.currentLang === 'ru' ? 'en' : 'ru';
      this.applyLanguage(newLang);
    });
  }

  // Apply language to UI
  applyLanguage(lang) {
    this.currentLang = lang;
    localStorage.setItem('fp2_lang', lang);
    
    // Update button text
    const langToggle = document.getElementById('lang-toggle');
    if (langToggle) {
      langToggle.textContent = lang === 'ru' ? '🇷🇺 RU' : '🇬🇧 EN';
    }
    
    // Update all elements with data-i18n attribute
    document.querySelectorAll('[data-i18n]').forEach(el => {
      const key = el.getAttribute('data-i18n');
      if (i18n[lang] && i18n[lang][key]) {
        el.textContent = i18n[lang][key];
      }
    });
  }

  // Clean up resources
  cleanup() {
    console.log('Cleaning up application resources...');
    
    // Dispose all components
    Object.values(this.components).forEach(component => {
      if (component && typeof component.dispose === 'function') {
        component.dispose();
      }
    });

    // Disconnect all WebSocket connections
    wsService.disconnectAll();
    
    // Stop health monitoring
    healthService.dispose();
  }

  // Public API
  getComponent(name) {
    return this.components[name];
  }

  isReady() {
    return this.isInitialized;
  }
}

// Initialize app when DOM is ready
document.addEventListener('DOMContentLoaded', () => {
  window.wifiDensePoseApp = new WiFiDensePoseApp();
  window.wifiDensePoseApp.init();
});

// Export for testing
export { WiFiDensePoseApp };
