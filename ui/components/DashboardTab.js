// Dashboard Tab Component

import { healthService } from '../services/health.service.js';
import { fp2Service } from '../services/fp2.service.js?v=20260307-dashboardlive1';

export class DashboardTab {
  constructor(containerElement) {
    this.container = containerElement;
    this.statsElements = {};
    this.healthSubscription = null;
    this.statsInterval = null;
    this.fp2Interval = null;
    this.csiPipelineEnabled = true;
    this.fp2OnlyMode = false;
  }

  // Initialize component
  async init() {
    this.cacheElements();
    await this.loadInitialData();
    this.startMonitoring();
  }

  // Cache DOM elements
  cacheElements() {
    // System stats
    const statsContainer = this.container.querySelector('.system-stats');
    if (statsContainer) {
      this.statsElements = {
        bodyRegions: statsContainer.querySelector('[data-stat="body-regions"] .stat-value'),
        samplingRate: statsContainer.querySelector('[data-stat="sampling-rate"] .stat-value'),
        accuracy: statsContainer.querySelector('[data-stat="accuracy"] .stat-value'),
        hardwareCost: statsContainer.querySelector('[data-stat="hardware-cost"] .stat-value')
      };
    }

    // Status indicators
    this.statusElements = {
      apiStatus: this.container.querySelector('.api-status'),
      streamStatus: this.container.querySelector('.stream-status'),
      hardwareStatus: this.container.querySelector('.hardware-status')
    };
  }

  // Load initial data
  async loadInitialData() {
    try {
      // Get API info
      const info = await healthService.getApiInfo();
      this.updateApiInfo(info);
      this.fp2OnlyMode = Boolean(info?.features?.fp2_only_mode);
      this.csiPipelineEnabled = info?.features?.csi_pipeline_enabled ?? info?.features?.real_time_processing ?? true;

      if (this.fp2OnlyMode || !this.csiPipelineEnabled) {
        this.setFp2OnlyState();
        await this.refreshFp2OnlyState();
        return;
      }

    } catch (error) {
      console.error('Failed to load dashboard data:', error);
      this.showError('Failed to load dashboard data');
    }
  }

  // Start monitoring
  startMonitoring() {
    // Subscribe to health updates
    this.healthSubscription = healthService.subscribeToHealth(health => {
      this.updateHealthStatus(health);
    });

    // Start periodic stats updates only when CSI mode is actually enabled.
    if (this.csiPipelineEnabled && !this.fp2OnlyMode) {
      this.statsInterval = setInterval(() => {
        this.updateLiveStats();
      }, 5000);
    }

    if (this.fp2OnlyMode) {
      this.fp2Interval = setInterval(() => {
        this.refreshFp2OnlyState().catch((error) => {
          console.error('Failed to refresh FP2 dashboard state:', error);
        });
      }, 3000);
    }

    // Start health monitoring
    healthService.startHealthMonitoring(30000);
  }

  // Update API info display
  updateApiInfo(info) {
    // Update version
    const versionElement = this.container.querySelector('.api-version');
    if (versionElement && info.version) {
      versionElement.textContent = `v${info.version}`;
    }

    // Update environment
    const envElement = this.container.querySelector('.api-environment');
    if (envElement && info.environment) {
      envElement.textContent = info.environment;
      envElement.className = `api-environment env-${info.environment}`;
    }

    // Update features status
    if (info.features) {
      this.updateFeatures(info.features);
    }
  }

  // Update features display
  updateFeatures(features) {
    const featuresContainer = this.container.querySelector('.features-status');
    if (!featuresContainer) return;

    featuresContainer.innerHTML = '';
    
    Object.entries(features).forEach(([feature, enabled]) => {
      const featureElement = document.createElement('div');
      featureElement.className = `feature-item ${enabled ? 'enabled' : 'disabled'}`;
      featureElement.innerHTML = `
        <span class="feature-name">${this.formatFeatureName(feature)}</span>
        <span class="feature-status">${enabled ? '✓' : '✗'}</span>
      `;
      featuresContainer.appendChild(featureElement);
    });
  }

  // Update health status
  updateHealthStatus(health) {
    if (!health) return;

    // Update overall status
    const overallStatus = this.container.querySelector('.overall-health');
    if (overallStatus) {
      overallStatus.className = `overall-health status-${health.status}`;
      overallStatus.textContent = health.status.toUpperCase();
    }

    if (this.fp2OnlyMode) {
      this.setFp2OnlyState();
      if (health.system_metrics || health.metrics) {
        this.updateSystemMetrics(health.system_metrics || health.metrics);
      }
      this.refreshFp2OnlyState().catch((error) => {
        console.error('Failed to refresh FP2 dashboard state:', error);
      });
      return;
    }

    // Update component statuses
    if (health.components) {
      Object.entries(health.components).forEach(([component, status]) => {
        this.updateComponentStatus(component, status);
      });
    }

    // Update metrics
    if (health.system_metrics || health.metrics) {
      this.updateSystemMetrics(health.system_metrics || health.metrics);
    }
  }

  // Update component status
  updateComponentStatus(component, status) {
    // Map backend component names to UI component names
    const componentMap = {
      'pose': 'inference',
      'stream': 'streaming',
      'hardware': 'hardware'
    };
    
    const uiComponent = componentMap[component] || component;
    const element = this.container.querySelector(`[data-component="${uiComponent}"]`);
    
    if (element) {
      element.className = `component-status status-${status.status}`;
      const statusText = element.querySelector('.status-text');
      const statusMessage = element.querySelector('.status-message');
      
      if (statusText) {
        statusText.textContent = status.status.toUpperCase();
      }
      
      if (statusMessage && status.message) {
        statusMessage.textContent = status.message;
      }
    }
    
    // Also update API status based on overall health
    if (component === 'hardware') {
      const apiElement = this.container.querySelector(`[data-component="api"]`);
      if (apiElement) {
        apiElement.className = `component-status status-healthy`;
        const apiStatusText = apiElement.querySelector('.status-text');
        const apiStatusMessage = apiElement.querySelector('.status-message');
        
        if (apiStatusText) {
          apiStatusText.textContent = 'HEALTHY';
        }
        
        if (apiStatusMessage) {
          apiStatusMessage.textContent = 'API server is running normally';
        }
      }
    }
  }

  // Update system metrics
  updateSystemMetrics(metrics) {
    // Handle both flat and nested metric structures
    // Backend returns system_metrics.cpu.percent, mock returns metrics.cpu.percent
    const systemMetrics = metrics.system_metrics || metrics;
    const cpuPercent = systemMetrics.cpu?.percent || systemMetrics.cpu_percent;
    const memoryPercent = systemMetrics.memory?.percent || systemMetrics.memory_percent;
    const diskPercent = systemMetrics.disk?.percent || systemMetrics.disk_percent;

    // CPU usage
    const cpuElement = this.container.querySelector('.cpu-usage');
    if (cpuElement && cpuPercent !== undefined) {
      cpuElement.textContent = `${cpuPercent.toFixed(1)}%`;
      this.updateProgressBar('cpu', cpuPercent);
    }

    // Memory usage
    const memoryElement = this.container.querySelector('.memory-usage');
    if (memoryElement && memoryPercent !== undefined) {
      memoryElement.textContent = `${memoryPercent.toFixed(1)}%`;
      this.updateProgressBar('memory', memoryPercent);
    }

    // Disk usage
    const diskElement = this.container.querySelector('.disk-usage');
    if (diskElement && diskPercent !== undefined) {
      diskElement.textContent = `${diskPercent.toFixed(1)}%`;
      this.updateProgressBar('disk', diskPercent);
    }
  }

  // Update progress bar
  updateProgressBar(type, percent) {
    const progressBar = this.container.querySelector(`.progress-bar[data-type="${type}"]`);
    if (progressBar) {
      const fill = progressBar.querySelector('.progress-fill');
      if (fill) {
        fill.style.width = `${percent}%`;
        fill.className = `progress-fill ${this.getProgressClass(percent)}`;
      }
    }
  }

  // Get progress class based on percentage
  getProgressClass(percent) {
    if (percent >= 90) return 'critical';
    if (percent >= 75) return 'warning';
    return 'normal';
  }

  // Update live statistics
  async updateLiveStats() {
    if (!this.csiPipelineEnabled || this.fp2OnlyMode) {
      return;
    }
  }

  // Update pose statistics
  updatePoseStats(poseData) {
    if (!poseData) return;

    // Update person count
    const personCount = this.container.querySelector('.person-count');
    if (personCount) {
      const count = poseData.persons ? poseData.persons.length : (poseData.total_persons || 0);
      personCount.textContent = count;
    }

    // Update average confidence
    const avgConfidence = this.container.querySelector('.avg-confidence');
    if (avgConfidence && poseData.persons && poseData.persons.length > 0) {
      const confidences = poseData.persons.map(p => p.confidence);
      const avg = confidences.length > 0
        ? (confidences.reduce((a, b) => a + b, 0) / confidences.length * 100).toFixed(1)
        : 0;
      avgConfidence.textContent = `${avg}%`;
    } else if (avgConfidence) {
      avgConfidence.textContent = '0%';
    }

    // Update total detections from stats if available
    const detectionCount = this.container.querySelector('.detection-count');
    if (detectionCount && poseData.total_detections !== undefined) {
      detectionCount.textContent = this.formatNumber(poseData.total_detections);
    }
  }

  // Update zones display
  updateZonesDisplay(zonesSummary) {
    const zonesContainer = this.container.querySelector('.zones-summary');
    if (!zonesContainer) return;

    zonesContainer.innerHTML = '';
    
    // Handle different zone summary formats
    let zones = {};
    if (zonesSummary && zonesSummary.zones) {
      zones = zonesSummary.zones;
    } else if (zonesSummary && typeof zonesSummary === 'object') {
      zones = zonesSummary;
    }
    
    // If no zones data, show default zones
    if (Object.keys(zones).length === 0) {
      ['zone_1', 'zone_2', 'zone_3', 'zone_4'].forEach(zoneId => {
        const zoneElement = document.createElement('div');
        zoneElement.className = 'zone-item';
        zoneElement.innerHTML = `
          <span class="zone-name">${zoneId}</span>
          <span class="zone-count">undefined</span>
        `;
        zonesContainer.appendChild(zoneElement);
      });
      return;
    }
    
    Object.entries(zones).forEach(([zoneId, data]) => {
      const zoneElement = document.createElement('div');
      zoneElement.className = 'zone-item';
      const count = typeof data === 'object' ? (data.person_count || data.count || 0) : data;
      zoneElement.innerHTML = `
        <span class="zone-name">${zoneId}</span>
        <span class="zone-count">${count}</span>
      `;
      zonesContainer.appendChild(zoneElement);
    });
  }

  // Update statistics
  updateStats(stats) {
    if (!stats) return;

    // Update detection count
    const detectionCount = this.container.querySelector('.detection-count');
    if (detectionCount && stats.total_detections !== undefined) {
      detectionCount.textContent = this.formatNumber(stats.total_detections);
    }

    // Update accuracy if available
    if (this.statsElements.accuracy && stats.average_confidence !== undefined) {
      this.statsElements.accuracy.textContent = `${(stats.average_confidence * 100).toFixed(1)}%`;
    }
  }

  setFp2OnlyState() {
    const heroTitle = this.container.querySelector('.hero-section h2');
    if (heroTitle) {
      heroTitle.textContent = 'Local FP2 Presence Monitoring';
    }

    const heroDescription = this.container.querySelector('.hero-description');
    if (heroDescription) {
      heroDescription.textContent = 'This dashboard is running in FP2-only mode. Presence is read from Aqara FP2 and pushed directly into the backend over the currently active transport.';
    }

    const detectionCount = this.container.querySelector('.detection-count');
    if (detectionCount) {
      detectionCount.textContent = 'FP2';
    }

    const personCount = this.container.querySelector('.person-count');
    if (personCount) {
      personCount.textContent = '-';
    }

    const avgConfidence = this.container.querySelector('.avg-confidence');
    if (avgConfidence) {
      avgConfidence.textContent = 'UNAVAILABLE';
    }

    if (this.statsElements.bodyRegions) {
      this.statsElements.bodyRegions.textContent = 'FP2';
    }

    if (this.statsElements.samplingRate) {
      this.statsElements.samplingRate.textContent = '1s';
    }

    if (this.statsElements.accuracy) {
      this.statsElements.accuracy.textContent = 'FP2';
    }

    if (this.statsElements.hardwareCost) {
      this.statsElements.hardwareCost.textContent = 'Local';
    }

    const zonesContainer = this.container.querySelector('.zones-summary');
    if (zonesContainer) {
      zonesContainer.innerHTML = `
        <div class="zone-item">
          <span class="zone-name">No live zones</span>
          <span class="zone-count">-</span>
        </div>
      `;
    }

    const apiCard = this.container.querySelector('[data-component="api"]');
    if (apiCard) {
      apiCard.className = 'component-status status-healthy';
      const statusText = apiCard.querySelector('.status-text');
      const statusMessage = apiCard.querySelector('.status-message');
      if (statusText) statusText.textContent = 'HEALTHY';
      if (statusMessage) statusMessage.textContent = 'Local backend is responding';
    }

    const hardwareCard = this.container.querySelector('[data-component="hardware"]');
    if (hardwareCard) {
      hardwareCard.className = 'component-status status-warning';
      const statusText = hardwareCard.querySelector('.status-text');
      const statusMessage = hardwareCard.querySelector('.status-message');
      if (statusText) statusText.textContent = 'FP2';
      if (statusMessage) statusMessage.textContent = 'Waiting for a live FP2 telemetry stream';
    }

    const inferenceCard = this.container.querySelector('[data-component="inference"]');
    if (inferenceCard) {
      inferenceCard.className = 'component-status status-disabled';
      const statusText = inferenceCard.querySelector('.status-text');
      const statusMessage = inferenceCard.querySelector('.status-message');
      if (statusText) statusText.textContent = 'DISABLED';
      if (statusMessage) statusMessage.textContent = 'CSI/DensePose pipeline is disabled on this setup';
    }

    const streamingCard = this.container.querySelector('[data-component="streaming"]');
    if (streamingCard) {
      streamingCard.className = 'component-status status-warning';
      const statusText = streamingCard.querySelector('.status-text');
      const statusMessage = streamingCard.querySelector('.status-message');
      if (statusText) statusText.textContent = 'STALE';
      if (statusMessage) statusMessage.textContent = 'No live FP2 snapshots are currently reaching the backend';
    }
  }

  async refreshFp2OnlyState() {
    if (!this.fp2OnlyMode) {
      return;
    }

    try {
      const [status, current] = await Promise.all([
        fp2Service.getStatus(),
        fp2Service.getCurrent()
      ]);

      this.renderFp2OnlyStatus(status, current);
    } catch (error) {
      console.error('Failed to load FP2-only dashboard state:', error);
      this.renderFp2OnlyError(error);
    }
  }

  renderFp2OnlyStatus(status, current) {
    const metadata = current?.metadata || {};
    const available = metadata.available !== false;
    const presence = Boolean(metadata.presence);
    const persons = Array.isArray(current?.persons) ? current.persons.length : 0;
    const connection = status?.connection || {};
    const zones = Array.isArray(connection.zones) ? connection.zones : [];
    const liveZoneCount = zones.length > 0 ? zones.length : Object.keys(current?.zone_summary || {}).length;
    const transportLabel = this.formatTransport(connection.transport || status?.source || 'fp2');
    const hasLiveStream = connection?.state === 'live' && available;

    const personCount = this.container.querySelector('.person-count');
    if (personCount) {
      personCount.textContent = available ? String(persons) : '-';
    }

    const avgConfidence = this.container.querySelector('.avg-confidence');
    if (avgConfidence) {
      avgConfidence.textContent = available
        ? (presence ? 'PRESENT' : 'ABSENT')
        : 'UNAVAILABLE';
    }

    const detectionCount = this.container.querySelector('.detection-count');
    if (detectionCount) {
      detectionCount.textContent = transportLabel;
    }

    const zonesContainer = this.container.querySelector('.zones-summary');
    if (zonesContainer) {
      if (liveZoneCount > 0) {
        const zoneMarkup = zones.length > 0
          ? zones.map((zone) => `
              <div class="zone-item">
                <span class="zone-name">${zone.name || zone.zone_id || 'zone'}</span>
                <span class="zone-count">${zone.occupied ? 'active' : 'idle'}</span>
              </div>
            `).join('')
          : Object.entries(current?.zone_summary || {}).map(([zoneName, count]) => `
              <div class="zone-item">
                <span class="zone-name">${zoneName}</span>
                <span class="zone-count">${count}</span>
              </div>
            `).join('');
        zonesContainer.innerHTML = zoneMarkup;
      } else {
        zonesContainer.innerHTML = `
          <div class="zone-item">
            <span class="zone-name">No live zones</span>
            <span class="zone-count">-</span>
          </div>
        `;
      }
    }

    const hardwareCard = this.container.querySelector('[data-component="hardware"]');
    if (hardwareCard) {
      hardwareCard.className = `component-status ${hasLiveStream ? 'status-healthy' : 'status-warning'}`;
      const statusText = hardwareCard.querySelector('.status-text');
      const statusMessage = hardwareCard.querySelector('.status-message');
      if (statusText) statusText.textContent = hasLiveStream ? 'FP2' : 'STALE';
      if (statusMessage) {
        statusMessage.textContent = hasLiveStream
          ? `Aqara FP2 telemetry is live over ${transportLabel}`
          : 'Aqara FP2 is configured, but no live telemetry stream is active';
      }
    }

    const streamingCard = this.container.querySelector('[data-component="streaming"]');
    if (streamingCard) {
      const streamState = hasLiveStream ? 'healthy' : 'warning';
      const statusText = streamingCard.querySelector('.status-text');
      const statusMessage = streamingCard.querySelector('.status-message');
      streamingCard.className = `component-status status-${streamState}`;
      if (statusText) {
        statusText.textContent = hasLiveStream ? transportLabel : this.formatConnectionState(connection.state || 'stale');
      }
      if (statusMessage) {
        statusMessage.textContent = hasLiveStream
          ? `Live FP2 snapshots are being pushed to the backend over ${transportLabel}`
          : 'No live FP2 snapshots are currently reaching the backend';
      }
    }
  }

  renderFp2OnlyError() {
    const hardwareCard = this.container.querySelector('[data-component="hardware"]');
    const streamingCard = this.container.querySelector('[data-component="streaming"]');
    const avgConfidence = this.container.querySelector('.avg-confidence');

    if (avgConfidence) {
      avgConfidence.textContent = 'UNAVAILABLE';
    }

    if (hardwareCard) {
      hardwareCard.className = 'component-status status-error';
      const statusText = hardwareCard.querySelector('.status-text');
      const statusMessage = hardwareCard.querySelector('.status-message');
      if (statusText) statusText.textContent = 'ERROR';
      if (statusMessage) statusMessage.textContent = 'Unable to load FP2 sensor state';
    }

    if (streamingCard) {
      streamingCard.className = 'component-status status-error';
      const statusText = streamingCard.querySelector('.status-text');
      const statusMessage = streamingCard.querySelector('.status-message');
      if (statusText) statusText.textContent = 'ERROR';
      if (statusMessage) statusMessage.textContent = 'Unable to load FP2 stream state';
    }
  }

  formatTransport(transport) {
    const normalized = String(transport || '').replace(/_/g, ' ').trim();
    if (!normalized) {
      return 'FP2';
    }
    return normalized
      .split(' ')
      .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
      .join(' ');
  }

  formatConnectionState(state) {
    const normalized = String(state || 'offline').trim().toUpperCase();
    return normalized || 'OFFLINE';
  }

  // Format feature name
  formatFeatureName(name) {
    return name.replace(/_/g, ' ')
      .split(' ')
      .map(word => word.charAt(0).toUpperCase() + word.slice(1))
      .join(' ');
  }

  // Format large numbers
  formatNumber(num) {
    if (num >= 1000000) {
      return `${(num / 1000000).toFixed(1)}M`;
    }
    if (num >= 1000) {
      return `${(num / 1000).toFixed(1)}K`;
    }
    return num.toString();
  }

  // Show error message
  showError(message) {
    const errorContainer = this.container.querySelector('.error-container');
    if (errorContainer) {
      errorContainer.textContent = message;
      errorContainer.style.display = 'block';
      
      setTimeout(() => {
        errorContainer.style.display = 'none';
      }, 5000);
    }
  }

  // Clean up
  dispose() {
    if (this.healthSubscription) {
      this.healthSubscription();
    }
    
    if (this.statsInterval) {
      clearInterval(this.statsInterval);
    }

    if (this.fp2Interval) {
      clearInterval(this.fp2Interval);
    }
    
    healthService.stopHealthMonitoring();
  }
}
