// FP2 Room Editor Mixin — extracted from FP2Tab.js
// Handles: room profiles, boundary capture, structural areas, layout items,
// calibration, scenario presets, room config sync/export/import,
// canvas hit-detection and pointer events for the editor.

import { t, tp } from '../services/i18n.js?v=20260313-v46';

const LOCAL_HISTORY_KEY = 'fp2_local_history_v1';
const LOCAL_ENTRY_KEY = 'fp2_local_presence_entries_v1';
const LOCAL_SCENARIO_KEY = 'fp2_ui_scenario_v1';
import { fp2Service } from '../services/fp2.service.js?v=20260330-fp2unavail1';
import {
  BUILTIN_ROOM_ITEM_LIBRARY,
  DEFAULT_ROOM_PROFILE_ID,
  buildRoomProfiles,
  buildRoomTemplates,
  getProfileAnimalFilterEnabled,
  getProfileGeometry,
  getRoomItemDefinition,
  getRoomProfileById,
  getRoomTemplateById,
  normalizeCalibrationOverride,
  persistActiveRoomProfileId,
  persistRoomProfileCalibration,
  persistRoomProfileBoundaries,
  persistRoomProfileFilters,
  persistRoomProfileLayouts,
  persistRoomProfileStructuralAreas,
  persistRoomProfileWalkableAreas,
  persistRoomProfiles,
  persistRoomTemplates,
  readStoredActiveRoomProfileId,
  readStoredRoomProfileCalibration,
  readStoredRoomProfileBoundaries,
  readStoredRoomProfileFilters,
  readStoredRoomProfileLayouts,
  readStoredRoomProfileStructuralAreas,
  readStoredRoomProfileWalkableAreas,
  readStoredRoomProfiles,
  readStoredRoomTemplates
} from '../services/fp2.profiles.js?v=20260313-v16';
import { hasTargetCoordinates } from '../services/fp2.target-filter.js?v=20260308-v2';

export const FP2RoomEditorMixin = {
  loadRoomProfiles() {
    const customProfiles = readStoredRoomProfiles();
    const roomProfiles = buildRoomProfiles(customProfiles);
    const customRoomTemplates = readStoredRoomTemplates();
    const roomTemplates = buildRoomTemplates(customRoomTemplates);
    const roomProfileFilters = readStoredRoomProfileFilters();
    const roomProfileCalibration = readStoredRoomProfileCalibration();
    const roomProfileBoundaries = readStoredRoomProfileBoundaries();
    const roomProfileLayouts = readStoredRoomProfileLayouts();
    const roomProfileStructuralAreas = readStoredRoomProfileStructuralAreas();
    const roomProfileWalkableAreas = readStoredRoomProfileWalkableAreas();
    const storedActiveId = readStoredActiveRoomProfileId();
    const activeRoomProfileId = roomProfiles.some(profile => profile.id === storedActiveId)
      ? storedActiveId
      : DEFAULT_ROOM_PROFILE_ID;

    this.state.customRoomProfiles = customProfiles;
    this.state.customRoomTemplates = customRoomTemplates;
    this.state.roomProfiles = roomProfiles;
    this.state.roomTemplates = roomTemplates;
    this.state.roomProfileFilters = roomProfileFilters;
    this.state.roomProfileCalibration = roomProfileCalibration;
    this.state.roomProfileBoundaries = roomProfileBoundaries;
    this.state.roomProfileLayouts = roomProfileLayouts;
    this.state.roomProfileStructuralAreas = roomProfileStructuralAreas;
    this.state.roomProfileWalkableAreas = roomProfileWalkableAreas;
    this.state.activeRoomProfileId = activeRoomProfileId;
    if (!roomTemplates.some((template) => template.id === this.state.selectedRoomTemplateId)) {
      this.state.selectedRoomTemplateId = roomTemplates[0]?.id || 'empty_room';
    }
    persistActiveRoomProfileId(activeRoomProfileId);
    this.renderRoomProfileControls();
  },

  loadLocalHistory() {
    if (typeof window === 'undefined' || !window.localStorage) return;
    try {
      const samples = JSON.parse(window.localStorage.getItem(LOCAL_HISTORY_KEY) || '[]');
      const entries = JSON.parse(window.localStorage.getItem(LOCAL_ENTRY_KEY) || '[]');
      this.state.localTelemetryHistory = Array.isArray(samples) ? samples : [];
      this.state.localPresenceEntries = Array.isArray(entries) ? entries : [];
    } catch {
      this.state.localTelemetryHistory = [];
      this.state.localPresenceEntries = [];
    }
  },

  loadScenarioPreference() {
    if (typeof window === 'undefined' || !window.localStorage) {
      this.state.selectedScenarioId = 'room_presence';
      return;
    }

    const stored = window.localStorage.getItem(LOCAL_SCENARIO_KEY);
    this.state.selectedScenarioId = stored || 'room_presence';
  },

  persistScenarioPreference() {
    if (typeof window === 'undefined' || !window.localStorage) return;
    window.localStorage.setItem(LOCAL_SCENARIO_KEY, this.state.selectedScenarioId || 'room_presence');
  },

  persistLocalHistory() {
    if (typeof window === 'undefined' || !window.localStorage) return;
    window.localStorage.setItem(LOCAL_HISTORY_KEY, JSON.stringify(this.state.localTelemetryHistory || []));
    window.localStorage.setItem(LOCAL_ENTRY_KEY, JSON.stringify(this.state.localPresenceEntries || []));
  },

  hasMeaningfulRoomConfig(payload) {
    if (!payload || typeof payload !== 'object') return false;

    const nonEmptyObject = (value) => Boolean(value && typeof value === 'object' && Object.keys(value).length);

    return (
      Array.isArray(payload.customRoomProfiles) && payload.customRoomProfiles.length > 0
    ) || (
      Array.isArray(payload.customRoomTemplates) && payload.customRoomTemplates.length > 0
    ) || nonEmptyObject(payload.roomProfileFilters)
      || nonEmptyObject(payload.roomProfileCalibration)
      || nonEmptyObject(payload.roomProfileBoundaries)
      || nonEmptyObject(payload.roomProfileLayouts)
      || nonEmptyObject(payload.roomProfileStructuralAreas)
      || nonEmptyObject(payload.roomProfileWalkableAreas)
      || payload.activeRoomProfileId !== DEFAULT_ROOM_PROFILE_ID
      || payload.selectedRoomTemplateId !== 'empty_room';
  },

  normalizeRoomConfigStorageBackend(value) {
    if (typeof value !== 'string') return 'unknown';
    const normalized = value.trim().toLowerCase();
    if (['postgresql', 'sqlite_fallback', 'file_fallback', 'r2', 'unavailable'].includes(normalized)) {
      return normalized;
    }
    return 'unknown';
  },

  setRoomConfigStorageBackend(value) {
    this.state.roomConfigStorageBackend = this.normalizeRoomConfigStorageBackend(value);
  },

  getRoomConfigStorageBadgeState() {
    if (this.state.roomConfigHydrating) {
      return {
        text: t('fp2.layout.storage.syncing'),
        className: 'chip chip--warn'
      };
    }

    switch (this.state.roomConfigStorageBackend) {
      case 'r2':
        return {
          text: t('fp2.layout.storage.r2'),
          className: 'chip chip--ok'
        };
      case 'postgresql':
        return {
          text: t('fp2.layout.storage.cloud_db'),
          className: 'chip chip--ok'
        };
      case 'sqlite_fallback':
        return {
          text: t('fp2.layout.storage.sqlite_fallback'),
          className: 'chip chip--info'
        };
      case 'file_fallback':
        return {
          text: t('fp2.layout.storage.file_fallback'),
          className: 'chip chip--warn'
        };
      case 'unavailable':
        return {
          text: t('fp2.layout.storage.unavailable'),
          className: 'chip chip--err'
        };
      default:
        return {
          text: t('fp2.layout.storage.unknown'),
          className: 'chip chip--neutral'
        };
    }
  },

  applyRoomConfigPayload(payload, { persistLocal = true } = {}) {
    if (!payload || typeof payload !== 'object') {
      return;
    }

    if (persistLocal) {
      persistRoomProfiles(Array.isArray(payload.customRoomProfiles) ? payload.customRoomProfiles : []);
      persistRoomTemplates(Array.isArray(payload.customRoomTemplates) ? payload.customRoomTemplates : []);
      persistRoomProfileFilters(
        payload.roomProfileFilters && typeof payload.roomProfileFilters === 'object'
          ? payload.roomProfileFilters
          : {}
      );
      persistRoomProfileCalibration(
        payload.roomProfileCalibration && typeof payload.roomProfileCalibration === 'object'
          ? payload.roomProfileCalibration
          : {}
      );
      persistRoomProfileBoundaries(
        payload.roomProfileBoundaries && typeof payload.roomProfileBoundaries === 'object'
          ? payload.roomProfileBoundaries
          : {}
      );
      persistRoomProfileLayouts(
        payload.roomProfileLayouts && typeof payload.roomProfileLayouts === 'object'
          ? payload.roomProfileLayouts
          : {}
      );
      persistRoomProfileStructuralAreas(
        payload.roomProfileStructuralAreas && typeof payload.roomProfileStructuralAreas === 'object'
          ? payload.roomProfileStructuralAreas
          : {}
      );
      persistRoomProfileWalkableAreas(
        payload.roomProfileWalkableAreas && typeof payload.roomProfileWalkableAreas === 'object'
          ? payload.roomProfileWalkableAreas
          : {}
      );
      persistActiveRoomProfileId(
        typeof payload.activeRoomProfileId === 'string' ? payload.activeRoomProfileId : DEFAULT_ROOM_PROFILE_ID
      );
    }

    this.loadRoomProfiles();
    if (
      typeof payload.selectedRoomTemplateId === 'string'
      && this.state.roomTemplates.some((template) => template.id === payload.selectedRoomTemplateId)
    ) {
      this.state.selectedRoomTemplateId = payload.selectedRoomTemplateId;
    }
    this.renderRoomProfileControls();
    if (this.lastCurrentData) {
      this.renderCurrent(this.lastCurrentData);
    }
  },

  async syncRoomConfigWithBackend() {
    this.state.roomConfigHydrating = true;
    try {
      const remoteState = await fp2Service.getLayoutState();
      this.setRoomConfigStorageBackend(remoteState?.storage_backend || 'unknown');
      if (remoteState?.found && remoteState.payload && typeof remoteState.payload === 'object') {
        this.applyRoomConfigPayload(remoteState.payload, { persistLocal: true });
      } else {
        const localPayload = this.buildRoomConfigExportPayload();
        if (this.hasMeaningfulRoomConfig(localPayload)) {
          const savedState = await fp2Service.saveLayoutState(localPayload);
          this.setRoomConfigStorageBackend(savedState?.storage_backend || remoteState?.storage_backend || 'unknown');
        }
      }
    } catch (error) {
      console.warn('Failed to sync FP2 room config with backend:', error);
      this.setRoomConfigStorageBackend('unavailable');
    } finally {
      this.state.roomConfigHydrating = false;
      this.state.roomConfigBackendReady = true;
      this.renderRoomProfileControls();
    }
  },

  scheduleRoomConfigSave({ immediate = false } = {}) {
    if (!this.state.roomConfigBackendReady || this.state.roomConfigHydrating) return;

    if (this.roomConfigSaveTimer) {
      clearTimeout(this.roomConfigSaveTimer);
      this.roomConfigSaveTimer = null;
    }

    if (immediate) {
      void this.flushRoomConfigSave();
      return;
    }

    this.roomConfigSaveTimer = window.setTimeout(() => {
      this.roomConfigSaveTimer = null;
      void this.flushRoomConfigSave();
    }, 600);
  },

  async flushRoomConfigSave() {
    if (!this.state.roomConfigBackendReady || this.state.roomConfigHydrating) return;
    try {
      const savedState = await fp2Service.saveLayoutState(this.buildRoomConfigExportPayload());
      this.setRoomConfigStorageBackend(savedState?.storage_backend || 'unknown');
      this.renderRoomProfileControls();
    } catch (error) {
      console.warn('Failed to persist FP2 room config to backend:', error);
      this.setRoomConfigStorageBackend('unavailable');
      this.renderRoomProfileControls();
    }
  },

  buildRoomConfigExportPayload() {
    return {
      version: 1,
      exportedAt: new Date().toISOString(),
      customRoomProfiles: this.state.customRoomProfiles || [],
      customRoomTemplates: this.state.customRoomTemplates || [],
      roomProfileFilters: this.state.roomProfileFilters || {},
      roomProfileCalibration: this.state.roomProfileCalibration || {},
      roomProfileBoundaries: this.state.roomProfileBoundaries || {},
      roomProfileLayouts: this.state.roomProfileLayouts || {},
      roomProfileStructuralAreas: this.state.roomProfileStructuralAreas || {},
      roomProfileWalkableAreas: this.state.roomProfileWalkableAreas || {},
      activeRoomProfileId: this.state.activeRoomProfileId || DEFAULT_ROOM_PROFILE_ID,
      selectedRoomTemplateId: this.state.selectedRoomTemplateId || 'empty_room'
    };
  },

  exportRoomConfig() {
    try {
      const payload = this.buildRoomConfigExportPayload();
      const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' });
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = `fp2-room-config-${Date.now()}.json`;
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
    } catch (error) {
      console.error('Failed to export FP2 room config:', error);
      window.alert(t('fp2.layout.export_failed'));
    }
  },

  async importRoomConfig(file) {
    try {
      const text = await file.text();
      const payload = JSON.parse(text);
      if (!payload || typeof payload !== 'object') {
        throw new Error('Invalid payload');
      }
      this.applyRoomConfigPayload(payload, { persistLocal: true });
      this.scheduleRoomConfigSave({ immediate: true });
    } catch (error) {
      console.error('Failed to import FP2 room config:', error);
      window.alert(t('fp2.layout.import_failed'));
    }
  },

  setSelectedScenario(scenarioId, { persist = true } = {}) {
    const nextId = scenarioId || 'room_presence';
    if (this.state.selectedScenarioId === nextId && persist) {
      this.renderScenarioPresets(this.lastCurrentData?.metadata?.raw_attributes?.resource_values || {});
      return;
    }

    this.state.selectedScenarioId = nextId;
    if (persist) {
      this.persistScenarioPreference();
    }
    this.renderScenarioPresets(this.lastCurrentData?.metadata?.raw_attributes?.resource_values || {});
  },

  getScenarioPresets(resourceValues = {}) {
    const bedsidePosition = [1, 2, 3].includes(Number(resourceValues?.['14.58.85']))
      ? Number(resourceValues['14.58.85'])
      : 3;

    return [
      {
        id: 'room_presence',
        titleKey: 'fp2.scenario.room_presence.title',
        descriptionKey: 'fp2.scenario.room_presence.description',
        outcomeKey: 'fp2.scenario.room_presence.outcome',
        limitationsKey: 'fp2.scenario.room_presence.limitations',
        channels: ['4.22.700', '3.51.85', '13.27.85', '0.60.85', '0.61.85', '0.63.85'],
        writes: [
          { resourceId: '4.22.85', value: 1 },
          { resourceId: '4.71.85', value: 1 },
          { resourceId: '4.75.85', value: 1 },
          { resourceId: '14.55.85', value: 0 },
          { resourceId: '14.58.85', value: 0 }
        ]
      },
      {
        id: 'corridor_flow',
        titleKey: 'fp2.scenario.corridor_flow.title',
        descriptionKey: 'fp2.scenario.corridor_flow.description',
        outcomeKey: 'fp2.scenario.corridor_flow.outcome',
        limitationsKey: 'fp2.scenario.corridor_flow.limitations',
        channels: ['13.27.85', '13.120.85', '4.22.700', '0.60.85', '0.61.85'],
        writes: [
          { resourceId: '4.22.85', value: 1 },
          { resourceId: '4.71.85', value: 1 },
          { resourceId: '14.55.85', value: 1 },
          { resourceId: '14.58.85', value: 0 }
        ]
      },
      {
        id: 'fall_safety',
        titleKey: 'fp2.scenario.fall_safety.title',
        descriptionKey: 'fp2.scenario.fall_safety.description',
        outcomeKey: 'fp2.scenario.fall_safety.outcome',
        limitationsKey: 'fp2.scenario.fall_safety.limitations',
        channels: ['4.31.85', '13.27.85', '4.22.700', '3.51.85'],
        writes: [
          { resourceId: '4.22.85', value: 1 },
          { resourceId: '14.55.85', value: 0 },
          { resourceId: '14.30.85', value: 1 },
          { resourceId: '14.59.85', value: 0 },
          { resourceId: '14.58.85', value: 0 }
        ]
      },
      {
        id: 'bedside_sleep',
        titleKey: 'fp2.scenario.bedside_sleep.title',
        descriptionKey: 'fp2.scenario.bedside_sleep.description',
        outcomeKey: 'fp2.scenario.bedside_sleep.outcome',
        limitationsKey: 'fp2.scenario.bedside_sleep.limitations',
        channels: ['0.9.85', '0.12.85', '0.13.85', '0.14.85', '13.11.85', '14.58.85'],
        writes: [
          { resourceId: '4.22.85', value: 1 },
          { resourceId: '14.55.85', value: 0 },
          { resourceId: '14.58.85', value: bedsidePosition }
        ]
      }
    ];
  },

  inferScenarioId(resourceValues = {}) {
    if ([1, 2, 3].includes(Number(resourceValues?.['14.58.85']))) {
      return 'bedside_sleep';
    }
    if (Number(resourceValues?.['14.55.85']) === 1) {
      return 'corridor_flow';
    }
    return 'room_presence';
  },

  getSelectedScenarioPreset(resourceValues = {}) {
    const presets = this.getScenarioPresets(resourceValues);
    const currentId = this.state.selectedScenarioId || this.inferScenarioId(resourceValues);
    return presets.find((preset) => preset.id === currentId) || presets[0] || null;
  },

  resolveActiveScenarioId(resourceValues = {}) {
    return this.inferScenarioId(resourceValues);
  },

  doesScenarioMatch(preset, resourceValues = {}) {
    if (!preset) return false;
    return (preset.writes || []).every((write) => String(resourceValues?.[write.resourceId] ?? '') === String(write.value));
  },

  getScenarioStateText(preset, matchesCurrent) {
    if (this.state.scenarioBusyId === preset?.id) {
      return t('fp2.scenario.state.applying');
    }
    if (matchesCurrent) {
      return t('fp2.scenario.state.matching');
    }
    if (this.state.selectedScenarioId === preset?.id) {
      return t('fp2.scenario.state.selected');
    }
    return t('fp2.scenario.state.preview');
  },

  formatScenarioResourceLabel(resourceId) {
    const key = RESOURCE_LABELS[resourceId];
    return key ? t(key) : resourceId;
  },

  formatScenarioWriteValue(resourceId, value) {
    if (['4.22.85', '4.71.85', '4.75.85', '4.23.85', '8.0.2032', '0.9.85', '0.12.85'].includes(resourceId)) {
      return String(value) === '1' ? t('common.enabled') : t('common.disabled');
    }
    return this.formatSettingValue(resourceId, value);
  },

  renderScenarioPresets(resourceValues = {}) {
    if (!this.elements.scenarioTabs || !this.elements.scenarioDetail || !this.elements.scenarioStatus) {
      return;
    }

    if (this.isCsiViewMode()) {
      this.elements.scenarioStatus.textContent = t('common.unavailable');
      this.elements.scenarioStatus.className = 'chip chip--neutral';
      this.elements.scenarioTabs.innerHTML = '';
      this.elements.scenarioDetail.innerHTML = `<div class="fp2-empty-state">${t('fp2.scenario.csi_unavailable')}</div>`;
      return;
    }

    const inferredId = this.inferScenarioId(resourceValues);
    if (!this.state.selectedScenarioId) {
      this.state.selectedScenarioId = inferredId;
    }

    const presets = this.getScenarioPresets(resourceValues);
    if (!presets.some((preset) => preset.id === this.state.selectedScenarioId)) {
      this.state.selectedScenarioId = inferredId;
    }

    const selected = presets.find((preset) => preset.id === this.state.selectedScenarioId) || presets[0] || null;
    const activeScenarioId = this.resolveActiveScenarioId(resourceValues);
    const selectedIsActive = selected?.id === activeScenarioId;
    const activePreset = presets.find((preset) => preset.id === activeScenarioId) || presets[0] || null;

    this.elements.scenarioTabs.innerHTML = presets.map((preset) => {
      const matchesCurrent = preset.id === activeScenarioId;
      const isSelected = preset.id === selected?.id;
      const classes = [
        'fp2-scenario-tab',
        isSelected ? 'is-selected' : '',
        matchesCurrent ? 'is-matching' : ''
      ].filter(Boolean).join(' ');

      return `
        <button
          type="button"
          class="${classes}"
          data-scenario-select="${preset.id}"
          aria-pressed="${isSelected ? 'true' : 'false'}"
        >
          <span class="fp2-scenario-tab-title">${t(preset.titleKey)}</span>
          <span class="fp2-scenario-tab-state">${this.getScenarioStateText(preset, matchesCurrent)}</span>
        </button>
      `;
    }).join('');

    const outcome = selected ? t(selected.outcomeKey) : '-';
    const limitations = selected ? t(selected.limitationsKey) : '-';
    const writes = selected?.writes || [];
    const channels = selected?.channels || [];

    this.elements.scenarioStatus.textContent = selectedIsActive
      ? t('fp2.scenario.badge.active')
      : t('fp2.scenario.badge.preview');
    this.elements.scenarioStatus.className = selectedIsActive ? 'chip ok' : 'chip chip--neutral';

    this.elements.scenarioDetail.innerHTML = selected ? `
      <div class="fp2-scenario-detail-head">
        <div>
          <h4>${t(selected.titleKey)}</h4>
          <p class="fp2-scenario-description">${t(selected.descriptionKey)}</p>
          ${selectedIsActive
            ? `<p class="fp2-scenario-current">${t('fp2.scenario.current_active', { name: t(selected.titleKey) })}</p>`
            : `<p class="fp2-scenario-current">${t('fp2.scenario.preview_note', { name: t(activePreset?.titleKey || 'fp2.scenario.room_presence.title') })}</p>`
          }
        </div>
        <button
          type="button"
          class="btn btn--secondary btn--sm"
          data-scenario-apply="${selected.id}"
          ${selectedIsActive || this.state.scenarioBusyId ? 'disabled' : ''}
        >
          ${this.state.scenarioBusyId === selected.id
            ? t('fp2.scenario.applying')
            : selectedIsActive
              ? t('fp2.scenario.active')
              : t('fp2.scenario.apply_to_device')}
        </button>
      </div>
      <div class="fp2-scenario-sections">
        <section class="fp2-scenario-section">
          <span class="fp2-scenario-section-label">${t('fp2.scenario.outcome')}</span>
          <p>${outcome}</p>
        </section>
        <section class="fp2-scenario-section">
          <span class="fp2-scenario-section-label">${t('fp2.scenario.uses')}</span>
          <ul class="fp2-scenario-list">
            ${channels.map((resourceId) => `
              <li><code>${resourceId}</code><span>${this.formatScenarioResourceLabel(resourceId)}</span></li>
            `).join('')}
          </ul>
        </section>
        <section class="fp2-scenario-section">
          <span class="fp2-scenario-section-label">${t('fp2.scenario.applies')}</span>
          <ul class="fp2-scenario-list">
            ${writes.map((write) => `
              <li>
                <code>${write.resourceId}</code>
                <span>${this.formatScenarioResourceLabel(write.resourceId)} → ${this.formatScenarioWriteValue(write.resourceId, write.value)}</span>
              </li>
            `).join('')}
          </ul>
        </section>
        <section class="fp2-scenario-section">
          <span class="fp2-scenario-section-label">${t('fp2.scenario.limitations')}</span>
          <p>${limitations}</p>
        </section>
      </div>
    ` : '';
  },

  async applyScenarioPreset(scenarioId) {
    if (!scenarioId || this.state.scenarioBusyId) return;
    const resourceValues = this.lastCurrentData?.metadata?.raw_attributes?.resource_values || {};
    const preset = this.getScenarioPresets(resourceValues).find((item) => item.id === scenarioId);
    if (!preset || !preset.writes?.length) return;

    this.state.scenarioBusyId = scenarioId;
    this.renderScenarioPresets(resourceValues);
    try {
      const writeResult = await fp2Service.writeCloudResources(preset.writes, true, { sourcePreference: 'fp2' });
      this.setSelectedScenario(scenarioId);
      if (writeResult?.current) {
        this.renderCurrent(writeResult.current);
      } else {
        await this.loadCurrent();
      }
      await this.loadStatus();
    } catch (error) {
      console.error('Failed to apply FP2 scenario preset:', error);
      window.alert(t('fp2.scenario.apply_failed', { name: t(preset.titleKey) }));
    } finally {
      this.state.scenarioBusyId = null;
      this.renderScenarioPresets(this.lastCurrentData?.metadata?.raw_attributes?.resource_values || resourceValues);
    }
  },

  setAqaraHomeRange(range) {
    this.state.aqaraHomeRange = range === 'week' ? 'week' : 'day';
    this.renderAqaraHomeOverview();
    this.renderZoneRangeSummary();
  },

  clearLocalHistory() {
    const confirmed = window.confirm(t('fp2.home.clear_history_confirm'));
    if (!confirmed) return;
    this.state.localTelemetryHistory = [];
    this.state.localPresenceEntries = [];
    this.persistLocalHistory();

    if (this.lastCurrentData) {
      this.renderCurrent(this.lastCurrentData);
      return;
    }

    this.renderAqaraHomeOverview();
    this.renderZoneRangeSummary();
  },

  buildZoneStateSignature(zoneIds = []) {
    return [...zoneIds].map((zoneId) => String(zoneId)).sort((left, right) => left.localeCompare(right)).join('|');
  },

  buildZoneMetricSignature(metricMap = {}) {
    return Object.entries(metricMap || {})
      .map(([zoneId, value]) => [String(zoneId), Number(value || 0)])
      .sort(([left], [right]) => left.localeCompare(right))
      .map(([zoneId, value]) => `${zoneId}:${value}`)
      .join('|');
  },

  recordTelemetrySample(sample) {
    if (!sample || !Number.isFinite(sample.ts)) return;
    const history = this.state.localTelemetryHistory || [];
    const last = history[history.length - 1];
    const sampleOccupiedSignature = this.buildZoneStateSignature(sample.occupiedZones || []);
    const lastOccupiedSignature = this.buildZoneStateSignature(last?.occupiedZones || []);
    const sampleTargetSignature = this.buildZoneMetricSignature(sample.zoneTargetCounts || {});
    const lastTargetSignature = this.buildZoneMetricSignature(last?.zoneTargetCounts || {});
    const changed = !last
      || Math.abs((sample.people || 0) - (last.people || 0)) > 0
      || Math.abs((sample.light || 0) - (last.light || 0)) > 0
      || Boolean(sample.presence) !== Boolean(last.presence)
      || (sample.movementEvent ?? null) !== (last.movementEvent ?? null)
      || Math.abs((sample.walkingDistance || 0) - (last.walkingDistance || 0)) > 0
      || (sample.currentZoneId ?? null) !== (last?.currentZoneId ?? null)
      || sampleOccupiedSignature !== lastOccupiedSignature
      || sampleTargetSignature !== lastTargetSignature;
    if (last && (sample.ts - last.ts) < 15000 && !changed) return;

    this.state.localTelemetryHistory = [
      ...history.filter((point) => sample.ts - point.ts <= 7 * 24 * 60 * 60 * 1000),
      sample
    ].slice(-3000);
    this.persistLocalHistory();
  },

  recordPresenceEntry(timestamp) {
    const ts = Number.isFinite(timestamp) ? timestamp : Date.now();
    this.state.localPresenceEntries = [
      ...(this.state.localPresenceEntries || []).filter((point) => ts - point <= 7 * 24 * 60 * 60 * 1000),
      ts
    ].slice(-500);
    this.persistLocalHistory();
  },

  getAqaraRangeWindow() {
    const now = Date.now();
    return this.state.aqaraHomeRange === 'week'
      ? now - 7 * 24 * 60 * 60 * 1000
      : now - 24 * 60 * 60 * 1000;
  },

  getVisitorsTodayCount() {
    const now = new Date();
    const start = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
    return (this.state.localPresenceEntries || []).filter((ts) => ts >= start).length;
  },

  getVisitorsCountForCurrentRange() {
    const startTs = this.getAqaraRangeWindow();
    return (this.state.localPresenceEntries || []).filter((ts) => ts >= startTs).length;
  },

  getWalkingDistanceForCurrentRange() {
    const startTs = this.getAqaraRangeWindow();
    const history = this.state.localTelemetryHistory || [];
    const points = history
      .filter((point) => point.ts >= startTs && Number.isFinite(point.walkingDistance));
    if (!points.length) {
      return this.state.advancedMetrics?.walking_distance_m ?? null;
    }
    const last = points[points.length - 1]?.walkingDistance;
    if (!Number.isFinite(last)) {
      return this.state.advancedMetrics?.walking_distance_m ?? null;
    }
    const baseline = [...history]
      .filter((point) => point.ts < startTs && Number.isFinite(point.walkingDistance))
      .at(-1)?.walkingDistance;
    if (!Number.isFinite(baseline)) {
      return Number(last);
    }
    return Math.max(0, Number(last) - Number(baseline));
  },

  formatDurationCompact(durationMs) {
    const normalized = Number.isFinite(durationMs) ? Math.max(0, durationMs) : 0;
    if (normalized < 60 * 1000) {
      return t('fp2.zone.summary.duration_lt_minute');
    }
    const totalMinutes = Math.floor(normalized / (60 * 1000));
    if (totalMinutes < 60) {
      return t('fp2.zone.summary.duration_minutes', { count: totalMinutes });
    }
    const hours = Math.floor(totalMinutes / 60);
    const minutes = totalMinutes % 60;
    if (minutes === 0) {
      return t('fp2.zone.summary.duration_hours', { count: hours });
    }
    return t('fp2.zone.summary.duration_hours_minutes', { hours, minutes });
  },

  getZoneSummaryForCurrentRange() {
    const startTs = this.getAqaraRangeWindow();
    const now = Date.now();
    const maxObservedIntervalMs = 2 * 60 * 1000;
    const history = (this.state.localTelemetryHistory || [])
      .filter((point) => Number.isFinite(point?.ts))
      .sort((left, right) => left.ts - right.ts);
    if (!history.length) {
      return [];
    }

    const firstInRangeIndex = history.findIndex((point) => point.ts >= startTs);
    if (firstInRangeIndex === -1) {
      return [];
    }

    const points = [
      ...(firstInRangeIndex > 0 ? [history[firstInRangeIndex - 1]] : []),
      ...history.slice(firstInRangeIndex)
    ];
    const zoneMeta = new Map((this.normalizeZones(this.state.zones || [])).map((zone) => [zone.zone_id, zone]));
    const summaryMap = new Map();
    const ensureSummary = (zoneId) => {
      const normalizedZoneId = String(zoneId || 'detection_area');
      if (!summaryMap.has(normalizedZoneId)) {
        const zone = zoneMeta.get(normalizedZoneId);
        summaryMap.set(normalizedZoneId, {
          zone_id: normalizedZoneId,
          displayName: zone?.displayName || this.displayZoneName(normalizedZoneId, this.state.zones || []) || this.formatZoneName(normalizedZoneId, summaryMap.size),
          dwellMs: 0,
          entries: 0,
          peakTargets: 0,
          isCurrent: false,
          isOccupied: false
        });
      }
      return summaryMap.get(normalizedZoneId);
    };

    for (let index = 0; index < points.length; index += 1) {
      const point = points[index];
      const nextTs = index < points.length - 1 ? points[index + 1].ts : now;
      const effectiveStart = Math.max(startTs, point.ts);
      const observedEnd = Math.min(now, nextTs, effectiveStart + maxObservedIntervalMs);
      const durationMs = Math.max(0, observedEnd - effectiveStart);
      const occupiedZones = Array.isArray(point.occupiedZones) ? point.occupiedZones : [];
      const targetCounts = point.zoneTargetCounts || {};

      occupiedZones.forEach((zoneId) => {
        const entry = ensureSummary(zoneId);
        entry.dwellMs += durationMs;
      });

      Object.entries(targetCounts).forEach(([zoneId, value]) => {
        const entry = ensureSummary(zoneId);
        entry.peakTargets = Math.max(entry.peakTargets, Number(value || 0));
      });

      if (index > 0 && point.ts >= startTs) {
        const previousZones = new Set(points[index - 1]?.occupiedZones || []);
        occupiedZones.forEach((zoneId) => {
          if (!previousZones.has(zoneId)) {
            ensureSummary(zoneId).entries += 1;
          }
        });
      }
    }

    const latestPoint = history[history.length - 1];
    const latestIsFresh = latestPoint && (now - latestPoint.ts) <= maxObservedIntervalMs;
    if (latestPoint && latestIsFresh) {
      const activeZones = new Set(latestPoint.occupiedZones || []);
      summaryMap.forEach((entry) => {
        entry.isOccupied = activeZones.has(entry.zone_id);
        entry.isCurrent = latestPoint.currentZoneId === entry.zone_id;
      });
    }

    return Array.from(summaryMap.values())
      .filter((entry) => entry.dwellMs > 0 || entry.entries > 0 || entry.peakTargets > 0 || entry.isOccupied || entry.isCurrent)
      .sort((left, right) => (
        right.dwellMs - left.dwellMs
        || right.entries - left.entries
        || right.peakTargets - left.peakTargets
        || left.displayName.localeCompare(right.displayName)
      ));
  },

  updateAqaraHomeRangeLabels() {
    const isDay = this.state.aqaraHomeRange !== 'week';
    if (this.elements.homeVisitorsLabel) {
      this.elements.homeVisitorsLabel.textContent = t(isDay ? 'fp2.home.visitors_24h' : 'fp2.home.visitors_7d');
    }
    if (this.elements.homeWalkingLabel) {
      this.elements.homeWalkingLabel.textContent = t(isDay ? 'fp2.home.walking_24h' : 'fp2.home.walking_7d');
    }
  },

  renderZoneRangeSummary() {
    const container = this.elements.zoneRangeSummary;
    if (!container) return;

    const isDay = this.state.aqaraHomeRange !== 'week';
    if (this.elements.zoneSummaryRange) {
      this.elements.zoneSummaryRange.textContent = t(isDay ? 'fp2.zone.summary.range_24h' : 'fp2.zone.summary.range_7d');
    }

    const summary = this.getZoneSummaryForCurrentRange();
    if (!summary.length) {
      container.innerHTML = `<div class="fp2-empty-state">${t('fp2.zone.summary.empty')}</div>`;
      return;
    }

    container.innerHTML = summary.map((zone) => `
      <article class="fp2-zone-summary-item ${zone.isOccupied ? 'active' : ''} ${zone.isCurrent ? 'current' : ''}">
        <div class="fp2-zone-summary-head">
          <div>
            <h4>${zone.displayName}</h4>
            <div class="fp2-zone-summary-meta">${zone.zone_id}</div>
          </div>
          <div class="fp2-zone-summary-badges">
            ${zone.isCurrent ? `<span class="chip chip--info">${t('fp2.zone.analytics.current')}</span>` : ''}
            ${zone.isOccupied ? `<span class="chip ok">${t('fp2.zone.occupied')}</span>` : ''}
          </div>
        </div>
        <div class="fp2-zone-summary-grid">
          <div class="fp2-zone-summary-metric">
            <span class="fp2-zone-summary-label">${t('fp2.zone.summary.dwell')}</span>
            <strong>${this.formatDurationCompact(zone.dwellMs)}</strong>
          </div>
          <div class="fp2-zone-summary-metric">
            <span class="fp2-zone-summary-label">${t('fp2.zone.summary.entries')}</span>
            <strong>${zone.entries}</strong>
          </div>
          <div class="fp2-zone-summary-metric">
            <span class="fp2-zone-summary-label">${t('fp2.zone.summary.peak_targets')}</span>
            <strong>${zone.peakTargets}</strong>
          </div>
        </div>
      </article>
    `).join('');
  },

  renderAqaraHomeOverview(latestSample = null) {
    const sample = latestSample || (this.state.localTelemetryHistory || []).at(-1) || null;
    const people = sample?.people ?? (this.state.currentPresenceActive ? Math.max(1, this.state.targets.length || 0) : 0);
    const light = sample?.light;
    const walkingDistance = this.getWalkingDistanceForCurrentRange();
    const visitorsToday = this.getVisitorsCountForCurrentRange();
    this.updateAqaraHomeRangeLabels();

    if (this.elements.homeCurrentPeople) this.elements.homeCurrentPeople.textContent = `${people ?? 0}`;
    if (this.elements.homePresenceDuration) this.elements.homePresenceDuration.textContent = this.getPresenceDuration();
    if (this.elements.homeVisitorsToday) this.elements.homeVisitorsToday.textContent = String(visitorsToday);
    if (this.elements.homeWalkingToday) this.elements.homeWalkingToday.textContent = this.formatMeters(walkingDistance);
    if (this.elements.homeLightNow) this.elements.homeLightNow.textContent = Number.isFinite(light) ? `${Math.round(light)} lux` : '-';

    if (this.elements.homePeopleChartValue) this.elements.homePeopleChartValue.textContent = `${people ?? 0}`;
    if (this.elements.homeLightChartValue) this.elements.homeLightChartValue.textContent = Number.isFinite(light) ? `${Math.round(light)} lux` : '-';

    const isDay = this.state.aqaraHomeRange !== 'week';
    if (this.elements.homeRangeDay) this.elements.homeRangeDay.classList.toggle('btn--primary', isDay);
    if (this.elements.homeRangeWeek) this.elements.homeRangeWeek.classList.toggle('btn--primary', !isDay);
    if (this.elements.homeRangeDay) this.elements.homeRangeDay.classList.toggle('btn--secondary', !isDay);
    if (this.elements.homeRangeWeek) this.elements.homeRangeWeek.classList.toggle('btn--secondary', isDay);

    if (this.state.pageVisible) {
      this.drawAqaraHomeCharts();
    } else {
      this.state.pendingVisualRefresh = true;
    }
  },

  drawAqaraHomeCharts() {
    const startTs = this.getAqaraRangeWindow();
    const endTs = Date.now();
    const points = this.getChartPointsForRange(startTs, endTs);
    this.drawHomeMetricChart(
      this.homePeopleCanvas,
      this.homePeopleCtx,
      points,
      (point) => Number(point.people || 0),
      '#5b7cff',
      '#90a4ff',
      t('fp2.home.people_chart_empty'),
      { startTs, endTs }
    );
    this.drawHomeMetricChart(
      this.homeLightCanvas,
      this.homeLightCtx,
      points,
      (point) => Number(point.light || 0),
      '#f59e0b',
      '#fcd34d',
      t('fp2.home.light_chart_empty'),
      { startTs, endTs }
    );
  },

  getChartPointsForRange(startTs, endTs) {
    const history = (this.state.localTelemetryHistory || [])
      .filter((point) => Number.isFinite(point?.ts))
      .sort((left, right) => left.ts - right.ts);
    if (!history.length) {
      return [];
    }

    const inRange = history.filter((point) => point.ts >= startTs && point.ts <= endTs);
    const previousPoint = [...history].reverse().find((point) => point.ts < startTs) || null;
    if (!inRange.length && !previousPoint) {
      return [];
    }

    const points = [];
    if (previousPoint) {
      points.push({ ...previousPoint, ts: startTs });
    } else if (inRange[0]) {
      points.push({ ...inRange[0], ts: startTs });
    }
    points.push(...inRange);

    const lastPoint = points[points.length - 1];
    if (lastPoint && lastPoint.ts < endTs) {
      points.push({ ...lastPoint, ts: endTs });
    }

    return points.filter((point, index) => (
      index === 0
      || point.ts !== points[index - 1].ts
      || JSON.stringify(point) !== JSON.stringify(points[index - 1])
    ));
  },

  drawHomeMetricChart(canvas, ctx, points, getValue, stroke, fill, emptyLabel, range = {}) {
    if (!canvas || !ctx) return;
    const width = canvas.width;
    const height = canvas.height;
    ctx.clearRect(0, 0, width, height);
    ctx.fillStyle = '#101722';
    ctx.fillRect(0, 0, width, height);

    ctx.strokeStyle = 'rgba(255,255,255,0.06)';
    ctx.lineWidth = 1;
    for (let i = 0; i < 4; i += 1) {
      const y = 16 + ((height - 28) / 3) * i;
      ctx.beginPath();
      ctx.moveTo(0, y);
      ctx.lineTo(width, y);
      ctx.stroke();
    }

    const chartPoints = [...(points || [])]
      .filter((point) => Number.isFinite(point?.ts))
      .sort((left, right) => left.ts - right.ts);

    if (!chartPoints.length) {
      ctx.fillStyle = 'rgba(255,255,255,0.42)';
      ctx.font = '12px Inter, sans-serif';
      ctx.fillText(emptyLabel, 12, height / 2);
      return;
    }

    const minTs = Number.isFinite(range.startTs) ? range.startTs : chartPoints[0].ts;
    const maxTs = Number.isFinite(range.endTs) ? range.endTs : (chartPoints[chartPoints.length - 1].ts || (minTs + 1));
    const span = Math.max(1, maxTs - minTs);
    const values = chartPoints.map((point) => {
      const value = Number(getValue(point));
      return Number.isFinite(value) ? value : 0;
    });
    const maxValue = Math.max(1, ...values);
    const yFor = (value) => height - 14 - (Math.max(0, value) / maxValue) * (height - 34);
    const xFor = (timestamp) => {
      const raw = ((timestamp - minTs) / span) * (width - 24) + 20;
      return Math.max(20, Math.min(width - 4, raw));
    };
    const drawStepPath = () => {
      ctx.beginPath();
      chartPoints.forEach((point, index) => {
        const x = xFor(point.ts);
        const y = yFor(Number(getValue(point) || 0));
        if (index === 0) {
          ctx.moveTo(x, y);
          return;
        }
        const prevPoint = chartPoints[index - 1];
        const prevY = yFor(Number(getValue(prevPoint) || 0));
        ctx.lineTo(x, prevY);
        ctx.lineTo(x, y);
      });
    };

    ctx.fillStyle = 'rgba(255,255,255,0.42)';
    ctx.font = '10px Inter, sans-serif';
    ctx.fillText(`0`, 8, height - 4);
    ctx.fillText(`${maxValue}`, 8, 12);

    ctx.strokeStyle = stroke;
    ctx.lineWidth = 2;
    drawStepPath();
    ctx.stroke();

    ctx.fillStyle = `${fill}22`;
    drawStepPath();
    const firstX = xFor(chartPoints[0].ts);
    const lastX = xFor(chartPoints[chartPoints.length - 1].ts);
    ctx.lineTo(lastX, height - 12);
    ctx.lineTo(firstX, height - 12);
    ctx.closePath();
    ctx.fill();

    const lastPoint = chartPoints[chartPoints.length - 1];
    ctx.fillStyle = stroke;
    ctx.beginPath();
    ctx.arc(xFor(lastPoint.ts), yFor(Number(getValue(lastPoint) || 0)), 3, 0, Math.PI * 2);
    ctx.fill();
  },

  getActiveRoomProfile() {
    return getRoomProfileById(this.state.roomProfiles, this.state.activeRoomProfileId);
  },

  getRoomProfileLabel(profile) {
    if (!profile) return '-';
    return profile.labelKey ? t(profile.labelKey) : (profile.name || profile.id);
  },

  getRoomTemplateLabel(template) {
    if (!template) return t('fp2.layout.template_none');
    return template.labelKey ? t(template.labelKey) : (template.name || template.id);
  },

  getSelectedRoomTemplate() {
    return getRoomTemplateById(this.state.roomTemplates, this.state.selectedRoomTemplateId);
  },

  getStoredRoomBoundary(profile = this.getActiveRoomProfile()) {
    if (!profile) return null;
    const boundary = this.state.roomProfileBoundaries?.[profile.id];
    return boundary && Array.isArray(boundary.points) && boundary.points.length >= 3
      ? boundary
      : null;
  },

  getActiveRoomBoundary(profile = this.getActiveRoomProfile(), { includeDraft = true } = {}) {
    if (!profile) return null;
    const draft = this.state.roomBoundaryDraft;
    if (
      includeDraft
      && draft
      && draft.profileId === profile.id
      && Array.isArray(draft.points)
      && draft.points.length >= 3
    ) {
      return {
        id: draft.id,
        label: draft.label || this.getRoomProfileLabel(profile),
        shapeType: draft.shapeType || 'polygon',
        source: draft.source || 'corner_capture',
        capturedAt: draft.capturedAt || null,
        points: draft.points.map((point) => ({
          xCm: Math.round(point.xCm),
          yCm: Math.round(point.yCm)
        }))
      };
    }
    return this.getStoredRoomBoundary(profile);
  },

  setActiveRoomBoundary(boundary, profile = this.getActiveRoomProfile()) {
    if (!profile) return;
    const nextBoundaries = { ...this.state.roomProfileBoundaries };
    if (boundary && Array.isArray(boundary.points) && boundary.points.length >= 3) {
      nextBoundaries[profile.id] = {
        ...boundary,
        label: boundary.label || this.getRoomProfileLabel(profile),
        points: boundary.points.map((point) => ({
          xCm: Math.round(point.xCm),
          yCm: Math.round(point.yCm)
        }))
      };
    } else {
      delete nextBoundaries[profile.id];
    }
    this.state.roomProfileBoundaries = nextBoundaries;
    persistRoomProfileBoundaries(this.state.roomProfileBoundaries);
    this.renderRoomProfileControls();
    this.renderAnimatedMap();
    this.scheduleRoomConfigSave();
  },

  getActiveRoomWalkableAreas(profile = this.getActiveRoomProfile()) {
    if (!profile) return [];
    const direct = Array.isArray(this.state.roomProfileWalkableAreas?.[profile.id])
      ? this.state.roomProfileWalkableAreas[profile.id]
      : [];
    if (direct.length) return direct;
    const fallbackGarage = Array.isArray(this.state.roomProfileWalkableAreas?.garage)
      ? this.state.roomProfileWalkableAreas.garage
      : [];
    const profileName = String(profile.name || profile.id || '').toLowerCase();
    if (fallbackGarage.length && (profile.id === 'garage' || profileName.includes('гараж') || profileName.includes('garage'))) {
      return fallbackGarage;
    }
    return [];
  },

  getActiveRoomLayoutItems(profile = this.getActiveRoomProfile()) {
    if (!profile) return [];
    return Array.isArray(this.state.roomProfileLayouts?.[profile.id]) ? this.state.roomProfileLayouts[profile.id] : [];
  },

  getActiveRoomStructuralAreas(profile = this.getActiveRoomProfile()) {
    if (!profile) return [];
    return Array.isArray(this.state.roomProfileStructuralAreas?.[profile.id])
      ? this.state.roomProfileStructuralAreas[profile.id]
      : [];
  },

  getSelectedRoomItem(profile = this.getActiveRoomProfile()) {
    if (!profile || !this.state.selectedRoomItemId) return null;
    return this.getActiveRoomLayoutItems(profile).find((item) => item.id === this.state.selectedRoomItemId) || null;
  },

  ensureSelectedRoomItem(profile = this.getActiveRoomProfile()) {
    const items = this.getActiveRoomLayoutItems(profile);
    if (!items.length) {
      this.state.selectedRoomItemId = null;
      return null;
    }
    if (!items.some((item) => item.id === this.state.selectedRoomItemId)) {
      this.state.selectedRoomItemId = null;
      return null;
    }
    return this.getSelectedRoomItem(profile);
  },

  setSelectedRoomItem(itemId) {
    this.state.selectedRoomItemId = itemId || null;
    if (itemId) {
      this.state.selectedRoomStructureId = null;
      this.state.roomItemInteraction = null;
    }
    this.renderRoomProfileControls();
    this.renderAnimatedMap();
  },

  setActiveRoomLayoutItems(items, profile = this.getActiveRoomProfile()) {
    if (!profile) return;
    const nextLayouts = { ...this.state.roomProfileLayouts };
    const nextItems = Array.isArray(items) ? items : [];
    if (nextItems.length) {
      nextLayouts[profile.id] = nextItems;
    } else {
      delete nextLayouts[profile.id];
    }
    this.state.roomProfileLayouts = nextLayouts;
    persistRoomProfileLayouts(this.state.roomProfileLayouts);
    this.ensureSelectedRoomItem(profile);
    this.renderRoomProfileControls();
    this.renderAnimatedMap();
    this.scheduleRoomConfigSave();
  },

  getSelectedRoomStructure(profile = this.getActiveRoomProfile()) {
    if (!profile || !this.state.selectedRoomStructureId) return null;
    return this.getActiveRoomStructuralAreas(profile).find((area) => area.id === this.state.selectedRoomStructureId) || null;
  },

  ensureSelectedRoomStructure(profile = this.getActiveRoomProfile()) {
    const areas = this.getActiveRoomStructuralAreas(profile);
    if (!areas.length) {
      this.state.selectedRoomStructureId = null;
      return null;
    }
    if (!areas.some((area) => area.id === this.state.selectedRoomStructureId)) {
      this.state.selectedRoomStructureId = null;
      return null;
    }
    return this.getSelectedRoomStructure(profile);
  },

  setSelectedRoomStructure(structureId) {
    this.state.selectedRoomStructureId = structureId || null;
    if (structureId) {
      this.state.selectedRoomItemId = null;
      this.state.roomItemInteraction = null;
    }
    this.renderRoomProfileControls();
    this.renderAnimatedMap();
  },

  setActiveRoomStructuralAreas(areas, profile = this.getActiveRoomProfile()) {
    if (!profile) return;
    const nextStructures = { ...this.state.roomProfileStructuralAreas };
    const nextAreas = Array.isArray(areas) ? areas.map((area) => this.cloneStructuralArea(area)).filter(Boolean) : [];
    if (nextAreas.length) {
      nextStructures[profile.id] = nextAreas;
    } else {
      delete nextStructures[profile.id];
    }
    this.state.roomProfileStructuralAreas = nextStructures;
    persistRoomProfileStructuralAreas(this.state.roomProfileStructuralAreas);
    this.ensureSelectedRoomStructure(profile);
    this.renderRoomProfileControls();
    this.renderAnimatedMap();
    this.scheduleRoomConfigSave();
  },

  getLayoutBounds(geometry) {
    if (!geometry) return null;
    return {
      minX: geometry.minX,
      maxX: geometry.maxX,
      minY: geometry.minY,
      maxY: geometry.maxY
    };
  },

  materializeTemplateItems(template, geometry) {
    const bounds = this.getLayoutBounds(geometry);
    if (!template || !bounds) return [];
    const widthCm = Math.max(1, bounds.maxX - bounds.minX);
    const depthCm = Math.max(1, bounds.maxY - bounds.minY);
    return (template.items || []).map((item, index) => {
      const def = getRoomItemDefinition(item.type);
      const width = item.nw ? Math.max(20, Math.round(item.nw * widthCm)) : def.widthCm;
      const depth = item.nd ? Math.max(20, Math.round(item.nd * depthCm)) : def.depthCm;
      return {
        id: `${template.id}-${item.type}-${index + 1}`,
        type: item.type,
        x: Math.round(bounds.minX + item.nx * widthCm),
        y: Math.round(bounds.minY + item.ny * depthCm),
        widthCm: width,
        depthCm: depth,
        rotationDeg: Number(item.rotationDeg || 0)
      };
    });
  },

  serializeLayoutItemsAsTemplate(items, geometry) {
    const bounds = this.getLayoutBounds(geometry);
    if (!bounds) return [];
    const widthCm = Math.max(1, bounds.maxX - bounds.minX);
    const depthCm = Math.max(1, bounds.maxY - bounds.minY);
    return (items || []).map((item) => ({
      type: item.type,
      nx: Number(((item.x - bounds.minX) / widthCm).toFixed(4)),
      ny: Number(((item.y - bounds.minY) / depthCm).toFixed(4)),
      nw: Number((item.widthCm / widthCm).toFixed(4)),
      nd: Number((item.depthCm / depthCm).toFixed(4)),
      rotationDeg: Number(item.rotationDeg || 0)
    }));
  },

  getStructureStyle(kind = 'blocked') {
    if (String(kind || 'blocked') === 'wall') {
      return {
        fill: 'rgba(148, 163, 184, 0.24)',
        stroke: 'rgba(226, 232, 240, 0.94)'
      };
    }
    return {
      fill: 'rgba(71, 85, 105, 0.22)',
      stroke: 'rgba(148, 163, 184, 0.92)'
    };
  },

  cloneRoomPoint(point) {
    if (!point) return null;
    return {
      xCm: Math.round(Number(point.xCm ?? point.x) || 0),
      yCm: Math.round(Number(point.yCm ?? point.y) || 0)
    };
  },

  isWallStructure(area) {
    return String(area?.kind || '').trim().toLowerCase() === 'wall';
  },

  getStructureKindLabel(area) {
    return this.isWallStructure(area)
      ? t('fp2.layout.structure_kind.wall')
      : t('fp2.layout.structure_kind.blocked');
  },

  getStructureEditablePoints(area) {
    if (this.isWallStructure(area)) {
      const start = this.cloneRoomPoint(area.start || area.points?.[0]);
      const end = this.cloneRoomPoint(area.end || area.points?.[1]);
      return start && end ? [start, end] : [];
    }
    return Array.isArray(area?.points)
      ? area.points.map((point) => this.cloneRoomPoint(point)).filter(Boolean)
      : [];
  },

  getStructuralAreaThicknessCm(area) {
    if (!this.isWallStructure(area)) return 0;
    return Math.max(6, Math.min(120, Math.round(Number(area?.thicknessCm || area?.widthCm || 16))));
  },

  getStructuralAreaPoints(area) {
    if (!area) return [];
    if (!this.isWallStructure(area)) {
      return this.getStructureEditablePoints(area);
    }
    const [start, end] = this.getStructureEditablePoints(area);
    if (!start || !end) return [];
    const thicknessCm = this.getStructuralAreaThicknessCm(area);
    const dx = Number(end.xCm) - Number(start.xCm);
    const dy = Number(end.yCm) - Number(start.yCm);
    const length = Math.hypot(dx, dy);
    const unitX = length > 0 ? dx / length : 1;
    const unitY = length > 0 ? dy / length : 0;
    const normalX = -unitY;
    const normalY = unitX;
    const half = thicknessCm / 2;
    const buildPoint = (point, direction) => ({
      xCm: Number((Number(point.xCm) + normalX * half * direction).toFixed(2)),
      yCm: Number((Number(point.yCm) + normalY * half * direction).toFixed(2))
    });
    return [
      buildPoint(start, 1),
      buildPoint(end, 1),
      buildPoint(end, -1),
      buildPoint(start, -1)
    ];
  },

  getStructureCanvasEditPoints(area, projection) {
    if (!projection) return [];
    return this.getStructureEditablePoints(area).map((point) => ({
      x: projection.toCanvasX(point.xCm),
      y: projection.toCanvasY(point.yCm)
    }));
  },

  getStructurePointLabel(area, index) {
    if (this.isWallStructure(area)) {
      return index === 0
        ? t('fp2.layout.structure_point_start')
        : t('fp2.layout.structure_point_end');
    }
    return t('fp2.layout.structure_point_label', { count: index + 1 });
  },

  cloneStructuralArea(area, { id = null } = {}) {
    if (!area) return null;
    if (this.isWallStructure(area)) {
      const [start, end] = this.getStructureEditablePoints(area);
      if (!start || !end) return null;
      return {
        id: String(id || area.id || `structure-${Date.now()}`),
        kind: 'wall',
        label: String(area.label || this.getStructureKindLabel(area)).trim() || this.getStructureKindLabel(area),
        fill: area.fill || this.getStructureStyle('wall').fill,
        stroke: area.stroke || this.getStructureStyle('wall').stroke,
        thicknessCm: this.getStructuralAreaThicknessCm(area),
        start,
        end,
        points: [start, end]
      };
    }

    const points = this.getStructureEditablePoints(area);
    if (points.length < 3) return null;
    return {
      id: String(id || area.id || `structure-${Date.now()}`),
      kind: String(area.kind || 'blocked'),
      label: String(area.label || this.getStructureKindLabel(area)).trim() || this.getStructureKindLabel(area),
      fill: area.fill || this.getStructureStyle('blocked').fill,
      stroke: area.stroke || this.getStructureStyle('blocked').stroke,
      points
    };
  },

  materializeTemplateStructures(template, geometry) {
    const bounds = this.getLayoutBounds(geometry);
    if (!template || !bounds) return [];
    const widthCm = Math.max(1, bounds.maxX - bounds.minX);
    const depthCm = Math.max(1, bounds.maxY - bounds.minY);
    return (template.structures || []).map((area, index) => {
      if (String(area?.kind || 'blocked') === 'wall') {
        const start = area.start || area.from || area.points?.[0];
        const end = area.end || area.to || area.points?.[1];
        if (!start || !end) return null;
        return this.cloneStructuralArea({
          id: `${template.id}-structure-${index + 1}`,
          kind: 'wall',
          label: String(area.label || t('fp2.layout.structure_default_name_wall', { count: index + 1 })),
          fill: area.fill || this.getStructureStyle('wall').fill,
          stroke: area.stroke || this.getStructureStyle('wall').stroke,
          thicknessCm: Number(area.thicknessCm || area.widthCm || 16),
          start: {
            xCm: Math.round(bounds.minX + start.nx * widthCm),
            yCm: Math.round(bounds.minY + start.ny * depthCm)
          },
          end: {
            xCm: Math.round(bounds.minX + end.nx * widthCm),
            yCm: Math.round(bounds.minY + end.ny * depthCm)
          }
        });
      }

      const points = (area.points || []).map((point) => ({
        xCm: Math.round(bounds.minX + point.nx * widthCm),
        yCm: Math.round(bounds.minY + point.ny * depthCm)
      }));
      return this.cloneStructuralArea({
        id: `${template.id}-structure-${index + 1}`,
        kind: String(area.kind || 'blocked'),
        label: String(area.label || t('fp2.layout.structure_default_name', { count: index + 1 })),
        fill: area.fill || this.getStructureStyle('blocked').fill,
        stroke: area.stroke || this.getStructureStyle('blocked').stroke,
        points
      });
    }).filter(Boolean);
  },

  serializeStructuralAreasAsTemplate(areas, geometry) {
    const bounds = this.getLayoutBounds(geometry);
    if (!bounds) return [];
    const widthCm = Math.max(1, bounds.maxX - bounds.minX);
    const depthCm = Math.max(1, bounds.maxY - bounds.minY);
    return (areas || []).map((area) => {
      if (this.isWallStructure(area)) {
        const [start, end] = this.getStructureEditablePoints(area);
        if (!start || !end) return null;
        return {
          kind: 'wall',
          label: String(area.label || 'Wall'),
          fill: area.fill || this.getStructureStyle('wall').fill,
          stroke: area.stroke || this.getStructureStyle('wall').stroke,
          thicknessCm: this.getStructuralAreaThicknessCm(area),
          start: {
            nx: Number((((start.xCm - bounds.minX) / widthCm)).toFixed(4)),
            ny: Number((((start.yCm - bounds.minY) / depthCm)).toFixed(4))
          },
          end: {
            nx: Number((((end.xCm - bounds.minX) / widthCm)).toFixed(4)),
            ny: Number((((end.yCm - bounds.minY) / depthCm)).toFixed(4))
          }
        };
      }

      const points = this.getStructureEditablePoints(area).map((point) => ({
        nx: Number((((point.xCm - bounds.minX) / widthCm)).toFixed(4)),
        ny: Number((((point.yCm - bounds.minY) / depthCm)).toFixed(4))
      }));
      if (points.length < 3) return null;
      return {
        kind: String(area.kind || 'blocked'),
        label: String(area.label || 'Blocked area'),
        fill: area.fill || this.getStructureStyle('blocked').fill,
        stroke: area.stroke || this.getStructureStyle('blocked').stroke,
        points
      };
    }).filter(Boolean);
  },

  clampRoomPointToGeometry(point, geometry) {
    if (!point || !geometry) return null;
    return {
      xCm: Math.round(Math.max(geometry.minX, Math.min(geometry.maxX, Number(point.xCm ?? point.x) || 0))),
      yCm: Math.round(Math.max(geometry.minY, Math.min(geometry.maxY, Number(point.yCm ?? point.y) || 0)))
    };
  },

  getNextStructureDefaultName(profile = this.getActiveRoomProfile(), kind = 'blocked') {
    const areas = this.getActiveRoomStructuralAreas(profile);
    const nextIndex = areas.filter((area) => String(area.kind || 'blocked') === String(kind || 'blocked')).length + 1;
    return kind === 'wall'
      ? t('fp2.layout.structure_default_name_wall', { count: nextIndex })
      : t('fp2.layout.structure_default_name', { count: nextIndex });
  },

  appendRoomStructureDraftPoint(roomPoint, profile = this.getActiveRoomProfile()) {
    const geometry = this.getActiveRoomGeometry(profile);
    const draft = this.state.roomStructureDraft;
    if (!geometry || !draft) return;
    const normalized = this.clampRoomPointToGeometry(roomPoint, geometry);
    if (!normalized) return;
    const previousPoint = (draft.points || []).at(-1);
    if (previousPoint && this.getBoundarySegmentLengthCm(previousPoint, normalized) < 8) {
      return draft;
    }
    this.state.roomStructureDraft = {
      ...draft,
      points: [...(draft.points || []), normalized]
    };
    this.renderRoomProfileControls();
    this.renderAnimatedMap();
    return this.state.roomStructureDraft;
  },

  handleStartRoomStructureDraft(kind = 'wall') {
    const activeProfile = this.getActiveRoomProfile();
    if (!activeProfile || activeProfile.kind !== 'fixed') return;
    const resolvedKind = String(kind || 'wall') === 'wall' ? 'wall' : 'blocked';
    const palette = this.getStructureStyle(resolvedKind);
    this.state.editLayoutMode = true;
    this.state.selectedRoomItemId = null;
    this.state.selectedRoomStructureId = null;
    this.state.roomItemInteraction = null;
    this.state.roomStructureDraft = {
      id: `structure-draft-${Date.now()}`,
      profileId: activeProfile.id,
      kind: resolvedKind,
      label: this.getNextStructureDefaultName(activeProfile, resolvedKind),
      fill: palette.fill,
      stroke: palette.stroke,
      thicknessCm: resolvedKind === 'wall' ? 18 : 0,
      points: []
    };
    this.renderRoomProfileControls();
    this.renderAnimatedMap();
  },

  cancelRoomStructureDraft() {
    this.state.roomStructureDraft = null;
    this.renderRoomProfileControls();
    this.renderAnimatedMap();
  },

  handleFinishRoomStructureDraft() {
    const activeProfile = this.getActiveRoomProfile();
    const draft = this.state.roomStructureDraft;
    if (!activeProfile || activeProfile.kind !== 'fixed' || !draft) return;
    const minPoints = draft.kind === 'wall' ? 2 : 3;
    if ((draft.points || []).length < minPoints) {
      window.alert(t('fp2.layout.structure_need_points', {
        count: minPoints,
        kind: this.getStructureKindLabel(draft)
      }));
      return;
    }
    const palette = this.getStructureStyle(draft.kind);
    const area = this.cloneStructuralArea({
      id: `structure-${Date.now()}`,
      kind: String(draft.kind || 'blocked'),
      label: String(draft.label || this.getNextStructureDefaultName(activeProfile, draft.kind)).trim(),
      fill: draft.fill || palette.fill,
      stroke: draft.stroke || palette.stroke,
      thicknessCm: draft.kind === 'wall' ? Number(draft.thicknessCm || 18) : 0,
      start: draft.points?.[0],
      end: draft.points?.[1],
      points: draft.points
    });
    if (!area) return;

    this.state.roomStructureDraft = null;
    this.setActiveRoomStructuralAreas([
      ...this.getActiveRoomStructuralAreas(activeProfile),
      area
    ], activeProfile);
    this.setSelectedRoomStructure(area.id);
  },

  handleClearRoomStructures() {
    const activeProfile = this.getActiveRoomProfile();
    if (!activeProfile || activeProfile.kind !== 'fixed' || typeof window === 'undefined') return;
    const confirmed = window.confirm(t('fp2.layout.structure_clear_confirm', {
      name: this.getRoomProfileLabel(activeProfile)
    }));
    if (!confirmed) return;
    this.state.roomStructureDraft = null;
    this.state.roomItemInteraction = null;
    this.state.selectedRoomStructureId = null;
    this.setActiveRoomStructuralAreas([], activeProfile);
    this.scheduleRoomConfigSave({ immediate: true });
  },

  handleRemoveRoomStructure(structureId) {
    const activeProfile = this.getActiveRoomProfile();
    if (!activeProfile) return;
    if (this.state.selectedRoomStructureId === structureId) {
      this.state.roomItemInteraction = null;
      this.state.selectedRoomStructureId = null;
    }
    this.setActiveRoomStructuralAreas(
      this.getActiveRoomStructuralAreas(activeProfile).filter((area) => area.id !== structureId),
      activeProfile
    );
    this.scheduleRoomConfigSave({ immediate: true });
  },

  handleSelectedRoomStructurePointInput(vertexIndex, axis, value, profile = this.getActiveRoomProfile()) {
    const selected = this.getSelectedRoomStructure(profile);
    if (!selected || !Number.isInteger(vertexIndex) || !['xCm', 'yCm'].includes(String(axis || ''))) {
      return;
    }
    const numeric = Number(value);
    if (!Number.isFinite(numeric)) return;
    const currentPoint = this.getStructureEditablePoints(selected)[vertexIndex];
    if (!currentPoint) return;
    this.updateRoomStructureVertex(selected.id, vertexIndex, {
      ...currentPoint,
      [axis]: Math.round(numeric)
    }, profile);
  },

  removeRoomStructureVertex(structureId, vertexIndex, profile = this.getActiveRoomProfile()) {
    if (!profile || !structureId || !Number.isInteger(vertexIndex)) return;
    const currentArea = this.getActiveRoomStructuralAreas(profile).find((area) => area.id === structureId);
    if (!currentArea || this.isWallStructure(currentArea)) return;
    const points = this.getStructureEditablePoints(currentArea);
    if (points.length <= 3 || !points[vertexIndex]) return;
    const nextPoints = points.filter((_, index) => index !== vertexIndex);
    const nextAreas = this.getActiveRoomStructuralAreas(profile).map((area) => {
      if (area.id !== structureId) return area;
      return this.cloneStructuralArea({
        ...area,
        points: nextPoints
      });
    }).filter(Boolean);
    this.setActiveRoomStructuralAreas(nextAreas, profile);
    this.state.selectedRoomStructureId = structureId;
    this.scheduleRoomConfigSave({ immediate: true });
  },

  updateRoomStructureLabel(structureId, label, profile = this.getActiveRoomProfile()) {
    if (!profile || !structureId) return;
    const trimmedLabel = String(label || '').trim();
    const currentArea = this.getActiveRoomStructuralAreas(profile).find((area) => area.id === structureId);
    if (!currentArea) return;
    const nextLabel = trimmedLabel || this.getNextStructureDefaultName(profile, currentArea.kind);
    if (String(currentArea.label || '') === nextLabel) return;
    const nextAreas = this.getActiveRoomStructuralAreas(profile).map((area) => {
      if (area.id !== structureId) return area;
      return this.cloneStructuralArea({
        ...area,
        label: nextLabel
      });
    }).filter(Boolean);
    this.setActiveRoomStructuralAreas(nextAreas, profile);
    this.state.selectedRoomStructureId = structureId;
  },

  updateRoomStructureWallThickness(structureId, thicknessCm, profile = this.getActiveRoomProfile()) {
    if (!profile || !structureId) return;
    const nextThickness = Math.max(6, Math.min(120, Math.round(Number(thicknessCm) || 16)));
    const currentArea = this.getActiveRoomStructuralAreas(profile).find((area) => area.id === structureId);
    if (!currentArea || !this.isWallStructure(currentArea) || this.getStructuralAreaThicknessCm(currentArea) === nextThickness) {
      return;
    }
    const nextAreas = this.getActiveRoomStructuralAreas(profile).map((area) => {
      if (area.id !== structureId || !this.isWallStructure(area)) return area;
      return this.cloneStructuralArea({
        ...area,
        thicknessCm: nextThickness
      });
    }).filter(Boolean);
    this.setActiveRoomStructuralAreas(nextAreas, profile);
    this.state.selectedRoomStructureId = structureId;
  },

  handleSelectedRoomStructureInput() {
    const activeProfile = this.getActiveRoomProfile();
    const selected = this.getSelectedRoomStructure(activeProfile);
    if (!selected) return;
    const label = this.elements.roomStructureLabel?.value ?? selected.label;
    this.updateRoomStructureLabel(selected.id, label, activeProfile);
    if (this.isWallStructure(selected)) {
      this.updateRoomStructureWallThickness(
        selected.id,
        Number(this.elements.roomStructureThickness?.value ?? this.getStructuralAreaThicknessCm(selected)),
        activeProfile
      );
    }
  },

  updateRoomStructureVertex(structureId, vertexIndex, roomPoint, profile = this.getActiveRoomProfile()) {
    const geometry = this.getActiveRoomGeometry(profile);
    if (!profile || !geometry || !Number.isInteger(vertexIndex)) return;
    const nextPoint = this.clampRoomPointToGeometry(roomPoint, geometry);
    if (!nextPoint) return;
    const nextAreas = this.getActiveRoomStructuralAreas(profile).map((area) => {
      if (area.id !== structureId) return area;
      if (this.isWallStructure(area)) {
        const [start, end] = this.getStructureEditablePoints(area);
        if (!start || !end || ![0, 1].includes(vertexIndex)) return area;
        const nextStart = vertexIndex === 0 ? nextPoint : start;
        const nextEnd = vertexIndex === 1 ? nextPoint : end;
        return this.cloneStructuralArea({
          ...area,
          start: nextStart,
          end: nextEnd
        });
      }
      const nextPoints = this.getStructureEditablePoints(area);
      if (!nextPoints[vertexIndex]) return area;
      nextPoints[vertexIndex] = nextPoint;
      return this.cloneStructuralArea({
        ...area,
        points: nextPoints
      });
    });
    this.setActiveRoomStructuralAreas(nextAreas, profile);
    this.state.selectedRoomStructureId = structureId;
  },

  translateStructuralArea(area, deltaX, deltaY, geometry) {
    if (!area || !geometry) return area;
    const constraintPoints = this.getStructuralAreaPoints(area);
    if (!constraintPoints.length) return area;

    const minX = Math.min(...constraintPoints.map((point) => Number(point.xCm || 0)));
    const maxX = Math.max(...constraintPoints.map((point) => Number(point.xCm || 0)));
    const minY = Math.min(...constraintPoints.map((point) => Number(point.yCm || 0)));
    const maxY = Math.max(...constraintPoints.map((point) => Number(point.yCm || 0)));

    const allowedDx = Math.max(
      geometry.minX - minX,
      Math.min(geometry.maxX - maxX, Number(deltaX) || 0)
    );
    const allowedDy = Math.max(
      geometry.minY - minY,
      Math.min(geometry.maxY - maxY, Number(deltaY) || 0)
    );

    if (this.isWallStructure(area)) {
      const [start, end] = this.getStructureEditablePoints(area);
      if (!start || !end) return area;
      return this.cloneStructuralArea({
        ...area,
        start: {
          xCm: start.xCm + allowedDx,
          yCm: start.yCm + allowedDy
        },
        end: {
          xCm: end.xCm + allowedDx,
          yCm: end.yCm + allowedDy
        }
      });
    }

    const points = this.getStructureEditablePoints(area).map((point) => ({
      xCm: point.xCm + allowedDx,
      yCm: point.yCm + allowedDy
    }));
    return this.cloneStructuralArea({
      ...area,
      points
    });
  },

  moveRoomStructure(structureId, deltaX, deltaY, profile = this.getActiveRoomProfile()) {
    const geometry = this.getActiveRoomGeometry(profile);
    if (!profile || !geometry || !structureId) return;
    const nextAreas = this.getActiveRoomStructuralAreas(profile).map((area) => (
      area.id === structureId
        ? this.translateStructuralArea(area, deltaX, deltaY, geometry)
        : area
    )).filter(Boolean);
    this.setActiveRoomStructuralAreas(nextAreas, profile);
    this.state.selectedRoomStructureId = structureId;
  },

  getRoomStructureCentroid(area) {
    const points = this.getStructuralAreaPoints(area);
    if (!points.length) return null;
    const sum = points.reduce((acc, point) => ({
      xCm: acc.xCm + Number(point.xCm || 0),
      yCm: acc.yCm + Number(point.yCm || 0)
    }), { xCm: 0, yCm: 0 });
    return {
      xCm: sum.xCm / points.length,
      yCm: sum.yCm / points.length
    };
  },

  getPolygonPerimeterCm(points = []) {
    if (!Array.isArray(points) || points.length < 2) return 0;
    let perimeter = 0;
    for (let index = 0; index < points.length; index += 1) {
      const current = points[index];
      const next = points[(index + 1) % points.length];
      perimeter += this.getBoundarySegmentLengthCm(current, next);
    }
    return perimeter;
  },

  getStructuralAreaLengthCm(area) {
    if (this.isWallStructure(area)) {
      const [start, end] = this.getStructureEditablePoints(area);
      return start && end ? this.getBoundarySegmentLengthCm(start, end) : 0;
    }
    return this.getPolygonPerimeterCm(this.getStructuralAreaPoints(area));
  },

  getPolygonAreaCm2(points = []) {
    if (!Array.isArray(points) || points.length < 3) return 0;
    let area = 0;
    for (let index = 0; index < points.length; index += 1) {
      const current = points[index];
      const next = points[(index + 1) % points.length];
      area += Number(current.xCm || 0) * Number(next.yCm || 0);
      area -= Number(next.xCm || 0) * Number(current.yCm || 0);
    }
    return Math.abs(area) / 2;
  },

  clampRoomItemToGeometry(item, geometry) {
    if (!item || !geometry) return item;
    return {
      ...item,
      x: Math.max(geometry.minX, Math.min(geometry.maxX, item.x)),
      y: Math.max(geometry.minY, Math.min(geometry.maxY, item.y)),
      widthCm: Math.max(20, Math.min(geometry.widthCm, item.widthCm)),
      depthCm: Math.max(20, Math.min(geometry.depthCm, item.depthCm))
    };
  },

  getRoomItemLabel(item) {
    const def = getRoomItemDefinition(item?.type);
    return def?.labelKey ? t(def.labelKey) : (item?.type || '-');
  },

  getRoomItemIcon(item) {
    const def = getRoomItemDefinition(item?.type);
    return def?.icon || '⬚';
  },

  normalizeRoomAddKind(kind = 'item') {
    const normalized = String(kind || 'item').trim().toLowerCase();
    if (normalized === 'wall' || normalized === 'zone') {
      return normalized;
    }
    return 'item';
  },

  getRoomAddConfirmLabel(kind = this.state.roomAddKind) {
    const resolvedKind = this.normalizeRoomAddKind(kind);
    if (resolvedKind === 'wall') return t('fp2.layout.add_confirm.wall');
    if (resolvedKind === 'zone') return t('fp2.layout.add_confirm.zone');
    return t('fp2.layout.add_confirm.item');
  },

  toggleRoomAddPanel(forceValue = null) {
    const activeProfile = this.getActiveRoomProfile();
    if (!activeProfile || activeProfile.kind !== 'fixed') return;
    this.state.roomAddPanelOpen = typeof forceValue === 'boolean'
      ? forceValue
      : !this.state.roomAddPanelOpen;
    if (!this.state.roomAddPanelOpen) {
      this.state.roomAddKind = 'item';
      this.state.roomAddItemType = this.state.roomAddItemType || BUILTIN_ROOM_ITEM_LIBRARY[0]?.type || 'sofa';
    }
    this.renderRoomProfileControls();
  },

  applyRoomAddSelection() {
    const activeProfile = this.getActiveRoomProfile();
    if (!activeProfile || activeProfile.kind !== 'fixed') return;
    const kind = this.normalizeRoomAddKind(this.state.roomAddKind);
    this.state.roomAddPanelOpen = false;
    if (kind === 'wall') {
      this.handleStartRoomStructureDraft('wall');
      return;
    }
    if (kind === 'zone') {
      this.handleStartRoomStructureDraft('blocked');
      return;
    }
    this.handleAddRoomItem(this.state.roomAddItemType || BUILTIN_ROOM_ITEM_LIBRARY[0]?.type || 'sofa');
  },

  toggleEditLayoutMode(forceValue = null) {
    this.state.editLayoutMode = typeof forceValue === 'boolean'
      ? forceValue
      : !this.state.editLayoutMode;
    if (!this.state.editLayoutMode) {
      this.state.roomItemInteraction = null;
      this.state.roomStructureDraft = null;
    }
    this.renderRoomProfileControls();
    this.renderAnimatedMap();
  },

  renderRoomProfileControls() {
    const {
      roomProfileSelect,
      roomProfileDelete,
      roomProfileMeta,
      roomStorageStatus,
      roomAddToggle,
      roomAddPanel,
      roomAddKind,
      roomAddItemField,
      roomAddItemType,
      roomAddConfirm,
      roomAddCancel,
      roomItemsClear,
      roomStructureFinish,
      roomStructureCancel,
      roomStructuresClear,
      roomEditMode,
      roomEditModeStatus,
      roomBoundaryStart,
      roomBoundaryCapture,
      roomBoundaryUndo,
      roomBoundaryClear,
      roomBoundaryStatus,
      roomBoundarySummary,
      roomBoundaryPoints,
      roomItemsSummary,
      roomItemsList,
      roomStructureDrawStatus,
      roomStructuresSummary,
      roomStructuresList,
      roomStructureInspector,
      roomStructurePointEditor,
      selectedRoomStructureName,
      roomStructureSelectionStatus,
      selectedRoomStructureDelete,
      roomStructureLabel,
      roomStructureThickness,
      roomStructureThicknessValue,
      roomStructureKindValue,
      roomStructurePointsValue,
      roomStructureLengthValue,
      roomStructureAreaValue,
      roomItemInspector,
      selectedRoomItemName,
      selectedRoomItemRotateLeft,
      selectedRoomItemRotateRight,
      selectedRoomItemDelete,
      roomItemX,
      roomItemY,
      roomItemWidth,
      roomItemDepth,
      roomItemRotation,
      roomItemXValue,
      roomItemYValue,
      roomItemWidthValue,
      roomItemDepthValue,
      roomItemRotationValue,
      animalFilterToggle,
      animalFilterStatus,
      calibrationStatus,
      calibrationCaptureLeft,
      calibrationCaptureRight,
      calibrationCaptureFar,
      calibrationApply,
      calibrationReset
    } = this.elements || {};
    const profiles = this.state.roomProfiles || [];
    const activeProfile = this.getActiveRoomProfile();
    const animalFilterEnabled = this.isAnimalFilterEnabled(activeProfile);
    const geometry = this.getActiveRoomGeometry();
    const draft = this.getCalibrationDraft(activeProfile);
    const storedBoundary = this.getStoredRoomBoundary(activeProfile);
    const boundaryDraft = this.getRoomBoundaryDraft(activeProfile);
    const activeBoundary = this.getActiveRoomBoundary(activeProfile);
    const boundaryMetrics = this.getRoomBoundaryMetrics(activeBoundary);
    const boundaryDraftMetrics = this.getRoomBoundaryMetrics(boundaryDraft);
    const hasBoundaryCaptureTarget = Boolean(this.getBoundaryCaptureTarget());
    const roomItems = this.getActiveRoomLayoutItems(activeProfile);
    const roomStructures = this.getActiveRoomStructuralAreas(activeProfile);
    const selectedItem = this.ensureSelectedRoomItem(activeProfile);
    const selectedStructure = this.ensureSelectedRoomStructure(activeProfile);
    const structureDraft = this.state.roomStructureDraft;
    const fixedProfile = activeProfile?.kind === 'fixed';
    const addKind = this.normalizeRoomAddKind(this.state.roomAddKind);

    if (roomProfileSelect) {
      roomProfileSelect.innerHTML = profiles.map(profile => `
        <option value="${profile.id}">${this.getRoomProfileLabel(profile)}</option>
      `).join('');
      roomProfileSelect.value = activeProfile?.id || '';
    }

    if (roomProfileDelete) {
      roomProfileDelete.disabled = !activeProfile || activeProfile.builtin;
      roomProfileDelete.hidden = !activeProfile || activeProfile.builtin;
    }

    if (roomAddToggle) {
      roomAddToggle.disabled = !fixedProfile;
      roomAddToggle.classList.toggle('is-active', Boolean(this.state.roomAddPanelOpen));
    }
    if (roomAddPanel) {
      roomAddPanel.hidden = !fixedProfile || !this.state.roomAddPanelOpen;
    }
    if (roomAddKind) {
      roomAddKind.value = addKind;
      roomAddKind.disabled = !fixedProfile;
    }
    if (roomAddItemType) {
      roomAddItemType.innerHTML = BUILTIN_ROOM_ITEM_LIBRARY.map((item) => `
        <option value="${item.type}">${this.getRoomItemLabel({ type: item.type })}</option>
      `).join('');
      roomAddItemType.value = this.state.roomAddItemType || BUILTIN_ROOM_ITEM_LIBRARY[0]?.type || '';
      roomAddItemType.disabled = !fixedProfile || addKind !== 'item';
    }
    if (roomAddItemField) {
      roomAddItemField.hidden = addKind !== 'item';
    }
    if (roomAddConfirm) {
      roomAddConfirm.textContent = this.getRoomAddConfirmLabel(addKind);
      roomAddConfirm.disabled = !fixedProfile;
    }
    if (roomAddCancel) {
      roomAddCancel.disabled = !fixedProfile;
    }
    if (roomItemsClear) roomItemsClear.disabled = !fixedProfile || roomItems.length === 0;
    if (roomBoundaryStart) roomBoundaryStart.disabled = !fixedProfile;
    if (roomBoundaryCapture) roomBoundaryCapture.disabled = !fixedProfile || !hasBoundaryCaptureTarget;
    if (roomBoundaryUndo) roomBoundaryUndo.disabled = !fixedProfile || !boundaryDraft || !(boundaryDraft.points || []).length;
    if (roomBoundaryClear) roomBoundaryClear.disabled = !fixedProfile || (!storedBoundary && !boundaryDraft);
    if (roomStructureFinish) {
      const requiredPoints = structureDraft?.kind === 'wall' ? 2 : 3;
      roomStructureFinish.disabled = !fixedProfile || !structureDraft || (structureDraft.points || []).length < requiredPoints;
    }
    if (roomStructureCancel) roomStructureCancel.disabled = !fixedProfile || !structureDraft;
    if (roomStructuresClear) roomStructuresClear.disabled = !fixedProfile || (!roomStructures.length && !structureDraft);
    if (roomEditMode) {
      roomEditMode.disabled = !fixedProfile;
      roomEditMode.classList.toggle('is-active', Boolean(this.state.editLayoutMode));
    }
    if (roomEditModeStatus) {
      roomEditModeStatus.textContent = this.state.editLayoutMode
        ? t('fp2.layout.edit_mode_on')
        : t('fp2.layout.edit_mode_off');
      roomEditModeStatus.className = `chip ${this.state.editLayoutMode ? 'chip--info' : 'chip--neutral'}`;
    }

    if (roomBoundaryStatus) {
      if (boundaryDraft) {
        roomBoundaryStatus.textContent = t('fp2.layout.room_boundary.status_draft', {
          count: (boundaryDraft.points || []).length,
          type: this.formatRoomBoundaryShape(boundaryDraftMetrics.shapeType)
        });
        roomBoundaryStatus.className = 'chip chip--warn';
      } else if (storedBoundary) {
        roomBoundaryStatus.textContent = t('fp2.layout.room_boundary.status_saved', {
          count: boundaryMetrics.pointCount,
          type: this.formatRoomBoundaryShape(boundaryMetrics.shapeType)
        });
        roomBoundaryStatus.className = 'chip chip--info';
      } else {
        roomBoundaryStatus.textContent = t('fp2.layout.room_boundary.status_empty');
        roomBoundaryStatus.className = 'chip chip--neutral';
      }
    }

    if (roomBoundarySummary) {
      roomBoundarySummary.textContent = activeBoundary
        ? t('fp2.layout.room_boundary.summary', {
            type: this.formatRoomBoundaryShape(boundaryMetrics.shapeType),
            count: boundaryMetrics.pointCount,
            width: this.formatLengthCm(boundaryMetrics.widthCm, { preferMeters: true }),
            depth: this.formatLengthCm(boundaryMetrics.depthCm, { preferMeters: true }),
            area: this.formatAreaCm2(boundaryMetrics.areaCm2)
          })
        : boundaryDraft
          ? t('fp2.layout.room_boundary.summary_draft', {
              count: (boundaryDraft.points || []).length
            })
          : t('fp2.layout.room_boundary.summary_empty');
    }

    if (roomBoundaryPoints) {
      const boundaryPoints = Array.isArray(boundaryDraft?.points)
        ? boundaryDraft.points
        : (Array.isArray(activeBoundary?.points) ? activeBoundary.points : []);
      roomBoundaryPoints.innerHTML = boundaryPoints.length
        ? boundaryPoints.map((point, index) => `
            <div class="fp2-layout-boundary-point">
              <strong>${t('fp2.layout.room_boundary.corner_index', { count: index + 1 })}</strong>
              <span>X ${this.formatLengthCm(point.xCm, { preferMeters: true })}</span>
              <span>Y ${this.formatLengthCm(point.yCm, { preferMeters: true })}</span>
            </div>
          `).join('')
        : `<div class="fp2-layout-item-empty">${t('fp2.layout.room_boundary.points_empty')}</div>`;
    }

    if (roomItemsSummary) {
      roomItemsSummary.textContent = t('fp2.layout.items_summary', { count: roomItems.length });
    }

    if (roomStructureDrawStatus) {
      roomStructureDrawStatus.textContent = structureDraft
        ? t('fp2.layout.structure_draw_active', {
            kind: this.getStructureKindLabel(structureDraft),
            count: (structureDraft.points || []).length
          })
        : selectedStructure
          ? `${this.getStructureKindLabel(selectedStructure)} · ${selectedStructure.label}`
          : t('fp2.layout.structure_draw_idle');
      roomStructureDrawStatus.className = `chip ${structureDraft ? 'chip--warn' : selectedStructure ? 'chip--info' : 'chip--neutral'}`;
    }

    if (roomStructuresSummary) {
      roomStructuresSummary.textContent = t('fp2.layout.structure_summary', { count: roomStructures.length });
    }

    if (roomStorageStatus) {
      const storageState = this.getRoomConfigStorageBadgeState();
      roomStorageStatus.textContent = storageState.text;
      roomStorageStatus.className = storageState.className;
    }

    if (roomItemsList) {
      roomItemsList.innerHTML = roomItems.length
        ? roomItems.map((item) => `
            <article class="fp2-layout-item ${selectedItem?.id === item.id ? 'is-selected' : ''}" data-item-select="${item.id}" role="button" tabindex="0" aria-label="${this.getRoomItemLabel(item)}">
              <div class="fp2-layout-item-head">
                <span class="fp2-layout-item-type">
                  <span class="fp2-layout-item-icon">${this.getRoomItemIcon(item)}</span>
                  <span class="fp2-layout-item-title">${this.getRoomItemLabel(item)}</span>
                </span>
                ${selectedItem?.id === item.id ? `<span class="chip chip--info fp2-layout-item-state">${t('fp2.layout.selected')}</span>` : ''}
              </div>
              <div class="fp2-layout-item-actions">
                <button class="btn btn--secondary btn--sm fp2-layout-item-btn fp2-layout-item-btn--compact" data-item-rotate-left="${item.id}">-90°</button>
                <button class="btn btn--secondary btn--sm fp2-layout-item-btn fp2-layout-item-btn--compact" data-item-rotate-right="${item.id}">+90°</button>
                <button class="btn btn--secondary btn--sm fp2-layout-item-btn" data-item-remove="${item.id}">${t('fp2.layout.item_remove')}</button>
              </div>
              <div class="fp2-layout-item-meta">
                <span>X ${this.formatLengthCm(item.x, { preferMeters: true })} · Y ${this.formatLengthCm(item.y, { preferMeters: true })}</span>
                <span>${this.formatLengthCm(item.widthCm, { preferMeters: true })} × ${this.formatLengthCm(item.depthCm, { preferMeters: true })}</span>
                <span>${Math.round(item.rotationDeg || 0)}°</span>
              </div>
            </article>
          `).join('')
        : `<div class="fp2-layout-item-empty">${t('fp2.layout.items_empty')}</div>`;
    }

    if (roomStructuresList) {
      roomStructuresList.innerHTML = roomStructures.length
        ? roomStructures.map((area) => `
            <article class="fp2-layout-structure ${selectedStructure?.id === area.id ? 'is-selected' : ''}" data-structure-select="${area.id}" role="button" tabindex="0" aria-label="${area.label}">
              <div class="fp2-layout-item-head">
                <span class="fp2-layout-item-type">
                  <span class="fp2-layout-item-icon">${this.isWallStructure(area) ? '║' : '▱'}</span>
                  <span class="fp2-layout-item-title">${area.label}</span>
                </span>
                ${selectedStructure?.id === area.id ? `<span class="chip chip--info fp2-layout-item-state">${t('fp2.layout.selected')}</span>` : ''}
              </div>
              <div class="fp2-layout-item-actions">
                <button class="btn btn--secondary btn--sm fp2-layout-item-btn" data-structure-remove="${area.id}">${t('fp2.layout.item_remove')}</button>
              </div>
              <div class="fp2-layout-item-meta">
                <span>${this.getStructureKindLabel(area)}</span>
                <span>${t('fp2.layout.structure_points', { count: this.getStructureEditablePoints(area).length })}</span>
                <span>${this.isWallStructure(area)
                  ? t('fp2.layout.structure_wall_meta', {
                      length: this.formatLengthCm(this.getStructuralAreaLengthCm(area), { preferMeters: true }),
                      thickness: this.formatLengthCm(this.getStructuralAreaThicknessCm(area), { preferMeters: true })
                    })
                  : t('fp2.layout.structure_zone_meta', {
                      area: this.formatAreaCm2(this.getPolygonAreaCm2(this.getStructuralAreaPoints(area))),
                      perimeter: this.formatLengthCm(this.getStructuralAreaLengthCm(area), { preferMeters: true })
                    })
                }</span>
              </div>
            </article>
          `).join('')
        : `<div class="fp2-layout-item-empty">${t('fp2.layout.structure_empty')}</div>`;
    }

    if (roomItemInspector) {
      roomItemInspector.style.display = fixedProfile ? 'flex' : 'none';
    }
    if (roomStructureInspector) {
      roomStructureInspector.style.display = fixedProfile ? 'flex' : 'none';
    }
    if (selectedRoomItemName) {
      selectedRoomItemName.textContent = selectedItem ? this.getRoomItemLabel(selectedItem) : t('fp2.layout.items_empty');
    }
    if (selectedRoomItemRotateLeft) {
      selectedRoomItemRotateLeft.disabled = !selectedItem;
    }
    if (selectedRoomItemRotateRight) {
      selectedRoomItemRotateRight.disabled = !selectedItem;
    }
    if (selectedRoomItemDelete) {
      selectedRoomItemDelete.disabled = !selectedItem;
    }
    if (roomItemX && roomItemY && roomItemWidth && roomItemDepth && roomItemRotation) {
      const geometryForRanges = geometry || { minX: -500, maxX: 500, minY: 0, maxY: 600, widthCm: 1000, depthCm: 600 };
      roomItemX.min = String(Math.floor(geometryForRanges.minX));
      roomItemX.max = String(Math.ceil(geometryForRanges.maxX));
      roomItemY.min = String(Math.floor(geometryForRanges.minY));
      roomItemY.max = String(Math.ceil(geometryForRanges.maxY));
      roomItemWidth.max = String(Math.ceil(geometryForRanges.widthCm));
      roomItemDepth.max = String(Math.ceil(geometryForRanges.depthCm));
      roomItemX.disabled = !selectedItem;
      roomItemY.disabled = !selectedItem;
      roomItemWidth.disabled = !selectedItem;
      roomItemDepth.disabled = !selectedItem;
      roomItemRotation.disabled = !selectedItem;
      if (selectedItem) {
        roomItemX.value = String(Math.round(selectedItem.x));
        roomItemY.value = String(Math.round(selectedItem.y));
        roomItemWidth.value = String(Math.round(selectedItem.widthCm));
        roomItemDepth.value = String(Math.round(selectedItem.depthCm));
        roomItemRotation.value = String(Math.round(selectedItem.rotationDeg || 0));
      }
    }
    if (roomItemXValue) roomItemXValue.textContent = selectedItem ? this.formatLengthCm(selectedItem.x, { preferMeters: true }) : '-';
    if (roomItemYValue) roomItemYValue.textContent = selectedItem ? this.formatLengthCm(selectedItem.y, { preferMeters: true }) : '-';
    if (roomItemWidthValue) roomItemWidthValue.textContent = selectedItem ? this.formatLengthCm(selectedItem.widthCm, { preferMeters: true }) : '-';
    if (roomItemDepthValue) roomItemDepthValue.textContent = selectedItem ? this.formatLengthCm(selectedItem.depthCm, { preferMeters: true }) : '-';
    if (roomItemRotationValue) roomItemRotationValue.textContent = selectedItem ? `${Math.round(selectedItem.rotationDeg || 0)}°` : '-';

    if (selectedRoomStructureName) {
      selectedRoomStructureName.textContent = selectedStructure ? selectedStructure.label : t('fp2.layout.structure_none_selected');
    }
    if (roomStructureSelectionStatus) {
      roomStructureSelectionStatus.textContent = selectedStructure
        ? this.getStructureKindLabel(selectedStructure)
        : t('fp2.layout.structure_none_short');
      roomStructureSelectionStatus.className = `chip ${selectedStructure ? 'chip--info' : 'chip--neutral'}`;
    }
    if (selectedRoomStructureDelete) {
      selectedRoomStructureDelete.disabled = !selectedStructure;
    }
    if (roomStructureLabel) {
      roomStructureLabel.disabled = !selectedStructure;
      roomStructureLabel.value = selectedStructure ? selectedStructure.label : '';
    }
    if (roomStructureThickness) {
      const selectedThickness = selectedStructure && this.isWallStructure(selectedStructure)
        ? this.getStructuralAreaThicknessCm(selectedStructure)
        : 16;
      roomStructureThickness.disabled = !selectedStructure || !this.isWallStructure(selectedStructure);
      roomStructureThickness.value = String(selectedThickness);
    }
    if (roomStructureThicknessValue) {
      roomStructureThicknessValue.textContent = selectedStructure && this.isWallStructure(selectedStructure)
        ? this.formatLengthCm(this.getStructuralAreaThicknessCm(selectedStructure), { preferMeters: true })
        : t('fp2.layout.structure_not_applicable');
    }
    if (roomStructureKindValue) {
      roomStructureKindValue.textContent = selectedStructure ? this.getStructureKindLabel(selectedStructure) : '-';
    }
    if (roomStructurePointsValue) {
      roomStructurePointsValue.textContent = selectedStructure
        ? t('fp2.layout.structure_points', { count: this.getStructureEditablePoints(selectedStructure).length })
        : '-';
    }
    if (roomStructureLengthValue) {
      roomStructureLengthValue.textContent = selectedStructure
        ? this.formatLengthCm(this.getStructuralAreaLengthCm(selectedStructure), { preferMeters: true })
        : '-';
    }
    if (roomStructureAreaValue) {
      roomStructureAreaValue.textContent = selectedStructure
        ? this.formatAreaCm2(this.getPolygonAreaCm2(this.getStructuralAreaPoints(selectedStructure)))
        : '-';
    }
    if (roomStructurePointEditor) {
      const geometryForRanges = geometry || { minX: -500, maxX: 500, minY: 0, maxY: 600 };
      const structurePoints = selectedStructure ? this.getStructureEditablePoints(selectedStructure) : [];
      roomStructurePointEditor.innerHTML = selectedStructure && structurePoints.length
        ? structurePoints.map((point, index) => `
            <div class="fp2-layout-structure-point-row">
              <div class="fp2-layout-structure-point-head">
                <strong>${this.getStructurePointLabel(selectedStructure, index)}</strong>
                ${!this.isWallStructure(selectedStructure) && structurePoints.length > 3
                  ? `<button class="btn btn--secondary btn--sm fp2-layout-point-remove" type="button" data-structure-point-remove="${index}">${t('fp2.layout.structure_vertex_remove')}</button>`
                  : ''}
              </div>
              <div class="fp2-layout-structure-point-fields">
                <label class="fp2-layout-field">
                  <span>X</span>
                  <input
                    type="number"
                    min="${Math.floor(geometryForRanges.minX)}"
                    max="${Math.ceil(geometryForRanges.maxX)}"
                    step="1"
                    value="${Math.round(point.xCm)}"
                    data-structure-point-input="xCm"
                    data-point-index="${index}"
                  >
                </label>
                <label class="fp2-layout-field">
                  <span>Y</span>
                  <input
                    type="number"
                    min="${Math.floor(geometryForRanges.minY)}"
                    max="${Math.ceil(geometryForRanges.maxY)}"
                    step="1"
                    value="${Math.round(point.yCm)}"
                    data-structure-point-input="yCm"
                    data-point-index="${index}"
                  >
                </label>
              </div>
            </div>
          `).join('')
        : `<div class="fp2-layout-item-empty">${t('fp2.layout.structure_points_empty')}</div>`;
    }

    if (roomProfileMeta) {
      roomProfileMeta.textContent = activeProfile?.kind === 'fixed'
        ? t('fp2.layout.meta', {
            name: this.getRoomProfileLabel(activeProfile),
            width: this.formatLengthCm(geometry?.widthCm || activeProfile.widthCm, { preferMeters: true }),
            depth: this.formatLengthCm(geometry?.depthCm || activeProfile.depthCm, { preferMeters: true })
          })
        : t('fp2.layout.meta_auto');
      if (activeProfile?.kind === 'fixed' && activeBoundary) {
        roomProfileMeta.textContent += ` · ${this.formatRoomBoundaryShape(boundaryMetrics.shapeType)}`;
      }
    }

    if (animalFilterToggle) {
      animalFilterToggle.checked = animalFilterEnabled;
    }

    if (animalFilterStatus) {
      animalFilterStatus.textContent = animalFilterEnabled ? t('fp2.filter.status.on') : t('fp2.filter.status.off');
      animalFilterStatus.className = `chip ${animalFilterEnabled ? 'warn' : 'chip--neutral'}`;
    }

    if (calibrationStatus) {
      calibrationStatus.textContent = activeProfile?.kind !== 'fixed'
        ? t('fp2.calibration.unavailable')
        : t('fp2.calibration.status', {
            left: this.formatCalibrationValue(draft?.leftX),
            right: this.formatCalibrationValue(draft?.rightX),
            far: this.formatCalibrationValue(draft?.farY)
          });
    }

    [calibrationCaptureLeft, calibrationCaptureRight, calibrationCaptureFar].forEach((button) => {
      if (!button) return;
      button.disabled = !fixedProfile;
    });

    if (calibrationApply) {
      calibrationApply.disabled = !fixedProfile || !this.canApplyCalibrationDraft(activeProfile);
    }

    if (calibrationReset) {
      calibrationReset.disabled = !fixedProfile
        || (!Number.isFinite(draft?.leftX) && !Number.isFinite(draft?.rightX) && !Number.isFinite(draft?.farY));
    }
  },

  setActiveRoomProfile(profileId) {
    if (!this.state.roomProfiles.some(profile => profile.id === profileId)) return;
    this.state.activeRoomProfileId = profileId;
    this.state.editLayoutMode = false;
    this.state.roomItemInteraction = null;
    this.state.roomBoundaryDraft = null;
    this.state.roomStructureDraft = null;
    persistActiveRoomProfileId(profileId);
    this.ensureSelectedRoomItem(this.getActiveRoomProfile());
    this.ensureSelectedRoomStructure(this.getActiveRoomProfile());
    this.renderRoomProfileControls();
    this.renderCurrent(this.lastCurrentData);
    this.renderAnimatedMap();
    this.scheduleRoomConfigSave();
  },

  isAnimalFilterEnabled(profile = this.getActiveRoomProfile()) {
    return getProfileAnimalFilterEnabled(profile, this.state.roomProfileFilters);
  },

  handleAnimalFilterToggle(enabled) {
    const activeProfile = this.getActiveRoomProfile();
    if (!activeProfile) return;
    this.state.roomProfileFilters = {
      ...this.state.roomProfileFilters,
      [activeProfile.id]: {
        antiAnimalFilterEnabled: Boolean(enabled)
      }
    };
    persistRoomProfileFilters(this.state.roomProfileFilters);
    this.renderRoomProfileControls();
    this.renderCurrent(this.lastCurrentData);
    this.scheduleRoomConfigSave();
  },

  getCalibrationDraft(profile = this.getActiveRoomProfile()) {
    if (!profile) return null;
    const stored = normalizeCalibrationOverride(this.state.roomProfileCalibration?.[profile.id]);
    const draft = normalizeCalibrationOverride(this.state.roomProfileCalibrationDrafts?.[profile.id]);
    return {
      leftX: draft?.leftX ?? stored?.leftX ?? null,
      rightX: draft?.rightX ?? stored?.rightX ?? null,
      farY: draft?.farY ?? stored?.farY ?? null,
      capturedAt: draft?.capturedAt ?? stored?.capturedAt ?? null
    };
  },

  getActiveRoomGeometry(profile = this.getActiveRoomProfile()) {
    if (!profile || profile.kind !== 'fixed') return null;
    const stored = normalizeCalibrationOverride(this.state.roomProfileCalibration?.[profile.id]);
    const draft = this.getCalibrationDraft(profile);
    const effectiveCalibration = this.canApplyCalibrationDraft(profile) ? draft : stored;
    const boundary = this.getActiveRoomBoundary(profile);
    return getProfileGeometry(profile, {
      [profile.id]: effectiveCalibration
    }, {
      [profile.id]: boundary
    });
  },

  formatCalibrationValue(value) {
    return this.formatLengthCm(value, { preferMeters: true });
  },

  canApplyCalibrationDraft(profile = this.getActiveRoomProfile()) {
    const draft = this.getCalibrationDraft(profile);
    return Number.isFinite(draft?.leftX) && Number.isFinite(draft?.rightX) && Number.isFinite(draft?.farY)
      && Math.abs(draft.rightX - draft.leftX) > 80
      && draft.farY >= 100;
  },

  getCalibrationCaptureTarget() {
    const withCoords = (this.state.targets || []).find((target) => this.hasCoordinates(target))
      || (this.state.rawTargets || []).find((target) => this.hasCoordinates(target));
    return withCoords || null;
  },

  getRoomBoundaryDraft(profile = this.getActiveRoomProfile()) {
    const draft = this.state.roomBoundaryDraft;
    if (!profile || !draft || draft.profileId !== profile.id) return null;
    return draft;
  },

  getBoundaryCaptureTarget() {
    const candidates = [
      ...(Array.isArray(this.state.targets) ? this.state.targets : []),
      ...(Array.isArray(this.state.rawTargets) ? this.state.rawTargets : [])
    ].filter((target) => this.hasCoordinates(target));

    if (!candidates.length) return null;

    return [...candidates].sort((left, right) => (
      Number(right?.confidence ?? 0) - Number(left?.confidence ?? 0)
      || Number(right?.distance ?? 0) - Number(left?.distance ?? 0)
    ))[0];
  },

  getBoundarySegmentLengthCm(fromPoint, toPoint) {
    if (!fromPoint || !toPoint) return 0;
    return Math.hypot(
      Number(toPoint.xCm || 0) - Number(fromPoint.xCm || 0),
      Number(toPoint.yCm || 0) - Number(fromPoint.yCm || 0)
    );
  },

  getBoundaryAngleDegrees(prevPoint, currentPoint, nextPoint) {
    if (!prevPoint || !currentPoint || !nextPoint) return null;
    const vectorA = {
      x: Number(prevPoint.xCm || 0) - Number(currentPoint.xCm || 0),
      y: Number(prevPoint.yCm || 0) - Number(currentPoint.yCm || 0)
    };
    const vectorB = {
      x: Number(nextPoint.xCm || 0) - Number(currentPoint.xCm || 0),
      y: Number(nextPoint.yCm || 0) - Number(currentPoint.yCm || 0)
    };
    const magnitudeA = Math.hypot(vectorA.x, vectorA.y);
    const magnitudeB = Math.hypot(vectorB.x, vectorB.y);
    if (magnitudeA < 1 || magnitudeB < 1) return null;
    const cosine = ((vectorA.x * vectorB.x) + (vectorA.y * vectorB.y)) / (magnitudeA * magnitudeB);
    return Math.acos(Math.max(-1, Math.min(1, cosine))) * (180 / Math.PI);
  },

  classifyBoundaryShape(points = []) {
    if (!Array.isArray(points) || points.length < 3) return 'polygon';
    if (points.length !== 4) return 'polygon';

    const lengths = points.map((point, index) => this.getBoundarySegmentLengthCm(point, points[(index + 1) % points.length]));
    const angles = points.map((point, index) => this.getBoundaryAngleDegrees(
      points[(index + points.length - 1) % points.length],
      point,
      points[(index + 1) % points.length]
    ));
    const hasRightAngles = angles.every((angle) => Number.isFinite(angle) && Math.abs(angle - 90) <= 18);
    const oppositeSidesMatch = (
      Math.abs(lengths[0] - lengths[2]) <= Math.max(18, Math.max(lengths[0], lengths[2]) * 0.18)
      && Math.abs(lengths[1] - lengths[3]) <= Math.max(18, Math.max(lengths[1], lengths[3]) * 0.18)
    );

    if (!hasRightAngles || !oppositeSidesMatch) {
      return 'polygon';
    }

    const minLength = Math.min(...lengths);
    const maxLength = Math.max(...lengths);
    return maxLength / Math.max(1, minLength) <= 1.12 ? 'square' : 'rectangle';
  },

  getRoomBoundaryMetrics(boundaryLike = null) {
    const points = Array.isArray(boundaryLike?.points) ? boundaryLike.points : [];
    if (!points.length) {
      return {
        pointCount: 0,
        widthCm: 0,
        depthCm: 0,
        areaCm2: 0,
        shapeType: 'polygon'
      };
    }

    const xs = points.map((point) => Number(point.xCm || 0));
    const ys = points.map((point) => Number(point.yCm || 0));
    return {
      pointCount: points.length,
      widthCm: Math.max(0, Math.max(...xs) - Math.min(...xs)),
      depthCm: Math.max(0, Math.max(...ys)),
      areaCm2: this.getPolygonAreaCm2(points),
      shapeType: this.classifyBoundaryShape(points)
    };
  },

  formatRoomBoundaryShape(shapeType) {
    const normalized = String(shapeType || 'polygon').trim().toLowerCase();
    if (normalized === 'square' || normalized === 'rectangle' || normalized === 'polygon') {
      return t(`fp2.layout.room_boundary.type.${normalized}`);
    }
    return normalized || t('fp2.layout.room_boundary.type.polygon');
  },

  buildRoomBoundaryPayload(boundaryLike, profile = this.getActiveRoomProfile()) {
    const points = Array.isArray(boundaryLike?.points)
      ? boundaryLike.points
          .map((point) => ({
            xCm: Math.round(Number(point.xCm || 0)),
            yCm: Math.max(0, Math.round(Number(point.yCm || 0)))
          }))
          .filter((point, index, list) => (
            index === 0
            || this.getBoundarySegmentLengthCm(point, list[index - 1]) >= 8
          ))
      : [];
    if (points.length < 3) return null;

    const metrics = this.getRoomBoundaryMetrics({ points });
    return {
      id: String(boundaryLike?.id || `room-boundary-${Date.now()}`),
      label: String(boundaryLike?.label || this.getRoomProfileLabel(profile) || 'Room boundary').trim() || 'Room boundary',
      shapeType: metrics.shapeType,
      source: String(boundaryLike?.source || 'corner_capture'),
      capturedAt: boundaryLike?.capturedAt || new Date().toISOString(),
      points
    };
  },

  startRoomBoundaryCapture() {
    const profile = this.getActiveRoomProfile();
    if (!profile || profile.kind !== 'fixed') return;

    const currentDraft = this.getRoomBoundaryDraft(profile);
    if (currentDraft) {
      return;
    }

    this.state.roomBoundaryDraft = {
      id: `room-boundary-draft-${Date.now()}`,
      profileId: profile.id,
      label: this.getRoomProfileLabel(profile),
      source: 'corner_capture',
      capturedAt: new Date().toISOString(),
      points: [],
      shapeType: 'polygon'
    };
    this.renderRoomProfileControls();
    this.renderAnimatedMap();
  },

  captureRoomBoundaryCorner() {
    const profile = this.getActiveRoomProfile();
    if (!profile || profile.kind !== 'fixed') return;

    const target = this.getBoundaryCaptureTarget();
    if (!target) {
      if (typeof window !== 'undefined') {
        window.alert(t('fp2.layout.room_boundary.no_target'));
      }
      return;
    }

    const draft = this.getRoomBoundaryDraft(profile) || {
      id: `room-boundary-draft-${Date.now()}`,
      profileId: profile.id,
      label: this.getRoomProfileLabel(profile),
      source: 'corner_capture',
      capturedAt: new Date().toISOString(),
      points: [],
      shapeType: 'polygon'
    };
    const nextPoint = {
      xCm: Math.round(Number(target.x || 0)),
      yCm: Math.max(0, Math.round(Number(target.y || 0)))
    };
    const previousPoint = draft.points.at(-1);
    if (previousPoint && this.getBoundarySegmentLengthCm(previousPoint, nextPoint) < 10) {
      return;
    }

    const nextPoints = [...draft.points, nextPoint];
    const metrics = this.getRoomBoundaryMetrics({ points: nextPoints });
    this.state.roomBoundaryDraft = {
      ...draft,
      capturedAt: new Date().toISOString(),
      points: nextPoints,
      shapeType: metrics.shapeType
    };
    this.renderRoomProfileControls();
    this.renderAnimatedMap();
  },

  undoRoomBoundaryCorner() {
    const profile = this.getActiveRoomProfile();
    const draft = this.getRoomBoundaryDraft(profile);
    if (!draft) return;
    const nextPoints = draft.points.slice(0, -1);
    this.state.roomBoundaryDraft = {
      ...draft,
      points: nextPoints,
      shapeType: this.classifyBoundaryShape(nextPoints)
    };
    if (!nextPoints.length) {
      this.state.roomBoundaryDraft = {
        ...this.state.roomBoundaryDraft,
        capturedAt: new Date().toISOString()
      };
    }
    this.renderRoomProfileControls();
    this.renderAnimatedMap();
  },

  clearRoomBoundary() {
    const profile = this.getActiveRoomProfile();
    if (!profile || profile.kind !== 'fixed') return;
    if (typeof window !== 'undefined') {
      const hasStoredBoundary = Boolean(this.getStoredRoomBoundary(profile));
      const message = hasStoredBoundary
        ? t('fp2.layout.room_boundary.clear_confirm', { name: this.getRoomProfileLabel(profile) })
        : t('fp2.layout.room_boundary.clear_draft_confirm');
      const confirmed = window.confirm(message);
      if (!confirmed) return;
    }
    this.state.roomBoundaryDraft = null;
    this.setActiveRoomBoundary(null, profile);
  },

  captureCalibrationPoint(kind) {
    const profile = this.getActiveRoomProfile();
    if (!profile || profile.kind !== 'fixed') return;

    const target = this.getCalibrationCaptureTarget();
    if (!target) {
      if (typeof window !== 'undefined') {
        window.alert(t('fp2.calibration.no_target'));
      }
      return;
    }

    const currentDraft = this.getCalibrationDraft(profile);
    const nextDraft = {
      ...currentDraft,
      capturedAt: new Date().toISOString()
    };

    if (kind === 'leftX') nextDraft.leftX = Number(target.x);
    if (kind === 'rightX') nextDraft.rightX = Number(target.x);
    if (kind === 'farY') nextDraft.farY = Number(target.y);

    this.state.roomProfileCalibrationDrafts = {
      ...this.state.roomProfileCalibrationDrafts,
      [profile.id]: nextDraft
    };

    this.renderRoomProfileControls();
    this.renderAnimatedMap();
  },

  applyCalibrationDraft() {
    const profile = this.getActiveRoomProfile();
    if (!profile || profile.kind !== 'fixed' || !this.canApplyCalibrationDraft(profile)) return;

    const draft = this.getCalibrationDraft(profile);
    this.state.roomProfileCalibration = {
      ...this.state.roomProfileCalibration,
      [profile.id]: draft
    };
    persistRoomProfileCalibration(this.state.roomProfileCalibration);
    this.renderRoomProfileControls();
    this.renderCurrent(this.lastCurrentData);
    this.scheduleRoomConfigSave();
  },

  resetCalibrationForActiveProfile() {
    const profile = this.getActiveRoomProfile();
    if (!profile || profile.kind !== 'fixed') return;

    const nextCalibration = { ...this.state.roomProfileCalibration };
    const nextDrafts = { ...this.state.roomProfileCalibrationDrafts };
    delete nextCalibration[profile.id];
    delete nextDrafts[profile.id];
    this.state.roomProfileCalibration = nextCalibration;
    this.state.roomProfileCalibrationDrafts = nextDrafts;
    persistRoomProfileCalibration(this.state.roomProfileCalibration);
    this.renderRoomProfileControls();
    this.renderCurrent(this.lastCurrentData);
    this.scheduleRoomConfigSave();
  },

  estimateRoomProfileDefaults() {
    const activeBoundary = this.getActiveRoomBoundary();
    if (activeBoundary) {
      const metrics = this.getRoomBoundaryMetrics(activeBoundary);
      if (metrics.widthCm >= 100 && metrics.depthCm >= 100) {
        return {
          widthCm: Math.ceil(metrics.widthCm / 10) * 10,
          depthCm: Math.ceil(metrics.depthCm / 10) * 10
        };
      }
    }

    const points = [];
    this.state.trailHistory.forEach(snapshot => {
      snapshot.targets.forEach(target => points.push(target));
    });
    this.state.targets.forEach(target => {
      if (this.hasCoordinates(target)) {
        points.push({ x: target.x, y: target.y });
      }
    });

    if (points.length === 0) {
      const activeProfile = this.getActiveRoomProfile();
      if (activeProfile?.kind === 'fixed') {
        return {
          widthCm: activeProfile.widthCm,
          depthCm: activeProfile.depthCm
        };
      }
      return { widthCm: 420, depthCm: 500 };
    }

    const xs = points.map(point => Number(point.x) || 0);
    const ys = points.map(point => Number(point.y) || 0);
    const halfWidth = Math.max(Math.abs(Math.min(...xs)), Math.abs(Math.max(...xs)), 140);
    const depth = Math.max(...ys, 260);

    return {
      widthCm: Math.ceil((halfWidth * 2 + 120) / 10) * 10,
      depthCm: Math.ceil((depth + 100) / 10) * 10
    };
  },

  handleSaveRoomProfile() {
    if (typeof window === 'undefined') return;

    const defaults = this.estimateRoomProfileDefaults();
    const activeProfile = this.getActiveRoomProfile();
    const boundaryDraft = this.getRoomBoundaryDraft(activeProfile);
    if (boundaryDraft && (boundaryDraft.points || []).length > 0 && (boundaryDraft.points || []).length < 3) {
      window.alert(t('fp2.layout.room_boundary.need_points'));
      return;
    }
    const activeBoundary = this.buildRoomBoundaryPayload(this.getActiveRoomBoundary(activeProfile), activeProfile);
    const activeLayoutItems = this.getActiveRoomLayoutItems(activeProfile);
    const activeStructures = this.getActiveRoomStructuralAreas(activeProfile);
    const activeWalkableAreas = this.getActiveRoomWalkableAreas(activeProfile);
    const suggestedName = activeProfile && !activeProfile.builtin
      ? activeProfile.name
      : (this.state.device?.room && this.state.device.room !== '-'
        ? this.state.device.room
        : t('fp2.layout.custom_default'));

    const name = window.prompt(t('fp2.layout.prompt_name'), suggestedName);
    if (name === null) return;
    const trimmedName = name.trim();
    if (!trimmedName) return;

    let widthCm = defaults.widthCm;
    let depthCm = defaults.depthCm;
    if (!activeBoundary) {
      const widthInput = window.prompt(t('fp2.layout.prompt_width'), String(defaults.widthCm));
      if (widthInput === null) return;
      const depthInput = window.prompt(t('fp2.layout.prompt_depth'), String(defaults.depthCm));
      if (depthInput === null) return;
      widthCm = this.parseLengthToCm(widthInput, { assumeMetersBelow: 15 });
      depthCm = this.parseLengthToCm(depthInput, { assumeMetersBelow: 30 });
    }
    if (!Number.isFinite(widthCm) || !Number.isFinite(depthCm) || widthCm < 100 || depthCm < 100) {
      window.alert(t('fp2.layout.invalid_size'));
      return;
    }

    const existing = this.state.customRoomProfiles.find(profile => profile.name.toLowerCase() === trimmedName.toLowerCase());
    const profile = {
      id: existing?.id || `custom-${Date.now()}`,
      kind: 'fixed',
      name: trimmedName,
      widthCm: Math.round(widthCm),
      depthCm: Math.round(depthCm),
      accent: existing?.accent || '#22d3ee',
      defaultAntiAnimalFilterEnabled: existing?.defaultAntiAnimalFilterEnabled ?? this.isAnimalFilterEnabled(activeProfile)
    };

    this.state.customRoomProfiles = existing
      ? this.state.customRoomProfiles.map(item => item.id === existing.id ? profile : item)
      : [...this.state.customRoomProfiles, profile];
    this.state.roomProfiles = buildRoomProfiles(this.state.customRoomProfiles);
    persistRoomProfiles(this.state.customRoomProfiles);
    const draft = this.getCalibrationDraft(activeProfile);
    if (draft && (Number.isFinite(draft.leftX) || Number.isFinite(draft.rightX) || Number.isFinite(draft.farY))) {
      this.state.roomProfileCalibration = {
        ...this.state.roomProfileCalibration,
        [profile.id]: draft
      };
      persistRoomProfileCalibration(this.state.roomProfileCalibration);
    }
    if (activeBoundary) {
      this.state.roomProfileBoundaries = {
        ...this.state.roomProfileBoundaries,
        [profile.id]: {
          ...activeBoundary,
          id: `${profile.id}-${activeBoundary.id}`
        }
      };
      persistRoomProfileBoundaries(this.state.roomProfileBoundaries);
    }
    if (activeLayoutItems.length > 0) {
      this.state.roomProfileLayouts = {
        ...this.state.roomProfileLayouts,
        [profile.id]: activeLayoutItems.map((item) => ({ ...item, id: `${profile.id}-${item.type}-${item.id}` }))
      };
      persistRoomProfileLayouts(this.state.roomProfileLayouts);
    }
    if (activeStructures.length > 0) {
      this.state.roomProfileStructuralAreas = {
        ...this.state.roomProfileStructuralAreas,
        [profile.id]: activeStructures.map((area) => this.cloneStructuralArea(area, {
          id: `${profile.id}-${area.id}`
        })).filter(Boolean)
      };
      persistRoomProfileStructuralAreas(this.state.roomProfileStructuralAreas);
    }
    if (activeWalkableAreas.length > 0) {
      this.state.roomProfileWalkableAreas = {
        ...this.state.roomProfileWalkableAreas,
        [profile.id]: activeWalkableAreas.map((area) => ({
          ...area,
          points: (area.points || []).map((point) => ({ ...point }))
        }))
      };
      persistRoomProfileWalkableAreas(this.state.roomProfileWalkableAreas);
    }
    this.state.roomBoundaryDraft = null;
    this.setActiveRoomProfile(profile.id);
    this.scheduleRoomConfigSave({ immediate: true });
  },

  handleDeleteRoomProfile() {
    const activeProfile = this.getActiveRoomProfile();
    if (!activeProfile || activeProfile.builtin || typeof window === 'undefined') return;

    const confirmed = window.confirm(t('fp2.layout.delete_confirm', {
      name: this.getRoomProfileLabel(activeProfile)
    }));
    if (!confirmed) return;

    this.state.customRoomProfiles = this.state.customRoomProfiles.filter(profile => profile.id !== activeProfile.id);
    this.state.roomProfiles = buildRoomProfiles(this.state.customRoomProfiles);
    const nextFilters = { ...this.state.roomProfileFilters };
    const nextCalibration = { ...this.state.roomProfileCalibration };
    const nextBoundaries = { ...this.state.roomProfileBoundaries };
    const nextLayouts = { ...this.state.roomProfileLayouts };
    const nextStructures = { ...this.state.roomProfileStructuralAreas };
    const nextWalkableAreas = { ...this.state.roomProfileWalkableAreas };
    delete nextFilters[activeProfile.id];
    delete nextCalibration[activeProfile.id];
    delete nextBoundaries[activeProfile.id];
    delete nextLayouts[activeProfile.id];
    delete nextStructures[activeProfile.id];
    delete nextWalkableAreas[activeProfile.id];
    this.state.roomProfileFilters = nextFilters;
    this.state.roomProfileCalibration = nextCalibration;
    this.state.roomProfileBoundaries = nextBoundaries;
    this.state.roomProfileLayouts = nextLayouts;
    this.state.roomProfileStructuralAreas = nextStructures;
    this.state.roomProfileWalkableAreas = nextWalkableAreas;
    persistRoomProfiles(this.state.customRoomProfiles);
    persistRoomProfileFilters(this.state.roomProfileFilters);
    persistRoomProfileCalibration(this.state.roomProfileCalibration);
    persistRoomProfileBoundaries(this.state.roomProfileBoundaries);
    persistRoomProfileLayouts(this.state.roomProfileLayouts);
    persistRoomProfileStructuralAreas(this.state.roomProfileStructuralAreas);
    persistRoomProfileWalkableAreas(this.state.roomProfileWalkableAreas);
    this.setActiveRoomProfile(DEFAULT_ROOM_PROFILE_ID);
    this.scheduleRoomConfigSave({ immediate: true });
  },

  handleApplyRoomTemplate() {
    const activeProfile = this.getActiveRoomProfile();
    const geometry = this.getActiveRoomGeometry(activeProfile);
    const template = this.getSelectedRoomTemplate();
    if (!activeProfile || activeProfile.kind !== 'fixed' || !geometry || !template) return;
    const items = this.materializeTemplateItems(template, geometry);
    const structures = this.materializeTemplateStructures(template, geometry);
    this.setActiveRoomLayoutItems(items, activeProfile);
    this.setActiveRoomStructuralAreas(structures, activeProfile);
  },

  handleSaveRoomTemplate() {
    const activeProfile = this.getActiveRoomProfile();
    const geometry = this.getActiveRoomGeometry(activeProfile);
    const items = this.getActiveRoomLayoutItems(activeProfile);
    const structures = this.getActiveRoomStructuralAreas(activeProfile);
    if (!activeProfile || activeProfile.kind !== 'fixed' || !geometry || typeof window === 'undefined') return;

    const suggestedName = activeProfile.name || this.getRoomProfileLabel(activeProfile);
    const name = window.prompt(t('fp2.layout.template_prompt_name'), suggestedName);
    if (name === null) return;
    const trimmedName = name.trim();
    if (!trimmedName) return;

    const existing = this.state.customRoomTemplates.find((template) => template.name.toLowerCase() === trimmedName.toLowerCase());
    const template = {
      id: existing?.id || `layout-template-${Date.now()}`,
      name: trimmedName,
      items: this.serializeLayoutItemsAsTemplate(items, geometry),
      structures: this.serializeStructuralAreasAsTemplate(structures, geometry)
    };

    this.state.customRoomTemplates = existing
      ? this.state.customRoomTemplates.map((item) => item.id === existing.id ? template : item)
      : [...this.state.customRoomTemplates, template];
    this.state.roomTemplates = buildRoomTemplates(this.state.customRoomTemplates);
    this.state.selectedRoomTemplateId = template.id;
    persistRoomTemplates(this.state.customRoomTemplates);
    this.renderRoomProfileControls();
    this.scheduleRoomConfigSave({ immediate: true });
  },

  getSuggestedRoomItemPosition(geometry) {
    const liveTarget = (this.state.targets || []).find((target) => this.hasCoordinates(target));
    if (liveTarget) {
      return {
        x: liveTarget.x,
        y: liveTarget.y
      };
    }
    return {
      x: Math.round((geometry.minX + geometry.maxX) / 2),
      y: Math.round(geometry.minY + (geometry.maxY - geometry.minY) * 0.35)
    };
  },

  handleAddRoomItem(type = null) {
    const activeProfile = this.getActiveRoomProfile();
    const geometry = this.getActiveRoomGeometry(activeProfile);
    if (!activeProfile || activeProfile.kind !== 'fixed' || !geometry) return;

    const existingCount = this.getActiveRoomLayoutItems(activeProfile).length;
    const def = type
      ? BUILTIN_ROOM_ITEM_LIBRARY.find((item) => item.type === type)
      : null;
    const chosen = def || BUILTIN_ROOM_ITEM_LIBRARY[0];
    if (!chosen) return;

    const position = this.getSuggestedRoomItemPosition(geometry);
    const item = this.clampRoomItemToGeometry({
      id: `${chosen.type}-${Date.now()}`,
      type: chosen.type,
      x: position.x + (((existingCount % 3) - 1) * 40),
      y: position.y + (Math.floor(existingCount / 3) * 30),
      widthCm: chosen.widthCm,
      depthCm: chosen.depthCm,
      rotationDeg: 0
    }, geometry);

    this.setActiveRoomLayoutItems([
      ...this.getActiveRoomLayoutItems(activeProfile),
      item
    ], activeProfile);
    this.setSelectedRoomItem(item.id);
    this.toggleEditLayoutMode(true);
  },

  handleClearRoomItems() {
    const activeProfile = this.getActiveRoomProfile();
    if (!activeProfile || activeProfile.kind !== 'fixed' || typeof window === 'undefined') return;
    const confirmed = window.confirm(t('fp2.layout.template_clear_confirm', {
      name: this.getRoomProfileLabel(activeProfile)
    }));
    if (!confirmed) return;
    this.state.selectedRoomItemId = null;
    this.state.roomItemInteraction = null;
    this.setActiveRoomLayoutItems([], activeProfile);
    this.scheduleRoomConfigSave({ immediate: true });
  },

  handleRemoveRoomItem(itemId) {
    const activeProfile = this.getActiveRoomProfile();
    if (!activeProfile) return;
    if (this.state.selectedRoomItemId === itemId) {
      this.state.roomItemInteraction = null;
      this.state.selectedRoomItemId = null;
    }
    this.setActiveRoomLayoutItems(
      this.getActiveRoomLayoutItems(activeProfile).filter((item) => item.id !== itemId),
      activeProfile
    );
    this.scheduleRoomConfigSave({ immediate: true });
  },

  handleSelectedRoomItemInput() {
    const activeProfile = this.getActiveRoomProfile();
    const geometry = this.getActiveRoomGeometry(activeProfile);
    const selected = this.getSelectedRoomItem(activeProfile);
    if (!activeProfile || !geometry || !selected) return;

    this.updateRoomItem(selected.id, {
      x: Number(this.elements.roomItemX?.value ?? selected.x),
      y: Number(this.elements.roomItemY?.value ?? selected.y),
      widthCm: Number(this.elements.roomItemWidth?.value ?? selected.widthCm),
      depthCm: Number(this.elements.roomItemDepth?.value ?? selected.depthCm),
      rotationDeg: Number(this.elements.roomItemRotation?.value ?? selected.rotationDeg ?? 0)
    }, activeProfile);
  },

  updateRoomItem(itemId, patch, profile = this.getActiveRoomProfile()) {
    const geometry = this.getActiveRoomGeometry(profile);
    if (!profile || !geometry) return;
    const nextItems = this.getActiveRoomLayoutItems(profile).map((item) => item.id === itemId
      ? this.clampRoomItemToGeometry({ ...item, ...patch }, geometry)
      : item);
    this.setActiveRoomLayoutItems(nextItems, profile);
    this.state.selectedRoomItemId = itemId;
  },

  rotateRoomItem(itemId, deltaDeg, profile = this.getActiveRoomProfile()) {
    const selected = this.getActiveRoomLayoutItems(profile).find((item) => item.id === itemId);
    if (!selected) return;
    const nextRotation = (((Number(selected.rotationDeg || 0) + deltaDeg) % 360) + 360) % 360;
    this.updateRoomItem(itemId, { rotationDeg: nextRotation }, profile);
  },

  getCanvasPoint(event) {
    const canvas = this.elements.movementCanvas;
    if (!canvas) return null;
    const rect = canvas.getBoundingClientRect();
    return {
      // Canvas drawing uses CSS pixel coordinates after prepareCanvasForDrawing()
      // sets a DPR transform on the 2D context, so hit-testing must stay in the
      // same CSS space as roomRect/toCanvasX/toCanvasY.
      x: event.clientX - rect.left,
      y: event.clientY - rect.top
    };
  },

  canvasToRoom(point, projection) {
    if (!projection || !point) return null;
    return {
      x: projection.minX + ((point.x - projection.roomRect.x) / Math.max(1, projection.roomRect.width)) * (projection.maxX - projection.minX),
      y: projection.maxY - ((point.y - projection.roomRect.y) / Math.max(1, projection.roomRect.height)) * (projection.maxY - projection.minY)
    };
  },

  getRoomItemCanvasBoxes(projection, profile = this.getActiveRoomProfile()) {
    const items = this.getActiveRoomLayoutItems(profile);
    const scaleX = projection.roomRect.width / Math.max(1, projection.widthCm);
    const scaleY = projection.roomRect.height / Math.max(1, projection.depthCm);
    return items.map((item) => {
      const cx = projection.toCanvasX(item.x);
      const cy = projection.toCanvasY(item.y);
      const width = Math.max(10, item.widthCm * scaleX);
      const depth = Math.max(10, item.depthCm * scaleY);
      return {
        item,
        x: cx - width / 2,
        y: cy - depth / 2,
        width,
        height: depth,
        resizeHandle: {
          x: cx + width / 2 - 12,
          y: cy + depth / 2 - 12,
          size: 16
        }
      };
    });
  },

  getRoomStructureCanvasPolygons(projection, profile = this.getActiveRoomProfile()) {
    return this.getActiveRoomStructuralAreas(profile).map((area) => {
      const roomPoints = this.getStructuralAreaPoints(area);
      return {
        area,
        roomPoints,
        canvasPoints: roomPoints.map((point) => ({
          x: projection.toCanvasX(point.xCm),
          y: projection.toCanvasY(point.yCm)
        })),
        editCanvasPoints: this.getStructureCanvasEditPoints(area, projection)
      };
    }).filter((entry) => entry.canvasPoints.length >= 3);
  },

  isPointInsidePolygon(point, polygon = []) {
    if (!point || !Array.isArray(polygon) || polygon.length < 3) return false;
    let inside = false;
    for (let i = 0, j = polygon.length - 1; i < polygon.length; j = i++) {
      const xi = Number(polygon[i].xCm ?? polygon[i].x);
      const yi = Number(polygon[i].yCm ?? polygon[i].y);
      const xj = Number(polygon[j].xCm ?? polygon[j].x);
      const yj = Number(polygon[j].yCm ?? polygon[j].y);
      const denominator = (yj - yi) || 1e-6;
      const intersects = ((yi > point.yCm) !== (yj > point.yCm))
        && (point.xCm < ((xj - xi) * (point.yCm - yi)) / denominator + xi);
      if (intersects) inside = !inside;
    }
    return inside;
  },

  getDistanceToCanvasSegment(point, start, end) {
    if (!point || !start || !end) return Number.POSITIVE_INFINITY;
    const dx = Number(end.x) - Number(start.x);
    const dy = Number(end.y) - Number(start.y);
    if (Math.abs(dx) < 1e-6 && Math.abs(dy) < 1e-6) {
      return Math.hypot(Number(point.x) - Number(start.x), Number(point.y) - Number(start.y));
    }
    const rawProjection = (
      ((Number(point.x) - Number(start.x)) * dx)
      + ((Number(point.y) - Number(start.y)) * dy)
    ) / ((dx * dx) + (dy * dy));
    const clampedProjection = Math.max(0, Math.min(1, rawProjection));
    const projectedX = Number(start.x) + dx * clampedProjection;
    const projectedY = Number(start.y) + dy * clampedProjection;
    return Math.hypot(Number(point.x) - projectedX, Number(point.y) - projectedY);
  },

  getDistanceToCanvasPolygonEdges(point, polygon = []) {
    if (!point || !Array.isArray(polygon) || polygon.length < 2) {
      return Number.POSITIVE_INFINITY;
    }
    let bestDistance = Number.POSITIVE_INFINITY;
    for (let index = 0; index < polygon.length; index += 1) {
      const start = polygon[index];
      const end = polygon[(index + 1) % polygon.length];
      bestDistance = Math.min(bestDistance, this.getDistanceToCanvasSegment(point, start, end));
    }
    return bestDistance;
  },

  findStructureVertexHit(point, polygons = [], radiusPx = 12) {
    let bestHit = null;
    [...polygons].reverse().forEach((entry) => {
      (entry.editCanvasPoints || []).forEach((vertex, vertexIndex) => {
        const distance = Math.hypot(Number(point.x) - Number(vertex.x), Number(point.y) - Number(vertex.y));
        if (distance > radiusPx) return;
        if (!bestHit || distance < bestHit.distance) {
          bestHit = {
            area: entry.area,
            vertexIndex,
            distance
          };
        }
      });
    });
    return bestHit;
  },

  findRoomStructureHit(point, roomPoint, polygons = []) {
    let bestHit = null;
    [...polygons].reverse().forEach((entry) => {
      const isWall = this.isWallStructure(entry.area);
      const inside = this.isPointInsidePolygon(roomPoint, entry.roomPoints || []);
      const edgeDistance = this.getDistanceToCanvasPolygonEdges(point, entry.canvasPoints || []);
      const segmentDistance = isWall
        ? this.getDistanceToCanvasSegment(
            point,
            entry.editCanvasPoints?.[0],
            entry.editCanvasPoints?.[1]
          )
        : Number.POSITIVE_INFINITY;
      const threshold = isWall ? 18 : 12;
      const score = inside ? 0 : Math.min(edgeDistance, segmentDistance);
      if (!inside && score > threshold) return;
      if (!bestHit || score < bestHit.score) {
        bestHit = {
          area: entry.area,
          score
        };
      }
    });
    return bestHit;
  },

  drawRoomStructuralAreas(ctx, projection, areas = []) {
    if (!projection || !Array.isArray(areas) || !areas.length) return;
    const { roomRect } = projection;

    ctx.save();
    ctx.beginPath();
    this.drawRoundedRect(ctx, roomRect.x, roomRect.y, roomRect.width, roomRect.height, 18);
    ctx.clip();

    areas.forEach((area) => {
      const roomPoints = this.getStructuralAreaPoints(area);
      const canvasPoints = roomPoints.map((point) => ({
        x: projection.toCanvasX(point.xCm),
        y: projection.toCanvasY(point.yCm)
      }));
      if (canvasPoints.length < 3) return;
      const isSelected = area.id === this.state.selectedRoomStructureId;
      const editCanvasPoints = this.getStructureCanvasEditPoints(area, projection);

      ctx.beginPath();
      canvasPoints.forEach((point, index) => {
        if (index === 0) ctx.moveTo(point.x, point.y);
        else ctx.lineTo(point.x, point.y);
      });
      ctx.closePath();
      ctx.fillStyle = area.fill || 'rgba(71, 85, 105, 0.22)';
      ctx.fill();
      ctx.strokeStyle = isSelected ? '#f8fafc' : (area.stroke || 'rgba(148, 163, 184, 0.92)');
      ctx.lineWidth = isSelected ? 2.4 : 1.7;
      ctx.setLineDash(isSelected ? [10, 6] : [6, 5]);
      ctx.stroke();
      ctx.setLineDash([]);

      if (this.state.editLayoutMode || isSelected) {
        editCanvasPoints.forEach((point) => {
          ctx.beginPath();
          ctx.arc(point.x, point.y, isSelected ? 5 : 4, 0, Math.PI * 2);
          ctx.fillStyle = isSelected ? '#f8fafc' : 'rgba(203, 213, 225, 0.95)';
          ctx.fill();
          ctx.strokeStyle = 'rgba(15, 23, 42, 0.96)';
          ctx.lineWidth = 1.25;
          ctx.stroke();
        });
      }

      const centroid = this.getRoomStructureCentroid(area);
      if (centroid?.xCm !== undefined && centroid?.yCm !== undefined) {
        this.drawCanvasTag(
          ctx,
          projection.toCanvasX(centroid.xCm),
          projection.toCanvasY(centroid.yCm) - 16,
          area.label,
          {
            bounds: {
              left: roomRect.x + 12,
              top: roomRect.y + 12,
              right: roomRect.x + roomRect.width - 12,
              bottom: roomRect.y + roomRect.height - 12
            },
            maxWidth: Math.min(220, roomRect.width * 0.5),
            background: isSelected ? 'rgba(8, 15, 28, 0.92)' : 'rgba(8, 15, 28, 0.82)',
            border: isSelected ? 'rgba(248, 250, 252, 0.32)' : 'rgba(148, 163, 184, 0.22)'
          }
        );
      }
    });

    ctx.restore();
  },

  drawRoomStructureDraft(ctx, projection, draft) {
    const points = Array.isArray(draft?.points) ? draft.points : [];
    if (!projection || !points.length) return;
    const isWall = this.isWallStructure(draft);
    const outlinePoints = isWall ? this.getStructuralAreaPoints(draft) : points;
    const canvasPoints = outlinePoints.map((point) => ({
      x: projection.toCanvasX(point.xCm),
      y: projection.toCanvasY(point.yCm)
    }));
    const editPoints = this.getStructureCanvasEditPoints(draft, projection);

    ctx.save();
    ctx.strokeStyle = 'rgba(251, 191, 36, 0.95)';
    ctx.fillStyle = 'rgba(251, 191, 36, 0.18)';
    ctx.lineWidth = 2;
    ctx.setLineDash([8, 6]);
    if (canvasPoints.length) {
      ctx.beginPath();
      canvasPoints.forEach((point, index) => {
        if (index === 0) ctx.moveTo(point.x, point.y);
        else ctx.lineTo(point.x, point.y);
      });
      if (canvasPoints.length >= 3) {
        ctx.closePath();
        ctx.fill();
      }
      ctx.stroke();
    }
    ctx.setLineDash([]);
    editPoints.forEach((point, index) => {
      ctx.beginPath();
      ctx.arc(point.x, point.y, index === editPoints.length - 1 ? 5 : 4, 0, Math.PI * 2);
      ctx.fillStyle = '#fbbf24';
      ctx.fill();
      ctx.strokeStyle = 'rgba(15, 23, 42, 0.96)';
      ctx.lineWidth = 1.2;
      ctx.stroke();
    });
    ctx.restore();
  },

  drawRoomWalkableAreas(ctx, projection, areas) {
    if (!projection || !Array.isArray(areas) || !areas.length) return;
    const { roomRect, minX, maxX, minY, maxY, toCanvasX, toCanvasY } = projection;
    const widthCm = Math.max(1, maxX - minX);
    const depthCm = Math.max(1, maxY - minY);

    ctx.save();
    ctx.beginPath();
    this.drawRoundedRect(ctx, roomRect.x, roomRect.y, roomRect.width, roomRect.height, 18);
    ctx.clip();

    areas.forEach((area) => {
      const points = Array.isArray(area.points) ? area.points : [];
      if (points.length < 3) return;
      const materialized = points.map((point) => ({
        x: minX + point.nx * widthCm,
        y: minY + point.ny * depthCm
      }));
      const centroid = materialized.reduce(
        (acc, point) => ({ x: acc.x + point.x, y: acc.y + point.y }),
        { x: 0, y: 0 }
      );
      centroid.x /= materialized.length;
      centroid.y /= materialized.length;

      ctx.beginPath();
      materialized.forEach((point, index) => {
        const px = toCanvasX(point.x);
        const py = toCanvasY(point.y);
        if (index === 0) ctx.moveTo(px, py);
        else ctx.lineTo(px, py);
      });
      ctx.closePath();
      ctx.fillStyle = area.fill || 'rgba(96, 165, 250, 0.20)';
      ctx.fill();
      ctx.strokeStyle = area.stroke || 'rgba(59, 130, 246, 0.92)';
      ctx.lineWidth = 2;
      ctx.setLineDash([8, 6]);
      ctx.stroke();
      ctx.setLineDash([]);

      const label = String(area.label || '').trim();
      if (label) {
        this.drawCanvasTag(ctx, toCanvasX(centroid.x), toCanvasY(centroid.y), label, {
          bounds: {
            left: roomRect.x + 12,
            top: roomRect.y + 12,
            right: roomRect.x + roomRect.width - 12,
            bottom: roomRect.y + roomRect.height - 12
          },
          maxWidth: Math.min(220, roomRect.width * 0.4),
          font: '700 12px Inter, system-ui, sans-serif',
          background: 'rgba(15, 23, 42, 0.82)',
          border: 'rgba(191, 219, 254, 0.34)',
          textColor: '#eff6ff'
        });
      }
    });

    ctx.restore();
  },

  handleCanvasPointerDown(event) {
    const activeProfile = this.getActiveRoomProfile();
    const projection = this.state.lastRoomProjection;
    if (!activeProfile || activeProfile.kind !== 'fixed' || !projection) return;
    const canEditLayout = Boolean(this.state.editLayoutMode);
    const point = this.getCanvasPoint(event);
    if (!point) return;
    const { roomRect } = projection;
    if (
      point.x < roomRect.x
      || point.x > roomRect.x + roomRect.width
      || point.y < roomRect.y
      || point.y > roomRect.y + roomRect.height
    ) {
      return;
    }
    const roomPoint = this.canvasToRoom(point, projection);
    if (!roomPoint) return;
    const geometry = this.getActiveRoomGeometry(activeProfile);
    const normalizedRoomPoint = this.clampRoomPointToGeometry(roomPoint, geometry);

    if (this.state.roomStructureDraft) {
      if (!canEditLayout) return;
      if (normalizedRoomPoint) {
        const draft = this.appendRoomStructureDraftPoint(normalizedRoomPoint, activeProfile);
        if (draft?.kind === 'wall' && (draft.points || []).length >= 2) {
          this.handleFinishRoomStructureDraft();
        }
      }
      return;
    }

    const polygons = this.getRoomStructureCanvasPolygons(projection, activeProfile);
    const vertexHit = this.findStructureVertexHit(point, polygons);
    if (vertexHit) {
      this.setSelectedRoomStructure(vertexHit.area.id);
      if (!canEditLayout) {
        return;
      }
      this.state.roomItemInteraction = {
        mode: 'structure-vertex',
        structureId: vertexHit.area.id,
        vertexIndex: vertexHit.vertexIndex,
        projection
      };
      return;
    }

    const boxes = this.getRoomItemCanvasBoxes(projection, activeProfile).reverse();
    for (const box of boxes) {
      const handle = box.resizeHandle;
      if (
        canEditLayout
        && point.x >= handle.x
        && point.x <= handle.x + handle.size
        && point.y >= handle.y
        && point.y <= handle.y + handle.size
      ) {
        this.setSelectedRoomItem(box.item.id);
        this.state.roomItemInteraction = { mode: 'resize', itemId: box.item.id, projection };
        return;
      }
      if (point.x >= box.x && point.x <= box.x + box.width && point.y >= box.y && point.y <= box.y + box.height) {
        this.setSelectedRoomItem(box.item.id);
        if (!canEditLayout) {
          return;
        }
        this.state.roomItemInteraction = {
          mode: 'move',
          itemId: box.item.id,
          projection,
          offsetX: roomPoint.x - box.item.x,
          offsetY: roomPoint.y - box.item.y
        };
        return;
      }
    }

    const structureHit = this.findRoomStructureHit(point, normalizedRoomPoint, polygons);
    if (structureHit) {
      this.setSelectedRoomStructure(structureHit.area.id);
      if (!canEditLayout) {
        return;
      }
      this.state.roomItemInteraction = {
        mode: 'structure-move',
        structureId: structureHit.area.id,
        projection,
        lastRoomPoint: normalizedRoomPoint
      };
      return;
    }

    this.state.selectedRoomItemId = null;
    this.state.selectedRoomStructureId = null;
    this.renderRoomProfileControls();
    this.renderAnimatedMap();
  },

  handleCanvasPointerMove(event) {
    const interaction = this.state.roomItemInteraction;
    if (!interaction) return;
    const activeProfile = this.getActiveRoomProfile();
    if (!activeProfile) return;
    const rawRoomPoint = this.canvasToRoom(this.getCanvasPoint(event), interaction.projection);
    const geometry = this.getActiveRoomGeometry(activeProfile);
    const normalizedRoomPoint = this.clampRoomPointToGeometry(rawRoomPoint, geometry);
    if (!normalizedRoomPoint) return;
    const selected = this.getSelectedRoomItem(activeProfile);
    if (interaction.mode === 'move' && selected) {
      this.updateRoomItem(selected.id, {
        x: Math.round(normalizedRoomPoint.xCm - interaction.offsetX),
        y: Math.round(normalizedRoomPoint.yCm - interaction.offsetY)
      }, activeProfile);
    } else if (interaction.mode === 'resize' && selected) {
      this.updateRoomItem(selected.id, {
        widthCm: Math.max(20, Math.round(Math.abs(normalizedRoomPoint.xCm - selected.x) * 2)),
        depthCm: Math.max(20, Math.round(Math.abs(normalizedRoomPoint.yCm - selected.y) * 2))
      }, activeProfile);
    } else if (interaction.mode === 'structure-vertex') {
      this.updateRoomStructureVertex(
        interaction.structureId,
        interaction.vertexIndex,
        normalizedRoomPoint,
        activeProfile
      );
    } else if (interaction.mode === 'structure-move') {
      const deltaX = Math.round(normalizedRoomPoint.xCm - Number(interaction.lastRoomPoint?.xCm || normalizedRoomPoint.xCm));
      const deltaY = Math.round(normalizedRoomPoint.yCm - Number(interaction.lastRoomPoint?.yCm || normalizedRoomPoint.yCm));
      if (!deltaX && !deltaY) {
        return;
      }
      this.moveRoomStructure(
        interaction.structureId,
        deltaX,
        deltaY,
        activeProfile
      );
      interaction.lastRoomPoint = normalizedRoomPoint;
    }
  },

  handleCanvasPointerUp() {
    this.state.roomItemInteraction = null;
  },

  handleEditorKeydown(event) {
    if (!this.isActive || !this.state.editLayoutMode) return;
    const target = event.target;
    const tagName = String(target?.tagName || '').toLowerCase();
    const isFormField = target?.isContentEditable || ['input', 'textarea', 'select'].includes(tagName);

    if (event.key === 'Escape') {
      if (this.state.roomStructureDraft) {
        event.preventDefault();
        this.cancelRoomStructureDraft();
      }
      this.state.roomItemInteraction = null;
      return;
    }

    if (event.key !== 'Delete' || isFormField) return;

    if (this.state.roomStructureDraft) {
      event.preventDefault();
      this.cancelRoomStructureDraft();
      return;
    }

    if (this.state.selectedRoomStructureId) {
      event.preventDefault();
      this.handleRemoveRoomStructure(this.state.selectedRoomStructureId);
      return;
    }

    if (this.state.selectedRoomItemId) {
      event.preventDefault();
      this.handleRemoveRoomItem(this.state.selectedRoomItemId);
    }
  },

};
