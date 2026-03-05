// FP2 Monitor Tab Component

import { fp2Service } from '../services/fp2.service.js?v=20260301-fix5';

export class FP2Tab {
  constructor(containerElement) {
    this.container = containerElement;
    this.unsubscribe = null;
    this.pollTimer = null;
    this.durationTimer = null;
    this.state = {
      streamState: 'disconnected',
      apiEnabled: false,
      lastUpdate: null,
      history: [],
      movementHistory: [],
      currentZone: null,
      lastPresence: null,
      presenceStartedAt: null,
      entities: [],
      selectedEntity: fp2Service.getSelectedEntity(),
      trajectories: []
    };
  }

  async init() {
    this.cacheElements();
    this.bindEvents();
    this.initCanvas();
    this.initRealtimeGraph();

    this.unsubscribe = fp2Service.subscribe((message) => this.handleMessage(message));

    await this.loadEntitiesCount();
    await this.autoSelectEntityIfNeeded();
    await this.refreshAll();
    await this.startStreaming();
    this.startPolling();
    this.startDurationTicker();
  }

  cacheElements() {
    this.elements = {
      refreshBtn: this.container.querySelector('#fp2Refresh'),
      streamBtn: this.container.querySelector('#fp2StreamToggle'),
      entitySelect: this.container.querySelector('#fp2EntitySelect'),
      entityAutoBtn: this.container.querySelector('#fp2EntityAuto'),
      apiStatus: this.container.querySelector('#fp2ApiStatus'),
      streamStatus: this.container.querySelector('#fp2StreamStatus'),
      presenceValue: this.container.querySelector('#fp2PresenceValue'),
      updatedAt: this.container.querySelector('#fp2UpdatedAt'),
      entityId: this.container.querySelector('#fp2EntityId'),
      personsCount: this.container.querySelector('#fp2PersonsCount'),
      zonesCount: this.container.querySelector('#fp2ZonesCount'),
      entitiesCount: this.container.querySelector('#fp2EntitiesCount'),
      currentZone: this.container.querySelector('#fp2CurrentZone'),
      presenceDuration: this.container.querySelector('#fp2PresenceDuration'),
      historyList: this.container.querySelector('#fp2HistoryList'),
      movementList: this.container.querySelector('#fp2MovementList'),
      rawOutput: this.container.querySelector('#fp2RawOutput'),
      movementCanvas: this.container.querySelector('#fp2MovementCanvas')
    };
  }

  bindEvents() {
    if (this.elements.refreshBtn) {
      this.elements.refreshBtn.addEventListener('click', async () => {
        await this.refreshAll();
      });
    }

    if (this.elements.streamBtn) {
      this.elements.streamBtn.addEventListener('click', async () => {
        if (this.state.streamState === 'connected' || this.state.streamState === 'connecting') {
          fp2Service.stopStream();
          this.updateStreamState('disconnected');
        } else {
          await this.startStreaming();
        }
      });
    }

    if (this.elements.entitySelect) {
      this.elements.entitySelect.addEventListener('change', async () => {
        const selected = this.elements.entitySelect.value || null;
        this.state.selectedEntity = selected;
        fp2Service.setSelectedEntity(selected);
        await this.restartStreamAndRefresh();
      });
    }

    if (this.elements.entityAutoBtn) {
      this.elements.entityAutoBtn.addEventListener('click', async () => {
        await this.autoSelectEntity();
      });
    }
  }

  initCanvas() {
    const canvas = this.elements.movementCanvas;
    if (!canvas) {
      return;
    }
    this.canvasCtx = canvas.getContext('2d');
    this.drawMovementMap(null);
  }

  async refreshAll() {
    await Promise.all([
      this.loadStatus(),
      this.loadCurrent(),
      this.loadEntitiesCount()
    ]);
  }

  async loadStatus() {
    try {
      const status = await fp2Service.getStatus();
      this.state.apiEnabled = Boolean(status.enabled);
      this.elements.apiStatus.textContent = this.state.apiEnabled ? 'Enabled' : 'Disabled';
      this.elements.apiStatus.className = `chip ${this.state.apiEnabled ? 'ok' : 'warn'}`;

      // Show currently selected entity in UI; if none selected then backend default.
      const selectedEntity = this.state.selectedEntity || status.entity_id || '-';
      this.elements.entityId.textContent = selectedEntity;
    } catch (_error) {
      // Don't show Error if we already had successful data before
      if (!this.state.apiEnabled) {
        this.elements.apiStatus.textContent = 'Error';
        this.elements.apiStatus.className = 'chip err';
      }
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

  async loadEntitiesCount() {
    try {
      const entities = await fp2Service.getEntities();
      this.state.entities = entities.entities || [];
      this.elements.entitiesCount.textContent = String(entities.count ?? 0);
      this.populateEntitySelector();
    } catch (_error) {
      this.elements.entitiesCount.textContent = '-';
    }
  }

  populateEntitySelector() {
    const select = this.elements.entitySelect;
    if (!select) {
      return;
    }

    const current = this.state.selectedEntity || '';
    select.innerHTML = '';

    const defaultOption = document.createElement('option');
    defaultOption.value = '';
    defaultOption.textContent = 'Default (.env FP2_ENTITY_ID)';
    select.appendChild(defaultOption);

    this.state.entities.forEach((entity) => {
      const option = document.createElement('option');
      option.value = entity.entity_id;
      const friendly = entity.attributes?.friendly_name || entity.entity_id;
      option.textContent = `${friendly} (${entity.entity_id})`;
      select.appendChild(option);
    });

    select.value = current;
  }

  async autoSelectEntityIfNeeded() {
    if (this.state.selectedEntity) {
      return;
    }
    await this.autoSelectEntity({ silent: true });
  }

  async autoSelectEntity({ silent = false } = {}) {
    try {
      const result = await fp2Service.getRecommendedEntity();
      const recommended = result?.recommended_entity_id || null;
      if (recommended) {
        this.state.selectedEntity = recommended;
        fp2Service.setSelectedEntity(recommended);
        this.populateEntitySelector();
        if (!silent) {
          console.info('[FP2] Auto-selected entity:', recommended);
        }
        await this.restartStreamAndRefresh();
      }
    } catch (error) {
      if (!silent) {
        console.warn('[FP2] Auto-select failed:', error);
      }
    }
  }

  async restartStreamAndRefresh() {
    fp2Service.stopStream();
    this.updateStreamState('disconnected');
    await this.refreshAll();
    await this.startStreaming();
  }

  async startStreaming() {
    // WebSocket не поддерживается на Render free tier — используем REST polling
    this.updateStreamState('polling');
  }

  startPolling() {
    this.stopPolling();
    this.pollTimer = setInterval(async () => {
      await this.loadStatus();
      if (this.state.streamState !== 'connected') {
        await this.loadCurrent();
      }
    }, 4000);
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
      if (this.elements.presenceDuration) {
        this.elements.presenceDuration.textContent = this.getPresenceDuration();
      }
    }, 1000);
  }

  stopDurationTicker() {
    if (this.durationTimer) {
      clearInterval(this.durationTimer);
      this.durationTimer = null;
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
    this.elements.streamStatus.textContent = state;
    const cls = state === 'connected' ? 'ok'
              : state === 'error'    ? 'err'
              : 'warn';
    this.elements.streamStatus.className = `chip ${cls}`;

    if (this.elements.streamBtn) {
      this.elements.streamBtn.textContent = state === 'connected' ? 'Stop Stream' : 'Start Stream';
    }
  }

  renderCurrent(data) {
    const presence = Boolean(data?.metadata?.presence);
    this.elements.presenceValue.textContent = presence ? 'PRESENT' : 'ABSENT';
    this.elements.presenceValue.className = `presence-pill ${presence ? 'present' : 'absent'}`;
    
    // Update real-time graph
    this.updateGraphData(presence);

    const persons = Array.isArray(data?.persons) ? data.persons : [];
    const personsCount = persons.length;
    const zonesCount = data?.zone_summary ? Object.keys(data.zone_summary).length : 0;
    const currentZone = this.detectCurrentZone(data);

    this.elements.personsCount.textContent = String(personsCount);
    this.elements.zonesCount.textContent = String(zonesCount);
    this.elements.currentZone.textContent = currentZone || '-';

    this.elements.updatedAt.textContent = new Date().toLocaleTimeString();
    this.elements.rawOutput.textContent = JSON.stringify(data, null, 2);

    const ts = new Date().toLocaleTimeString();
    this.trackMovement({
      timestamp: ts,
      presence,
      zone: currentZone
    });

    if (presence && !this.state.presenceStartedAt) {
      this.state.presenceStartedAt = Date.now();
    }
    if (!presence) {
      this.state.presenceStartedAt = null;
    }
    this.elements.presenceDuration.textContent = this.getPresenceDuration();

    this.state.lastUpdate = ts;

    // Записываем в историю только при смене состояния
    if (this.state.lastPresence !== presence) {
      this.pushHistory({ timestamp: ts, presence });
    }

    this.updateTrajectory(data);
    this.drawMovementMap(data);
  }

  detectCurrentZone(data) {
    const personZone = Array.isArray(data?.persons) && data.persons.length > 0
      ? data.persons[0]?.zone_id
      : null;
    if (personZone) {
      return personZone;
    }

    const zoneSummary = data?.zone_summary;
    if (zoneSummary && typeof zoneSummary === 'object') {
      const zones = Object.entries(zoneSummary);
      if (zones.length > 0) {
        zones.sort((a, b) => (Number(b[1]) || 0) - (Number(a[1]) || 0));
        return zones[0][0];
      }
    }

    const attrs = data?.metadata?.raw_attributes || {};
    return attrs.current_zone || attrs.zone || null;
  }

  trackMovement(event) {
    const prevPresence = this.state.lastPresence;
    const prevZone = this.state.currentZone;

    if (prevPresence === null) {
      this.state.lastPresence = event.presence;
      this.state.currentZone = event.zone;
      if (event.presence) {
        this.pushMovementEvent(event.timestamp, 'enter', `Detected in ${event.zone || 'unknown zone'}`);
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
    // Не пишем PRESENCE при каждом poll — только реальные события

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
      const li = document.createElement('li');
      li.className = 'fp2-history-item';
      li.innerHTML = `
        <span>${entry.timestamp}</span>
        <span>${entry.text}</span>
        <strong class="fp2-event fp2-event-${entry.type}">${entry.type.toUpperCase()}</strong>
      `;
      this.elements.movementList.appendChild(li);
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
      const li = document.createElement('li');
      li.className = 'fp2-history-item';
      li.innerHTML = `
        <span>${entry.timestamp}</span>
        <strong class="${entry.presence ? 'ok' : 'muted'}">${entry.presence ? 'PRESENT' : 'ABSENT'}</strong>
      `;
      this.elements.historyList.appendChild(li);
    });
  }

  updateTrajectory(data) {
    const people = Array.isArray(data?.persons) ? data.persons : [];
    if (people.length === 0) {
      return;
    }

    const zoneKeys = Object.keys(data?.zone_summary || {});
    const zoneIndex = {};
    zoneKeys.forEach((zone, i) => {
      zoneIndex[zone] = i;
    });

    people.forEach((person, idx) => {
      const bb = person?.bounding_box || {};
      let x = Number.isFinite(bb.x) ? bb.x : null;
      let y = Number.isFinite(bb.y) ? bb.y : null;

      if (x === null || y === null) {
        const zid = person.zone_id || this.state.currentZone;
        const zi = zid && zoneIndex[zid] !== undefined ? zoneIndex[zid] : idx;
        x = 0.15 + (zi % 6) * 0.14;
        y = 0.5;
      }

      this.state.trajectories.push({
        x: Math.max(0, Math.min(1, x)),
        y: Math.max(0, Math.min(1, y)),
        personId: person.person_id || `p${idx + 1}`,
        ts: Date.now()
      });
    });

    // Keep recent points only.
    this.state.trajectories = this.state.trajectories.filter((p) => (Date.now() - p.ts) < 30000);
  }

  drawMovementMap(data) {
    const canvas = this.elements.movementCanvas;
    const ctx = this.canvasCtx;
    if (!canvas || !ctx) {
      return;
    }

    const w = canvas.width;
    const h = canvas.height;
    ctx.clearRect(0, 0, w, h);

    // Grid
    ctx.strokeStyle = 'rgba(90,110,130,0.24)';
    ctx.lineWidth = 1;
    for (let i = 1; i < 8; i += 1) {
      const x = (w / 8) * i;
      ctx.beginPath();
      ctx.moveTo(x, 0);
      ctx.lineTo(x, h);
      ctx.stroke();
    }
    for (let j = 1; j < 4; j += 1) {
      const y = (h / 4) * j;
      ctx.beginPath();
      ctx.moveTo(0, y);
      ctx.lineTo(w, y);
      ctx.stroke();
    }

    // Zone labels
    const zones = Object.keys(data?.zone_summary || {});
    ctx.font = '12px monospace';
    ctx.fillStyle = 'rgba(170,200,220,0.85)';
    zones.forEach((zone, i) => {
      const x = 12 + i * 130;
      ctx.fillText(zone, x, 18);
    });

    // Draw trajectories
    this.state.trajectories.forEach((point) => {
      const age = Date.now() - point.ts;
      const alpha = Math.max(0.15, 1 - age / 30000);
      const px = Math.floor(point.x * (w - 20)) + 10;
      const py = Math.floor(point.y * (h - 20)) + 10;

      ctx.fillStyle = `rgba(40, 220, 180, ${alpha.toFixed(2)})`;
      ctx.beginPath();
      ctx.arc(px, py, 4, 0, Math.PI * 2);
      ctx.fill();
    });

    // Current presence marker
    if (this.state.lastPresence) {
      ctx.fillStyle = 'rgba(90, 255, 140, 0.9)';
      ctx.fillText('PRESENT', w - 90, 20);
    } else {
      ctx.fillStyle = 'rgba(255, 110, 110, 0.9)';
      ctx.fillText('ABSENT', w - 80, 20);
    }
  }

  // Real-time graph initialization
  initRealtimeGraph() {
    const canvas = this.container.querySelector('#fp2RealtimeGraph');
    if (!canvas) return;
    
    this.graphCanvas = canvas;
    this.graphCtx = canvas.getContext('2d');
    this.graphData = []; // Array of {timestamp, presence}
    this.maxGraphPoints = 120; // 60 seconds at 0.5s interval
    
    this.startGraphAnimation();
  }
  
  startGraphAnimation() {
    if (this.graphAnimationId) return;
    
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
    
    // Keep only recent data
    if (this.graphData.length > this.maxGraphPoints) {
      this.graphData.shift();
    }
  }
  
  drawRealtimeGraph() {
    const canvas = this.graphCanvas;
    const ctx = this.graphCtx;
    if (!canvas || !ctx) return;
    
    const w = canvas.width;
    const h = canvas.height;
    
    // Clear canvas
    ctx.fillStyle = '#1a1a2e';
    ctx.fillRect(0, 0, w, h);
    
    // Draw grid
    ctx.strokeStyle = 'rgba(255,255,255,0.1)';
    ctx.lineWidth = 1;
    for (let i = 0; i < 5; i++) {
      const y = (h / 4) * i;
      ctx.beginPath();
      ctx.moveTo(0, y);
      ctx.lineTo(w, y);
      ctx.stroke();
    }
    
    // Draw time labels
    ctx.fillStyle = 'rgba(255,255,255,0.5)';
    ctx.font = '10px sans-serif';
    ctx.fillText('Present', 8, 15);
    ctx.fillText('Absent', 8, h - 5);
    
    if (this.graphData.length < 2) return;
    
    // Draw presence line
    ctx.strokeStyle = '#4ade80';
    ctx.lineWidth = 2;
    ctx.beginPath();
    
    const xStep = w / this.maxGraphPoints;
    
    this.graphData.forEach((point, i) => {
      const x = i * xStep;
      const y = point.presence ? 30 : h - 20;
      
      if (i === 0) {
        ctx.moveTo(x, y);
      } else {
        ctx.lineTo(x, y);
      }
    });
    
    ctx.stroke();
    
    // Fill area under line
    ctx.fillStyle = 'rgba(74, 222, 128, 0.2)';
    ctx.beginPath();
    ctx.moveTo(0, h);
    this.graphData.forEach((point, i) => {
      const x = i * xStep;
      const y = point.presence ? 30 : h - 20;
      ctx.lineTo(x, y);
    });
    ctx.lineTo((this.graphData.length - 1) * xStep, h);
    ctx.closePath();
    ctx.fill();
    
    // Draw current indicator
    if (this.graphData.length > 0) {
      const last = this.graphData[this.graphData.length - 1];
      const x = (this.graphData.length - 1) * xStep;
      const y = last.presence ? 30 : h - 20;
      
      ctx.fillStyle = last.presence ? '#4ade80' : '#6b7280';
      ctx.beginPath();
      ctx.arc(x, y, 4, 0, Math.PI * 2);
      ctx.fill();
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
