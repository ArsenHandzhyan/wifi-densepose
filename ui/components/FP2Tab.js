// FP2 Monitor Tab Component — Ultra Edition

import { fp2Service } from '../services/fp2.service.js?v=20260307-fp2max1';

const RESOURCE_LABELS = {
  '3.51.85': 'Presence',
  '0.4.85': 'Light Level',
  '8.0.2026': 'RSSI',
  '8.0.2045': 'Online State',
  '13.27.85': 'Movement Event',
  '4.31.85': 'Fall State',
  '8.0.2116': 'Sensor Angle',
  '13.120.85': 'Total Count',
  '4.22.700': 'Coordinates Payload'
};

const MOVEMENT_LABELS = {
  0: 'No event',
  1: 'Static presence',
  2: 'Micro-movement',
  3: 'Significant movement',
  4: 'Large movement',
  5: 'Approaching',
  6: 'Departing',
  7: 'Moving',
  8: 'Static after movement',
  9: 'Entering zone',
  10: 'Leaving zone'
};

const FALL_LABELS = {
  0: 'No fall detected',
  1: 'Possible fall',
  2: 'Fall detected'
};

// Colors for target rendering
const TARGET_COLORS = ['#4ade80', '#38bdf8', '#f472b6', '#facc15', '#a78bfa', '#fb923c'];

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
      targets: [],
      device: null,
      connection: null,
      lastMovementEvent: null,
      lastFallState: null,
      lastTargetCount: null,
      currentPresenceActive: false,
      currentAvailability: false,
      currentSensorAngle: null,
      currentRssi: null,
      coordinateSignature: null,
      lastCoordinateChangeAtMs: null,
      // Trail history: store last N coordinate snapshots
      trailHistory: [],
      maxTrailLength: 30,
      animation: {
        fromTargets: [],
        toTargets: [],
        startedAtMs: 0,
        durationMs: 900,
        lastSampleAtMs: 0
      }
    };
    this.renderLoopUntilMs = 0;
  }

  async init() {
    this.cacheElements();
    this.bindEvents();
    this.initCanvas();
    this.initRealtimeGraph();
    this.initRssiGauge();
    this.initAngleDial();

    this.unsubscribe = fp2Service.subscribe((message) => this.handleMessage(message));

    await this.refreshAll();
    await this.startLiveStream();
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
      cloudDid: this.container.querySelector('#fp2CloudDid'),
      positionId: this.container.querySelector('#fp2PositionId'),
      roomValue: this.container.querySelector('#fp2RoomValue'),
      networkValue: this.container.querySelector('#fp2NetworkValue'),
      firmwareValue: this.container.querySelector('#fp2FirmwareValue'),
      personsCount: this.container.querySelector('#fp2PersonsCount'),
      zonesCount: this.container.querySelector('#fp2ZonesCount'),
      lightLevel: this.container.querySelector('#fp2LightLevel'),
      currentZone: this.container.querySelector('#fp2CurrentZone'),
      presenceDuration: this.container.querySelector('#fp2PresenceDuration'),
      lastPacketAge: this.container.querySelector('#fp2LastPacketAge'),
      onlineState: this.container.querySelector('#fp2OnlineState'),
      rssiValue: this.container.querySelector('#fp2RssiValue'),
      sensorAngle: this.container.querySelector('#fp2SensorAngle'),
      movementEvent: this.container.querySelector('#fp2MovementEvent'),
      fallState: this.container.querySelector('#fp2FallState'),
      deviceTimestamp: this.container.querySelector('#fp2DeviceTimestamp'),
      coordinateStream: this.container.querySelector('#fp2CoordinateStream'),
      coordinateChangeAge: this.container.querySelector('#fp2CoordinateChangeAge'),
      coordinateCount: this.container.querySelector('#fp2CoordinateCount'),
      apiDomain: this.container.querySelector('#fp2ApiDomain'),
      primaryTargetId: this.container.querySelector('#fp2PrimaryTargetId'),
      primaryTargetType: this.container.querySelector('#fp2PrimaryTargetType'),
      primaryTargetCoords: this.container.querySelector('#fp2PrimaryTargetCoords'),
      primaryTargetDistance: this.container.querySelector('#fp2PrimaryTargetDistance'),
      primaryTargetAngle: this.container.querySelector('#fp2PrimaryTargetAngle'),
      targetList: this.container.querySelector('#fp2TargetList'),
      resourceGrid: this.container.querySelector('#fp2ResourceGrid'),
      historyList: this.container.querySelector('#fp2HistoryList'),
      movementList: this.container.querySelector('#fp2MovementList'),
      sensorOutput: this.container.querySelector('#fp2SensorOutput'),
      rawOutput: this.container.querySelector('#fp2RawOutput'),
      movementCanvas: this.container.querySelector('#fp2MovementCanvas'),
      zoneWindows: this.container.querySelector('#fp2ZoneWindows'),
      // New elements
      fallAlert: this.container.querySelector('#fp2FallAlert'),
      fallAlertText: this.container.querySelector('#fp2FallAlertText'),
      fallAlertTime: this.container.querySelector('#fp2FallAlertTime'),
      rssiGauge: this.container.querySelector('#fp2RssiGauge'),
      angleDial: this.container.querySelector('#fp2AngleDial'),
      mapMode: this.container.querySelector('#fp2MapMode')
    };
  }

  bindEvents() {
    if (this.elements.refreshBtn) {
      this.elements.refreshBtn.addEventListener('click', async () => {
        await this.refreshAll();
      });
    }
  }

  // ── Canvas init ──

  initCanvas() {
    const canvas = this.elements.movementCanvas;
    if (!canvas) return;
    this.canvasCtx = canvas.getContext('2d');
    this.drawMovementMap([], false, [], null, false);
  }

  initRssiGauge() {
    const canvas = this.elements.rssiGauge;
    if (!canvas) return;
    this.rssiCtx = canvas.getContext('2d');
    this.drawRssiGauge(null);
  }

  initAngleDial() {
    const canvas = this.elements.angleDial;
    if (!canvas) return;
    this.angleCtx = canvas.getContext('2d');
    this.drawAngleDial(null);
  }

  initRealtimeGraph() {
    const canvas = this.container.querySelector('#fp2RealtimeGraph');
    if (!canvas) return;
    this.graphCanvas = canvas;
    this.graphCtx = canvas.getContext('2d');
    this.graphData = [];
    this.maxGraphPoints = 120;
    this.drawRealtimeGraph();
  }

  // ── Data loading ──

  async refreshAll() {
    await Promise.all([this.loadStatus(), this.loadCurrent()]);
  }

  async startLiveStream() {
    try {
      await fp2Service.startStream();
    } catch (error) {
      console.error('Failed to start FP2 live stream:', error);
    }
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
      this.elements.transportValue.textContent = this.formatTransport(status.connection?.transport || status.device?.transport);
      this.elements.connectionState.textContent = this.formatConnectionState(status.connection?.state);

      this.renderDevice(status.device, status.connection);

      const statusZones = this.normalizeZones(status.connection?.zones || []);
      if (statusZones.length > 0) {
        this.state.zones = statusZones;
        this.renderZoneWindows(statusZones, this.state.currentZone);
      }

      this.elements.onlineState.textContent = this.formatOnlineState(status.connection?.online);
      this.elements.rssiValue.textContent = this.formatDbm(status.connection?.rssi);
      this.elements.apiDomain.textContent = status.connection?.api_domain || status.device?.api_domain || '-';

      if (Number.isFinite(status.connection?.rssi)) {
        this.state.currentRssi = status.connection.rssi;
        this.drawRssiGauge(status.connection.rssi);
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
      this.updateStreamState('live');
      this.renderCurrent(message.payload);
    }
  }

  // ── Stream state ──

  updateStreamState(state) {
    this.state.streamState = state;
    const label = state === 'live' ? 'live'
      : state === 'connected' ? 'connected'
      : state === 'polling' ? 'polling'
      : state === 'error' ? 'error'
      : 'offline';
    const cls = (label === 'live' || label === 'connected') ? 'ok' : label === 'error' ? 'err' : 'warn';
    this.elements.streamStatus.textContent = label.toUpperCase();
    this.elements.streamStatus.className = `chip ${cls}`;
  }

  // ── Render cycle ──

  renderDevice(device, connection) {
    const wifi = device?.wifi || {};
    this.elements.deviceName.textContent = device?.name || 'Aqara FP2';
    this.elements.deviceModel.textContent = device?.model || '-';
    this.elements.deviceId.textContent = device?.device_id || '-';
    this.elements.deviceMac.textContent = device?.mac_address || '-';
    this.elements.deviceIp.textContent = this.formatEndpoint(device?.ip_address, device?.hap_port);
    this.elements.pairingId.textContent = device?.pairing_id || '-';
    this.elements.cloudDid.textContent = device?.cloud_did || '-';
    this.elements.positionId.textContent = device?.position_id || connection?.position_id || '-';
    this.elements.roomValue.textContent = device?.room || '-';
    this.elements.firmwareValue.textContent = device?.firmware || '-';
    this.elements.networkValue.textContent = this.formatNetworkInfo(wifi);
  }

  renderCurrent(data) {
    const metadata = data?.metadata || {};
    const rawAttributes = metadata.raw_attributes || {};
    const available = metadata.available !== false;
    const presence = Boolean(metadata.presence);
    const zones = this.getZoneStates(data);
    const previousTargets = Array.isArray(this.state.targets) ? this.state.targets : [];
    const targets = this.attachTargetDeltas(this.getTargets(data, rawAttributes, zones), previousTargets);
    const currentZone = this.detectCurrentZone(data, zones, targets);
    const packetAge = this.getPacketAge(rawAttributes.push_time);
    const timestampLabel = this.formatTimestamp(data?.timestamp);
    const primaryTarget = targets[0] || null;
    const sampleAtMs = this.resolveSampleTimestampMs(data?.timestamp, rawAttributes.device_timestamp);

    this.state.zones = zones;
    this.state.targets = targets;
    this.state.lastUpdate = timestampLabel;
    this.state.currentPresenceActive = available && presence;
    this.state.currentAvailability = available;
    this.state.currentSensorAngle = rawAttributes.sensor_angle;
    this.updateTargetAnimation(targets, sampleAtMs);

    // Store trail snapshot
    const coordTargets = targets.filter(t => this.hasCoordinates(t));
    if (coordTargets.length > 0) {
      this.state.trailHistory.push({
        ts: sampleAtMs,
        targets: coordTargets.map(t => ({ id: t.target_id, x: t.x, y: t.y }))
      });
      if (this.state.trailHistory.length > this.state.maxTrailLength) {
        this.state.trailHistory.shift();
      }
    }

    // Update elements
    this.elements.entityId.textContent = metadata.entity_id || metadata.source || 'fp2';
    this.elements.updatedAt.textContent = timestampLabel;
    this.elements.presenceValue.textContent = available ? (presence ? 'PRESENT' : 'ABSENT') : 'UNAVAILABLE';
    this.elements.presenceValue.className = `presence-pill ${available && presence ? 'present' : 'absent'}`;
    this.elements.personsCount.textContent = String(targets.length);
    this.elements.zonesCount.textContent = String(zones.length);
    this.elements.currentZone.textContent = currentZone || '-';
    this.elements.lastPacketAge.textContent = packetAge;
    this.elements.coordinateCount.textContent = `${coordTargets.length} targets`;
    this.elements.onlineState.textContent = this.formatOnlineState(rawAttributes.online);
    this.elements.movementEvent.textContent = this.formatMovementEventCode(rawAttributes.movement_event);
    this.elements.fallState.textContent = this.formatFallStateCode(rawAttributes.fall_state);
    this.elements.deviceTimestamp.textContent = this.formatDeviceTimestamp(rawAttributes.device_timestamp);
    this.elements.apiDomain.textContent = this.state.connection?.api_domain || this.state.device?.api_domain || '-';

    // RSSI
    if (Number.isFinite(rawAttributes.rssi)) {
      this.state.currentRssi = rawAttributes.rssi;
      this.elements.rssiValue.textContent = this.formatDbm(rawAttributes.rssi);
      this.drawRssiGauge(rawAttributes.rssi);
    }

    // Sensor angle
    this.elements.sensorAngle.textContent = this.formatDegrees(rawAttributes.sensor_angle);
    this.drawAngleDial(rawAttributes.sensor_angle);

    // Coordinate stream status
    this.renderCoordinateFreshness(targets, sampleAtMs);
    this.updateCoordinateStreamStatus(targets, rawAttributes.coordinates, sampleAtMs, rawAttributes.movement_event);

    // Light
    if (typeof rawAttributes.light_level === 'number') {
      this.elements.lightLevel.textContent = `${Math.round(rawAttributes.light_level)} lux`;
    } else {
      this.elements.lightLevel.textContent = '-';
    }

    // Fall alert
    this.updateFallAlert(rawAttributes.fall_state, timestampLabel);

    // Targets
    this.renderPrimaryTarget(primaryTarget);
    this.renderTargetList(targets);
    this.renderResourceGrid(rawAttributes.resource_values || {});
    this.elements.sensorOutput.textContent = JSON.stringify(rawAttributes, null, 2);
    this.elements.rawOutput.textContent = JSON.stringify(data, null, 2);

    // Graph + map
    this.updateGraphData(available && presence, targets.length);
    this.renderZoneWindows(zones, currentZone);
    this.renderAnimatedMap();
    this.startGraphAnimation(this.hasTargetDeltas(targets) ? this.state.animation.durationMs + 120 : 80);

    // Presence duration
    if (available && presence && !this.state.presenceStartedAt) {
      this.state.presenceStartedAt = Date.now();
    }
    if (!available || !presence) {
      this.state.presenceStartedAt = null;
    }
    this.elements.presenceDuration.textContent = this.getPresenceDuration();

    // Presence history
    const currentPresenceState = available ? presence : null;
    if (this.state.lastPresence !== currentPresenceState) {
      this.pushHistory({ timestamp: timestampLabel, presence: currentPresenceState });
    }

    // Movement tracking
    this.trackMovement({
      timestamp: timestampLabel,
      presence: available && presence,
      zone: currentZone,
      movementEvent: rawAttributes.movement_event,
      fallState: rawAttributes.fall_state,
      targetCount: targets.length
    });
  }

  // ── Fall Alert ──

  updateFallAlert(fallState, timestamp) {
    if (!this.elements.fallAlert) return;
    if (fallState === 1 || fallState === 2) {
      this.elements.fallAlert.style.display = 'flex';
      this.elements.fallAlert.className = `fp2-fall-alert ${fallState === 2 ? 'critical' : 'warning'}`;
      this.elements.fallAlertText.textContent = FALL_LABELS[fallState] || `Fall code ${fallState}`;
      this.elements.fallAlertTime.textContent = timestamp;
    } else {
      this.elements.fallAlert.style.display = 'none';
    }
  }

  // ── RSSI Gauge ──

  drawRssiGauge(rssi) {
    const ctx = this.rssiCtx;
    if (!ctx) return;
    const w = 80, h = 44;
    ctx.clearRect(0, 0, w, h);

    // Draw arc gauge
    const cx = w / 2, cy = h - 4;
    const r = 30;
    const startAngle = Math.PI;
    const endAngle = 2 * Math.PI;

    // Background arc
    ctx.beginPath();
    ctx.arc(cx, cy, r, startAngle, endAngle);
    ctx.lineWidth = 6;
    ctx.strokeStyle = 'rgba(148,163,184,0.2)';
    ctx.lineCap = 'round';
    ctx.stroke();

    if (!Number.isFinite(rssi)) return;

    // Signal quality: -30 (best) to -90 (worst)
    const quality = Math.max(0, Math.min(1, (rssi + 90) / 60));
    const fillAngle = startAngle + quality * Math.PI;

    // Gradient color: green → yellow → red
    const color = quality > 0.6 ? '#4ade80' : quality > 0.3 ? '#facc15' : '#f87171';

    ctx.beginPath();
    ctx.arc(cx, cy, r, startAngle, fillAngle);
    ctx.lineWidth = 6;
    ctx.strokeStyle = color;
    ctx.lineCap = 'round';
    ctx.stroke();

    // Needle dot
    const needleX = cx + Math.cos(fillAngle) * r;
    const needleY = cy + Math.sin(fillAngle) * r;
    ctx.fillStyle = color;
    ctx.beginPath();
    ctx.arc(needleX, needleY, 3, 0, Math.PI * 2);
    ctx.fill();
  }

  // ── Sensor Angle Dial ──

  drawAngleDial(angle) {
    const ctx = this.angleCtx;
    if (!ctx) return;
    const s = 32;
    ctx.clearRect(0, 0, s, s);
    const cx = s / 2, cy = s / 2, r = 12;

    // Circle
    ctx.beginPath();
    ctx.arc(cx, cy, r, 0, Math.PI * 2);
    ctx.strokeStyle = 'rgba(148,163,184,0.3)';
    ctx.lineWidth = 1.5;
    ctx.stroke();

    if (!Number.isFinite(angle)) return;

    // Ray
    const rad = (angle - 90) * (Math.PI / 180);
    const rx = cx + Math.cos(rad) * r;
    const ry = cy + Math.sin(rad) * r;
    ctx.beginPath();
    ctx.moveTo(cx, cy);
    ctx.lineTo(rx, ry);
    ctx.strokeStyle = '#facc15';
    ctx.lineWidth = 2;
    ctx.stroke();

    // Tip
    ctx.fillStyle = '#facc15';
    ctx.beginPath();
    ctx.arc(rx, ry, 2, 0, Math.PI * 2);
    ctx.fill();
  }

  // ── Zone & Target data extraction ──

  getZoneStates(data) {
    const rawZones = data?.metadata?.raw_attributes?.zones;
    if (Array.isArray(rawZones) && rawZones.length > 0) return this.normalizeZones(rawZones);

    const zoneSummary = data?.zone_summary || {};
    const summaryZones = Object.entries(zoneSummary).map(([zoneId, targetCount], index) => ({
      zone_id: zoneId, name: zoneId, occupied: Number(targetCount) > 0, target_count: Number(targetCount) || 0, index
    }));
    if (summaryZones.length > 0) return this.normalizeZones(summaryZones);

    if (this.state.zones.length > 0) return this.state.zones;

    return [{
      zone_id: 'detection_area', name: 'Detection Area', displayName: 'Detection Area',
      occupied: Boolean(data?.metadata?.presence), target_count: Boolean(data?.metadata?.presence) ? 1 : 0
    }];
  }

  getTargets(data, rawAttributes, zones) {
    const coordinates = Array.isArray(rawAttributes.coordinates) ? rawAttributes.coordinates : [];
    if (coordinates.length > 0) {
      return coordinates.map((target, i) => ({
        target_id: target.target_id || `target_${i + 1}`,
        zone_id: target.zone_id || zones[0]?.zone_id || 'detection_area',
        x: Number(target.x ?? 0), y: Number(target.y ?? 0),
        distance: Number(target.distance ?? 0), angle: Number(target.angle ?? 0),
        activity: target.activity || 'present', confidence: Number(target.confidence ?? 0.95),
        target_type: target.target_type ?? null, range_id: target.range_id ?? null
      }));
    }

    const rawTargets = Array.isArray(rawAttributes.targets) ? rawAttributes.targets : [];
    if (rawTargets.length > 0) {
      return rawTargets.map((target, i) => ({
        target_id: target.target_id || target.id || `target_${i + 1}`,
        zone_id: target.zone_id || zones[0]?.zone_id || 'detection_area',
        x: Number(target.x ?? 0), y: Number(target.y ?? 0),
        distance: Number(target.distance ?? 0), angle: Number(target.angle ?? 0),
        activity: target.activity || 'present', confidence: Number(target.confidence ?? 0.95),
        target_type: target.target_type ?? null, range_id: target.range_id ?? null
      }));
    }

    const persons = Array.isArray(data?.persons) ? data.persons : [];
    return persons.map((person, i) => ({
      target_id: person.person_id || `person_${i + 1}`,
      zone_id: person.zone_id || zones[0]?.zone_id || 'detection_area',
      x: Number(person.bounding_box?.x ?? person.x ?? 0),
      y: Number(person.bounding_box?.y ?? person.y ?? 0),
      distance: Number(person.distance ?? 0), angle: Number(person.angle ?? 0),
      activity: person.activity || 'present', confidence: Number(person.confidence ?? 0.95),
      target_type: null, range_id: null
    }));
  }

  normalizeZones(zones) {
    return zones.map((zone, i) => {
      const zoneId = zone.zone_id || zone.id || `zone_${i + 1}`;
      const targetCount = Number(zone.target_count ?? zone.count ?? (zone.occupied ? 1 : 0)) || 0;
      return {
        zone_id: zoneId, name: zone.name || zoneId,
        displayName: this.formatZoneName(zoneId, i),
        occupied: Boolean(zone.occupied), target_count: targetCount,
        service_iid: zone.service_iid || null
      };
    });
  }

  detectCurrentZone(data, zones, targets) {
    const coordZone = targets.find(t => t.zone_id)?.zone_id;
    if (coordZone) return this.displayZoneName(coordZone, zones);
    const personZone = data?.persons?.[0]?.zone_id;
    if (personZone) return this.displayZoneName(personZone, zones);
    const occupiedZone = zones.find(z => z.occupied);
    if (occupiedZone) return occupiedZone.displayName;
    const attrs = data?.metadata?.raw_attributes || {};
    if (attrs.current_zone) return this.displayZoneName(attrs.current_zone, zones);
    return null;
  }

  displayZoneName(zoneId, zones) {
    const match = zones.find(z => z.zone_id === zoneId || z.name === zoneId);
    return match?.displayName || zoneId;
  }

  // ── Target deltas & animation ──

  attachTargetDeltas(targets, previousTargets) {
    const prevById = new Map((previousTargets || []).map(t => [t.target_id, t]));
    return targets.map(target => {
      const prev = prevById.get(target.target_id);
      return {
        ...target,
        dx: Number.isFinite(prev?.x) && Number.isFinite(target.x) ? target.x - prev.x : null,
        dy: Number.isFinite(prev?.y) && Number.isFinite(target.y) ? target.y - prev.y : null
      };
    });
  }

  updateTargetAnimation(targets, sampleAtMs) {
    const currentAnimated = this.getInterpolatedTargets();
    const prevSample = this.state.animation.lastSampleAtMs || 0;
    const inferredDuration = prevSample > 0 ? sampleAtMs - prevSample : 900;
    const durationMs = Math.min(1600, Math.max(250, inferredDuration || 900));

    this.state.animation = {
      fromTargets: currentAnimated,
      toTargets: targets,
      startedAtMs: Date.now(),
      durationMs,
      lastSampleAtMs: sampleAtMs
    };
  }

  getInterpolatedTargets() {
    const anim = this.state.animation;
    if (!anim.toTargets.length) return [];
    const duration = Math.max(anim.durationMs || 1, 1);
    const progress = Math.min(1, Math.max(0, (Date.now() - anim.startedAtMs) / duration));
    const prevById = new Map(anim.fromTargets.map(t => [t.target_id, t]));

    return anim.toTargets.map(target => {
      const prev = prevById.get(target.target_id);
      if (!prev || !this.hasCoordinates(prev) || !this.hasCoordinates(target)) return target;
      return {
        ...target,
        x: prev.x + (target.x - prev.x) * progress,
        y: prev.y + (target.y - prev.y) * progress,
        distance: prev.distance + (target.distance - prev.distance) * progress,
        angle: prev.angle + (target.angle - prev.angle) * progress
      };
    });
  }

  hasTargetDeltas(targets) {
    return (targets || []).some(t => Number.isFinite(t?.dx) || Number.isFinite(t?.dy));
  }

  hasCoordinates(target) {
    return Number.isFinite(target?.x) && Number.isFinite(target?.y) && (target.x !== 0 || target.y !== 0);
  }

  // ── Coordinate freshness ──

  buildCoordinateSignature(targets) {
    const ct = (targets || [])
      .filter(t => this.hasCoordinates(t))
      .map(t => [t.target_id, Math.round(t.x), Math.round(t.y), Math.round(t.distance ?? 0), Math.round(t.angle ?? 0)])
      .sort((a, b) => String(a[0]).localeCompare(String(b[0])));
    return ct.length ? JSON.stringify(ct) : null;
  }

  renderCoordinateFreshness(targets, sampleAtMs) {
    if (!this.elements.coordinateStream || !this.elements.coordinateChangeAge) return;

    const signature = this.buildCoordinateSignature(targets);
    if (!signature) {
      this.state.coordinateSignature = null;
      this.state.lastCoordinateChangeAtMs = null;
      this.elements.coordinateChangeAge.textContent = '-';
      return;
    }

    if (this.state.coordinateSignature !== signature) {
      this.state.coordinateSignature = signature;
      this.state.lastCoordinateChangeAtMs = sampleAtMs || Date.now();
    }

    const ageMs = this.state.lastCoordinateChangeAtMs ? Math.max(0, Date.now() - this.state.lastCoordinateChangeAtMs) : null;
    const ageSec = ageMs === null ? null : ageMs / 1000;
    this.elements.coordinateChangeAge.textContent = ageSec === null ? '-' : `${ageSec.toFixed(ageSec < 10 ? 1 : 0)}s ago`;
  }

  updateCoordinateStreamStatus(targets, coordinatesPayload, sampleAtMs, movementEvent) {
    if (!this.elements.coordinateStream) return;

    const coordTargets = targets.filter(t => this.hasCoordinates(t));
    if (!coordinatesPayload || coordTargets.length === 0) {
      this.elements.coordinateStream.textContent = 'ZONE-ONLY';
      this.elements.coordinateStream.className = 'chip warn';
      if (this.elements.mapMode) {
        this.elements.mapMode.textContent = 'ZONE';
        this.elements.mapMode.className = 'chip warn';
      }
      return;
    }

    const ageMs = this.state.lastCoordinateChangeAtMs ? Math.max(0, Date.now() - this.state.lastCoordinateChangeAtMs) : null;
    const ageSec = ageMs !== null ? ageMs / 1000 : null;
    
    // Check coordinate delta movement
    const hasDeltaMovement = this.hasTargetDeltas(targets);
    
    // Also consider movement event codes (1-4, 7 indicate active movement even without coordinate changes)
    const hasMovementEvent = [1, 2, 3, 4, 7].includes(movementEvent);
    
    // Combined movement detection: either delta OR movement event
    const isActivelyMoving = hasDeltaMovement || hasMovementEvent;

    let label, cls;
    if (ageSec === null || ageSec > 60) { label = 'STALE'; cls = 'err'; }
    else if (ageSec <= 2.5 && isActivelyMoving) { label = 'LIVE'; cls = 'ok'; }
    else if (ageSec <= 2.5) { label = 'STATIC'; cls = 'warn'; }
    else if (ageSec <= 10) { label = 'REPEATING'; cls = 'warn'; }
    else { label = 'SLOW'; cls = 'warn'; }

    this.elements.coordinateStream.textContent = label;
    this.elements.coordinateStream.className = `chip ${cls}`;
    if (this.elements.mapMode) {
      this.elements.mapMode.textContent = `COORD · ${label}`;
      this.elements.mapMode.className = `chip ${cls}`;
    }
  }

  // ── Render sub-components ──

  renderPrimaryTarget(target) {
    if (!target) {
      this.elements.primaryTargetId.textContent = '-';
      this.elements.primaryTargetType.textContent = '-';
      this.elements.primaryTargetCoords.textContent = '-';
      this.elements.primaryTargetDistance.textContent = '-';
      this.elements.primaryTargetAngle.textContent = '-';
      return;
    }
    this.elements.primaryTargetId.textContent = target.target_id || '-';
    this.elements.primaryTargetType.textContent = target.target_type ?? (target.range_id ?? '-');
    this.elements.primaryTargetCoords.textContent = this.hasCoordinates(target) ? `${this.fmtCoord(target.x)}, ${this.fmtCoord(target.y)}` : '-';
    this.elements.primaryTargetDistance.textContent = this.formatDistance(target.distance);
    this.elements.primaryTargetAngle.textContent = this.hasCoordinates(target)
      ? `${this.formatAngle(target.angle)} · Δ ${this.fmtDelta(target.dx)}, ${this.fmtDelta(target.dy)}`
      : this.formatAngle(target.angle);
  }

  renderTargetList(targets) {
    if (!this.elements.targetList) return;
    if (!targets.length) {
      this.elements.targetList.innerHTML = '<div class="fp2-empty-state">No coordinate targets in the current sample.</div>';
      return;
    }

    this.elements.targetList.innerHTML = targets.map((t, i) => {
      const color = TARGET_COLORS[i % TARGET_COLORS.length];
      const hasXY = this.hasCoordinates(t);
      const velocityMag = (Number.isFinite(t.dx) && Number.isFinite(t.dy)) ? Math.sqrt(t.dx * t.dx + t.dy * t.dy) : 0;
      const velocityLabel = velocityMag > 0 ? `${velocityMag.toFixed(1)} u/s` : '-';

      return `
        <article class="fp2-target-card ${hasXY ? 'has-coords' : ''}">
          <div class="fp2-target-card-header">
            <span class="fp2-target-dot" style="background:${color}"></span>
            <strong>${t.target_id}</strong>
            <span class="fp2-target-zone">${this.displayZoneName(t.zone_id, this.state.zones)}</span>
          </div>
          <div class="fp2-target-card-body">
            <div class="fp2-target-metric"><span class="fp2-target-metric-label">XY</span><span>${hasXY ? `${this.fmtCoord(t.x)}, ${this.fmtCoord(t.y)}` : '-'}</span></div>
            <div class="fp2-target-metric"><span class="fp2-target-metric-label">Dist</span><span>${this.formatDistance(t.distance)}</span></div>
            <div class="fp2-target-metric"><span class="fp2-target-metric-label">Angle</span><span>${this.formatAngle(t.angle)}</span></div>
            <div class="fp2-target-metric"><span class="fp2-target-metric-label">Delta</span><span>Δ ${this.fmtDelta(t.dx)}, ${this.fmtDelta(t.dy)}</span></div>
            <div class="fp2-target-metric"><span class="fp2-target-metric-label">Speed</span><span>${velocityLabel}</span></div>
            ${t.target_type !== null ? `<div class="fp2-target-metric"><span class="fp2-target-metric-label">Type</span><span>${t.target_type}</span></div>` : ''}
          </div>
        </article>`;
    }).join('');
  }

  renderResourceGrid(resourceValues) {
    if (!this.elements.resourceGrid) return;
    const entries = Object.entries(resourceValues || {});
    if (!entries.length) {
      this.elements.resourceGrid.innerHTML = '<div class="fp2-empty-state">No raw resource channels in the current payload.</div>';
      return;
    }

    this.elements.resourceGrid.innerHTML = entries.map(([rid, value]) => {
      let displayValue = value;
      if (rid === '4.22.700' && value) {
        try {
          const coords = typeof value === 'string' ? JSON.parse(value) : value;
          const active = Array.isArray(coords) ? coords.filter(t => t && t.state === "1" && (t.x !== 0 || t.y !== 0)) : [];
          displayValue = active.length > 0 ? JSON.stringify(active, null, 2) : '[] (no active targets)';
        } catch { displayValue = value; }
      }
      return `
        <article class="fp2-resource-item">
          <span class="fp2-resource-label">${RESOURCE_LABELS[rid] || 'Resource'}</span>
          <code class="fp2-resource-id">${rid}</code>
          <pre class="fp2-resource-value fp2-resource-value--json">${displayValue ?? '-'}</pre>
        </article>`;
    }).join('');
  }

  renderZoneWindows(zones, currentZone) {
    const container = this.elements.zoneWindows;
    if (!container) return;

    if (!zones.length) {
      container.innerHTML = '<div class="fp2-zone-window fp2-zone-window--empty">No zone telemetry yet</div>';
      return;
    }

    container.innerHTML = zones.map(zone => {
      const isCurrent = currentZone && zone.displayName === currentZone;
      return `
        <article class="fp2-zone-window ${zone.occupied ? 'active' : ''} ${isCurrent ? 'current' : ''}">
          <div class="fp2-zone-window-header">
            <h4>${zone.displayName}</h4>
            <span class="fp2-zone-window-status">${zone.occupied ? 'OCCUPIED' : 'CLEAR'}</span>
          </div>
          <div class="fp2-zone-window-body">
            <span class="fp2-zone-window-count">${zone.target_count || 0}</span>
            <span class="fp2-zone-window-label">targets</span>
          </div>
          <div class="fp2-zone-window-meta">
            <span>${zone.zone_id}</span>
          </div>
        </article>`;
    }).join('');
  }

  // ── Movement tracking ──

  trackMovement(event) {
    const prevPresence = this.state.lastPresence;
    const prevZone = this.state.currentZone;

    if (prevPresence === null) {
      this.state.lastPresence = event.presence;
      this.state.currentZone = event.zone;
      this.state.lastMovementEvent = event.movementEvent ?? null;
      this.state.lastFallState = event.fallState ?? null;
      this.state.lastTargetCount = event.targetCount ?? null;
      if (event.presence) {
        this.pushMovementEvent(event.timestamp, 'enter', `Presence detected in ${event.zone || 'detection area'}`);
      }
      return;
    }

    if (!prevPresence && event.presence) {
      this.pushMovementEvent(event.timestamp, 'enter', `Entered ${event.zone || 'detection area'}`);
    } else if (prevPresence && !event.presence) {
      this.pushMovementEvent(event.timestamp, 'exit', `Left ${prevZone || 'detection area'}`);
    } else if (event.presence && prevZone && event.zone && prevZone !== event.zone) {
      this.pushMovementEvent(event.timestamp, 'move', `${prevZone} → ${event.zone}`);
    }

    if (event.movementEvent !== undefined && event.movementEvent !== this.state.lastMovementEvent) {
      let label = this.formatMovementEventCode(event.movementEvent);
      if (event.movementEvent === 1 && this.state.currentSensorAngle !== null) {
        label += ` · ${Math.round(this.state.currentSensorAngle)}°`;
      }
      if ([5, 6, 7].includes(event.movementEvent)) {
        const active = this.state.targets.filter(t => this.hasCoordinates(t));
        if (active.length > 0) label += ` · ${active.length} target${active.length > 1 ? 's' : ''}`;
      }
      this.pushMovementEvent(event.timestamp, 'telemetry', label);
    }

    if (event.fallState !== undefined && event.fallState !== this.state.lastFallState) {
      const fallLabel = this.formatFallStateCode(event.fallState);
      this.pushMovementEvent(event.timestamp, event.fallState ? 'alert' : 'telemetry', fallLabel);
    }

    if (event.targetCount !== undefined && event.targetCount !== this.state.lastTargetCount) {
      this.pushMovementEvent(event.timestamp, 'telemetry', `Target count ${event.targetCount}`);
    }

    this.state.lastPresence = event.presence;
    this.state.currentZone = event.zone;
    this.state.lastMovementEvent = event.movementEvent ?? this.state.lastMovementEvent;
    this.state.lastFallState = event.fallState ?? this.state.lastFallState;
    this.state.lastTargetCount = event.targetCount ?? this.state.lastTargetCount;
  }

  pushMovementEvent(timestamp, type, text) {
    this.state.movementHistory.unshift({ timestamp, type, text });
    this.state.movementHistory = this.state.movementHistory.slice(0, 30);
    this.renderMovementHistory();
  }

  renderMovementHistory() {
    if (!this.elements.movementList) return;
    this.elements.movementList.innerHTML = '';
    this.state.movementHistory.forEach(entry => {
      const item = document.createElement('li');
      item.className = 'fp2-history-item';
      item.innerHTML = `
        <span class="fp2-event-time">${entry.timestamp}</span>
        <span class="fp2-event-text">${entry.text}</span>
        <strong class="fp2-event fp2-event-${entry.type}">${entry.type.toUpperCase()}</strong>`;
      this.elements.movementList.appendChild(item);
    });
  }

  pushHistory(item) {
    this.state.history.unshift(item);
    this.state.history = this.state.history.slice(0, 16);

    if (!this.elements.historyList) return;
    this.elements.historyList.innerHTML = '';
    this.state.history.forEach(entry => {
      const el = document.createElement('li');
      el.className = 'fp2-history-item';
      el.innerHTML = `
        <span>${entry.timestamp}</span>
        <strong class="${entry.presence === null ? 'err' : entry.presence ? 'ok' : 'muted'}">
          ${entry.presence === null ? 'UNAVAILABLE' : entry.presence ? 'PRESENT' : 'ABSENT'}
        </strong>`;
      this.elements.historyList.appendChild(el);
    });
  }

  // ── Movement Map (enlarged, with trails) ──

  renderAnimatedMap() {
    this.drawMovementMap(this.state.zones, this.state.currentPresenceActive, this.getInterpolatedTargets(), this.state.currentSensorAngle, this.state.currentAvailability);
  }

  drawMovementMap(zones, presence, targets, sensorAngle, available) {
    const canvas = this.elements.movementCanvas;
    const ctx = this.canvasCtx;
    if (!canvas || !ctx) return;

    const width = canvas.width;
    const height = canvas.height;
    ctx.clearRect(0, 0, width, height);

    // Background
    ctx.fillStyle = '#0c1220';
    ctx.fillRect(0, 0, width, height);

    const coordTargets = targets.filter(t => this.hasCoordinates(t));
    if (coordTargets.length > 0) {
      this.drawCoordinateMap(ctx, width, height, coordTargets, sensorAngle, available);
      return;
    }

    // Zone-based fallback
    const zoneList = zones.length > 0 ? zones : [{ displayName: 'Detection Area', zone_id: 'detection_area', occupied: presence, target_count: presence ? 1 : 0 }];
    const gap = 18, padding = 24;
    const zoneWidth = Math.max(140, (width - padding * 2 - gap * (zoneList.length - 1)) / zoneList.length);
    const zoneHeight = height - padding * 2;

    zoneList.forEach((zone, i) => {
      const x = padding + i * (zoneWidth + gap);
      const y = padding;
      const active = Boolean(zone.occupied);

      this.drawRoundedRect(ctx, x, y, zoneWidth, zoneHeight, 18);
      ctx.fillStyle = active ? 'rgba(74,222,128,0.15)' : 'rgba(148,163,184,0.06)';
      ctx.fill();
      ctx.lineWidth = active ? 2 : 1;
      ctx.strokeStyle = active ? 'rgba(74,222,128,0.8)' : 'rgba(148,163,184,0.2)';
      ctx.stroke();

      ctx.fillStyle = '#f8fafc';
      ctx.font = '600 15px sans-serif';
      ctx.fillText(zone.displayName, x + 18, y + 30);

      ctx.fillStyle = active ? 'rgba(134,239,172,0.9)' : 'rgba(148,163,184,0.7)';
      ctx.font = '11px monospace';
      ctx.fillText(zone.zone_id, x + 18, y + 48);

      ctx.fillStyle = active ? '#4ade80' : '#475569';
      ctx.font = '700 36px sans-serif';
      ctx.fillText(active ? 'OCCUPIED' : 'CLEAR', x + 18, y + zoneHeight / 2 + 12);

      ctx.fillStyle = '#94a3b8';
      ctx.font = '13px sans-serif';
      ctx.fillText(`${zone.target_count || 0} target(s)`, x + 18, y + zoneHeight / 2 + 40);

      if (active) {
        const px = x + zoneWidth - 50;
        const py = y + zoneHeight / 2;
        const pulseR = 20 + Math.sin(Date.now() / 200) * 6;
        ctx.strokeStyle = 'rgba(74,222,128,0.3)';
        ctx.lineWidth = 2;
        ctx.beginPath();
        ctx.arc(px, py, pulseR, 0, Math.PI * 2);
        ctx.stroke();
        ctx.fillStyle = 'rgba(74,222,128,0.85)';
        ctx.beginPath();
        ctx.arc(px, py, 8, 0, Math.PI * 2);
        ctx.fill();
      }
    });

    // Status label
    ctx.fillStyle = available && presence ? 'rgba(74,222,128,0.9)' : 'rgba(248,113,113,0.9)';
    ctx.font = '700 13px monospace';
    ctx.fillText(available && presence ? 'ZONE MODE' : 'ROOM CLEAR', width - 120, 22);
  }

  drawCoordinateMap(ctx, width, height, targets, sensorAngle, available) {
    const margin = 40;
    const plotLeft = margin;
    const plotTop = 30;
    const plotWidth = width - margin * 2;
    const plotHeight = height - margin - 20;
    const originX = plotLeft + plotWidth / 2;
    const originY = plotTop + plotHeight / 2;
    const maxAbs = Math.max(400, ...targets.flatMap(t => [Math.abs(t.x || 0), Math.abs(t.y || 0)]));

    const toCanvasX = (x) => originX + (x / maxAbs) * (plotWidth / 2 - 30);
    const toCanvasY = (y) => originY - (y / maxAbs) * (plotHeight / 2 - 30);

    // Grid
    ctx.strokeStyle = 'rgba(148,163,184,0.08)';
    ctx.lineWidth = 1;
    for (let i = 0; i <= 8; i++) {
      const x = plotLeft + (plotWidth / 8) * i;
      const y = plotTop + (plotHeight / 8) * i;
      ctx.beginPath(); ctx.moveTo(x, plotTop); ctx.lineTo(x, plotTop + plotHeight); ctx.stroke();
      ctx.beginPath(); ctx.moveTo(plotLeft, y); ctx.lineTo(plotLeft + plotWidth, y); ctx.stroke();
    }

    // Range rings
    ctx.strokeStyle = 'rgba(99,102,241,0.12)';
    ctx.lineWidth = 1;
    for (let r = 100; r <= maxAbs; r += 100) {
      const pr = (r / maxAbs) * (Math.min(plotWidth, plotHeight) / 2 - 30);
      ctx.beginPath();
      ctx.arc(originX, originY, pr, 0, Math.PI * 2);
      ctx.stroke();
      ctx.fillStyle = 'rgba(99,102,241,0.3)';
      ctx.font = '9px monospace';
      ctx.fillText(`${r}`, originX + pr + 3, originY - 3);
    }

    // Axes
    ctx.strokeStyle = 'rgba(99,102,241,0.35)';
    ctx.lineWidth = 1.5;
    ctx.beginPath(); ctx.moveTo(originX, plotTop); ctx.lineTo(originX, plotTop + plotHeight); ctx.stroke();
    ctx.beginPath(); ctx.moveTo(plotLeft, originY); ctx.lineTo(plotLeft + plotWidth, originY); ctx.stroke();

    // Origin
    ctx.fillStyle = '#6366f1';
    ctx.beginPath();
    ctx.arc(originX, originY, 6, 0, Math.PI * 2);
    ctx.fill();
    ctx.fillStyle = 'rgba(248,250,252,0.6)';
    ctx.font = '11px sans-serif';
    ctx.fillText('Sensor', originX - 18, originY + 20);

    // Sensor angle ray
    if (Number.isFinite(sensorAngle)) {
      const rayLen = Math.min(plotWidth, plotHeight) * 0.4;
      const rad = sensorAngle * (Math.PI / 180);
      const rx = originX + Math.cos(rad) * rayLen;
      const ry = originY - Math.sin(rad) * rayLen;

      // FOV cone
      const fovHalf = 30 * (Math.PI / 180);
      ctx.fillStyle = 'rgba(250,204,21,0.05)';
      ctx.beginPath();
      ctx.moveTo(originX, originY);
      ctx.arc(originX, originY, rayLen, -(rad + fovHalf), -(rad - fovHalf));
      ctx.closePath();
      ctx.fill();

      ctx.strokeStyle = 'rgba(250,204,21,0.5)';
      ctx.lineWidth = 2;
      ctx.setLineDash([6, 4]);
      ctx.beginPath(); ctx.moveTo(originX, originY); ctx.lineTo(rx, ry); ctx.stroke();
      ctx.setLineDash([]);

      ctx.fillStyle = 'rgba(250,204,21,0.85)';
      ctx.font = '10px monospace';
      ctx.fillText(`${Math.round(sensorAngle)}°`, rx + 6, ry - 4);
    }

    // Draw trail history (fading paths)
    const trail = this.state.trailHistory;
    if (trail.length > 1) {
      const byId = new Map();
      trail.forEach((snapshot, si) => {
        snapshot.targets.forEach(t => {
          if (!byId.has(t.id)) byId.set(t.id, []);
          byId.get(t.id).push({ x: t.x, y: t.y, si });
        });
      });

      let colorIndex = 0;
      byId.forEach((points, id) => {
        if (points.length < 2) { colorIndex++; return; }
        const color = TARGET_COLORS[colorIndex % TARGET_COLORS.length];
        colorIndex++;

        for (let j = 1; j < points.length; j++) {
          const opacity = 0.08 + (j / points.length) * 0.25;
          const px1 = toCanvasX(points[j - 1].x);
          const py1 = toCanvasY(points[j - 1].y);
          const px2 = toCanvasX(points[j].x);
          const py2 = toCanvasY(points[j].y);

          ctx.strokeStyle = color.replace(')', `,${opacity})`).replace('rgb', 'rgba').replace('#', '');
          // Use hex with alpha workaround
          ctx.globalAlpha = opacity;
          ctx.strokeStyle = color;
          ctx.lineWidth = 1.5;
          ctx.beginPath();
          ctx.moveTo(px1, py1);
          ctx.lineTo(px2, py2);
          ctx.stroke();

          // Trail dots
          ctx.fillStyle = color;
          ctx.beginPath();
          ctx.arc(px2, py2, 1.5, 0, Math.PI * 2);
          ctx.fill();
        }
        ctx.globalAlpha = 1;
      });
    }

    // Draw targets
    targets.forEach((target, i) => {
      const px = toCanvasX(target.x);
      const py = toCanvasY(target.y);
      const color = TARGET_COLORS[i % TARGET_COLORS.length];

      // Connection line to origin
      ctx.strokeStyle = `${color}44`;
      ctx.lineWidth = 1.5;
      ctx.beginPath();
      ctx.moveTo(originX, originY);
      ctx.lineTo(px, py);
      ctx.stroke();

      // Velocity vector
      if (Number.isFinite(target.dx) && Number.isFinite(target.dy) && (Math.abs(target.dx) > 0.5 || Math.abs(target.dy) > 0.5)) {
        const scale = 3;
        const vx = px + target.dx * scale;
        const vy = py - target.dy * scale;
        ctx.strokeStyle = `${color}88`;
        ctx.lineWidth = 2;
        ctx.beginPath();
        ctx.moveTo(px, py);
        ctx.lineTo(vx, vy);
        ctx.stroke();

        // Arrowhead
        const angle = Math.atan2(vy - py, vx - px);
        ctx.fillStyle = color;
        ctx.beginPath();
        ctx.moveTo(vx, vy);
        ctx.lineTo(vx - 6 * Math.cos(angle - 0.4), vy - 6 * Math.sin(angle - 0.4));
        ctx.lineTo(vx - 6 * Math.cos(angle + 0.4), vy - 6 * Math.sin(angle + 0.4));
        ctx.closePath();
        ctx.fill();
      }

      // Target glow
      const gradient = ctx.createRadialGradient(px, py, 0, px, py, 20);
      gradient.addColorStop(0, `${color}40`);
      gradient.addColorStop(1, `${color}00`);
      ctx.fillStyle = gradient;
      ctx.beginPath();
      ctx.arc(px, py, 20, 0, Math.PI * 2);
      ctx.fill();

      // Target dot
      ctx.fillStyle = color;
      ctx.beginPath();
      ctx.arc(px, py, i === 0 ? 8 : 6, 0, Math.PI * 2);
      ctx.fill();
      ctx.strokeStyle = '#fff';
      ctx.lineWidth = 1.5;
      ctx.stroke();

      // Label
      ctx.fillStyle = '#e2e8f0';
      ctx.font = '600 11px monospace';
      ctx.fillText(target.target_id, px + 12, py - 10);
      ctx.fillStyle = '#94a3b8';
      ctx.font = '10px monospace';
      ctx.fillText(`${this.fmtCoord(target.x)}, ${this.fmtCoord(target.y)}`, px + 12, py + 4);
      ctx.fillText(`${this.formatDistance(target.distance)} · ${this.formatAngle(target.angle)}`, px + 12, py + 16);
    });

    // Status badge
    ctx.fillStyle = available ? 'rgba(74,222,128,0.9)' : 'rgba(248,113,113,0.9)';
    ctx.font = '700 12px monospace';
    ctx.fillText(available ? `COORDINATE MODE · ${targets.length} target${targets.length !== 1 ? 's' : ''}` : 'TARGETS UNAVAILABLE', width - 260, 22);

    // Axis labels
    ctx.fillStyle = 'rgba(148,163,184,0.4)';
    ctx.font = '9px monospace';
    ctx.fillText('+Y', originX + 4, plotTop + 8);
    ctx.fillText('-Y', originX + 4, plotTop + plotHeight - 4);
    ctx.fillText('+X', plotLeft + plotWidth - 18, originY - 4);
    ctx.fillText('-X', plotLeft + 4, originY - 4);
  }

  drawRoundedRect(ctx, x, y, w, h, r) {
    ctx.beginPath();
    ctx.moveTo(x + r, y);
    ctx.lineTo(x + w - r, y);
    ctx.quadraticCurveTo(x + w, y, x + w, y + r);
    ctx.lineTo(x + w, y + h - r);
    ctx.quadraticCurveTo(x + w, y + h, x + w - r, y + h);
    ctx.lineTo(x + r, y + h);
    ctx.quadraticCurveTo(x, y + h, x, y + h - r);
    ctx.lineTo(x, y + r);
    ctx.quadraticCurveTo(x, y, x + r, y);
    ctx.closePath();
  }

  // ── Real-time Presence Graph (enhanced with target count) ──

  startGraphAnimation(durationMs = 0) {
    const now = Date.now();
    this.renderLoopUntilMs = Math.max(this.renderLoopUntilMs, now + Math.max(0, durationMs));
    if (this.graphAnimationId) return;

    const animate = () => {
      this.drawRealtimeGraph();
      this.renderAnimatedMap();
      if (Date.now() < this.renderLoopUntilMs) {
        this.graphAnimationId = requestAnimationFrame(animate);
        return;
      }
      this.graphAnimationId = null;
    };
    this.graphAnimationId = requestAnimationFrame(animate);
  }

  stopGraphAnimation() {
    if (this.graphAnimationId) {
      cancelAnimationFrame(this.graphAnimationId);
      this.graphAnimationId = null;
    }
  }

  updateGraphData(presence, targetCount = 0) {
    this.graphData.push({ timestamp: Date.now(), presence: presence ? 1 : 0, targets: targetCount });
    if (this.graphData.length > this.maxGraphPoints) this.graphData.shift();
    this.drawRealtimeGraph();
  }

  drawRealtimeGraph() {
    const canvas = this.graphCanvas;
    const ctx = this.graphCtx;
    if (!canvas || !ctx) return;

    const width = canvas.width;
    const height = canvas.height;
    ctx.fillStyle = '#101722';
    ctx.fillRect(0, 0, width, height);

    // Grid lines
    ctx.strokeStyle = 'rgba(255,255,255,0.06)';
    ctx.lineWidth = 1;
    for (let i = 0; i < 5; i++) {
      const y = (height / 4) * i;
      ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(width, y); ctx.stroke();
    }

    // Labels
    ctx.fillStyle = 'rgba(255,255,255,0.4)';
    ctx.font = '10px sans-serif';
    ctx.fillText('Present', 8, 15);
    ctx.fillText('Absent', 8, height - 6);

    if (this.graphData.length < 2) return;

    const xStep = width / this.maxGraphPoints;
    const presenceY = 30;
    const absentY = height - 20;

    // Target count bars (background layer)
    const maxTargets = Math.max(1, ...this.graphData.map(p => p.targets || 0));
    this.graphData.forEach((point, i) => {
      if (point.targets > 0) {
        const x = i * xStep;
        const barHeight = (point.targets / maxTargets) * (height - 60);
        ctx.fillStyle = 'rgba(56,189,248,0.12)';
        ctx.fillRect(x, height - 20 - barHeight, Math.max(xStep - 1, 2), barHeight);
      }
    });

    // Presence fill
    ctx.fillStyle = 'rgba(74,222,128,0.12)';
    ctx.beginPath();
    ctx.moveTo(0, height);
    this.graphData.forEach((point, i) => {
      const x = i * xStep;
      const y = point.presence ? presenceY : absentY;
      ctx.lineTo(x, y);
    });
    ctx.lineTo((this.graphData.length - 1) * xStep, height);
    ctx.closePath();
    ctx.fill();

    // Presence line
    ctx.strokeStyle = '#4ade80';
    ctx.lineWidth = 2;
    ctx.beginPath();
    this.graphData.forEach((point, i) => {
      const x = i * xStep;
      const y = point.presence ? presenceY : absentY;
      if (i === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    });
    ctx.stroke();

    // Target count line (overlay)
    if (maxTargets > 0) {
      ctx.strokeStyle = 'rgba(56,189,248,0.6)';
      ctx.lineWidth = 1.5;
      ctx.setLineDash([3, 3]);
      ctx.beginPath();
      this.graphData.forEach((point, i) => {
        const x = i * xStep;
        const y = height - 20 - ((point.targets || 0) / maxTargets) * (height - 60);
        if (i === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      });
      ctx.stroke();
      ctx.setLineDash([]);
    }

    // Current point
    const last = this.graphData[this.graphData.length - 1];
    const lastX = (this.graphData.length - 1) * xStep;
    const lastY = last.presence ? presenceY : absentY;
    ctx.fillStyle = last.presence ? '#4ade80' : '#94a3b8';
    ctx.beginPath();
    ctx.arc(lastX, lastY, 5, 0, Math.PI * 2);
    ctx.fill();
    ctx.strokeStyle = '#fff';
    ctx.lineWidth = 1.5;
    ctx.stroke();

    // Target count label
    if (last.targets > 0) {
      ctx.fillStyle = '#38bdf8';
      ctx.font = '600 11px monospace';
      ctx.fillText(`${last.targets} targets`, lastX - 60, height - 24 - ((last.targets / maxTargets) * (height - 60)));
    }
  }

  // ── Formatting helpers ──

  formatZoneName(zoneId, index) {
    if (!zoneId) return `Zone ${index + 1}`;
    if (/^occupancy_\d+$/i.test(zoneId)) return `Zone ${index + 1}`;
    return zoneId.replace(/^zone[_-]?/i, 'Zone ').replace(/[_-]+/g, ' ').replace(/\s+/g, ' ').trim().replace(/\b\w/g, c => c.toUpperCase());
  }

  formatTransport(transport) {
    if (!transport) return 'Direct sensor';
    return String(transport).replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
  }

  formatConnectionState(state) {
    if (!state) return '-';
    if (state === 'live') return 'Live telemetry stream';
    if (state === 'waiting_for_hap_push') return 'Waiting for sensor updates';
    return String(state).replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
  }

  formatEndpoint(ip, port) { return ip ? (port ? `${ip}:${port}` : ip) : '-'; }

  formatNetworkInfo(wifi) {
    const parts = [];
    if (wifi.ssid) parts.push(wifi.ssid);
    if (wifi.channel && wifi.channel !== '-') parts.push(`ch ${wifi.channel}`);
    if (wifi.signal_strength && wifi.signal_strength !== '-') parts.push(`${wifi.signal_strength} dBm`);
    return parts.join(' · ') || '-';
  }

  formatTimestamp(timestamp) {
    if (!timestamp) return new Date().toLocaleTimeString();
    const d = new Date(timestamp);
    return Number.isNaN(d.getTime()) ? new Date().toLocaleTimeString() : d.toLocaleTimeString();
  }

  formatDeviceTimestamp(ts) {
    if (!Number.isFinite(ts)) return '-';
    const d = new Date(ts * 1000);
    if (Number.isNaN(d.getTime())) return '-';
    const ageSec = (Date.now() - d.getTime()) / 1000;
    return `${d.toLocaleTimeString()} (${ageSec.toFixed(ageSec < 10 ? 1 : 0)}s ago)`;
  }

  formatOnlineState(online) { return online === true ? 'ONLINE' : online === false ? 'OFFLINE' : '-'; }
  formatDbm(v) { return Number.isFinite(v) ? `${Math.round(v)} dBm` : '-'; }
  formatDegrees(v) { return Number.isFinite(v) ? `${Math.round(v)}°` : '-'; }
  formatDistance(v) { return Number.isFinite(v) ? `${v.toFixed(1)} cm` : '-'; }
  formatAngle(v) { return Number.isFinite(v) ? `${v.toFixed(1)}°` : '-'; }
  fmtCoord(v) { return Number.isFinite(v) ? `${Math.round(v)}` : '-'; }
  fmtDelta(v) { return Number.isFinite(v) ? `${v >= 0 ? '+' : ''}${Math.round(v)}` : '-'; }

  formatMovementEventCode(v) {
    if (v === null || v === undefined || v === '') return '-';
    const label = MOVEMENT_LABELS[v];
    return label ? `${label} (${v})` : `Code ${v}`;
  }

  formatFallStateCode(v) {
    if (v === null || v === undefined || v === '') return '-';
    const label = FALL_LABELS[v];
    return label ? `${label} (${v})` : `Code ${v}`;
  }

  getPacketAge(pushTime) {
    if (!Number.isFinite(pushTime)) return '-';
    const ageSec = Math.max(0, Date.now() / 1000 - pushTime);
    return `${ageSec.toFixed(ageSec < 10 ? 1 : 0)}s`;
  }

  resolveSampleTimestampMs(iso, devTs) {
    const parsed = iso ? Date.parse(iso) : NaN;
    if (Number.isFinite(parsed)) return parsed;
    if (Number.isFinite(devTs)) return devTs * 1000;
    return Date.now();
  }

  getPresenceDuration() {
    if (!this.state.presenceStartedAt) return '0s';
    const sec = Math.max(0, Math.floor((Date.now() - this.state.presenceStartedAt) / 1000));
    const m = Math.floor(sec / 60);
    const s = sec % 60;
    return m === 0 ? `${s}s` : `${m}m ${s}s`;
  }

  // ── Lifecycle ──

  startPolling() {
    this.stopPolling();
    this.pollTimer = setInterval(async () => {
      await this.loadStatus();
      if (this.state.streamState !== 'live' && this.state.streamState !== 'connected') {
        await this.loadCurrent();
      }
    }, 3000);
  }

  stopPolling() { if (this.pollTimer) { clearInterval(this.pollTimer); this.pollTimer = null; } }

  startDurationTicker() {
    this.stopDurationTicker();
    this.durationTimer = setInterval(() => {
      this.elements.presenceDuration.textContent = this.getPresenceDuration();
    }, 1000);
  }

  stopDurationTicker() { if (this.durationTimer) { clearInterval(this.durationTimer); this.durationTimer = null; } }

  dispose() {
    this.stopPolling();
    this.stopDurationTicker();
    this.stopGraphAnimation();
    fp2Service.stopStream();
    if (this.unsubscribe) { this.unsubscribe(); this.unsubscribe = null; }
  }
}
