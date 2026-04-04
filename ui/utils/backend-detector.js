// Backend Detection Utility

import { API_CONFIG } from '../config/api.config.js';

export class BackendDetector {
  constructor() {
    this.isBackendAvailable = null;
    this.lastCheck = 0;
    this.checkInterval = 30000; // Check every 30 seconds
    this.resolvedBaseUrl = this.getDefaultBaseUrl();
  }

  getLocation() {
    return typeof window !== 'undefined' ? window.location : null;
  }

  getBackendOverride(location = this.getLocation()) {
    if (!location) {
      return null;
    }
    const params = new URLSearchParams(location.search || '');
    return params.get('backend');
  }

  isLocalOrigin(location = this.getLocation()) {
    const hostname = location?.hostname || '';
    return ['127.0.0.1', 'localhost', '0.0.0.0'].includes(hostname);
  }

  shouldLockToLocalRuntime(location = this.getLocation()) {
    return this.isLocalOrigin(location) && !this.getBackendOverride(location);
  }

  getDefaultBaseUrl(location = this.getLocation()) {
    return this.shouldLockToLocalRuntime(location)
      ? API_CONFIG.LOCAL_RUNTIME_URL
      : API_CONFIG.BASE_URL;
  }

  getBackendCandidates() {
    const candidates = [];
    const location = this.getLocation();

    const addCandidate = (value) => {
      if (!value || candidates.includes(value)) {
        return;
      }
      candidates.push(value);
    };

    addCandidate(this.getBackendOverride(location));

    const hostname = location?.hostname || '';
    const isLocalOrigin = this.isLocalOrigin(location);
    if (isLocalOrigin) {
      addCandidate(API_CONFIG.LOCAL_RUNTIME_URL);
      if (hostname !== '127.0.0.1' && hostname !== 'localhost') {
        addCandidate(`${location.protocol}//${hostname}:8000`);
      }
      if (hostname !== 'localhost') {
        addCandidate('http://localhost:8000');
      }
      if (this.shouldLockToLocalRuntime(location)) {
        return candidates;
      }
    }

    addCandidate(API_CONFIG.BASE_URL);
    addCandidate(API_CONFIG.LOCAL_RUNTIME_URL);
    addCandidate('http://localhost:8000');

    return candidates;
  }

  async probeBackend(baseUrl, timeoutMs = 3000) {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), timeoutMs);

    try {
      const response = await fetch(`${baseUrl}/health/live`, {
        method: 'GET',
        signal: controller.signal,
        headers: { 'Accept': 'application/json' }
      });
      return response.ok;
    } finally {
      clearTimeout(timeoutId);
    }
  }

  async resolveRealBackendBaseUrl(force = false) {
    const now = Date.now();

    if (!force && this.resolvedBaseUrl && this.isBackendAvailable !== null && (now - this.lastCheck) < this.checkInterval) {
      return this.resolvedBaseUrl;
    }

    try {
      console.log('🔍 Checking backend availability...');

      const candidates = this.getBackendCandidates();

      for (const baseUrl of candidates) {
        try {
          const responseOk = await this.probeBackend(baseUrl);

          if (responseOk) {
            this.isBackendAvailable = true;
            this.lastCheck = now;
            this.resolvedBaseUrl = baseUrl;
            console.log(`✅ Real backend is available at ${baseUrl}`);
            return baseUrl;
          }
        } catch (_candidateError) {
          // Try next candidate
        }
      }

      throw new Error('All backend candidates are unavailable');
    } catch (error) {
      this.isBackendAvailable = false;
      this.lastCheck = now;
      
      if (error.name === 'AbortError') {
        console.log('⏱️ Backend check timed out - assuming unavailable');
      } else {
        console.log(`❌ Backend unavailable: ${error.message}`);
      }

      this.resolvedBaseUrl = this.getDefaultBaseUrl();
      throw error;
    }
  }

  // Check if the real backend is available
  async checkBackendAvailability() {
    const now = Date.now();

    // Use cached result if recent
    if (this.isBackendAvailable !== null && (now - this.lastCheck) < this.checkInterval) {
      return this.isBackendAvailable;
    }

    try {
      await this.resolveRealBackendBaseUrl(true);
      return true;
    } catch (_error) {
      return false;
    }
  }

  // Determine if mock server should be used
  async shouldUseMockServer() {
    // If mock is explicitly enabled, always use it
    if (API_CONFIG.MOCK_SERVER.ENABLED) {
      console.log('🧪 Using mock server (explicitly enabled)');
      return true;
    }

    // If auto-detection is disabled, never use mock
    if (!API_CONFIG.MOCK_SERVER.AUTO_DETECT) {
      console.log('🔌 Using real backend (auto-detection disabled)');
      return false;
    }

    // Check if backend is available
    const backendAvailable = await this.checkBackendAvailability();
    
    if (backendAvailable) {
      console.log('🔌 Using real backend (detected and available)');
      return false;
    } else {
      console.log('🧪 Using mock server (backend unavailable)');
      return true;
    }
  }

  // Get the appropriate base URL
  async getBaseUrl() {
    const useMock = await this.shouldUseMockServer();
    if (useMock) {
      return window.location.origin;
    }

    try {
      return await this.resolveRealBackendBaseUrl();
    } catch (_error) {
      return this.resolvedBaseUrl || API_CONFIG.BASE_URL;
    }
  }

  // Force a fresh check
  forceCheck() {
    this.isBackendAvailable = null;
    this.lastCheck = 0;
    this.resolvedBaseUrl = this.getDefaultBaseUrl();
  }
}

// Create singleton instance
export const backendDetector = new BackendDetector();
