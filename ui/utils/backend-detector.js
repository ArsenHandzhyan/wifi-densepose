// Backend Detection Utility

import { API_CONFIG } from '../config/api.config.js';

export class BackendDetector {
  constructor() {
    this.isBackendAvailable = null;
    this.lastCheck = 0;
    this.checkInterval = 30000; // Check every 30 seconds
  }

  // Check if the real backend is available
  async checkBackendAvailability() {
    const now = Date.now();
    
    // Use cached result if recent
    if (this.isBackendAvailable !== null && (now - this.lastCheck) < this.checkInterval) {
      return this.isBackendAvailable;
    }

    try {
      console.log('🔍 Checking backend availability...');

      const candidates = [
        API_CONFIG.BASE_URL,
        'http://127.0.0.1:8000',
        'http://localhost:8000'
      ].filter((v, i, a) => a.indexOf(v) === i);

      for (const baseUrl of candidates) {
        try {
          const controller = new AbortController();
          const timeoutId = setTimeout(() => controller.abort(), 3000);

          const response = await fetch(`${baseUrl}/health/live`, {
            method: 'GET',
            signal: controller.signal,
            headers: { 'Accept': 'application/json' }
          });

          clearTimeout(timeoutId);

          if (response.ok) {
            this.isBackendAvailable = true;
            this.lastCheck = now;
            console.log(`✅ Real backend is available at ${baseUrl}`);
            return true;
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
    return useMock ? window.location.origin : API_CONFIG.BASE_URL;
  }

  // Force a fresh check
  forceCheck() {
    this.isBackendAvailable = null;
    this.lastCheck = 0;
  }
}

// Create singleton instance
export const backendDetector = new BackendDetector();
