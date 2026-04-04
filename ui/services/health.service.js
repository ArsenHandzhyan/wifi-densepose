// Health Service for WiFi-DensePose UI

import { API_CONFIG } from '../config/api.config.js';
import { apiService } from './api.service.js?v=20260404-ui-runtime-20';

export class HealthService {
  constructor() {
    this.healthCheckInterval = null;
    this.healthSubscribers = [];
    this.lastHealthStatus = null;
  }

  normalizeRequestOptions(options) {
    return options && typeof options === 'object' ? options : {};
  }

  // Get system health
  async getSystemHealth() {
    const health = await apiService.get(API_CONFIG.ENDPOINTS.HEALTH.SYSTEM);
    this.lastHealthStatus = health;
    this.notifySubscribers(health);
    return health;
  }

  // Check readiness
  async checkReadiness() {
    return apiService.get(API_CONFIG.ENDPOINTS.HEALTH.READY);
  }

  // Check liveness
  async checkLiveness() {
    return apiService.get(API_CONFIG.ENDPOINTS.HEALTH.LIVE);
  }

  // Get system metrics
  async getSystemMetrics(options = {}) {
    return apiService.get(
      API_CONFIG.ENDPOINTS.HEALTH.METRICS,
      {},
      this.normalizeRequestOptions(options)
    );
  }

  // Get version info
  async getVersion() {
    return apiService.get(API_CONFIG.ENDPOINTS.HEALTH.VERSION);
  }

  // Get API info
  async getApiInfo(options = {}) {
    return apiService.get(
      API_CONFIG.ENDPOINTS.INFO,
      {},
      this.normalizeRequestOptions(options)
    );
  }

  // Get API status
  async getApiStatus(options = {}) {
    return apiService.get(
      API_CONFIG.ENDPOINTS.STATUS,
      {},
      this.normalizeRequestOptions(options)
    );
  }

  // Start periodic health checks
  startHealthMonitoring(intervalMs = 30000) {
    if (this.healthCheckInterval) {
      console.warn('Health monitoring already active');
      return;
    }

    // Initial check (silent on failure — DensePose API may not be running)
    this.getSystemHealth().catch(() => {
      // DensePose API not running — sensing-only mode, skip polling
      this._backendUnavailable = true;
    });

    // Set up periodic checks only if backend was reachable
    this.healthCheckInterval = setInterval(() => {
      if (this._backendUnavailable) return;
      this.getSystemHealth().catch(error => {
        this.notifySubscribers({
          status: 'error',
          error: error.message,
          timestamp: new Date().toISOString()
        });
      });
    }, intervalMs);
  }

  // Stop health monitoring
  stopHealthMonitoring() {
    if (this.healthCheckInterval) {
      clearInterval(this.healthCheckInterval);
      this.healthCheckInterval = null;
    }
  }

  // Subscribe to health updates
  subscribeToHealth(callback) {
    this.healthSubscribers.push(callback);
    
    // Send last known status if available
    if (this.lastHealthStatus) {
      callback(this.lastHealthStatus);
    }
    
    // Return unsubscribe function
    return () => {
      const index = this.healthSubscribers.indexOf(callback);
      if (index > -1) {
        this.healthSubscribers.splice(index, 1);
      }
    };
  }

  // Notify subscribers
  notifySubscribers(health) {
    this.healthSubscribers.forEach(callback => {
      try {
        callback(health);
      } catch (error) {
        console.error('Error in health subscriber:', error);
      }
    });
  }

  // Check if system is healthy
  isSystemHealthy() {
    if (!this.lastHealthStatus) {
      return null;
    }
    return this.lastHealthStatus.status === 'healthy';
  }

  // Get component status
  getComponentStatus(componentName) {
    if (!this.lastHealthStatus?.components) {
      return null;
    }
    return this.lastHealthStatus.components[componentName];
  }

  // Clean up
  dispose() {
    this.stopHealthMonitoring();
    this.healthSubscribers = [];
    this.lastHealthStatus = null;
  }
}

// Create singleton instance
export const healthService = new HealthService();
