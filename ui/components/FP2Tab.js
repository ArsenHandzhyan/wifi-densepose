// FP2 Monitor Tab Component

import { fp2Service } from '../services/fp2.service.js?v=20260307-fixedfp2';

export class FP2Tab {
  constructor(containerElement) {
    this.container = containerElement;
    this.unsubscribe = null;
    this.pollTimer = null;
    this.durationTimer = null;
    this.graphAnimationId = null;
    this.state = {
      streamState: 'offline',
      apiEnabled: false,
      lastUpdate: null,
      history: [],
      movementHistory: [],
      currentZone: null,
      lastPresence: null,
      presenceStartedAt: null,
      zones: [],
      device: null,
      connection: null
    };
  }

  async init() {
    this.cacheElements();
    this.bindEvents();
    this.initCanvas();
    this.initRealtimeGraph();

    this.unsubscribe = fp2Service.subscribe((message) => this.handleMessage(message));

    await this.refreshAll();
    this.startPolling();
    this.startDurationTicker();
  }

  cacheElements() {
    this.elements = {
      refreshBtn: this.container.querySelector('#fp2Refresh'),
      apiStatus: this.container.querySelector('#fp2ApiStatus'),
      streamStatus: this.container.querySelector('#fp2StreamStatus'),
      connectionState: this.container.querySelector('#fp2ConnectionState'),
      transportValue: this.container.querySelector('#fp2TransportValue'),
      entityId: this.container.querySelector('#fp2EntityId'),
      updatedAt: this.container.querySelector('#fp2UpdatedAt'),
      presenceValue: this.container.querySelector('#fp2PresenceValue'),
      deviceName: this.container.querySelector('#fp2DeviceName'),
      deviceModel: this.container.querySelector('#fp2DeviceModel'),
      deviceId: this.container.querySelector('#fp2DeviceId'),
      deviceMac: this.container.querySelector('#fp2DeviceMac'),
      deviceIp: this.container.querySelector('#fp2DeviceIp'),
      pairingId: this.container.querySelector('#fp2PairingId'),
      roomValue: this.container.querySelector('#fp2RoomValue'),
      networkValue: this.container.querySelector('#fp2NetworkValue'),
      firmwareValue: this.container.querySelector('#fp2FirmwareValue'),
      personsCount: this.container.querySelector('#fp2PersonsCount'),
      zonesCount: this.container.querySelector('#fp2ZonesCount'),
      lightLevel: this.container.querySelector('#fp2LightLevel'),
      currentZone: this.container.querySelector('#fp2CurrentZone'),
      presenceDuration: this.container.querySelector('#fp2PresenceDuration'),
      lastPacketAge: this.container.querySelector('#fp2LastPacketAge'),
      historyList: this.container.querySelector('#fp2HistoryList'),
      movementList: this.container.querySelector('#fp2MovementList'),
      rawOutput: this.container.querySelector('#fp2RawOutput'),
      movementCanvas: this.container.querySelector('#fp2MovementCanvas'),
      zoneWindows: this.container.querySelector('#fp2ZoneWindows')
    };
  }

  bindEvents() {
    if (this.elements.refreshBtn) {
      this.elements.refreshBtn.addEventListener('click', async () => {
        await this.refreshAll();
      });
    }
  }

  initCanvas() {
    const canvas = this.elements.movementCanvas;
    if (!canvas) {
      return;
    }

    this.canvasCtx = canvas.getContext('2d');
    this.drawMovementMap([], false);
  }

  async refreshAll() {
    await Promise.all([
      this.loadStatus(),
      this.loadCurrent()
    ]);
  }

  async loadStatus() {
    try {
      const status = await fp2Service.getStatus();
      this.state.apiEnabled = Boolean(status.enabled);
      this.state.device = status.device || null;
      this.state.connection = status.connection || null;

      this.elements.apiStatus.textContent = this.state.apiEnabled ? 'Enabled' : 'Disabled';
      this.elements.apiStatus.className = `chip ${this.state.apiEnabled ? 'ok' : 'warn'}`;

      this.updateStreamState(status.connection?.state || (status.stream_connected ? 'live' : 'offline'));
      this.elements.entityId.textContent = status.entity_id || status.source || 'fp2';
      this.elements.transportValue.textContent = this.formatTransport(
        status.connection?.transport || status.device?.transport
      );
      this.elements.connectionState.textContent = this.formatConnectionState(status.connection?.state);

      this.renderDevice(status.device);

      const statusZones = this.normalizeZones(status.connection?.zones || []);
      if (statusZones.length > 0) {
        this.state.zones = statusZones;
        this.renderZoneWindows(statusZones, this.state.currentZone);
      }

      if (typeof status.connection?.light_level === 'number') {
        this.elements.lightLevel.textContent = `${Math.round(status.connection.light_level)} lux`;
      }
      if (typeof status.connection?.last_update_age_sec === 'number') {
        this.elements.lastPacketAge.textContent = `${status.connection.last_update_age_sec.toFixed(1)}s`;
      }
    } catch (error) {
      console.error('Failed to load FP2 status:', error);
      this.elements.apiStatus.textContent = 'Error';
      this.elements.apiStatus.className = 'chip err';
      this.updateStreamState('offline');
    }
  }

  async loadCurrent() {
    try {
      const data = await fp2Service.getCurrent();
      this.renderCurrent(data);
    } catch (error) {
      console.error('Failed to load FP2 current data:', error);
    }
  }

  handleMessage(message) {
    if (message.type === 'connection_state') {
      this.updateStreamState(message.state);
      return;
    }

    if (message.type === 'data' && message.payload) {
      this.renderCurrent(message.payload);
    }
  }

  updateStreamState(state) {
    this.state.streamState = state;

    const label = state === 'live'
      ? 'live'
      : state === 'connected'
        ? 'connected'
        : state === 'polling'
          ? 'polling'
          : state === 'error'
            ? 'error'
            : 'offline';

    const cls = label === 'live' || label === 'connected'
      ? 'ok'
      : label === 'error'
        ? 'err'
        : 'warn';

    this.elements.streamStatus.textContent = label.toUpperCase();
    this.elements.streamStatus.className = `chip ${cls}`;
  }

  renderDevice(device) {
    const wifi = device?.wifi || {};
    this.elements.deviceName.textContent = device?.name || 'Aqara FP2';
    this.elements.deviceModel.textContent = device?.model || '-';
    this.elements.deviceId.textContent = device?.device_id || '-';
    this.elements.deviceMac.textContent = device?.mac_address || '-';
    this.elements.deviceIp.textContent = this.formatEndpoint(device?.ip_address, device?.hap_port);
    this.elements.pairingId.textContent = device?.pairing_id || '-';
    this.elements.roomValue.textContent = device?.room || '-';
    this.elements.firmwareValue.textContent = device?.firmware || '-';
    this.elements.networkValue.textContent = this.formatNetworkInfo(wifi);
  }

  renderCurrent(data) {
    const metadata = data?.metadata || {};
    const rawAttributes = metadata.raw_attributes || {};
    const available = metadata.available !== false;
    const presence = Boolean(metadata.presence);
    const persons = Array.isArray(data?.persons) ? data.persons : [];
    const zones = this.getZoneStates(data);
    const currentZone = this.detectCurrentZone(data, zones);
    const packetAge = this.getPacketAge(rawAttributes.push_time);
    const timestampLabel = this.formatTimestamp(data?.timestamp);

    this.state.zones = zones;
    this.state.lastUpdate = timestampLabel;

      this.elements.entityId.textContent = metadata.entity_id || metadata.source || 'fp2';
    this.elements.updatedAt.textContent = timestampLabel;
    this.elements.presenceValue.textContent = available
      ? (presence ? 'PRESENT' : 'ABSENT')
      : 'UNAVAILABLE';
    this.elements.presenceValue.className = `presence-pill ${available && presence ? 'present' : 'absent'}`;

    this.elements.personsCount.textContent = String(persons.length);
    this.elements.zonesCount.textContent = String(zones.length);
    this.elements.currentZone.textContent = currentZone || '-';
    this.elements.lastPacketAge.textContent = packetAge;

    if (typeof rawAttributes.light_level === 'number') {
      this.elements.lightLevel.textContent = `${Math.round(rawAttributes.light_level)} lux`;
    } else if (!this.elements.lightLevel.textContent.trim()) {
      this.elements.lightLevel.textContent = '-';
    }

    this.elements.rawOutput.textContent = JSON.stringify(data, null, 2);

    this.updateGraphData(available && presence);
    this.renderZoneWindows(zones, currentZone);
    this.drawMovementMap(zones, available && presence);

    if (available && presence && !this.state.presenceStartedAt) {
      this.state.presenceStartedAt = Date.now();
    }
    if (!available || !presence) {
      this.state.presenceStartedAt = null;
    }
    this.elements.presenceDuration.textContent = this.getPresenceDuration();

    const currentPresenceState = available ? presence : null;
    if (this.state.lastPresence !== currentPresenceState) {
      this.pushHistory({ timestamp: timestampLabel, presence: currentPresenceState });
    }

    this.trackMovement({
      timestamp: timestampLabel,
      presence: available && presence,
      zone: currentZone
    });
  }

  getZoneStates(data) {
    const rawZones = data?.metadata?.raw_attributes?.zones;
    if (Array.isArray(rawZones) && rawZones.length > 0) {
      return this.normalizeZones(rawZones);
    }

    const zoneSummary = data?.zone_summary || {};
    const summaryZones = Object.entries(zoneSummary).map(([zoneId, targetCount], index) => ({
      zone_id: zoneId,
      name: zoneId,
      occupied: Number(targetCount) > 0,
      target_count: Number(targetCount) || 0,
      index
    }));
    if (summaryZones.length > 0) {
      return this.normalizeZones(summaryZones);
    }

    if (this.state.zones.length > 0) {
      return this.state.zones;
    }

    return [
      {
        zone_id: 'detection_area',
        name: 'Detection Area',
        displayName: 'Detection Area',
        occupied: Boolean(data?.metadata?.presence),
        target_count: Boolean(data?.metadata?.presence) ? 1 : 0
      }
    ];
  }

  normalizeZones(zones) {
    return zones.map((zone, index) => {
      const zoneId = zone.zone_id || zone.id || `zone_${index + 1}`;
      const targetCount = Number(zone.target_count ?? zone.count ?? (zone.occupied ? 1 : 0)) || 0;
      return {
        zone_id: zoneId,
        name: zone.name || zoneId,
        displayName: this.formatZoneName(zoneId, index),
        occupied: Boolean(zone.occupied),
        target_count: targetCount,
        service_iid: zone.service_iid || null
      };
    });
  }

  detectCurrentZone(data, zones) {
    const personZone = Array.isArray(data?.persons) && data.persons.length > 0
      ? data.persons[0]?.zone_id
      : null;
    if (personZone) {
      return this.displayZoneName(personZone, zones);
    }

    const occupiedZone = zones.find((zone) => zone.occupied);
    if (occupiedZone) {
      return occupiedZone.displayName;
    }

    const attrs = data?.metadata?.raw_attributes || {};
    if (attrs.current_zone) {
      return this.displayZoneName(attrs.current_zone, zones);
    }

    return null;
  }

  displayZoneName(zoneId, zones) {
    const match = zones.find((zone) => zone.zone_id === zoneId || zone.name === zoneId);
    return match?.displayName || zoneId;
  }

  formatZoneName(zoneId, index) {
    if (!zoneId) {
      return `Zone ${index + 1}`;
    }

    if (/^occupancy_\d+$/i.test(zoneId)) {
      return `Zone ${index + 1}`;
    }

    return zoneId
      .replace(/^zone[_-]?/i, 'Zone ')
      .replace(/[_-]+/g, ' ')
      .replace(/\s+/g, ' ')
      .trim()
      .replace(/\b\w/g, (char) => char.toUpperCase());
  }

  formatTransport(transport) {
    if (!transport) {
      return 'Direct sensor';
    }

    return String(transport)
      .replace(/_/g, ' ')
      .replace(/\b\w/g, (char) => char.toUpperCase());
  }

  formatConnectionState(state) {
    if (!state) {
      return '-';
    }

    if (state === 'live') {
      return 'Direct live link';
    }

    if (state === 'waiting_for_hap_push') {
      return 'Waiting for sensor updates';
    }

    return String(state)
      .replace(/_/g, ' ')
      .replace(/\b\w/g, (char) => char.toUpperCase());
  }

  formatEndpoint(ipAddress, port) {
    if (!ipAddress) {
      return '-';
    }

    return port ? `${ipAddress}:${port}` : ipAddress;
  }

  formatNetworkInfo(wifi) {
    const parts = [];
    if (wifi.ssid) {
      parts.push(wifi.ssid);
    }
    if (wifi.channel && wifi.channel !== '-') {
      parts.push(`ch ${wifi.channel}`);
    }
    if (wifi.signal_strength && wifi.signal_strength !== '-') {
      parts.push(`${wifi.signal_strength} dBm`);
    }

    return parts.join(' · ') || '-';
  }

  formatTimestamp(timestamp) {
    if (!timestamp) {
      return new Date().toLocaleTimeString();
    }

    const date = new Date(timestamp);
    if (Number.isNaN(date.getTime())) {
      return new Date().toLocaleTimeString();
    }

    return date.toLocaleTimeString();
  }

  getPacketAge(pushTime) {
    if (!Number.isFinite(pushTime)) {
      return '-';
    }

    const ageSec = Math.max(0, Date.now() / 1000 - pushTime);
    return `${ageSec.toFixed(ageSec < 10 ? 1 : 0)}s`;
  }

  renderZoneWindows(zones, currentZone) {
    const container = this.elements.zoneWindows;
    if (!container) {
      return;
    }

    if (!zones.length) {
      container.innerHTML = '<div class="fp2-zone-window fp2-zone-window--empty">No zone telemetry yet</div>';
      return;
    }

    container.innerHTML = zones.map((zone) => {
      const isCurrent = currentZone && zone.displayName === currentZone;
      return `
        <article class="fp2-zone-window ${zone.occupied ? 'active' : ''} ${isCurrent ? 'current' : ''}">
          <div class="fp2-zone-window-header">
            <h4>${zone.displayName}</h4>
            <span class="fp2-zone-window-status">${zone.occupied ? 'MOTION' : 'IDLE'}</span>
          </div>
          <div class="fp2-zone-window-body">
            <span class="fp2-zone-window-count">${zone.target_count || 0}</span>
            <span class="fp2-zone-window-label">targets</span>
          </div>
          <div class="fp2-zone-window-meta">
            <span>${zone.zone_id}</span>
            <span>${zone.occupied ? 'occupied' : 'clear'}</span>
          </div>
        </article>
      `;
    }).join('');
  }

  trackMovement(event) {
    const prevPresence = this.state.lastPresence;
    const prevZone = this.state.currentZone;

    if (prevPresence === null) {
      this.state.lastPresence = event.presence;
      if (event.presence) {
        this.pushMovementEvent(event.timestamp, 'enter', `Motion detected in ${event.zone || 'detection area'}`);
      }
      return;
    }

    if (!prevPresence && event.presence) {
      this.pushMovementEvent(event.timestamp, 'enter', `Entered ${event.zone || 'detection area'}`);
    } else if (prevPresence && !event.presence) {
      this.pushMovementEvent(event.timestamp, 'exit', `Left ${prevZone || 'detection area'}`);
    } else if (event.presence && prevZone && event.zone && prevZone !== event.zone) {
      this.pushMovementEvent(event.timestamp, 'move', `${prevZone} -> ${event.zone}`);
    }

    this.state.lastPresence = event.presence;
    this.state.currentZone = event.zone;
  }

  pushMovementEvent(timestamp, type, text) {
    this.state.movementHistory.unshift({ timestamp, type, text });
    this.state.movementHistory = this.state.movementHistory.slice(0, 20);
    this.renderMovementHistory();
  }

  renderMovementHistory() {
    if (!this.elements.movementList) {
      return;
    }

    this.elements.movementList.innerHTML = '';
    this.state.movementHistory.forEach((entry) => {
      const item = document.createElement('li');
      item.className = 'fp2-history-item';
      item.innerHTML = `
        <span>${entry.timestamp}</span>
        <span>${entry.text}</span>
        <strong class="fp2-event fp2-event-${entry.type}">${entry.type.toUpperCase()}</strong>
      `;
      this.elements.movementList.appendChild(item);
    });
  }

  getPresenceDuration() {
    if (!this.state.presenceStartedAt) {
      return '0s';
    }

    const diffSec = Math.max(0, Math.floor((Date.now() - this.state.presenceStartedAt) / 1000));
    const min = Math.floor(diffSec / 60);
    const sec = diffSec % 60;

    if (min === 0) {
      return `${sec}s`;
    }

    return `${min}m ${sec}s`;
  }

  pushHistory(item) {
    this.state.history.unshift(item);
    this.state.history = this.state.history.slice(0, 12);

    this.elements.historyList.innerHTML = '';
    this.state.history.forEach((entry) => {
      const itemElement = document.createElement('li');
      itemElement.className = 'fp2-history-item';
      itemElement.innerHTML = `
        <span>${entry.timestamp}</span>
        <strong class="${entry.presence === null ? 'err' : entry.presence ? 'ok' : 'muted'}">
          ${entry.presence === null ? 'UNAVAILABLE' : entry.presence ? 'PRESENT' : 'ABSENT'}
        </strong>
      `;
      this.elements.historyList.appendChild(itemElement);
    });
  }

  drawMovementMap(zones, presence) {
    const canvas = this.elements.movementCanvas;
    const ctx = this.canvasCtx;
    if (!canvas || !ctx) {
      return;
    }

    const zoneList = zones.length > 0
      ? zones
      : [{ displayName: 'Detection Area', zone_id: 'detection_area', occupied: presence, target_count: presence ? 1 : 0 }];
    const width = canvas.width;
    const height = canvas.height;

    ctx.clearRect(0, 0, width, height);
    ctx.fillStyle = '#101722';
    ctx.fillRect(0, 0, width, height);

    const gap = 18;
    const padding = 24;
    const zoneWidth = Math.max(140, (width - padding * 2 - gap * (zoneList.length - 1)) / zoneList.length);
    const zoneHeight = height - padding * 2;

    zoneList.forEach((zone, index) => {
      const x = padding + index * (zoneWidth + gap);
      const y = padding;
      const active = Boolean(zone.occupied);

      this.drawRoundedRect(ctx, x, y, zoneWidth, zoneHeight, 18);
      ctx.fillStyle = active ? 'rgba(74, 222, 128, 0.18)' : 'rgba(148, 163, 184, 0.08)';
      ctx.fill();
      ctx.lineWidth = active ? 2 : 1;
      ctx.strokeStyle = active ? 'rgba(74, 222, 128, 0.9)' : 'rgba(148, 163, 184, 0.25)';
      ctx.stroke();

      ctx.fillStyle = '#f8fafc';
      ctx.font = '600 16px sans-serif';
      ctx.fillText(zone.displayName, x + 18, y + 30);

      ctx.fillStyle = active ? 'rgba(134, 239, 172, 0.95)' : 'rgba(148, 163, 184, 0.85)';
      ctx.font = '12px monospace';
      ctx.fillText(zone.zone_id, x + 18, y + 50);

      ctx.fillStyle = active ? '#4ade80' : '#64748b';
      ctx.font = '700 28px sans-serif';
      ctx.fillText(active ? 'MOTION' : 'IDLE', x + 18, y + 98);

      ctx.fillStyle = '#cbd5e1';
      ctx.font = '13px sans-serif';
      ctx.fillText(`${zone.target_count || 0} target(s)`, x + 18, y + 126);

      if (active) {
        const pulseX = x + zoneWidth - 58;
        const pulseY = y + zoneHeight / 2;
        const pulseRadius = 18 + Math.sin(Date.now() / 240) * 5;

        ctx.strokeStyle = 'rgba(74, 222, 128, 0.35)';
        ctx.lineWidth = 3;
        ctx.beginPath();
        ctx.arc(pulseX, pulseY, pulseRadius, 0, Math.PI * 2);
        ctx.stroke();

        ctx.fillStyle = 'rgba(74, 222, 128, 0.9)';
        ctx.beginPath();
        ctx.arc(pulseX, pulseY, 9, 0, Math.PI * 2);
        ctx.fill();
      }
    });

    ctx.fillStyle = presence ? 'rgba(74, 222, 128, 0.95)' : 'rgba(248, 113, 113, 0.95)';
    ctx.font = '700 14px monospace';
    ctx.fillText(presence ? 'LIVE MOTION' : 'ROOM CLEAR', width - 128, 22);
  }

  drawRoundedRect(ctx, x, y, width, height, radius) {
    ctx.beginPath();
    ctx.moveTo(x + radius, y);
    ctx.lineTo(x + width - radius, y);
    ctx.quadraticCurveTo(x + width, y, x + width, y + radius);
    ctx.lineTo(x + width, y + height - radius);
    ctx.quadraticCurveTo(x + width, y + height, x + width - radius, y + height);
    ctx.lineTo(x + radius, y + height);
    ctx.quadraticCurveTo(x, y + height, x, y + height - radius);
    ctx.lineTo(x, y + radius);
    ctx.quadraticCurveTo(x, y, x + radius, y);
    ctx.closePath();
  }

  initRealtimeGraph() {
    const canvas = this.container.querySelector('#fp2RealtimeGraph');
    if (!canvas) {
      return;
    }

    this.graphCanvas = canvas;
    this.graphCtx = canvas.getContext('2d');
    this.graphData = [];
    this.maxGraphPoints = 120;
    this.startGraphAnimation();
  }

  startGraphAnimation() {
    if (this.graphAnimationId) {
      return;
    }

    const animate = () => {
      this.drawRealtimeGraph();
      this.graphAnimationId = requestAnimationFrame(animate);
    };
    animate();
  }

  stopGraphAnimation() {
    if (this.graphAnimationId) {
      cancelAnimationFrame(this.graphAnimationId);
      this.graphAnimationId = null;
    }
  }

  updateGraphData(presence) {
    const now = Date.now();
    this.graphData.push({
      timestamp: now,
      presence: presence ? 1 : 0
    });

    if (this.graphData.length > this.maxGraphPoints) {
      this.graphData.shift();
    }
  }

  drawRealtimeGraph() {
    const canvas = this.graphCanvas;
    const ctx = this.graphCtx;
    if (!canvas || !ctx) {
      return;
    }

    const width = canvas.width;
    const height = canvas.height;
    ctx.fillStyle = '#101722';
    ctx.fillRect(0, 0, width, height);

    ctx.strokeStyle = 'rgba(255,255,255,0.08)';
    ctx.lineWidth = 1;
    for (let index = 0; index < 5; index += 1) {
      const y = (height / 4) * index;
      ctx.beginPath();
      ctx.moveTo(0, y);
      ctx.lineTo(width, y);
      ctx.stroke();
    }

    ctx.fillStyle = 'rgba(255,255,255,0.5)';
    ctx.font = '10px sans-serif';
    ctx.fillText('Present', 8, 15);
    ctx.fillText('Absent', 8, height - 6);

    if (this.graphData.length < 2) {
      return;
    }

    const xStep = width / this.maxGraphPoints;
    ctx.strokeStyle = '#4ade80';
    ctx.lineWidth = 2;
    ctx.beginPath();

    this.graphData.forEach((point, index) => {
      const x = index * xStep;
      const y = point.presence ? 30 : height - 20;
      if (index === 0) {
        ctx.moveTo(x, y);
      } else {
        ctx.lineTo(x, y);
      }
    });
    ctx.stroke();

    ctx.fillStyle = 'rgba(74, 222, 128, 0.18)';
    ctx.beginPath();
    ctx.moveTo(0, height);
    this.graphData.forEach((point, index) => {
      const x = index * xStep;
      const y = point.presence ? 30 : height - 20;
      ctx.lineTo(x, y);
    });
    ctx.lineTo((this.graphData.length - 1) * xStep, height);
    ctx.closePath();
    ctx.fill();

    const last = this.graphData[this.graphData.length - 1];
    const lastX = (this.graphData.length - 1) * xStep;
    const lastY = last.presence ? 30 : height - 20;
    ctx.fillStyle = last.presence ? '#4ade80' : '#94a3b8';
    ctx.beginPath();
    ctx.arc(lastX, lastY, 4, 0, Math.PI * 2);
    ctx.fill();
  }

  startPolling() {
    this.stopPolling();
    this.pollTimer = setInterval(async () => {
      await this.refreshAll();
    }, 2000);
  }

  stopPolling() {
    if (this.pollTimer) {
      clearInterval(this.pollTimer);
      this.pollTimer = null;
    }
  }

  startDurationTicker() {
    this.stopDurationTicker();
    this.durationTimer = setInterval(() => {
      this.elements.presenceDuration.textContent = this.getPresenceDuration();
    }, 1000);
  }

  stopDurationTicker() {
    if (this.durationTimer) {
      clearInterval(this.durationTimer);
      this.durationTimer = null;
    }
  }

  dispose() {
    this.stopPolling();
    this.stopDurationTicker();
    this.stopGraphAnimation();
    fp2Service.stopStream();
    if (this.unsubscribe) {
      this.unsubscribe();
      this.unsubscribe = null;
    }
  }
}
