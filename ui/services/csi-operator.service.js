import { API_CONFIG } from '../config/api.config.js';
import { NODES as CANONICAL_GARAGE_NODES } from '../config/garage-layout-v3.js';
import { apiService } from './api.service.js';
import { healthService } from './health.service.js';
import { GUIDED_CAPTURE_PACKS, getGuidedCapturePack } from '../data/guided-capture-packs.js';
import { FEWSHOT_CALIBRATION_PROTOCOLS, getFewshotCalibrationProtocol } from '../data/fewshot-calibration-protocol.js';
import {
  buildManualCaptureLabel,
  buildManualCaptureNotes,
  getManualCapturePreset,
  getManualCapturePresetVariant
} from '../data/manual-capture-presets.js';

const KNOWN_RUNTIME_NODES = CANONICAL_GARAGE_NODES.map((node) => ({ id: node.id, ip: node.ip }));
const NODE_ORDER = KNOWN_RUNTIME_NODES.map((node) => node.id);
const NODE_IP_TO_ID = Object.fromEntries(KNOWN_RUNTIME_NODES.map((node) => [node.ip, node.id]));
const DEFAULT_VISIBLE_NODE_COUNT = Math.max(CANONICAL_GARAGE_NODES.length, 7);
const DEFAULT_GARAGE_LAYOUT = {
  // Garage Planner v3 (2026-03-26): 3×7m, single door 2.4m at bottom.
  // Backend uses center-based X: x ∈ [-1.5, +1.5]. Y: 0=door, 7=deep end.
  widthMeters: 3.0,
  heightMeters: 7.0,
  door: { xMeters: 0.0, yMeters: 0.0 },
  zones: {
    doorMaxY: 3.5,
    deepMinY: 5.0
  },
  nodes: [
    // Center-based coords (matching backend): x = planner_x - 1.5
    { nodeId: 'node01', ip: '192.168.1.137', xMeters: -1.50, yMeters: 0.55, zone: 'door' },
    { nodeId: 'node02', ip: '192.168.1.117', xMeters: 1.50, yMeters: 0.55, zone: 'door' },
    { nodeId: 'node03', ip: '192.168.1.101', xMeters: -1.50, yMeters: 3.15, zone: 'door' },
    { nodeId: 'node04', ip: '192.168.1.125', xMeters: 1.50, yMeters: 2.50, zone: 'door' },
    { nodeId: 'node05', ip: '192.168.1.33',  xMeters: 0.00, yMeters: 3.50, zone: 'center' },
    { nodeId: 'node06', ip: '192.168.1.77',  xMeters: -1.50, yMeters: 4.35, zone: 'center' },
    { nodeId: 'node07', ip: '192.168.1.41',  xMeters: 1.50, yMeters: 3.70, zone: 'center' }
  ]
};
const CSI_ENDPOINTS = API_CONFIG?.ENDPOINTS?.CSI || {};
const CSI_STATUS_ENDPOINT = CSI_ENDPOINTS.STATUS || '/api/v1/csi/status';
const CSI_MODELS_ENDPOINT = CSI_ENDPOINTS.MODELS || '/api/v1/csi/models';
const CSI_MODEL_SELECT_ENDPOINT = CSI_ENDPOINTS.MODEL_SELECT || '/api/v1/csi/model/select';
const CSI_VALIDATION_ENDPOINTS = CSI_ENDPOINTS.VALIDATION || {
  STATUS: '/api/v1/csi/validation/status',
  RESOLVE: '/api/v1/csi/validation/resolve',
  BATCH_APPROVE: '/api/v1/csi/validation/batch-approve',
  SEGMENT: '/api/v1/csi/validation/segment/{segment_id}'
};
const CSI_ZONE_ENDPOINTS = CSI_ENDPOINTS.ZONE || {
  STATUS: '/api/v1/csi/zone/status',
  START: '/api/v1/csi/zone/calibrate/start',
  STOP: '/api/v1/csi/zone/calibrate/stop',
  FIT: '/api/v1/csi/zone/calibrate/fit',
  RESET: '/api/v1/csi/zone/calibrate/reset'
};
const CSI_FEWSHOT_ENDPOINTS = CSI_ENDPOINTS.FEWSHOT || {
  STATUS: '/api/v1/csi/fewshot/status',
  START: '/api/v1/csi/fewshot/session/start',
  STEP_START: '/api/v1/csi/fewshot/session/step/start',
  STEP_COMPLETE: '/api/v1/csi/fewshot/session/step/complete',
  FINALIZE: '/api/v1/csi/fewshot/session/finalize',
  RESET: '/api/v1/csi/fewshot/session/reset'
};
const CSI_TTS_ENDPOINTS = CSI_ENDPOINTS.TTS || {
  STATUS: '/api/v1/csi/tts/status',
  SPEAK: '/api/v1/csi/tts/speak',
  STOP: '/api/v1/csi/tts/stop'
};
const CSI_RECORD_ENDPOINTS = CSI_ENDPOINTS.RECORD || {
  PREFLIGHT: '/api/v1/csi/record/preflight',
  START: '/api/v1/csi/record/start',
  STOP: '/api/v1/csi/record/stop',
  STATUS: '/api/v1/csi/record/status'
};
const DEFAULT_POLLING = {
  csi: 500,
  pose: 1000,
  status: 15000,
  metrics: 10000,
  info: 60000,
  runtimeModels: 60000,
  forensicRuns: 30000,
  recording: 2000,
  validation: 15000
};
const STARTUP_SIGNAL_GUARD_DEFAULTS = {
  graceSec: 6,
  minActiveCoreNodes: 3,
  minPackets: 20,
  minPps: 5
};
const OPERATOR_PRESENCE_GATE = {
  confirmMotionWindows: 3,
  clearNoMotionWindows: 2,
  staleWindowAgeSec: 8,
  minNodesActive: 3
};
const MULTI_PERSON_AMBIGUITY_SCORE_THRESHOLD = 0.55;
const MULTI_PERSON_AMBIGUITY_RISK_TOKENS = ['collapse', 'ambigu', 'multi_person', 'multiperson'];
const ACTIVE_GUIDED_STATUSES = ['cueing', 'running', 'paused', 'stopping'];
const DEFAULT_GUIDED_COUNTDOWN_SEC = 4;
const TEACHER_SOURCE_KINDS = {
  PIXEL_RTSP: 'pixel_rtsp',
  MAC_CAMERA: 'mac_camera',
  NONE: 'none'
};
const DEFAULT_PIXEL_RTSP_URL = 'rtsp://admin:admin@192.168.1.148:8554/live';
const DEFAULT_PIXEL_RTSP_NAME = 'Pixel 8 Pro';
const DEFAULT_MAC_CAMERA_DEVICE = '0';
const DEFAULT_MAC_CAMERA_DEVICE_NAME = 'Mac Camera (device 0)';
const DEFAULT_TEACHER_INPUT_PIXEL_FORMAT = 'nv12';

function nodeOrderIndex(nodeId) {
  const index = NODE_ORDER.indexOf(nodeId);
  return index === -1 ? NODE_ORDER.length + 100 : index;
}

function isLocalHostname(hostname) {
  return ['127.0.0.1', 'localhost', '0.0.0.0'].includes(hostname);
}

function asArray(value) {
  return Array.isArray(value) ? value : [];
}

function safeNumber(value, fallback = null) {
  return Number.isFinite(Number(value)) ? Number(value) : fallback;
}

function getTopProbability(probabilities) {
  if (!probabilities || typeof probabilities !== 'object') {
    return { label: null, confidence: null };
  }

  let topLabel = null;
  let topConfidence = null;
  for (const [label, value] of Object.entries(probabilities)) {
    const confidence = safeNumber(value);
    if (confidence == null) {
      continue;
    }
    if (topConfidence == null || confidence > topConfidence) {
      topLabel = label;
      topConfidence = confidence;
    }
  }

  return {
    label: topLabel,
    confidence: topConfidence
  };
}

function clamp(value, min, max) {
  return Math.min(max, Math.max(min, value));
}

function nowIso() {
  return new Date().toISOString();
}

function delay(ms) {
  return new Promise((resolve) => {
    window.setTimeout(resolve, ms);
  });
}

function makeManualRecordingLabel() {
  return `manual_${nowIso()
    .replace(/\.\d{3}Z$/, '')
    .replaceAll('-', '')
    .replaceAll(':', '')
    .replace('T', '_')}`;
}

function makeFreeformRecordingLabel(personCount = 1) {
  const stamp = nowIso()
    .replace(/\.\d{3}Z$/, '')
    .replaceAll('-', '')
    .replaceAll(':', '')
    .replace('T', '_');
  const countToken = Number(personCount) >= 3 ? 'p3plus' : `p${Math.max(1, Number(personCount) || 1)}`;
  return `freeform_${countToken}_${stamp}`;
}

function getFreeformRoleHint(personCount = 1) {
  return Number(personCount) > 1
    ? 'runtime_acceptance / forensic_reference'
    : 'freeform_single_person';
}

function buildFreeformNotes(freeform) {
  const personCount = Math.max(1, Number(freeform?.personCount) || 1);
  const roleHint = Number(personCount) > 1
    ? 'runtime_acceptance|forensic_reference'
    : 'freeform_single_person';
  const parts = [
    'mode=freeform',
    `person_count=${personCount}`,
    'motion_type=freeform_single_person',
    `role_hint=${roleHint}`
  ];
  const extraNotes = String(freeform?.notes || '').trim();
  if (extraNotes) {
    parts.push(extraNotes);
  }
  return parts.join(', ');
}

function buildFreeformStopSummary(result, recording) {
  const status = recording?.status || {};
  const freeform = recording?.freeform || {};
  return {
    label: result?.label || status.label || freeform.label || null,
    durationSec: safeNumber(result?.duration_sec),
    totalChunks: safeNumber(result?.total_chunks),
    totalPackets: safeNumber(result?.total_packets),
    nodePackets: result?.node_packets || null,
    lastChunk: result?.last_chunk || null,
    withVideo: true,
    personCount: Math.max(1, Number(status.person_count || freeform.personCount) || 1),
    motionType: status.motion_type || 'freeform_single_person',
    stoppedAt: nowIso()
  };
}

function normalizeStartupSignalGuard(rawGuard, recordingStatus = null, lastStopResult = null) {
  const guard = rawGuard && typeof rawGuard === 'object' ? rawGuard : {};
  const stopReason = lastStopResult?.stopReason
    || lastStopResult?.stop_reason
    || lastStopResult?.reason
    || recordingStatus?.stop_reason
    || guard.stop_reason
    || null;
  const status = String(guard.status || guard.verdict || '').trim().toLowerCase();
  const passed = Boolean(
    guard.passed
    || status === 'passed'
    || status === 'pass'
    || status === 'ready'
    || guard.ok
  );
  const deadOnStart = stopReason === 'csi_dead_on_start'
    || status === 'failed'
    || Boolean(guard.failed);

  return {
    label: 'startup_signal_guard',
    status: passed ? 'passed' : (deadOnStart ? 'failed' : (status || 'unknown')),
    passed,
    failed: deadOnStart || status === 'failed' || Boolean(guard.failed),
    verdict: deadOnStart ? 'csi_dead_on_start' : (passed ? 'passed' : (status || 'pending')),
    stopReason,
    reason: guard.reason
      || guard.message
      || (deadOnStart
        ? 'CSI сигнал не пошёл. Запись остановлена.'
        : passed
          ? 'проверка старта пройдена'
          : 'проверка старта в ожидании'),
    thresholds: {
      graceSec: safeNumber(guard.grace_sec, safeNumber(guard.graceSec, STARTUP_SIGNAL_GUARD_DEFAULTS.graceSec)) ?? STARTUP_SIGNAL_GUARD_DEFAULTS.graceSec,
      minActiveCoreNodes: safeNumber(guard.min_active_core_nodes, safeNumber(guard.minActiveCoreNodes, STARTUP_SIGNAL_GUARD_DEFAULTS.minActiveCoreNodes)) ?? STARTUP_SIGNAL_GUARD_DEFAULTS.minActiveCoreNodes,
      minPackets: safeNumber(guard.min_packets, safeNumber(guard.minPackets, STARTUP_SIGNAL_GUARD_DEFAULTS.minPackets)) ?? STARTUP_SIGNAL_GUARD_DEFAULTS.minPackets,
      minPps: safeNumber(guard.min_pps, safeNumber(guard.minPps, STARTUP_SIGNAL_GUARD_DEFAULTS.minPps)) ?? STARTUP_SIGNAL_GUARD_DEFAULTS.minPps
    },
    metrics: {
      activeCoreNodes: safeNumber(guard.active_core_nodes, safeNumber(guard.nodes_active, safeNumber(recordingStatus?.nodes_active))) ?? null,
      packets: safeNumber(guard.packets, safeNumber(guard.total_packets, safeNumber(recordingStatus?.chunk_packets))) ?? null,
      pps: safeNumber(guard.pps, safeNumber(recordingStatus?.chunk_pps)) ?? null,
      elapsedSec: safeNumber(guard.elapsed_sec, safeNumber(recordingStatus?.elapsed_sec)) ?? null,
      windowAgeSec: safeNumber(guard.window_age_sec, safeNumber(recordingStatus?.window_age_sec)) ?? null
    },
    note: guard.note
      || guard.summary
      || (deadOnStart
        ? 'Автостоп по startup_signal_guard: CSI dead on start.'
        : passed
          ? 'проверка старта пройдена'
          : 'проверка старта в ожидании'),
    raw: guard
  };
}

function normalizeRecordingStopResult(result, recordingStatus = null) {
  if (!result) {
    return null;
  }

  const stopReason = result.stopReason
    || result.stop_reason
    || result.reason
    || recordingStatus?.stop_reason
    || null;
  const deadOnStart = stopReason === 'csi_dead_on_start'
    || result.session_status === 'failed'
    || result.status === 'failed';

  return {
    ...result,
    stopReason,
    deadOnStart,
    message: result.message
      || (deadOnStart
        ? 'CSI сигнал не пошёл. Запись остановлена.'
        : 'Запись остановлена.'),
    summary: result.summary || result.note || null
  };
}

function getRecordingLastStopResult(recording) {
  return recording?.lastStopResult
    || recording?.status?.lastStopResult
    || recording?.status?.last_result
    || null;
}

function getRecordingLastSessionSummary(recording) {
  return recording?.freeform?.lastSummary
    || recording?.status?.lastSessionSummary
    || recording?.status?.last_session_summary
    || null;
}

function isFreeformSessionSummary(summary) {
  const motionType = String(summary?.motion_type || summary?.motionType || '').trim();
  return motionType === 'free_motion' || motionType === 'freeform_single_person';
}

function inferActiveRecordingMode(recording) {
  const status = recording?.status;
  if (!status?.recording) {
    return null;
  }
  if (ACTIVE_GUIDED_STATUSES.includes(recording?.guided?.status || 'idle')) {
    return 'guided';
  }
  if (
    recording?.activeMode === 'freeform'
    || ((status?.motion_type === 'free_motion' || status?.motion_type === 'freeform_single_person') && status?.with_video)
  ) {
    return 'freeform';
  }
  if (recording?.activeMode === 'manual') {
    return 'manual';
  }
  return 'manual';
}

function buildTeacherSourceState() {
  return {
    selectedKind: TEACHER_SOURCE_KINDS.PIXEL_RTSP,
    pixelRtspUrl: DEFAULT_PIXEL_RTSP_URL,
    pixelRtspName: DEFAULT_PIXEL_RTSP_NAME,
    macDevice: DEFAULT_MAC_CAMERA_DEVICE,
    macDeviceName: DEFAULT_MAC_CAMERA_DEVICE_NAME
  };
}

function normalizeTeacherSourceKind(value) {
  const raw = String(value || '').trim();
  if (!raw) {
    return TEACHER_SOURCE_KINDS.PIXEL_RTSP;
  }
  if (raw === 'phone_rtsp' || raw === 'rtsp_teacher') {
    return TEACHER_SOURCE_KINDS.PIXEL_RTSP;
  }
  if (raw === 'mac_camera_terminal') {
    return TEACHER_SOURCE_KINDS.MAC_CAMERA;
  }
  if (Object.values(TEACHER_SOURCE_KINDS).includes(raw)) {
    return raw;
  }
  return raw;
}

function buildTeacherSourceContract(
  recording,
  {
    withVideo = true,
    videoRequired = null,
    allowLegacyNone = false
  } = {}
) {
  const teacherSource = recording?.teacherSource || buildTeacherSourceState();
  const requestedKind = normalizeTeacherSourceKind(teacherSource.selectedKind);
  const videoRequested = Boolean(withVideo);
  const strictVideoRequired = typeof videoRequired === 'boolean'
    ? videoRequired
    : videoRequested;
  const fallbackKind = strictVideoRequired ? TEACHER_SOURCE_KINDS.PIXEL_RTSP : TEACHER_SOURCE_KINDS.NONE;
  const effectiveKind = videoRequested ? (requestedKind || fallbackKind) : TEACHER_SOURCE_KINDS.NONE;
  const contract = {
    withVideo: videoRequested,
    checkVideo: videoRequested,
    videoRequired: strictVideoRequired && effectiveKind !== TEACHER_SOURCE_KINDS.NONE,
    teacherSourceKind: effectiveKind,
    teacherSourceUrl: '',
    teacherSourceName: '',
    teacherDevice: '',
    teacherDeviceName: '',
    teacherInputPixelFormat: DEFAULT_TEACHER_INPUT_PIXEL_FORMAT,
    error: null
  };

  if (effectiveKind === TEACHER_SOURCE_KINDS.NONE) {
    if (strictVideoRequired && !allowLegacyNone) {
      contract.error = 'video_required=true требует явный источник teacher вместо legacy none.';
    }
    return contract;
  }

  if (effectiveKind === TEACHER_SOURCE_KINDS.PIXEL_RTSP) {
    contract.teacherSourceUrl = String(teacherSource.pixelRtspUrl || DEFAULT_PIXEL_RTSP_URL).trim();
    contract.teacherSourceName = String(teacherSource.pixelRtspName || DEFAULT_PIXEL_RTSP_NAME).trim() || DEFAULT_PIXEL_RTSP_NAME;
    if (!contract.teacherSourceUrl) {
      contract.error = 'Для Pixel RTSP нужен явный URL teacher-источника.';
    }
    return contract;
  }

  if (effectiveKind === TEACHER_SOURCE_KINDS.MAC_CAMERA) {
    contract.teacherDevice = String(teacherSource.macDevice || DEFAULT_MAC_CAMERA_DEVICE).trim() || DEFAULT_MAC_CAMERA_DEVICE;
    contract.teacherDeviceName = String(teacherSource.macDeviceName || DEFAULT_MAC_CAMERA_DEVICE_NAME).trim()
      || DEFAULT_MAC_CAMERA_DEVICE_NAME;
    contract.teacherSourceName = 'Камера Mac';
    return contract;
  }

  contract.error = `Неподдерживаемый источник teacher: ${effectiveKind}`;
  return contract;
}

function applyTeacherSourceContract(target, contract) {
  target.video_required = Boolean(contract.videoRequired);
  target.teacher_source_kind = contract.teacherSourceKind;
  if (contract.teacherSourceUrl) {
    target.teacher_source_url = contract.teacherSourceUrl;
  }
  if (contract.teacherSourceName) {
    target.teacher_source_name = contract.teacherSourceName;
  }
  if (contract.teacherDevice) {
    target.teacher_device = contract.teacherDevice;
  }
  if (contract.teacherDeviceName) {
    target.teacher_device_name = contract.teacherDeviceName;
  }
  if (contract.teacherInputPixelFormat) {
    target.teacher_input_pixel_format = contract.teacherInputPixelFormat;
  }
}

function applyManualCapturePreset(manual, { resetVariant = false } = {}) {
  const preset = getManualCapturePreset(manual.labelPresetId);
  if (!preset || preset.id === 'custom') {
    return;
  }

  const fallbackVariant = preset.variants?.[0] || null;
  const variant = getManualCapturePresetVariant(
    manual.labelPresetId,
    resetVariant ? fallbackVariant?.id : manual.labelVariantId
  ) || fallbackVariant;

  if (variant?.id) {
    manual.labelVariantId = variant.id;
  }

  const generatedLabel = buildManualCaptureLabel(preset, variant);
  const generatedNotes = buildManualCaptureNotes(preset, variant);

  if (generatedLabel) {
    manual.label = generatedLabel;
  }
  manual.notes = generatedNotes || '';

  if (preset.motionType) {
    manual.motionType = preset.motionType;
  }
  if (Number.isFinite(Number(preset.personCount))) {
    manual.personCount = Number(preset.personCount);
  }
}

function buildRecordingState() {
  const defaultPack = GUIDED_CAPTURE_PACKS[0] || null;
  const defaultFewshotProtocol = FEWSHOT_CALIBRATION_PROTOCOLS[0] || null;
  return {
    status: null,
    activeMode: null,
    lastStopResult: null,
    startupSignalGuard: null,
    stopFailure: null,
    preflight: null,
    preflightLoading: false,
    preflightError: null,
    actionError: null,
    selectedPackId: null,
    teacherSource: buildTeacherSourceState(),
    manual: {
      label: '',
      labelPresetId: 'custom',
      labelVariantId: 'custom',
      personCount: 1,
      motionType: '',
      chunkSec: 60,
      withVideo: true,
      voicePrompt: true,
      notes: '',
      skipPreflight: false
    },
    freeform: {
      label: '',
      personCount: 1,
      chunkSec: 60,
      notes: '',
      voiceCue: true,
      withVideo: true,
      lastSummary: null
    },
    guided: {
      packId: defaultPack?.id || null,
      runToken: 0,
      status: 'idle',
      sequencePhase: null,
      countdownValue: null,
      stepIndex: -1,
      stepStartedAt: null,
      stepEndsAt: null,
      pauseUntil: null,
      sessionPrefix: null,
      currentStep: null,
      currentRecordingLabel: null,
      voiceEnabled: defaultPack?.voiceEnabledByDefault !== false,
      withVideo: defaultPack?.withVideo !== false,
      logs: [],
      completedAt: null,
      lastError: null
    },
    fewshotCalibration: {
      protocolId: defaultFewshotProtocol?.id || null,
      runToken: 0,
      packetSessionId: null,
      packetStoragePath: null,
      packetStatus: 'idle',
      status: 'idle',
      sequencePhase: null,
      countdownValue: null,
      stepIndex: -1,
      stepStartedAt: null,
      stepEndsAt: null,
      pauseUntil: null,
      currentStep: null,
      voiceEnabled: true,
      logs: [],
      completedAt: null,
      lastError: null,
      fitResult: null,
      storageStatus: null
    }
  };
}

function makeGuidedSessionPrefix(pack) {
  const stamp = nowIso()
    .replace(/\.\d{3}Z$/, '')
    .replaceAll('-', '')
    .replaceAll(':', '')
    .replace('T', '_');
  return `${pack.labelPrefix || 'train'}_${stamp}_${pack.sessionSlug || pack.id}`;
}

function makeGuidedRecordingLabel(sessionPrefix, stepIndex, step) {
  const stepNumber = String(stepIndex + 1).padStart(2, '0');
  return `${sessionPrefix}_clip${stepNumber}_${step.id}`;
}

function updateGuidedLogEntry(logs, recordingLabel, patch) {
  const nextLogs = [...logs];
  const targetIndex = [...nextLogs].reverse().findIndex((entry) => entry.recordingLabel === recordingLabel);
  if (targetIndex === -1) {
    return nextLogs;
  }
  const actualIndex = nextLogs.length - 1 - targetIndex;
  nextLogs[actualIndex] = {
    ...nextLogs[actualIndex],
    ...patch
  };
  return nextLogs;
}

function buildFewshotProtocolSessionPayload(protocol) {
  return {
    protocol_id: protocol.id,
    protocol_name: protocol.name,
    zone_scheme: protocol.zoneScheme || null,
    total_windows: Number(protocol.totalWindows || 0),
    window_duration_sec: Number(protocol.windowDurationSec || 0),
    metadata: {
      source: 'csi_operator_ui',
      mode: 'guided_fewshot_calibration',
      live_geometry: protocol.zoneScheme || null,
      expected_date_lodo_ba: safeNumber(protocol.expectedDateLodoBa),
      expected_inside_recall: safeNumber(protocol.expectedInsideRecall),
      expected_door_recall: safeNumber(protocol.expectedDoorRecall),
      notes: asArray(protocol.notes)
    },
    steps: asArray(protocol.steps).map((step, index) => ({
      id: step.id,
      label: step.label,
      display_zone: step.displayZone || null,
      capture_zone: step.captureZone || null,
      activity: step.activity || null,
      research_only: Boolean(step.researchOnly),
      duration_sec: Number(step.durationSec || 0),
      target_windows: Number(step.targetWindows || 0),
      index
    }))
  };
}

function parseTopologySignature(signature) {
  if (!signature || typeof signature !== 'string') {
    return [];
  }
  return signature.split('+').map((item) => item.trim()).filter(Boolean);
}

function normalizeGarageLayout(csiPayload) {
  const garage = csiPayload?.garage || {};
  const widthMeters = DEFAULT_GARAGE_LAYOUT.widthMeters;
  const heightMeters = DEFAULT_GARAGE_LAYOUT.heightMeters;
  const door = { ...DEFAULT_GARAGE_LAYOUT.door };
  const rawNodes = Object.entries(garage?.nodes || {})
    .map(([ip, node]) => ({
      nodeId: NODE_IP_TO_ID[ip] || ip,
      ip,
      xMeters: safeNumber(node?.x),
      yMeters: safeNumber(node?.y),
      zone: safeNumber(node?.y) != null
        ? (safeNumber(node?.y) < DEFAULT_GARAGE_LAYOUT.zones.doorMaxY
            ? 'door'
            : safeNumber(node?.y) > DEFAULT_GARAGE_LAYOUT.zones.deepMinY
              ? 'deep'
              : 'center')
        : 'unknown'
    }))
    .filter((node) => node.xMeters != null && node.yMeters != null);

  const nodeById = new Map(DEFAULT_GARAGE_LAYOUT.nodes.map((node) => [node.nodeId, { ...node }]));
  rawNodes.forEach((node) => {
    const canonicalNode = nodeById.get(node.nodeId);
    if (canonicalNode) {
      nodeById.set(node.nodeId, {
        ...canonicalNode,
        ip: node.ip || canonicalNode.ip
      });
      return;
    }
    nodeById.set(node.nodeId, { ...node });
  });

  return {
    widthMeters,
    heightMeters,
    door,
    zones: { ...DEFAULT_GARAGE_LAYOUT.zones },
    nodes: Array.from(nodeById.values()).sort((left, right) => nodeOrderIndex(left.nodeId) - nodeOrderIndex(right.nodeId))
  };
}

function buildCoordinateHistory(csiPayload, garageLayout, { motionOnly = false } = {}) {
  const widthHalf = garageLayout.widthMeters / 2;
  return asArray(csiPayload?.history)
    .map((entry) => {
      const motionState = entry?.motion_state || 'unknown';
      if (motionOnly && motionState !== 'MOTION_DETECTED') {
        return null;
      }
      const xMeters = safeNumber(entry?.target_x);
      const yMeters = safeNumber(entry?.target_y);
      if (xMeters == null || yMeters == null) {
        return null;
      }
      return {
        t: safeNumber(entry?.t),
        motionState,
        zone: entry?.zone || 'unknown',
        xMeters: clamp(xMeters, -widthHalf, widthHalf),
        yMeters: clamp(yMeters, 0, garageLayout.heightMeters)
      };
    })
    .filter(Boolean);
}

function buildOperatorPresenceEntries(csiPayload) {
  const history = asArray(csiPayload?.history);
  const normalizedHistory = history
    .map((entry) => ({
      t: safeNumber(entry?.t),
      motionState: entry?.motion_state || 'unknown',
      binary: entry?.binary || 'unknown',
      xMeters: safeNumber(entry?.target_x),
      yMeters: safeNumber(entry?.target_y),
      zone: entry?.zone || 'unknown',
      nodesActive: safeNumber(entry?.nodes_active, safeNumber(csiPayload?.nodes_active, 0)) || 0,
      confidence: safeNumber(entry?.motion_confidence)
    }))
    .filter((entry) => entry.motionState !== 'unknown' && entry.t != null)
    .sort((left, right) => left.t - right.t);

  if (normalizedHistory.length) {
    const latestT = normalizedHistory.at(-1)?.t ?? null;
    const currentWindowAgeSec = safeNumber(csiPayload?.window_age_sec, 0) || 0;
    return normalizedHistory.map((entry) => ({
      ...entry,
      ageSec: latestT != null ? Math.max(0, currentWindowAgeSec + Math.max(0, latestT - entry.t)) : currentWindowAgeSec
    }));
  }

  if (!csiPayload) {
    return [];
  }

  return [{
    t: 0,
    motionState: csiPayload?.motion_state || 'unknown',
    binary: csiPayload?.binary || 'unknown',
    xMeters: safeNumber(csiPayload?.target_x),
    yMeters: safeNumber(csiPayload?.target_y),
    zone: csiPayload?.target_zone || 'unknown',
    nodesActive: safeNumber(csiPayload?.nodes_active, 0) || 0,
    confidence: safeNumber(csiPayload?.motion_confidence),
    ageSec: safeNumber(csiPayload?.window_age_sec)
  }].filter((entry) => entry.motionState !== 'unknown');
}

function isEligibleOperatorMotion(entry) {
  const hasMinNodes = (safeNumber(entry?.nodesActive, 0) || 0) >= OPERATOR_PRESENCE_GATE.minNodesActive;
  const hasCoordinates = safeNumber(entry?.xMeters) != null && safeNumber(entry?.yMeters) != null;
  const motionDetected = entry?.motionState === 'MOTION_DETECTED';
  // Also accept binary=occupied (static presence) so stationary people show on map
  const binaryOccupied = entry?.binary === 'occupied';
  return (motionDetected || binaryOccupied) && hasMinNodes && hasCoordinates;
}

function countTrailingState(entries, state) {
  let count = 0;
  for (let index = entries.length - 1; index >= 0; index -= 1) {
    if (entries[index]?.motionState !== state) {
      break;
    }
    count += 1;
  }
  return count;
}

function getTrailingMotionRun(entries, endIndexInclusive) {
  if (endIndexInclusive < 0) {
    return [];
  }
  const run = [];
  for (let index = endIndexInclusive; index >= 0; index -= 1) {
    const entry = entries[index];
    if (!isEligibleOperatorMotion(entry)) {
      break;
    }
    run.push(entry);
  }
  return run.reverse();
}

function evaluateOperatorPresenceGate(csiPayload) {
  const entries = buildOperatorPresenceEntries(csiPayload);
  const payloadWindowAgeSec = safeNumber(csiPayload?.window_age_sec);
  const payloadFresh = payloadWindowAgeSec == null || payloadWindowAgeSec <= OPERATOR_PRESENCE_GATE.staleWindowAgeSec;
  const consecutiveMotion = countTrailingState(entries, 'MOTION_DETECTED');
  const consecutiveNoMotion = countTrailingState(entries, 'NO_MOTION');

  // Path 1: classic motion-based confirmation
  let confirmedRun = [];
  if (consecutiveMotion >= OPERATOR_PRESENCE_GATE.confirmMotionWindows) {
    confirmedRun = getTrailingMotionRun(entries, entries.length - 1);
  } else if (consecutiveNoMotion === 1) {
    confirmedRun = getTrailingMotionRun(entries, entries.length - 2);
  }

  const motionConfirmed = confirmedRun.length >= OPERATOR_PRESENCE_GATE.confirmMotionWindows;
  const lastMotionEntry = motionConfirmed ? confirmedRun.at(-1) : null;

  // Path 2: binary=occupied confirmation (static presence without motion)
  // If the model says occupied with valid coordinates, trust it after 3 consecutive windows
  const binaryOccupied = csiPayload?.binary === 'occupied';
  const hasCoordinates = safeNumber(csiPayload?.target_x) != null && safeNumber(csiPayload?.target_y) != null;
  const hasMinNodes = (safeNumber(csiPayload?.nodes_active, 0) || 0) >= OPERATOR_PRESENCE_GATE.minNodesActive;
  let consecutiveOccupied = 0;
  for (let i = entries.length - 1; i >= 0; i--) {
    if (entries[i]?.binary === 'occupied') {
      consecutiveOccupied++;
    } else {
      break;
    }
  }
  const binaryConfirmed = binaryOccupied && hasCoordinates && hasMinNodes
    && consecutiveOccupied >= OPERATOR_PRESENCE_GATE.confirmMotionWindows;

  const confirmed = motionConfirmed || binaryConfirmed;
  const lastConfirmedEntry = motionConfirmed
    ? lastMotionEntry
    : binaryConfirmed
      ? entries.at(-1)
      : null;

  const activeForOperator = Boolean(
    csiPayload?.running
    && csiPayload?.model_loaded
    && payloadFresh
    && confirmed
    && lastConfirmedEntry
  );

  const confirmSource = motionConfirmed ? 'motion' : binaryConfirmed ? 'binary_occupied' : 'none';
  const note = activeForOperator
    ? (confirmSource === 'motion'
      ? `operator presence подтверждён: >=${OPERATOR_PRESENCE_GATE.confirmMotionWindows} подряд MOTION_DETECTED`
      : `operator presence подтверждён: >=${OPERATOR_PRESENCE_GATE.confirmMotionWindows} подряд binary=occupied (static presence)`)
    : `operator presence скрыт до >=${OPERATOR_PRESENCE_GATE.confirmMotionWindows} подряд MOTION_DETECTED или binary=occupied`;

  return {
    source: confirmSource === 'none' ? 'confirmed_motion_gate' : `confirmed_${confirmSource}_gate`,
    confirmed: activeForOperator,
    payloadFresh,
    rawMotionState: csiPayload?.motion_state || 'unknown',
    rawBinary: csiPayload?.binary || 'unknown',
    rawCoarse: csiPayload?.coarse || 'unknown',
    consecutiveMotion,
    consecutiveNoMotion,
    consecutiveOccupied,
    confirmThreshold: OPERATOR_PRESENCE_GATE.confirmMotionWindows,
    clearThreshold: OPERATOR_PRESENCE_GATE.clearNoMotionWindows,
    windowAgeSec: payloadWindowAgeSec,
    lastConfirmedAtWindowT: lastConfirmedEntry?.t ?? null,
    lastConfirmedAgeSec: lastConfirmedEntry?.ageSec ?? null,
    lastConfirmedZone: lastConfirmedEntry?.zone || 'unknown',
    lastConfirmedX: lastConfirmedEntry?.xMeters ?? null,
    lastConfirmedY: lastConfirmedEntry?.yMeters ?? null,
    lastConfirmedConfidence: lastConfirmedEntry?.confidence ?? null,
    note
  };
}

function buildServiceCards(statusPayload) {
  const services = statusPayload?.services || {};
  return Object.entries(services).map(([name, value]) => ({
    name,
    status: value?.status || 'unknown',
    detail: value?.last_error
      || value?.message
      || (value?.status === 'unknown' ? 'backend прислал только status=unknown' : null),
    running: value?.running,
    initialized: value?.initialized,
    uptime: safeNumber(value?.uptime)
  }));
}

function buildMotionRuntime(csiPayload, posePayload) {
  const garage = normalizeGarageLayout(csiPayload);
  const zoneProbabilities = csiPayload?.zone_probabilities || null;
  const zoneTop = getTopProbability(zoneProbabilities);
  return {
    state: csiPayload?.motion_state || posePayload?.motion_state || 'unknown',
    confidence: safeNumber(csiPayload?.motion_confidence),
    running: Boolean(csiPayload?.running),
    modelLoaded: Boolean(csiPayload?.model_loaded),
    nodesActive: safeNumber(csiPayload?.nodes_active),
    totalNodes: Math.max(garage.nodes.length, DEFAULT_VISIBLE_NODE_COUNT),
    packetsInWindow: safeNumber(csiPayload?.packets_in_window),
    packetsPerSecond: safeNumber(csiPayload?.pps),
    windowAgeSec: safeNumber(csiPayload?.window_age_sec),
    targetZone: csiPayload?.target_zone || 'unknown',
    zoneProbabilities,
    zoneConfidence: zoneTop.confidence,
    zoneTopLabel: zoneTop.label,
    zoneModel: csiPayload?.zone_model || null,
    targetX: safeNumber(csiPayload?.target_x),
    targetY: safeNumber(csiPayload?.target_y),
    modelVersion: csiPayload?.model_version || 'unknown',
    modelId: csiPayload?.model_id || csiPayload?.model_filename || null,
    modelKind: csiPayload?.model_kind || 'unknown',
    modelDefault: Boolean(csiPayload?.model_default),
    binaryThreshold: safeNumber(csiPayload?.binary_threshold),
    binary: csiPayload?.binary || 'unknown',
    binaryConfidence: safeNumber(csiPayload?.binary_confidence),
    history: asArray(csiPayload?.history),
    garage
  };
}

function buildExperimentalRuntime(csiPayload) {
  return {
    binary: csiPayload?.binary || 'unknown',
    binaryConfidence: safeNumber(csiPayload?.binary_confidence),
    coarse: csiPayload?.coarse || 'unknown',
    coarseConfidence: safeNumber(csiPayload?.coarse_confidence)
  };
}

function buildShadowDisagreement(csiPayload, primaryRuntime = null, v27Binary7NodeShadow = null) {
  const primaryBinary = primaryRuntime?.binary || csiPayload?.binary || 'unknown';
  const primaryBinaryConfidence = safeNumber(primaryRuntime?.binaryConfidence, safeNumber(csiPayload?.binary_confidence));
  const primaryZone = primaryRuntime?.targetZone || csiPayload?.target_zone || 'unknown';
  const primaryZoneConfidence = safeNumber(primaryRuntime?.zoneConfidence);
  const shadowBinary = v27Binary7NodeShadow?.binary
    || csiPayload?.v26_shadow?.binary
    || 'unknown';
  const shadowBinaryConfidence = safeNumber(
    v27Binary7NodeShadow?.occupiedProbability,
    safeNumber(csiPayload?.v26_shadow?.binary_proba)
  );
  const shadowLoaded = Boolean(v27Binary7NodeShadow?.loaded ?? csiPayload?.v26_shadow?.loaded);
  const binaryDisagreement = shadowBinary !== 'unknown'
    && primaryBinary !== 'unknown'
    && primaryBinary !== shadowBinary;
  const summary = binaryDisagreement
    ? `primary=${primaryBinary} vs shadow=${shadowBinary}`
    : 'primary и shadow совпадают';
  const tone = binaryDisagreement ? 'risk' : (shadowLoaded ? 'ok' : 'warn');

  return {
    primaryBinary,
    primaryBinaryConfidence,
    primaryZone,
    primaryZoneConfidence,
    shadowBinary,
    shadowBinaryConfidence,
    shadowLoaded,
    binaryDisagreement,
    summary,
    tone
  };
}

function buildTrackBShadowRuntime(csiPayload) {
  const shadow = csiPayload?.track_b_shadow || {};
  const probabilities = shadow?.probabilities || {};
  const predictedClass = typeof shadow?.predicted_class === 'string'
    ? shadow.predicted_class
    : null;
  const loaded = shadow?.loaded != null
    ? Boolean(shadow.loaded)
    : Boolean(predictedClass);
  const status = shadow?.status
    || (predictedClass ? 'shadow_live' : (loaded ? 'awaiting_first_window' : 'not_loaded'));

  return {
    enabled: Boolean(csiPayload?.track_b_shadow),
    track: shadow?.track || 'B_v1',
    loaded,
    status,
    predictedClass,
    predictedIdx: safeNumber(shadow?.predicted_idx),
    probabilities,
    emptyProbability: safeNumber(probabilities?.EMPTY),
    staticProbability: safeNumber(probabilities?.STATIC),
    motionProbability: safeNumber(probabilities?.MOTION),
    inferenceMs: safeNumber(shadow?.inference_ms),
    nodesWithData: safeNumber(shadow?.nodes_with_data),
    windowT: safeNumber(shadow?.t)
  };
}

function buildV15ShadowRuntime(csiPayload) {
  const shadow = csiPayload?.v8_shadow || csiPayload?.v7_shadow || csiPayload?.v15_shadow || {};
  const probabilities = shadow?.probabilities || {};
  const predictedClass = typeof shadow?.predicted_class === 'string'
    ? shadow.predicted_class
    : null;
  const loaded = shadow?.loaded != null
    ? Boolean(shadow.loaded)
    : Boolean(predictedClass);
  const status = shadow?.status
    || (predictedClass ? 'shadow_live' : (loaded ? 'warmup' : 'not_loaded'));

  return {
    enabled: Boolean(csiPayload?.v8_shadow || csiPayload?.v7_shadow || csiPayload?.v15_shadow),
    track: shadow?.track || 'V8_shadow',
    loaded,
    status,
    predictedClass,
    binary: shadow?.binary || null,
    probabilities,
    emptyProbability: safeNumber(probabilities?.EMPTY),
    staticProbability: safeNumber(probabilities?.STATIC),
    motionProbability: safeNumber(probabilities?.MOTION),
    binaryProbability: safeNumber(shadow?.binary_proba),
    inferenceMs: safeNumber(shadow?.inference_ms),
    bufferDepth: safeNumber(shadow?.buffer_depth),
    warmupRemaining: safeNumber(shadow?.warmup_remaining),
    warmupWindowsSeen: safeNumber(shadow?.warmup_windows_seen),
    agreeCoarse: shadow?.agree_coarse ?? null,
    agreeBinary: shadow?.agree_binary ?? null,
    targetX: safeNumber(shadow?.target_x),
    targetY: safeNumber(shadow?.target_y),
    targetZone: shadow?.target_zone || 'unknown',
    coordinateSource: shadow?.coordinate_source || null,
    windowT: safeNumber(shadow?.t)
  };
}

function buildV19ShadowRuntime(csiPayload) {
  const shadow = csiPayload?.v19_shadow || {};
  const probabilities = shadow?.probabilities || {};
  const predictedClass = typeof shadow?.predicted_class === 'string'
    ? shadow.predicted_class
    : null;
  const loaded = shadow?.loaded != null
    ? Boolean(shadow.loaded)
    : Boolean(predictedClass);
  const status = shadow?.status
    || (predictedClass ? 'shadow_live' : (loaded ? 'warmup' : 'not_loaded'));

  return {
    enabled: Boolean(csiPayload?.v19_shadow),
    track: shadow?.track || 'V19_shadow',
    loaded,
    status,
    predictedClass,
    binary: shadow?.binary || null,
    probabilities,
    emptyProbability: safeNumber(probabilities?.EMPTY),
    staticProbability: safeNumber(probabilities?.STATIC),
    motionProbability: safeNumber(probabilities?.MOTION),
    binaryProbability: safeNumber(shadow?.binary_proba),
    inferenceMs: safeNumber(shadow?.inference_ms),
    bufferDepth: safeNumber(shadow?.buffer_depth),
    warmupRemaining: safeNumber(shadow?.warmup_remaining),
    warmupWindowsSeen: safeNumber(shadow?.warmup_windows_seen),
    agreeCoarse: shadow?.agree_coarse ?? null,
    agreeBinary: shadow?.agree_binary ?? null,
    windowT: safeNumber(shadow?.t),
    emptyGateFired: Boolean(shadow?.empty_gate_fired),
    emptyGateState: Boolean(shadow?.empty_gate_state),
    rawPredictedClass: shadow?.raw_predicted_class || null,
    blAmpDevMax: safeNumber(shadow?.bl_amp_dev_max),
    blScVarDevMax: safeNumber(shadow?.bl_sc_var_dev_max),
    gateConsecBelow: shadow?.gate_consec_below ?? 0,
    gateConsecAbove: shadow?.gate_consec_above ?? 0,
  };
}

function buildV27Binary7NodeRuntime(csiPayload) {
  const shadow = csiPayload?.v26_shadow || {};
  const binary = typeof shadow?.binary === 'string'
    ? shadow.binary
    : null;
  const occupiedProbability = safeNumber(shadow?.binary_proba);
  const emptyProbability = occupiedProbability != null
    ? clamp(1 - occupiedProbability, 0, 1)
    : null;
  const loaded = shadow?.loaded != null
    ? Boolean(shadow.loaded)
    : Boolean(binary);
  const status = shadow?.status
    || (binary ? 'shadow_live' : (loaded ? 'awaiting_first_window' : 'not_loaded'));

  return {
    enabled: Boolean(csiPayload?.v26_shadow),
    sourceField: 'v26_shadow',
    track: shadow?.track || 'V26_binary_7node',
    candidateName: shadow?.candidate_name || shadow?.candidateName || shadow?.track || 'unknown_candidate',
    loaded,
    status,
    binary,
    predictedClass: binary,
    occupiedProbability,
    emptyProbability,
    threshold: safeNumber(shadow?.threshold),
    agreeBinary: shadow?.agree_binary ?? null,
    inferenceMs: safeNumber(shadow?.inference_ms),
    windowT: safeNumber(shadow?.window_t)
  };
}

function buildGarageRatioV2ShadowRuntime(csiPayload) {
  const shadow = csiPayload?.garage_ratio_v3_shadow || csiPayload?.garage_ratio_v2_shadow || {};
  const probabilities = shadow?.probabilities || {};
  const predictedZone = typeof shadow?.target_zone === 'string'
    ? shadow.target_zone
    : (typeof shadow?.predicted_zone === 'string' ? shadow.predicted_zone : null);
  const loaded = shadow?.loaded != null
    ? Boolean(shadow.loaded)
    : Boolean(predictedZone || shadow?.candidate_name);
  const status = shadow?.status
    || (predictedZone ? 'shadow_live' : (loaded ? 'awaiting_first_window' : 'not_loaded'));

  return {
    enabled: Boolean(csiPayload?.garage_ratio_v3_shadow || csiPayload?.garage_ratio_v2_shadow),
    track: shadow?.track || 'GARAGE_RATIO_LAYER_V3_CANDIDATE',
    candidateName: shadow?.candidate_name || 'GARAGE_RATIO_LAYER_V3_CANDIDATE',
    loaded,
    status,
    predictedZone,
    targetZone: predictedZone || 'unknown',
    predictedIdx: safeNumber(shadow?.predicted_idx),
    probabilities,
    doorProbability: safeNumber(probabilities?.door),
    centerProbability: safeNumber(probabilities?.center),
    deepProbability: safeNumber(probabilities?.deep),
    adjustedScores: shadow?.adjusted_scores || {},
    inferenceMs: safeNumber(shadow?.inference_ms),
    activeNodes: safeNumber(shadow?.active_nodes),
    nodesWithRatio: safeNumber(shadow?.nodes_with_ratio),
    packetsInWindow: safeNumber(shadow?.packets_in_window),
    binary: shadow?.binary || null,
    productionZone: shadow?.production_zone || 'unknown',
    doorRescueApplied: Boolean(shadow?.door_rescue_applied),
    rawPredictedZone: shadow?.raw_predicted_zone || null,
    thresholds: shadow?.thresholds || {},
    rescuePolicy: shadow?.v5_door_rescue || {},
    runtimeSmoothing: shadow?.runtime_smoothing || {},
    smoothing: shadow?.smoothing || {},
    smoothingApplied: Boolean(shadow?.smoothing?.applied),
    smoothingReady: Boolean(shadow?.smoothing?.ready),
    smoothingWindow: safeNumber(shadow?.smoothing?.window),
    smoothingCount: safeNumber(shadow?.smoothing?.count),
    smoothingCounts: shadow?.smoothing?.counts || {},
    topFeatures: shadow?.top_features || {},
    nodePackets: shadow?.node_packets || {},
    windowT: safeNumber(shadow?.t)
  };
}

function buildZoneCalibrationShadow(csiPayload) {
  const zc = csiPayload?.zone_calibration_shadow || {};
  const lastPred = zc?.last_prediction || {};
  return {
    available: Boolean(csiPayload?.zone_calibration_shadow),
    calibrated: Boolean(zc?.calibrated),
    status: zc?.status || 'not_calibrated',
    calibratingZone: zc?.calibrating_zone || null,
    calibratedAt: zc?.calibrated_at || null,
    calibrationQuality: zc?.calibration_quality || 'not_calibrated',
    zonesCalibrated: Array.isArray(zc?.zones_calibrated) ? zc.zones_calibrated : [],
    nCalWindows: zc?.n_cal_windows || {},
    stale: Boolean(zc?.stale),
    rejectionReason: zc?.rejection_reason || null,
    predictionHistoryLen: safeNumber(zc?.prediction_history_len, 0),
    // Last prediction
    zone: lastPred?.zone || 'unknown',
    zoneRaw: lastPred?.zone_raw || 'unknown',
    confidence: safeNumber(lastPred?.confidence),
    lowConfidence: Boolean(lastPred?.low_confidence),
    distances: lastPred?.distances || {},
    smoothed: Boolean(lastPred?.smoothed),
    smoothingMeta: lastPred?.smoothing_meta || {},
    inferenceMs: safeNumber(lastPred?.inference_ms),
    calibrationStatus: lastPred?.calibration_status || zc?.status || 'not_calibrated',
  };
}

function buildBaselineStatus(csiPayload) {
  const bl = csiPayload?.empty_baseline || {};
  const profiles = bl?.profiles || {};
  const profileEntries = Object.values(profiles);
  const firstProfile = profileEntries[0] || {};
  return {
    calibrated: Boolean(bl?.calibrated),
    captureActive: Boolean(bl?.capturing),
    calibratedAt: firstProfile?.captured_at || null,
    windowsPerNode: safeNumber(firstProfile?.window_count),
    nodeCount: profileEntries.length || 0,
    nodeIps: Object.keys(profiles)
  };
}

function buildSignalQuality(csiPayload) {
  const sq = csiPayload?.signal_quality || {};
  return {
    available: Boolean(csiPayload?.signal_quality),
    phaseJumpMax: safeNumber(sq?.phase_jump_max),
    deadScMax: safeNumber(sq?.dead_sc_max),
    ampDriftMax: safeNumber(sq?.amp_drift_max),
    phaseCoherenceMean: safeNumber(sq?.phase_coherence_mean)
  };
}

function normalizeRuntimeModelItem(item, activeModelId, defaultModelId, modelLoaded) {
  const version = item?.version || item?.display_name || item?.filename || 'unknown';
  const fileName = item?.filename || item?.model_id || 'unknown';
  const kind = item?.kind || 'unknown';
  const threshold = safeNumber(item?.threshold);
  const isActive = Boolean(item?.is_active) || (!!activeModelId && fileName === activeModelId);
  const isDefault = Boolean(item?.is_default) || (!!defaultModelId && fileName === defaultModelId);

  return {
    modelId: item?.model_id || fileName,
    fileName,
    displayName: item?.display_name || `${version} · ${fileName}`,
    version,
    kind,
    threshold,
    isActive,
    isDefault,
    loaded: Boolean(item?.loaded) || (isActive && Boolean(modelLoaded)),
    updatedAt: item?.updated_at || null,
    path: item?.path || null
  };
}

function buildRuntimeModelsState(state) {
  const catalog = state.runtimeModels;
  const activeModelId = state.csi?.model_id || catalog?.activeModelId || null;
  const defaultModelId = catalog?.defaultModelId || null;
  const modelLoaded = Boolean(state.csi?.model_loaded);
  const items = asArray(catalog?.items).map((item) =>
    normalizeRuntimeModelItem(item, activeModelId, defaultModelId, modelLoaded)
  );

  return {
    items,
    activeModelId,
    defaultModelId,
    loadedAt: catalog?.loadedAt || null,
    loading: Boolean(catalog?.loading),
    error: catalog?.error || null,
    switching: Boolean(catalog?.switching),
    actionError: catalog?.actionError || null
  };
}

function buildShadowDiagnostics(metadata) {
  const items = [];

  if (metadata?.staged_motion_shadow_enabled) {
    items.push({
      label: 'Тень дверной границы',
      status: metadata.staged_motion_shadow_status || 'unknown',
      prediction: metadata.staged_motion_shadow_prediction || 'n/a',
      detail: metadata.staged_motion_shadow_decision_reason || 'решение не сформировано'
    });
  }

  if (metadata?.staged_single_person_router_enabled) {
    items.push({
      label: 'Роутер одного человека',
      status: metadata.staged_single_person_router_status || 'unknown',
      prediction: metadata.staged_single_person_router_prediction || 'n/a',
      detail: metadata.staged_single_person_router_route_name || 'маршрут не выбран'
    });
  }

  if (metadata?.staged_single_person_validated_router_enabled) {
    items.push({
      label: 'Проверенный роутер',
      status: metadata.staged_single_person_validated_router_status || 'unknown',
      prediction: metadata.staged_single_person_validated_router_prediction || 'n/a',
      detail: metadata.staged_single_person_validated_router_route_name || 'маршрут не выбран'
    });
  }

  items.push({
    label: 'Риск схлопывания',
    status: metadata?.collapse_risk_runtime_status || 'unknown',
    prediction: metadata?.multi_person_collapse_risk_flag ? 'risk' : 'clear',
    detail: metadata?.multi_person_ambiguity_score != null
      ? `неоднозначность ${metadata.multi_person_ambiguity_score}`
      : 'оценка неоднозначности недоступна'
  });

  return items;
}

function normalizeRiskText(value) {
  return typeof value === 'string' ? value.trim().toLowerCase() : '';
}

function hasAmbiguityRiskToken(value) {
  const normalized = normalizeRiskText(value);
  return MULTI_PERSON_AMBIGUITY_RISK_TOKENS.some((token) => normalized.includes(token));
}

function deriveAmbiguityMode(csiPayload, posePayload, support, operatorPresence) {
  const metadata = posePayload?.metadata || {};
  const ambiguityScore = safeNumber(metadata?.multi_person_ambiguity_score);
  const explicitCollapseRisk = Boolean(metadata?.multi_person_collapse_risk_flag);
  const collapseRuntimeStatus = metadata?.collapse_risk_runtime_status || 'unknown';
  const supportSignals = [
    support?.invalidation_reason,
    support?.reason,
    support?.status,
    support?.pending_direction,
    collapseRuntimeStatus
  ];
  const textualRisk = supportSignals.some((value) => hasAmbiguityRiskToken(value));
  const highAmbiguity = Boolean(
    explicitCollapseRisk
    || (ambiguityScore != null && ambiguityScore >= MULTI_PERSON_AMBIGUITY_SCORE_THRESHOLD)
    || textualRisk
  );
  const targetZone = (
    operatorPresence?.lastConfirmedZone && operatorPresence.lastConfirmedZone !== 'unknown'
      ? operatorPresence.lastConfirmedZone
      : csiPayload?.target_zone || 'unknown'
  );
  const active = Boolean(
    csiPayload?.running
    && csiPayload?.model_loaded
    && operatorPresence?.payloadFresh !== false
    && highAmbiguity
    && (
      operatorPresence?.confirmed
      || csiPayload?.motion_state === 'MOTION_DETECTED'
    )
  );

  let reason = 'none';
  let detail = 'single-target marker разрешён';
  if (explicitCollapseRisk) {
    reason = 'multi_person_collapse_risk_flag';
    detail = 'backend пометил collapse risk: single-target marker скрыт';
  } else if (ambiguityScore != null && ambiguityScore >= MULTI_PERSON_AMBIGUITY_SCORE_THRESHOLD) {
    reason = 'multi_person_ambiguity_score';
    detail = `ambiguity score ${ambiguityScore.toFixed(2)}: точная одиночная позиция скрыта`;
  } else if (textualRisk) {
    reason = 'collapse_support_signal';
    detail = 'support/collapse signal указывает на неоднозначную одиночную позицию';
  }

  return {
    active,
    highAmbiguity,
    singleTargetAllowed: Boolean(operatorPresence?.confirmed && !active),
    reason,
    detail,
    headline: active ? 'несколько людей / позиция неоднозначна' : 'single-target safe',
    ambiguityScore,
    ambiguityScoreThreshold: MULTI_PERSON_AMBIGUITY_SCORE_THRESHOLD,
    collapseRiskFlag: explicitCollapseRisk,
    collapseRiskRuntimeStatus: collapseRuntimeStatus,
    targetZone: ['door', 'center', 'deep'].includes(targetZone) ? targetZone : 'center',
    rawTargetZone: csiPayload?.target_zone || 'unknown',
    source: explicitCollapseRisk
      ? 'collapse_risk_flag'
      : ambiguityScore != null && ambiguityScore >= MULTI_PERSON_AMBIGUITY_SCORE_THRESHOLD
        ? 'ambiguity_score'
        : textualRisk
          ? 'support_risk_signal'
          : 'clear'
  };
}

function buildNodeSummary(csiPayload, posePayload, statusPayload) {
  const metadata = posePayload?.metadata || {};
  const support = posePayload?.support_observations?.four_node_entry_exit_shadow_core || {};
  const sourceTotals = statusPayload?.services?.hardware?.live_udp?.source_totals || {};
  const liveSignature = asArray(metadata.live_source_signature);
  const requiredNodes = parseTopologySignature(support.required_topology_signature || support.observed_topology_signature);
  const union = new Set([...NODE_ORDER, ...Object.keys(sourceTotals), ...liveSignature, ...requiredNodes]);
  const total = Object.values(sourceTotals).reduce((sum, value) => sum + (safeNumber(value, 0) || 0), 0);
  const breakdownAvailable = liveSignature.length > 0 || Object.keys(sourceTotals).length > 0;
  const aggregateNodesActive = safeNumber(csiPayload?.nodes_active, 0) || 0;

  return Array.from(union)
    .filter(Boolean)
    .sort((left, right) => nodeOrderIndex(left) - nodeOrderIndex(right))
    .map((nodeId) => {
      if (!breakdownAvailable && aggregateNodesActive > 0) {
        const allKnownNodesActive = aggregateNodesActive >= union.size && union.size > 0;
        return {
          nodeId,
          packets: null,
          packetShare: null,
          active: allKnownNodesActive ? true : null,
          aggregateOnly: true,
          required: requiredNodes.length ? requiredNodes.includes(nodeId) : true
        };
      }
      const packets = safeNumber(sourceTotals[nodeId], 0) || 0;
      return {
        nodeId,
        packets,
        packetShare: total > 0 ? packets / total : 0,
        active: liveSignature.includes(nodeId),
        aggregateOnly: false,
        required: requiredNodes.includes(nodeId)
      };
    });
}

function deriveLastMeaningfulEvent(csiPayload, posePayload, support, operatorPresence, ambiguityMode) {
  const supportAge = safeNumber(support?.last_event_age_sec);
  const motionAge = safeNumber(csiPayload?.window_age_sec);
  const latestMotion = asArray(csiPayload?.history).at(-1);

  if (ambiguityMode?.active) {
    const detail = [
      ambiguityMode.detail,
      ambiguityMode.targetZone ? `зона ${ambiguityMode.targetZone}` : null,
      ambiguityMode.ambiguityScore != null ? `score ${ambiguityMode.ambiguityScore.toFixed(2)}` : null
    ].filter(Boolean).join(' / ');
    return {
      source: 'ambiguity_safe_mode',
      label: ambiguityMode.headline,
      ageSec: operatorPresence?.lastConfirmedAgeSec ?? motionAge,
      timestamp: null,
      detail: detail || 'single-target marker hidden in ambiguity safe-mode'
    };
  }

  if (operatorPresence?.confirmed) {
    const detail = [
      `gate ${operatorPresence.confirmThreshold}/${operatorPresence.confirmThreshold}`,
      operatorPresence.lastConfirmedZone ? `зона ${operatorPresence.lastConfirmedZone}` : null,
      operatorPresence.lastConfirmedConfidence != null
        ? `conf ${operatorPresence.lastConfirmedConfidence.toFixed(2)}`
        : null
    ].filter(Boolean).join(' / ');
    return {
      source: operatorPresence.source,
      label: 'CONFIRMED_MOTION',
      ageSec: operatorPresence.lastConfirmedAgeSec,
      timestamp: null,
      detail: detail || 'motion confirmation gate active'
    };
  }

  if (csiPayload?.motion_state === 'MOTION_DETECTED' && (motionAge == null || supportAge == null || motionAge <= supportAge)) {
    const confidence = safeNumber(latestMotion?.motion_confidence ?? csiPayload?.motion_confidence);
    const zone = latestMotion?.zone || csiPayload?.target_zone;
    const pps = safeNumber(latestMotion?.pps ?? csiPayload?.pps);
    const detail = [
      `raw spike ${operatorPresence?.consecutiveMotion || 0}/${operatorPresence?.confirmThreshold || OPERATOR_PRESENCE_GATE.confirmMotionWindows}`,
      confidence != null ? `conf ${confidence.toFixed(2)}` : null,
      zone ? `зона ${zone}` : null,
      pps != null ? `${pps.toFixed(1)} pps` : null
    ].filter(Boolean).join(' / ');
    return {
      source: 'motion_runtime_raw',
      label: 'UNCONFIRMED_MOTION_SPIKE',
      ageSec: motionAge,
      timestamp: null,
      detail: detail || 'raw motion spike is not yet operator-confirmed'
    };
  }

  if (csiPayload?.motion_state && (motionAge == null || supportAge == null || motionAge <= supportAge)) {
    const confidence = safeNumber(latestMotion?.motion_confidence ?? csiPayload?.motion_confidence);
    const zone = latestMotion?.zone || csiPayload?.target_zone;
    const pps = safeNumber(latestMotion?.pps ?? csiPayload?.pps);
    const detail = [
      confidence != null ? `conf ${confidence.toFixed(2)}` : null,
      zone ? `зона ${zone}` : null,
      pps != null ? `${pps.toFixed(1)} pps` : null
    ].filter(Boolean).join(' / ');
    return {
      source: 'motion_runtime',
      label: csiPayload.motion_state,
      ageSec: motionAge,
      timestamp: null,
      detail: detail || 'motion runtime активен'
    };
  }

  if (support?.last_event) {
    return {
      source: 'support_path',
      label: support.last_event,
      ageSec: supportAge,
      timestamp: support.last_event_ts,
      detail: support.context_validity || support.status || 'unknown'
    };
  }

  return {
    source: 'none',
    label: 'no_meaningful_event',
    ageSec: null,
    timestamp: null,
    detail: posePayload ? 'Сейчас нет свежего motion-runtime события или support-перехода.' : 'Сейчас нет live CSI runtime payload.'
  };
}

function deriveFailureSignal(posePayload, support) {
  if (support?.invalidation_reason) {
    return {
      label: support.invalidation_reason,
      tone: 'risk',
      summary: 'Support-path сейчас невалиден.'
    };
  }

  if (support?.pending_review) {
    return {
      label: 'review_hold',
      tone: 'warn',
      summary: 'Support-path активен, но не разрешён и остаётся на review-hold.'
    };
  }

  if (support?.positive) {
    return {
      label: support.pending_direction || support.resolution_event || support.status || 'active_shadow',
      tone: 'info',
      summary: 'Shadow-support live, но это по-прежнему неавторитетное evidence.'
    };
  }

  return {
    label: 'no_active_failure_family_signal',
    tone: 'ok',
    summary: 'В текущем кадре нет активной live-signature семейства сбоев.'
  };
}

function deriveTrust(csiPayload, support) {
  if (!csiPayload) {
    return {
      label: 'offline',
      tone: 'risk',
      summary: 'Статус CSI runtime недоступен.'
    };
  }

  if (!csiPayload.running) {
    return {
      label: 'offline',
      tone: 'risk',
      summary: 'CSI runtime не запущен.'
    };
  }

  if (!csiPayload.model_loaded) {
    return {
      label: 'degraded',
      tone: 'risk',
      summary: 'Runtime только по движению поднят, но модель не загружена.'
    };
  }

  const topologyMatch = support?.topology_match !== false;
  const nodesActive = safeNumber(csiPayload.nodes_active, 0) || 0;
  const packetsPerSecond = safeNumber(csiPayload.pps);
  const windowAgeSec = safeNumber(csiPayload.window_age_sec);

  if (windowAgeSec != null && windowAgeSec > 8) {
    return {
      label: 'degraded',
      tone: 'warn',
      summary: 'Runtime только по движению отвечает, но окно CSI уже несвежее.'
    };
  }

  if (nodesActive < 3) {
    return {
      label: 'degraded',
      tone: 'warn',
      summary: 'Runtime только по движению жив, но активных узлов меньше трёх.'
    };
  }

  if (packetsPerSecond != null && packetsPerSecond < 20) {
    return {
      label: 'degraded',
      tone: 'warn',
      summary: 'Runtime только по движению жив, но packet-rate слишком низкий.'
    };
  }

  if (!topologyMatch) {
    return {
      label: 'topology_mismatch',
      tone: 'risk',
      summary: 'Runtime только по движению жив, но support-топология не совпадает с frozen-контрактом.'
    };
  }

  const confidence = safeNumber(csiPayload.motion_confidence);
  return {
    label: 'ready',
    tone: 'ok',
    summary: `Motion-runtime свежий${confidence != null ? `, уверенность ${confidence.toFixed(2)}` : ''}; семантика вход/выход остаётся только support-слоем.`
  };
}

function buildRuntimePaths(csiPayload, metadata, support, trackBShadow, v19Shadow, v27Binary7NodeShadow) {
  const experimentalAvailable = csiPayload && (
    (csiPayload.binary && csiPayload.binary !== 'unknown')
    || (csiPayload.coarse && csiPayload.coarse !== 'unknown')
  );
  const trackBStatus = trackBShadow?.loaded
    ? (trackBShadow?.predictedClass ? 'healthy' : 'inactive')
    : (trackBShadow?.status === 'not_loaded' ? 'failed' : 'inactive');
  const trackBMode = trackBShadow?.predictedClass
    ? `shadow_${String(trackBShadow.predictedClass).toLowerCase()}`
    : (trackBShadow?.status || 'unknown');

  return [
    {
      label: 'Runtime только по движению',
      status: csiPayload?.running && csiPayload?.model_loaded ? 'healthy' : 'failed',
      mode: csiPayload?.motion_state || 'unknown',
      role: 'active_primary'
    },
    {
      label: 'Track B тень',
      status: trackBStatus,
      mode: trackBMode,
      role: 'shadow_candidate'
    },
    {
      label: 'Координатный регрессор',
      status: metadata?.coordinate_runtime_status || 'unknown',
      mode: metadata?.coordinate_model_source || 'unknown',
      role: 'active_reference'
    },
    {
      label: 'Бинарная/coarse диагностика',
      status: experimentalAvailable ? 'healthy' : 'inactive',
      mode: experimentalAvailable ? 'experimental_only' : 'unknown',
      role: 'active_diagnostic'
    },
    {
      label: 'Ядро shadow вход/выход',
      status: support?.candidate_status || support?.status || 'unknown',
      mode: support?.support_only ? 'support_only' : 'active',
      role: 'support_path'
    },
    {
      label: 'V19 shadow по V23-features',
      status: v19Shadow?.loaded
        ? (v19Shadow?.predictedClass ? 'healthy' : 'inactive')
        : (v19Shadow?.status === 'not_loaded' ? 'failed' : 'inactive'),
      mode: v19Shadow?.predictedClass
        ? `shadow_${String(v19Shadow.predictedClass).toLowerCase()}`
        : (v19Shadow?.status || 'unknown'),
      role: 'shadow_candidate'
    },
    {
      label: v27Binary7NodeShadow?.candidateName || v27Binary7NodeShadow?.track || '7-node binary candidate',
      status: v27Binary7NodeShadow?.loaded
        ? (v27Binary7NodeShadow?.binary ? 'healthy' : 'inactive')
        : (v27Binary7NodeShadow?.status === 'not_loaded' ? 'failed' : 'inactive'),
      mode: v27Binary7NodeShadow?.binary
        ? `binary_${String(v27Binary7NodeShadow.binary).toLowerCase()}`
        : (v27Binary7NodeShadow?.status || 'unknown'),
      role: 'shadow_candidate'
    },
    {
      label: 'Риск схлопывания',
      status: metadata?.collapse_risk_runtime_status || 'unknown',
      mode: metadata?.multi_person_collapse_risk_flag ? 'risk' : 'clear',
      role: 'active_diagnostic'
    }
  ];
}

async function requestUiJson(path, { method = 'GET', body = null } = {}) {
  const location = typeof window !== 'undefined' ? window.location : null;
  const shouldUseLocalUiOrigin = path.startsWith('/api/agent7/')
    && location
    && isLocalHostname(location.hostname)
    && location.port !== '3000';
  const baseUrl = shouldUseLocalUiOrigin ? API_CONFIG.LOCAL_UI_URL : '';
  const headers = {
    Accept: 'application/json'
  };
  if (body !== null) {
    headers['Content-Type'] = 'application/json';
  }

  const response = await fetch(`${baseUrl}${path}`, {
    method,
    headers,
    body: body === null ? undefined : JSON.stringify(body)
  });

  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    const payloadError = payload?.error;
    const message = typeof payloadError === 'string'
      ? payloadError
      : typeof payloadError?.message === 'string'
        ? payloadError.message
        : typeof payload?.message === 'string'
          ? payload.message
          : `UI forensic request failed with HTTP ${response.status}`;
    const error = new Error(message);
    error.status = response.status;
    error.payload = payload;
    throw error;
  }

  return response.json();
}

function buildMultiPersonEstimate(csiPayload) {
  const mpe = csiPayload?.multi_person_estimate || {};
  const tracks = Array.isArray(mpe.diagnostic_tracks) ? mpe.diagnostic_tracks : [];
  return {
    personCountEstimate: Number(mpe.person_count_estimate) || 1,
    state: mpe.multi_person_state || 'single',
    confidence: safeNumber(mpe.multi_person_confidence) ?? 0,
    diagnosticTracks: tracks.map((t) => ({
      id: t.id || 'unknown',
      source: t.source || 'unknown',
      x: safeNumber(t.x) ?? 0,
      y: safeNumber(t.y) ?? 0,
      zone: t.zone || 'unknown',
      class: t.class || 'unknown',
      confidence: safeNumber(t.confidence) ?? 0
    })),
    clusterCenter: mpe.diagnostic_cluster_center
      ? { x: safeNumber(mpe.diagnostic_cluster_center.x) ?? 0, y: safeNumber(mpe.diagnostic_cluster_center.y) ?? 0 }
      : null,
    clusterRadius: safeNumber(mpe.diagnostic_cluster_radius) ?? 0,
    estimatorSource: mpe.estimator_source || 'unknown',
    estimatorReasons: Array.isArray(mpe.estimator_reasons) ? mpe.estimator_reasons : [],
    recordingHint: Number(mpe.recording_hint) || 0
  };
}

function normalizeSnapshot(state, service = null) {
  const csi = state.csi;
  const pose = state.pose;
  const metadata = pose?.metadata || {};
  const support = pose?.support_observations?.four_node_entry_exit_shadow_core || {};
  const primaryRuntime = buildMotionRuntime(csi, pose);
  const garageLayout = primaryRuntime.garage || normalizeGarageLayout(csi);
  const secondaryRuntime = buildExperimentalRuntime(csi);
  const trackBShadow = buildTrackBShadowRuntime(csi);
  const v15Shadow = buildV15ShadowRuntime(csi);
  const v19Shadow = buildV19ShadowRuntime(csi);
  const v27Binary7NodeShadow = buildV27Binary7NodeRuntime(csi);
  const garageRatioV2Shadow = buildGarageRatioV2ShadowRuntime(csi);
  const zoneCalibrationShadow = buildZoneCalibrationShadow(csi);
  const baselineStatus = buildBaselineStatus(csi);
  const signalQuality = buildSignalQuality(csi);
  const operatorPresence = evaluateOperatorPresenceGate(csi);
  const shadowDisagreement = buildShadowDisagreement(csi, primaryRuntime, v27Binary7NodeShadow);
  const ambiguity = deriveAmbiguityMode(csi, pose, support, operatorPresence);
  const lastMeaningfulEvent = deriveLastMeaningfulEvent(csi, pose, support, operatorPresence, ambiguity);
  const recordingStatus = state.recording.status || {};
  const lastStopResult = normalizeRecordingStopResult(state.recording.lastStopResult, recordingStatus);
  const startupSignalGuard = normalizeStartupSignalGuard(
    recordingStatus.startup_signal_guard,
    recordingStatus,
    lastStopResult
  );
  const cachedRunIds = service ? Array.from(service.forensicDetailCache.keys()) : [];
  const inflightRunIds = service ? Array.from(service.forensicDetailRequests.keys()) : [];
  const lastSessionSummary = getRecordingLastSessionSummary(state.recording);
  const freeformSummary = isFreeformSessionSummary(lastSessionSummary) ? lastSessionSummary : null;

  return {
    now: new Date().toISOString(),
    errors: { ...state.errors },
    info: state.info,
    status: state.status,
    metrics: state.metrics,
    csi,
    pose,
    recording: {
      ...state.recording,
      lastStopResult,
      startupSignalGuard,
      stopFailure: lastStopResult?.deadOnStart
        ? {
            code: 'csi_dead_on_start',
            message: lastStopResult.message,
            stopReason: lastStopResult.stopReason,
            guard: startupSignalGuard
        }
        : null,
      teacherSource: {
        ...(state.recording.teacherSource || buildTeacherSourceState())
      },
      manual: {
        ...state.recording.manual
      },
      freeform: {
        ...state.recording.freeform,
        lastSummary: freeformSummary
          ? { ...freeformSummary }
          : null
      },
      guided: {
        ...state.recording.guided,
        logs: [...state.recording.guided.logs]
      },
      fewshotCalibration: {
        ...state.recording.fewshotCalibration,
        logs: [...state.recording.fewshotCalibration.logs],
        currentStep: state.recording.fewshotCalibration.currentStep
          ? { ...state.recording.fewshotCalibration.currentStep }
          : null,
        fitResult: state.recording.fewshotCalibration.fitResult
          ? { ...state.recording.fewshotCalibration.fitResult }
          : null,
        storageStatus: state.recording.fewshotCalibration.storageStatus
          ? { ...state.recording.fewshotCalibration.storageStatus }
          : null
      }
    },
    runtimeModels: buildRuntimeModelsState(state),
    services: buildServiceCards(state.status),
    forensics: {
      ...state.forensics,
      cacheState: {
        cachedRunIds,
        inflightRunIds
      }
    },
    validation: {
      ...state.validation,
      status: state.validation.status ? { ...state.validation.status } : null,
      selectedSegmentDetail: state.validation.selectedSegmentDetail
        ? { ...state.validation.selectedSegmentDetail }
        : null
    },
    live: {
      trust: deriveTrust(csi, support),
      failureSignal: deriveFailureSignal(pose, support),
      lastMeaningfulEvent,
      primaryRuntime,
      secondaryRuntime,
      trackBShadow,
      v7Shadow: v15Shadow,
      v15Shadow,
      v8Shadow: v15Shadow,
      v27Binary7NodeShadow,
      garageRatioV2Shadow,
      zoneCalibrationShadow,
      operatorPresence,
      ambiguity,
      supportPath: {
        candidateName: support?.candidate_name || 'unavailable',
        candidateStatus: support?.candidate_status || 'unknown',
        status: support?.status || 'unknown',
        reason: support?.reason || 'unknown',
        supportOnly: Boolean(support?.support_only),
        authoritative: Boolean(support?.authoritative),
        topologyMatch: support?.topology_match !== false,
        requiredTopologySignature: support?.required_topology_signature || 'unknown',
        observedTopologySignature: support?.observed_topology_signature || 'unknown',
        threshold: safeNumber(support?.threshold),
        probability: safeNumber(support?.probability),
        positive: Boolean(support?.positive),
        lastEvent: support?.last_event || null,
        lastEventTs: support?.last_event_ts || null,
        lastEventAgeSec: safeNumber(support?.last_event_age_sec),
        pulseSeq: safeNumber(support?.pulse_seq, 0) || 0,
        pendingReview: Boolean(support?.pending_review),
        pendingDirection: support?.pending_direction || null,
        contextValidity: support?.context_validity || 'unknown',
        invalidationReason: support?.invalidation_reason || null,
        reviewHoldSec: safeNumber(support?.review_hold_sec),
        maxActiveSec: safeNumber(support?.max_active_sec),
        gapGraceSec: safeNumber(support?.gap_grace_sec),
        scope: asArray(support?.runtime_scope)
      },
      topology: {
        signature: support?.observed_topology_signature || metadata?.live_source_signature?.join('+') || 'unknown',
        liveNodes: asArray(metadata?.live_source_signature),
        sourceCount: safeNumber(metadata?.live_source_count, safeNumber(csi?.nodes_active, 0)) || 0,
        liveWindowSeconds: safeNumber(metadata?.live_window_seconds, safeNumber(csi?.window_age_sec)),
        liveTotalPackets: safeNumber(metadata?.live_total_packets, safeNumber(csi?.packets_in_window)),
        lastPacketAgeSec: safeNumber(metadata?.live_last_packet_age_sec, safeNumber(csi?.window_age_sec)),
        motionWindowSeconds: safeNumber(metadata?.motion_window_seconds, safeNumber(csi?.window_age_sec)),
        motionTotalPackets: safeNumber(metadata?.motion_total_packets, safeNumber(csi?.packets_in_window)),
        vitalsWindowSeconds: safeNumber(metadata?.vitals_window_seconds),
        vitalsTotalPackets: safeNumber(metadata?.vitals_total_packets),
        nodes: buildNodeSummary(csi, pose, state.status)
      },
      motion: {
        label: csi?.motion_state || metadata?.motion_runtime_label || metadata?.motion_label || pose?.motion_state || 'unknown',
        probabilities: metadata?.motion_runtime_probabilities || metadata?.motion_probabilities || {},
        state: csi?.motion_state || pose?.motion_state || 'unknown',
        confidence: safeNumber(csi?.motion_confidence),
        activity: pose?.activity || 'unknown'
      },
      fingerprint: {
        label: metadata?.room_fingerprint_label || 'unknown',
        margin: safeNumber(metadata?.room_fingerprint_margin),
        distances: metadata?.room_fingerprint_distances || {}
      },
      coordinate: {
        xCm: safeNumber(metadata?.coordinate_plane_x_cm, safeNumber(csi?.target_x) != null ? safeNumber(csi?.target_x) * 100 : null),
        yCm: safeNumber(metadata?.coordinate_plane_y_cm, safeNumber(csi?.target_y) != null ? safeNumber(csi?.target_y) * 100 : null),
        xMeters: safeNumber(csi?.target_x, safeNumber(metadata?.coordinate_plane_x_cm) != null ? safeNumber(metadata.coordinate_plane_x_cm) / 100 : null),
        yMeters: safeNumber(csi?.target_y, safeNumber(metadata?.coordinate_plane_y_cm) != null ? safeNumber(metadata.coordinate_plane_y_cm) / 100 : null),
        targetZone: csi?.target_zone || 'unknown',
        operatorXMeters: operatorPresence.lastConfirmedX,
        operatorYMeters: operatorPresence.lastConfirmedY,
        operatorTargetZone: operatorPresence.lastConfirmedZone || 'unknown',
        ambiguityActive: Boolean(ambiguity.active),
        ambiguityTargetZone: ambiguity.targetZone || 'unknown',
        source: metadata?.coordinate_model_source || 'unknown',
        history: buildCoordinateHistory(csi, garageLayout),
        motionHistory: buildCoordinateHistory(csi, garageLayout, { motionOnly: true }),
        activeForMap: Boolean(operatorPresence.confirmed && ambiguity.singleTargetAllowed),
        shadowXMeters: v15Shadow.targetX,
        shadowYMeters: v15Shadow.targetY,
        shadowTargetZone: v15Shadow.targetZone || 'unknown',
        shadowSource: v15Shadow.coordinateSource || null
      },
      garage: garageLayout,
      v19Shadow,
      baselineStatus,
      signalQuality,
      shadowDisagreement,
      shadowDiagnostics: buildShadowDiagnostics(metadata),
      multiPersonEstimate: buildMultiPersonEstimate(csi),
      runtimePaths: buildRuntimePaths(csi, metadata, support, trackBShadow, v19Shadow, v27Binary7NodeShadow)
    }
  };
}

export class CsiOperatorService {
  constructor() {
    this.state = {
      info: null,
      status: null,
      metrics: null,
      csi: null,
      pose: null,
      runtimeModels: {
        items: [],
        activeModelId: null,
        defaultModelId: null,
        loadedAt: null,
        loading: false,
        error: null,
        switching: false,
        actionError: null
      },
      recording: buildRecordingState(),
      errors: {},
      forensics: {
        manifest: [],
        manifestLoadedAt: null,
        manifestError: null,
        selectedRunId: null,
        selectedRun: null,
        selectedRunLoadedAt: null,
        selectedRunError: null,
        loadingManifest: false,
        loadingRun: false
      },
      validation: {
        status: null,
        loadedAt: null,
        loading: false,
        error: null,
        selectedSegmentId: null,
        selectedSegmentDetail: null
      }
    };
    this.subscribers = new Set();
    this.timers = new Map();
    this.running = false;
    this.guidedStepTimer = null;
    this.guidedPauseTimer = null;
    this.fewshotStepTimer = null;
    this.fewshotPauseTimer = null;
    this.forensicDetailCache = new Map();
    this.forensicDetailRequests = new Map();
    this.forensicDetailRevision = 0;
    this.guidedSpeechToken = 0;
    this.guidedUtterance = null;
    this.operatorCueToken = 0;
    this.operatorCueUtterance = null;
    this.visibilityListener = () => {
      if (!document.hidden) {
        void this.refreshAll(true);
      }
    };
  }

  subscribe(callback) {
    this.subscribers.add(callback);
    callback(normalizeSnapshot(this.state, this));
    return () => this.subscribers.delete(callback);
  }

  emit() {
    const snapshot = normalizeSnapshot(this.state, this);
    this.subscribers.forEach((callback) => {
      try {
        callback(snapshot);
      } catch (error) {
        console.error('CSI operator subscriber failed:', error);
      }
    });
  }

  clearGuidedTimers() {
    if (this.guidedStepTimer) {
      clearTimeout(this.guidedStepTimer);
      this.guidedStepTimer = null;
    }
    if (this.guidedPauseTimer) {
      clearTimeout(this.guidedPauseTimer);
      this.guidedPauseTimer = null;
    }
    this.cancelGuidedSpeech();
  }

  clearFewshotCalibrationTimers() {
    if (this.fewshotStepTimer) {
      clearTimeout(this.fewshotStepTimer);
      this.fewshotStepTimer = null;
    }
    if (this.fewshotPauseTimer) {
      clearTimeout(this.fewshotPauseTimer);
      this.fewshotPauseTimer = null;
    }
    this.cancelGuidedSpeech();
  }

  cancelGuidedSpeech() {
    this.guidedSpeechToken += 1;
    this.guidedUtterance = null;
    this.stopServerSpeech();
    if (typeof window !== 'undefined' && window.speechSynthesis) {
      try {
        window.speechSynthesis.cancel();
      } catch (error) {
        console.warn('Failed to cancel guided speech:', error);
      }
    }
  }

  cancelOperatorCue() {
    this.operatorCueToken += 1;
    this.operatorCueUtterance = null;
    this.stopServerSpeech();
    if (typeof window !== 'undefined' && window.speechSynthesis) {
      try {
        window.speechSynthesis.cancel();
      } catch (error) {
        console.warn('Failed to cancel operator cue:', error);
      }
    }
  }

  stopServerSpeech() {
    requestUiJson(CSI_TTS_ENDPOINTS.STOP, { method: 'POST' }).catch((error) => {
      console.warn('Failed to stop server TTS:', error);
    });
  }

  async speakServerPrompt(text) {
    if (!text) {
      return false;
    }
    try {
      const payload = await requestUiJson(CSI_TTS_ENDPOINTS.SPEAK, {
        method: 'POST',
        body: {
          text,
          block: true
        }
      });
      return payload?.ok === true && payload?.backend === 'elevenlabs';
    } catch (error) {
      console.warn('Server TTS failed, falling back to browser voice:', error);
      return false;
    }
  }

  getGuidedVoice() {
    if (typeof window === 'undefined' || !window.speechSynthesis) {
      return null;
    }
    const voices = window.speechSynthesis.getVoices?.() || [];
    return voices.find((voice) => /^ru/i.test(voice.lang || ''))
      || voices.find((voice) => /milena/i.test(voice.name || ''))
      || null;
  }

  async speakOperatorCue(text) {
    if (!text) {
      return false;
    }

    this.cancelOperatorCue();
    const token = ++this.operatorCueToken;

    if (await this.speakServerPrompt(text)) {
      return this.operatorCueToken === token;
    }

    if (typeof window === 'undefined' || !window.speechSynthesis || typeof window.SpeechSynthesisUtterance === 'undefined') {
      return false;
    }

    return new Promise((resolve) => {
      try {
        const utterance = new SpeechSynthesisUtterance(text);
        utterance.lang = 'ru-RU';
        utterance.rate = 1;
        utterance.pitch = 1;
        utterance.volume = 1;

        const voices = window.speechSynthesis.getVoices?.() || [];
        const preferredVoice = voices.find((voice) => voice.lang?.toLowerCase().startsWith('ru'));
        if (preferredVoice) {
          utterance.voice = preferredVoice;
        }

        const finalize = () => {
          if (this.operatorCueToken === token) {
            this.operatorCueUtterance = null;
          }
          resolve(true);
        };

        utterance.onend = finalize;
        utterance.onerror = finalize;
        this.operatorCueUtterance = utterance;
        window.speechSynthesis.speak(utterance);
      } catch (error) {
        console.warn('Operator cue failed:', error);
        resolve(false);
      }
    });
  }

  async speakGuidedPrompt(text, { forceSilence = false } = {}) {
    if (forceSilence || !text) {
      return;
    }

    this.cancelGuidedSpeech();
    const token = this.guidedSpeechToken;

    if (await this.speakServerPrompt(text)) {
      return;
    }

    if (typeof window === 'undefined' || typeof window.SpeechSynthesisUtterance === 'undefined' || !window.speechSynthesis) {
      return;
    }

    await new Promise((resolve) => {
      const utterance = new window.SpeechSynthesisUtterance(text);
      utterance.lang = 'ru-RU';
      utterance.rate = 1;
      utterance.pitch = 1;
      utterance.volume = 1;
      const voice = this.getGuidedVoice();
      if (voice) {
        utterance.voice = voice;
      }
      utterance.onend = () => {
        if (token === this.guidedSpeechToken) {
          this.guidedUtterance = null;
        }
        resolve();
      };
      utterance.onerror = () => {
        if (token === this.guidedSpeechToken) {
          this.guidedUtterance = null;
        }
        resolve();
      };
      this.guidedUtterance = utterance;
      window.speechSynthesis.speak(utterance);
    });
  }

  async runGuidedStartSequence(pack, step, stepIndex, runToken) {
    const guided = this.state.recording.guided;
    if (guided.runToken !== runToken) {
      return false;
    }

    guided.status = 'cueing';
    guided.sequencePhase = 'prompt';
    guided.countdownValue = null;
    this.emit();

    const instructionPrompt = step.voiceInstruction
      || `Шаг ${stepIndex + 1}. ${step.label}. ${step.instruction}`;
    await this.speakGuidedPrompt(instructionPrompt, {
      forceSilence: guided.voiceEnabled === false
    });
    if (guided.runToken !== runToken) {
      return false;
    }

    const countdownSec = Number(pack.countdownSec || DEFAULT_GUIDED_COUNTDOWN_SEC);
    for (let countdown = countdownSec; countdown >= 1; countdown -= 1) {
      guided.status = 'cueing';
      guided.sequencePhase = 'countdown';
      guided.countdownValue = countdown;
      this.emit();
      await delay(1000);
      if (guided.runToken !== runToken) {
        return false;
      }
    }

    guided.status = 'cueing';
    guided.sequencePhase = 'start_cue';
    guided.countdownValue = 0;
    this.emit();
    await this.speakGuidedPrompt(step.startCue || 'Старт', {
      forceSilence: guided.voiceEnabled === false
    });
    return guided.runToken === runToken;
  }

  resetForensicDetailCache() {
    this.forensicDetailRevision += 1;
    this.forensicDetailCache.clear();
    this.forensicDetailRequests.clear();
  }

  pruneForensicDetailCache(validRunIds) {
    if (!(validRunIds instanceof Set)) {
      return;
    }

    this.forensicDetailCache.forEach((_, runId) => {
      if (!validRunIds.has(runId)) {
        this.forensicDetailCache.delete(runId);
      }
    });

    this.forensicDetailRequests.forEach((_, runId) => {
      if (!validRunIds.has(runId)) {
        this.forensicDetailRequests.delete(runId);
      }
    });
  }

  getCachedForensicDetail(runId) {
    return this.forensicDetailCache.get(runId) || null;
  }

  async fetchForensicRunDetail(runId, { force = false } = {}) {
    if (!runId) {
      return null;
    }

    if (force) {
      this.forensicDetailCache.delete(runId);
      this.forensicDetailRequests.delete(runId);
    }

    const cachedEntry = !force ? this.getCachedForensicDetail(runId) : null;
    if (cachedEntry?.payload) {
      return cachedEntry.payload;
    }

    const inflightRequest = !force ? this.forensicDetailRequests.get(runId) : null;
    if (inflightRequest) {
      return inflightRequest;
    }

    const revision = this.forensicDetailRevision;
    const query = force
      ? `run_id=${encodeURIComponent(runId)}&_=${Date.now()}`
      : `run_id=${encodeURIComponent(runId)}`;
    const request = requestUiJson(`/api/agent7/forensics/run?${query}`)
      .then((payload) => {
        const currentRequest = this.forensicDetailRequests.get(runId);
        if (revision === this.forensicDetailRevision && currentRequest === request) {
          this.forensicDetailCache.set(runId, {
            payload,
            loadedAt: payload?.generated_at || new Date().toISOString()
          });
        }
        return payload;
      })
      .finally(() => {
        const currentRequest = this.forensicDetailRequests.get(runId);
        if (currentRequest === request) {
          this.forensicDetailRequests.delete(runId);
          this.emit();
        }
      });

    this.forensicDetailRequests.set(runId, request);
    this.emit();
    return request;
  }

  async prefetchForensicRuns(runIds, { force = false } = {}) {
    const uniqueRunIds = Array.from(new Set((runIds || []).filter(Boolean)));
    if (!uniqueRunIds.length) {
      return;
    }

    const targets = uniqueRunIds.filter((runId) => {
      if (force) {
        return true;
      }
      if (this.forensicDetailCache.has(runId)) {
        return false;
      }
      if (this.forensicDetailRequests.has(runId)) {
        return false;
      }
      return true;
    });

    if (!targets.length) {
      return;
    }

    await Promise.allSettled(targets.map((runId) => this.fetchForensicRunDetail(runId, { force })));
  }

  async start() {
    if (this.running) {
      return;
    }
    this.running = true;
    document.addEventListener('visibilitychange', this.visibilityListener);
    await this.refreshAll(true);
    this.schedule('csi', DEFAULT_POLLING.csi, () => this.refreshCsi());
    this.schedule('pose', DEFAULT_POLLING.pose, () => this.refreshPose());
    this.schedule('status', DEFAULT_POLLING.status, () => this.refreshStatus());
    this.schedule('metrics', DEFAULT_POLLING.metrics, () => this.refreshMetrics());
    this.schedule('info', DEFAULT_POLLING.info, () => this.refreshInfo());
    this.schedule('runtimeModels', DEFAULT_POLLING.runtimeModels, () => this.refreshRuntimeModels());
    this.schedule('recording', DEFAULT_POLLING.recording, () => this.refreshRecordingStatus());
    this.schedule('forensicRuns', DEFAULT_POLLING.forensicRuns, () => this.refreshForensicRuns());
    this.schedule('validation', DEFAULT_POLLING.validation, () => this.refreshValidationStatus());
  }

  stop() {
    this.running = false;
    document.removeEventListener('visibilitychange', this.visibilityListener);
    this.timers.forEach((timerId) => clearInterval(timerId));
    this.timers.clear();
    this.clearGuidedTimers();
    this.clearFewshotCalibrationTimers();
  }

  schedule(key, intervalMs, task) {
    if (this.timers.has(key)) {
      clearInterval(this.timers.get(key));
    }
    const timerId = setInterval(() => {
      if (document.hidden && key === 'pose') {
        return;
      }
      void task();
    }, intervalMs);
    this.timers.set(key, timerId);
  }

  async refreshAll(force = false) {
    await Promise.allSettled([
      this.refreshInfo(force),
      this.refreshStatus(force),
      this.refreshMetrics(force),
      this.refreshCsi(force),
      this.refreshPose(force),
      this.refreshRuntimeModels(force),
      this.refreshRecordingStatus(force),
      this.refreshForensicRuns(force),
      this.refreshValidationStatus(force)
    ]);
  }

  async refreshInfo(force = false) {
    try {
      this.state.info = await healthService.getApiInfo(force);
      delete this.state.errors.info;
    } catch (error) {
      this.state.errors.info = error.message;
    } finally {
      this.emit();
    }
  }

  async refreshStatus(force = false) {
    try {
      this.state.status = await healthService.getApiStatus(force);
      delete this.state.errors.status;
    } catch (error) {
      this.state.errors.status = error.message;
    } finally {
      this.emit();
    }
  }

  async refreshMetrics() {
    try {
      this.state.metrics = await healthService.getSystemMetrics();
      delete this.state.errors.metrics;
    } catch (error) {
      this.state.errors.metrics = error.message;
    } finally {
      this.emit();
    }
  }

  async refreshCsi(force = false) {
    try {
      this.state.csi = await apiService.get(CSI_STATUS_ENDPOINT, force ? { _: Date.now() } : {});
      delete this.state.errors.csi;
    } catch (error) {
      this.state.errors.csi = error.message;
    } finally {
      this.emit();
    }
  }

  async refreshPose(force = false) {
    try {
      this.state.pose = await apiService.get(API_CONFIG.ENDPOINTS.POSE.CURRENT, force ? { _: Date.now() } : {});
      delete this.state.errors.pose;
    } catch (error) {
      this.state.errors.pose = error.message;
    } finally {
      this.emit();
    }
  }

  async refreshRuntimeModels(force = false) {
    const runtimeModels = this.state.runtimeModels;
    if (runtimeModels.loading && !force) {
      return runtimeModels.items;
    }

    runtimeModels.loading = true;
    if (force) {
      runtimeModels.error = null;
    }
    this.emit();

    try {
      const payload = await apiService.get(
        CSI_MODELS_ENDPOINT,
        force ? { _: Date.now() } : {}
      );
      runtimeModels.items = Array.isArray(payload?.models) ? payload.models : [];
      runtimeModels.activeModelId = payload?.active_model_id || this.state.csi?.model_id || null;
      runtimeModels.defaultModelId = payload?.default_model_id || null;
      runtimeModels.loadedAt = new Date().toISOString();
      runtimeModels.error = null;
      return runtimeModels.items;
    } catch (error) {
      runtimeModels.error = error.message;
      return runtimeModels.items;
    } finally {
      runtimeModels.loading = false;
      this.emit();
    }
  }

  async refreshValidationStatus(force = false) {
    const validation = this.state.validation;
    if (validation.loading && !force) {
      return validation.status;
    }
    validation.loading = true;
    if (force) {
      validation.error = null;
    }
    this.emit();
    try {
      const payload = await apiService.get(
        CSI_VALIDATION_ENDPOINTS.STATUS,
        force ? { _: Date.now() } : {}
      );
      validation.status = payload || null;
      validation.loadedAt = new Date().toISOString();
      validation.error = null;
      return validation.status;
    } catch (error) {
      validation.error = error.message;
      return validation.status;
    } finally {
      validation.loading = false;
      this.emit();
    }
  }

  async fetchValidationSegmentDetail(segmentId) {
    if (!segmentId) {
      return null;
    }
    try {
      const payload = await apiService.get(
        CSI_VALIDATION_ENDPOINTS.SEGMENT,
        { segment_id: segmentId, _: Date.now() }
      );
      this.state.validation.selectedSegmentDetail = payload || null;
      this.state.validation.selectedSegmentId = segmentId;
      this.emit();
      return payload;
    } catch (error) {
      this.state.validation.error = error.message;
      this.emit();
      return null;
    }
  }

  async resolveValidationSegment(segmentId, resolution, operatorNote = null) {
    if (!segmentId || !resolution) {
      return { ok: false, error: 'segment_id/resolution required' };
    }
    try {
      await apiService.post(CSI_VALIDATION_ENDPOINTS.RESOLVE, {
        segment_id: segmentId,
        resolution,
        operator_note: operatorNote
      });
      await this.refreshValidationStatus(true);
      return { ok: true };
    } catch (error) {
      this.state.validation.error = error.message;
      this.emit();
      return { ok: false, error: error.message };
    }
  }

  async batchApproveValidated({ recordingId = null, dryRun = false } = {}) {
    try {
      const payload = await apiService.post(CSI_VALIDATION_ENDPOINTS.BATCH_APPROVE, {
        recording_id: recordingId,
        dry_run: dryRun
      });
      await this.refreshValidationStatus(true);
      return payload;
    } catch (error) {
      this.state.validation.error = error.message;
      this.emit();
      return { ok: false, error: error.message };
    }
  }

  async selectRuntimeModel(modelId) {
    if (!modelId) {
      return { ok: false, error: 'model_id is required' };
    }

    const runtimeModels = this.state.runtimeModels;
    if (runtimeModels.switching) {
      return { ok: false, error: 'Модель уже переключается.' };
    }

    runtimeModels.switching = true;
    runtimeModels.actionError = null;
    this.emit();

    try {
      const payload = await apiService.post(CSI_MODEL_SELECT_ENDPOINT, {
        model_id: modelId
      });
      await Promise.allSettled([
        this.refreshRuntimeModels(true),
        this.refreshCsi(true)
      ]);
      runtimeModels.actionError = null;
      return { ok: true, payload };
    } catch (error) {
      runtimeModels.actionError = error.message;
      return { ok: false, error: error.message };
    } finally {
      runtimeModels.switching = false;
      this.emit();
    }
  }

  selectGuidedCapturePack(packId) {
    const pack = getGuidedCapturePack(packId);
    if (!pack) {
      return;
    }
    this.state.recording.selectedPackId = packId;
    const guided = this.state.recording.guided;
    if (!ACTIVE_GUIDED_STATUSES.includes(guided.status)) {
      guided.packId = packId;
      guided.voiceEnabled = pack.voiceEnabledByDefault !== false;
      guided.withVideo = pack.withVideo !== false;
    }
    this.emit();
  }

  selectFewshotCalibrationProtocol(protocolId) {
    const protocol = getFewshotCalibrationProtocol(protocolId);
    if (!protocol) {
      return;
    }
    this.state.recording.fewshotCalibration.protocolId = protocol.id;
    if (!['cueing', 'running', 'paused', 'stopping'].includes(this.state.recording.fewshotCalibration.status)) {
      this.state.recording.fewshotCalibration.currentStep = null;
      this.state.recording.fewshotCalibration.stepIndex = -1;
      this.state.recording.fewshotCalibration.fitResult = null;
    }
    this.emit();
  }

  async runFewshotCalibrationStartSequence(protocol, step, stepIndex, runToken) {
    const fewshot = this.state.recording.fewshotCalibration;
    if (fewshot.runToken !== runToken) {
      return false;
    }

    fewshot.status = 'cueing';
    fewshot.sequencePhase = 'prompt';
    fewshot.countdownValue = null;
    this.emit();

    await this.speakGuidedPrompt(
      step.voiceInstruction || `Шаг ${stepIndex + 1}. ${step.label}. ${step.instruction}`,
      { forceSilence: fewshot.voiceEnabled === false }
    );
    if (fewshot.runToken !== runToken) {
      return false;
    }

    for (let countdown = 4; countdown >= 1; countdown -= 1) {
      fewshot.status = 'cueing';
      fewshot.sequencePhase = 'countdown';
      fewshot.countdownValue = countdown;
      this.emit();
      await delay(1000);
      if (fewshot.runToken !== runToken) {
        return false;
      }
    }

    fewshot.status = 'cueing';
    fewshot.sequencePhase = 'start_cue';
    fewshot.countdownValue = 0;
    this.emit();
    await this.speakGuidedPrompt('Старт', { forceSilence: fewshot.voiceEnabled === false });
    return fewshot.runToken === runToken;
  }

  async startFewshotCalibration(protocolId = null) {
    const recording = this.state.recording;
    const fewshot = recording.fewshotCalibration;
    const protocol = getFewshotCalibrationProtocol(protocolId || fewshot.protocolId);
    const activeMode = inferActiveRecordingMode(recording) || recording.activeMode;

    if (['cueing', 'running', 'paused', 'stopping'].includes(fewshot.status)) {
      recording.actionError = 'Few-shot calibration уже активна.';
      this.emit();
      return { ok: false, error: recording.actionError };
    }

    if (activeMode || recording.status?.recording) {
      recording.actionError = 'Сначала заверши активную запись или legacy guided/manual ветку.';
      this.emit();
      return { ok: false, error: recording.actionError };
    }

    if (!this.state.csi?.running || !this.state.csi?.model_loaded) {
      recording.actionError = 'CSI runtime не готов. Сначала подними живой runtime.';
      this.emit();
      return { ok: false, error: recording.actionError };
    }

    if ((safeNumber(this.state.csi?.nodes_active, 0) || 0) < 3) {
      recording.actionError = 'Для guided calibration нужно минимум 3 активные ноды.';
      this.emit();
      return { ok: false, error: recording.actionError };
    }

    this.clearFewshotCalibrationTimers();
    recording.actionError = null;
    const runToken = fewshot.runToken + 1;
    recording.fewshotCalibration = {
      protocolId: protocol.id,
      runToken,
      packetSessionId: null,
      packetStoragePath: null,
      packetStatus: 'idle',
      status: 'idle',
      sequencePhase: null,
      countdownValue: null,
      stepIndex: -1,
      stepStartedAt: null,
      stepEndsAt: null,
      pauseUntil: null,
      currentStep: null,
      voiceEnabled: true,
      logs: [],
      completedAt: null,
      lastError: null,
      fitResult: null,
      storageStatus: null
    };
    this.emit();

    try {
      await apiService.post(CSI_ZONE_ENDPOINTS.RESET, {});
      const storageSession = await apiService.post(
        CSI_FEWSHOT_ENDPOINTS.START,
        buildFewshotProtocolSessionPayload(protocol)
      );
      recording.fewshotCalibration.packetSessionId = storageSession?.session_id || null;
      recording.fewshotCalibration.packetStoragePath = storageSession?.storage_path || null;
      recording.fewshotCalibration.packetStatus = storageSession?.status || 'active';
      recording.fewshotCalibration.storageStatus = storageSession || null;
      await this.refreshCsi(true);
    } catch (error) {
      recording.fewshotCalibration.status = 'error';
      recording.fewshotCalibration.lastError = error.message;
      recording.actionError = error.message;
      this.emit();
      return { ok: false, error: error.message };
    }

    return this.runFewshotCalibrationStep(protocol.id, 0, runToken);
  }

  async runFewshotCalibrationStep(protocolId, stepIndex, runToken) {
    const protocol = getFewshotCalibrationProtocol(protocolId);
    const recording = this.state.recording;
    const fewshot = recording.fewshotCalibration;
    const step = protocol?.steps?.[stepIndex];

    if (!protocol || !step || fewshot.runToken !== runToken) {
      return { ok: false, error: 'Few-shot calibration step устарел.' };
    }

    fewshot.status = 'cueing';
    fewshot.sequencePhase = 'prompt';
    fewshot.countdownValue = null;
    fewshot.stepIndex = stepIndex;
    fewshot.stepStartedAt = null;
    fewshot.stepEndsAt = null;
    fewshot.pauseUntil = null;
    fewshot.currentStep = {
      ...step,
      index: stepIndex,
      totalSteps: protocol.steps.length
    };
    fewshot.logs = [
      ...fewshot.logs,
      {
        stepId: step.id,
        stepLabel: step.label,
        captureZone: step.captureZone || null,
        displayZone: step.displayZone || 'unknown',
        researchOnly: Boolean(step.researchOnly),
        status: 'cueing',
        startedAt: null,
        expectedDurationSec: step.durationSec
      }
    ];
    this.emit();

    try {
      const sequenceReady = await this.runFewshotCalibrationStartSequence(protocol, step, stepIndex, runToken);
      if (!sequenceReady || fewshot.runToken !== runToken) {
        return { ok: false, error: 'Few-shot calibration start sequence interrupted.' };
      }

      let captureStartPayload = null;
      if (step.captureZone) {
        captureStartPayload = await apiService.post(CSI_ZONE_ENDPOINTS.START, {
          zone: step.captureZone,
          duration_sec: Number(step.durationSec || 50)
        });
      }

      const storageStepStart = await apiService.post(CSI_FEWSHOT_ENDPOINTS.STEP_START, {
        step_id: step.id,
        started_at: nowIso(),
        metadata: {
          label: step.label,
          display_zone: step.displayZone || null,
          capture_zone: step.captureZone || null,
          activity: step.activity || null,
          research_only: Boolean(step.researchOnly),
          target_windows: Number(step.targetWindows || 0),
          duration_sec: Number(step.durationSec || 0),
          capture_start_payload: captureStartPayload
        }
      });

      const startedAt = nowIso();
      fewshot.status = 'running';
      fewshot.sequencePhase = null;
      fewshot.countdownValue = null;
      fewshot.stepStartedAt = startedAt;
      fewshot.stepEndsAt = new Date(Date.now() + Number(step.durationSec || 0) * 1000).toISOString();
      const lastIndex = fewshot.logs.length - 1;
      fewshot.logs[lastIndex] = {
        ...fewshot.logs[lastIndex],
        status: 'running',
        startedAt,
        captureStartPayload,
        storageStepStart
      };
      this.emit();
      this.fewshotStepTimer = setTimeout(() => {
        void this.completeFewshotCalibrationStep(protocol.id, stepIndex, runToken);
      }, Number(step.durationSec || 0) * 1000);
      return { ok: true };
    } catch (error) {
      fewshot.status = 'error';
      fewshot.lastError = error.message;
      fewshot.completedAt = nowIso();
      recording.actionError = error.message;
      const lastIndex = fewshot.logs.length - 1;
      if (lastIndex >= 0) {
        fewshot.logs[lastIndex] = {
          ...fewshot.logs[lastIndex],
          status: 'error',
          finishedAt: nowIso(),
          error: error.message
        };
      }
      this.emit();
      return { ok: false, error: error.message };
    }
  }

  async completeFewshotCalibrationStep(protocolId, stepIndex, runToken) {
    const protocol = getFewshotCalibrationProtocol(protocolId);
    const recording = this.state.recording;
    const fewshot = recording.fewshotCalibration;
    const step = protocol?.steps?.[stepIndex];

    if (!protocol || !step || fewshot.runToken !== runToken) {
      return;
    }

    fewshot.status = 'stopping';
    fewshot.sequencePhase = null;
    fewshot.countdownValue = null;
    this.emit();

    let captureStopPayload = null;
    try {
      if (step.captureZone) {
        captureStopPayload = await apiService.post(CSI_ZONE_ENDPOINTS.STOP, {});
      }
      const storageStepComplete = await apiService.post(CSI_FEWSHOT_ENDPOINTS.STEP_COMPLETE, {
        step_id: step.id,
        completed_at: nowIso(),
        metadata: {
          label: step.label,
          display_zone: step.displayZone || null,
          capture_zone: step.captureZone || null,
          activity: step.activity || null,
          research_only: Boolean(step.researchOnly),
          capture_stop_payload: captureStopPayload
        }
      });
      fewshot.storageStatus = storageStepComplete || fewshot.storageStatus;
    } catch (error) {
      fewshot.status = 'error';
      fewshot.lastError = error.message;
      fewshot.completedAt = nowIso();
      recording.actionError = error.message;
      const lastIndex = fewshot.logs.length - 1;
      if (lastIndex >= 0) {
        fewshot.logs[lastIndex] = {
          ...fewshot.logs[lastIndex],
          status: 'error',
          finishedAt: nowIso(),
          error: error.message
        };
      }
      this.emit();
      return;
    }

    const lastIndex = fewshot.logs.length - 1;
    if (lastIndex >= 0) {
        fewshot.logs[lastIndex] = {
          ...fewshot.logs[lastIndex],
          status: 'completed',
          finishedAt: nowIso(),
          captureStopPayload
        };
    }

    const nextStepIndex = stepIndex + 1;
    if (nextStepIndex >= protocol.steps.length) {
      try {
        const fitResult = await apiService.post(CSI_ZONE_ENDPOINTS.FIT, {});
        const finalizePayload = await apiService.post(CSI_FEWSHOT_ENDPOINTS.FINALIZE, {
          fit_result: fitResult,
          completed_at: nowIso(),
          status: 'completed',
          metadata: {
            ui_status: 'completed',
            packet_status: 'ready_for_shadow_adaptation'
          }
        });
        fewshot.fitResult = fitResult;
        fewshot.storageStatus = finalizePayload || fewshot.storageStatus;
        fewshot.packetStatus = finalizePayload?.status || 'completed';
        fewshot.packetStoragePath = finalizePayload?.storage_path || fewshot.packetStoragePath;
        fewshot.status = 'completed';
        fewshot.completedAt = nowIso();
        fewshot.currentStep = null;
        fewshot.stepStartedAt = null;
        fewshot.stepEndsAt = null;
        fewshot.pauseUntil = null;
        recording.actionError = null;
      } catch (error) {
        try {
          const finalizePayload = await apiService.post(CSI_FEWSHOT_ENDPOINTS.FINALIZE, {
            fit_result: { ok: false, error: error.message },
            completed_at: nowIso(),
            status: 'error',
            metadata: {
              ui_status: 'fit_error'
            }
          });
          fewshot.storageStatus = finalizePayload || fewshot.storageStatus;
          fewshot.packetStatus = finalizePayload?.status || 'error';
          fewshot.packetStoragePath = finalizePayload?.storage_path || fewshot.packetStoragePath;
        } catch (storageError) {
          fewshot.storageStatus = { ok: false, error: storageError.message };
        }
        fewshot.status = 'error';
        fewshot.lastError = error.message;
        fewshot.completedAt = nowIso();
        fewshot.fitResult = { ok: false, error: error.message };
        recording.actionError = error.message;
      } finally {
        await this.refreshCsi(true);
        this.emit();
      }
      return;
    }

    const pauseBetweenStepsSec = Number(protocol.pauseBetweenStepsSec || 0);
    fewshot.status = pauseBetweenStepsSec > 0 ? 'paused' : 'idle';
    fewshot.sequencePhase = null;
    fewshot.countdownValue = null;
    fewshot.currentStep = null;
    fewshot.stepStartedAt = null;
    fewshot.stepEndsAt = null;
    fewshot.pauseUntil = pauseBetweenStepsSec > 0
      ? new Date(Date.now() + pauseBetweenStepsSec * 1000).toISOString()
      : null;
    this.emit();

    if (pauseBetweenStepsSec > 0) {
      this.fewshotPauseTimer = setTimeout(() => {
        void this.runFewshotCalibrationStep(protocol.id, nextStepIndex, runToken);
      }, pauseBetweenStepsSec * 1000);
      return;
    }

    void this.runFewshotCalibrationStep(protocol.id, nextStepIndex, runToken);
  }

  async stopFewshotCalibration() {
    const recording = this.state.recording;
    const fewshot = recording.fewshotCalibration;

    if (!fewshot.protocolId || !['cueing', 'running', 'paused', 'stopping'].includes(fewshot.status)) {
      return { ok: false, error: 'Few-shot calibration не активна.' };
    }

    this.clearFewshotCalibrationTimers();
    const currentStep = fewshot.currentStep;
    fewshot.runToken += 1;
    fewshot.status = 'stopping';
    fewshot.sequencePhase = null;
    fewshot.countdownValue = null;
    this.emit();

    try {
      if (currentStep?.captureZone) {
        await apiService.post(CSI_ZONE_ENDPOINTS.STOP, {});
      }
      const storageReset = await apiService.post(CSI_FEWSHOT_ENDPOINTS.RESET, {});
      fewshot.storageStatus = storageReset || fewshot.storageStatus;
      fewshot.packetStatus = storageReset?.status || 'cancelled';
      fewshot.packetStoragePath = storageReset?.storage_path || fewshot.packetStoragePath;
    } catch (error) {
      if (!/No zone capture in progress/i.test(error.message || '')) {
        fewshot.status = 'error';
        fewshot.lastError = error.message;
        fewshot.completedAt = nowIso();
        recording.actionError = error.message;
        this.emit();
        return { ok: false, error: error.message };
      }
    }

    fewshot.status = 'cancelled';
    fewshot.completedAt = nowIso();
    fewshot.currentStep = null;
    fewshot.stepStartedAt = null;
    fewshot.stepEndsAt = null;
    fewshot.pauseUntil = null;
    await this.refreshCsi(true);
    this.emit();
    return { ok: true };
  }

  async resetFewshotCalibration() {
    const recording = this.state.recording;
    const fewshot = recording.fewshotCalibration;
    const protocolId = fewshot.protocolId || FEWSHOT_CALIBRATION_PROTOCOLS[0]?.id || null;

    if (['cueing', 'running', 'paused', 'stopping'].includes(fewshot.status)) {
      await this.stopFewshotCalibration();
    }

    try {
      await apiService.post(CSI_ZONE_ENDPOINTS.RESET, {});
      const storageReset = await apiService.post(CSI_FEWSHOT_ENDPOINTS.RESET, {});
      recording.fewshotCalibration = {
        protocolId,
        runToken: 0,
        packetSessionId: null,
        packetStoragePath: null,
        packetStatus: storageReset?.status || 'idle',
        status: 'idle',
        sequencePhase: null,
        countdownValue: null,
        stepIndex: -1,
        stepStartedAt: null,
        stepEndsAt: null,
        pauseUntil: null,
        currentStep: null,
        voiceEnabled: true,
        logs: [],
        completedAt: null,
        lastError: null,
        fitResult: null,
        storageStatus: storageReset || null
      };
      recording.actionError = null;
      await this.refreshCsi(true);
      this.emit();
      return { ok: true };
    } catch (error) {
      recording.actionError = error.message;
      this.emit();
      return { ok: false, error: error.message };
    }
  }

  async runRecordingPreflight({ packId = null, force = true, checkVideoOverride = null } = {}) {
    const recording = this.state.recording;
    const pack = getGuidedCapturePack(packId || recording.selectedPackId);
    const checkVideo = typeof checkVideoOverride === 'boolean'
      ? checkVideoOverride
      : pack?.preflightCheckVideo !== false;
    const teacherContract = buildTeacherSourceContract(recording, {
      withVideo: checkVideo,
      videoRequired: checkVideo,
      allowLegacyNone: !checkVideo
    });

    if (recording.preflightLoading) {
      return recording.preflight;
    }

    recording.selectedPackId = pack?.id || recording.selectedPackId;
    recording.preflightLoading = true;
    recording.preflightError = null;
    recording.actionError = null;
    if (teacherContract.error) {
      recording.preflightLoading = false;
      recording.preflightError = teacherContract.error;
      recording.actionError = teacherContract.error;
      this.emit();
      return null;
    }
    this.emit();

    try {
      const params = {
        check_video: checkVideo
      };
      applyTeacherSourceContract(params, teacherContract);
      if (force) {
        params._ = Date.now();
      }
      recording.preflight = await apiService.get(CSI_RECORD_ENDPOINTS.PREFLIGHT, params);
      recording.preflightError = null;
      return recording.preflight;
    } catch (error) {
      recording.preflightError = error.message;
      recording.actionError = error.message;
      return null;
    } finally {
      recording.preflightLoading = false;
      this.emit();
    }
  }

  async refreshRecordingStatus(force = false) {
    try {
      this.state.recording.status = await apiService.get(
        CSI_RECORD_ENDPOINTS.STATUS,
        force ? { _: Date.now() } : {}
      );
      const lastStopResultPayload = getRecordingLastStopResult(this.state.recording);
      const lastSessionSummaryPayload = getRecordingLastSessionSummary(this.state.recording);
      const freeformSummaryPayload = isFreeformSessionSummary(lastSessionSummaryPayload)
        ? lastSessionSummaryPayload
        : null;
      if (lastStopResultPayload) {
        this.state.recording.lastStopResult = normalizeRecordingStopResult(
          lastStopResultPayload,
          this.state.recording.status
        );
      }
      if (freeformSummaryPayload) {
        this.state.recording.freeform.lastSummary = {
          ...freeformSummaryPayload
        };
      }
      this.state.recording.activeMode = inferActiveRecordingMode(this.state.recording);
      const normalizedStopResult = normalizeRecordingStopResult(
        this.state.recording.lastStopResult,
        this.state.recording.status
      );
      this.state.recording.startupSignalGuard = normalizeStartupSignalGuard(
        this.state.recording.status?.startup_signal_guard,
        this.state.recording.status,
        normalizedStopResult
      );
      this.state.recording.stopFailure = normalizedStopResult?.deadOnStart
        ? {
            code: 'csi_dead_on_start',
            message: normalizedStopResult.message,
            stopReason: normalizedStopResult.stopReason
          }
        : null;
      if (normalizedStopResult?.deadOnStart) {
        this.state.recording.actionError = normalizedStopResult.message;
      }
      delete this.state.errors.recording;
    } catch (error) {
      this.state.errors.recording = error.message;
    } finally {
      this.emit();
    }
  }

  updateManualRecordingField(field, value) {
    const manual = this.state.recording.manual;
    if (!Object.prototype.hasOwnProperty.call(manual, field)) {
      return;
    }
    manual[field] = value;
    if (field === 'labelPresetId') {
      if (value === 'custom') {
        manual.labelVariantId = 'custom';
      } else {
        applyManualCapturePreset(manual, { resetVariant: true });
      }
    } else if (field === 'labelVariantId') {
      applyManualCapturePreset(manual, { resetVariant: false });
    }
    this.emit();
  }

  updateFreeformRecordingField(field, value) {
    const freeform = this.state.recording.freeform;
    if (!Object.prototype.hasOwnProperty.call(freeform, field)) {
      return;
    }
    freeform[field] = value;
    this.emit();
  }

  updateTeacherSourceField(field, value) {
    const teacherSource = this.state.recording.teacherSource;
    if (!Object.prototype.hasOwnProperty.call(teacherSource, field)) {
      return;
    }
    teacherSource[field] = field === 'selectedKind'
      ? normalizeTeacherSourceKind(value)
      : value;
    this.emit();
  }

  async stopActiveRecording() {
    const recording = this.state.recording;
    const activeMode = inferActiveRecordingMode(recording) || recording.activeMode;
    const shouldSpeakFreeformStop = activeMode === 'freeform' && recording.freeform?.voiceCue !== false;
    const result = await apiService.post(CSI_RECORD_ENDPOINTS.STOP, {});
    const normalizedStopResult = normalizeRecordingStopResult(result, this.state.recording.status);
    const deadOnStart = Boolean(normalizedStopResult?.deadOnStart);
    this.state.recording.status = {
      recording: false,
      preflight: this.state.recording.preflight,
      startup_signal_guard: this.state.recording.status?.startup_signal_guard || null
    };
    this.state.recording.activeMode = null;
    this.state.recording.lastStopResult = normalizedStopResult;
    this.state.recording.startupSignalGuard = normalizeStartupSignalGuard(
      this.state.recording.status.startup_signal_guard,
      this.state.recording.status,
      normalizedStopResult
    );
    this.state.recording.stopFailure = deadOnStart
      ? {
          code: 'csi_dead_on_start',
          message: normalizedStopResult.message,
          stopReason: normalizedStopResult.stopReason
        }
      : null;
    this.state.recording.actionError = deadOnStart ? normalizedStopResult.message : null;
    if (activeMode === 'freeform') {
      this.state.recording.freeform.lastSummary = buildFreeformStopSummary(normalizedStopResult, recording);
    }
    this.emit();
    if (deadOnStart) {
      void this.speakOperatorCue(normalizedStopResult.message || 'CSI сигнал не пошёл. Запись остановлена.');
    } else if (shouldSpeakFreeformStop) {
      void this.speakOperatorCue('Запись остановлена');
    }
    return normalizedStopResult;
  }

  async startManualRecording() {
    const recording = this.state.recording;
    const manual = recording.manual;
    const guidedStatus = recording.guided?.status || 'idle';
    const teacherContract = buildTeacherSourceContract(recording, {
      withVideo: Boolean(manual.withVideo),
      videoRequired: Boolean(manual.withVideo),
      allowLegacyNone: !manual.withVideo
    });
    const selectedPreset = getManualCapturePreset(manual.labelPresetId);
    const selectedVariant = getManualCapturePresetVariant(manual.labelPresetId, manual.labelVariantId);
    const generatedLabel = buildManualCaptureLabel(selectedPreset, selectedVariant);
    const generatedNotes = buildManualCaptureNotes(selectedPreset, selectedVariant);

    if (ACTIVE_GUIDED_STATUSES.includes(guidedStatus)) {
      recording.actionError = 'Сначала останови активный guided-пакет.';
      this.emit();
      return { ok: false, error: recording.actionError };
    }

    if (recording.status?.recording) {
      recording.actionError = 'Запись уже идёт. Сначала останови текущий run.';
      this.emit();
      return { ok: false, error: recording.actionError };
    }

    if (teacherContract.error) {
      recording.actionError = teacherContract.error;
      this.emit();
      return { ok: false, error: recording.actionError };
    }

    if (!manual.skipPreflight) {
      const preflight = await this.runRecordingPreflight({
        force: true,
        checkVideoOverride: Boolean(manual.withVideo)
      });
      if (!preflight?.ok) {
        recording.actionError = recording.preflightError || 'Предпроверка не пройдена.';
        this.emit();
        return { ok: false, error: recording.actionError };
      }
    }

    const label = String(manual.label || '').trim() || generatedLabel || makeManualRecordingLabel();
    const notes = String(manual.notes || '').trim() || generatedNotes || '';
    recording.actionError = null;
    this.emit();

    try {
      const request = {
        label,
        chunk_sec: Number(manual.chunkSec || 60),
        with_video: Boolean(manual.withVideo),
        person_count: Number(manual.personCount || 0),
        motion_type: manual.motionType || '',
        notes,
        voice_prompt: Boolean(manual.voicePrompt),
        skip_preflight: Boolean(manual.skipPreflight)
      };
      applyTeacherSourceContract(request, teacherContract);
      const payload = await apiService.post(CSI_RECORD_ENDPOINTS.START, request);
      recording.manual.label = label;
      recording.manual.notes = notes;
      recording.activeMode = 'manual';
      recording.lastStopResult = null;
      recording.stopFailure = null;
      recording.startupSignalGuard = null;
      await this.refreshRecordingStatus(true);
      return { ok: true, payload };
    } catch (error) {
      recording.actionError = error.message;
      this.emit();
      return { ok: false, error: error.message };
    }
  }

  async startFreeformRecording() {
    const recording = this.state.recording;
    const freeform = recording.freeform;
    const guidedStatus = recording.guided?.status || 'idle';
    const teacherContract = buildTeacherSourceContract(recording, {
      withVideo: true,
      videoRequired: true,
      allowLegacyNone: false
    });

    if (ACTIVE_GUIDED_STATUSES.includes(guidedStatus)) {
      recording.actionError = 'Сначала останови активный guided-пакет.';
      this.emit();
      return { ok: false, error: recording.actionError };
    }

    if (recording.status?.recording) {
      recording.actionError = 'Запись уже идёт. Сначала останови текущий run.';
      this.emit();
      return { ok: false, error: recording.actionError };
    }

    if (!freeform.personCount) {
      recording.actionError = 'Для freeform-режима сначала выбери количество людей.';
      this.emit();
      return { ok: false, error: recording.actionError };
    }

    if (teacherContract.error) {
      recording.actionError = teacherContract.error;
      this.emit();
      return { ok: false, error: recording.actionError };
    }

    const preflight = await this.runRecordingPreflight({
      force: true,
      checkVideoOverride: true
    });
    if (!preflight?.ok) {
      recording.actionError = recording.preflightError || 'Предпроверка не пройдена.';
      this.emit();
      return { ok: false, error: recording.actionError };
    }

    if (!preflight.video?.available) {
      recording.actionError = 'Freeform-режим требует обязательного видео, но предпроверка видео не пройдена.';
      this.emit();
      return { ok: false, error: recording.actionError };
    }

    const personCount = Math.max(1, Number(freeform.personCount) || 1);
    const label = String(freeform.label || '').trim() || makeFreeformRecordingLabel(personCount);
    const notes = buildFreeformNotes(freeform);
    recording.actionError = null;
    this.emit();

    try {
      const request = {
        label,
        chunk_sec: Number(freeform.chunkSec || 60),
        with_video: true,
        person_count: personCount,
        motion_type: 'freeform_single_person',
        notes,
        voice_prompt: false,
        skip_preflight: false
      };
      applyTeacherSourceContract(request, teacherContract);
      const payload = await apiService.post(CSI_RECORD_ENDPOINTS.START, request);
      recording.freeform.label = label;
      recording.freeform.notes = String(freeform.notes || '').trim();
      recording.freeform.lastSummary = null;
      recording.activeMode = 'freeform';
      recording.lastStopResult = null;
      recording.stopFailure = null;
      recording.startupSignalGuard = null;
      await this.refreshRecordingStatus(true);
      if (freeform.voiceCue !== false) {
        void this.speakOperatorCue('Запись началась');
      }
      return { ok: true, payload };
    } catch (error) {
      recording.actionError = error.message;
      this.emit();
      return { ok: false, error: error.message };
    }
  }

  async startGuidedCapturePack(packId, options = {}) {
    const pack = getGuidedCapturePack(packId || this.state.recording.selectedPackId);
    if (!pack) {
      this.state.recording.actionError = 'guided-пакет не найден.';
      this.emit();
      return { ok: false, error: this.state.recording.actionError };
    }

    const recording = this.state.recording;
    const currentGuided = recording.guided;
    if (ACTIVE_GUIDED_STATUSES.includes(currentGuided.status)) {
      recording.actionError = 'guided-запуск уже активен.';
      this.emit();
      return { ok: false, error: recording.actionError };
    }

    if (recording.status?.recording) {
      recording.actionError = 'Сейчас уже идёт запись. Сначала останови текущий run.';
      this.emit();
      return { ok: false, error: recording.actionError };
    }

    const preflight = await this.runRecordingPreflight({ packId: pack.id, force: true });
    if (!preflight?.ok) {
      recording.guided = {
        ...recording.guided,
        packId: pack.id,
        status: 'preflight_failed',
        completedAt: nowIso(),
        lastError: preflight?.error || recording.preflightError || 'Предпроверка не пройдена.',
        sequencePhase: null,
        countdownValue: null,
        currentStep: null,
        currentRecordingLabel: null,
        stepIndex: -1,
        stepStartedAt: null,
        stepEndsAt: null,
        pauseUntil: null
      };
      recording.actionError = recording.guided.lastError;
      this.emit();
      return { ok: false, error: recording.actionError };
    }

    this.clearGuidedTimers();
    const runToken = currentGuided.runToken + 1;
    recording.selectedPackId = pack.id;
    recording.actionError = null;
    recording.guided = {
      packId: pack.id,
      runToken,
      status: 'idle',
      sequencePhase: null,
      countdownValue: null,
      stepIndex: -1,
      stepStartedAt: null,
      stepEndsAt: null,
      pauseUntil: null,
      sessionPrefix: makeGuidedSessionPrefix(pack),
      currentStep: null,
      currentRecordingLabel: null,
      voiceEnabled: options.voiceEnabled ?? pack.voiceEnabledByDefault !== false,
      withVideo: options.withVideo ?? pack.withVideo !== false,
      logs: [],
      completedAt: null,
      lastError: null
    };
    this.emit();

    return this.runGuidedCaptureStep(pack.id, 0, runToken);
  }

  async runGuidedCaptureStep(packId, stepIndex, runToken) {
    const pack = getGuidedCapturePack(packId);
    const recording = this.state.recording;
    const guided = recording.guided;

    if (!pack || guided.runToken !== runToken) {
      return { ok: false, error: 'guided-пакет устарел.' };
    }

    const step = pack.steps[stepIndex];
    if (!step) {
      guided.status = 'completed';
      guided.completedAt = nowIso();
      guided.sequencePhase = null;
      guided.countdownValue = null;
      guided.currentStep = null;
      guided.currentRecordingLabel = null;
      guided.stepStartedAt = null;
      guided.stepEndsAt = null;
      guided.pauseUntil = null;
      this.emit();
      return { ok: true };
    }

    const recordingLabel = makeGuidedRecordingLabel(guided.sessionPrefix, stepIndex, step);
    const notes = [pack.notesPrefix, step.notes].filter(Boolean).join(', ');
    const teacherContract = buildTeacherSourceContract(recording, {
      withVideo: Boolean(guided.withVideo),
      videoRequired: Boolean(guided.withVideo),
      allowLegacyNone: !guided.withVideo
    });

    recording.actionError = null;
    if (teacherContract.error) {
      guided.status = 'error';
      guided.lastError = teacherContract.error;
      guided.completedAt = nowIso();
      this.emit();
      return { ok: false, error: teacherContract.error };
    }
    guided.status = 'cueing';
    guided.sequencePhase = 'prompt';
    guided.countdownValue = null;
    guided.stepIndex = stepIndex;
    guided.stepStartedAt = null;
    guided.stepEndsAt = null;
    guided.pauseUntil = null;
    guided.currentRecordingLabel = recordingLabel;
    guided.currentStep = {
      ...step,
      index: stepIndex,
      totalSteps: pack.steps.length
    };
    guided.logs = [
      ...guided.logs,
      {
        stepId: step.id,
        stepLabel: step.label,
        recordingLabel,
        status: 'cueing',
        startedAt: null,
        expectedDurationSec: step.durationSec,
        instruction: step.instruction
      }
    ];
    this.emit();

    try {
      const sequenceReady = await this.runGuidedStartSequence(pack, step, stepIndex, runToken);
      if (!sequenceReady || guided.runToken !== runToken) {
        return { ok: false, error: 'Guided start sequence interrupted.' };
      }

      const startedAt = nowIso();
      const request = {
        label: recordingLabel,
        chunk_sec: Number(step.durationSec || 30),
        with_video: guided.withVideo,
        person_count: Number(step.personCountExpected || pack.personCount || 1),
        motion_type: pack.motionType || '',
        notes,
        voice_prompt: false,
        skip_preflight: true
      };
      applyTeacherSourceContract(request, teacherContract);
      await apiService.post(CSI_RECORD_ENDPOINTS.START, request);
      guided.status = 'running';
      guided.sequencePhase = null;
      guided.countdownValue = null;
      guided.stepStartedAt = startedAt;
      guided.stepEndsAt = new Date(Date.now() + Number(step.durationSec || 0) * 1000).toISOString();
      await this.refreshRecordingStatus(true);
      guided.logs = updateGuidedLogEntry(guided.logs, recordingLabel, {
        status: 'running',
        startedAt
      });
      this.emit();
      this.guidedStepTimer = setTimeout(() => {
        void this.completeGuidedCaptureStep(pack.id, stepIndex, runToken);
      }, Number(step.durationSec || 0) * 1000);
      return { ok: true };
    } catch (error) {
      guided.status = 'error';
      guided.lastError = error.message;
      guided.completedAt = nowIso();
      guided.sequencePhase = null;
      guided.countdownValue = null;
      recording.actionError = error.message;
      guided.logs = updateGuidedLogEntry(guided.logs, recordingLabel, {
        status: 'error',
        finishedAt: nowIso(),
        error: error.message
      });
      this.emit();
      return { ok: false, error: error.message };
    }
  }

  async completeGuidedCaptureStep(packId, stepIndex, runToken) {
    const pack = getGuidedCapturePack(packId);
    const recording = this.state.recording;
    const guided = recording.guided;

    if (!pack || guided.runToken !== runToken) {
      return;
    }

    const step = pack.steps[stepIndex];
    const recordingLabel = guided.currentRecordingLabel || makeGuidedRecordingLabel(guided.sessionPrefix, stepIndex, step);

    guided.status = 'stopping';
    guided.sequencePhase = null;
    guided.countdownValue = null;
    this.emit();

    let stopResult = null;
    try {
      stopResult = await this.stopActiveRecording();
    } catch (error) {
      if (!/Not recording/i.test(error.message || '')) {
        guided.status = 'error';
        guided.lastError = error.message;
        guided.completedAt = nowIso();
        guided.sequencePhase = null;
        guided.countdownValue = null;
        recording.actionError = error.message;
        guided.logs = updateGuidedLogEntry(guided.logs, recordingLabel, {
          status: 'error',
          finishedAt: nowIso(),
          error: error.message
        });
        this.emit();
        return;
      }
    }

    guided.logs = updateGuidedLogEntry(guided.logs, recordingLabel, {
      status: 'completed',
      finishedAt: nowIso(),
      result: stopResult,
      lastChunkLabel: stopResult?.last_chunk?.label || null
    });

    const nextStepIndex = stepIndex + 1;
    if (nextStepIndex >= pack.steps.length) {
      guided.status = 'completed';
      guided.completedAt = nowIso();
      guided.currentStep = null;
      guided.currentRecordingLabel = null;
      guided.stepStartedAt = null;
      guided.stepEndsAt = null;
      guided.pauseUntil = null;
      this.emit();
      return;
    }

    const pauseBetweenStepsSec = Number(pack.pauseBetweenStepsSec || 0);
    guided.status = pauseBetweenStepsSec > 0 ? 'paused' : 'idle';
    guided.sequencePhase = null;
    guided.countdownValue = null;
    guided.stepIndex = stepIndex;
    guided.currentStep = null;
    guided.currentRecordingLabel = null;
    guided.stepStartedAt = null;
    guided.stepEndsAt = null;
    guided.pauseUntil = pauseBetweenStepsSec > 0
      ? new Date(Date.now() + pauseBetweenStepsSec * 1000).toISOString()
      : null;
    this.emit();

    if (pauseBetweenStepsSec > 0) {
      this.guidedPauseTimer = setTimeout(() => {
        void this.runGuidedCaptureStep(pack.id, nextStepIndex, runToken);
      }, pauseBetweenStepsSec * 1000);
      return;
    }

    void this.runGuidedCaptureStep(pack.id, nextStepIndex, runToken);
  }

  async stopGuidedCapturePack() {
    const recording = this.state.recording;
    const guided = recording.guided;
    if (!guided.packId) {
      return { ok: false, error: 'guided-запуск не активен.' };
    }

    this.clearGuidedTimers();
    const currentRunToken = guided.runToken;
    guided.runToken += 1;
    guided.status = 'stopping';
    guided.sequencePhase = null;
    guided.countdownValue = null;
    this.emit();

    let stopResult = null;
    try {
      if (recording.status?.recording || guided.currentRecordingLabel) {
        stopResult = await this.stopActiveRecording();
      }
    } catch (error) {
      if (!/Not recording/i.test(error.message || '')) {
        guided.status = 'error';
        guided.lastError = error.message;
        guided.completedAt = nowIso();
        recording.actionError = error.message;
        this.emit();
        return { ok: false, error: error.message };
      }
    }

    const cancelledRecordingLabel = guided.currentRecordingLabel;
    if (cancelledRecordingLabel) {
      guided.logs = updateGuidedLogEntry(guided.logs, cancelledRecordingLabel, {
        status: 'cancelled',
        finishedAt: nowIso(),
        result: stopResult,
        lastChunkLabel: stopResult?.last_chunk?.label || null
      });
    }

    guided.status = 'cancelled';
    guided.completedAt = nowIso();
    guided.sequencePhase = null;
    guided.countdownValue = null;
    guided.currentStep = null;
    guided.currentRecordingLabel = null;
    guided.stepStartedAt = null;
    guided.stepEndsAt = null;
    guided.pauseUntil = null;
    this.emit();
    return { ok: true, result: stopResult };
  }

  async refreshForensicRuns(force = false) {
    const forensics = this.state.forensics;
    if (forensics.loadingManifest && !force) {
      return;
    }

    forensics.loadingManifest = true;
    if (force) {
      forensics.manifestError = null;
    }
    this.emit();

    try {
      const query = force ? `?_=${Date.now()}` : '';
      const payload = await requestUiJson(`/api/agent7/forensics/runs${query}`);
      if (force) {
        this.resetForensicDetailCache();
      }
      forensics.manifest = Array.isArray(payload?.runs) ? payload.runs : [];
      forensics.manifestLoadedAt = payload?.generated_at || new Date().toISOString();
      forensics.manifestError = null;
      this.pruneForensicDetailCache(new Set(forensics.manifest.map((item) => item.run_id).filter(Boolean)));

      const selectedRunStillExists = forensics.selectedRunId
        && forensics.manifest.some((item) => item.run_id === forensics.selectedRunId);
      const nextRunId = selectedRunStillExists
        ? forensics.selectedRunId
        : (forensics.manifest[0]?.run_id || null);

      if (nextRunId && nextRunId !== forensics.selectedRunId) {
        forensics.selectedRunId = nextRunId;
        forensics.selectedRun = null;
        forensics.selectedRunLoadedAt = null;
      }

      if (nextRunId && (!forensics.selectedRun || force || nextRunId !== forensics.selectedRun?.run_id)) {
        await this.selectForensicRun(nextRunId, { force });
      }
    } catch (error) {
      forensics.manifestError = error.message;
    } finally {
      forensics.loadingManifest = false;
      this.emit();
    }
  }

  async selectForensicRun(runId, { force = false } = {}) {
    const forensics = this.state.forensics;

    if (!runId) {
      forensics.selectedRunId = null;
      forensics.selectedRun = null;
      forensics.selectedRunLoadedAt = null;
      forensics.selectedRunError = null;
      this.emit();
      return;
    }

    const sameRunAlreadyLoaded = forensics.selectedRun?.run_id === runId && !force;
    if (sameRunAlreadyLoaded) {
      forensics.selectedRunId = runId;
      this.emit();
      return;
    }

    const cachedEntry = !force ? this.getCachedForensicDetail(runId) : null;
    if (cachedEntry?.payload) {
      forensics.selectedRunId = runId;
      forensics.selectedRun = cachedEntry.payload;
      forensics.selectedRunLoadedAt = cachedEntry.loadedAt;
      forensics.selectedRunError = null;
      forensics.loadingRun = false;
      this.emit();
      return;
    }

    forensics.selectedRunId = runId;
    forensics.loadingRun = true;
    forensics.selectedRunError = null;
    this.emit();

    try {
      const payload = await this.fetchForensicRunDetail(runId, { force });
      forensics.selectedRun = payload;
      forensics.selectedRunLoadedAt = this.getCachedForensicDetail(runId)?.loadedAt || payload?.generated_at || new Date().toISOString();
      forensics.selectedRunError = null;
    } catch (error) {
      forensics.selectedRun = null;
      forensics.selectedRunLoadedAt = null;
      forensics.selectedRunError = error.message;
    } finally {
      forensics.loadingRun = false;
      this.emit();
    }
  }
}
