// FP2 Monitor Tab Component — Ultra Edition

import { fp2Service } from '../services/fp2.service.js?v=20260309-v4';
import { t, tp } from '../services/i18n.js?v=20260309-v22';
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
  persistRoomProfileFilters,
  persistRoomProfileLayouts,
  persistRoomProfiles,
  persistRoomTemplates,
  readStoredActiveRoomProfileId,
  readStoredRoomProfileCalibration,
  readStoredRoomProfileFilters,
  readStoredRoomProfileLayouts,
  readStoredRoomProfiles,
  readStoredRoomTemplates
} from '../services/fp2.profiles.js?v=20260309-v10';
import {
  applyTargetCountsToZones,
  classifyTargets,
  hasTargetCoordinates,
  updateTargetTrackState
} from '../services/fp2.target-filter.js?v=20260308-v2';

const RESOURCE_LABELS = {
  '3.51.85': 'fp2.resource.presence',
  '0.4.85': 'fp2.resource.light_level',
  '8.0.2026': 'fp2.resource.rssi',
  '8.0.2045': 'fp2.resource.online_state',
  '13.27.85': 'fp2.resource.movement_event',
  '4.31.85': 'fp2.resource.fall_state',
  '8.0.2116': 'fp2.resource.sensor_angle',
  '13.120.85': 'fp2.resource.area_entries_10s',
  '4.22.700': 'fp2.resource.coordinates_payload',
  '0.60.85': 'fp2.resource.realtime_people',
  '0.61.85': 'fp2.resource.visitors_1m',
  '0.63.85': 'fp2.resource.walking_distance',
  '4.71.85': 'fp2.resource.people_mode',
  '4.75.85': 'fp2.resource.distance_mode',
  '0.14.85': 'fp2.resource.respiration_confidence',
  '4.60.85': 'fp2.resource.first_network_join',
  '14.49.85': 'fp2.resource.work_mode',
  '4.22.85': 'fp2.resource.realtime_position_switch',
  '14.57.85': 'fp2.resource.installation_position',
  '13.35.85': 'fp2.resource.installation_angle_status',
  '0.9.85': 'fp2.resource.respiration_reporting',
  '1.10.85': 'fp2.resource.bed_height',
  '0.13.85': 'fp2.resource.heart_rate_confidence',
  '13.11.85': 'fp2.resource.body_movement_level',
  '4.23.85': 'fp2.resource.do_not_disturb_switch',
  '14.59.85': 'fp2.resource.fall_detection_delay',
  '14.1.85': 'fp2.resource.presence_sensitivity',
  '8.0.2032': 'fp2.resource.indicator_light',
  '1.11.85': 'fp2.resource.installation_height',
  '0.12.85': 'fp2.resource.respiration_reporting_minute',
  '14.55.85': 'fp2.resource.detection_mode',
  '14.30.85': 'fp2.resource.fall_detection_sensitivity',
  '4.66.85': 'fp2.resource.reset_absence_state',
  '14.47.85': 'fp2.resource.approach_detection_level',
  '14.58.85': 'fp2.resource.bedside_installation_position',
  '8.0.2207': 'fp2.resource.do_not_disturb_schedule'
};

const ZONE_ENTRY_RESOURCE_BASE = 120;
const ZONE_ENTRY_RESOURCE_PREFIX = /^13\.(\d+)\.85$/;
const ZONE_VISITOR_RESOURCE_PREFIX = /^0\.(\d+)\.85$/;

const MOVEMENT_LABELS = {
  0: 'fp2.movement.0',
  1: 'fp2.movement.1',
  2: 'fp2.movement.2',
  3: 'fp2.movement.3',
  4: 'fp2.movement.4',
  5: 'fp2.movement.5',
  6: 'fp2.movement.6',
  7: 'fp2.movement.7',
  8: 'fp2.movement.8',
  9: 'fp2.movement.9',
  10: 'fp2.movement.10'
};

const FALL_LABELS = {
  0: 'fp2.fall.0',
  1: 'fp2.fall.1',
  2: 'fp2.fall.2'
};

// Colors for target rendering
const TARGET_COLORS = ['#4ade80', '#38bdf8', '#f472b6', '#facc15', '#a78bfa', '#fb923c'];
const LOCAL_HISTORY_KEY = 'fp2_local_history_v1';
const LOCAL_ENTRY_KEY = 'fp2_local_presence_entries_v1';
const LOCAL_SCENARIO_KEY = 'fp2_ui_scenario_v1';

export class FP2Tab {
  constructor(containerElement) {
    this.container = containerElement;
    this.unsubscribe = null;
    this.pollTimer = null;
    this.durationTimer = null;
    this.graphAnimationId = null;
    this.languageListener = null;
    this.visibilityListener = null;
    this.lastStatus = null;
    this.lastCurrentData = null;
    this.state = {
      streamState: 'offline',
      apiEnabled: false,
      lastUpdate: null,
      history: [],
      movementHistory: [],
      currentZone: null,
      lastPresence: null,
      presenceStartedAt: null,
      sessionPeakTargets: 0,
      sessionPeakCoordinateTargets: 0,
      zones: [],
      targets: [],
      device: null,
      connection: null,
      lastMovementEvent: null,
      lastFallState: null,
      lastTargetCount: null,
      lastRealtimePeopleCount: null,
      lastVisitors1m: null,
      lastAreaEntries10s: null,
      lastWalkingDistance: null,
      currentPresenceActive: false,
      currentPresenceDerived: false,
      currentAvailability: false,
      currentSensorAngle: null,
      currentRssi: null,
      zoneMetrics: {},
      advancedMetrics: {},
      currentMovementEvent: null,
      coordinateSignature: null,
      lastCoordinateChangeAtMs: null,
      lastCoordinateSeenAtMs: null,
      coordinateGapStartedAtMs: null,
      lastCoordinateRevivedAtMs: null,
      lastCoordinateRevivedGapMs: null,
      coordinateUpdateTimestamps: [],
      coordinateHealthHistory: [],
      maxCoordinateHealthPoints: 60,
      pageVisible: typeof document === 'undefined' ? true : !document.hidden,
      pendingVisualRefresh: false,
      lastMapSignature: null,
      lastGraphDrawAtMs: 0,
      aqaraHomeRange: 'day',
      localTelemetryHistory: [],
      localPresenceEntries: [],
      customRoomProfiles: [],
      roomProfiles: [],
      customRoomTemplates: [],
      roomTemplates: [],
      roomProfileFilters: {},
      roomProfileCalibration: {},
      roomProfileCalibrationDrafts: {},
      roomProfileLayouts: {},
      editLayoutMode: false,
      activeRoomProfileId: DEFAULT_ROOM_PROFILE_ID,
      selectedRoomTemplateId: 'living_room',
      selectedRoomItemId: null,
      roomItemInteraction: null,
      coordinateEnableBusy: false,
      selectedScenarioId: null,
      scenarioBusyId: null,
      roomConfigBackendReady: false,
      roomConfigHydrating: false,
      roomConfigStorageBackend: 'unknown',
      lastRoomProjection: null,
      rawTargets: [],
      filteredTargets: [],
      targetTracks: {},
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
    this.roomConfigSaveTimer = null;
    this.renderLoopUntilMs = 0;
  }

  async init() {
    this.cacheElements();
    this.loadRoomProfiles();
    await this.syncRoomConfigWithBackend();
    this.loadLocalHistory();
    this.loadScenarioPreference();
    this.bindEvents();
    this.languageListener = () => this.handleLanguageChange();
    document.addEventListener('fp2:languagechange', this.languageListener);
    this.visibilityListener = () => this.handleVisibilityChange();
    document.addEventListener('visibilitychange', this.visibilityListener);
    this.initCanvas();
    this.initRealtimeGraph();
    this.initAqaraHomeCharts();
    this.initCoordinateQualityMonitor();
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
      homeRangeDay: this.container.querySelector('#fp2HomeRangeDay'),
      homeRangeWeek: this.container.querySelector('#fp2HomeRangeWeek'),
      homeClearHistory: this.container.querySelector('#fp2HomeClearHistory'),
      scenarioStatus: this.container.querySelector('#fp2ScenarioStatus'),
      scenarioTabs: this.container.querySelector('#fp2ScenarioTabs'),
      scenarioDetail: this.container.querySelector('#fp2ScenarioDetail'),
      homeCurrentPeople: this.container.querySelector('#fp2HomeCurrentPeople'),
      homePresenceDuration: this.container.querySelector('#fp2HomePresenceDuration'),
      homeVisitorsLabel: this.container.querySelector('#fp2HomeVisitorsLabel'),
      homeVisitorsToday: this.container.querySelector('#fp2HomeVisitorsToday'),
      homeWalkingLabel: this.container.querySelector('#fp2HomeWalkingLabel'),
      homeWalkingToday: this.container.querySelector('#fp2HomeWalkingToday'),
      homeLightNow: this.container.querySelector('#fp2HomeLightNow'),
      homePeopleChartValue: this.container.querySelector('#fp2HomePeopleChartValue'),
      homeLightChartValue: this.container.querySelector('#fp2HomeLightChartValue'),
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
      coordinateConfidence: this.container.querySelector('#fp2CoordinateConfidence'),
      coordinateUpdateRate: this.container.querySelector('#fp2CoordinateUpdateRate'),
      coordinateHealthBadge: this.container.querySelector('#fp2CoordinateHealthBadge'),
      coordinateSwitchState: this.container.querySelector('#fp2CoordinateSwitchState'),
      coordinateEnable: this.container.querySelector('#fp2CoordinateEnable'),
      coordinateCount: this.container.querySelector('#fp2CoordinateCount'),
      apiDomain: this.container.querySelector('#fp2ApiDomain'),
      primaryTargetId: this.container.querySelector('#fp2PrimaryTargetId'),
      activeTargetCount: this.container.querySelector('#fp2ActiveTargetCount'),
      coordinateTargetCount: this.container.querySelector('#fp2CoordinateTargetCount'),
      sessionPeakTargetCount: this.container.querySelector('#fp2SessionPeakTargetCount'),
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
      zoneAnalytics: this.container.querySelector('#fp2ZoneAnalytics'),
      zoneSummaryRange: this.container.querySelector('#fp2ZoneSummaryRange'),
      zoneRangeSummary: this.container.querySelector('#fp2ZoneRangeSummary'),
      // New elements
      fallAlert: this.container.querySelector('#fp2FallAlert'),
      fallAlertText: this.container.querySelector('#fp2FallAlertText'),
      fallAlertTime: this.container.querySelector('#fp2FallAlertTime'),
      rssiGauge: this.container.querySelector('#fp2RssiGauge'),
      angleDial: this.container.querySelector('#fp2AngleDial'),
      mapMode: this.container.querySelector('#fp2MapMode'),
      roomProfileSelect: this.container.querySelector('#fp2RoomProfileSelect'),
      roomProfileSave: this.container.querySelector('#fp2RoomProfileSave'),
      roomProfileDelete: this.container.querySelector('#fp2RoomProfileDelete'),
      roomProfileMeta: this.container.querySelector('#fp2RoomProfileMeta'),
      roomTemplateSelect: this.container.querySelector('#fp2RoomTemplateSelect'),
      roomTemplateApply: this.container.querySelector('#fp2RoomTemplateApply'),
      roomTemplateSave: this.container.querySelector('#fp2RoomTemplateSave'),
      roomTemplateStatus: this.container.querySelector('#fp2RoomTemplateStatus'),
      roomStorageStatus: this.container.querySelector('#fp2RoomStorageStatus'),
      roomItemLibrary: this.container.querySelector('#fp2RoomItemLibrary'),
      roomItemAdd: this.container.querySelector('#fp2RoomItemAdd'),
      roomItemsClear: this.container.querySelector('#fp2RoomItemsClear'),
      roomEditMode: this.container.querySelector('#fp2RoomEditMode'),
      roomConfigExport: this.container.querySelector('#fp2RoomConfigExport'),
      roomConfigImport: this.container.querySelector('#fp2RoomConfigImport'),
      roomConfigFile: this.container.querySelector('#fp2RoomConfigFile'),
      roomEditModeStatus: this.container.querySelector('#fp2RoomEditModeStatus'),
      roomItemsSummary: this.container.querySelector('#fp2RoomItemsSummary'),
      roomItemsList: this.container.querySelector('#fp2RoomItemsList'),
      roomItemInspector: this.container.querySelector('#fp2RoomItemInspector'),
      selectedRoomItemName: this.container.querySelector('#fp2SelectedRoomItemName'),
      selectedRoomItemRotateLeft: this.container.querySelector('#fp2SelectedRoomItemRotateLeft'),
      selectedRoomItemRotateRight: this.container.querySelector('#fp2SelectedRoomItemRotateRight'),
      selectedRoomItemDelete: this.container.querySelector('#fp2SelectedRoomItemDelete'),
      roomItemX: this.container.querySelector('#fp2RoomItemX'),
      roomItemY: this.container.querySelector('#fp2RoomItemY'),
      roomItemWidth: this.container.querySelector('#fp2RoomItemWidth'),
      roomItemDepth: this.container.querySelector('#fp2RoomItemDepth'),
      roomItemRotation: this.container.querySelector('#fp2RoomItemRotation'),
      roomItemXValue: this.container.querySelector('#fp2RoomItemXValue'),
      roomItemYValue: this.container.querySelector('#fp2RoomItemYValue'),
      roomItemWidthValue: this.container.querySelector('#fp2RoomItemWidthValue'),
      roomItemDepthValue: this.container.querySelector('#fp2RoomItemDepthValue'),
      roomItemRotationValue: this.container.querySelector('#fp2RoomItemRotationValue'),
      animalFilterToggle: this.container.querySelector('#fp2AnimalFilterToggle'),
      animalFilterStatus: this.container.querySelector('#fp2AnimalFilterStatus'),
      calibrationCaptureLeft: this.container.querySelector('#fp2CalibrationCaptureLeft'),
      calibrationCaptureRight: this.container.querySelector('#fp2CalibrationCaptureRight'),
      calibrationCaptureFar: this.container.querySelector('#fp2CalibrationCaptureFar'),
      calibrationApply: this.container.querySelector('#fp2CalibrationApply'),
      calibrationReset: this.container.querySelector('#fp2CalibrationReset'),
      calibrationStatus: this.container.querySelector('#fp2CalibrationStatus'),
      realtimePeople: this.container.querySelector('#fp2RealtimePeople'),
      visitors1m: this.container.querySelector('#fp2Visitors1m'),
      areaEntries10s: this.container.querySelector('#fp2AreaEntries10s'),
      walkingDistance: this.container.querySelector('#fp2WalkingDistance'),
      peopleMode: this.container.querySelector('#fp2PeopleMode'),
      distanceMode: this.container.querySelector('#fp2DistanceMode'),
      realtimePositionSwitch: this.container.querySelector('#fp2RealtimePositionSwitch'),
      workMode: this.container.querySelector('#fp2WorkMode'),
      detectionMode: this.container.querySelector('#fp2DetectionMode'),
      doNotDisturbSwitch: this.container.querySelector('#fp2DoNotDisturbSwitch'),
      doNotDisturbSchedule: this.container.querySelector('#fp2DoNotDisturbSchedule'),
      indicatorLight: this.container.querySelector('#fp2IndicatorLight'),
      installationPosition: this.container.querySelector('#fp2InstallationPosition'),
      installationHeight: this.container.querySelector('#fp2InstallationHeight'),
      bedHeight: this.container.querySelector('#fp2BedHeight'),
      installationAngleStatus: this.container.querySelector('#fp2InstallationAngleStatus'),
      presenceSensitivity: this.container.querySelector('#fp2PresenceSensitivity'),
      approachLevel: this.container.querySelector('#fp2ApproachLevel'),
      fallDetectionSensitivity: this.container.querySelector('#fp2FallDetectionSensitivity'),
      fallDetectionDelay: this.container.querySelector('#fp2FallDetectionDelay'),
      respirationReporting: this.container.querySelector('#fp2RespirationReporting'),
      respirationReportingMinute: this.container.querySelector('#fp2RespirationReportingMinute'),
      respirationConfidence: this.container.querySelector('#fp2RespirationConfidence'),
      heartRateConfidence: this.container.querySelector('#fp2HeartRateConfidence'),
      bodyMovementLevel: this.container.querySelector('#fp2BodyMovementLevel'),
      bedsideInstallationPosition: this.container.querySelector('#fp2BedsideInstallationPosition'),
      firstNetworkJoin: this.container.querySelector('#fp2FirstNetworkJoin'),
      resetAbsenceState: this.container.querySelector('#fp2ResetAbsenceState')
    };
  }

  bindEvents() {
    if (this.elements.refreshBtn) {
      this.elements.refreshBtn.addEventListener('click', async () => {
        await this.refreshAll();
      });
    }

    if (this.elements.homeRangeDay) {
      this.elements.homeRangeDay.addEventListener('click', () => this.setAqaraHomeRange('day'));
    }

    if (this.elements.homeRangeWeek) {
      this.elements.homeRangeWeek.addEventListener('click', () => this.setAqaraHomeRange('week'));
    }

    if (this.elements.homeClearHistory) {
      this.elements.homeClearHistory.addEventListener('click', () => this.clearLocalHistory());
    }
    if (this.elements.coordinateEnable) {
      this.elements.coordinateEnable.addEventListener('click', () => this.enableRealtimeCoordinates());
    }

    if (this.elements.scenarioTabs) {
      this.elements.scenarioTabs.addEventListener('click', (event) => {
        const button = event.target.closest('[data-scenario-select]');
        if (!button) return;
        this.setSelectedScenario(button.dataset.scenarioSelect);
      });
    }

    if (this.elements.scenarioDetail) {
      this.elements.scenarioDetail.addEventListener('click', (event) => {
        const button = event.target.closest('[data-scenario-apply]');
        if (!button) return;
        this.applyScenarioPreset(button.dataset.scenarioApply);
      });
    }

    if (this.elements.roomProfileSelect) {
      this.elements.roomProfileSelect.addEventListener('change', (event) => {
        this.setActiveRoomProfile(event.target.value);
      });
    }

    if (this.elements.roomProfileSave) {
      this.elements.roomProfileSave.addEventListener('click', () => {
        this.handleSaveRoomProfile();
      });
    }

    if (this.elements.roomProfileDelete) {
      this.elements.roomProfileDelete.addEventListener('click', () => {
        this.handleDeleteRoomProfile();
      });
    }

    if (this.elements.roomTemplateSelect) {
      this.elements.roomTemplateSelect.addEventListener('change', (event) => {
        this.state.selectedRoomTemplateId = event.target.value;
        this.renderRoomProfileControls();
        this.scheduleRoomConfigSave();
      });
    }

    if (this.elements.roomTemplateApply) {
      this.elements.roomTemplateApply.addEventListener('click', () => {
        this.handleApplyRoomTemplate();
      });
    }

    if (this.elements.roomTemplateSave) {
      this.elements.roomTemplateSave.addEventListener('click', () => {
        this.handleSaveRoomTemplate();
      });
    }

    if (this.elements.roomItemAdd) {
      this.elements.roomItemAdd.addEventListener('click', () => {
        this.handleAddRoomItem();
      });
    }

    if (this.elements.roomItemsClear) {
      this.elements.roomItemsClear.addEventListener('click', () => {
        this.handleClearRoomItems();
      });
    }

    if (this.elements.roomEditMode) {
      this.elements.roomEditMode.addEventListener('click', () => {
        this.toggleEditLayoutMode();
      });
    }

    if (this.elements.roomConfigExport) {
      this.elements.roomConfigExport.addEventListener('click', () => {
        this.exportRoomConfig();
      });
    }

    if (this.elements.roomConfigImport) {
      this.elements.roomConfigImport.addEventListener('click', () => {
        this.elements.roomConfigFile?.click();
      });
    }

    if (this.elements.roomConfigFile) {
      this.elements.roomConfigFile.addEventListener('change', async (event) => {
        const [file] = Array.from(event.target.files || []);
        event.target.value = '';
        if (!file) return;
        await this.importRoomConfig(file);
      });
    }

    if (this.elements.roomItemsList) {
      this.elements.roomItemsList.addEventListener('click', (event) => {
        const rotateLeft = event.target.closest('[data-item-rotate-left]');
        if (rotateLeft) {
          this.rotateRoomItem(rotateLeft.dataset.itemRotateLeft, -90);
          return;
        }
        const rotateRight = event.target.closest('[data-item-rotate-right]');
        if (rotateRight) {
          this.rotateRoomItem(rotateRight.dataset.itemRotateRight, 90);
          return;
        }
        const button = event.target.closest('[data-item-remove]');
        if (button) {
          this.handleRemoveRoomItem(button.dataset.itemRemove);
          return;
        }
        const select = event.target.closest('[data-item-select]');
        if (!select) return;
        this.setSelectedRoomItem(select.dataset.itemSelect);
      });
      this.elements.roomItemsList.addEventListener('keydown', (event) => {
        if (event.key !== 'Enter' && event.key !== ' ') return;
        const item = event.target.closest('[data-item-select]');
        if (!item) return;
        event.preventDefault();
        this.setSelectedRoomItem(item.dataset.itemSelect);
      });
    }

    if (this.elements.roomItemLibrary) {
      this.elements.roomItemLibrary.addEventListener('click', (event) => {
        const button = event.target.closest('[data-library-add]');
        if (!button) return;
        this.handleAddRoomItem(button.dataset.libraryAdd);
      });
    }

    if (this.elements.selectedRoomItemDelete) {
      this.elements.selectedRoomItemDelete.addEventListener('click', () => {
        if (this.state.selectedRoomItemId) {
          this.handleRemoveRoomItem(this.state.selectedRoomItemId);
        }
      });
    }

    if (this.elements.selectedRoomItemRotateLeft) {
      this.elements.selectedRoomItemRotateLeft.addEventListener('click', () => {
        if (this.state.selectedRoomItemId) {
          this.rotateRoomItem(this.state.selectedRoomItemId, -90);
        }
      });
    }

    if (this.elements.selectedRoomItemRotateRight) {
      this.elements.selectedRoomItemRotateRight.addEventListener('click', () => {
        if (this.state.selectedRoomItemId) {
          this.rotateRoomItem(this.state.selectedRoomItemId, 90);
        }
      });
    }

    ['roomItemX', 'roomItemY', 'roomItemWidth', 'roomItemDepth', 'roomItemRotation'].forEach((key) => {
      const input = this.elements[key];
      if (!input) return;
      input.addEventListener('input', () => this.handleSelectedRoomItemInput());
    });

    if (this.elements.animalFilterToggle) {
      this.elements.animalFilterToggle.addEventListener('change', (event) => {
        this.handleAnimalFilterToggle(event.target.checked);
      });
    }

    if (this.elements.calibrationCaptureLeft) {
      this.elements.calibrationCaptureLeft.addEventListener('click', () => {
        this.captureCalibrationPoint('leftX');
      });
    }

    if (this.elements.calibrationCaptureRight) {
      this.elements.calibrationCaptureRight.addEventListener('click', () => {
        this.captureCalibrationPoint('rightX');
      });
    }

    if (this.elements.calibrationCaptureFar) {
      this.elements.calibrationCaptureFar.addEventListener('click', () => {
        this.captureCalibrationPoint('farY');
      });
    }

    if (this.elements.calibrationApply) {
      this.elements.calibrationApply.addEventListener('click', () => {
        this.applyCalibrationDraft();
      });
    }

    if (this.elements.calibrationReset) {
      this.elements.calibrationReset.addEventListener('click', () => {
        this.resetCalibrationForActiveProfile();
      });
    }

    if (this.elements.movementCanvas) {
      this.elements.movementCanvas.addEventListener('mousedown', (event) => this.handleCanvasPointerDown(event));
    }
    if (typeof window !== 'undefined') {
      window.addEventListener('mousemove', (event) => this.handleCanvasPointerMove(event));
      window.addEventListener('mouseup', () => this.handleCanvasPointerUp());
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

  initAqaraHomeCharts() {
    const peopleCanvas = this.container.querySelector('#fp2HomePeopleChart');
    if (peopleCanvas) {
      this.homePeopleCanvas = peopleCanvas;
      this.homePeopleCtx = peopleCanvas.getContext('2d');
    }
    const lightCanvas = this.container.querySelector('#fp2HomeLightChart');
    if (lightCanvas) {
      this.homeLightCanvas = lightCanvas;
      this.homeLightCtx = lightCanvas.getContext('2d');
    }
    this.drawAqaraHomeCharts();
  }

  initCoordinateQualityMonitor() {
    const canvas = this.container.querySelector('#fp2CoordinateQualityCanvas');
    if (!canvas) return;
    this.coordinateQualityCanvas = canvas;
    this.coordinateQualityCtx = canvas.getContext('2d');
    this.drawCoordinateQualityGraph();
  }

  prepareCanvasForDrawing(canvas, ctx) {
    const rect = canvas.getBoundingClientRect();
    const cssWidth = Math.max(1, Math.round(rect.width || canvas.clientWidth || canvas.width || 1));
    const cssHeight = Math.max(1, Math.round(rect.height || canvas.clientHeight || canvas.height || 1));
    const dpr = typeof window !== 'undefined' ? (window.devicePixelRatio || 1) : 1;
    const pixelWidth = Math.max(1, Math.round(cssWidth * dpr));
    const pixelHeight = Math.max(1, Math.round(cssHeight * dpr));

    if (canvas.width !== pixelWidth || canvas.height !== pixelHeight) {
      canvas.width = pixelWidth;
      canvas.height = pixelHeight;
    }
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    return { width: cssWidth, height: cssHeight };
  }

  fitCanvasText(ctx, text, maxWidth) {
    const normalized = String(text ?? '');
    if (!normalized || !Number.isFinite(maxWidth) || maxWidth <= 0) return '';
    if (ctx.measureText(normalized).width <= maxWidth) return normalized;

    let trimmed = normalized;
    while (trimmed.length > 1 && ctx.measureText(`${trimmed}…`).width > maxWidth) {
      trimmed = trimmed.slice(0, -1);
    }
    return `${trimmed}…`;
  }

  drawCanvasTextBubble(ctx, x, y, lines, options = {}) {
    const visibleLines = (lines || []).filter(Boolean);
    if (!visibleLines.length) return;

    const {
      bounds = null,
      offsetX = 14,
      offsetY = -18,
      paddingX = 10,
      paddingY = 7,
      titleFont = '600 12px "SFMono-Regular", "JetBrains Mono", monospace',
      bodyFont = '11px "SFMono-Regular", "JetBrains Mono", monospace',
      background = 'rgba(8, 15, 28, 0.82)',
      border = 'rgba(148, 163, 184, 0.18)',
      titleColor = '#e2e8f0',
      bodyColor = '#94a3b8',
      radius = 10
    } = options;

    ctx.save();
    const fonts = visibleLines.map((_, index) => (index === 0 ? titleFont : bodyFont));
    const lineMetrics = visibleLines.map((line, index) => {
      ctx.font = fonts[index];
      return ctx.measureText(line).width;
    });
    const lineHeights = visibleLines.map((_, index) => (index === 0 ? 14 : 13));
    const contentWidth = Math.max(...lineMetrics);
    const boxWidth = Math.ceil(contentWidth + paddingX * 2);
    const boxHeight = Math.ceil(lineHeights.reduce((sum, value) => sum + value, 0) + paddingY * 2 + Math.max(0, visibleLines.length - 1) * 2);

    let boxX = x + offsetX;
    let boxY = y + offsetY;
    if (bounds) {
      const minX = Number.isFinite(bounds.left) ? bounds.left : 0;
      const maxX = Number.isFinite(bounds.right) ? bounds.right : boxX + boxWidth;
      const minY = Number.isFinite(bounds.top) ? bounds.top : 0;
      const maxY = Number.isFinite(bounds.bottom) ? bounds.bottom : boxY + boxHeight;
      if (boxX + boxWidth > maxX) boxX = x - boxWidth - 14;
      if (boxX < minX) boxX = minX;
      if (boxY < minY) boxY = y + 12;
      if (boxY + boxHeight > maxY) boxY = Math.max(minY, maxY - boxHeight);
    }

    this.drawRoundedRect(ctx, boxX, boxY, boxWidth, boxHeight, radius);
    ctx.fillStyle = background;
    ctx.fill();
    ctx.strokeStyle = border;
    ctx.lineWidth = 1;
    ctx.stroke();

    let cursorY = boxY + paddingY + 10;
    visibleLines.forEach((line, index) => {
      ctx.font = fonts[index];
      ctx.fillStyle = index === 0 ? titleColor : bodyColor;
      ctx.fillText(line, boxX + paddingX, cursorY);
      cursorY += lineHeights[index] + 2;
    });
    ctx.restore();
  }

  isPageVisible() {
    return typeof document === 'undefined' ? true : !document.hidden;
  }

  handleVisibilityChange() {
    this.state.pageVisible = this.isPageVisible();
    if (!this.state.pageVisible) {
      this.stopGraphAnimation();
      return;
    }
    if (!this.lastCurrentData) return;
    this.state.pendingVisualRefresh = false;
    this.drawRealtimeGraph();
    this.drawAqaraHomeCharts();
    this.drawCoordinateQualityGraph();
    this.drawRssiGauge(this.state.currentRssi);
    this.drawAngleDial(this.state.currentSensorAngle);
    this.renderAnimatedMap(true);
  }

  // ── Room Profiles ──

  loadRoomProfiles() {
    const customProfiles = readStoredRoomProfiles();
    const roomProfiles = buildRoomProfiles(customProfiles);
    const customRoomTemplates = readStoredRoomTemplates();
    const roomTemplates = buildRoomTemplates(customRoomTemplates);
    const roomProfileFilters = readStoredRoomProfileFilters();
    const roomProfileCalibration = readStoredRoomProfileCalibration();
    const roomProfileLayouts = readStoredRoomProfileLayouts();
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
    this.state.roomProfileLayouts = roomProfileLayouts;
    this.state.activeRoomProfileId = activeRoomProfileId;
    if (!roomTemplates.some((template) => template.id === this.state.selectedRoomTemplateId)) {
      this.state.selectedRoomTemplateId = roomTemplates[0]?.id || 'empty_room';
    }
    persistActiveRoomProfileId(activeRoomProfileId);
    this.renderRoomProfileControls();
  }

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
  }

  loadScenarioPreference() {
    if (typeof window === 'undefined' || !window.localStorage) {
      this.state.selectedScenarioId = 'room_presence';
      return;
    }

    const stored = window.localStorage.getItem(LOCAL_SCENARIO_KEY);
    this.state.selectedScenarioId = stored || 'room_presence';
  }

  persistScenarioPreference() {
    if (typeof window === 'undefined' || !window.localStorage) return;
    window.localStorage.setItem(LOCAL_SCENARIO_KEY, this.state.selectedScenarioId || 'room_presence');
  }

  persistLocalHistory() {
    if (typeof window === 'undefined' || !window.localStorage) return;
    window.localStorage.setItem(LOCAL_HISTORY_KEY, JSON.stringify(this.state.localTelemetryHistory || []));
    window.localStorage.setItem(LOCAL_ENTRY_KEY, JSON.stringify(this.state.localPresenceEntries || []));
  }

  hasMeaningfulRoomConfig(payload) {
    if (!payload || typeof payload !== 'object') return false;

    const nonEmptyObject = (value) => Boolean(value && typeof value === 'object' && Object.keys(value).length);

    return (
      Array.isArray(payload.customRoomProfiles) && payload.customRoomProfiles.length > 0
    ) || (
      Array.isArray(payload.customRoomTemplates) && payload.customRoomTemplates.length > 0
    ) || nonEmptyObject(payload.roomProfileFilters)
      || nonEmptyObject(payload.roomProfileCalibration)
      || nonEmptyObject(payload.roomProfileLayouts)
      || payload.activeRoomProfileId !== DEFAULT_ROOM_PROFILE_ID
      || payload.selectedRoomTemplateId !== 'living_room';
  }

  normalizeRoomConfigStorageBackend(value) {
    if (typeof value !== 'string') return 'unknown';
    const normalized = value.trim().toLowerCase();
    if (['postgresql', 'sqlite_fallback', 'file_fallback', 'unavailable'].includes(normalized)) {
      return normalized;
    }
    return 'unknown';
  }

  setRoomConfigStorageBackend(value) {
    this.state.roomConfigStorageBackend = this.normalizeRoomConfigStorageBackend(value);
  }

  getRoomConfigStorageBadgeState() {
    if (this.state.roomConfigHydrating) {
      return {
        text: t('fp2.layout.storage.syncing'),
        className: 'chip chip--warn'
      };
    }

    switch (this.state.roomConfigStorageBackend) {
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
  }

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
      persistRoomProfileLayouts(
        payload.roomProfileLayouts && typeof payload.roomProfileLayouts === 'object'
          ? payload.roomProfileLayouts
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
  }

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
  }

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
  }

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
  }

  buildRoomConfigExportPayload() {
    return {
      version: 1,
      exportedAt: new Date().toISOString(),
      customRoomProfiles: this.state.customRoomProfiles || [],
      customRoomTemplates: this.state.customRoomTemplates || [],
      roomProfileFilters: this.state.roomProfileFilters || {},
      roomProfileCalibration: this.state.roomProfileCalibration || {},
      roomProfileLayouts: this.state.roomProfileLayouts || {},
      activeRoomProfileId: this.state.activeRoomProfileId || DEFAULT_ROOM_PROFILE_ID,
      selectedRoomTemplateId: this.state.selectedRoomTemplateId || 'empty_room'
    };
  }

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
  }

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
  }

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
  }

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
  }

  inferScenarioId(resourceValues = {}) {
    if ([1, 2, 3].includes(Number(resourceValues?.['14.58.85']))) {
      return 'bedside_sleep';
    }
    if (Number(resourceValues?.['14.55.85']) === 1) {
      return 'corridor_flow';
    }
    return 'room_presence';
  }

  getSelectedScenarioPreset(resourceValues = {}) {
    const presets = this.getScenarioPresets(resourceValues);
    const currentId = this.state.selectedScenarioId || this.inferScenarioId(resourceValues);
    return presets.find((preset) => preset.id === currentId) || presets[0] || null;
  }

  resolveActiveScenarioId(resourceValues = {}) {
    return this.inferScenarioId(resourceValues);
  }

  doesScenarioMatch(preset, resourceValues = {}) {
    if (!preset) return false;
    return (preset.writes || []).every((write) => String(resourceValues?.[write.resourceId] ?? '') === String(write.value));
  }

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
  }

  formatScenarioResourceLabel(resourceId) {
    const key = RESOURCE_LABELS[resourceId];
    return key ? t(key) : resourceId;
  }

  formatScenarioWriteValue(resourceId, value) {
    if (['4.22.85', '4.71.85', '4.75.85', '4.23.85', '8.0.2032', '0.9.85', '0.12.85'].includes(resourceId)) {
      return String(value) === '1' ? t('common.enabled') : t('common.disabled');
    }
    return this.formatSettingValue(resourceId, value);
  }

  renderScenarioPresets(resourceValues = {}) {
    if (!this.elements.scenarioTabs || !this.elements.scenarioDetail || !this.elements.scenarioStatus) {
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
  }

  async applyScenarioPreset(scenarioId) {
    if (!scenarioId || this.state.scenarioBusyId) return;
    const resourceValues = this.lastCurrentData?.metadata?.raw_attributes?.resource_values || {};
    const preset = this.getScenarioPresets(resourceValues).find((item) => item.id === scenarioId);
    if (!preset || !preset.writes?.length) return;

    this.state.scenarioBusyId = scenarioId;
    this.renderScenarioPresets(resourceValues);
    try {
      const writeResult = await fp2Service.writeCloudResources(preset.writes, true);
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
  }

  setAqaraHomeRange(range) {
    this.state.aqaraHomeRange = range === 'week' ? 'week' : 'day';
    this.renderAqaraHomeOverview();
    this.renderZoneRangeSummary();
  }

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
  }

  buildZoneStateSignature(zoneIds = []) {
    return [...zoneIds].map((zoneId) => String(zoneId)).sort((left, right) => left.localeCompare(right)).join('|');
  }

  buildZoneMetricSignature(metricMap = {}) {
    return Object.entries(metricMap || {})
      .map(([zoneId, value]) => [String(zoneId), Number(value || 0)])
      .sort(([left], [right]) => left.localeCompare(right))
      .map(([zoneId, value]) => `${zoneId}:${value}`)
      .join('|');
  }

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
  }

  recordPresenceEntry(timestamp) {
    const ts = Number.isFinite(timestamp) ? timestamp : Date.now();
    this.state.localPresenceEntries = [
      ...(this.state.localPresenceEntries || []).filter((point) => ts - point <= 7 * 24 * 60 * 60 * 1000),
      ts
    ].slice(-500);
    this.persistLocalHistory();
  }

  getAqaraRangeWindow() {
    const now = Date.now();
    return this.state.aqaraHomeRange === 'week'
      ? now - 7 * 24 * 60 * 60 * 1000
      : now - 24 * 60 * 60 * 1000;
  }

  getVisitorsTodayCount() {
    const now = new Date();
    const start = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
    return (this.state.localPresenceEntries || []).filter((ts) => ts >= start).length;
  }

  getVisitorsCountForCurrentRange() {
    const startTs = this.getAqaraRangeWindow();
    return (this.state.localPresenceEntries || []).filter((ts) => ts >= startTs).length;
  }

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
  }

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
  }

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
  }

  updateAqaraHomeRangeLabels() {
    const isDay = this.state.aqaraHomeRange !== 'week';
    if (this.elements.homeVisitorsLabel) {
      this.elements.homeVisitorsLabel.textContent = t(isDay ? 'fp2.home.visitors_24h' : 'fp2.home.visitors_7d');
    }
    if (this.elements.homeWalkingLabel) {
      this.elements.homeWalkingLabel.textContent = t(isDay ? 'fp2.home.walking_24h' : 'fp2.home.walking_7d');
    }
  }

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
  }

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
  }

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
  }

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
  }

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
  }

  getActiveRoomProfile() {
    return getRoomProfileById(this.state.roomProfiles, this.state.activeRoomProfileId);
  }

  getRoomProfileLabel(profile) {
    if (!profile) return '-';
    return profile.labelKey ? t(profile.labelKey) : (profile.name || profile.id);
  }

  getRoomTemplateLabel(template) {
    if (!template) return t('fp2.layout.template_none');
    return template.labelKey ? t(template.labelKey) : (template.name || template.id);
  }

  getSelectedRoomTemplate() {
    return getRoomTemplateById(this.state.roomTemplates, this.state.selectedRoomTemplateId);
  }

  getActiveRoomLayoutItems(profile = this.getActiveRoomProfile()) {
    if (!profile) return [];
    return Array.isArray(this.state.roomProfileLayouts?.[profile.id]) ? this.state.roomProfileLayouts[profile.id] : [];
  }

  getSelectedRoomItem(profile = this.getActiveRoomProfile()) {
    if (!profile || !this.state.selectedRoomItemId) return null;
    return this.getActiveRoomLayoutItems(profile).find((item) => item.id === this.state.selectedRoomItemId) || null;
  }

  ensureSelectedRoomItem(profile = this.getActiveRoomProfile()) {
    const items = this.getActiveRoomLayoutItems(profile);
    if (!items.length) {
      this.state.selectedRoomItemId = null;
      return null;
    }
    if (!items.some((item) => item.id === this.state.selectedRoomItemId)) {
      this.state.selectedRoomItemId = items[0].id;
    }
    return this.getSelectedRoomItem(profile);
  }

  setSelectedRoomItem(itemId) {
    this.state.selectedRoomItemId = itemId || null;
    this.renderRoomProfileControls();
    this.renderAnimatedMap();
  }

  setActiveRoomLayoutItems(items, profile = this.getActiveRoomProfile()) {
    if (!profile) return;
    this.state.roomProfileLayouts = {
      ...this.state.roomProfileLayouts,
      [profile.id]: Array.isArray(items) ? items : []
    };
    persistRoomProfileLayouts(this.state.roomProfileLayouts);
    this.ensureSelectedRoomItem(profile);
    this.renderRoomProfileControls();
    this.renderAnimatedMap();
    this.scheduleRoomConfigSave();
  }

  getLayoutBounds(geometry) {
    if (!geometry) return null;
    return {
      minX: geometry.minX,
      maxX: geometry.maxX,
      minY: geometry.minY,
      maxY: geometry.maxY
    };
  }

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
  }

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
  }

  clampRoomItemToGeometry(item, geometry) {
    if (!item || !geometry) return item;
    return {
      ...item,
      x: Math.max(geometry.minX, Math.min(geometry.maxX, item.x)),
      y: Math.max(geometry.minY, Math.min(geometry.maxY, item.y)),
      widthCm: Math.max(20, Math.min(geometry.widthCm, item.widthCm)),
      depthCm: Math.max(20, Math.min(geometry.depthCm, item.depthCm))
    };
  }

  getRoomItemPromptOptions() {
    return BUILTIN_ROOM_ITEM_LIBRARY.map((item, index) => `${index + 1}. ${t(item.labelKey)}`).join('\n');
  }

  getRoomItemLabel(item) {
    const def = getRoomItemDefinition(item?.type);
    return def?.labelKey ? t(def.labelKey) : (item?.type || '-');
  }

  getRoomItemIcon(item) {
    const def = getRoomItemDefinition(item?.type);
    return def?.icon || '⬚';
  }

  toggleEditLayoutMode(forceValue = null) {
    this.state.editLayoutMode = typeof forceValue === 'boolean'
      ? forceValue
      : !this.state.editLayoutMode;
    if (!this.state.editLayoutMode) {
      this.state.roomItemInteraction = null;
    }
    this.renderRoomProfileControls();
    this.renderAnimatedMap();
  }

  renderRoomProfileControls() {
    const {
      roomProfileSelect,
      roomProfileDelete,
      roomProfileMeta,
      roomTemplateSelect,
      roomTemplateApply,
      roomTemplateSave,
      roomTemplateStatus,
      roomStorageStatus,
      roomItemLibrary,
      roomItemAdd,
      roomItemsClear,
      roomEditMode,
      roomEditModeStatus,
      roomItemsSummary,
      roomItemsList,
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
    const activeTemplate = this.getSelectedRoomTemplate();
    const roomItems = this.getActiveRoomLayoutItems(activeProfile);
    const selectedItem = this.ensureSelectedRoomItem(activeProfile);
    const fixedProfile = activeProfile?.kind === 'fixed';

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

    if (roomTemplateSelect) {
      roomTemplateSelect.innerHTML = (this.state.roomTemplates || []).map((template) => `
        <option value="${template.id}">${this.getRoomTemplateLabel(template)}</option>
      `).join('');
      roomTemplateSelect.value = activeTemplate?.id || '';
      roomTemplateSelect.disabled = !fixedProfile;
    }

    if (roomTemplateApply) roomTemplateApply.disabled = !fixedProfile || !activeTemplate;
    if (roomTemplateSave) roomTemplateSave.disabled = !fixedProfile;
    if (roomItemAdd) roomItemAdd.disabled = !fixedProfile;
    if (roomItemsClear) roomItemsClear.disabled = !fixedProfile || roomItems.length === 0;
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

    if (roomTemplateStatus) {
      roomTemplateStatus.textContent = activeTemplate ? this.getRoomTemplateLabel(activeTemplate) : t('fp2.layout.template_none');
      roomTemplateStatus.className = `chip ${fixedProfile ? 'chip--info' : 'chip--neutral'}`;
    }

    if (roomItemsSummary) {
      roomItemsSummary.textContent = t('fp2.layout.items_summary', { count: roomItems.length });
    }

    if (roomStorageStatus) {
      const storageState = this.getRoomConfigStorageBadgeState();
      roomStorageStatus.textContent = storageState.text;
      roomStorageStatus.className = storageState.className;
    }

    if (roomItemLibrary) {
      roomItemLibrary.innerHTML = BUILTIN_ROOM_ITEM_LIBRARY.map((item) => `
        <button class="fp2-layout-library-item btn-reset" data-library-add="${item.type}" type="button">
          <span class="fp2-layout-library-icon">${item.icon || this.getRoomItemIcon({ type: item.type })}</span>
          <span class="fp2-layout-library-name">${this.getRoomItemLabel({ type: item.type })}</span>
        </button>
      `).join('');
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
                <span>X ${Math.round(item.x)} · Y ${Math.round(item.y)}</span>
                <span>${Math.round(item.widthCm)}×${Math.round(item.depthCm)} cm</span>
                <span>${Math.round(item.rotationDeg || 0)}°</span>
              </div>
            </article>
          `).join('')
        : `<div class="fp2-layout-item-empty">${t('fp2.layout.items_empty')}</div>`;
    }

    if (roomItemInspector) {
      roomItemInspector.style.display = fixedProfile ? 'flex' : 'none';
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
    if (roomItemXValue) roomItemXValue.textContent = selectedItem ? `${Math.round(selectedItem.x)} cm` : '-';
    if (roomItemYValue) roomItemYValue.textContent = selectedItem ? `${Math.round(selectedItem.y)} cm` : '-';
    if (roomItemWidthValue) roomItemWidthValue.textContent = selectedItem ? `${Math.round(selectedItem.widthCm)} cm` : '-';
    if (roomItemDepthValue) roomItemDepthValue.textContent = selectedItem ? `${Math.round(selectedItem.depthCm)} cm` : '-';
    if (roomItemRotationValue) roomItemRotationValue.textContent = selectedItem ? `${Math.round(selectedItem.rotationDeg || 0)}°` : '-';

    if (roomProfileMeta) {
      roomProfileMeta.textContent = activeProfile?.kind === 'fixed'
        ? t('fp2.layout.meta', {
            name: this.getRoomProfileLabel(activeProfile),
            width: Math.round(geometry?.widthCm || activeProfile.widthCm),
            depth: Math.round(geometry?.depthCm || activeProfile.depthCm)
          })
        : t('fp2.layout.meta_auto');
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
  }

  setActiveRoomProfile(profileId) {
    if (!this.state.roomProfiles.some(profile => profile.id === profileId)) return;
    this.state.activeRoomProfileId = profileId;
    this.state.editLayoutMode = false;
    this.state.roomItemInteraction = null;
    persistActiveRoomProfileId(profileId);
    this.ensureSelectedRoomItem(this.getActiveRoomProfile());
    this.renderRoomProfileControls();
    this.renderCurrent(this.lastCurrentData);
    this.renderAnimatedMap();
    this.scheduleRoomConfigSave();
  }

  isAnimalFilterEnabled(profile = this.getActiveRoomProfile()) {
    return getProfileAnimalFilterEnabled(profile, this.state.roomProfileFilters);
  }

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
  }

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
  }

  getActiveRoomGeometry(profile = this.getActiveRoomProfile()) {
    if (!profile || profile.kind !== 'fixed') return null;
    const stored = normalizeCalibrationOverride(this.state.roomProfileCalibration?.[profile.id]);
    const draft = this.getCalibrationDraft(profile);
    const effectiveCalibration = this.canApplyCalibrationDraft(profile) ? draft : stored;
    return getProfileGeometry(profile, {
      [profile.id]: effectiveCalibration
    });
  }

  formatCalibrationValue(value) {
    return Number.isFinite(value) ? `${Math.round(value)} cm` : '-';
  }

  canApplyCalibrationDraft(profile = this.getActiveRoomProfile()) {
    const draft = this.getCalibrationDraft(profile);
    return Number.isFinite(draft?.leftX) && Number.isFinite(draft?.rightX) && Number.isFinite(draft?.farY)
      && Math.abs(draft.rightX - draft.leftX) > 80
      && draft.farY >= 100;
  }

  getCalibrationCaptureTarget() {
    const withCoords = (this.state.targets || []).find((target) => this.hasCoordinates(target))
      || (this.state.rawTargets || []).find((target) => this.hasCoordinates(target));
    return withCoords || null;
  }

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
  }

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
  }

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
  }

  estimateRoomProfileDefaults() {
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
  }

  handleSaveRoomProfile() {
    if (typeof window === 'undefined') return;

    const defaults = this.estimateRoomProfileDefaults();
    const activeProfile = this.getActiveRoomProfile();
    const activeLayoutItems = this.getActiveRoomLayoutItems(activeProfile);
    const suggestedName = activeProfile && !activeProfile.builtin
      ? activeProfile.name
      : (this.state.device?.room && this.state.device.room !== '-'
        ? this.state.device.room
        : t('fp2.layout.custom_default'));

    const name = window.prompt(t('fp2.layout.prompt_name'), suggestedName);
    if (name === null) return;
    const trimmedName = name.trim();
    if (!trimmedName) return;

    const widthInput = window.prompt(t('fp2.layout.prompt_width'), String(defaults.widthCm));
    if (widthInput === null) return;
    const depthInput = window.prompt(t('fp2.layout.prompt_depth'), String(defaults.depthCm));
    if (depthInput === null) return;

    const widthCm = Number(widthInput);
    const depthCm = Number(depthInput);
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
    if (activeLayoutItems.length > 0) {
      this.state.roomProfileLayouts = {
        ...this.state.roomProfileLayouts,
        [profile.id]: activeLayoutItems.map((item) => ({ ...item, id: `${profile.id}-${item.type}-${item.id}` }))
      };
      persistRoomProfileLayouts(this.state.roomProfileLayouts);
    }
    this.setActiveRoomProfile(profile.id);
    this.scheduleRoomConfigSave({ immediate: true });
  }

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
    const nextLayouts = { ...this.state.roomProfileLayouts };
    delete nextFilters[activeProfile.id];
    delete nextLayouts[activeProfile.id];
    this.state.roomProfileFilters = nextFilters;
    this.state.roomProfileLayouts = nextLayouts;
    persistRoomProfiles(this.state.customRoomProfiles);
    persistRoomProfileFilters(this.state.roomProfileFilters);
    persistRoomProfileLayouts(this.state.roomProfileLayouts);
    this.setActiveRoomProfile(DEFAULT_ROOM_PROFILE_ID);
    this.scheduleRoomConfigSave({ immediate: true });
  }

  handleApplyRoomTemplate() {
    const activeProfile = this.getActiveRoomProfile();
    const geometry = this.getActiveRoomGeometry(activeProfile);
    const template = this.getSelectedRoomTemplate();
    if (!activeProfile || activeProfile.kind !== 'fixed' || !geometry || !template) return;
    const items = this.materializeTemplateItems(template, geometry);
    this.setActiveRoomLayoutItems(items, activeProfile);
  }

  handleSaveRoomTemplate() {
    const activeProfile = this.getActiveRoomProfile();
    const geometry = this.getActiveRoomGeometry(activeProfile);
    const items = this.getActiveRoomLayoutItems(activeProfile);
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
      items: this.serializeLayoutItemsAsTemplate(items, geometry)
    };

    this.state.customRoomTemplates = existing
      ? this.state.customRoomTemplates.map((item) => item.id === existing.id ? template : item)
      : [...this.state.customRoomTemplates, template];
    this.state.roomTemplates = buildRoomTemplates(this.state.customRoomTemplates);
    this.state.selectedRoomTemplateId = template.id;
    persistRoomTemplates(this.state.customRoomTemplates);
    this.renderRoomProfileControls();
    this.scheduleRoomConfigSave({ immediate: true });
  }

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
  }

  handleAddRoomItem(type = null) {
    const activeProfile = this.getActiveRoomProfile();
    const geometry = this.getActiveRoomGeometry(activeProfile);
    if (!activeProfile || activeProfile.kind !== 'fixed' || !geometry || typeof window === 'undefined') return;

    const existingCount = this.getActiveRoomLayoutItems(activeProfile).length;
    const def = type
      ? BUILTIN_ROOM_ITEM_LIBRARY.find((item) => item.type === type)
      : null;
    const choice = !def ? window.prompt(
      t('fp2.layout.item_prompt', {
        options: this.getRoomItemPromptOptions()
      }),
      '1'
    ) : null;
    if (!def && choice === null) return;
    const itemIndex = !def ? Number(choice) - 1 : -1;
    const chosen = def || BUILTIN_ROOM_ITEM_LIBRARY[itemIndex];
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
  }

  handleClearRoomItems() {
    const activeProfile = this.getActiveRoomProfile();
    if (!activeProfile || activeProfile.kind !== 'fixed' || typeof window === 'undefined') return;
    const confirmed = window.confirm(t('fp2.layout.template_clear_confirm', {
      name: this.getRoomProfileLabel(activeProfile)
    }));
    if (!confirmed) return;
    this.setActiveRoomLayoutItems([], activeProfile);
  }

  handleRemoveRoomItem(itemId) {
    const activeProfile = this.getActiveRoomProfile();
    if (!activeProfile) return;
    if (this.state.selectedRoomItemId === itemId) {
      this.state.roomItemInteraction = null;
    }
    this.setActiveRoomLayoutItems(
      this.getActiveRoomLayoutItems(activeProfile).filter((item) => item.id !== itemId),
      activeProfile
    );
  }

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
  }

  updateRoomItem(itemId, patch, profile = this.getActiveRoomProfile()) {
    const geometry = this.getActiveRoomGeometry(profile);
    if (!profile || !geometry) return;
    const nextItems = this.getActiveRoomLayoutItems(profile).map((item) => item.id === itemId
      ? this.clampRoomItemToGeometry({ ...item, ...patch }, geometry)
      : item);
    this.setActiveRoomLayoutItems(nextItems, profile);
    this.state.selectedRoomItemId = itemId;
  }

  rotateRoomItem(itemId, deltaDeg, profile = this.getActiveRoomProfile()) {
    const selected = this.getActiveRoomLayoutItems(profile).find((item) => item.id === itemId);
    if (!selected) return;
    const nextRotation = (((Number(selected.rotationDeg || 0) + deltaDeg) % 360) + 360) % 360;
    this.updateRoomItem(itemId, { rotationDeg: nextRotation }, profile);
  }

  getCanvasPoint(event) {
    const canvas = this.elements.movementCanvas;
    if (!canvas) return null;
    const rect = canvas.getBoundingClientRect();
    return {
      x: (event.clientX - rect.left) * (canvas.width / rect.width),
      y: (event.clientY - rect.top) * (canvas.height / rect.height)
    };
  }

  canvasToRoom(point, projection) {
    if (!projection || !point) return null;
    return {
      x: projection.minX + ((point.x - projection.roomRect.x) / Math.max(1, projection.roomRect.width)) * (projection.maxX - projection.minX),
      y: projection.maxY - ((point.y - projection.roomRect.y) / Math.max(1, projection.roomRect.height)) * (projection.maxY - projection.minY)
    };
  }

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
  }

  handleCanvasPointerDown(event) {
    const activeProfile = this.getActiveRoomProfile();
    const projection = this.state.lastRoomProjection;
    if (!activeProfile || activeProfile.kind !== 'fixed' || !projection || !this.state.editLayoutMode) return;
    const point = this.getCanvasPoint(event);
    if (!point) return;

    const boxes = this.getRoomItemCanvasBoxes(projection, activeProfile).reverse();
    for (const box of boxes) {
      const handle = box.resizeHandle;
      if (point.x >= handle.x && point.x <= handle.x + handle.size && point.y >= handle.y && point.y <= handle.y + handle.size) {
        this.setSelectedRoomItem(box.item.id);
        this.state.roomItemInteraction = { mode: 'resize', itemId: box.item.id, projection };
        return;
      }
      if (point.x >= box.x && point.x <= box.x + box.width && point.y >= box.y && point.y <= box.y + box.height) {
        const roomPoint = this.canvasToRoom(point, projection);
        this.setSelectedRoomItem(box.item.id);
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
  }

  handleCanvasPointerMove(event) {
    const interaction = this.state.roomItemInteraction;
    if (!interaction) return;
    const activeProfile = this.getActiveRoomProfile();
    const selected = this.getSelectedRoomItem(activeProfile);
    if (!activeProfile || !selected) return;
    const roomPoint = this.canvasToRoom(this.getCanvasPoint(event), interaction.projection);
    if (!roomPoint) return;
    if (interaction.mode === 'move') {
      this.updateRoomItem(selected.id, {
        x: Math.round(roomPoint.x - interaction.offsetX),
        y: Math.round(roomPoint.y - interaction.offsetY)
      }, activeProfile);
    } else if (interaction.mode === 'resize') {
      this.updateRoomItem(selected.id, {
        widthCm: Math.max(20, Math.round(Math.abs(roomPoint.x - selected.x) * 2)),
        depthCm: Math.max(20, Math.round(Math.abs(roomPoint.y - selected.y) * 2))
      }, activeProfile);
    }
  }

  handleCanvasPointerUp() {
    this.state.roomItemInteraction = null;
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
      this.lastStatus = status;
      this.state.apiEnabled = Boolean(status.enabled);
      this.state.device = status.device || null;
      this.state.connection = status.connection || null;

      this.elements.apiStatus.textContent = this.state.apiEnabled ? t('common.enabled') : t('common.disabled');
      this.elements.apiStatus.className = `chip ${this.state.apiEnabled ? 'ok' : 'warn'}`;

      this.updateStreamState(status.connection?.state || (status.stream_connected ? 'live' : 'offline'));
      this.elements.entityId.textContent = this.formatSource(status.source || status.entity_id, status.connection?.transport || status.device?.transport);
      this.elements.transportValue.textContent = this.formatTransport(status.connection?.transport || status.device?.transport);
      this.elements.connectionState.textContent = this.formatConnectionState(status.connection?.state);

      this.renderDevice(status.device, status.connection);

      const statusZones = this.normalizeZones(status.connection?.zones || []);
      if (statusZones.length > 0) {
        this.state.zones = statusZones;
        this.renderZoneWindows(statusZones, this.state.currentZone, {}, { frozen: false });
        this.renderZoneAnalytics(statusZones, this.state.currentZone, {}, { frozen: false });
      } else {
        this.renderZoneAnalytics([], this.state.currentZone, {}, { frozen: false });
      }
      this.renderZoneRangeSummary();

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
        this.elements.lastPacketAge.textContent = this.formatAgeSeconds(status.connection.last_update_age_sec);
      }
    } catch (error) {
      console.error('Failed to load FP2 status:', error);
      this.elements.apiStatus.textContent = t('common.error');
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

  async enableRealtimeCoordinates() {
    if (this.state.coordinateEnableBusy) return;
    this.state.coordinateEnableBusy = true;
    this.renderCoordinateControl(this.lastCurrentData?.metadata?.raw_attributes?.resource_values || null);
    try {
      await fp2Service.enableRealtimeCoordinates();
      await this.loadCurrent();
      await this.loadStatus();
    } catch (error) {
      console.error('Failed to enable realtime coordinates:', error);
      window.alert(t('fp2.coordinate_enable_failed'));
    } finally {
      this.state.coordinateEnableBusy = false;
      this.renderCoordinateControl(this.lastCurrentData?.metadata?.raw_attributes?.resource_values || null);
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
    const label = state === 'live' ? t('fp2.stream.live')
      : state === 'connected' ? t('fp2.stream.connected')
      : state === 'polling' ? t('fp2.stream.polling')
      : state === 'error' ? t('fp2.stream.error')
      : t('fp2.stream.offline');
    const cls = (state === 'live' || state === 'connected') ? 'ok' : state === 'error' ? 'err' : 'warn';
    this.elements.streamStatus.textContent = label;
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
    if (!data) return;

    this.lastCurrentData = data;

    const metadata = data?.metadata || {};
    const rawAttributes = metadata.raw_attributes || {};
    const advancedMetrics = rawAttributes.advanced_metrics || {};
    const zoneMetrics = rawAttributes.zone_metrics || {};
    const available = metadata.available !== false;
    const presenceState = this.resolvePresenceState(metadata);
    const rawPresence = presenceState.rawPresence;
    const effectivePresence = presenceState.effectivePresence;
    const derivedPresence = presenceState.derivedPresence;
    const rawZones = this.getZoneStates(data, effectivePresence);
    const previousTargets = Array.isArray(this.state.rawTargets) ? this.state.rawTargets : [];
    const sampleAtMs = this.resolveSampleTimestampMs(data?.timestamp, rawAttributes.device_timestamp);
    const activeProfile = this.getActiveRoomProfile();
    const rawTargets = this.attachTargetDeltas(this.getTargets(data, rawAttributes, rawZones), previousTargets);
    this.state.targetTracks = updateTargetTrackState(this.state.targetTracks, rawTargets, sampleAtMs, activeProfile);
    const classifiedTargets = classifyTargets(
      rawTargets,
      this.state.targetTracks,
      activeProfile,
      this.isAnimalFilterEnabled(activeProfile),
      sampleAtMs
    );
    const targets = classifiedTargets.visibleTargets;
    const filteredTargets = classifiedTargets.filteredTargets;
    const zones = this.buildDisplayZones(rawZones, targets, filteredTargets);
    const currentZone = this.detectCurrentZone(data, zones, targets, effectivePresence);
    const packetAge = this.getPacketAge(rawAttributes.push_time);
    const timestampLabel = this.formatTimestamp(data?.timestamp);
    const frozenCoordinates = this.hasFrozenCoordinates(rawAttributes.movement_event);
    const primaryTarget = targets[0] || filteredTargets[0] || null;
    const allTargets = classifiedTargets.allTargets || [];
    const coordinateTargets = allTargets.filter((target) => this.hasCoordinates(target));

    this.state.zones = zones;
    this.state.targets = targets;
    this.state.rawTargets = allTargets;
    this.state.filteredTargets = filteredTargets;
    this.state.lastUpdate = timestampLabel;
    this.state.currentPresenceActive = available && effectivePresence;
    this.state.currentPresenceDerived = available && derivedPresence;
    this.state.currentAvailability = available;
    this.state.currentSensorAngle = rawAttributes.sensor_angle;
    this.state.zoneMetrics = zoneMetrics;
    this.state.advancedMetrics = advancedMetrics;
    this.state.sessionPeakTargets = Math.max(this.state.sessionPeakTargets || 0, allTargets.length);
    this.state.sessionPeakCoordinateTargets = Math.max(this.state.sessionPeakCoordinateTargets || 0, coordinateTargets.length);
    this.updateTargetAnimation(targets, sampleAtMs);

    // Store trail snapshot
    const coordTargets = targets.filter(t => this.hasCoordinates(t) && !t.held);
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
    this.elements.entityId.textContent = this.formatSource(metadata.source || metadata.entity_id, rawAttributes.transport || this.state.connection?.transport || this.state.device?.transport);
    this.elements.updatedAt.textContent = timestampLabel;
    this.elements.presenceValue.textContent = available
      ? (effectivePresence
        ? (derivedPresence ? t('common.present_derived') : t('common.present'))
        : t('common.absent'))
      : t('common.unavailable');
    this.elements.presenceValue.className = `presence-pill ${available && effectivePresence ? 'present' : 'absent'}${derivedPresence ? ' derived' : ''}`;
    this.elements.personsCount.textContent = String(targets.length);
    this.elements.zonesCount.textContent = String(zones.length);
    this.elements.currentZone.textContent = currentZone || '-';
    this.elements.lastPacketAge.textContent = packetAge;
    this.elements.coordinateCount.textContent = tp('fp2.count.targets', Math.max(coordTargets.length, targets.length));
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
    this.state.currentMovementEvent = rawAttributes.movement_event;
    this.renderCoordinateFreshness(targets, sampleAtMs, effectivePresence);
    this.updateCoordinateStreamStatus(
      targets,
      classifiedTargets.allTargets,
      rawAttributes.coordinates,
      sampleAtMs,
      rawAttributes.movement_event,
      rawAttributes.coordinates_source,
      effectivePresence,
      zones
    );
    this.renderCoordinateConfidence(targets, effectivePresence, rawAttributes.movement_event);
    this.renderCoordinateQualityMonitor(targets, effectivePresence, rawAttributes.movement_event);

    // Light
    if (typeof rawAttributes.light_level === 'number') {
      this.elements.lightLevel.textContent = `${Math.round(rawAttributes.light_level)} lux`;
    } else {
      this.elements.lightLevel.textContent = '-';
    }

    // Fall alert
    this.updateFallAlert(rawAttributes.fall_state, timestampLabel);
    this.renderAdvancedMetrics(advancedMetrics);
    this.renderConfigMetrics(rawAttributes.resource_values || {});

    // Targets
    this.renderTargetSummary(allTargets, coordinateTargets);
    this.renderPrimaryTarget(primaryTarget, { frozen: frozenCoordinates });
    this.renderTargetList(allTargets, { frozen: frozenCoordinates });
    this.renderResourceGrid(rawAttributes.resource_values || {}, rawAttributes.resource_labels || {});
    this.elements.sensorOutput.textContent = JSON.stringify(rawAttributes, null, 2);
    this.elements.rawOutput.textContent = JSON.stringify(data, null, 2);

    // Graph + map
    this.updateGraphData(available && effectivePresence, targets.length);
    this.renderZoneWindows(zones, currentZone, zoneMetrics, { frozen: frozenCoordinates });
    this.renderZoneAnalytics(zones, currentZone, zoneMetrics, { frozen: frozenCoordinates });
    this.renderAnimatedMap();
    const shouldAnimateMap = this.state.pageVisible && (this.hasTargetDeltas(targets) || Boolean(this.state.roomItemInteraction));
    if (shouldAnimateMap) {
      this.startGraphAnimation(this.state.animation.durationMs + 120);
    } else {
      this.stopGraphAnimation();
    }

    // Presence duration
    if (available && effectivePresence && !this.state.presenceStartedAt) {
      this.state.presenceStartedAt = Date.now();
    }
    if (!available || !effectivePresence) {
      this.state.presenceStartedAt = null;
    }
    this.elements.presenceDuration.textContent = this.getPresenceDuration();
    const currentPeopleCount = Number.isFinite(advancedMetrics?.realtime_people_count)
      ? advancedMetrics.realtime_people_count
      : (effectivePresence ? Math.max(1, targets.length || 0) : 0);
    const occupiedZones = zones.filter((zone) => zone.occupied).map((zone) => zone.zone_id);
    if (!occupiedZones.length && available && effectivePresence) {
      occupiedZones.push('detection_area');
    }
    const currentZoneId = zones.find((zone) => zone.displayName === currentZone)?.zone_id
      || rawAttributes.current_zone
      || occupiedZones[0]
      || (available && effectivePresence ? 'detection_area' : null);
    const zoneTargetCounts = zones.reduce((acc, zone) => {
      acc[zone.zone_id] = Number(zone.target_count || 0);
      return acc;
    }, {});
    if (available && effectivePresence && !Object.prototype.hasOwnProperty.call(zoneTargetCounts, 'detection_area')) {
      zoneTargetCounts.detection_area = currentPeopleCount;
    }
    this.recordTelemetrySample({
      ts: sampleAtMs,
      people: currentPeopleCount,
      light: Number.isFinite(rawAttributes.light_level) ? rawAttributes.light_level : null,
      presence: available && effectivePresence,
      targets: targets.length,
      movementEvent: rawAttributes.movement_event,
      walkingDistance: Number.isFinite(advancedMetrics?.walking_distance_m) ? advancedMetrics.walking_distance_m : null,
      currentZoneId,
      occupiedZones,
      zoneTargetCounts
    });
    this.renderAqaraHomeOverview({
      ts: sampleAtMs,
      people: currentPeopleCount,
      light: Number.isFinite(rawAttributes.light_level) ? rawAttributes.light_level : null,
      walkingDistance: Number.isFinite(advancedMetrics?.walking_distance_m) ? advancedMetrics.walking_distance_m : null
    });
    this.renderZoneRangeSummary();

    // Presence history
    const currentPresenceState = available ? effectivePresence : null;
    if (this.state.lastPresence !== currentPresenceState) {
      this.pushHistory({ timestamp: timestampLabel, presence: currentPresenceState });
    }

    // Movement tracking
    this.trackMovement({
      timestamp: timestampLabel,
      presence: available && effectivePresence,
      zone: currentZone,
      movementEvent: rawAttributes.movement_event,
      fallState: rawAttributes.fall_state,
      targetCount: targets.length,
      realtimePeopleCount: advancedMetrics.realtime_people_count,
      visitors1m: advancedMetrics.people_count_1m,
      areaEntries10s: advancedMetrics.area_entries_10s,
      walkingDistance: advancedMetrics.walking_distance_m
    });
  }

  // ── Fall Alert ──

  updateFallAlert(fallState, timestamp) {
    if (!this.elements.fallAlert) return;
    if (fallState === 1 || fallState === 2) {
      this.elements.fallAlert.style.display = 'flex';
      this.elements.fallAlert.className = `fp2-fall-alert ${fallState === 2 ? 'critical' : 'warning'}`;
      this.elements.fallAlertText.textContent = this.formatFallStateCode(fallState);
      this.elements.fallAlertTime.textContent = timestamp;
    } else {
      this.elements.fallAlert.style.display = 'none';
    }
  }

  renderAdvancedMetrics(metrics) {
    if (this.elements.realtimePeople) {
      this.elements.realtimePeople.textContent = Number.isFinite(metrics?.realtime_people_count)
        ? String(metrics.realtime_people_count)
        : '-';
    }

    if (this.elements.visitors1m) {
      this.elements.visitors1m.textContent = Number.isFinite(metrics?.people_count_1m)
        ? t('fp2.count.per_minute', { count: metrics.people_count_1m })
        : metrics?.people_statistics_enabled ? t('fp2.waiting_report') : '-';
    }

    if (this.elements.areaEntries10s) {
      this.elements.areaEntries10s.textContent = Number.isFinite(metrics?.area_entries_10s)
        ? t('fp2.count.entries_10s', { count: metrics.area_entries_10s })
        : '-';
    }

    if (this.elements.walkingDistance) {
      this.elements.walkingDistance.textContent = Number.isFinite(metrics?.walking_distance_m)
        ? this.formatMeters(metrics.walking_distance_m)
        : metrics?.walking_distance_enabled ? t('fp2.waiting_report') : '-';
    }

    this.setFeatureChip(this.elements.peopleMode, metrics?.people_statistics_enabled);
    this.setFeatureChip(this.elements.distanceMode, metrics?.walking_distance_enabled);
  }

  renderConfigMetrics(resourceValues) {
    const values = resourceValues || {};
    this.setMetricValue(this.elements.realtimePositionSwitch, this.formatSettingValue('4.22.85', values['4.22.85']));
    this.setMetricValue(this.elements.workMode, this.formatSettingValue('14.49.85', values['14.49.85']));
    this.setMetricValue(this.elements.detectionMode, this.formatSettingValue('14.55.85', values['14.55.85']));
    this.setMetricValue(this.elements.doNotDisturbSwitch, this.formatSettingValue('4.23.85', values['4.23.85']));
    this.setMetricValue(this.elements.doNotDisturbSchedule, this.formatSettingValue('8.0.2207', values['8.0.2207']));
    this.setMetricValue(this.elements.indicatorLight, this.formatSettingValue('8.0.2032', values['8.0.2032']));
    this.setMetricValue(this.elements.installationPosition, this.formatSettingValue('14.57.85', values['14.57.85']));
    this.setMetricValue(this.elements.installationHeight, this.formatSettingValue('1.11.85', values['1.11.85']));
    this.setMetricValue(this.elements.bedHeight, this.formatSettingValue('1.10.85', values['1.10.85']));
    this.setMetricValue(this.elements.installationAngleStatus, this.formatSettingValue('13.35.85', values['13.35.85']));
    this.setMetricValue(this.elements.presenceSensitivity, this.formatSettingValue('14.1.85', values['14.1.85']));
    this.setMetricValue(this.elements.approachLevel, this.formatSettingValue('14.47.85', values['14.47.85']));
    this.setMetricValue(this.elements.fallDetectionSensitivity, this.formatSettingValue('14.30.85', values['14.30.85']));
    this.setMetricValue(this.elements.fallDetectionDelay, this.formatSettingValue('14.59.85', values['14.59.85']));
    this.setMetricValue(this.elements.respirationReporting, this.formatSettingValue('0.9.85', values['0.9.85']));
    this.setMetricValue(this.elements.respirationReportingMinute, this.formatSettingValue('0.12.85', values['0.12.85']));
    this.setMetricValue(this.elements.respirationConfidence, this.formatSettingValue('0.14.85', values['0.14.85']));
    this.setMetricValue(this.elements.heartRateConfidence, this.formatSettingValue('0.13.85', values['0.13.85']));
    this.setMetricValue(this.elements.bodyMovementLevel, this.formatSettingValue('13.11.85', values['13.11.85']));
    this.setMetricValue(this.elements.bedsideInstallationPosition, this.formatSettingValue('14.58.85', values['14.58.85']));
    this.setMetricValue(this.elements.firstNetworkJoin, this.formatSettingValue('4.60.85', values['4.60.85']));
    this.setMetricValue(this.elements.resetAbsenceState, this.formatSettingValue('4.66.85', values['4.66.85']));
    this.renderCoordinateControl(values);
    this.renderScenarioPresets(values);
  }

  renderCoordinateControl(resourceValues) {
    const switchValue = resourceValues ? String(resourceValues['4.22.85'] ?? '') : '';
    const enabled = switchValue === '1';

    if (this.elements.coordinateSwitchState) {
      this.elements.coordinateSwitchState.textContent = enabled ? t('common.enabled') : t('common.disabled');
      this.elements.coordinateSwitchState.className = enabled ? 'chip ok' : 'chip chip--neutral';
    }

    if (this.elements.coordinateEnable) {
      if (this.state.coordinateEnableBusy) {
        this.elements.coordinateEnable.hidden = false;
        this.elements.coordinateEnable.disabled = true;
        this.elements.coordinateEnable.textContent = t('fp2.coordinate_enabling');
      } else if (enabled) {
        this.elements.coordinateEnable.hidden = true;
        this.elements.coordinateEnable.disabled = true;
        this.elements.coordinateEnable.textContent = t('fp2.coordinate_enabled');
      } else {
        this.elements.coordinateEnable.hidden = false;
        this.elements.coordinateEnable.disabled = false;
        this.elements.coordinateEnable.textContent = t('fp2.coordinate_enable');
      }
    }
  }

  setMetricValue(element, value) {
    if (!element) return;
    element.textContent = value ?? '-';
  }

  formatSettingValue(rid, value) {
    if (value === null || value === undefined || value === '') {
      return '-';
    }

    if (['4.22.85', '4.23.85', '4.71.85', '4.75.85', '8.0.2032', '0.9.85', '0.12.85'].includes(rid)) {
      return String(value) === '1' ? t('common.enabled') : t('common.disabled');
    }

    if (['0.13.85', '0.14.85'].includes(rid) && Number.isFinite(Number(value))) {
      return `${Math.round(Number(value))}%`;
    }

    if (rid === '14.55.85') {
      return t(`fp2.value.detection_mode.${Number(value)}`) || t('fp2.state.code', { code: Number(value) });
    }

    if (rid === '14.57.85') {
      return t(`fp2.value.installation_position.${Number(value)}`) || t('fp2.state.code', { code: Number(value) });
    }

    if (rid === '14.58.85') {
      return t(`fp2.value.bedside_position.${Number(value)}`) || t('fp2.state.code', { code: Number(value) });
    }

    if (['1.10.85', '1.11.85'].includes(rid) && Number.isFinite(Number(value))) {
      return `${Math.round(Number(value))} cm`;
    }

    if (rid === '8.0.2207') {
      const match = String(value).match(/^(\d+)\s*-\s*(\d+)\s+(\d+)\s+\*\s+\*\s+\*\s*-\s*(\d+)\s+(\d+)\s+\*\s+\*\s+\*$/);
      if (match) {
        const enabled = match[1] === '1';
        const start = `${String(match[3]).padStart(2, '0')}:${String(match[2]).padStart(2, '0')}`;
        const end = `${String(match[5]).padStart(2, '0')}:${String(match[4]).padStart(2, '0')}`;
        return enabled ? `${start} → ${end}` : t('common.disabled');
      }
    }

    if (Number.isFinite(Number(value))) {
      return t('fp2.state.code', { code: Number(value) });
    }

    return String(value);
  }

  formatResourceMetricValue(rid, value) {
    if (value === null || value === undefined || value === '') {
      return '-';
    }
    if (rid === '4.22.700' && value) {
      try {
        const coords = typeof value === 'string' ? JSON.parse(value) : value;
        const active = Array.isArray(coords) ? coords.filter((target) => target && target.state === '1' && (target.x !== 0 || target.y !== 0)) : [];
        return active.length > 0 ? JSON.stringify(active, null, 2) : `[] (${t('fp2.empty.targets')})`;
      } catch {
        return value;
      }
    }
    if (rid === '0.63.85' && Number.isFinite(Number(value))) {
      return this.formatMeters(Number(value));
    }
    if (['4.71.85', '4.75.85'].includes(rid)) {
      return String(value) === '1' ? t('common.enabled') : t('common.disabled');
    }
    if (['0.9.85', '0.12.85', '0.13.85', '0.14.85', '13.11.85', '14.58.85', '4.60.85', '4.66.85'].includes(rid)) {
      return this.formatSettingValue(rid, value);
    }
    return value;
  }

  setFeatureChip(element, enabled) {
    if (!element) return;
    if (enabled === true) {
      element.textContent = t('common.enabled');
      element.className = 'chip ok';
      return;
    }
    if (enabled === false) {
      element.textContent = t('common.disabled');
      element.className = 'chip warn';
      return;
    }
    element.textContent = '-';
    element.className = 'chip chip--neutral';
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

  resolvePresenceState(metadata) {
    const rawPresence = Boolean(metadata?.presence);
    const effectivePresence = metadata?.effective_presence !== undefined
      ? Boolean(metadata.effective_presence)
      : rawPresence;
    const derivedPresence = effectivePresence && Boolean(metadata?.derived_presence) && !rawPresence;
    return {
      rawPresence,
      effectivePresence,
      derivedPresence,
      mode: metadata?.presence_mode || (effectivePresence ? (derivedPresence ? 'derived' : 'raw') : 'none'),
      reason: metadata?.presence_reason || null
    };
  }

  getZoneStates(data, effectivePresence = false) {
    const rawZones = data?.metadata?.raw_attributes?.zones;
    if (Array.isArray(rawZones) && rawZones.length > 0) return this.normalizeZones(rawZones);

    const zoneSummary = data?.zone_summary || {};
    const summaryZones = Object.entries(zoneSummary).map(([zoneId, targetCount], index) => ({
      zone_id: zoneId, name: zoneId, occupied: Number(targetCount) > 0, target_count: Number(targetCount) || 0, index
    }));
    if (summaryZones.length > 0) return this.normalizeZones(summaryZones);

    if (this.state.zones.length > 0) return this.state.zones;

    return [{
      zone_id: 'detection_area',
      name: t('fp2.zone.detection_area'),
      displayName: t('fp2.zone.detection_area'),
      occupied: Boolean(effectivePresence), target_count: 0
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
        target_type: target.target_type ?? null, range_id: target.range_id ?? null,
        held: Boolean(target.held),
        hold_age_sec: Number(target.hold_age_sec ?? 0),
        coordinate_source: target.held ? 'hold' : (rawAttributes.coordinates_source || 'live')
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
        target_type: target.target_type ?? null, range_id: target.range_id ?? null,
        held: Boolean(target.held),
        hold_age_sec: Number(target.hold_age_sec ?? 0),
        coordinate_source: target.held ? 'hold' : (rawAttributes.coordinates_source || 'live')
      }));
    }

    return [];
  }

  buildDisplayZones(zones, visibleTargets, filteredTargets) {
    const normalizedZones = this.normalizeZones(zones || []);
    return applyTargetCountsToZones(normalizedZones, visibleTargets, filteredTargets);
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

  detectCurrentZone(data, zones, targets, effectivePresence = false) {
    const coordZone = targets.find(t => t.zone_id)?.zone_id;
    if (coordZone) return this.displayZoneName(coordZone, zones);
    const personZone = data?.persons?.[0]?.zone_id;
    if (personZone) return this.displayZoneName(personZone, zones);
    const occupiedZone = zones.find(z => z.occupied);
    if (occupiedZone) return occupiedZone.displayName;
    const attrs = data?.metadata?.raw_attributes || {};
    if (attrs.current_zone) return this.displayZoneName(attrs.current_zone, zones);
    if (effectivePresence) return t('fp2.zone.detection_area');
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
    return hasTargetCoordinates(target);
  }

  // ── Coordinate freshness ──

  buildCoordinateSignature(targets) {
    const ct = (targets || [])
      .filter(t => this.hasCoordinates(t))
      .map(t => [t.target_id, Math.round(t.x), Math.round(t.y), Math.round(t.distance ?? 0), Math.round(t.angle ?? 0)])
      .sort((a, b) => String(a[0]).localeCompare(String(b[0])));
    return ct.length ? JSON.stringify(ct) : null;
  }

  renderCoordinateFreshness(targets, sampleAtMs, presence) {
    if (!this.elements.coordinateStream || !this.elements.coordinateChangeAge) return;

    const now = sampleAtMs || Date.now();
    const signature = this.buildCoordinateSignature(targets);
    if (!signature) {
      this.state.coordinateSignature = null;
      if (this.state.lastCoordinateSeenAtMs && !this.state.coordinateGapStartedAtMs) {
        this.state.coordinateGapStartedAtMs = now;
      }
      const ageMs = this.state.lastCoordinateChangeAtMs ? Math.max(0, Date.now() - this.state.lastCoordinateChangeAtMs) : null;
      const shouldForget =
        !presence &&
        ageMs !== null &&
        ageMs > 15000;
      if (shouldForget) {
        this.state.lastCoordinateChangeAtMs = null;
        this.state.lastCoordinateSeenAtMs = null;
        this.elements.coordinateChangeAge.textContent = '-';
      } else {
        this.elements.coordinateChangeAge.textContent = ageMs === null ? '-' : this.formatAgeSeconds(ageMs / 1000, true);
      }
      return;
    }

    if (this.state.coordinateGapStartedAtMs) {
      const gapMs = Math.max(0, now - this.state.coordinateGapStartedAtMs);
      if (gapMs >= 5000) {
        this.state.lastCoordinateRevivedAtMs = now;
        this.state.lastCoordinateRevivedGapMs = gapMs;
      }
      this.state.coordinateGapStartedAtMs = null;
    }

    if (this.state.coordinateSignature !== signature) {
      this.state.coordinateSignature = signature;
      this.state.lastCoordinateChangeAtMs = now;
      this.state.coordinateUpdateTimestamps = [
        ...(this.state.coordinateUpdateTimestamps || []).filter((ts) => now - ts <= 60000),
        now
      ].slice(-40);
    }
    this.state.lastCoordinateSeenAtMs = now;

    const ageMs = this.state.lastCoordinateChangeAtMs ? Math.max(0, Date.now() - this.state.lastCoordinateChangeAtMs) : null;
    const ageSec = ageMs === null ? null : ageMs / 1000;
    this.elements.coordinateChangeAge.textContent = ageSec === null ? '-' : this.formatAgeSeconds(ageSec, true);
  }

  isActiveMovementEvent(movementEvent) {
    return [2, 3, 4, 6, 7, 8, 9, 10].includes(Number(movementEvent));
  }

  hasFrozenCoordinates(movementEvent = this.state.currentMovementEvent) {
    if (!this.state.lastCoordinateChangeAtMs) return false;
    const ageSec = Math.max(0, Date.now() - this.state.lastCoordinateChangeAtMs) / 1000;
    return ageSec > (this.isActiveMovementEvent(movementEvent) ? 8 : 15);
  }

  getCoordinateConfidence(targets, presence, movementEvent) {
    const now = Date.now();
    const coordTargets = (targets || []).filter((target) => this.hasCoordinates(target));
    const hasCoords = coordTargets.length > 0;
    const recentUpdates = (this.state.coordinateUpdateTimestamps || []).filter((ts) => now - ts <= 20000);
    this.state.coordinateUpdateTimestamps = recentUpdates.slice(-40);
    const lastAgeSec = this.state.lastCoordinateChangeAtMs
      ? Math.max(0, now - this.state.lastCoordinateChangeAtMs) / 1000
      : null;
    const revivedRecently =
      hasCoords &&
      this.state.lastCoordinateRevivedAtMs !== null &&
      (now - this.state.lastCoordinateRevivedAtMs) <= 15000 &&
      (this.state.lastCoordinateRevivedGapMs || 0) >= 5000;

    if (this.hasFrozenCoordinates(movementEvent)) {
      return { label: t('fp2.coordinate.confidence.frozen'), className: 'chip err' };
    }
    if (revivedRecently) {
      return { label: t('fp2.coordinate.confidence.app_assisted'), className: 'chip ok' };
    }
    if (hasCoords && lastAgeSec !== null && lastAgeSec <= 5 && recentUpdates.length >= 4) {
      return { label: t('fp2.coordinate.confidence.stable'), className: 'chip ok' };
    }
    if (hasCoords && lastAgeSec !== null && lastAgeSec <= 8 && recentUpdates.length >= 1) {
      return { label: t('fp2.coordinate.confidence.bursty'), className: 'chip warn' };
    }
    if (!hasCoords && presence) {
      return { label: t('fp2.coordinate.confidence.none'), className: 'chip chip--neutral' };
    }
    return { label: '-', className: 'chip chip--neutral' };
  }

  getCoordinateUpdateRate(now = Date.now()) {
    const updates = (this.state.coordinateUpdateTimestamps || []).filter((ts) => now - ts <= 60000);
    this.state.coordinateUpdateTimestamps = updates.slice(-60);
    return updates.length;
  }

  getCoordinateHealthState(targets, presence, movementEvent) {
    const now = Date.now();
    const coordTargets = (targets || []).filter((target) => this.hasCoordinates(target));
    const hasCoords = coordTargets.length > 0;
    const rate = this.getCoordinateUpdateRate(now);
    const lastAgeSec = this.state.lastCoordinateChangeAtMs
      ? Math.max(0, now - this.state.lastCoordinateChangeAtMs) / 1000
      : null;
    const activeMovement = this.isActiveMovementEvent(movementEvent);
    const revivedRecently =
      hasCoords &&
      this.state.lastCoordinateRevivedAtMs !== null &&
      (now - this.state.lastCoordinateRevivedAtMs) <= 15000 &&
      (this.state.lastCoordinateRevivedGapMs || 0) >= 5000;

    if (this.hasFrozenCoordinates(movementEvent)) {
      return { label: t('fp2.coordinate.health.frozen'), className: 'chip err', score: 0.2 };
    }
    if (revivedRecently) {
      return { label: t('fp2.coordinate.health.app_assisted'), className: 'chip ok', score: 2.7 };
    }
    if (hasCoords && lastAgeSec !== null && lastAgeSec <= 3 && rate >= 8) {
      return { label: t('fp2.coordinate.health.steady'), className: 'chip ok', score: 3 };
    }
    if (presence && activeMovement && rate < 4) {
      return { label: t('fp2.coordinate.health.unstable'), className: 'chip warn', score: hasCoords ? 1.5 : 1.1 };
    }
    if (hasCoords && lastAgeSec !== null && lastAgeSec <= 8 && rate >= 1) {
      return { label: t('fp2.coordinate.health.bursty'), className: 'chip warn', score: 2.1 };
    }
    if (!hasCoords && presence) {
      return { label: t('fp2.coordinate.health.no_coords'), className: 'chip chip--neutral', score: 0.8 };
    }
    return { label: '-', className: 'chip chip--neutral', score: 0.4 };
  }

  updateCoordinateStreamStatus(targets, allTargets, coordinatesPayload, sampleAtMs, movementEvent, coordinatesSource, presence, zones = []) {
    if (!this.elements.coordinateStream) return;

    const rawCoordTargets = (allTargets || []).filter(t => this.hasCoordinates(t));
    const coordTargets = targets.filter(t => this.hasCoordinates(t));
    const occupiedZones = (zones || []).filter((zone) => zone?.occupied);
    const ageMs = this.state.lastCoordinateChangeAtMs ? Math.max(0, Date.now() - this.state.lastCoordinateChangeAtMs) : null;
    const ageSec = ageMs !== null ? ageMs / 1000 : null;
    const lastSeenAgeMs = this.state.lastCoordinateSeenAtMs ? Math.max(0, Date.now() - this.state.lastCoordinateSeenAtMs) : null;
    const hasDeltaMovement = this.hasTargetDeltas(targets);
    const hasMovementEvent = this.isActiveMovementEvent(movementEvent);
    const isActivelyMoving = hasDeltaMovement || hasMovementEvent;
    const hasRecentTrace =
      coordTargets.length === 0 &&
      lastSeenAgeMs !== null &&
      lastSeenAgeMs <= 20000 &&
      this.state.trailHistory.length > 0;
    const cloudSleepWithCoords =
      coordTargets.length > 0 &&
      isActivelyMoving &&
      ageSec !== null &&
      ageSec > 3;
    const cloudSleepWithoutCoords =
      !coordinatesPayload &&
      coordTargets.length === 0 &&
      presence &&
      isActivelyMoving &&
      ageSec !== null &&
      ageSec <= 15;
    const revivedRecently =
      coordTargets.length > 0 &&
      this.state.lastCoordinateRevivedAtMs !== null &&
      (Date.now() - this.state.lastCoordinateRevivedAtMs) <= 15000 &&
      (this.state.lastCoordinateRevivedGapMs || 0) >= 5000;
    const frozenWithCoords =
      coordTargets.length > 0 &&
      this.hasFrozenCoordinates(movementEvent);

    if (coordinatesSource === 'hold' || coordTargets.some((target) => target.held)) {
      this.elements.coordinateStream.textContent = t('fp2.coordinate.status.hold');
      this.elements.coordinateStream.className = 'chip warn';
      if (this.elements.mapMode) {
        this.elements.mapMode.textContent = t('fp2.map.mode.coord_status', {
          mode: t('fp2.map.mode.coord'),
          status: t('fp2.coordinate.status.hold')
        });
        this.elements.mapMode.className = 'chip warn';
      }
      return;
    }

    if (frozenWithCoords || cloudSleepWithCoords) {
      this.elements.coordinateStream.textContent = t('fp2.coordinate.status.frozen');
      this.elements.coordinateStream.className = 'chip err';
      if (this.elements.mapMode) {
        this.elements.mapMode.textContent = t('fp2.map.mode.coord_status', {
          mode: t('fp2.map.mode.coord'),
          status: t('fp2.coordinate.status.frozen')
        });
        this.elements.mapMode.className = 'chip err';
      }
      return;
    }

    if (rawCoordTargets.length > 0 && coordTargets.length === 0) {
      this.elements.coordinateStream.textContent = t('fp2.coordinate.status.filtered');
      this.elements.coordinateStream.className = 'chip warn';
      if (this.elements.mapMode) {
        this.elements.mapMode.textContent = t('fp2.map.mode.coord_status', {
          mode: t('fp2.map.mode.coord'),
          status: t('fp2.coordinate.status.filtered')
        });
        this.elements.mapMode.className = 'chip warn';
      }
      return;
    }

    if (!coordinatesPayload || coordTargets.length === 0) {
      if (cloudSleepWithoutCoords) {
        this.elements.coordinateStream.textContent = t('fp2.coordinate.status.cloud_sleep');
        this.elements.coordinateStream.className = 'chip err';
        if (this.elements.mapMode) {
          this.elements.mapMode.textContent = t('fp2.map.mode.coord_status', {
            mode: t('fp2.map.mode.zone'),
            status: t('fp2.coordinate.status.cloud_sleep')
          });
          this.elements.mapMode.className = 'chip err';
        }
        return;
      }

      if (hasRecentTrace) {
        this.elements.coordinateStream.textContent = t('fp2.coordinate.status.trace');
        this.elements.coordinateStream.className = 'chip warn';
        if (this.elements.mapMode) {
          this.elements.mapMode.textContent = t('fp2.map.mode.coord_status', {
            mode: t('fp2.map.mode.coord'),
            status: t('fp2.coordinate.status.trace')
          });
          this.elements.mapMode.className = 'chip warn';
        }
        return;
      }

      const noCoordStatus = presence
        ? t('fp2.coordinate.status.presence_only')
        : t('fp2.coordinate.status.zone_only');
      this.elements.coordinateStream.textContent = noCoordStatus;
      this.elements.coordinateStream.className = `chip ${presence ? 'warn' : 'chip--neutral'}`;
      if (this.elements.mapMode) {
        this.elements.mapMode.textContent = presence
          ? t('fp2.map.mode.coord_status', {
              mode: occupiedZones.length > 0 ? t('fp2.map.mode.zone') : t('fp2.map.mode.coord'),
              status: noCoordStatus
            })
          : t('fp2.map.mode.zone');
        this.elements.mapMode.className = `chip ${presence ? 'warn' : 'chip--neutral'}`;
      }
      return;
    }

    let statusKey;
    let cls;
    if (ageSec === null || ageSec > 60) {
      statusKey = 'fp2.coordinate.status.stale';
      cls = 'err';
    } else if (revivedRecently && ageSec <= 6) {
      statusKey = 'fp2.coordinate.status.app_assisted';
      cls = 'ok';
    } else if (ageSec <= 2.5 && isActivelyMoving) {
      statusKey = 'fp2.coordinate.status.live';
      cls = 'ok';
    } else if (ageSec <= 2.5) {
      statusKey = 'fp2.coordinate.status.static';
      cls = 'warn';
    } else if (ageSec <= 10) {
      statusKey = 'fp2.coordinate.status.repeating';
      cls = 'warn';
    } else {
      statusKey = 'fp2.coordinate.status.slow';
      cls = 'warn';
    }

    const statusLabel = t(statusKey);
    this.elements.coordinateStream.textContent = statusLabel;
    this.elements.coordinateStream.className = `chip ${cls}`;
    if (this.elements.mapMode) {
      this.elements.mapMode.textContent = t('fp2.map.mode.coord_status', {
        mode: t('fp2.map.mode.coord'),
        status: statusLabel
      });
      this.elements.mapMode.className = `chip ${cls}`;
    }
  }

  renderCoordinateConfidence(targets, presence, movementEvent) {
    if (!this.elements.coordinateConfidence) return;
    const confidence = this.getCoordinateConfidence(targets, presence, movementEvent);
    this.elements.coordinateConfidence.textContent = confidence.label;
    this.elements.coordinateConfidence.className = confidence.className;
  }

  renderCoordinateQualityMonitor(targets, presence, movementEvent) {
    const now = Date.now();
    const updatesPerMinute = this.getCoordinateUpdateRate(now);
    const health = this.getCoordinateHealthState(targets, presence, movementEvent);

    if (this.elements.coordinateUpdateRate) {
      this.elements.coordinateUpdateRate.textContent = t('fp2.coordinate.updates_per_minute', {
        count: updatesPerMinute
      });
    }
    if (this.elements.coordinateHealthBadge) {
      this.elements.coordinateHealthBadge.textContent = health.label;
      this.elements.coordinateHealthBadge.className = health.className;
    }

    const nextPoint = {
      ts: now,
      score: health.score,
      updated: this.state.lastCoordinateChangeAtMs !== null && (now - this.state.lastCoordinateChangeAtMs) <= 1200,
      presence: Boolean(presence)
    };
    const filteredHistory = (this.state.coordinateHealthHistory || []).filter((point) => now - point.ts <= 60000);
    const lastPoint = filteredHistory[filteredHistory.length - 1];
    if (
      lastPoint
      && (now - lastPoint.ts) < 900
      && lastPoint.score === nextPoint.score
      && lastPoint.updated === nextPoint.updated
      && lastPoint.presence === nextPoint.presence
    ) {
      filteredHistory[filteredHistory.length - 1] = nextPoint;
    } else {
      filteredHistory.push(nextPoint);
    }
    this.state.coordinateHealthHistory = filteredHistory.slice(-(this.state.maxCoordinateHealthPoints || 60));

    if (this.state.pageVisible) {
      this.drawCoordinateQualityGraph();
    } else {
      this.state.pendingVisualRefresh = true;
    }
  }

  // ── Render sub-components ──

  renderTargetSummary(allTargets = [], coordinateTargets = []) {
    if (this.elements.activeTargetCount) {
      this.elements.activeTargetCount.textContent = String(allTargets.length);
    }
    if (this.elements.coordinateTargetCount) {
      this.elements.coordinateTargetCount.textContent = String(coordinateTargets.length);
    }
    if (this.elements.sessionPeakTargetCount) {
      this.elements.sessionPeakTargetCount.textContent = String(this.state.sessionPeakTargets || allTargets.length || 0);
    }
  }

  renderPrimaryTarget(target, options = {}) {
    if (!target) {
      this.elements.primaryTargetId.textContent = '-';
      this.elements.primaryTargetType.textContent = '-';
      this.elements.primaryTargetCoords.textContent = '-';
      this.elements.primaryTargetDistance.textContent = '-';
      this.elements.primaryTargetAngle.textContent = '-';
      return;
    }
    this.elements.primaryTargetId.textContent = target.target_id || '-';
    this.elements.primaryTargetType.textContent = target.target_classification
      ? `${this.formatTargetClassification(target.target_classification)}${target.held ? ` · ${t('fp2.target.class.held')}` : ''}${options.frozen ? ` · ${t('fp2.coordinate.status.frozen')}` : ''} · ${target.target_type ?? (target.range_id ?? '-')}`
      : (target.target_type ?? (target.range_id ?? '-'));
    this.elements.primaryTargetCoords.textContent = this.hasCoordinates(target) ? `${this.fmtCoord(target.x)}, ${this.fmtCoord(target.y)}` : '-';
    this.elements.primaryTargetDistance.textContent = this.formatDistance(target.distance);
    this.elements.primaryTargetAngle.textContent = this.hasCoordinates(target)
      ? `${this.formatAngle(target.angle)} · Δ ${this.fmtDelta(target.dx)}, ${this.fmtDelta(target.dy)}`
      : this.formatAngle(target.angle);
  }

  renderTargetList(targets, options = {}) {
    if (!this.elements.targetList) return;
    if (!targets.length) {
      this.elements.targetList.innerHTML = `<div class="fp2-empty-state">${t('fp2.empty.targets')}</div>`;
      return;
    }

    this.elements.targetList.innerHTML = targets.map((target, i) => {
      const color = TARGET_COLORS[i % TARGET_COLORS.length];
      const hasXY = this.hasCoordinates(target);
      const velocityMag = (Number.isFinite(target.dx) && Number.isFinite(target.dy))
        ? Math.sqrt(target.dx * target.dx + target.dy * target.dy)
        : 0;
      const velocityLabel = velocityMag > 0
        ? `${velocityMag.toFixed(1)} ${t('fp2.target.metric.speed_unit')}`
        : '-';
      const trackLabel = Number.isFinite(target.track_age_sec)
        ? this.formatAgeSeconds(target.track_age_sec)
        : '-';
      const targetClass = this.formatTargetClassification(target.target_classification);
      const filterNote = target.filtered_out ? `<div class="fp2-target-note">${t('fp2.target.filtered')}</div>` : '';
      const holdNote = target.held
        ? `<div class="fp2-target-note">${t('fp2.target.held', { age: this.formatAgeSeconds(target.hold_age_sec || 0) })}</div>`
        : '';
      const frozenNote = options.frozen && hasXY
        ? `<div class="fp2-target-note">${t('fp2.target.frozen')}</div>`
        : '';

      return `
        <article class="fp2-target-card ${hasXY ? 'has-coords' : ''} ${target.filtered_out ? 'is-filtered' : ''}">
          <div class="fp2-target-card-header">
            <span class="fp2-target-dot" style="background:${color}"></span>
            <strong>${target.target_id}</strong>
            <span class="fp2-target-zone">${this.displayZoneName(target.zone_id, this.state.zones)}</span>
            <span class="fp2-target-class ${target.target_classification || 'uncertain'}">${targetClass}${target.held ? ` · ${t('fp2.target.class.held')}` : ''}${options.frozen && hasXY ? ` · ${t('fp2.coordinate.status.frozen')}` : ''}</span>
          </div>
          <div class="fp2-target-card-body">
            <div class="fp2-target-metric"><span class="fp2-target-metric-label">${t('fp2.target.metric.xy')}</span><span>${hasXY ? `${this.fmtCoord(target.x)}, ${this.fmtCoord(target.y)}` : '-'}</span></div>
            <div class="fp2-target-metric"><span class="fp2-target-metric-label">${t('fp2.target.metric.dist')}</span><span>${this.formatDistance(target.distance)}</span></div>
            <div class="fp2-target-metric"><span class="fp2-target-metric-label">${t('fp2.target.metric.angle')}</span><span>${this.formatAngle(target.angle)}</span></div>
            <div class="fp2-target-metric"><span class="fp2-target-metric-label">${t('fp2.target.metric.delta')}</span><span>Δ ${this.fmtDelta(target.dx)}, ${this.fmtDelta(target.dy)}</span></div>
            <div class="fp2-target-metric"><span class="fp2-target-metric-label">${t('fp2.target.metric.speed')}</span><span>${velocityLabel}</span></div>
            <div class="fp2-target-metric"><span class="fp2-target-metric-label">${t('fp2.target.metric.track')}</span><span>${trackLabel}</span></div>
            ${target.target_type !== null ? `<div class="fp2-target-metric"><span class="fp2-target-metric-label">${t('fp2.target.metric.type')}</span><span>${target.target_type}</span></div>` : ''}
          </div>
          ${filterNote}
          ${holdNote}
          ${frozenNote}
        </article>`;
    }).join('');
  }

  renderResourceGrid(resourceValues, resourceLabels = {}) {
    if (!this.elements.resourceGrid) return;
    const entries = Object.entries(resourceValues || {});
    if (!entries.length) {
      this.elements.resourceGrid.innerHTML = `<div class="fp2-empty-state">${t('fp2.empty.resources')}</div>`;
      return;
    }

    this.elements.resourceGrid.innerHTML = entries.map(([rid, value]) => {
      const displayValue = this.formatResourceMetricValue(rid, value);
      return `
        <article class="fp2-resource-item">
          <span class="fp2-resource-label">${this.resourceLabel(rid, resourceLabels[rid])}</span>
          <code class="fp2-resource-id">${rid}</code>
          <pre class="fp2-resource-value fp2-resource-value--json">${displayValue ?? '-'}</pre>
        </article>`;
    }).join('');
  }

  renderZoneWindows(zones, currentZone, zoneMetrics = {}, options = {}) {
    const container = this.elements.zoneWindows;
    if (!container) return;

    if (!zones.length) {
      container.innerHTML = `<div class="fp2-zone-window fp2-zone-window--empty">${t('fp2.empty.zones')}</div>`;
      return;
    }

    container.innerHTML = zones.map(zone => {
      const isCurrent = currentZone && zone.displayName === currentZone;
      const metrics = zoneMetrics?.[zone.zone_id] || {};
      const entries10s = Number(metrics.people_entries_10s);
      const visitors1m = Number(metrics.people_count_1m);
      const fallbackEntries10s = zone.zone_id === 'detection_area'
        ? Number(this.state.advancedMetrics?.area_entries_10s)
        : NaN;
      const fallbackVisitors1m = zone.zone_id === 'detection_area'
        ? Number(this.state.advancedMetrics?.people_count_1m)
        : NaN;
      const metaParts = [zone.zone_id];
      const trackedTargets = Number(zone.target_count || 0);
      const countLabel = trackedTargets > 0
        ? tp('fp2.zone.targets', trackedTargets)
        : (zone.occupied ? t('fp2.layout.presence_only') : tp('fp2.zone.targets', 0));
      const countValue = trackedTargets > 0 ? trackedTargets : '—';
      if (Number.isFinite(entries10s)) {
        metaParts.push(t('fp2.count.entries_10s', { count: entries10s }));
      } else if (Number.isFinite(fallbackEntries10s) && fallbackEntries10s > 0) {
        metaParts.push(t('fp2.count.entries_10s', { count: fallbackEntries10s }));
      }
      if (Number.isFinite(visitors1m)) {
        metaParts.push(t('fp2.count.per_minute', { count: visitors1m }));
      } else if (Number.isFinite(fallbackVisitors1m) && fallbackVisitors1m > 0) {
        metaParts.push(t('fp2.count.per_minute', { count: fallbackVisitors1m }));
      }
      if (Number.isFinite(zone.suppressed_count) && zone.suppressed_count > 0) {
        metaParts.push(t('fp2.zone.suppressed', { count: zone.suppressed_count }));
      }
      return `
        <article class="fp2-zone-window ${zone.occupied ? 'active' : ''} ${isCurrent ? 'current' : ''}">
          <div class="fp2-zone-window-header">
            <h4>${zone.displayName}</h4>
            <span class="fp2-zone-window-status">${zone.occupied ? t('fp2.zone.occupied') : t('fp2.zone.clear')}</span>
          </div>
          <div class="fp2-zone-window-body">
            <span class="fp2-zone-window-count">${countValue}</span>
            <span class="fp2-zone-window-label">${countLabel}</span>
          </div>
          <div class="fp2-zone-window-meta">
            <span>${metaParts.join(' · ')}</span>
          </div>
        </article>`;
    }).join('');
  }

  renderZoneAnalytics(zones, currentZone, zoneMetrics = {}, options = {}) {
    const container = this.elements.zoneAnalytics;
    if (!container) return;

    const zoneMap = new Map((this.normalizeZones(zones || [])).map((zone) => [zone.zone_id, zone]));
    Object.keys(zoneMetrics || {}).forEach((zoneId) => {
      if (!zoneMap.has(zoneId)) {
        zoneMap.set(zoneId, {
          zone_id: zoneId,
          name: zoneId,
          displayName: this.displayZoneName(zoneId, this.state.zones),
          occupied: zoneId === 'detection_area' ? Boolean(this.state.currentPresenceActive) : false,
          target_count: 0
        });
      }
    });

    const analytics = Array.from(zoneMap.values())
      .map((zone, index) => {
        const metrics = zoneMetrics?.[zone.zone_id] || {};
        const trackedTargets = Number(zone.target_count || 0);
        const entries10sMetric = Number(metrics.people_entries_10s);
        const visitors1mMetric = Number(metrics.people_count_1m);
        const entries10s = Number.isFinite(entries10sMetric)
          ? entries10sMetric
          : (zone.zone_id === 'detection_area' && Number.isFinite(Number(this.state.advancedMetrics?.area_entries_10s))
              ? Number(this.state.advancedMetrics?.area_entries_10s)
              : 0);
        const visitors1m = Number.isFinite(visitors1mMetric)
          ? visitors1mMetric
          : (zone.zone_id === 'detection_area' && Number.isFinite(Number(this.state.advancedMetrics?.people_count_1m))
              ? Number(this.state.advancedMetrics?.people_count_1m)
              : 0);
        const suppressed = Number.isFinite(zone.suppressed_count) ? zone.suppressed_count : 0;
        const displayName = zone.displayName || this.formatZoneName(zone.zone_id, index);
        const isCurrent = currentZone && displayName === currentZone;
        return {
          zone_id: zone.zone_id,
          displayName,
          occupied: Boolean(zone.occupied),
          trackedTargets,
          entries10s,
          visitors1m,
          suppressed,
          isCurrent
        };
      })
      .filter((zone) => zone.occupied || zone.trackedTargets > 0 || zone.entries10s > 0 || zone.visitors1m > 0 || zone.zone_id === 'detection_area')
      .sort((left, right) => (
        Number(right.isCurrent) - Number(left.isCurrent)
        || Number(right.occupied) - Number(left.occupied)
        || right.entries10s - left.entries10s
        || right.visitors1m - left.visitors1m
        || right.trackedTargets - left.trackedTargets
        || left.displayName.localeCompare(right.displayName)
      ));

    if (!analytics.length) {
      container.innerHTML = `<div class="fp2-empty-state">${t('fp2.zone.analytics.empty')}</div>`;
      return;
    }

    container.innerHTML = analytics.map((zone) => `
      <article class="fp2-zone-analytics-item ${zone.occupied ? 'active' : ''} ${zone.isCurrent ? 'current' : ''}">
        <div class="fp2-zone-analytics-head">
          <div>
            <h4>${zone.displayName}</h4>
            <div class="fp2-zone-analytics-meta">${zone.zone_id}</div>
          </div>
          <div class="fp2-zone-analytics-badges">
            ${zone.isCurrent ? `<span class="chip chip--info">${t('fp2.zone.analytics.current')}</span>` : ''}
            <span class="chip ${zone.occupied ? 'ok' : 'chip--neutral'}">${zone.occupied ? t('fp2.zone.occupied') : t('fp2.zone.clear')}</span>
          </div>
        </div>
        <div class="fp2-zone-analytics-grid">
          <div class="fp2-zone-analytics-metric">
            <span class="fp2-zone-analytics-label">${t('fp2.zone.analytics.targets')}</span>
            <strong>${zone.trackedTargets}</strong>
          </div>
          <div class="fp2-zone-analytics-metric">
            <span class="fp2-zone-analytics-label">${t('fp2.zone.analytics.entries')}</span>
            <strong>${zone.entries10s}</strong>
          </div>
          <div class="fp2-zone-analytics-metric">
            <span class="fp2-zone-analytics-label">${t('fp2.zone.analytics.visitors')}</span>
            <strong>${zone.visitors1m}</strong>
          </div>
        </div>
        ${zone.suppressed > 0 ? `<div class="fp2-zone-analytics-foot">${t('fp2.zone.suppressed', { count: zone.suppressed })}</div>` : ''}
      </article>
    `).join('');
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
      this.state.lastRealtimePeopleCount = event.realtimePeopleCount ?? null;
      this.state.lastVisitors1m = event.visitors1m ?? null;
      this.state.lastAreaEntries10s = event.areaEntries10s ?? null;
      this.state.lastWalkingDistance = event.walkingDistance ?? null;
      if (event.presence) {
        this.recordPresenceEntry(Date.parse(event.timestamp) || Date.now());
        this.pushMovementEvent(event.timestamp, 'enter', t('fp2.event.presence_detected', {
          zone: event.zone || t('fp2.zone.detection_area')
        }));
      }
      return;
    }

    if (!prevPresence && event.presence) {
      this.recordPresenceEntry(Date.parse(event.timestamp) || Date.now());
      this.pushMovementEvent(event.timestamp, 'enter', t('fp2.event.entered', {
        zone: event.zone || t('fp2.zone.detection_area')
      }));
    } else if (prevPresence && !event.presence) {
      this.pushMovementEvent(event.timestamp, 'exit', t('fp2.event.left', {
        zone: prevZone || t('fp2.zone.detection_area')
      }));
    } else if (event.presence && prevZone && event.zone && prevZone !== event.zone) {
      this.pushMovementEvent(event.timestamp, 'move', t('fp2.event.transition', {
        from: prevZone,
        to: event.zone
      }));
    }

    if (event.movementEvent !== undefined && event.movementEvent !== this.state.lastMovementEvent) {
      let label = this.formatMovementEventAqaraStyle(event.movementEvent);
      if (event.movementEvent === 1 && this.state.currentSensorAngle !== null) {
        label += ` · ${Math.round(this.state.currentSensorAngle)}°`;
      }
      if ([5, 6, 7].includes(event.movementEvent)) {
        const active = this.state.targets.filter(t => this.hasCoordinates(t));
        if (active.length > 0) label += ` · ${tp('fp2.count.targets', active.length)}`;
      }
      this.pushMovementEvent(event.timestamp, 'telemetry', label);
    }

    if (event.fallState !== undefined && event.fallState !== this.state.lastFallState) {
      const fallLabel = this.formatFallStateCode(event.fallState);
      this.pushMovementEvent(event.timestamp, event.fallState ? 'alert' : 'telemetry', fallLabel);
    }

    if (event.targetCount !== undefined && event.targetCount !== this.state.lastTargetCount) {
      this.pushMovementEvent(event.timestamp, 'telemetry', t('fp2.event.target_count', {
        count: event.targetCount
      }));
    }

    if (event.realtimePeopleCount !== undefined && event.realtimePeopleCount !== this.state.lastRealtimePeopleCount) {
      this.pushMovementEvent(event.timestamp, 'telemetry', t('fp2.event.people_count_home', {
        count: event.realtimePeopleCount
      }));
    }

    if (event.visitors1m !== undefined && event.visitors1m !== this.state.lastVisitors1m) {
      this.pushMovementEvent(event.timestamp, 'telemetry', t('fp2.event.visitors_1m', {
        count: event.visitors1m
      }));
    }

    if (event.areaEntries10s !== undefined && event.areaEntries10s !== this.state.lastAreaEntries10s) {
      this.pushMovementEvent(event.timestamp, 'telemetry', t('fp2.count.entries_10s', {
        count: event.areaEntries10s
      }));
    }

    if (event.walkingDistance !== undefined && event.walkingDistance !== this.state.lastWalkingDistance) {
      this.pushMovementEvent(event.timestamp, 'telemetry', t('fp2.event.walking_distance', {
        distance: this.formatMeters(event.walkingDistance)
      }));
    }

    this.state.lastPresence = event.presence;
    this.state.currentZone = event.zone;
    this.state.lastMovementEvent = event.movementEvent ?? this.state.lastMovementEvent;
    this.state.lastFallState = event.fallState ?? this.state.lastFallState;
    this.state.lastTargetCount = event.targetCount ?? this.state.lastTargetCount;
    this.state.lastRealtimePeopleCount = event.realtimePeopleCount ?? this.state.lastRealtimePeopleCount;
    this.state.lastVisitors1m = event.visitors1m ?? this.state.lastVisitors1m;
    this.state.lastAreaEntries10s = event.areaEntries10s ?? this.state.lastAreaEntries10s;
    this.state.lastWalkingDistance = event.walkingDistance ?? this.state.lastWalkingDistance;
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
        <strong class="fp2-event fp2-event-${entry.type}">${this.formatEventType(entry.type)}</strong>`;
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
          ${entry.presence === null ? t('common.unavailable') : entry.presence ? t('common.present') : t('common.absent')}
        </strong>`;
      this.elements.historyList.appendChild(el);
    });
  }

  // ── Movement Map (enlarged, with trails) ──

  buildMapRenderSignature(displayTargets, allTargets = this.state.rawTargets) {
    const roomProfile = this.getActiveRoomProfile();
    const roomItems = this.getActiveRoomLayoutItems(roomProfile);
    const targetSig = (displayTargets || []).map((target) => [
      target.target_id,
      this.fmtCoord(target.x),
      this.fmtCoord(target.y),
      this.fmtDelta(target.dx),
      this.fmtDelta(target.dy),
      target.held ? 1 : 0
    ].join(':')).join('|');
    const rawSig = (allTargets || []).map((target) => [
      target.target_id,
      this.hasCoordinates(target) ? this.fmtCoord(target.x) : 'na',
      this.hasCoordinates(target) ? this.fmtCoord(target.y) : 'na',
      target.filtered_out ? 1 : 0
    ].join(':')).join('|');
    const zoneSig = (this.state.zones || []).map((zone) => [
      zone.zone_id,
      zone.occupied ? 1 : 0,
      zone.target_count || 0
    ].join(':')).join('|');
    const layoutSig = (roomItems || []).map((item) => [
      item.id,
      item.type,
      item.x,
      item.y,
      item.widthCm,
      item.depthCm,
      item.rotationDeg || 0
    ].join(':')).join('|');
    const trailLast = this.state.trailHistory?.[this.state.trailHistory.length - 1];
    const trailSig = trailLast ? `${trailLast.ts}:${trailLast.targets.length}` : 'none';

    return [
      this.state.currentPresenceActive ? 1 : 0,
      this.state.currentAvailability ? 1 : 0,
      this.state.currentSensorAngle ?? 'na',
      this.state.activeRoomProfileId,
      this.state.selectedRoomItemId || 'none',
      this.state.editLayoutMode ? 1 : 0,
      targetSig,
      rawSig,
      zoneSig,
      layoutSig,
      trailSig,
      this.hasFrozenCoordinates() ? 1 : 0
    ].join('~');
  }

  renderAnimatedMap(force = false) {
    if (!this.state.pageVisible && !force) {
      this.state.pendingVisualRefresh = true;
      return;
    }
    const displayTargets = this.hasFrozenCoordinates()
      ? (this.state.rawTargets || []).filter((target) => this.hasCoordinates(target))
      : this.getInterpolatedTargets();
    const signature = this.buildMapRenderSignature(displayTargets, this.state.rawTargets);
    if (!force && signature === this.state.lastMapSignature) {
      return;
    }
    this.state.lastMapSignature = signature;
    this.drawMovementMap(
      this.state.zones,
      this.state.currentPresenceActive,
      displayTargets,
      this.state.rawTargets,
      this.state.currentSensorAngle,
      this.state.currentAvailability
    );
  }

  drawMovementMap(zones, presence, targets, allTargets, sensorAngle, available) {
    const canvas = this.elements.movementCanvas;
    const ctx = this.canvasCtx;
    if (!canvas || !ctx) return;

    const { width, height } = this.prepareCanvasForDrawing(canvas, ctx);
    ctx.clearRect(0, 0, width, height);

    // Background
    ctx.fillStyle = '#0c1220';
    ctx.fillRect(0, 0, width, height);

    const coordTargets = targets.filter(t => this.hasCoordinates(t));
    const roomProfile = this.getActiveRoomProfile();
    if (coordTargets.length > 0 || roomProfile?.kind === 'fixed' || this.state.trailHistory.length > 0) {
      this.drawCoordinateMap(ctx, width, height, coordTargets, allTargets || [], sensorAngle, available, roomProfile, presence);
      return;
    }
    this.state.lastRoomProjection = null;

    // Zone-based fallback
    const zoneList = zones.length > 0 ? zones : [{
      displayName: t('fp2.zone.detection_area'),
      zone_id: 'detection_area',
      occupied: presence,
      target_count: 0
    }];
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
      ctx.fillText(active ? t('fp2.zone.occupied') : t('fp2.zone.clear'), x + 18, y + zoneHeight / 2 + 12);

      ctx.fillStyle = '#94a3b8';
      ctx.font = '13px sans-serif';
      ctx.fillText(
        zone.occupied && !(zone.target_count > 0)
          ? t('fp2.layout.presence_only')
          : tp('fp2.zone.targets', zone.target_count || 0),
        x + 18,
        y + zoneHeight / 2 + 40
      );

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
    ctx.fillText(available && presence ? t('fp2.zone.mode') : t('fp2.zone.room_clear'), width - 120, 22);
  }

  getFixedRoomProjection(width, height, profile) {
    const marginX = 42;
    const marginTop = 28;
    const marginBottom = 44;
    const availableWidth = width - marginX * 2;
    const availableHeight = height - marginTop - marginBottom - 18;
    const geometry = this.getActiveRoomGeometry(profile) || {
      minX: -(profile.widthCm / 2),
      maxX: profile.widthCm / 2,
      minY: 0,
      maxY: profile.depthCm,
      widthCm: profile.widthCm,
      depthCm: profile.depthCm
    };

    const scale = Math.min(
      availableWidth / Math.max(1, geometry.widthCm),
      availableHeight / Math.max(1, geometry.depthCm)
    );
    const rectWidth = Math.max(120, geometry.widthCm * scale);
    const rectHeight = Math.max(140, geometry.depthCm * scale);
    const roomRect = {
      x: marginX + (availableWidth - rectWidth) / 2,
      y: marginTop + 18 + (availableHeight - rectHeight) / 2,
      width: rectWidth,
      height: rectHeight
    };
    const minX = geometry.minX;
    const maxX = geometry.maxX;
    const minY = geometry.minY;
    const maxY = geometry.maxY;
    const toCanvasX = (x = 0) => roomRect.x + ((x - minX) / Math.max(1, maxX - minX)) * roomRect.width;
    const toCanvasY = (y = 0) => roomRect.y + roomRect.height - ((y - minY) / Math.max(1, maxY - minY)) * roomRect.height;

    return {
      roomRect,
      minX,
      maxX,
      minY,
      maxY,
      widthCm: geometry.widthCm,
      depthCm: geometry.depthCm,
      calibrated: Boolean(geometry.calibrated),
      originX: toCanvasX(0),
      originY: roomRect.y + roomRect.height,
      toCanvasX,
      toCanvasY
    };
  }

  drawRoomProfileShell(ctx, projection, profile, sensorAngle, available, presence) {
    const { roomRect, originX, originY, toCanvasY, widthCm, depthCm, calibrated } = projection;
    const accent = profile?.accent || '#38bdf8';
    const calibration = this.getCalibrationDraft(profile);

    this.drawRoundedRect(ctx, roomRect.x, roomRect.y, roomRect.width, roomRect.height, 18);
    ctx.fillStyle = available && presence ? 'rgba(34,211,238,0.06)' : 'rgba(15,23,42,0.55)';
    ctx.fill();
    ctx.lineWidth = 2;
    ctx.strokeStyle = `${accent}aa`;
    ctx.stroke();

    ctx.strokeStyle = 'rgba(148,163,184,0.10)';
    ctx.lineWidth = 1;
    for (let depth = 100; depth < depthCm; depth += 100) {
      const y = toCanvasY(depth);
      ctx.beginPath();
      ctx.moveTo(roomRect.x + 10, y);
      ctx.lineTo(roomRect.x + roomRect.width - 10, y);
      ctx.stroke();
    }

    ctx.fillStyle = '#f8fafc';
    ctx.font = '600 12px sans-serif';
    ctx.fillText(this.getRoomProfileLabel(profile), roomRect.x + 16, roomRect.y + 24);
    ctx.fillStyle = 'rgba(148,163,184,0.75)';
    ctx.font = '10px monospace';
    ctx.fillText(
      `${Math.round(widthCm)} × ${Math.round(depthCm)} cm${calibrated ? ` · ${t('fp2.layout.calibrated_short')}` : ''}`,
      roomRect.x + 16,
      roomRect.y + 40
    );

    if (Number.isFinite(calibration?.leftX)) {
      const x = projection.toCanvasX(calibration.leftX);
      ctx.strokeStyle = 'rgba(56,189,248,0.85)';
      ctx.lineWidth = 2;
      ctx.setLineDash([8, 5]);
      ctx.beginPath();
      ctx.moveTo(x, roomRect.y);
      ctx.lineTo(x, roomRect.y + roomRect.height);
      ctx.stroke();
      ctx.setLineDash([]);
    }

    if (Number.isFinite(calibration?.rightX)) {
      const x = projection.toCanvasX(calibration.rightX);
      ctx.strokeStyle = 'rgba(56,189,248,0.85)';
      ctx.lineWidth = 2;
      ctx.setLineDash([8, 5]);
      ctx.beginPath();
      ctx.moveTo(x, roomRect.y);
      ctx.lineTo(x, roomRect.y + roomRect.height);
      ctx.stroke();
      ctx.setLineDash([]);
    }

    if (Number.isFinite(calibration?.farY)) {
      const y = projection.toCanvasY(calibration.farY);
      ctx.strokeStyle = 'rgba(56,189,248,0.85)';
      ctx.lineWidth = 2;
      ctx.setLineDash([8, 5]);
      ctx.beginPath();
      ctx.moveTo(roomRect.x, y);
      ctx.lineTo(roomRect.x + roomRect.width, y);
      ctx.stroke();
      ctx.setLineDash([]);
    }

    ctx.fillStyle = '#6366f1';
    ctx.beginPath();
    ctx.arc(originX, originY, 6, 0, Math.PI * 2);
    ctx.fill();
    ctx.fillStyle = 'rgba(248,250,252,0.6)';
    ctx.font = '11px sans-serif';
    ctx.fillText(t('fp2.sensor_label'), originX - 18, originY + 22);

    if (Number.isFinite(sensorAngle)) {
      const rayLen = Math.min(roomRect.width * 0.42, roomRect.height * 0.92);
      const rad = sensorAngle * (Math.PI / 180);
      const rx = originX + Math.cos(rad) * rayLen;
      const ry = originY - Math.sin(rad) * rayLen;
      const fovHalf = 30 * (Math.PI / 180);

      ctx.fillStyle = 'rgba(250,204,21,0.05)';
      ctx.beginPath();
      ctx.moveTo(originX, originY);
      ctx.arc(originX, originY, rayLen, -(rad + fovHalf), -(rad - fovHalf));
      ctx.closePath();
      ctx.fill();

      ctx.strokeStyle = 'rgba(250,204,21,0.45)';
      ctx.lineWidth = 2;
      ctx.setLineDash([6, 4]);
      ctx.beginPath();
      ctx.moveTo(originX, originY);
      ctx.lineTo(rx, ry);
      ctx.stroke();
      ctx.setLineDash([]);
    }
  }

  drawRoomLayoutItems(ctx, projection, items = []) {
    if (!items.length) return;

    const { roomRect, widthCm, depthCm, toCanvasX, toCanvasY } = projection;
    const scaleX = roomRect.width / Math.max(1, widthCm);
    const scaleY = roomRect.height / Math.max(1, depthCm);

    items.forEach((item) => {
      const def = getRoomItemDefinition(item.type);
      const width = Math.max(10, item.widthCm * scaleX);
      const depth = Math.max(10, item.depthCm * scaleY);
      const centerX = toCanvasX(item.x);
      const centerY = toCanvasY(item.y);
      const isSelected = item.id === this.state.selectedRoomItemId;
      const icon = this.getRoomItemIcon(item);

      ctx.save();
      ctx.translate(centerX, centerY);
      if (item.rotationDeg) {
        ctx.rotate((item.rotationDeg * Math.PI) / 180);
      }

      if (item.type === 'plant' || item.type === 'lamp') {
        ctx.fillStyle = `${def.accent}33`;
        ctx.beginPath();
        ctx.arc(0, 0, Math.max(width, depth) / 2, 0, Math.PI * 2);
        ctx.fill();
        ctx.strokeStyle = `${def.accent}cc`;
        ctx.lineWidth = 1.5;
        ctx.stroke();
      } else if (item.type === 'door' || item.type === 'curtain' || item.type === 'tv') {
        ctx.strokeStyle = `${def.accent}dd`;
        ctx.lineWidth = Math.max(3, depth);
        ctx.beginPath();
        ctx.moveTo(-width / 2, 0);
        ctx.lineTo(width / 2, 0);
        ctx.stroke();
      } else {
        this.drawRoundedRect(ctx, -width / 2, -depth / 2, width, depth, 10);
        ctx.fillStyle = `${def.accent}26`;
        ctx.fill();
        ctx.strokeStyle = isSelected ? '#f8fafc' : `${def.accent}cc`;
        ctx.lineWidth = isSelected ? 2 : 1.5;
        ctx.stroke();
      }

      const minBox = Math.min(width, depth);
      const iconFontPx = Math.max(13, Math.min(20, Math.round(minBox / 3.1)));
      const labelFontPx = Math.max(11, Math.min(15, Math.round(minBox / 4.2)));
      const showInlineLabel = !['door', 'curtain', 'tv'].includes(item.type)
        && (isSelected || (width >= 120 && depth >= 58));

      ctx.fillStyle = '#e2e8f0';
      ctx.font = `600 ${iconFontPx}px sans-serif`;
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      ctx.shadowColor = 'rgba(8, 15, 28, 0.85)';
      ctx.shadowBlur = 6;
      ctx.fillText(icon, 0, showInlineLabel ? -8 : 0);

      if (showInlineLabel) {
        ctx.font = `600 ${labelFontPx}px sans-serif`;
        const label = this.fitCanvasText(ctx, this.getRoomItemLabel(item), Math.max(40, width - 18));
        const labelY = Math.min(depth / 2 - 12, 18);
        const textMetrics = ctx.measureText(label);
        const backgroundWidth = Math.max(30, textMetrics.width + 14);
        const backgroundHeight = labelFontPx + 8;
        ctx.fillStyle = 'rgba(8, 15, 28, 0.72)';
        this.drawRoundedRect(
          ctx,
          -backgroundWidth / 2,
          labelY - backgroundHeight / 2,
          backgroundWidth,
          backgroundHeight,
          8
        );
        ctx.fill();
        ctx.strokeStyle = 'rgba(255, 255, 255, 0.08)';
        ctx.lineWidth = 1;
        ctx.stroke();
        ctx.fillStyle = '#e2e8f0';
        ctx.fillText(label, 0, labelY + 1);
      }
      ctx.shadowBlur = 0;

      if (isSelected) {
        ctx.strokeStyle = 'rgba(248,250,252,0.85)';
        ctx.lineWidth = 1.5;
        ctx.setLineDash([5, 4]);
        this.drawRoundedRect(ctx, -width / 2 - 4, -depth / 2 - 4, width + 8, depth + 8, 12);
        ctx.stroke();
        ctx.setLineDash([]);

        ctx.fillStyle = '#f8fafc';
        ctx.fillRect(width / 2 - 10, depth / 2 - 10, 12, 12);
      }
      ctx.restore();
    });
    ctx.textAlign = 'left';
    ctx.textBaseline = 'alphabetic';
    ctx.font = '12px sans-serif';
  }

  drawCoordinateMap(ctx, width, height, targets, allTargets, sensorAngle, available, roomProfile, presence) {
    if (roomProfile?.kind === 'fixed') {
      const projection = this.getFixedRoomProjection(width, height, roomProfile);
      this.state.lastRoomProjection = projection;
      const { roomRect, originX, originY, toCanvasX, toCanvasY } = projection;
      const suppressedTargets = (allTargets || []).filter((target) => target.filtered_out && this.hasCoordinates(target));
      const roomItems = this.getActiveRoomLayoutItems(roomProfile);
      const recentTrace =
        targets.length === 0 &&
        this.state.lastCoordinateSeenAtMs &&
        (Date.now() - this.state.lastCoordinateSeenAtMs) <= 20000 &&
        this.state.trailHistory.length > 0;

      this.drawRoomProfileShell(ctx, projection, roomProfile, sensorAngle, available, presence);
      this.drawRoomLayoutItems(ctx, projection, roomItems);

      const trail = this.state.trailHistory;
      if (trail.length > 1) {
        const byId = new Map();
        trail.forEach(snapshot => {
          snapshot.targets.forEach(target => {
            if (!byId.has(target.id)) byId.set(target.id, []);
            byId.get(target.id).push(target);
          });
        });

        let colorIndex = 0;
        byId.forEach(points => {
          if (points.length < 2) {
            colorIndex++;
            return;
          }

          const color = TARGET_COLORS[colorIndex % TARGET_COLORS.length];
          colorIndex++;
          for (let i = 1; i < points.length; i++) {
            const opacity = 0.06 + (i / points.length) * 0.2;
            ctx.globalAlpha = opacity;
            ctx.strokeStyle = color;
            ctx.lineWidth = 1.4;
            ctx.beginPath();
            ctx.moveTo(toCanvasX(points[i - 1].x), toCanvasY(points[i - 1].y));
            ctx.lineTo(toCanvasX(points[i].x), toCanvasY(points[i].y));
            ctx.stroke();
          }
          ctx.globalAlpha = 1;
        });
      }

      targets.forEach((target, i) => {
        const px = toCanvasX(target.x);
        const py = toCanvasY(target.y);
        const color = TARGET_COLORS[i % TARGET_COLORS.length];

        ctx.strokeStyle = `${color}55`;
        ctx.lineWidth = 1.5;
        ctx.beginPath();
        ctx.moveTo(originX, originY);
        ctx.lineTo(px, py);
        ctx.stroke();

        const gradient = ctx.createRadialGradient(px, py, 0, px, py, 20);
        gradient.addColorStop(0, `${color}40`);
        gradient.addColorStop(1, `${color}00`);
        ctx.fillStyle = gradient;
        ctx.beginPath();
        ctx.arc(px, py, 20, 0, Math.PI * 2);
        ctx.fill();

        ctx.fillStyle = color;
        ctx.beginPath();
        ctx.arc(px, py, i === 0 ? 8 : 6, 0, Math.PI * 2);
        ctx.fill();
        ctx.strokeStyle = '#fff';
        ctx.lineWidth = 1.5;
        ctx.stroke();
        this.drawCanvasTextBubble(
          ctx,
          px,
          py,
          [
            String(target.target_id || `target_${i}`),
            `${Math.round(target.distance || 0)} cm · ${Math.round(target.angle || 0)}°`
          ],
          {
            bounds: {
              left: roomRect.x + 8,
              right: roomRect.x + roomRect.width - 8,
              top: roomRect.y + 8,
              bottom: roomRect.y + roomRect.height - 8
            }
          }
        );
      });

      suppressedTargets.forEach((target) => {
        const px = toCanvasX(target.x);
        const py = toCanvasY(target.y);

        ctx.setLineDash([4, 4]);
        ctx.strokeStyle = 'rgba(248,113,113,0.55)';
        ctx.lineWidth = 1.5;
        ctx.beginPath();
        ctx.moveTo(originX, originY);
        ctx.lineTo(px, py);
        ctx.stroke();
        ctx.setLineDash([]);

        ctx.strokeStyle = 'rgba(248,113,113,0.9)';
        ctx.lineWidth = 2;
        ctx.beginPath();
        ctx.arc(px, py, 7, 0, Math.PI * 2);
        ctx.stroke();

        ctx.fillStyle = 'rgba(248,113,113,0.8)';
        ctx.font = '10px monospace';
        ctx.fillText(t('fp2.target.class.animal_like'), px + 10, py - 8);
      });

      ctx.fillStyle = available
        ? (targets.length > 0 ? 'rgba(74,222,128,0.9)' : 'rgba(251,191,36,0.9)')
        : 'rgba(248,113,113,0.9)';
      ctx.font = '700 12px monospace';
      ctx.textAlign = 'right';
      ctx.fillText(
        available
          ? (targets.length > 0
            ? t('fp2.zone.coordinate_mode', { targets: tp('fp2.count.targets', targets.length) })
            : (recentTrace
              ? t('fp2.layout.recent_trace')
              : (presence ? t('fp2.layout.presence_only') : t('fp2.zone.room_clear'))))
          : t('fp2.zone.targets_unavailable'),
        width - 16,
        22
      );
      ctx.textAlign = 'left';

      ctx.fillStyle = 'rgba(148,163,184,0.45)';
      ctx.font = '9px monospace';
      ctx.fillText('+Y', originX + 4, roomRect.y + 10);
      ctx.fillText('+X', roomRect.x + roomRect.width - 18, originY - 6);
      ctx.fillText('-X', roomRect.x + 6, originY - 6);
      return;
    }

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
    ctx.fillText(t('fp2.sensor_label'), originX - 18, originY + 20);

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
      this.drawCanvasTextBubble(
        ctx,
        px,
        py,
        [
          String(target.target_id || `target_${i}`),
          `${Math.round(target.distance || 0)} cm · ${Math.round(target.angle || 0)}°`
        ],
        {
          bounds: {
            left: plotLeft + 6,
            right: plotLeft + plotWidth - 6,
            top: plotTop + 6,
            bottom: plotTop + plotHeight - 6
          }
        }
      );
    });

    // Status badge
    ctx.fillStyle = available ? 'rgba(74,222,128,0.9)' : 'rgba(248,113,113,0.9)';
    ctx.font = '700 12px monospace';
    ctx.textAlign = 'right';
    ctx.fillText(
      available
        ? t('fp2.zone.coordinate_mode', { targets: tp('fp2.count.targets', targets.length) })
        : t('fp2.zone.targets_unavailable'),
      width - 16,
      22
    );
    ctx.textAlign = 'left';

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
    if (!this.state.pageVisible) return;
    const now = Date.now();
    this.renderLoopUntilMs = Math.max(this.renderLoopUntilMs, now + Math.max(0, durationMs));
    if (this.graphAnimationId) return;

    const animate = () => {
      if (!this.state.pageVisible) {
        this.graphAnimationId = null;
        return;
      }
      const frameNow = Date.now();
      if (!this.state.lastGraphDrawAtMs || (frameNow - this.state.lastGraphDrawAtMs) >= 400) {
        this.drawRealtimeGraph();
        this.state.lastGraphDrawAtMs = frameNow;
      }
      this.renderAnimatedMap(true);
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
    if (this.state.pageVisible) {
      this.drawRealtimeGraph();
    } else {
      this.state.pendingVisualRefresh = true;
    }
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
    ctx.fillText(t('fp2.legend.present'), 8, 15);
    ctx.fillText(t('fp2.legend.absent'), 8, height - 6);

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

  drawCoordinateQualityGraph() {
    const canvas = this.coordinateQualityCanvas;
    const ctx = this.coordinateQualityCtx;
    if (!canvas || !ctx) return;

    const width = canvas.width;
    const height = canvas.height;
    ctx.clearRect(0, 0, width, height);
    ctx.fillStyle = '#101722';
    ctx.fillRect(0, 0, width, height);

    ctx.strokeStyle = 'rgba(255,255,255,0.06)';
    ctx.lineWidth = 1;
    for (let i = 0; i < 4; i += 1) {
      const y = 10 + ((height - 20) / 3) * i;
      ctx.beginPath();
      ctx.moveTo(0, y);
      ctx.lineTo(width, y);
      ctx.stroke();
    }

    ctx.fillStyle = 'rgba(255,255,255,0.42)';
    ctx.font = '10px Inter, sans-serif';
    ctx.fillText(t('fp2.coordinate.quality_axis.low'), 8, height - 6);
    ctx.fillText(t('fp2.coordinate.quality_axis.high'), 8, 12);

    const points = this.state.coordinateHealthHistory || [];
    if (points.length < 2) return;

    const minTs = points[0].ts;
    const maxTs = points[points.length - 1].ts || (minTs + 1);
    const span = Math.max(1, maxTs - minTs);
    const yForScore = (score) => {
      const normalized = Math.max(0, Math.min(3, score)) / 3;
      return height - 10 - normalized * (height - 20);
    };

    points.forEach((point) => {
      if (!point.updated) return;
      const x = ((point.ts - minTs) / span) * width;
      ctx.strokeStyle = 'rgba(74, 222, 128, 0.28)';
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(x, height - 8);
      ctx.lineTo(x, 8);
      ctx.stroke();
    });

    ctx.strokeStyle = '#38bdf8';
    ctx.lineWidth = 2;
    ctx.beginPath();
    points.forEach((point, index) => {
      const x = ((point.ts - minTs) / span) * width;
      const y = yForScore(point.score);
      if (index === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    });
    ctx.stroke();

    const last = points[points.length - 1];
    const lastX = ((last.ts - minTs) / span) * width;
    const lastY = yForScore(last.score);
    ctx.fillStyle = last.score >= 2.4 ? '#4ade80' : last.score >= 1.2 ? '#facc15' : '#f87171';
    ctx.beginPath();
    ctx.arc(lastX, lastY, 3.5, 0, Math.PI * 2);
    ctx.fill();
  }

  // ── Formatting helpers ──

  formatZoneName(zoneId, index) {
    if (!zoneId) return `Zone ${index + 1}`;
    if (zoneId === 'detection_area') return t('fp2.zone.detection_area');
    if (/^occupancy_\d+$/i.test(zoneId)) return `Zone ${index + 1}`;
    const match = String(zoneId).match(/^zone[_-]?(\d+)$/i);
    if (match) return t('fp2.zone.generic', { number: match[1] });
    return zoneId.replace(/^zone[_-]?/i, '').replace(/[_-]+/g, ' ').replace(/\s+/g, ' ').trim();
  }

  formatTransport(transport) {
    const normalized = String(transport || '').replace(/_/g, ' ').trim().toLowerCase();
    if (!normalized) return t('transport.fp2');
    if (normalized === 'aqara cloud') return t('transport.aqara_cloud');
    if (normalized === 'homekit / hap') return t('transport.homekit_hap');
    return String(transport).replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
  }

  formatSource(source, transport) {
    const normalizedSource = String(source || '').replace(/\s+/g, ' ').trim().toLowerCase();
    const normalizedTransport = String(transport || '').replace(/_/g, ' ').trim().toLowerCase();

    if (normalizedSource === 'aqara_cloud' || normalizedSource === 'aqara cloud') {
      return 'aqara_cloud';
    }
    if (normalizedSource === 'homekit_hap' || normalizedSource === 'homekit / hap') {
      return 'homekit_hap';
    }
    if (!normalizedSource || normalizedSource === 'fp2') {
      if (normalizedTransport === 'aqara cloud') return 'aqara_cloud';
      if (normalizedTransport === 'homekit / hap') return 'homekit_hap';
      return 'fp2';
    }

    return String(source).replace(/\s+/g, '_').toLowerCase();
  }

  formatConnectionState(state) {
    if (!state) return '-';
    if (state === 'live') return t('fp2.connection_state.live');
    if (state === 'waiting_for_hap_push') return t('fp2.connection_state.waiting_for_hap_push');
    if (state === 'connected') return t('fp2.stream.connected');
    if (state === 'polling') return t('fp2.stream.polling');
    if (state === 'error') return t('fp2.stream.error');
    if (state === 'offline') return t('fp2.stream.offline');
    if (state === 'stale') return t('common.stale');
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

  getLocale() {
    return document.documentElement.lang === 'ru' ? 'ru-RU' : 'en-US';
  }

  formatTimestamp(timestamp) {
    if (!timestamp) return new Date().toLocaleTimeString(this.getLocale());
    const d = new Date(timestamp);
    return Number.isNaN(d.getTime())
      ? new Date().toLocaleTimeString(this.getLocale())
      : d.toLocaleTimeString(this.getLocale());
  }

  formatDeviceTimestamp(ts) {
    if (!Number.isFinite(ts)) return '-';
    const d = new Date(ts * 1000);
    if (Number.isNaN(d.getTime())) return '-';
    const ageSec = (Date.now() - d.getTime()) / 1000;
    return `${d.toLocaleTimeString(this.getLocale())} (${this.formatAgeSeconds(ageSec, true)})`;
  }

  formatOnlineState(online) { return online === true ? t('common.online') : online === false ? t('common.offline') : '-'; }
  formatDbm(v) { return Number.isFinite(v) ? `${Math.round(v)} dBm` : '-'; }
  formatDegrees(v) { return Number.isFinite(v) ? `${Math.round(v)}°` : '-'; }
  formatDistance(v) { return Number.isFinite(v) ? `${v.toFixed(1)} cm` : '-'; }
  formatAngle(v) { return Number.isFinite(v) ? `${v.toFixed(1)}°` : '-'; }
  formatMeters(v) { return Number.isFinite(v) ? `${v.toFixed(v >= 10 ? 0 : 1)} m` : '-'; }
  fmtCoord(v) { return Number.isFinite(v) ? `${Math.round(v)}` : '-'; }
  fmtDelta(v) { return Number.isFinite(v) ? `${v >= 0 ? '+' : ''}${Math.round(v)}` : '-'; }

  formatMovementEventCode(v) {
    if (v === null || v === undefined || v === '') return '-';
    const labelKey = MOVEMENT_LABELS[v];
    return labelKey ? `${t(labelKey)} (${v})` : t('fp2.state.code', { code: v });
  }

  formatMovementEventAqaraStyle(v) {
    if (v === null || v === undefined || v === '') return '-';
    const key = {
      0: 'fp2.event.aqara.entered',
      1: 'fp2.event.aqara.left',
      2: 'fp2.event.aqara.entered_left',
      3: 'fp2.event.aqara.exited_right',
      4: 'fp2.event.aqara.entered_right',
      5: 'fp2.event.aqara.exited_left',
      6: 'fp2.event.aqara.approaching',
      7: 'fp2.event.aqara.departing'
    }[Number(v)];
    return key ? t(key) : this.formatMovementEventCode(v);
  }

  formatFallStateCode(v) {
    if (v === null || v === undefined || v === '') return '-';
    const labelKey = FALL_LABELS[v];
    return labelKey ? `${t(labelKey)} (${v})` : t('fp2.state.code', { code: v });
  }

  formatTargetClassification(value) {
    if (!value) return t('fp2.target.class.uncertain');
    return t(`fp2.target.class.${value}`);
  }

  formatAgeSeconds(ageSec, withAgo = false) {
    if (!Number.isFinite(ageSec)) return '-';
    const rounded = ageSec.toFixed(ageSec < 10 ? 1 : 0);
    return withAgo
      ? t('common.seconds_ago', { count: rounded })
      : t('common.seconds_short', { count: rounded });
  }

  getPacketAge(pushTime) {
    if (!Number.isFinite(pushTime)) return '-';
    const ageSec = Math.max(0, Date.now() / 1000 - pushTime);
    return this.formatAgeSeconds(ageSec);
  }

  resolveSampleTimestampMs(iso, devTs) {
    const parsed = iso ? Date.parse(iso) : NaN;
    if (Number.isFinite(parsed)) return parsed;
    if (Number.isFinite(devTs)) return devTs * 1000;
    return Date.now();
  }

  getPresenceDuration() {
    if (!this.state.presenceStartedAt) return t('common.seconds_short', { count: 0 });
    const sec = Math.max(0, Math.floor((Date.now() - this.state.presenceStartedAt) / 1000));
    const m = Math.floor(sec / 60);
    const s = sec % 60;
    if (m === 0) {
      return t('common.seconds_short', { count: s });
    }
    return t('common.minutes_seconds', { minutes: m, seconds: s });
  }

  resourceLabel(rid, fallbackLabel) {
    const key = RESOURCE_LABELS[rid];
    if (key) return t(key);
    const zoneLabel = this.resourceZoneLabel(rid);
    if (zoneLabel) return zoneLabel;
    return fallbackLabel || rid;
  }

  resourceZoneLabel(rid) {
    const zoneEntryMatch = String(rid || '').match(ZONE_ENTRY_RESOURCE_PREFIX);
    if (zoneEntryMatch) {
      const zoneMetricId = Number(zoneEntryMatch[1]);
      if (zoneMetricId > ZONE_ENTRY_RESOURCE_BASE && zoneMetricId <= ZONE_ENTRY_RESOURCE_BASE + 30) {
        return t('fp2.resource.zone_entries_10s', { number: zoneMetricId - ZONE_ENTRY_RESOURCE_BASE });
      }
    }

    const zoneVisitorMatch = String(rid || '').match(ZONE_VISITOR_RESOURCE_PREFIX);
    if (zoneVisitorMatch) {
      const zoneMetricId = Number(zoneVisitorMatch[1]);
      if (zoneMetricId > ZONE_ENTRY_RESOURCE_BASE && zoneMetricId <= ZONE_ENTRY_RESOURCE_BASE + 30) {
        return t('fp2.resource.zone_visitors_1m', { number: zoneMetricId - ZONE_ENTRY_RESOURCE_BASE });
      }
    }

    return null;
  }

  formatEventType(type) {
    return t(`fp2.event_type.${type}`);
  }

  handleLanguageChange() {
    this.renderRoomProfileControls();
    this.updateStreamState(this.state.streamState);
    if (this.lastStatus) {
      this.loadStatus().catch(() => {});
    }
    if (this.lastCurrentData) {
      this.renderCurrent(this.lastCurrentData);
    }
  }

  // ── Lifecycle ──

  startPolling() {
    this.stopPolling();
    this.pollTimer = setInterval(async () => {
      if (!this.isPageVisible()) return;
      await this.loadStatus();
      const transport = String(this.state.connection?.transport || this.state.device?.transport || '').toLowerCase();
      const shouldPollCurrent = this.state.streamState !== 'live' || transport === 'aqara_cloud';
      if (shouldPollCurrent) {
        await this.loadCurrent();
      }
    }, 3000);
  }

  stopPolling() { if (this.pollTimer) { clearInterval(this.pollTimer); this.pollTimer = null; } }

  startDurationTicker() {
    this.stopDurationTicker();
    this.durationTimer = setInterval(() => {
      if (!this.isPageVisible()) return;
      this.elements.presenceDuration.textContent = this.getPresenceDuration();
      if (this.elements.homePresenceDuration) {
        this.elements.homePresenceDuration.textContent = this.getPresenceDuration();
      }
    }, 1000);
  }

  stopDurationTicker() { if (this.durationTimer) { clearInterval(this.durationTimer); this.durationTimer = null; } }

  dispose() {
    this.stopPolling();
    this.stopDurationTicker();
    if (this.roomConfigSaveTimer) {
      clearTimeout(this.roomConfigSaveTimer);
      this.roomConfigSaveTimer = null;
    }
    this.stopGraphAnimation();
    fp2Service.stopStream();
    if (this.unsubscribe) { this.unsubscribe(); this.unsubscribe = null; }
    if (this.languageListener) {
      document.removeEventListener('fp2:languagechange', this.languageListener);
      this.languageListener = null;
    }
    if (this.visibilityListener) {
      document.removeEventListener('visibilitychange', this.visibilityListener);
      this.visibilityListener = null;
    }
  }
}
