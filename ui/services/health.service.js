// Health Service for WiFi-DensePose UI

import { API_CONFIG } from '../config/api.config.js';
import { apiService } from './api.service.js';

export class HealthService {
  constructor() {
    this.healthCheckTimer = null;
    this.healthSubscribers = [];
    this.lastHealthStatus = null;
    this.monitorIntervalMs = 30000;
    this.checkInFlight = false;
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
  async getSystemMetrics() {
    return apiService.get(API_CONFIG.ENDPOINTS.HEALTH.METRICS);
  }

  // Get version info
  async getVersion() {
    return apiService.get(API_CONFIG.ENDPOINTS.HEALTH.VERSION);
  }

  // Get API info
  async getApiInfo() {
    return apiService.get(API_CONFIG.ENDPOINTS.INFO);
  }

  // Get API status
  async getApiStatus() {
    return apiService.get(API_CONFIG.ENDPOINTS.STATUS);
  }

  // Start periodic health checks
  startHealthMonitoring(intervalMs = 30000) {
    this.monitorIntervalMs = Math.max(30000, intervalMs);

    if (this.healthCheckTimer || this.checkInFlight) {
      return;
    }

    this.scheduleNextHealthCheck(this.monitorIntervalMs);
  }

  // Stop health monitoring
  stopHealthMonitoring() {
    if (this.healthCheckTimer) {
      clearTimeout(this.healthCheckTimer);
      this.healthCheckTimer = null;
    }
  }

  scheduleNextHealthCheck(delayMs = this.monitorIntervalMs) {
    if (this.healthCheckTimer) {
      clearTimeout(this.healthCheckTimer);
    }

    this.healthCheckTimer = setTimeout(() => {
      this.healthCheckTimer = null;
      this.runHealthCheck();
    }, delayMs);
  }

  async runHealthCheck() {
    if (this.checkInFlight) {
      return;
    }

    this.checkInFlight = true;
    try {
      await this.getSystemHealth();
      this.scheduleNextHealthCheck(this.monitorIntervalMs);
    } catch (error) {
      console.error('Health check failed:', error);
      this.notifySubscribers({
        status: 'error',
        error: error.message,
        timestamp: new Date().toISOString()
      });

      const isRateLimited = Number(error?.status) === 429
        || /429|too many requests/i.test(String(error?.message || ''));
      this.scheduleNextHealthCheck(isRateLimited ? Math.max(60000, this.monitorIntervalMs) : this.monitorIntervalMs);
    } finally {
      this.checkInFlight = false;
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
    this.checkInFlight = false;
  }
}

// Create singleton instance
export const healthService = new HealthService();
