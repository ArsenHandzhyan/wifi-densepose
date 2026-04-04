import { TabManager } from './TabManager.js?v=20260326-stabilize-01';
import { AGENT7_OPERATOR_TRUTH } from '../data/agent7-truth.js?v=20260326-stabilize-01';
import { getOperatorCopy, localizeOperatorToken } from '../data/operator-copy.js?v=20260326-stabilize-01';
import { GUIDED_CAPTURE_PACKS, getGuidedCapturePack, getGuidedCapturePackSummary } from '../data/guided-capture-packs.js?v=20260403-truth-capture-02';
import { FEWSHOT_CALIBRATION_PROTOCOLS, getFewshotCalibrationProtocol } from '../data/fewshot-calibration-protocol.js?v=20260326-fewshot-ui-01';
import {
  MANUAL_CAPTURE_PRESETS,
  getManualCapturePreset,
  getManualCapturePresetVariant
} from '../data/manual-capture-presets.js?v=20260326-stabilize-01';
import { FP2Tab } from './FP2Tab.js?v=20260327-unified-01';
import { CsiOperatorService } from '../services/csi-operator.service.js?v=20260404-ui-runtime-20';

const UI_LOCALE = getOperatorCopy(typeof document !== 'undefined' ? document.documentElement?.lang : 'ru');
const TRUTH_TVAR_UI_THRESHOLD = 4.0;
const TRUTH_TVAR_UI_CONFIDENT_OCCUPIED = 6.0;
const TRUTH_TVAR_UI_CONFIDENT_EMPTY = 2.0;

function escapeHtml(value) {
  return String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;');
}

function formatNumber(value, digits = 0) {
  if (value == null || Number.isNaN(Number(value))) {
    return UI_LOCALE.common.noData;
  }
  return Number(value).toFixed(digits);
}

function safeNumber(value, fallback = null) {
  if (value == null || value === '') {
    return fallback;
  }
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
}

function toSortableTimestamp(value, fallback = -1) {
  const numeric = safeNumber(value, null);
  if (numeric != null) {
    return numeric;
  }
  const parsed = new Date(value).getTime();
  return Number.isFinite(parsed) ? parsed : fallback;
}

function sortRuntimeModelsByFreshness(items = []) {
  return [...items].sort((left, right) => {
    const rightUpdated = toSortableTimestamp(right?.updatedAt, -1);
    const leftUpdated = toSortableTimestamp(left?.updatedAt, -1);
    if (rightUpdated !== leftUpdated) {
      return rightUpdated - leftUpdated;
    }
    if (Boolean(right?.isActive) !== Boolean(left?.isActive)) {
      return right?.isActive ? 1 : -1;
    }
    if (Boolean(right?.isDefault) !== Boolean(left?.isDefault)) {
      return right?.isDefault ? 1 : -1;
    }
    return String(left?.displayName || left?.fileName || '')
      .localeCompare(String(right?.displayName || right?.fileName || ''), 'ru');
  });
}

function formatNumberWithUnit(value, { digits = 0, unit = '', missing = UI_LOCALE.common.noData } = {}) {
  if (value == null || Number.isNaN(Number(value))) {
    return missing;
  }
  return `${Number(value).toFixed(digits)}${unit}`;
}

function formatPercent(value, digits = 0) {
  if (value == null || Number.isNaN(Number(value))) {
    return 'не вычислено';
  }
  return `${(Number(value) * 100).toFixed(digits)}%`;
}

function formatRelativeTime(value) {
  if (value == null || Number.isNaN(Number(value))) {
    return 'время не передано';
  }
  const seconds = Number(value);
  if (seconds < 1) {
    return `${Math.round(seconds * 1000)} мс`;
  }
  if (seconds < 60) {
    return `${seconds.toFixed(1)} с`;
  }
  if (seconds < 3600) {
    return `${(seconds / 60).toFixed(1)} мин`;
  }
  return `${(seconds / 3600).toFixed(1)} ч`;
}

function formatDurationCompact(value) {
  if (value == null || Number.isNaN(Number(value))) {
    return 'длительность не передана';
  }
  const seconds = Math.max(0, Math.round(Number(value)));
  const minutes = Math.floor(seconds / 60);
  const remainSec = seconds % 60;
  if (!minutes) {
    return `${remainSec} с`;
  }
  if (!remainSec) {
    return `${minutes} мин`;
  }
  return `${minutes} мин ${remainSec} с`;
}

function formatTimestamp(value) {
  if (!value) {
    return 'время не передано';
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return 'время не передано';
  }
  return new Intl.DateTimeFormat('ru-RU', {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    day: '2-digit',
    month: '2-digit'
  }).format(date);
}

function formatCountdown(targetIso) {
  if (!targetIso) {
    return 'таймер не запущен';
  }
  const deltaMs = new Date(targetIso).getTime() - Date.now();
  if (!Number.isFinite(deltaMs)) {
    return 'таймер не запущен';
  }
  return formatDurationCompact(Math.max(0, Math.ceil(deltaMs / 1000)));
}

function formatList(items) {
  if (!items?.length) {
    return '<span class="muted">список не передан</span>';
  }
  return items.map((item) => `<span class="token">${escapeHtml(item)}</span>`).join('');
}

function humanizeToken(value) {
  if (value == null || value === '') {
    return UI_LOCALE.common.noData;
  }
  return String(value).replaceAll('_', ' ');
}

function displayToken(value) {
  if (value == null || value === '') {
    return UI_LOCALE.common.noData;
  }
  return localizeOperatorToken(value, UI_LOCALE.locale);
}

function displayMaybeToken(value) {
  if (value == null || value === '') {
    return UI_LOCALE.common.noData;
  }
  const raw = String(value);
  return Object.prototype.hasOwnProperty.call(UI_LOCALE.tokens || {}, raw)
    ? displayToken(raw)
    : raw;
}

function displayFewshotZone(value) {
  switch (String(value || '').trim()) {
    case 'door':
    case 'door_passage':
      return 'door_passage';
    case 'center':
      return 'center';
    case 'mixed':
      return 'transition';
    case 'deep':
      return 'deep';
    case '':
      return UI_LOCALE.common.noData;
    default:
      return String(value);
  }
}

function getShadowDisagreementLabel(shadowDisagreement) {
  if (!shadowDisagreement) {
    return UI_LOCALE.common.noData;
  }
  if (!shadowDisagreement.shadowLoaded) {
    return 'shadow не загружен';
  }
  return shadowDisagreement.binaryDisagreement ? 'есть расхождение' : 'совпадает';
}

function getDoorZoneWindowCount(zoneShadow) {
  return safeNumber(zoneShadow?.nCalWindows?.door, safeNumber(zoneShadow?.nCalWindows?.door_passage, 0)) || 0;
}

function buildDoorCenterCalibrationGate(zoneShadow, fewshot = {}) {
  const centerWindows = safeNumber(zoneShadow?.nCalWindows?.center, 0) || 0;
  const doorWindows = getDoorZoneWindowCount(zoneShadow);
  const zones = Array.isArray(zoneShadow?.zonesCalibrated) ? zoneShadow.zonesCalibrated : [];
  const hasCenter = zones.includes('center');
  const hasDoor = zones.includes('door') || zones.includes('door_passage');
  const ready = Boolean(zoneShadow?.calibrated && hasCenter && hasDoor);
  const fewshotStatus = String(fewshot?.status || 'idle');
  const rejectionReason = zoneShadow?.rejectionReason || fewshot?.fitResult?.error || fewshot?.lastError || null;
  const windowDetail = `center ${formatNumber(centerWindows, 0)} / door ${formatNumber(doorWindows, 0)}`;

  if (ready) {
    return {
      state: 'готово',
      detail: `${windowDetail} / quality ${zoneShadow?.calibrationQuality || 'unknown'}`,
      tone: 'ok'
    };
  }

  if (zoneShadow?.status === 'calibrating' || ['cueing', 'running', 'paused', 'stopping'].includes(fewshotStatus)) {
    return {
      state: 'калибруется',
      detail: `${windowDetail} / few-shot ${fewshotStatus}`,
      tone: 'warn'
    };
  }

  if (centerWindows + doorWindows === 0) {
    return {
      state: 'не готово',
      detail: `few-shot пустой: ${windowDetail}`,
      tone: 'risk'
    };
  }

  if (rejectionReason) {
    return {
      state: 'отклонено',
      detail: `${windowDetail} / ${rejectionReason}`,
      tone: 'risk'
    };
  }

  return {
    state: 'не готово',
    detail: `${windowDetail} / нужна рабочая калибровка door vs center`,
    tone: 'warn'
  };
}

function normalizeSearchValue(value) {
  return String(value ?? '')
    .toLowerCase()
    .replaceAll('_', ' ')
    .replaceAll('-', ' ');
}

function toneClass(tone) {
  switch (tone) {
    case 'risk':
      return 'tone-risk';
    case 'warn':
      return 'tone-warn';
    case 'ok':
      return 'tone-ok';
    case 'info':
      return 'tone-info';
    default:
      return 'tone-neutral';
  }
}

function statusTone(status) {
  if (['healthy', 'ok', 'ready', 'active_primary', 'active_reference'].includes(status)) {
    return 'ok';
  }
  if (['inactive', 'diagnostic_only', 'unknown'].includes(status)) {
    return 'warn';
  }
  if (['error', 'unhealthy', 'failed'].includes(status)) {
    return 'risk';
  }
  return 'info';
}

function classificationTone(status) {
  if (status === 'canonical_resolved_strong') {
    return 'ok';
  }
  if (status === 'failure_family_evidence') {
    return 'risk';
  }
  if (status === 'incomplete_artifact_bundle') {
    return 'warn';
  }
  return 'info';
}

function captureTone(status) {
  switch (status) {
    case 'completed':
      return 'ok';
    case 'cueing':
      return 'info';
    case 'running':
      return 'risk';
    case 'paused':
    case 'preflight_failed':
      return 'warn';
    case 'stopping':
      return 'info';
    case 'cancelled':
    case 'error':
      return 'risk';
    default:
      return 'neutral';
  }
}

function classificationBadgeLabel(status) {
  switch (status) {
    case 'canonical_resolved_strong':
      return UI_LOCALE.badges.canonical;
    case 'failure_family_evidence':
      return UI_LOCALE.badges.failure;
    case 'incomplete_artifact_bundle':
      return UI_LOCALE.badges.incomplete;
    default:
      return displayToken(status);
  }
}

function sensitivityBadgeLabel(status) {
  switch (status) {
    case 'robust':
      return UI_LOCALE.badges.robust;
    case 'contamination_sensitive':
      return UI_LOCALE.badges.timingBias;
    default:
      return displayToken(status);
  }
}

const FATE_GROUPS = [
  { id: 'all', label: UI_LOCALE.fateGroups.all, tone: 'neutral' },
  { id: 'canonical', label: UI_LOCALE.fateGroups.canonical, tone: 'ok' },
  { id: 'failure', label: UI_LOCALE.fateGroups.failure, tone: 'risk' },
  { id: 'incomplete', label: UI_LOCALE.fateGroups.incomplete, tone: 'warn' },
  { id: 'timing_bias', label: UI_LOCALE.fateGroups.timing_bias, tone: 'warn' }
];
const ACTIVE_GUIDED_STATUSES = ['cueing', 'running', 'paused', 'stopping'];
const ACTIVE_FEWSHOT_STATUSES = ['cueing', 'running', 'paused', 'stopping'];

const FATE_GROUP_HOTKEYS = {
  '1': 'all',
  '2': 'canonical',
  '3': 'failure',
  '4': 'incomplete',
  '5': 'timing_bias'
};
const FORENSIC_SEARCH_PREFETCH_DELAY_MS = 180;
const DEFAULT_GARAGE_LAYOUT = {
  // Garage Planner v3 (2026-03-28): 3×7m, door-sector + updated center/deep cut.
  // Backend center-based X: x ∈ [-1.5, +1.5]. Y: 0=door, 7=deep end.
  widthMeters: 3.0,
  heightMeters: 7.0,
  door: { xMeters: 1.0, yMeters: 0.0, widthMeters: 1.0, offsetMeters: 2.0 },
  zones: {
    doorMaxY: 2.0,
    deepMinY: 5.5,
    // Подзоны внутри door (center-based X: -1.5..+1.5)
    zone3: { xMin: 0.50, xMax: 1.50, yMin: 0.0, yMax: 3.0, label: 'Проход' },
    zone4: { xMin: -0.50, xMax: 0.50, yMin: 0.0, yMax: 1.0, label: 'FP2' }
  },
  nodes: [
    { nodeId: 'node01', ip: '192.168.0.137', xMeters: -1.50, yMeters: 0.55, zone: 'door' },
    { nodeId: 'node02', ip: '192.168.0.117', xMeters: 1.50, yMeters: 0.55, zone: 'door' },
    { nodeId: 'node03', ip: '192.168.0.144', xMeters: -1.50, yMeters: 3.15, zone: 'center' },
    { nodeId: 'node04', ip: '192.168.0.125', xMeters: 1.50, yMeters: 2.50, zone: 'door' },
    { nodeId: 'node05', ip: '192.168.0.110',  xMeters: 0.00, yMeters: 3.50, zone: 'center' },
    { nodeId: 'node06', ip: '192.168.0.132',  xMeters: -1.50, yMeters: 4.35, zone: 'center' },
    { nodeId: 'node07', ip: '192.168.0.153',  xMeters: 1.50, yMeters: 3.70, zone: 'center' }
  ]
};
const DEFAULT_VISIBLE_NODE_COUNT = Math.max(DEFAULT_GARAGE_LAYOUT.nodes.length, 7);
const TEACHER_SOURCE_KIND = {
  PIXEL_RTSP: 'pixel_rtsp',
  MAC_CAMERA: 'mac_camera',
  NONE: 'none'
};
const DEFAULT_PIXEL_RTSP_URL = 'rtsp://admin:admin@192.168.1.148:8554/live';
const DEFAULT_PIXEL_RTSP_NAME = 'Pixel 8 Pro';
const UI_RUNTIME_VIEW_STORAGE_KEY = 'agent7.csiOperator.runtimeView';
const UI_RUNTIME_VIEW_OPTIONS = {
  TRACK_A: 'track_a',
  TRACK_B: 'track_b',
  V15: 'v15',
  V27_7NODE: 'v27_7node',
  GARAGE_V2: 'garage_v2'
};

function readUiRuntimeViewSelection() {
  try {
    const raw = window.localStorage?.getItem(UI_RUNTIME_VIEW_STORAGE_KEY);
    if (raw === UI_RUNTIME_VIEW_OPTIONS.TRACK_B) {
      return UI_RUNTIME_VIEW_OPTIONS.TRACK_B;
    }
    if (raw === UI_RUNTIME_VIEW_OPTIONS.V15) {
      return UI_RUNTIME_VIEW_OPTIONS.V15;
    }
    if (raw === UI_RUNTIME_VIEW_OPTIONS.V27_7NODE) {
      return UI_RUNTIME_VIEW_OPTIONS.V27_7NODE;
    }
    if (raw === UI_RUNTIME_VIEW_OPTIONS.GARAGE_V2) {
      return UI_RUNTIME_VIEW_OPTIONS.GARAGE_V2;
    }
    return UI_RUNTIME_VIEW_OPTIONS.TRACK_A;
  } catch (_error) {
    return UI_RUNTIME_VIEW_OPTIONS.TRACK_A;
  }
}

function writeUiRuntimeViewSelection(value) {
  try {
    window.localStorage?.setItem(UI_RUNTIME_VIEW_STORAGE_KEY, value);
  } catch (_error) {
    // UI selector is best-effort; localStorage is optional.
  }
}

function getTrackBShadowConfidence(trackBShadow) {
  const candidates = [
    Number(trackBShadow?.emptyProbability),
    Number(trackBShadow?.staticProbability),
    Number(trackBShadow?.motionProbability)
  ].filter((value) => Number.isFinite(value));
  return candidates.length ? Math.max(...candidates) : null;
}

function getShadowConfidence(shadow) {
  const candidates = [
    Number(shadow?.emptyProbability),
    Number(shadow?.staticProbability),
    Number(shadow?.motionProbability)
  ].filter((value) => Number.isFinite(value));
  return candidates.length ? Math.max(...candidates) : null;
}

function getGarageRatioV2Confidence(shadow) {
  const candidates = [
    Number(shadow?.doorProbability),
    Number(shadow?.centerProbability),
    Number(shadow?.deepProbability)
  ].filter((value) => Number.isFinite(value));
  return candidates.length ? Math.max(...candidates) : null;
}

function getV27Binary7NodeConfidence(shadow) {
  const candidates = [
    Number(shadow?.emptyProbability),
    Number(shadow?.occupiedProbability)
  ].filter((value) => Number.isFinite(value));
  return candidates.length ? Math.max(...candidates) : null;
}

function buildRuntimeView(primaryRuntime, trackBShadow, v15Shadow, v27Binary7NodeShadow, garageRatioV2Shadow, selectedView) {
  if (selectedView === UI_RUNTIME_VIEW_OPTIONS.TRACK_B) {
    const headline = trackBShadow?.predictedClass || trackBShadow?.status || 'unknown';
    return {
      id: UI_RUNTIME_VIEW_OPTIONS.TRACK_B,
      label: 'Track B v1 кандидат',
      routeLabel: 'только shadow',
      state: headline,
      confidence: getTrackBShadowConfidence(trackBShadow),
      modelVersion: 'track_b_v1',
      modelId: 'tcn_v2_track_b_v1_torchscript.pt',
      running: Boolean(trackBShadow?.loaded),
      modelLoaded: Boolean(trackBShadow?.loaded),
      nodesActive: Number(trackBShadow?.nodesWithData) || 0,
      totalNodes: Number(primaryRuntime?.totalNodes) || DEFAULT_VISIBLE_NODE_COUNT,
      packetsInWindow: primaryRuntime?.packetsInWindow,
      packetsPerSecond: primaryRuntime?.packetsPerSecond,
      windowAgeSec: primaryRuntime?.windowAgeSec,
      targetZone: trackBShadow?.predictedClass || 'unknown',
      targetX: null,
      targetY: null,
      inferenceMs: trackBShadow?.inferenceMs,
      summary: 'UI показывает Track B как тестовый режим отображения; боевой маршрут остаётся на Track A.'
    };
  }

  if (selectedView === UI_RUNTIME_VIEW_OPTIONS.V15) {
    const headline = v15Shadow?.predictedClass || v15Shadow?.status || 'unknown';
    return {
      id: UI_RUNTIME_VIEW_OPTIONS.V15,
      label: 'V8 F2-spectral canonical кандидат',
      routeLabel: 'только shadow',
      state: headline,
      confidence: getShadowConfidence(v15Shadow),
      modelVersion: 'v8_f2spectral_canonical',
      modelId: 'v8_f2spectral_canonical_candidate.pkl',
      running: Boolean(v15Shadow?.loaded),
      modelLoaded: Boolean(v15Shadow?.loaded),
      nodesActive: primaryRuntime?.nodesActive,
      totalNodes: Number(primaryRuntime?.totalNodes) || DEFAULT_VISIBLE_NODE_COUNT,
      packetsInWindow: primaryRuntime?.packetsInWindow,
      packetsPerSecond: primaryRuntime?.packetsPerSecond,
      windowAgeSec: primaryRuntime?.windowAgeSec,
      targetZone: v15Shadow?.predictedClass || 'unknown',
      targetX: null,
      targetY: null,
      inferenceMs: v15Shadow?.inferenceMs,
      bufferDepth: v15Shadow?.bufferDepth,
      warmupRemaining: v15Shadow?.warmupRemaining,
      summary: 'UI показывает V8 как shadow‑кандидат только для теста, буфер 7 окон; боевой маршрут остаётся на Track A.'
    };
  }

  if (selectedView === UI_RUNTIME_VIEW_OPTIONS.V27_7NODE) {
    const headline = v27Binary7NodeShadow?.binary || v27Binary7NodeShadow?.status || 'unknown';
    const candidateName = v27Binary7NodeShadow?.candidateName || v27Binary7NodeShadow?.track || '7-node binary candidate';
    return {
      id: UI_RUNTIME_VIEW_OPTIONS.V27_7NODE,
      label: `${candidateName} / binary кандидат`,
      routeLabel: 'тестовый UI',
      state: headline,
      confidence: getV27Binary7NodeConfidence(v27Binary7NodeShadow),
      modelVersion: v27Binary7NodeShadow?.track || candidateName,
      modelId: candidateName,
      running: Boolean(v27Binary7NodeShadow?.loaded),
      modelLoaded: Boolean(v27Binary7NodeShadow?.loaded),
      nodesActive: primaryRuntime?.nodesActive,
      totalNodes: Number(primaryRuntime?.totalNodes) || DEFAULT_VISIBLE_NODE_COUNT,
      packetsInWindow: primaryRuntime?.packetsInWindow,
      packetsPerSecond: primaryRuntime?.packetsPerSecond,
      windowAgeSec: primaryRuntime?.windowAgeSec,
      targetZone: v27Binary7NodeShadow?.binary || 'unknown',
      targetX: null,
      targetY: null,
      inferenceMs: v27Binary7NodeShadow?.inferenceMs,
      threshold: v27Binary7NodeShadow?.threshold,
      summary: 'UI показывает текущего 7-node binary кандидата из архивного payload v26_shadow; селектор меняет только представление, состояние backend не трогает.'
    };
  }

  if (selectedView === UI_RUNTIME_VIEW_OPTIONS.GARAGE_V2) {
    const headline = garageRatioV2Shadow?.predictedZone || garageRatioV2Shadow?.status || 'unknown';
    return {
      id: UI_RUNTIME_VIEW_OPTIONS.GARAGE_V2,
      label: 'Garage Ratio V3 кандидат',
      routeLabel: 'только shadow',
      state: headline,
      confidence: getGarageRatioV2Confidence(garageRatioV2Shadow),
      modelVersion: garageRatioV2Shadow?.candidateName || 'GARAGE_RATIO_LAYER_V3_CANDIDATE',
      modelId: 'garage_ratio_layer_v3_candidate.pkl',
      running: Boolean(garageRatioV2Shadow?.loaded),
      modelLoaded: Boolean(garageRatioV2Shadow?.loaded),
      nodesActive: Number(garageRatioV2Shadow?.activeNodes || garageRatioV2Shadow?.nodesWithRatio) || 0,
      totalNodes: Number(primaryRuntime?.totalNodes) || DEFAULT_VISIBLE_NODE_COUNT,
      packetsInWindow: garageRatioV2Shadow?.packetsInWindow ?? primaryRuntime?.packetsInWindow,
      packetsPerSecond: primaryRuntime?.packetsPerSecond,
      windowAgeSec: primaryRuntime?.windowAgeSec,
      targetZone: garageRatioV2Shadow?.targetZone || 'unknown',
      targetX: null,
      targetY: null,
      inferenceMs: garageRatioV2Shadow?.inferenceMs,
      summary: 'UI показывает гаражный V3 ratio‑layer как shadow‑кандидат; боевой маршрут остаётся на Track A.'
    };
  }

  // When production binary is confidently empty, show "empty" as primary state
  const trackAState = (primaryRuntime?.binary === 'empty' && (primaryRuntime?.binaryConfidence || 0) > 0.75)
    ? 'empty'
    : primaryRuntime?.state || 'unknown';

  return {
    id: UI_RUNTIME_VIEW_OPTIONS.TRACK_A,
    label: 'Track A боевой',
    routeLabel: 'боевой',
    state: trackAState,
    confidence: primaryRuntime?.confidence,
    modelVersion: primaryRuntime?.modelVersion,
    modelId: primaryRuntime?.modelId,
    running: Boolean(primaryRuntime?.running),
    modelLoaded: Boolean(primaryRuntime?.modelLoaded),
    nodesActive: primaryRuntime?.nodesActive,
    totalNodes: Number(primaryRuntime?.totalNodes) || DEFAULT_VISIBLE_NODE_COUNT,
    packetsInWindow: primaryRuntime?.packetsInWindow,
    packetsPerSecond: primaryRuntime?.packetsPerSecond,
    windowAgeSec: primaryRuntime?.windowAgeSec,
    targetZone: primaryRuntime?.targetZone,
    targetX: primaryRuntime?.targetX,
    targetY: primaryRuntime?.targetY,
    inferenceMs: null,
    summary: 'UI показывает текущий боевой runtime Track A.'
  };
}
const DEFAULT_MAC_CAMERA_DEVICE = '0';
const DEFAULT_MAC_CAMERA_DEVICE_NAME = 'Mac Camera (device 0)';

function fateGroupLabel(groupId) {
  return FATE_GROUPS.find((item) => item.id === groupId)?.label || displayToken(groupId);
}

function fateGroupTone(groupId) {
  return FATE_GROUPS.find((item) => item.id === groupId)?.tone || 'neutral';
}

function isTextEditingTarget(target) {
  if (!(target instanceof HTMLElement)) {
    return false;
  }
  if (target.isContentEditable) {
    return true;
  }
  const editable = target.closest('input, textarea, select, [contenteditable="true"]');
  return Boolean(editable);
}

function formatBoolean(value) {
  if (value == null) {
    return UI_LOCALE.common.noData;
  }
  return value ? UI_LOCALE.common.yes : UI_LOCALE.common.no;
}

function firstDefinedValue(...values) {
  for (const value of values) {
    if (value != null && !Number.isNaN(Number(value))) {
      return value;
    }
  }
  return null;
}

function clamp(value, min, max) {
  return Math.min(max, Math.max(min, value));
}

function isSupportPathMissing(support) {
  return !support || !support.candidateName || support.candidateName === 'unavailable';
}

function hasPerNodeTelemetry(nodes = []) {
  return nodes.some((node) => !node?.aggregateOnly && (node.active || (Number(node.packets) || 0) > 0));
}

function getAggregateNodeNote(nodes, primaryRuntime) {
  const activeNodes = Number(primaryRuntime?.nodesActive) || 0;
  if (hasPerNodeTelemetry(nodes) || activeNodes <= 0) {
    return null;
  }
  const totalNodes = Math.max(Number(primaryRuntime?.totalNodes) || 0, nodes.length || 0, DEFAULT_VISIBLE_NODE_COUNT, activeNodes);
  return `Runtime видит ${activeNodes}/${totalNodes} источника, но по пакетам доступен только сводный уровень.`;
}

function getNodeValueText(node) {
  if (node?.packetShare != null) {
    return formatPercent(node.packetShare, 1);
  }
  if (node?.aggregateOnly && node?.active) {
    return UI_LOCALE.common.live;
  }
  return UI_LOCALE.common.noData;
}

function getNodeMetaText(node) {
  if (node?.aggregateOnly && node?.active) {
    return 'по пакетам только сводный уровень';
  }
  if (node?.active == null) {
    return 'нет детализации по узлам';
  }
  return `${node?.required ? UI_LOCALE.common.required : UI_LOCALE.common.auxiliary} / ${node?.active ? UI_LOCALE.common.live : 'не в эфире'}`;
}

function getNodeSignalScopeText(node) {
  if (node?.aggregateOnly) {
    return 'только сводный сигнал';
  }
  return node?.required ? UI_LOCALE.common.required : UI_LOCALE.common.optional;
}

function getNodePacketText(node) {
  if (node?.packets != null) {
    return formatNumber(node.packets);
  }
  if (node?.aggregateOnly) {
    return 'сводно';
  }
  return UI_LOCALE.common.noData;
}

function getNodeShareText(node) {
  if (node?.packetShare != null) {
    return formatPercent(node.packetShare, 1);
  }
  if (node?.aggregateOnly) {
    return 'сводно';
  }
  return UI_LOCALE.common.noData;
}

function getTopologyHeadline(topology, primaryRuntime) {
  const sourceCount = Number(topology?.sourceCount) || Number(primaryRuntime?.nodesActive) || 0;
  const signature = topology?.signature;
  if (sourceCount > 0 && (!signature || signature === 'unknown' || signature === 'unavailable')) {
    return `${sourceCount} активных источника`;
  }
  const aggregateNote = getAggregateNodeNote(topology?.nodes || [], primaryRuntime);
  if (aggregateNote && sourceCount > 0) {
    return `${sourceCount} активных источника`;
  }
  return signature || UI_LOCALE.common.unknown;
}

function formatLiveEventDetail(detail) {
  if (!detail) {
    return '';
  }
  return String(detail)
    .split(' / ')
    .map((part) => {
      const trimmed = part.trim();
      if (trimmed.startsWith('зона ')) {
        return `зона ${displayToken(trimmed.slice(5))}`;
      }
      if (trimmed.startsWith('zone ')) {
        return `зона ${displayToken(trimmed.slice(5))}`;
      }
      return trimmed;
    })
    .join(' / ');
}

function getSupportStatusText(support) {
  if (!support) {
      return 'support‑path не прислал статус';
  }
  if ((support.status === 'unknown' || !support.status) && isSupportPathMissing(support)) {
    return 'без live-данных';
  }
  return displayToken(support.status || 'unknown');
}

function getSupportHeadline(support) {
  if (!support) {
    return 'support‑path не прислал данные';
  }
  if (isSupportPathMissing(support)) {
    return 'support‑path не получен';
  }
  return displayMaybeToken(support.candidateName);
}

function getSupportReasonText(support) {
  if (!support) {
    return 'support‑path не прислал причину';
  }
  if ((support.reason === 'unknown' || !support.reason) && isSupportPathMissing(support)) {
    return 'pose payload не прислал support_observations';
  }
  return displayToken(support.reason || 'unknown');
}

function getRecordingLabelText(recordingStatus, fallback = null) {
  if (recordingStatus?.label) {
    return recordingStatus.label;
  }
  if (fallback) {
    return fallback;
  }
  if (recordingStatus?.recording) {
    return 'метка не пришла';
  }
  return 'запись без метки';
}

function getLastChunkText(recordingStatus, { duringRecording = 'текущий фрагмент ещё не закрыт', whenIdle = 'последний фрагмент пока не зафиксирован' } = {}) {
  if (recordingStatus?.last_chunk?.label) {
    return recordingStatus.last_chunk.label;
  }
  if (recordingStatus?.recording) {
    return duringRecording;
  }
  return whenIdle;
}

function getStartupSignalGuard(recording) {
  const status = recording?.status || {};
  const fallbackGuard = status?.startup_signal_guard || {};
  const guard = recording?.startupSignalGuard || fallbackGuard;
  const lastStopResult = recording?.lastStopResult || {};
  const stopReason = guard?.stopReason || guard?.stop_reason || lastStopResult?.stopReason || lastStopResult?.stop_reason || null;
  const deadOnStart = Boolean(
    guard?.verdict === 'csi_dead_on_start'
    || guard?.failed
    || guard?.status === 'failed'
    || stopReason === 'csi_dead_on_start'
    || recording?.stopFailure?.code === 'csi_dead_on_start'
  );
  const passed = Boolean(guard?.passed || guard?.status === 'passed');
  const thresholds = guard?.thresholds || {
    graceSec: 6,
    minActiveCoreNodes: 3,
    minPackets: 20,
    minPps: 5
  };
  const metrics = guard?.metrics || {
    activeCoreNodes: status?.nodes_active ?? null,
    packets: status?.chunk_packets ?? null,
    pps: status?.chunk_pps ?? null,
    elapsedSec: status?.elapsed_sec ?? null,
    windowAgeSec: status?.window_age_sec ?? null
  };

  return {
    label: guard?.label || 'startup_signal_guard',
    passed,
    deadOnStart,
    stopReason,
    status: guard?.status || (deadOnStart ? 'failed' : (passed ? 'passed' : 'unknown')),
    verdict: guard?.verdict || (deadOnStart ? 'csi_dead_on_start' : (passed ? 'passed' : 'pending')),
    reason: guard?.reason || guard?.note || (deadOnStart
      ? 'CSI сигнал не пошёл. Запись остановлена.'
      : passed
    ? 'проверка старта пройдена'
    : 'проверка старта в ожидании'),
    thresholds,
    metrics,
    note: guard?.note || (deadOnStart ? 'Автостоп по startup_signal_guard' : 'проверка старта в ожидании'),
    raw: guard
  };
}

function getStartupSignalGuardTone(guard) {
  if (!guard) {
    return 'neutral';
  }
  if (guard.deadOnStart || guard.verdict === 'csi_dead_on_start') {
    return 'risk';
  }
  if (guard.passed) {
    return 'ok';
  }
  return 'warn';
}

function getStartupSignalGuardLabel(guard) {
  if (!guard) {
    return 'startup_signal_guard: нет данных';
  }
  if (guard.deadOnStart || guard.verdict === 'csi_dead_on_start') {
    return 'startup_signal_guard: csi_dead_on_start';
  }
  if (guard.passed) {
    return 'startup_signal_guard: пройдена';
  }
  return `startup_signal_guard: ${displayToken(guard.status || 'unknown')}`;
}

function getRecordingStopResult(recording) {
  const stopResult = recording?.lastStopResult || null;
  if (!stopResult) {
    return null;
  }
  return {
    ...stopResult,
    deadOnStart: Boolean(stopResult.deadOnStart || stopResult.stopReason === 'csi_dead_on_start'),
    stopReason: stopResult.stopReason || stopResult.stop_reason || stopResult.reason || null,
    message: stopResult.message || (stopResult.stopReason === 'csi_dead_on_start'
      ? 'CSI сигнал не пошёл. Запись остановлена.'
      : 'Запись остановлена.')
  };
}

function getGuidedLastChunkText(guided, recordingStatus) {
  const lastChunkLabel = guided?.logs?.at(-1)?.lastChunkLabel;
  if (lastChunkLabel) {
    return lastChunkLabel;
  }
  if (recordingStatus?.recording) {
    return 'фрагмент текущего шага ещё не закрыт';
  }
  return 'guided-пакет пока не зафиксировал последний фрагмент';
}

function getRecordingMode(recording) {
  const guidedStatus = recording?.guided?.status || 'idle';
  if (isGuidedActiveStatus(guidedStatus)) {
    return 'guided';
  }
  const activeMode = recording?.activeMode;
  if (activeMode === 'freeform' || activeMode === 'manual') {
    return activeMode;
  }
  const status = recording?.status;
  if (status?.recording && status?.motion_type === 'free_motion' && status?.with_video) {
    return 'freeform';
  }
  if (status?.recording) {
    return 'manual';
  }
  return null;
}

function getActiveNodeCount(recordingStatus) {
  const nodePackets = recordingStatus?.node_packets || {};
  return Object.values(nodePackets).filter((value) => Number(value) > 0).length;
}

function getChunkCountText(recordingStatus) {
  if (recordingStatus?.recording) {
    return `текущий ${formatNumber(recordingStatus.chunk_num)} / сохранено ${formatNumber(recordingStatus.total_chunks)}`;
  }
  if (recordingStatus?.last_chunk?.label) {
    return recordingStatus.last_chunk.label;
  }
  return 'фрагменты ещё не зафиксированы';
}

function getFreeformRoleHintText(personCount) {
  return Number(personCount) > 1
    ? UI_LOCALE.capture.freeformRoleHintMulti
    : UI_LOCALE.capture.freeformRoleHintSingle;
}

function buildLocalFileHref(path) {
  if (!path) {
    return null;
  }
  const normalizedPath = String(path).trim();
  if (!normalizedPath.startsWith('/')) {
    return null;
  }
  return `file://${encodeURI(normalizedPath)}`;
}

function isGuidedActiveStatus(status) {
  return ACTIVE_GUIDED_STATUSES.includes(status);
}

function getPreflightNodeEntries(preflight) {
  return Array.isArray(preflight?.nodes)
    ? preflight.nodes
    : Object.entries(preflight?.nodes || {}).map(([name, item]) => ({
        name,
        ...(item || {})
      }));
}

function normalizeTeacherSourceKind(value) {
  const raw = String(value || '').trim();
  if (!raw) {
    return TEACHER_SOURCE_KIND.PIXEL_RTSP;
  }
  if (raw === 'phone_rtsp' || raw === 'rtsp_teacher') {
    return TEACHER_SOURCE_KIND.PIXEL_RTSP;
  }
  if (raw === 'mac_camera_terminal') {
    return TEACHER_SOURCE_KIND.MAC_CAMERA;
  }
  if (Object.values(TEACHER_SOURCE_KIND).includes(raw)) {
    return raw;
  }
  return raw;
}

function getTeacherSourceSelection(recording) {
  const teacherSource = recording?.teacherSource || {};
  const selectedKind = normalizeTeacherSourceKind(teacherSource.selectedKind);
  return {
    selectedKind,
    pixelRtspUrl: String(teacherSource.pixelRtspUrl || DEFAULT_PIXEL_RTSP_URL).trim() || DEFAULT_PIXEL_RTSP_URL,
    pixelRtspName: String(teacherSource.pixelRtspName || DEFAULT_PIXEL_RTSP_NAME).trim() || DEFAULT_PIXEL_RTSP_NAME,
    macDevice: String(teacherSource.macDevice || DEFAULT_MAC_CAMERA_DEVICE).trim() || DEFAULT_MAC_CAMERA_DEVICE,
    macDeviceName: String(teacherSource.macDeviceName || DEFAULT_MAC_CAMERA_DEVICE_NAME).trim() || DEFAULT_MAC_CAMERA_DEVICE_NAME
  };
}

function getTeacherSourceKindLabel(kind) {
  switch (normalizeTeacherSourceKind(kind)) {
    case TEACHER_SOURCE_KIND.PIXEL_RTSP:
      return 'Pixel RTSP';
    case TEACHER_SOURCE_KIND.MAC_CAMERA:
    return 'Камера Mac';
    case TEACHER_SOURCE_KIND.NONE:
      return 'нет (архивный/деградированный)';
    default:
      return humanizeToken(kind);
  }
}

function getTeacherSourceSelectionDetail(selection) {
  switch (normalizeTeacherSourceKind(selection?.selectedKind)) {
    case TEACHER_SOURCE_KIND.PIXEL_RTSP:
      return `${selection.pixelRtspName || DEFAULT_PIXEL_RTSP_NAME} · ${selection.pixelRtspUrl || DEFAULT_PIXEL_RTSP_URL}`;
    case TEACHER_SOURCE_KIND.MAC_CAMERA:
      return `${selection.macDeviceName || DEFAULT_MAC_CAMERA_DEVICE_NAME} · device=${selection.macDevice || DEFAULT_MAC_CAMERA_DEVICE}`;
    case TEACHER_SOURCE_KIND.NONE:
      return 'Архивный путь без teacher‑видео.';
    default:
      return UI_LOCALE.common.noData;
  }
}

function getCanonicalRecordingState(snapshot) {
  const recording = snapshot?.recording || {};
  const preflight = recording.preflight || {};
  const freeform = recording.freeform || {};
  const status = recording.status || {};
  const support = snapshot?.live?.supportPath || {};
  const trust = snapshot?.live?.trust || {};
  const topology = snapshot?.live?.topology || {};
  const recordingMode = getRecordingMode(recording);
  const guidedActive = recordingMode === 'guided';
  const manualActive = recordingMode === 'manual';
  const freeformActive = recordingMode === 'freeform';
  const legacyFreeformActive = Boolean(status.recording && status.motion_type === 'free_motion' && !status.with_video);
  const nodeEntries = getPreflightNodeEntries(preflight);
  const readyNodes = nodeEntries.filter((item) => item?.ok).length;
  const totalNodes = Math.max(nodeEntries.length, 4);
  const videoChecked = Boolean(preflight.video?.checked);
  const videoAvailable = videoChecked ? Boolean(preflight.video?.available) : false;
  const videoError = preflight.video?.error || null;
  const liveSourceCount = Number(topology.sourceCount) || 0;
  const truthInvalidationReason = support.invalidationReason || support.invalidation_reason || support.reason || null;
  const voiceEnabled = freeform.voiceCue !== false;
  const personCount = Math.max(1, Number(freeform.personCount) || 1);
  const teacherSelection = getTeacherSourceSelection(recording);
  const preflightTeacher = preflight.teacher || {};
  const selectedTeacherKind = normalizeTeacherSourceKind(teacherSelection.selectedKind);
  const preflightTeacherKind = preflightTeacher.source_kind
    ? normalizeTeacherSourceKind(preflightTeacher.source_kind)
    : '';
  const activeTeacherKind = status.teacher_source_kind
    ? normalizeTeacherSourceKind(status.teacher_source_kind)
    : '';
  const resolvedTeacherKind = status.recording
    ? activeTeacherKind
    : preflightTeacherKind || selectedTeacherKind;
  const teacherDetail = status.recording
    ? (
        status.teacher_source_url_redacted
        || status.teacher_device_name
        || getTeacherSourceSelectionDetail(teacherSelection)
      )
    : (
        preflightTeacher.source_url_redacted
        || preflightTeacher.device_name
        || getTeacherSourceSelectionDetail(teacherSelection)
      );
  const teacherSelectionLabel = getTeacherSourceKindLabel(selectedTeacherKind);
  const teacherResolvedLabel = getTeacherSourceKindLabel(resolvedTeacherKind || selectedTeacherKind);
  const teacher = {
    selected: selectedTeacherKind !== TEACHER_SOURCE_KIND.NONE,
    selectedKind: selectedTeacherKind,
    selectionLabel: teacherSelectionLabel,
    label: teacherResolvedLabel,
    detail: teacherDetail,
    required: true,
    stateLabel: selectedTeacherKind === TEACHER_SOURCE_KIND.NONE
      ? 'legacy_selected'
      : videoChecked ? (videoAvailable ? 'available' : 'unavailable') : 'not_checked',
    tone: selectedTeacherKind === TEACHER_SOURCE_KIND.NONE
      ? 'risk'
      : videoChecked ? (videoAvailable ? 'ok' : 'risk') : 'warn',
    reason: selectedTeacherKind === TEACHER_SOURCE_KIND.NONE
      ? 'Выбран архивный источник none. Канонический freeform не стартует с teacher_source_kind=none.'
      : videoChecked
        ? (videoAvailable
            ? `Предпроверка подтвердила ${teacherResolvedLabel} как явный источник teacher.`
            : (videoError || `Предпроверка не подтвердила ${teacherResolvedLabel}.`))
        : `Источник teacher выбран явно (${teacherSelectionLabel}), но ещё не проверен предпроверкой.`
  };

  let truth = {
    label: 'ожидает предпроверку',
    tone: 'warn',
    summary: 'Слой truth ещё не подтверждён: сначала нужна предпроверка с видео.'
  };

  const activeVideoBackedSession = Boolean(status.recording && status.with_video);
  const activeTruthTrackedSession = freeformActive || activeVideoBackedSession;

  if ((manualActive && !status.with_video) || legacyFreeformActive) {
    truth = {
      label: 'архив без teacher-видео',
      tone: 'risk',
      summary: legacyFreeformActive
        ? 'Идёт архивный freeform без teacher-видео. Это не каноническая teacher‑запись.'
        : 'Идёт архивная сессия без teacher-видео. Это не каноническая teacher‑запись.'
    };
  } else if (activeTruthTrackedSession) {
    if (videoChecked && !videoAvailable) {
      truth = {
        label: 'доверие потеряно',
        tone: 'risk',
        summary: videoError || 'Сессия требует видео, но источник teacher недоступен.'
      };
    } else if (trust.label === 'offline' || liveSourceCount < 3) {
      truth = {
        label: 'доверие потеряно',
        tone: 'risk',
        summary: trust.label === 'offline'
          ? 'Живой runtime ушёл в оффлайн во время teacher-сессии.'
          : `Live coverage просела до ${liveSourceCount}/${Math.max(liveSourceCount, readyNodes, DEFAULT_VISIBLE_NODE_COUNT)} активных источников.`
      };
    } else if (trust.label === 'degraded' || trust.tone === 'warn' || truthInvalidationReason) {
      truth = {
        label: 'деградация',
        tone: 'warn',
        summary: truthInvalidationReason
          ? `Покрытие truth деградировало: ${displayToken(truthInvalidationReason)}.`
          : `Сейчас live trust = ${displayToken(trust.label || 'degraded')}; teacher truth нужно считать деградировавшим.`
      };
    } else {
      truth = {
        label: 'с видео',
        tone: 'ok',
        summary: `Teacher-сессия остаётся с видео; live trust ${displayToken(trust.label || 'ready')} и ${Math.max(liveSourceCount, readyNodes)}/${Math.max(liveSourceCount, readyNodes, DEFAULT_VISIBLE_NODE_COUNT)} источников активны.`
      };
    }
  } else if (preflight.ok && videoAvailable) {
    truth = {
      label: 'ready',
      tone: 'ok',
      summary: 'Предпроверка подтвердила источник с видео; можно стартовать каноническую запись.'
    };
  }

  const blockReasons = [];
  if (guidedActive) {
    blockReasons.push('Сейчас активен архивный guided‑пакет. Останови его, прежде чем запускать канонический freeform.');
  }
  if (legacyFreeformActive) {
    blockReasons.push('Сейчас идёт архивный freeform без teacher‑видео. Канонический freeform заблокирован, пока эта сессия не завершится.');
  }
  if (manualActive && !legacyFreeformActive) {
    blockReasons.push(status.with_video
      ? 'Сейчас активна ручная запись. Канонический freeform ждёт освобождения backend.'
      : 'Сейчас активна архивная ручная запись без teacher‑видео. Канонический freeform заблокирован.');
  }
  if (!Number.isFinite(Number(freeform.personCount)) || Number(freeform.personCount) < 1) {
    blockReasons.push('Сначала выбери количество людей для freeform-сессии.');
  }
  if (selectedTeacherKind === TEACHER_SOURCE_KIND.NONE) {
    blockReasons.push('Выбран архивный source none. Для канонического freeform нужен Pixel RTSP или камера Mac.');
  }
  if (!videoChecked) {
    blockReasons.push('Сначала запусти предпроверку, чтобы явно проверить источник teacher и узлы.');
  }
  if (videoChecked && !videoAvailable) {
    blockReasons.push(videoError || 'Источник teacher-видео недоступен, поэтому старт заблокирован.');
  }
  if (videoChecked && !preflight.ok) {
    blockReasons.push(recording.preflightError || preflight.error || 'Предпроверка не подтвердила operational readiness.');
  }

  return {
    recordingMode,
    guidedActive,
    manualActive,
    freeformActive,
    legacyFreeformActive,
    personCount,
    voiceEnabled,
    nodeEntries,
    readyNodes,
    totalNodes,
    videoChecked,
    videoAvailable,
    teacher,
    truth,
    preflight,
    startReady: blockReasons.length === 0,
    blockReasons
  };
}

function getRuntimeSessionText(snapshot) {
  const sessionId = snapshot?.csi?.runtime_session_id
    || snapshot?.pose?.runtime_session_id
    || snapshot?.pose?.metadata?.runtime_session_id;
  return sessionId || 'локальный runtime без session-id';
}

function getRuntimeStartText(snapshot) {
  const startedTs = snapshot?.csi?.runtime_started_at
    || snapshot?.csi?.runtime_started_ts
    || snapshot?.pose?.runtime_started_ts
    || snapshot?.pose?.metadata?.runtime_started_ts;
  return startedTs ? formatTimestamp(startedTs) : 'время старта runtime не публикуется';
}

function getSupportTopologyText(signature) {
  if (!signature || signature === 'unknown' || signature === 'unavailable') {
    return 'не передана';
  }
  return displayMaybeToken(signature);
}

function getRequiredTopologyText(support) {
  if (isSupportPathMissing(support)) {
    return 'support‑path не прислал';
  }
  return getSupportTopologyText(support.requiredTopologySignature);
}

function getObservedTopologyText(topology, support, primaryRuntime) {
  if (support?.observedTopologySignature && !['unknown', 'unavailable'].includes(support.observedTopologySignature)) {
    return displayMaybeToken(support.observedTopologySignature);
  }
  const sourceCount = Number(topology?.sourceCount) || Number(primaryRuntime?.nodesActive) || 0;
  if (sourceCount > 0) {
    return `${sourceCount} активных источника`;
  }
  return 'не передана';
}

function getSupportProbabilityText(support) {
  if (support?.probability != null && !Number.isNaN(Number(support.probability))) {
    return formatNumber(support.probability, 4);
  }
    return isSupportPathMissing(support) ? 'support‑path не рассчитан' : 'вероятность не передана';
}

function getSupportThresholdText(support) {
  if (support?.threshold != null && !Number.isNaN(Number(support.threshold))) {
    return formatNumber(support.threshold, 3);
  }
    return isSupportPathMissing(support) ? 'support‑path не рассчитан' : 'порог не передан';
}

function getSupportLastEventText(support) {
  if (!support?.lastEvent) {
    return 'событие не приходило';
  }
  const eventAgeText = support?.lastEventAgeSec == null ? 'время события не передано' : formatRelativeTime(support.lastEventAgeSec);
  return `${displayToken(support.lastEvent)} / ${eventAgeText}`;
}

function getSupportTimingText(value, support) {
  if (value != null && !Number.isNaN(Number(value))) {
    return formatRelativeTime(value);
  }
    return isSupportPathMissing(support) ? 'support‑path не активен' : 'время не передано';
}

function getFingerprintLabelText(fingerprint) {
  if (fingerprint?.label && fingerprint.label !== 'unknown') {
    return displayToken(fingerprint.label);
  }
  return 'сигнатура не рассчитана';
}

function getFingerprintMarginText(fingerprint) {
  if (fingerprint?.margin != null && !Number.isNaN(Number(fingerprint.margin))) {
    return formatNumber(fingerprint.margin, 2);
  }
  return 'запас не рассчитан';
}

function getCoordinateSourceText(coordinate) {
  if (coordinate?.ambiguityActive) {
    return 'диагностическая координата (безопасный режим неоднозначности)';
  }
  if (coordinate?.activeForMap && coordinate?.operatorXMeters != null && coordinate?.operatorYMeters != null) {
    return 'подтверждённый motion gate в безопасном режиме оператора';
  }
  if (coordinate?.activeForMap === false && (coordinate?.xCm != null || coordinate?.yCm != null)) {
    return 'диагностическая координата (вне активного движения)';
  }
  if (coordinate?.source && coordinate.source !== 'unknown') {
    return displayToken(coordinate.source);
  }
  if (coordinate?.xCm != null || coordinate?.yCm != null) {
    return 'из motion-runtime';
  }
  return 'источник не передан';
}

function getMotionActivityText(motion, primaryRuntime) {
  if (motion?.activity && motion.activity !== 'unknown') {
    return displayToken(motion.activity);
  }
  if (primaryRuntime?.state && primaryRuntime.state !== 'unknown') {
    return 'по motion-runtime';
  }
  return 'активность не передана';
}

function getGarageLayout(live) {
  return live?.garage || live?.primaryRuntime?.garage || DEFAULT_GARAGE_LAYOUT;
}

function normalizeGarageNodes(nodes = []) {
  const canonicalIpByNode = {
    node01: '192.168.0.137',
    node02: '192.168.0.117',
    node03: '192.168.0.144',
    node04: '192.168.0.125',
    node05: '192.168.0.110',
    node06: '192.168.0.132',
    node07: '192.168.0.153'
  };
  const legacyIpAliasToNode = {
    '192.168.0.143': 'node03'
  };
  const seen = new Set();

  return nodes.reduce((acc, node) => {
    if (!node) {
      return acc;
    }
    const nodeId = legacyIpAliasToNode[node.ip] || node.nodeId || node.id || null;
    const canonicalIp = nodeId ? (canonicalIpByNode[nodeId] || node.ip || null) : (node.ip || null);
    const dedupeKey = nodeId || canonicalIp || JSON.stringify(node);
    if (seen.has(dedupeKey)) {
      return acc;
    }
    seen.add(dedupeKey);
    acc.push({
      ...node,
      nodeId: nodeId || node.nodeId || node.id,
      ip: canonicalIp || node.ip
    });
    return acc;
  }, []);
}

function clampGarageCoordinate(coordinate, garage) {
  if (!coordinate || coordinate.xMeters == null || coordinate.yMeters == null) {
    return null;
  }
  const widthMeters = Number(garage?.widthMeters) || DEFAULT_GARAGE_LAYOUT.widthMeters;
  const heightMeters = Number(garage?.heightMeters) || DEFAULT_GARAGE_LAYOUT.heightMeters;
  const halfWidth = widthMeters / 2;
  return {
    xMeters: clamp(Number(coordinate.xMeters), -halfWidth, halfWidth),
    yMeters: clamp(Number(coordinate.yMeters), 0, heightMeters)
  };
}

function mapGarageCoordinateToPercent(coordinate, garage) {
  const clamped = clampGarageCoordinate(coordinate, garage);
  if (!clamped) {
    return null;
  }
  const widthMeters = Number(garage?.widthMeters) || DEFAULT_GARAGE_LAYOUT.widthMeters;
  const heightMeters = Number(garage?.heightMeters) || DEFAULT_GARAGE_LAYOUT.heightMeters;
  return {
    left: clamp(((clamped.xMeters + widthMeters / 2) / widthMeters) * 100, 3, 97),
    top: clamp((1 - (clamped.yMeters / heightMeters)) * 100, 3, 97)
  };
}

function buildGarageTrackPoints(history, currentCoordinate, garage) {
  const points = [];
  const input = Array.isArray(history) ? history.slice(-8) : [];
  input.forEach((item) => {
    const point = mapGarageCoordinateToPercent(item, garage);
    if (!point) {
      return;
    }
    points.push(point);
  });
  const currentPoint = mapGarageCoordinateToPercent(currentCoordinate, garage);
  if (currentPoint) {
    points.push(currentPoint);
  }
  return points;
}

function buildGarageTrackPolyline(points) {
  if (!points.length) {
    return '';
  }
  return points.map((point) => `${point.left.toFixed(2)},${point.top.toFixed(2)}`).join(' ');
}

function getGarageZoneBands(garage) {
  const heightMeters = Number(garage?.heightMeters) || DEFAULT_GARAGE_LAYOUT.heightMeters;
  const doorMaxY = Number(garage?.zones?.doorMaxY) || DEFAULT_GARAGE_LAYOUT.zones.doorMaxY;
  const deepMinY = Number(garage?.zones?.deepMinY) || DEFAULT_GARAGE_LAYOUT.zones.deepMinY;
  return [
    {
      id: 'deep',
      label: 'ДАЛЬНЯЯ ЗОНА',
      top: 0,
      height: ((heightMeters - deepMinY) / heightMeters) * 100
    },
    {
      id: 'center',
      label: 'ЦЕНТР',
      top: ((heightMeters - deepMinY) / heightMeters) * 100,
      height: ((deepMinY - doorMaxY) / heightMeters) * 100
    },
    {
      id: 'door',
      label: 'ДВЕРЬ',
      top: ((heightMeters - doorMaxY) / heightMeters) * 100,
      height: (doorMaxY / heightMeters) * 100
    }
  ];
}

function buildMultiTargetDiagnosticCoordinates(centerCoordinate, garage, personCount) {
  const count = Math.max(2, Math.min(4, Number(personCount) || 2));
  const patterns = {
    2: [
      { dx: -0.45, dy: 0 },
      { dx: 0.45, dy: 0 }
    ],
    3: [
      { dx: -0.52, dy: -0.18 },
      { dx: 0, dy: 0.26 },
      { dx: 0.52, dy: -0.18 }
    ],
    4: [
      { dx: -0.56, dy: -0.24 },
      { dx: 0.56, dy: -0.24 },
      { dx: -0.56, dy: 0.24 },
      { dx: 0.56, dy: 0.24 }
    ]
  };

  const base = clampGarageCoordinate(centerCoordinate, garage);
  if (!base) {
    return [];
  }

  return (patterns[count] || patterns[4]).map((offset, index) => {
    const candidate = clampGarageCoordinate({
      xMeters: base.xMeters + offset.dx,
      yMeters: base.yMeters + offset.dy
    }, garage);
    return candidate ? {
      ...candidate,
      id: `cand_${index + 1}`
    } : null;
  }).filter(Boolean);
}

function formatMarkerSummary(marker) {
  if (!marker || typeof marker !== 'object') {
    return 'маркер не передан';
  }

  const parts = [];
  if (marker.sample_index != null) {
    parts.push(`сэмпл ${marker.sample_index}`);
  }
  if (marker.elapsed_sec != null) {
    parts.push(`${formatNumber(marker.elapsed_sec, 3)} с`);
  }
  if (marker.assigned_side) {
    parts.push(displayToken(marker.assigned_side));
  } else if (marker.shadow_status) {
    parts.push(displayToken(marker.shadow_status));
  }
  if (marker.scenario_phase_label) {
    parts.push(displayToken(marker.scenario_phase_label));
  }

  return parts.length ? parts.join(' / ') : 'маркер есть';
}

function renderMetricBar(label, value) {
  return `
    <div class="metric-bar">
      <div class="metric-bar__label">${escapeHtml(label)}</div>
      <div class="metric-bar__track">
        <div class="metric-bar__fill" style="width:${Math.min(100, Math.max(0, value * 100))}%"></div>
      </div>
      <div class="metric-bar__value">${formatPercent(value, 1)}</div>
    </div>
  `;
}

function renderStatusPill(label, tone) {
  return `<span class="status-pill ${toneClass(tone)}">${escapeHtml(label)}</span>`;
}

function renderInspectorValue(value) {
  if (value == null || value === '') {
    return '<span class="muted">данные не пришли</span>';
  }
  if (Array.isArray(value)) {
    if (!value.length) {
      return '<span class="muted">список пуст</span>';
    }
    return escapeHtml(value.map((item) => displayToken(item)).join(', '));
  }
  if (typeof value === 'boolean') {
    return value ? UI_LOCALE.common.yes : UI_LOCALE.common.no;
  }
  if (typeof value === 'number') {
    if (Number.isInteger(value)) {
      return escapeHtml(String(value));
    }
    const digits = Math.abs(value) >= 100 ? 1 : 3;
    return escapeHtml(Number(value).toFixed(digits).replace(/\.?0+$/, ''));
  }
  return escapeHtml(displayToken(String(value)));
}

function renderInspectorTable(columns, rows, emptyText) {
  if (!rows?.length) {
    return `<div class="empty-state">${escapeHtml(emptyText)}</div>`;
  }

  const columnCount = columns.length;
  return `
    <div class="inspector-table">
      <div class="inspector-table__head" style="--columns:${columnCount}">
        ${columns.map((column) => `<div class="inspector-table__cell">${escapeHtml(column.label)}</div>`).join('')}
      </div>
      ${rows.map((row) => `
        <div class="inspector-table__row" style="--columns:${columnCount}">
          ${columns.map((column) => `<div class="inspector-table__cell">${renderInspectorValue(row[column.key])}</div>`).join('')}
        </div>
      `).join('')}
    </div>
  `;
}

export function buildForensicWarmIndicator(orderedRuns, selectedRunId, cacheState = {}) {
  if (!orderedRuns?.length || !selectedRunId) {
    return null;
  }

  const currentIndex = orderedRuns.findIndex((item) => item.run_id === selectedRunId);
  if (currentIndex === -1) {
    return null;
  }

  const prevRunId = orderedRuns[currentIndex - 1]?.run_id || null;
  const nextRunId = orderedRuns[currentIndex + 1]?.run_id || null;
  if (!prevRunId && !nextRunId) {
    return null;
  }

  const cachedRunIds = new Set(Array.isArray(cacheState?.cachedRunIds) ? cacheState.cachedRunIds : []);
  const inflightRunIds = new Set(Array.isArray(cacheState?.inflightRunIds) ? cacheState.inflightRunIds : []);
  const prevCached = prevRunId ? cachedRunIds.has(prevRunId) : false;
  const nextCached = nextRunId ? cachedRunIds.has(nextRunId) : false;
  const prevInflight = prevRunId ? inflightRunIds.has(prevRunId) : false;
  const nextInflight = nextRunId ? inflightRunIds.has(nextRunId) : false;
  const cachedCount = Number(prevCached) + Number(nextCached);
  const inflightCount = Number(prevInflight) + Number(nextInflight);
  const neighborCount = Number(Boolean(prevRunId)) + Number(Boolean(nextRunId));

  if (!cachedCount && !inflightCount) {
    return null;
  }

  if (neighborCount === 1) {
    const hasNext = Boolean(nextRunId);
    const warmed = hasNext ? nextCached : prevCached;
    const warming = hasNext ? nextInflight : prevInflight;

    if (warmed) {
      return {
        tone: 'ready',
        label: hasNext ? 'Следующий прогрет' : 'Предыдущий прогрет',
        detail: hasNext ? 'переход вниз уже из cache' : 'переход вверх уже из cache'
      };
    }

    if (warming) {
      return {
        tone: 'warming',
        label: hasNext ? 'Прогреваю следующий run' : 'Прогреваю предыдущий run',
        detail: 'prefetch идёт в фоне'
      };
    }

    return null;
  }

  if (cachedCount === 2) {
    return {
      tone: 'ready',
      label: 'Соседние run’ы прогреты',
      detail: 'prev и next уже в cache'
    };
  }

  if (cachedCount === 1 && inflightCount === 1) {
    return {
      tone: 'warming',
      label: 'Соседние почти готовы',
      detail: 'один сосед уже в cache, второй догружается'
    };
  }

  if (cachedCount === 1) {
    return {
      tone: 'partial',
      label: 'Прогрет один сосед',
      detail: 'второй загрузится по запросу'
    };
  }

  return {
    tone: 'warming',
    label: 'Прогреваю соседние run’ы',
    detail: inflightCount === 2 ? 'prefetch идёт в фоне' : 'один сосед ещё догружается'
  };
}

export class CsiOperatorApp {
  constructor(rootElement) {
    this.root = rootElement;
    this.tabManager = null;
    this.service = new CsiOperatorService();
    this.snapshot = null;
    this.unsubscribe = null;
    this.fp2Tab = null;
    this.sections = {};
    this.forensicQuery = '';
    this.forensicViewMode = 'time';
    this.forensicFateFilter = 'all';
    this.forensicSearchPrefetchTimer = null;
    this.pendingForensicScrollRunId = null;
    this.lastRenderedForensicRunId = null;
    this.signalCoordinateState = null;
    this._nodesLive = null;
    this._nodesLiveTimer = null;
    this._nodesHealth = null; // from /api/v1/csi/nodes (management + stream health)
    this._nodesHealthTimer = null;
    this._nodesRssiHistory = {}; // { node_id: [rssi, rssi, ...] } - last 20 values for sparklines
    // Signal dashboard chart state
    this._sdCharts = null;
    this._sdHistory = [];
    this._sdEvents = [];
    this._sdLastBinary = null;
    this._sdSelectedRange = 60;
    this._sdSparklineData = {};
    this._sdNodeState = {};
    this._sdHealth = null;
    this._sdShadow = null;
    this._sdArchiveMeta = null;
    this._sdTruthOccupancy = null;
    this._sdLoadedHistoryRangeKey = null;
    this._sdServerHistoryPromise = null;
    this._sdPendingHistoryRangeKey = null;
    this._sdPollTimer = null;
    this._sdInitialized = false;
    this._runtimeUiBackoffUntil = 0;
    this._runtimeUiOptionalSurface = {
      csiFeaturesEnabled: true
    };
    this._doorCenterMapOverlayState = {
      heldZone: null,
      holdUntilMs: 0,
      centerConfirmStreak: 0,
      lastAgreement: null,
      lastConfidence: null
    };
    this.runtimeViewSelection = readUiRuntimeViewSelection();
    this.validationFilter = 'all';
    this.runtimeRecordingUi = {
      showLegacyGuided: false,
      showLegacyManual: false,
      showLegacyTeacherSource: false
    };
    this.handleRootClick = this.handleRootClick.bind(this);
    this.handleRootInput = this.handleRootInput.bind(this);
    this.handleRootChange = this.handleRootChange.bind(this);
    this.handleGlobalKeydown = this.handleGlobalKeydown.bind(this);
  }

  async init() {
    this.renderShell();
    this.cacheElements();
    this.root.addEventListener('click', this.handleRootClick);
    this.root.addEventListener('input', this.handleRootInput);
    this.root.addEventListener('change', this.handleRootChange);
    document.addEventListener('keydown', this.handleGlobalKeydown);
    this.tabManager = new TabManager(this.root);
    this.tabManager.init();
    this.tabManager.onTabChange((tabId) => {
      if (tabId === 'fp2') {
        this.initFp2Tab();
      }
      if (tabId === 'labeling') {
        this.renderLabeling();
      }
      if (tabId === 'signal') {
        this._initSignalDashboard();
      }
    });
    this.unsubscribe = this.service.subscribe((snapshot) => {
      this.snapshot = snapshot;
      this.renderSnapshot();
    });
    await this.service.start();
    this._startNodesLivePolling();
  }

  _isTabActive(tabId) {
    return this.root?.querySelector(`.tab-content.active#${tabId}`) != null;
  }

  _isRuntimeUiBackoffActive() {
    return this._runtimeUiBackoffUntil > Date.now();
  }

  _markRuntimeUiBackoff() {
    this._runtimeUiBackoffUntil = Date.now() + this._RUNTIME_UI_BACKOFF_MS;
  }

  _clearRuntimeUiBackoff() {
    this._runtimeUiBackoffUntil = 0;
  }

  _isRuntimeUiOptionalSurfaceEnabled(url) {
    if (url === '/api/v1/csi/features') {
      return this._runtimeUiOptionalSurface.csiFeaturesEnabled;
    }
    return true;
  }

  _disableRuntimeUiOptionalSurface(url) {
    if (url === '/api/v1/csi/features') {
      this._runtimeUiOptionalSurface.csiFeaturesEnabled = false;
    }
  }

  async _fetchRuntimeUiJson(url, { timeoutMs = 4000 } = {}) {
    if (this._isRuntimeUiBackoffActive() || !this._isRuntimeUiOptionalSurfaceEnabled(url)) {
      return null;
    }
    try {
      const response = await fetch(url, { signal: AbortSignal.timeout(timeoutMs) });
      if (!response.ok) {
        if (response.status === 404) {
          this._disableRuntimeUiOptionalSurface(url);
          return null;
        }
        if (response.status >= 500) {
          this._markRuntimeUiBackoff();
        }
        return null;
      }
      this._clearRuntimeUiBackoff();
      return await response.json();
    } catch (_) {
      this._markRuntimeUiBackoff();
      return null;
    }
  }

  _startNodesLivePolling() {
    const SPARKLINE_MAX = 20;
    const poll = async () => {
      const payload = await this._fetchRuntimeUiJson('/api/v1/csi/nodes/live');
      if (payload) {
        this._nodesLive = payload;
        // Track RSSI history for sparklines
        if (this._nodesLive?.nodes) {
          for (const n of this._nodesLive.nodes) {
            if (!this._nodesRssiHistory[n.node_id]) {
              this._nodesRssiHistory[n.node_id] = [];
            }
            const hist = this._nodesRssiHistory[n.node_id];
            hist.push(n.rssi != null ? n.rssi : null);
            if (hist.length > SPARKLINE_MAX) {
              hist.splice(0, hist.length - SPARKLINE_MAX);
            }
          }
        }
        this._renderNodesLiveCards();
      }
    };
    poll();
    this._nodesLiveTimer = setInterval(poll, 1500);

    // Poll management health at a slower rate (every 10s)
    const pollHealth = async () => {
      const payload = await this._fetchRuntimeUiJson('/api/v1/csi/nodes', { timeoutMs: 8000 });
      if (payload) {
        this._nodesHealth = payload;
        this._renderNodesLiveCards();
      }
    };
    pollHealth();
    this._nodesHealthTimer = setInterval(pollHealth, 10000);
  }

  _rssiColor(rssi) {
    if (rssi == null) return '#6b7280';
    if (rssi > -40) return '#22c55e';
    if (rssi > -55) return '#f59e0b';
    return '#ef4444';
  }

  _renderSparkline(nodeId) {
    const hist = this._nodesRssiHistory[nodeId];
    if (!hist || hist.length < 2) return '';
    const BARS = 20;
    const values = hist.slice(-BARS);
    const validValues = values.filter((v) => v != null);
    if (validValues.length < 2) return '';
    const minR = Math.min(...validValues);
    const maxR = Math.max(...validValues);
    const range = Math.max(maxR - minR, 5); // at least 5dBm range
    return `<div class="node-signal-card__sparkline">${values.map((v) => {
      if (v == null) return '<div class="node-signal-card__sparkline-bar" style="height:1px;background:#333"></div>';
      const pct = Math.max(5, ((v - minR) / range) * 100);
      const color = this._rssiColor(v);
      return `<div class="node-signal-card__sparkline-bar" style="height:${pct}%;background:${color}"></div>`;
    }).join('')}</div>`;
  }

  _getNodeHealthInfo(nodeId) {
    if (!this._nodesHealth) return null;
    const nodes = Array.isArray(this._nodesHealth) ? this._nodesHealth : (this._nodesHealth.nodes || []);
    return nodes.find((h) => h.name === nodeId) || null;
  }

  _renderNodeCard(n) {
    const online = n.online;
    const health = this._getNodeHealthInfo(n.node_id);

    // Determine tri-state: stream (CSI packets) and management (HTTP :8032)
    const streamActive = online; // based on packet age < 10s
    const mgmtOk = health ? Boolean(health.management_ok) : null; // null = not yet probed

    // Compute composite status
    let dotColor, statusLabel, statusClass, interpretText;
    if (streamActive && mgmtOk !== false) {
      // Stream OK + mgmt OK (or not yet probed)
      dotColor = '#22c55e';
      statusLabel = mgmtOk === true ? '\u041F\u043E\u043B\u043D\u043E\u0441\u0442\u044C\u044E \u0434\u043E\u0441\u0442\u0443\u043F\u043D\u0430' : 'CSI \u0430\u043A\u0442\u0438\u0432\u0435\u043D';
      statusClass = mgmtOk === true ? 'node-status-full' : '';
      interpretText = '';
    } else if (streamActive && mgmtOk === false) {
      // Stream OK + mgmt FAIL = likely wrong router
      dotColor = '#f59e0b';
      statusLabel = 'CSI \u0410\u041A\u0422\u0418\u0412\u0415\u041D';
      statusClass = 'node-status-stream-only';
      interpretText = 'MGMT \u043D\u0435\u0434\u043E\u0441\u0442\u0443\u043F\u0435\u043D \u2014 \u0432\u043E\u0437\u043C\u043E\u0436\u043D\u043E Mac \u043D\u0430 \u0434\u0440\u0443\u0433\u043E\u043C \u0440\u043E\u0443\u0442\u0435\u0440\u0435';
    } else if (!streamActive && mgmtOk === true) {
      // No CSI but mgmt OK = something wrong with CSI stream
      dotColor = '#ff9800';
      statusLabel = 'CSI \u041D\u0415 \u041F\u041E\u0421\u0422\u0423\u041F\u0410\u0415\u0422';
      statusClass = 'node-status-mgmt-only';
      interpretText = 'Management \u0434\u043E\u0441\u0442\u0443\u043F\u0435\u043D, \u043D\u043E CSI \u043D\u0435 \u043F\u043E\u0441\u0442\u0443\u043F\u0430\u0435\u0442';
    } else {
      // Both down
      dotColor = '#ef4444';
      statusLabel = '\u041D\u041E\u0414\u0410 \u041D\u0415\u0414\u041E\u0421\u0422\u0423\u041F\u041D\u0410';
      statusClass = 'node-status-offline';
      interpretText = '';
    }

    const rssiColor = this._rssiColor(n.rssi);
    const tvColor = n.temporal_var > 2.0 ? '#ef4444' : n.temporal_var > 0.5 ? '#f59e0b' : '#22c55e';
    const pps = n.packets_window != null && n.last_age_sec > 0
      ? Math.round(n.packets_window / Math.max(n.last_age_sec, 1))
      : null;
    const lastSeenText = n.last_age_sec != null
      ? (n.last_age_sec < 2 ? '\u0442\u043E\u043B\u044C\u043A\u043E \u0447\u0442\u043E' : `${n.last_age_sec.toFixed(0)} \u0441 \u043D\u0430\u0437\u0430\u0434`)
      : '\u2014';

    // Status pills for stream and management
    const streamPill = streamActive
      ? '<span class="node-signal-card__status-pill node-status-full">\u2705 CSI</span>'
      : '<span class="node-signal-card__status-pill node-status-offline">\u274C CSI</span>';
    const mgmtPill = mgmtOk === true
      ? '<span class="node-signal-card__status-pill node-status-full">\u2705 MGMT</span>'
      : mgmtOk === false
        ? '<span class="node-signal-card__status-pill node-status-stream-only">\u26A0\uFE0F MGMT</span>'
        : '';

    const dimCard = !streamActive && mgmtOk !== true;

    return `
      <div class="node-signal-card${dimCard ? ' node-signal-card--offline' : ''}">
        <div class="node-signal-card__header">
          <div class="node-signal-card__name">
            <span class="node-signal-card__dot" style="background:${dotColor}"></span>
            ${escapeHtml(n.node_id)}
            <span style="font-size:10px;font-weight:400;color:${dotColor}">${escapeHtml(statusLabel)}</span>
          </div>
          <span class="node-signal-card__ip">${escapeHtml(n.ip)}</span>
        </div>
        <div class="node-signal-card__status-row">${streamPill}${mgmtPill}</div>
        ${interpretText ? `<div class="node-signal-card__status-interpret">${escapeHtml(interpretText)}</div>` : ''}
        <div style="display:flex;align-items:center;gap:8px">
          <span class="node-signal-card__rssi-label" style="color:${rssiColor}">${n.rssi != null ? n.rssi + '' : '\u2014'}<small style="font-size:10px;font-weight:400"> dBm</small></span>
          <div style="flex:1">${this._renderSparkline(n.node_id)}</div>
        </div>
        <div class="node-signal-card__metrics">
          <div class="node-signal-card__metric"><span>amp avg</span><span class="node-signal-card__metric-value">${n.amp_mean != null ? n.amp_mean.toFixed(1) : '\u2014'}</span></div>
          <div class="node-signal-card__metric"><span>tvar</span><span class="node-signal-card__metric-value" style="color:${tvColor}">${n.temporal_var != null ? n.temporal_var.toFixed(3) : '\u2014'}</span></div>
          <div class="node-signal-card__metric"><span>\u043F\u0430\u043A\u0435\u0442\u044B</span><span class="node-signal-card__metric-value">${n.packets || 0}${pps != null ? ' <small style="opacity:0.6">(' + pps + '/\u0441)</small>' : ''}</span></div>
          <div class="node-signal-card__metric"><span>amp max</span><span class="node-signal-card__metric-value">${n.amp_max != null ? n.amp_max.toFixed(0) : '\u2014'}</span></div>
        </div>
        <div class="node-signal-card__last-seen">${escapeHtml(lastSeenText)}</div>
      </div>`;
  }

  _renderNodesLiveRows() {
    const data = this._nodesLive;
    if (!data || !data.nodes) {
      return '<div style="padding:8px;opacity:0.5">Загрузка...</div>';
    }
    return data.nodes.map((n) => this._renderNodeCard(n)).join('');
  }

  _signalBar(value, min, max) {
    const pct = Math.max(0, Math.min(100, ((value - min) / (max - min)) * 100));
    const color = pct > 60 ? '#22c55e' : pct > 30 ? '#f59e0b' : '#ef4444';
    return `<div style="height:3px;margin-top:2px;background:#333;border-radius:2px"><div style="width:${pct}%;height:100%;background:${color};border-radius:2px"></div></div>`;
  }

  _renderNetworkMismatchBanner() {
    if (!this._nodesLive?.nodes || !this._nodesHealth) return '';
    const nodes = this._nodesLive.nodes;
    const healthNodes = Array.isArray(this._nodesHealth) ? this._nodesHealth : (this._nodesHealth.nodes || []);
    if (!nodes.length || !healthNodes.length) return '';

    let streamOkMgmtFail = 0;
    let totalWithStream = 0;
    for (const n of nodes) {
      if (!n.online) continue;
      totalWithStream++;
      const h = healthNodes.find((h) => h.name === n.node_id);
      if (h && !h.management_ok) {
        streamOkMgmtFail++;
      }
    }

    if (totalWithStream >= 3 && streamOkMgmtFail === totalWithStream) {
      return `
        <div class="network-mismatch-banner">
          <span class="network-mismatch-banner__icon">\u26A0\uFE0F</span>
          <div class="network-mismatch-banner__text">
            <strong>\u0412\u0441\u0435 \u043D\u043E\u0434\u044B \u043F\u0435\u0440\u0435\u0434\u0430\u044E\u0442 CSI, \u043D\u043E management HTTP \u043D\u0435\u0434\u043E\u0441\u0442\u0443\u043F\u0435\u043D.</strong>
            \u0412\u0435\u0440\u043E\u044F\u0442\u043D\u043E Mac \u043F\u043E\u0434\u043A\u043B\u044E\u0447\u0451\u043D \u043A \u0434\u0440\u0443\u0433\u043E\u043C\u0443 \u0440\u043E\u0443\u0442\u0435\u0440\u0443 (\u043D\u0435 Tenda). CSI \u0434\u0430\u043D\u043D\u044B\u0435 \u043F\u043E\u0441\u0442\u0443\u043F\u0430\u044E\u0442 \u043D\u043E\u0440\u043C\u0430\u043B\u044C\u043D\u043E, \u043D\u043E HTTP-\u043F\u0440\u043E\u0431\u044B \u043A \u043D\u043E\u0434\u0430\u043C \u043D\u0435 \u043F\u0440\u043E\u0445\u043E\u0434\u044F\u0442.
          </div>
        </div>
      `;
    }

    return '';
  }

  _renderNodesLiveCards() {
    const el = this.root.querySelector('#nodes-live-grid');
    if (!el) return;
    el.innerHTML = this._renderNetworkMismatchBanner() + this._renderNodesLiveRows();
    // Update position info
    const posEl = this.root.querySelector('#nodes-live-position');
    if (posEl && this._nodesLive?.position) {
      const p = this._nodesLive.position;
      if (p.label) {
        const probsText = p.probabilities
          ? Object.entries(p.probabilities).map(([k, v]) => `${k}: ${(v * 100).toFixed(1)}%`).join(' / ')
          : '';
        posEl.innerHTML = `<strong>V48 prediction:</strong> ${escapeHtml(p.label)} (${(p.confidence * 100).toFixed(1)}%) — ${escapeHtml(probsText)} — ${p.nodes_ready}/${this._nodesLive.total_nodes} nodes ready`;
      } else if (p.error) {
        posEl.innerHTML = `<span style="color:#ef4444">Error: ${escapeHtml(p.error)}</span>`;
      }
    }
  }

  dispose() {
    this.root.removeEventListener('click', this.handleRootClick);
    this.root.removeEventListener('input', this.handleRootInput);
    this.root.removeEventListener('change', this.handleRootChange);
    document.removeEventListener('keydown', this.handleGlobalKeydown);
    this.clearForensicSearchPrefetch();
    if (this._nodesLiveTimer) clearInterval(this._nodesLiveTimer);
    if (this._nodesHealthTimer) clearInterval(this._nodesHealthTimer);
    this._destroySignalDashboard();
    this.unsubscribe?.();
    this.service.stop();
  }

  selectUiRuntimeView(nextView) {
    const resolved = nextView === UI_RUNTIME_VIEW_OPTIONS.TRACK_B
      ? UI_RUNTIME_VIEW_OPTIONS.TRACK_B
      : nextView === UI_RUNTIME_VIEW_OPTIONS.V15
        ? UI_RUNTIME_VIEW_OPTIONS.V15
        : nextView === UI_RUNTIME_VIEW_OPTIONS.V27_7NODE
          ? UI_RUNTIME_VIEW_OPTIONS.V27_7NODE
        : nextView === UI_RUNTIME_VIEW_OPTIONS.GARAGE_V2
          ? UI_RUNTIME_VIEW_OPTIONS.GARAGE_V2
        : UI_RUNTIME_VIEW_OPTIONS.TRACK_A;
    if (this.runtimeViewSelection === resolved) {
      return;
    }
    this.runtimeViewSelection = resolved;
    writeUiRuntimeViewSelection(resolved);
    if (this.snapshot) {
      this.renderSnapshot();
    }
  }

  getSmoothedSignalCoordinate(coordinate, garage) {
    const target = clampGarageCoordinate(coordinate, garage);
    if (!target) {
      this.signalCoordinateState = null;
      this.signalCoordinateHistory = [];
      return null;
    }

    // Initialize history buffer on first call
    if (!this.signalCoordinateHistory) {
      this.signalCoordinateHistory = [];
    }

    // Keep a sliding window of recent raw samples for median filtering
    this.signalCoordinateHistory.push({ x: target.xMeters, y: target.yMeters });
    if (this.signalCoordinateHistory.length > 3) {
      this.signalCoordinateHistory.shift();
    }

    // Compute median of recent samples (robust against outlier spikes)
    const sortedX = this.signalCoordinateHistory.map(p => p.x).sort((a, b) => a - b);
    const sortedY = this.signalCoordinateHistory.map(p => p.y).sort((a, b) => a - b);
    const mid = Math.floor(sortedX.length / 2);
    const medianX = sortedX.length % 2 ? sortedX[mid] : (sortedX[mid - 1] + sortedX[mid]) / 2;
    const medianY = sortedY.length % 2 ? sortedY[mid] : (sortedY[mid - 1] + sortedY[mid]) / 2;

    const previous = this.signalCoordinateState;
    if (!previous) {
      this.signalCoordinateState = { xMeters: medianX, yMeters: medianY };
      return { xMeters: medianX, yMeters: medianY };
    }

    const dx = medianX - previous.xMeters;
    const dy = medianY - previous.yMeters;
    const distance = Math.hypot(dx, dy);

    // Simple EMA — no dead-zone, no velocity damping
    // Backend already does smoothing; UI just adds gentle follow
    const alpha = distance > 2.0 ? 0.80 : distance > 0.5 ? 0.50 : 0.35;

    const smoothed = {
      xMeters: previous.xMeters + dx * alpha,
      yMeters: previous.yMeters + dy * alpha
    };

    this.signalCoordinateState = smoothed;
    return { xMeters: smoothed.xMeters, yMeters: smoothed.yMeters };
  }

  handleRootClick(event) {
    const toggleLegacyGuidedButton = event.target.closest('[data-action="toggle-legacy-guided"]');
    if (toggleLegacyGuidedButton) {
      this.runtimeRecordingUi.showLegacyGuided = !this.runtimeRecordingUi.showLegacyGuided;
      this.renderRuntime();
      return;
    }

    const toggleLegacyManualButton = event.target.closest('[data-action="toggle-legacy-manual"]');
    if (toggleLegacyManualButton) {
      this.runtimeRecordingUi.showLegacyManual = !this.runtimeRecordingUi.showLegacyManual;
      this.renderRuntime();
      return;
    }

    const toggleLegacyTeacherSourceButton = event.target.closest('[data-action="toggle-legacy-teacher-source"]');
    if (toggleLegacyTeacherSourceButton) {
      this.runtimeRecordingUi.showLegacyTeacherSource = !this.runtimeRecordingUi.showLegacyTeacherSource;
      this.renderRuntime();
      return;
    }

    const capturePreflightButton = event.target.closest('[data-action="capture-preflight"]');
    if (capturePreflightButton) {
      const packId = capturePreflightButton.getAttribute('data-pack-id');
      if (packId) {
        this.service.selectGuidedCapturePack(packId);
      }
      void this.service.runRecordingPreflight({ packId: packId || null, force: true });
      return;
    }

    const captureStartButton = event.target.closest('[data-action="capture-start"]');
    if (captureStartButton) {
      const packId = captureStartButton.getAttribute('data-pack-id');
      if (packId) {
        this.service.selectGuidedCapturePack(packId);
        void this.service.startGuidedCapturePack(packId);
      }
      return;
    }

    const captureStopButton = event.target.closest('[data-action="capture-stop"]');
    if (captureStopButton) {
      void this.service.stopGuidedCapturePack();
      return;
    }

    const manualPreflightButton = event.target.closest('[data-action="manual-preflight"]');
    if (manualPreflightButton) {
      const withVideo = manualPreflightButton.getAttribute('data-manual-video') === 'true';
      void this.service.runRecordingPreflight({ force: true, checkVideoOverride: withVideo });
      return;
    }

    const manualStartButton = event.target.closest('[data-action="manual-start"]');
    if (manualStartButton) {
      void this.service.startManualRecording();
      return;
    }

    const manualStopButton = event.target.closest('[data-action="manual-stop"]');
    if (manualStopButton) {
      void this.service.stopActiveRecording();
      return;
    }

    const freeformPreflightButton = event.target.closest('[data-action="freeform-preflight"]');
    if (freeformPreflightButton) {
      void this.service.runRecordingPreflight({ force: true, checkVideoOverride: true });
      return;
    }

    const freeformStartButton = event.target.closest('[data-action="freeform-start"]');
    if (freeformStartButton) {
      void this.service.startFreeformRecording();
      return;
    }

    const freeformStopButton = event.target.closest('[data-action="freeform-stop"]');
    if (freeformStopButton) {
      void this.service.stopActiveRecording();
      return;
    }

    const fewshotStartButton = event.target.closest('[data-action="fewshot-calibration-start"]');
    if (fewshotStartButton) {
      const protocolId = fewshotStartButton.getAttribute('data-protocol-id');
      void this.service.startFewshotCalibration(protocolId || null);
      return;
    }

    const fewshotStopButton = event.target.closest('[data-action="fewshot-calibration-stop"]');
    if (fewshotStopButton) {
      void this.service.stopFewshotCalibration();
      return;
    }

    const fewshotResetButton = event.target.closest('[data-action="fewshot-calibration-reset"]');
    if (fewshotResetButton) {
      void this.service.resetFewshotCalibration();
      return;
    }

    const capturePackButton = event.target.closest('[data-pack-select]');
    if (capturePackButton) {
      const packId = capturePackButton.getAttribute('data-pack-select');
      if (packId) {
        this.service.selectGuidedCapturePack(packId);
      }
      return;
    }

    const refreshButton = event.target.closest('[data-action="refresh-forensics"]');
    if (refreshButton) {
      void this.service.refreshForensicRuns({ force: true, manual: true });
      return;
    }

    const viewButton = event.target.closest('[data-forensic-view]');
    if (viewButton) {
      const nextView = viewButton.getAttribute('data-forensic-view');
      if (nextView) {
        this.applyForensicViewMode(nextView);
      }
      return;
    }

    const fateButton = event.target.closest('[data-forensic-fate]');
    if (fateButton) {
      const nextGroup = fateButton.getAttribute('data-forensic-fate') || 'all';
      this.applyForensicFateFilter(nextGroup);
      return;
    }

    const runCard = event.target.closest('[data-forensic-run-id]');
    if (runCard) {
      const runId = runCard.getAttribute('data-forensic-run-id');
      if (runId) {
        void this.service.selectForensicRun(runId);
      }
      return;
    }

    const validationRefresh = event.target.closest('[data-action="validation-refresh"]');
    if (validationRefresh) {
      void this.service.refreshValidationStatus(true);
      return;
    }

    const validationSelect = event.target.closest('[data-action="validation-select"]');
    if (validationSelect) {
      const segmentId = validationSelect.getAttribute('data-segment-id');
      if (segmentId) {
        void this.service.fetchValidationSegmentDetail(segmentId);
      }
      return;
    }

    const validationResolve = event.target.closest('[data-action="validation-resolve"]');
    if (validationResolve) {
      const segmentId = validationResolve.getAttribute('data-segment-id');
      const resolution = validationResolve.getAttribute('data-resolution');
      if (segmentId && resolution) {
        void this.service.resolveValidationSegment(segmentId, resolution);
      }
      return;
    }

    const validationBatch = event.target.closest('[data-action="validation-batch-approve"]');
    if (validationBatch) {
      void this.service.batchApproveValidated({ dryRun: false });
      return;
    }

    const refreshRuntimeModelsButton = event.target.closest('[data-action="refresh-runtime-models"]');
    if (refreshRuntimeModelsButton) {
      void this.service.refreshRuntimeModels(true);
      return;
    }

    const selectRuntimeModelButton = event.target.closest('[data-action="select-runtime-model"]');
    if (selectRuntimeModelButton) {
      const modelId = selectRuntimeModelButton.getAttribute('data-model-id');
      if (modelId) {
        void this.service.selectRuntimeModel(modelId);
      }
      return;
    }

    const selectUiRuntimeViewButton = event.target.closest('[data-action="select-ui-runtime-view"]');
    if (selectUiRuntimeViewButton) {
      const runtimeView = selectUiRuntimeViewButton.getAttribute('data-runtime-view');
      if (runtimeView) {
        this.selectUiRuntimeView(runtimeView);
      }
    }
  }

  handleRootInput(event) {
    const filterInput = event.target.closest('[data-role="forensic-filter"]');
    if (filterInput) {
      this.forensicQuery = filterInput.value || '';
      if (this.snapshot) {
        this.ensureForensicSelectionVisible();
        this.renderForensics();
        this.scheduleForensicSearchPrefetch();
      }
      return;
    }

    const validationFilter = event.target.closest('[data-role="validation-filter"]');
    if (validationFilter) {
      this.validationFilter = validationFilter.value || 'all';
      if (this.snapshot) {
        this.renderValidation();
      }
      return;
    }

    const manualField = event.target.closest('[data-role="manual-recording-field"]');
    if (manualField) {
      if (manualField.tagName === 'SELECT' || manualField.type === 'checkbox') {
        return;
      }
      const field = manualField.getAttribute('data-field');
      if (!field) {
        return;
      }
      this.service.updateManualRecordingField(field, manualField.value);
      this.syncManualRecordingForm();
      return;
    }

    const teacherSourceField = event.target.closest('[data-role="teacher-source-field"]');
    if (teacherSourceField) {
      if (teacherSourceField.tagName === 'SELECT' || teacherSourceField.type === 'checkbox') {
        return;
      }
      const field = teacherSourceField.getAttribute('data-field');
      if (!field) {
        return;
      }
      this.service.updateTeacherSourceField(field, teacherSourceField.value);
      this.syncFreeformRecordingForm();
      return;
    }

    const freeformField = event.target.closest('[data-role="freeform-recording-field"]');
    if (freeformField) {
      if (freeformField.tagName === 'SELECT' || freeformField.type === 'checkbox') {
        return;
      }
      const field = freeformField.getAttribute('data-field');
      if (!field) {
        return;
      }
      this.service.updateFreeformRecordingField(field, freeformField.value);
      this.syncFreeformRecordingForm();
    }
  }

  handleRootChange(event) {
    const manualField = event.target.closest('[data-role="manual-recording-field"]');
    if (manualField) {
      const field = manualField.getAttribute('data-field');
      if (!field) {
        return;
      }
      const value = manualField.type === 'checkbox'
        ? manualField.checked
        : manualField.type === 'number'
          ? Number(manualField.value)
          : manualField.value;
      this.service.updateManualRecordingField(field, value);
      this.syncManualRecordingForm();
      return;
    }

    const teacherSourceField = event.target.closest('[data-role="teacher-source-field"]');
    if (teacherSourceField) {
      const field = teacherSourceField.getAttribute('data-field');
      if (!field) {
        return;
      }
      const value = teacherSourceField.type === 'checkbox'
        ? teacherSourceField.checked
        : teacherSourceField.type === 'number'
          ? Number(teacherSourceField.value)
          : teacherSourceField.value;
      this.service.updateTeacherSourceField(field, value);
      this.syncFreeformRecordingForm();
      return;
    }

    const freeformField = event.target.closest('[data-role="freeform-recording-field"]');
    if (freeformField) {
      const field = freeformField.getAttribute('data-field');
      if (!field) {
        return;
      }
      const value = freeformField.type === 'checkbox'
        ? freeformField.checked
        : freeformField.type === 'number'
          ? Number(freeformField.value)
          : freeformField.value;
      this.service.updateFreeformRecordingField(field, value);
      this.syncFreeformRecordingForm();
    }
  }

  isRuntimeRecorderEditing() {
    const recording = this.snapshot?.recording;
    const recordingMode = getRecordingMode(recording);
    if (recordingMode) {
      return false;
    }

    const active = document.activeElement;
    if (!(active instanceof HTMLElement)) {
      return false;
    }
    if (!active.closest('.manual-recorder, .freeform-recorder')) {
      return false;
    }

    const tag = active.tagName;
    if (tag === 'SELECT' || tag === 'TEXTAREA') {
      return true;
    }
    if (tag === 'INPUT') {
      const inputType = (active.getAttribute('type') || 'text').toLowerCase();
      return ['text', 'search', 'number', 'email', 'url', 'tel'].includes(inputType);
    }

    return false;
  }

  syncManualRecordingForm() {
    const container = this.sections.runtime?.querySelector('.manual-recorder');
    const manual = this.snapshot?.recording?.manual;
    if (!container || !manual) {
      return;
    }

    const selectedPreset = getManualCapturePreset(manual.labelPresetId);
    const selectedVariant = getManualCapturePresetVariant(manual.labelPresetId, manual.labelVariantId);
    const generatedLabel = selectedPreset?.id === 'custom' ? '' : (selectedPreset?.labelValue || '');
    const generatedNotes = [selectedPreset?.notesPrefix, selectedVariant?.notes].filter(Boolean).join(', ');

    const presetSelect = container.querySelector('[data-field="labelPresetId"]');
    if (presetSelect) {
      presetSelect.value = manual.labelPresetId || 'custom';
    }

    const variantSelect = container.querySelector('[data-field="labelVariantId"]');
    if (variantSelect) {
      variantSelect.innerHTML = (selectedPreset?.variants || []).map((variant) => `
        <option value="${escapeHtml(variant.id)}" ${String(manual.labelVariantId || selectedPreset?.variants?.[0]?.id || '') === variant.id ? 'selected' : ''}>${escapeHtml(variant.label)}</option>
      `).join('');
      variantSelect.value = manual.labelVariantId || selectedPreset?.variants?.[0]?.id || 'custom';
    }

    const labelInput = container.querySelector('[data-field="label"]');
    if (labelInput) {
      labelInput.placeholder = generatedLabel || 'авто или из каталога';
      if (document.activeElement !== labelInput) {
        labelInput.value = manual.label || '';
      }
    }

    const notesInput = container.querySelector('[data-field="notes"]');
    if (notesInput) {
      notesInput.placeholder = generatedNotes || 'опционально';
      if (document.activeElement !== notesInput) {
        notesInput.value = manual.notes || '';
      }
    }

    const personCountSelect = container.querySelector('[data-field="personCount"]');
    if (personCountSelect) {
      personCountSelect.value = String(manual.personCount ?? 1);
    }

    const motionTypeSelect = container.querySelector('[data-field="motionType"]');
    if (motionTypeSelect) {
      motionTypeSelect.value = String(manual.motionType || '');
    }

    const scenarioHint = container.querySelector('.manual-recorder__selection-note--scenario');
    if (scenarioHint) {
      scenarioHint.textContent = selectedPreset?.id === 'custom'
        ? UI_LOCALE.capture.manualSelectionHintCustom
        : `${UI_LOCALE.capture.manualSelectionHintPreset}: ${selectedPreset.label}${selectedVariant ? ` · ${selectedVariant.label}` : ''}`;
    }
  }

  syncFreeformRecordingForm() {
    const container = this.sections.runtime?.querySelector('.freeform-recorder');
    const freeform = this.snapshot?.recording?.freeform;
    const teacherSource = this.snapshot?.recording?.teacherSource;
    if (!container || !freeform) {
      return;
    }

    const labelInput = container.querySelector('[data-field="label"]');
    if (labelInput && document.activeElement !== labelInput) {
      labelInput.value = freeform.label || '';
    }

    const notesInput = container.querySelector('[data-field="notes"]');
    if (notesInput && document.activeElement !== notesInput) {
      notesInput.value = freeform.notes || '';
    }

    const personCountSelect = container.querySelector('[data-field="personCount"]');
    if (personCountSelect) {
      personCountSelect.value = String(freeform.personCount || '');
    }

    const chunkSecSelect = container.querySelector('[data-field="chunkSec"]');
    if (chunkSecSelect) {
      chunkSecSelect.value = String(freeform.chunkSec || 60);
    }

    const voiceCueToggle = container.querySelector('[data-field="voiceCue"]');
    if (voiceCueToggle) {
      voiceCueToggle.checked = freeform.voiceCue !== false;
    }

    const teacherSourceSelect = container.querySelector('[data-role="teacher-source-field"][data-field="selectedKind"]');
    if (teacherSourceSelect && teacherSource) {
      teacherSourceSelect.value = normalizeTeacherSourceKind(teacherSource.selectedKind);
    }

    const teacherSourceUrlInput = container.querySelector('[data-role="teacher-source-field"][data-field="pixelRtspUrl"]');
    if (teacherSourceUrlInput && teacherSource && document.activeElement !== teacherSourceUrlInput) {
      teacherSourceUrlInput.value = teacherSource.pixelRtspUrl || DEFAULT_PIXEL_RTSP_URL;
    }

    const teacherDeviceInput = container.querySelector('[data-role="teacher-source-field"][data-field="macDevice"]');
    if (teacherDeviceInput && teacherSource && document.activeElement !== teacherDeviceInput) {
      teacherDeviceInput.value = teacherSource.macDevice || DEFAULT_MAC_CAMERA_DEVICE;
    }

    const roleHint = container.querySelector('.freeform-recorder__selection-note--role');
    if (roleHint) {
      roleHint.textContent = `${UI_LOCALE.capture.freeformRoleHint}: ${getFreeformRoleHintText(freeform.personCount || 1)}`;
    }
  }

  ensureForensicSelectionVisible() {
    const orderedRuns = this.getOrderedForensicRuns(this.getForensicManifest());
    if (!orderedRuns.length) {
      return null;
    }

    const selectedRunId = this.snapshot?.forensics?.selectedRunId;
    if (selectedRunId && orderedRuns.some((item) => item.run_id === selectedRunId)) {
      return selectedRunId;
    }

    const nextRunId = orderedRuns[0].run_id;
    this.pendingForensicScrollRunId = nextRunId;
    void this.service.selectForensicRun(nextRunId);
    return nextRunId;
  }

  isForensicsKeyboardContext() {
    return this.tabManager?.getActiveTab() === 'forensics';
  }

  getForensicManifest() {
    return Array.isArray(this.snapshot?.forensics?.manifest) ? this.snapshot.forensics.manifest : [];
  }

  getOrderedForensicRuns(manifest, options = {}) {
    const {
      viewMode = this.forensicViewMode,
      fateFilter = this.forensicFateFilter,
      query = this.forensicQuery
    } = options;
    const visibleRuns = this.getVisibleForensicRuns(manifest, { fateFilter, query });
    if (viewMode !== 'fate') {
      return visibleRuns;
    }

    return FATE_GROUPS
      .filter((item) => item.id !== 'all')
      .flatMap((group) => visibleRuns.filter((item) => (item.fate_group || 'incomplete') === group.id));
  }

  getFirstVisibleForensicRunId(manifest, options = {}) {
    return this.getOrderedForensicRuns(manifest, options)[0]?.run_id || null;
  }

  prefetchForensicBucketTarget(nextGroup) {
    const manifest = this.getForensicManifest();
    if (!manifest.length) {
      return null;
    }

    const targetRunId = this.getFirstVisibleForensicRunId(manifest, { fateFilter: nextGroup });
    if (!targetRunId) {
      return null;
    }

    void this.service.prefetchForensicRuns([targetRunId]);
    return targetRunId;
  }

  prefetchForensicModeTarget(nextView) {
    const manifest = this.getForensicManifest();
    if (!manifest.length) {
      return null;
    }

    const currentTargetRunId = this.getFirstVisibleForensicRunId(manifest);
    const nextTargetRunId = this.getFirstVisibleForensicRunId(manifest, { viewMode: nextView });
    if (!nextTargetRunId || nextTargetRunId === currentTargetRunId) {
      return null;
    }

    void this.service.prefetchForensicRuns([nextTargetRunId]);
    return nextTargetRunId;
  }

  clearForensicSearchPrefetch() {
    if (!this.forensicSearchPrefetchTimer) {
      return;
    }
    clearTimeout(this.forensicSearchPrefetchTimer);
    this.forensicSearchPrefetchTimer = null;
  }

  scheduleForensicSearchPrefetch() {
    this.clearForensicSearchPrefetch();
    if (!this.snapshot) {
      return;
    }

    this.forensicSearchPrefetchTimer = setTimeout(() => {
      this.forensicSearchPrefetchTimer = null;
      const targetRunId = this.getFirstVisibleForensicRunId(this.getForensicManifest());
      if (!targetRunId) {
        return;
      }
      void this.service.prefetchForensicRuns([targetRunId]);
    }, FORENSIC_SEARCH_PREFETCH_DELAY_MS);
  }

  applyForensicViewMode(nextView) {
    if (!nextView || nextView === this.forensicViewMode) {
      return;
    }
    const prefetchedRunId = this.prefetchForensicModeTarget(nextView);
    this.forensicViewMode = nextView;
    if (this.snapshot) {
      const selectedRunId = this.ensureForensicSelectionVisible();
      this.pendingForensicScrollRunId = selectedRunId || prefetchedRunId || this.snapshot?.forensics?.selectedRunId || null;
      this.renderForensics();
    }
  }

  applyForensicFateFilter(nextGroup) {
    const normalizedGroup = nextGroup || 'all';
    if (normalizedGroup === this.forensicFateFilter) {
      return;
    }
    const prefetchedRunId = this.prefetchForensicBucketTarget(normalizedGroup);
    this.forensicFateFilter = normalizedGroup;
    if (this.snapshot) {
      const selectedRunId = this.ensureForensicSelectionVisible();
      this.pendingForensicScrollRunId = selectedRunId || prefetchedRunId || this.snapshot?.forensics?.selectedRunId || null;
      this.renderForensics();
    }
  }

  navigateForensicRuns(step) {
    const orderedRuns = this.getOrderedForensicRuns(this.getForensicManifest());
    if (!orderedRuns.length) {
      return;
    }

    const selectedRunId = this.snapshot?.forensics?.selectedRunId;
    const currentIndex = orderedRuns.findIndex((item) => item.run_id === selectedRunId);
    const fallbackIndex = step > 0 ? 0 : orderedRuns.length - 1;
    const baseIndex = currentIndex === -1 ? fallbackIndex : currentIndex;
    const nextIndex = (baseIndex + step + orderedRuns.length) % orderedRuns.length;
    const nextRunId = orderedRuns[nextIndex]?.run_id;
    if (!nextRunId) {
      return;
    }

    this.pendingForensicScrollRunId = nextRunId;
    void this.service.selectForensicRun(nextRunId);
  }

  getForensicPrefetchTargets(orderedRuns, selectedRunId) {
    if (!orderedRuns.length || !selectedRunId) {
      return [];
    }

    const currentIndex = orderedRuns.findIndex((item) => item.run_id === selectedRunId);
    if (currentIndex === -1) {
      return [];
    }

    return [-1, 1]
      .map((offset) => orderedRuns[currentIndex + offset]?.run_id)
      .filter(Boolean);
  }

  scheduleForensicPrefetch(orderedRuns, selectedRunId) {
    const targets = this.getForensicPrefetchTargets(orderedRuns, selectedRunId);
    if (!targets.length) {
      return;
    }
    void this.service.prefetchForensicRuns(targets);
  }

  toggleForensicViewMode() {
    this.applyForensicViewMode(this.forensicViewMode === 'fate' ? 'time' : 'fate');
  }

  handleGlobalKeydown(event) {
    if (!this.isForensicsKeyboardContext()) {
      return;
    }
    if (event.defaultPrevented || event.metaKey || event.ctrlKey || event.altKey) {
      return;
    }
    if (isTextEditingTarget(event.target)) {
      return;
    }

    const key = event.key;
    const lowerKey = key.toLowerCase();

    if (key === 'ArrowDown' || lowerKey === 'j') {
      event.preventDefault();
      this.navigateForensicRuns(1);
      return;
    }

    if (key === 'ArrowUp' || lowerKey === 'k') {
      event.preventDefault();
      this.navigateForensicRuns(-1);
      return;
    }

    if (lowerKey === 'm') {
      event.preventDefault();
      this.toggleForensicViewMode();
      return;
    }

    const nextGroup = FATE_GROUP_HOTKEYS[key];
    if (nextGroup) {
      event.preventDefault();
      this.applyForensicFateFilter(nextGroup);
    }
  }

  syncForensicRunScroll(selectedRunId) {
    if (!selectedRunId || !this.sections.forensics) {
      return;
    }
    const list = this.sections.forensics.querySelector('.forensic-run-list');
    const escapedRunId = typeof CSS !== 'undefined' && typeof CSS.escape === 'function'
      ? CSS.escape(selectedRunId)
      : selectedRunId.replaceAll('\\', '\\\\').replaceAll('"', '\\"');
    const activeCard = this.sections.forensics.querySelector(`[data-forensic-run-id="${escapedRunId}"]`);
    if (!list || !activeCard) {
      return;
    }

    activeCard.scrollIntoView({
      block: 'nearest',
      inline: 'nearest'
    });
  }

  cacheElements() {
    this.sections = {
      overview: this.root.querySelector('[data-region="overview"]'),
      errors: this.root.querySelector('[data-region="errors"]'),
      live: this.root.querySelector('#live'),
      signal: this.root.querySelector('#signal'),
      runtime: this.root.querySelector('#runtime'),
      labeling: this.root.querySelector('#labeling'),
      model: this.root.querySelector('#model'),
      forensics: this.root.querySelector('#forensics'),
      validation: this.root.querySelector('#validation'),
      fp2: this.root.querySelector('#fp2')
    };
  }

  renderShell() {
    this.root.innerHTML = `
      <div class="operator-shell">
        <header class="operator-header">
          <div class="operator-header__copy">
            <div class="eyebrow">${escapeHtml(UI_LOCALE.shell.eyebrow)}</div>
            <h1>${escapeHtml(UI_LOCALE.shell.title)}</h1>
            <p>
              ${escapeHtml(UI_LOCALE.shell.subtitle)}
            </p>
          </div>
          <div class="operator-header__stack" data-region="overview"></div>
        </header>

        <div class="operator-alerts" data-region="errors"></div>

        <nav class="nav-tabs">
          ${AGENT7_OPERATOR_TRUTH.informationArchitecture.map((item, index) => `
            <button type="button" class="nav-tab ${index === 0 ? 'active' : ''}" data-tab="${item.id}">
              <span class="nav-tab__label">${escapeHtml(item.label)}</span>
              <span class="nav-tab__meta">${escapeHtml(UI_LOCALE.roles[item.role] || displayToken(item.role))}</span>
            </button>
          `).join('')}
        </nav>

        <main class="operator-main">
          ${AGENT7_OPERATOR_TRUTH.informationArchitecture.map((item, index) => `
            <section id="${item.id}" class="tab-content ${index === 0 ? 'active' : ''}"></section>
          `).join('')}
        </main>
      </div>
    `;
  }

  renderSnapshot() {
    this.renderOverview();
    this.renderErrors();
    this.renderLive();
    this.renderSignal();
    if (!this.isRuntimeRecorderEditing()) {
      this.renderRuntime();
    }
    this.renderLabeling();
    this.renderForensics();
    this.renderValidation();
    this.renderModel();
    this.renderFp2();
  }

  renderOverview() {
    const snapshot = this.snapshot;
    const trust = snapshot?.live?.trust || { tone: 'neutral', label: 'booting', summary: 'Идёт загрузка live-runtime…' };
    const topology = snapshot?.live?.topology || {};
    const primaryRuntime = snapshot?.live?.primaryRuntime || {};
    const poseSurface = snapshot?.live?.poseSurface || {
      tone: 'neutral',
      label: 'No data',
      summary: 'pose snapshot ещё не загружен',
      detail: 'оператор видит только CSI/runtime слой'
    };
    const shadowDisagreement = snapshot?.live?.shadowDisagreement || {};
    const trackBShadow = snapshot?.live?.trackBShadow || {};
    const v15Shadow = snapshot?.live?.v8Shadow || snapshot?.live?.v7Shadow || snapshot?.live?.v15Shadow || {};
    const v27Binary7NodeShadow = snapshot?.live?.v27Binary7NodeShadow || {};
    const zoneCalibrationShadow = snapshot?.live?.zoneCalibrationShadow || {};
    const fewshotCalibration = snapshot?.recording?.fewshotCalibration || {};
    const garageRatioV2Shadow = snapshot?.live?.garageRatioV2Shadow || {};
    const runtimeView = buildRuntimeView(
      primaryRuntime,
      trackBShadow,
      v15Shadow,
      v27Binary7NodeShadow,
      garageRatioV2Shadow,
      this.runtimeViewSelection
    );
    const zoneGate = buildDoorCenterCalibrationGate(zoneCalibrationShadow, fewshotCalibration);
    const topologyLabel = getTopologyHeadline(topology, primaryRuntime);
    const sessionId = getRuntimeSessionText(snapshot);
    const csiRaw = snapshot?.csi || {};
    const productionBinary = csiRaw.binary || primaryRuntime.binary || shadowDisagreement.primaryBinary || 'unknown';
    const productionZone = csiRaw.target_zone || csiRaw.zone || primaryRuntime.targetZone || runtimeView.targetZone || 'unknown';
    const productionBinaryConfidence = csiRaw.binary_confidence ?? primaryRuntime.binaryConfidence ?? shadowDisagreement.primaryBinaryConfidence ?? null;
    const productionZoneSource = csiRaw.zone_source || primaryRuntime.zoneSource || 'unknown';
    const liveBinaryLabel = displayMaybeToken(productionBinary);
    const liveZoneLabel = displayMaybeToken(productionZone);
    const activeBackend = csiRaw.decision_model_backend || 'unknown';
    const modelCalloutHtml = this._renderModelCalloutCard(activeBackend, csiRaw);

    this.sections.overview.innerHTML = `
      <div class="summary-stack">
        <div class="summary-card ${toneClass(trust.tone)}">
          <div class="summary-card__label">Доверие</div>
          <div class="summary-card__value">${escapeHtml(displayToken(trust.label))}</div>
          <div class="summary-card__meta">${escapeHtml(trust.summary)}</div>
        </div>
        <div class="summary-card tone-info">
          <div class="summary-card__label">Live verdict</div>
          <div class="summary-card__value">${escapeHtml(String(liveBinaryLabel || 'unknown')).toUpperCase()}</div>
          <div class="summary-card__meta">
            binary ${escapeHtml(liveBinaryLabel)} / ${escapeHtml(formatPercent(productionBinaryConfidence, 0))}
            <br>zone ${escapeHtml(liveZoneLabel)} / ${escapeHtml(productionZoneSource)}${primaryRuntime.n02RssiEma != null ? ` / RSSI ${formatNumber(primaryRuntime.n02RssiEma, 1)}` : ''}
          </div>
        </div>
        <div class="summary-card tone-neutral">
          <div class="summary-card__label">Runtime-сессия</div>
          <div class="summary-card__value">${escapeHtml(sessionId)}</div>
          <div class="summary-card__meta">Старт ${escapeHtml(getRuntimeStartText(snapshot))} / топология ${escapeHtml(topologyLabel)}</div>
        </div>
        <div class="summary-card ${toneClass(poseSurface.tone)}">
          <div class="summary-card__label">Pose / FP2</div>
          <div class="summary-card__value">${escapeHtml(String(poseSurface.label || 'No data').toUpperCase())}</div>
          <div class="summary-card__meta">
            ${escapeHtml(poseSurface.summary || 'нет данных')}
            <br>${escapeHtml(poseSurface.detail || 'детали не переданы')}
          </div>
        </div>
      </div>
      ${modelCalloutHtml}
    `;
  }

  _renderModelCalloutCard(activeBackend, csiRaw) {
    if (!activeBackend || activeBackend === 'unknown') {
      return '';
    }

    const backendLower = activeBackend.toLowerCase();
    let activeStepKey = null;
    let displayName = activeBackend;
    let badgeClass = 'model-badge-legacy';

    if (backendLower.includes('truth_tvar')) {
      activeStepKey = 'truth_tvar';
      displayName = 'Truth TVAR v2';
      badgeClass = 'model-badge-truth';
    } else if (backendLower.includes('v8_empty') || backendLower.includes('empty_priority')) {
      activeStepKey = 'v8_empty';
      displayName = 'V8 Empty Priority Guard';
      badgeClass = 'model-badge-warn';
    } else if (backendLower.includes('track_b')) {
      activeStepKey = 'track_b';
      displayName = 'Track B Candidate';
      badgeClass = 'model-badge-legacy';
    } else if (backendLower.includes('v60') || backendLower.includes('mesh')) {
      activeStepKey = 'v60';
      displayName = 'V60 Mesh Binary';
      badgeClass = 'model-badge-legacy';
    } else if (backendLower.includes('v48') || backendLower.includes('random_forest')) {
      activeStepKey = 'v48';
      displayName = 'V48 Random Forest';
      badgeClass = 'model-badge-legacy';
    } else if (backendLower.includes('hysteresis')) {
      activeStepKey = 'hysteresis';
      displayName = 'Hysteresis Gate';
      badgeClass = 'model-badge-legacy';
    }

    const productionBinary = displayMaybeToken(csiRaw.binary || 'unknown');
    const productionZone = displayMaybeToken(csiRaw.target_zone || csiRaw.zone || csiRaw.binary || 'unknown');
    const binaryConfidence = Number.isFinite(Number(csiRaw.binary_confidence)) ? Number(csiRaw.binary_confidence) : null;
    const zoneSource = csiRaw.zone_source || 'unknown';
    const metaLines = [
      `Backend: ${escapeHtml(activeBackend)}`,
      `binary: ${escapeHtml(productionBinary)}${binaryConfidence != null ? ` / ${escapeHtml(formatPercent(binaryConfidence, 0))}` : ''}`,
      `zone: ${escapeHtml(productionZone)} / ${escapeHtml(zoneSource)}`
    ];

    return `
      <div class="model-callout-card">
        <div class="model-callout-card__eyebrow">\u0410\u043A\u0442\u0438\u0432\u043D\u0430\u044F \u043C\u043E\u0434\u0435\u043B\u044C \u043F\u0440\u0438\u043D\u044F\u0442\u0438\u044F \u0440\u0435\u0448\u0435\u043D\u0438\u044F</div>
        <div class="model-callout-card__headline">
          ${escapeHtml(displayName)}
          <span class="${badgeClass}">${activeStepKey === 'truth_tvar' ? 'TRUTH' : activeStepKey === 'v8_empty' ? 'GUARD' : 'ACTIVE'}</span>
        </div>
        <div class="model-callout-card__meta">${metaLines.join(' &middot; ')}</div>
      </div>
    `;
  }

  renderErrors() {
    const errorEntries = Object.entries(this.snapshot?.errors || {}).filter(([, value]) => value);
    if (!errorEntries.length) {
      this.sections.errors.innerHTML = '';
      return;
    }

    this.sections.errors.innerHTML = `
      <div class="panel panel--danger">
        <div class="panel__eyebrow">Проблемы live-fetch</div>
        <div class="error-list">
          ${errorEntries.map(([key, value]) => `
            <div class="error-chip">
              <strong>${escapeHtml(key)}</strong>
              <span>${escapeHtml(value)}</span>
            </div>
          `).join('')}
        </div>
      </div>
    `;
  }

  renderLive() {
    const snapshot = this.snapshot;
    if (!snapshot) {
      return;
    }

    const primaryRuntime = snapshot.live.primaryRuntime || {};
    const shadowDisagreement = snapshot.live.shadowDisagreement || {};
    const secondaryRuntime = snapshot.live.secondaryRuntime || {};
    const trackBShadow = snapshot.live.trackBShadow || {};
    const v15Shadow = snapshot.live.v8Shadow || snapshot.live.v7Shadow || snapshot.live.v15Shadow || {};
    const v27Binary7NodeShadow = snapshot.live.v27Binary7NodeShadow || {};
    const garageRatioV2Shadow = snapshot.live.garageRatioV2Shadow || {};
    const v19Shadow = snapshot.live.v19Shadow || {};
    const zoneCalibrationShadow = snapshot.live.zoneCalibrationShadow || {};
    const baselineStatus = snapshot.live.baselineStatus || {};
    const signalQuality = snapshot.live.signalQuality || {};
    const poseSurface = snapshot.live.poseSurface || {
      tone: 'neutral',
      label: 'No data',
      summary: 'pose snapshot ещё не загружен',
      detail: 'оператор видит только CSI/runtime слой'
    };
    const fewshotCalibration = snapshot.recording?.fewshotCalibration || {};
    const runtimeView = buildRuntimeView(
      primaryRuntime,
      trackBShadow,
      v15Shadow,
      v27Binary7NodeShadow,
      garageRatioV2Shadow,
      this.runtimeViewSelection
    );
    const zoneGate = buildDoorCenterCalibrationGate(zoneCalibrationShadow, fewshotCalibration);
    const support = snapshot.live.supportPath;
    const trust = snapshot.live.trust;
    const failureSignal = snapshot.live.failureSignal;
    const lastEvent = snapshot.live.lastMeaningfulEvent;
    const topology = snapshot.live.topology;
    const nodes = topology.nodes || [];
    const aggregateNodeNote = getAggregateNodeNote(nodes, primaryRuntime);
    const topologyHeadline = getTopologyHeadline(topology, primaryRuntime);

    const trackBStatusToken = String(
      trackBShadow.predictedClass
        ? trackBShadow.predictedClass.toLowerCase()
        : (trackBShadow.status || 'unknown')
    );
    const trackBProbabilities = [
      ['EMPTY', trackBShadow.emptyProbability],
      ['STATIC', trackBShadow.staticProbability],
      ['MOTION', trackBShadow.motionProbability]
    ].filter(([, value]) => value != null);
    const v15StatusToken = String(
      v15Shadow.predictedClass
        ? v15Shadow.predictedClass.toLowerCase()
        : (v15Shadow.status || 'unknown')
    );
    const v15Probabilities = [
      ['EMPTY', v15Shadow.emptyProbability],
      ['STATIC', v15Shadow.staticProbability],
      ['MOTION', v15Shadow.motionProbability]
    ].filter(([, value]) => value != null);
    const v19StatusToken = String(
      v19Shadow.predictedClass
        ? v19Shadow.predictedClass.toLowerCase()
        : (v19Shadow.status || 'unknown')
    );
    const v19Probabilities = [
      ['EMPTY', v19Shadow.emptyProbability],
      ['STATIC', v19Shadow.staticProbability],
      ['MOTION', v19Shadow.motionProbability]
    ].filter(([, value]) => value != null);
    const v27BinaryStatusToken = String(v27Binary7NodeShadow.binary || v27Binary7NodeShadow.status || 'unknown');
    const v27BinaryProbabilities = [
      ['EMPTY', v27Binary7NodeShadow.emptyProbability],
      ['OCCUPIED', v27Binary7NodeShadow.occupiedProbability]
    ].filter(([, value]) => value != null);
    const binary7NodeCandidateName = v27Binary7NodeShadow.candidateName || v27Binary7NodeShadow.track || 'V42 binary balanced';
    const liveBinaryLabel = displayMaybeToken(shadowDisagreement.primaryBinary || primaryRuntime.binary || 'unknown');
    const liveZoneLabel = displayMaybeToken(primaryRuntime.targetZone || 'unknown');
    const liveShadowLabel = displayMaybeToken(shadowDisagreement.shadowBinary || 'unknown');

    this.sections.live.innerHTML = `
      <section class="hero-panel">
        <div class="hero-panel__copy">
          <div class="eyebrow">Live-консоль</div>
          <h2>${escapeHtml(String(displayMaybeToken(runtimeView.state || 'unknown')).toUpperCase())}</h2>
          <p>
            ${escapeHtml(runtimeView.label)} сейчас <strong>${escapeHtml(displayMaybeToken(runtimeView.state || 'unknown'))}</strong>
            с уверенностью <strong>${escapeHtml(formatPercent(runtimeView.confidence, 0))}</strong>,
            support‑path сейчас <strong>${escapeHtml(getSupportStatusText(support))}</strong>,
            а текущий кадр читается как <strong>${escapeHtml(displayToken(trust.label))}</strong>.
          </p>
          <div class="hero-tags">
            <span class="tag ${toneClass(trust.tone)}">${escapeHtml(trust.summary)}</span>
            <span class="tag tone-info">${escapeHtml(runtimeView.routeLabel)} / уверенность ${escapeHtml(formatPercent(runtimeView.confidence, 0))}</span>
            <span class="tag ${toneClass(zoneGate.tone)}">дверь‑центр ${escapeHtml(zoneGate.state)} / ${escapeHtml(zoneGate.detail)}</span>
            <span class="tag ${toneClass(shadowDisagreement.tone)}">shadow ${escapeHtml(getShadowDisagreementLabel(shadowDisagreement))} / ${escapeHtml(shadowDisagreement.summary || 'данные не переданы')}</span>
            <span class="tag ${toneClass(poseSurface.tone)}">pose/fp2 ${escapeHtml(poseSurface.label)} / ${escapeHtml(poseSurface.summary || 'нет данных')}</span>
            <span class="tag tone-info">support‑path ${escapeHtml(getSupportStatusText({ ...support, status: support.candidateStatus || support.status }))}</span>
          </div>
        </div>
        <div class="hero-panel__rail">
          <div class="hero-stat">
            <span>Последнее значимое событие</span>
            <strong>${escapeHtml(displayToken(lastEvent.label))}</strong>
            <small>${escapeHtml(formatLiveEventDetail(lastEvent.detail))} / ${escapeHtml(formatRelativeTime(lastEvent.ageSec))}</small>
          </div>
          <div class="hero-stat">
            <span>${escapeHtml(runtimeView.label)} / окно</span>
            <strong>${escapeHtml(formatRelativeTime(runtimeView.windowAgeSec))}</strong>
            <small>${escapeHtml(formatNumber(runtimeView.nodesActive))}/${escapeHtml(formatNumber(runtimeView.totalNodes || DEFAULT_VISIBLE_NODE_COUNT))} узлов / ${escapeHtml(formatNumber(runtimeView.packetsPerSecond, 1))} pps</small>
          </div>
          <div class="hero-stat">
            <span>Поза failure-family</span>
            <strong>${escapeHtml(displayToken(failureSignal.label))}</strong>
            <small>${escapeHtml(failureSignal.summary)}</small>
          </div>
        </div>
      </section>

      <div class="surface-grid surface-grid--four">
        <article class="panel">
          <div class="panel__eyebrow">Операторский digest</div>
          <div class="panel__headline">${escapeHtml(String(liveBinaryLabel || 'unknown'))} · ${escapeHtml(liveZoneLabel)}</div>
          <div class="kv-list">
            <div class="kv"><span>Binary</span><strong>${escapeHtml(liveBinaryLabel)} / ${escapeHtml(formatPercent(shadowDisagreement.primaryBinaryConfidence ?? primaryRuntime.binaryConfidence, 0))}</strong></div>
            <div class="kv"><span>Zone</span><strong>${escapeHtml(liveZoneLabel)} / ${escapeHtml(primaryRuntime.zoneSource || 'unknown')}${primaryRuntime.n02RssiEma != null ? ` / RSSI ${formatNumber(primaryRuntime.n02RssiEma, 1)}` : ''}</strong></div>
            <div class="kv"><span>Shadow</span><strong>${escapeHtml(liveShadowLabel)} / ${escapeHtml(formatPercent(shadowDisagreement.shadowBinaryConfidence, 0))} / ${escapeHtml(getShadowDisagreementLabel(shadowDisagreement))}</strong></div>
            <div class="kv"><span>Disagreement</span><strong>${escapeHtml(shadowDisagreement.binaryDisagreement ? 'есть' : 'нет')} / ${escapeHtml(shadowDisagreement.summary || 'данные не переданы')}</strong></div>
            <div class="kv"><span>Runtime</span><strong>${escapeHtml(runtimeView.label)} / ${escapeHtml(runtimeView.routeLabel)} / ${escapeHtml(runtimeView.running ? UI_LOCALE.common.running : 'offline')}</strong></div>
            <div class="kv"><span>Узлы / packets</span><strong>${escapeHtml(formatNumber(runtimeView.nodesActive))}/${escapeHtml(formatNumber(runtimeView.totalNodes || DEFAULT_VISIBLE_NODE_COUNT))} / ${escapeHtml(formatNumber(runtimeView.packetsInWindow))}</strong></div>
            <div class="kv"><span>PPS / возраст окна</span><strong>${escapeHtml(formatNumber(runtimeView.packetsPerSecond, 1))} / ${escapeHtml(formatRelativeTime(runtimeView.windowAgeSec))}</strong></div>
            <div class="kv"><span>Model</span><strong>${escapeHtml(runtimeView.modelVersion || 'unknown')} / ${escapeHtml(runtimeView.modelLoaded ? 'модель загружена' : 'модель не загружена')}</strong></div>
            <div class="kv"><span>Zone model</span><strong>${escapeHtml(primaryRuntime.zoneModel || 'unknown')} / ${primaryRuntime.zoneProbabilities ? Object.entries(primaryRuntime.zoneProbabilities).map(([k, v]) => `${k}: ${(v * 100).toFixed(0)}%`).join(' / ') : 'нет вероятностей'}</strong></div>
            <div class="kv"><span>Pose / FP2</span><strong>${escapeHtml(poseSurface.label || 'No data')} / ${escapeHtml(poseSurface.summary || 'нет данных')}</strong></div>
          </div>
          <div class="panel__footer">${escapeHtml(runtimeView.summary)} / ${escapeHtml(zoneGate.state)} · ${escapeHtml(zoneGate.detail)}</div>
        </article>

        <article class="panel">
          <div class="panel__eyebrow">Track B (тень)</div>
          <div class="panel__headline">${escapeHtml(displayMaybeToken(trackBStatusToken))}</div>
          <div class="kv-list">
            <div class="kv"><span>Роль</span><strong>${escapeHtml(displayToken(trackBShadow.track || 'B_v1'))}</strong></div>
            <div class="kv"><span>Статус</span><strong>${escapeHtml(displayMaybeToken(trackBShadow.status || 'unknown'))} / ${escapeHtml(trackBShadow.loaded ? 'модель загружена' : 'модель не загружена')}</strong></div>
            <div class="kv"><span>Узлы / окно</span><strong>${escapeHtml(formatNumber(trackBShadow.nodesWithData))}/${escapeHtml(formatNumber(runtimeView.totalNodes || DEFAULT_VISIBLE_NODE_COUNT))} / ${escapeHtml(formatRelativeTime(primaryRuntime.windowAgeSec))}</strong></div>
            <div class="kv"><span>Время inference</span><strong>${escapeHtml(formatNumberWithUnit(trackBShadow.inferenceMs, { digits: 2, unit: ' ms', missing: 'ещё нет окна' }))}</strong></div>
            <div class="kv"><span>Боевой маршрут</span><strong>только shadow / Track A остаётся боевым</strong></div>
          </div>
          <div class="metric-bars">
            ${trackBProbabilities.length
              ? trackBProbabilities.map(([label, value]) => renderMetricBar(label, Number(value) || 0)).join('')
              : '<div class="muted">Track B ещё не прислал вероятности.</div>'}
          </div>
          <div class="panel__footer">Этот блок нужен только для тестов: Track B считает параллельно и не подменяет production verdict.</div>
        </article>

        <article class="panel">
          <div class="panel__eyebrow">V8 F2‑spectral кандидат</div>
          <div class="panel__headline">${escapeHtml(displayMaybeToken(v15StatusToken))}</div>
          <div class="kv-list">
            <div class="kv"><span>Роль</span><strong>V8 shadow / только тест</strong></div>
            <div class="kv"><span>Статус</span><strong>${escapeHtml(displayMaybeToken(v15Shadow.status || 'unknown'))} / ${escapeHtml(v15Shadow.loaded ? 'модель загружена' : 'модель не загружена')}</strong></div>
            <div class="kv"><span>Буфер / warmup</span><strong>${escapeHtml(formatNumber(v15Shadow.bufferDepth))}/7 / ${escapeHtml(formatNumber(v15Shadow.warmupRemaining))} до ready</strong></div>
            <div class="kv"><span>Время inference</span><strong>${escapeHtml(formatNumberWithUnit(v15Shadow.inferenceMs, { digits: 2, unit: ' ms', missing: 'ещё нет seq=7' }))}</strong></div>
            <div class="kv"><span>Согласование с V5</span><strong>${escapeHtml(v15Shadow.agreeCoarse == null ? 'ещё нет verdict' : (v15Shadow.agreeCoarse ? 'coarse согласован' : 'coarse расходится'))} / ${escapeHtml(v15Shadow.agreeBinary == null ? 'binary n/a' : (v15Shadow.agreeBinary ? 'binary согласован' : 'binary расходится'))}</strong></div>
          </div>
          <div class="metric-bars">
            ${v15Probabilities.length
              ? v15Probabilities.map(([label, value]) => renderMetricBar(label, Number(value) || 0)).join('')
              : '<div class="muted">V8 ещё греет буфер и не отдал coarse-вероятности.</div>'}
          </div>
          <div class="panel__footer">Это текущий самый сильный замороженный кандидат. UI показывает его отдельно в shadow‑режиме, без смены боевого routing с V5.</div>
        </article>

        <article class="panel">
          <div class="panel__eyebrow">V19 shadow по V23-features</div>
          <div class="panel__headline">${escapeHtml(displayMaybeToken(v19StatusToken))}</div>
          <div class="kv-list">
            <div class="kv"><span>Роль</span><strong>V19 shadow / V23 phase+baseline+quality</strong></div>
            <div class="kv"><span>Статус</span><strong>${escapeHtml(displayMaybeToken(v19Shadow.status || 'unknown'))} / ${escapeHtml(v19Shadow.loaded ? 'модель загружена' : 'модель не загружена')}</strong></div>
            <div class="kv"><span>Буфер / warmup</span><strong>${escapeHtml(formatNumber(v19Shadow.bufferDepth))}/7 / ${escapeHtml(formatNumber(v19Shadow.warmupRemaining))} до ready</strong></div>
            <div class="kv"><span>Время inference</span><strong>${escapeHtml(formatNumberWithUnit(v19Shadow.inferenceMs, { digits: 2, unit: ' ms', missing: 'ещё нет seq=7' }))}</strong></div>
            <div class="kv"><span>Согласование с V5</span><strong>${escapeHtml(v19Shadow.agreeCoarse == null ? 'ещё нет verdict' : (v19Shadow.agreeCoarse ? 'coarse согласован' : 'coarse расходится'))} / ${escapeHtml(v19Shadow.agreeBinary == null ? 'binary n/a' : (v19Shadow.agreeBinary ? 'binary согласован' : 'binary расходится'))}</strong></div>
            <div class="kv"><span>Empty gate</span><strong style="color: ${v19Shadow.emptyGateState ? '#f0c040' : '#6c8'};">${v19Shadow.emptyGateState ? 'ON → EMPTY' + (v19Shadow.rawPredictedClass ? ' (raw: ' + escapeHtml(v19Shadow.rawPredictedClass) + ')' : '') : 'OFF'} [${v19Shadow.gateConsecBelow}↓ ${v19Shadow.gateConsecAbove}↑ / N=4]</strong></div>
            <div class="kv"><span>Отклонение от baseline</span><strong>amp=${escapeHtml(formatNumber(v19Shadow.blAmpDevMax, 2))}σ / sc=${escapeHtml(formatNumber(v19Shadow.blScVarDevMax, 2))}σ (thr: 1.2/1.3)</strong></div>
          </div>
          <div class="metric-bars">
            ${v19Probabilities.length
              ? v19Probabilities.map(([label, value]) => renderMetricBar(label, Number(value) || 0)).join('')
              : '<div class="muted">V19 ещё греет буфер и не отдал coarse-вероятности.</div>'}
          </div>
          <div class="panel__footer">V23 features: enhanced phase, baseline deviation, signal quality gates. Macro F1=0.9467, STATIC F1=0.8657. Shadow-only, production остаётся на V5.</div>
        </article>

        <article class="panel">
          <div class="panel__eyebrow">${escapeHtml(binary7NodeCandidateName)}</div>
          <div class="panel__headline">${escapeHtml(displayMaybeToken(v27BinaryStatusToken))}</div>
          <div class="kv-list">
            <div class="kv"><span>Источник payload</span><strong>${escapeHtml(v27Binary7NodeShadow.sourceField || 'v26_shadow')}</strong></div>
            <div class="kv"><span>Статус</span><strong>${escapeHtml(displayMaybeToken(v27Binary7NodeShadow.status || 'unknown'))} / ${escapeHtml(v27Binary7NodeShadow.loaded ? 'модель загружена' : 'модель не загружена')}</strong></div>
            <div class="kv"><span>Binary вердикт</span><strong>${escapeHtml(displayMaybeToken(v27Binary7NodeShadow.binary || 'unknown'))}</strong></div>
            <div class="kv"><span>Дверь vs Центр</span><strong>${escapeHtml(zoneGate.state)} / ${escapeHtml(zoneGate.detail)}</strong></div>
            <div class="kv"><span>Threshold / согласие</span><strong>${escapeHtml(formatNumber(v27Binary7NodeShadow.threshold, 3))} / ${escapeHtml(v27Binary7NodeShadow.agreeBinary == null ? 'ещё нет verdict' : (v27Binary7NodeShadow.agreeBinary ? 'совпадает с primary' : 'расходится с primary'))}</strong></div>
            <div class="kv"><span>Время inference</span><strong>${escapeHtml(formatNumberWithUnit(v27Binary7NodeShadow.inferenceMs, { digits: 2, unit: ' ms', missing: 'ещё нет окна' }))}</strong></div>
          </div>
          <div class="metric-bars">
            ${v27BinaryProbabilities.length
              ? v27BinaryProbabilities.map(([label, value]) => renderMetricBar(label, Number(value) || 0)).join('')
              : '<div class="muted">7-node binary кандидат ещё не прислал probability.</div>'}
          </div>
          <div class="panel__footer">В UI этот кандидат показывается отдельно как тестовый binary‑режим, хотя backend пока публикует его через архивный field v26_shadow.</div>
        </article>

        <article class="panel">
          <div class="panel__eyebrow">Текущий support‑path</div>
          <div class="panel__headline">${escapeHtml(getSupportHeadline(support))}</div>
          <div class="kv-list">
            <div class="kv"><span>Статус</span><strong>${escapeHtml(getSupportStatusText(support))}</strong></div>
            <div class="kv"><span>Причина</span><strong>${escapeHtml(getSupportReasonText(support))}</strong></div>
            <div class="kv"><span>Вероятность / threshold</span><strong>${escapeHtml(getSupportProbabilityText(support))} / ${escapeHtml(getSupportThresholdText(support))}</strong></div>
            <div class="kv"><span>Валидность контекста</span><strong>${escapeHtml(displayToken(support.contextValidity || 'unknown'))}</strong></div>
            <div class="kv"><span>Последнее shadow-событие</span><strong>${escapeHtml(getSupportLastEventText(support))}</strong></div>
          </div>
        </article>

        <article class="panel">
          <div class="panel__eyebrow">Разделение truth-слоёв</div>
          <div class="truth-stack">
            <div class="truth-item tone-info">
              <span>Основной runtime</span>
              <strong>motion-only вердикт</strong>
            </div>
            <div class="truth-item tone-warn">
              <span>Support-path</span>
              <strong>entry/exit только как support-сигнал</strong>
            </div>
            <div class="truth-item tone-neutral">
              <span>Форензик-истина</span>
              <strong>карта сбоев по артефактам</strong>
            </div>
          </div>
          <div class="panel__footer">Binary / coarse остаются только экспериментальной диагностикой: ${escapeHtml(displayToken(secondaryRuntime.binary || 'unknown'))} / ${escapeHtml(displayToken(secondaryRuntime.coarse || 'unknown'))}.</div>
        </article>
      </div>

      <div class="surface-grid surface-grid--two">
        <article class="panel">
          <div class="panel__eyebrow">V23: Качество сигнала</div>
          <div class="panel__headline">${signalQuality.available ? 'OK' : 'нет данных'}</div>
          <div class="kv-list">
            <div class="kv"><span>Phase jump max</span><strong>${escapeHtml(formatNumber(signalQuality.phaseJumpMax, 3))} ${signalQuality.phaseJumpMax != null && signalQuality.phaseJumpMax > 0.30 ? '/ GATE' : '/ ok'}</strong></div>
            <div class="kv"><span>Dead SC max</span><strong>${escapeHtml(formatNumber(signalQuality.deadScMax, 3))} ${signalQuality.deadScMax != null && signalQuality.deadScMax > 0.40 ? '/ GATE' : '/ ok'}</strong></div>
            <div class="kv"><span>Amp drift max</span><strong>${escapeHtml(formatNumber(signalQuality.ampDriftMax, 3))} ${signalQuality.ampDriftMax != null && signalQuality.ampDriftMax > 2.0 ? '/ GATE' : '/ ok'}</strong></div>
            <div class="kv"><span>Phase coherence mean</span><strong>${escapeHtml(formatNumber(signalQuality.phaseCoherenceMean, 3))}</strong></div>
          </div>
          <div class="panel__footer">V23 quality gates: phase noise &gt;0.30, dead SC &gt;0.40, amp drift &gt;2.0 подавляют occupied-предсказание.</div>
        </article>

        <article class="panel">
          <div class="panel__eyebrow">V23: Empty baseline калибрация</div>
          <div class="panel__headline">${baselineStatus.calibrated ? 'Откалибровано' : (baselineStatus.captureActive ? 'Захват...' : 'Не откалибровано')}</div>
          <div class="kv-list">
            <div class="kv"><span>Статус</span><strong>${escapeHtml(baselineStatus.calibrated ? 'calibrated' : (baselineStatus.captureActive ? 'capturing' : 'not_calibrated'))}</strong></div>
            <div class="kv"><span>Откалибровано</span><strong>${escapeHtml(baselineStatus.calibratedAt || 'never')}</strong></div>
            <div class="kv"><span>Окон / узел</span><strong>${escapeHtml(formatNumber(baselineStatus.windowsPerNode))}</strong></div>
            <div class="kv"><span>Узлов</span><strong>${escapeHtml(formatNumber(baselineStatus.nodeCount))}</strong></div>
            ${baselineStatus.roomDimensions ? `<div class="kv"><span>Комната</span><strong>${escapeHtml(baselineStatus.roomDimensions)}</strong></div>` : ''}
          </div>
          <div class="panel__footer">Baseline профили используются для deviation-features (отклонение от пустой комнаты) в V19/V23 pipeline.</div>
        </article>
      </div>

      <div class="surface-grid surface-grid--two">
        <article class="panel">
          <div class="panel__eyebrow">Топология</div>
          <div class="topology-map">
            <div class="topology-map__center">
              <span>наблюдаемая топология</span>
              <strong>${escapeHtml(topologyHeadline)}</strong>
            </div>
            ${nodes.map((node, index) => `
              <div class="node-dot node-dot--${index + 1} ${node.active ? 'is-active' : ''} ${node.active == null ? 'is-unknown' : ''} ${node.required ? 'is-required' : ''}">
                <span>${escapeHtml(node.nodeId)}</span>
                <strong>${escapeHtml(getNodeValueText(node))}</strong>
              </div>
            `).join('')}
          </div>
          <div class="panel__footer">
            Обязательная топология ${escapeHtml(getRequiredTopologyText(support))} / наблюдаемая ${escapeHtml(getObservedTopologyText(topology, support, primaryRuntime))}
          </div>
        </article>

        <article class="panel">
          <div class="panel__eyebrow">Активность узлов</div>
          <div class="node-grid">
            ${nodes.map((node) => `
              <div class="node-card ${node.active ? 'is-active' : ''} ${node.active == null ? 'is-unknown' : ''}">
                <div class="node-card__head">
                  <span>${escapeHtml(node.nodeId)}</span>
                  <span class="status-dot ${node.active ? 'status-dot--live' : node.active == null ? 'status-dot--unknown' : 'status-dot--idle'}"></span>
                </div>
                <div class="node-card__value">${escapeHtml(getNodeValueText(node))}</div>
                <div class="node-card__meta">${escapeHtml(getNodeMetaText(node))}</div>
              </div>
            `).join('')}
          </div>
          ${aggregateNodeNote ? `<div class="panel__footer">${escapeHtml(aggregateNodeNote)}</div>` : ''}
        </article>
      </div>

      <div class="surface-grid surface-grid--two">
        <article class="panel">
          <div class="panel__eyebrow">Текущая runtime-сессия</div>
          <div class="timeline">
            <div class="timeline__item">
              <span>Runtime-сессия</span>
              <strong>${escapeHtml(getRuntimeSessionText(snapshot))}</strong>
            </div>
            <div class="timeline__item">
              <span>Старт runtime</span>
              <strong>${escapeHtml(getRuntimeStartText(snapshot))}</strong>
            </div>
            <div class="timeline__item">
              <span>Номер импульса</span>
              <strong>${escapeHtml(formatNumber(support.pulseSeq))}</strong>
            </div>
            <div class="timeline__item">
              <span>Пауза проверки / max active</span>
              <strong>${escapeHtml(getSupportTimingText(support.reviewHoldSec, support))} / ${escapeHtml(getSupportTimingText(support.maxActiveSec, support))}</strong>
            </div>
          </div>
        </article>

        <article class="panel">
          <div class="panel__eyebrow">Карта failure-family</div>
          <div class="family-watch">
            ${AGENT7_OPERATOR_TRUTH.failureFamilies.robustCore.map((item) => `
              <div class="family-chip tone-warn">
                <strong>${escapeHtml(item.label)}</strong>
                <span>${escapeHtml(item.family)}</span>
              </div>
            `).join('')}
            ${AGENT7_OPERATOR_TRUTH.failureFamilies.conditionalSubtype.map((item) => `
              <div class="family-chip tone-neutral">
                <strong>${escapeHtml(item.label)}</strong>
                <span>${escapeHtml(item.family)}</span>
              </div>
            `).join('')}
          </div>
          <div class="panel__footer">${escapeHtml(AGENT7_OPERATOR_TRUTH.contaminationNote.summary)}</div>
        </article>
      </div>
    `;
  }

  _getDoorCenterMapOverlay(live) {
    const candidate = live?.doorCenterCandidateShadow || {};
    const temporal = live?.temporalZoneOverlayShadow || {};
    const state = this._doorCenterMapOverlayState || {
      heldZone: null,
      holdUntilMs: 0,
      centerConfirmStreak: 0,
      lastAgreement: null,
      lastConfidence: null
    };
    const nowMs = Date.now();
    const candidateZone = candidate?.candidateZone || candidate?.zone || null;
    const stableZone = candidate?.stableZone || candidate?.stable_zone || null;
    const agreement = candidate?.agreement || null;
    const confidence = Number.isFinite(Number(candidate?.confidence)) ? Number(candidate.confidence) : null;
    const temporalScore = Number.isFinite(Number(temporal?.directionalScore)) ? Number(temporal.directionalScore) : null;

    if (['door_passage', 'center'].includes(stableZone)) {
      const anchor = stableZone === 'center'
        ? { xMeters: 1.5, yMeters: 3.0 }
        : { xMeters: 1.0, yMeters: 1.0 };
      state.heldZone = stableZone;
      state.holdUntilMs = nowMs + 12000;
      state.centerConfirmStreak = 0;
      state.lastAgreement = agreement;
      state.lastConfidence = confidence;
      this._doorCenterMapOverlayState = state;
      return {
        zone: stableZone,
        xMeters: anchor.xMeters,
        yMeters: anchor.yMeters,
        source: `door_center_candidate_shadow stable (${agreement || 'shadow_live'})`,
        reason: 'backend_stable_zone',
        confidence
      };
    }

    const strongDoor = candidateZone === 'door_passage'
      && (
        ['full', 'prototype_temporal'].includes(agreement)
        || (agreement === 'temporal_threshold' && (temporalScore == null || temporalScore <= -0.05))
      )
      && (confidence == null || confidence >= 0.60);
    const strongCenter = candidateZone === 'center'
      && ['full', 'prototype_temporal'].includes(agreement)
      && (confidence == null || confidence >= 0.72);

    if (strongDoor) {
      state.heldZone = 'door_passage';
      state.holdUntilMs = nowMs + 12000;
      state.centerConfirmStreak = 0;
      state.lastAgreement = agreement;
      state.lastConfidence = confidence;
    } else if (strongCenter) {
      if (state.heldZone === 'door_passage' && state.holdUntilMs > nowMs) {
        state.centerConfirmStreak += 1;
        if (state.centerConfirmStreak >= 4) {
          state.heldZone = null;
          state.holdUntilMs = 0;
          state.centerConfirmStreak = 0;
          state.lastAgreement = null;
          state.lastConfidence = null;
        }
      } else {
        state.heldZone = null;
        state.holdUntilMs = 0;
        state.centerConfirmStreak = 0;
        state.lastAgreement = null;
        state.lastConfidence = null;
      }
    } else if (state.heldZone === 'door_passage' && state.holdUntilMs <= nowMs) {
      state.heldZone = null;
      state.holdUntilMs = 0;
      state.centerConfirmStreak = 0;
      state.lastAgreement = null;
      state.lastConfidence = null;
    }

    this._doorCenterMapOverlayState = state;

    if (state.heldZone === 'door_passage' && state.holdUntilMs > nowMs) {
      return {
        zone: 'door_passage',
        xMeters: 1.0,
        yMeters: 1.0,
        source: `door_center_candidate_shadow hold (${state.lastAgreement || 'full'})`,
        reason: 'door_hold_grace',
        confidence: state.lastConfidence
      };
    }

    return null;
  }

  renderSignal() {
    const snapshot = this.snapshot;
    const signalRenderSignature = JSON.stringify({
      binary: snapshot?.csi?.binary ?? snapshot?.live?.primaryRuntime?.binary ?? null,
      zone: snapshot?.csi?.target_zone ?? snapshot?.csi?.zone ?? snapshot?.live?.primaryRuntime?.targetZone ?? null,
      backend: snapshot?.csi?.decision_model_backend ?? null,
      packets: snapshot?.live?.topology?.liveTotalPackets ?? snapshot?.live?.primaryRuntime?.packetsInWindow ?? null
    });
    if (
      this._isTabActive('signal')
      && this._sdInitialized
      && this.sections.signal?.childElementCount
      && this._lastSignalRenderSignature === signalRenderSignature
    ) {
      this._refreshSignalLiveSurface();
      return;
    }
    this._lastSignalRenderSignature = signalRenderSignature;
    const recording = snapshot.recording || {};
    const recordingStatus = recording.status || {};
    const topology = snapshot.live.topology;
    const motion = snapshot.live.motion;
    const live = snapshot.live;
    const primaryRuntime = snapshot.live.primaryRuntime || {};
    const primaryRuntimeDisplay = snapshot.live.primaryRuntimeDisplay || primaryRuntime;
    const secondaryRuntime = snapshot.live.secondaryRuntime || {};
    const csiRaw = snapshot.csi || {};
    const trackBShadow = snapshot.live.trackBShadow || {};
    const v8Shadow = snapshot.live.v8Shadow || snapshot.live.v7Shadow || snapshot.live.v15Shadow || {};
    const fingerprint = snapshot.live.fingerprint;
    const baseCoordinate = snapshot.live.coordinate || {};
    const productionBinary = csiRaw.binary || primaryRuntime.binary || 'unknown';
    const productionZone = csiRaw.target_zone || csiRaw.zone || primaryRuntime.targetZone || primaryRuntime.zone || productionBinary;
    const productionZoneSource = csiRaw.zone_source || primaryRuntime.zoneSource || 'unknown';
    const productionBinaryConfidence = csiRaw.binary_confidence ?? primaryRuntime.binaryConfidence ?? null;
    const binarySafeOnly = productionZoneSource === 'binary_safe_only';
    const doorCenterMapOverlay = binarySafeOnly ? null : this._getDoorCenterMapOverlay(live);
    const coordinate = doorCenterMapOverlay
      ? {
          ...baseCoordinate,
          xCm: doorCenterMapOverlay.xMeters != null ? doorCenterMapOverlay.xMeters * 100 : baseCoordinate.xCm,
          yCm: doorCenterMapOverlay.yMeters != null ? doorCenterMapOverlay.yMeters * 100 : baseCoordinate.yCm,
          xMeters: doorCenterMapOverlay.xMeters ?? baseCoordinate.xMeters,
          yMeters: doorCenterMapOverlay.yMeters ?? baseCoordinate.yMeters,
          targetZone: doorCenterMapOverlay.zone,
          source: doorCenterMapOverlay.source,
          displaySource: doorCenterMapOverlay.source,
          displayMode: 'shadow_candidate_hold',
          displayReason: doorCenterMapOverlay.reason,
          shadowCandidateConfidence: doorCenterMapOverlay.confidence ?? baseCoordinate.shadowCandidateConfidence,
          operatorXMeters: doorCenterMapOverlay.xMeters ?? baseCoordinate.operatorXMeters,
          operatorYMeters: doorCenterMapOverlay.yMeters ?? baseCoordinate.operatorYMeters,
          operatorTargetZone: doorCenterMapOverlay.zone
        }
      : baseCoordinate;
    const operatorPresence = snapshot.live.operatorPresence || {};
    const ambiguity = snapshot.live.ambiguity || {};
    const activeCoordinate = coordinate?.activeForMap ? {
      ...coordinate,
      xMeters: coordinate.operatorXMeters ?? coordinate.xMeters,
      yMeters: coordinate.operatorYMeters ?? coordinate.yMeters,
      targetZone: coordinate.operatorTargetZone || coordinate.targetZone
    } : null;
    const diagnosticShadowCoordinate = !binarySafeOnly
      && !ambiguity.active
      && !activeCoordinate
      && safeNumber(coordinate?.shadowXMeters) != null
      && safeNumber(coordinate?.shadowYMeters) != null
      ? {
          xMeters: coordinate.shadowXMeters,
          yMeters: coordinate.shadowYMeters,
          targetZone: coordinate.shadowTargetZone || v8Shadow.targetZone || 'unknown',
          source: coordinate.shadowSource || v8Shadow.coordinateSource || 'v8_shadow_diagnostic'
        }
      : null;
    const activeRecordingPersonCount = Boolean(recordingStatus.recording)
      ? Math.max(0, Number(recordingStatus.person_count || 0) || 0)
      : 0;
    const mpEstimate = snapshot.live.multiPersonEstimate || {};
    const mpState = mpEstimate.state || 'single';
    const mpTracks = Array.isArray(mpEstimate.diagnosticTracks) ? mpEstimate.diagnosticTracks : [];
    const mpConfidence = mpEstimate.confidence || 0;
    // Multi-target diagnostic only when production is NOT confidently empty.
    // Prevents showing "2 people" in empty garage from shadow disagreement.
    const prodBinaryEmpty = productionBinary === 'empty'
      && (productionBinaryConfidence || 0) > 0.75;
    const multiTargetDiagnosticActive = !ambiguity.active
      && !activeCoordinate
      && !prodBinaryEmpty
      && (mpState === 'multi' || mpState === 'unresolved')
      && mpTracks.length > 1;
    const displayCoordinate = activeCoordinate || ((prodBinaryEmpty || binarySafeOnly) ? null : diagnosticShadowCoordinate);
    const garage = getGarageLayout(live);
    const smoothedCoordinate = this.getSmoothedSignalCoordinate(displayCoordinate, garage);
    const currentPoint = mapGarageCoordinateToPercent(smoothedCoordinate, garage);
    const multiTargetDiagnosticCoordinates = multiTargetDiagnosticActive
      ? mpTracks.map((track) => {
          const clamped = clampGarageCoordinate({ xMeters: track.x, yMeters: track.y }, garage);
          return clamped ? { ...clamped, id: track.id, source: track.source, trackClass: track.class, trackConfidence: track.confidence } : null;
        }).filter(Boolean)
      : (
        // Fallback: if runtime estimator not available yet but recording hint exists
        !ambiguity.active && !activeCoordinate && activeRecordingPersonCount > 1 && Boolean(diagnosticShadowCoordinate)
          ? buildMultiTargetDiagnosticCoordinates(smoothedCoordinate || diagnosticShadowCoordinate, garage, activeRecordingPersonCount)
          : []
      );
    const multiTargetDiagnosticPoints = multiTargetDiagnosticCoordinates
      .map((candidate) => mapGarageCoordinateToPercent(candidate, garage))
      .filter(Boolean);
    const garagePath = ambiguity.active
      ? null
      : activeCoordinate
        ? buildGarageTrackPolyline(buildGarageTrackPoints(coordinate.motionHistory, smoothedCoordinate, garage))
        : null;
    const garageDoor = mapGarageCoordinateToPercent(garage?.door, garage);
    const garageDoorWidth = garageDoor
      ? clamp(
          ((Number(garage?.door?.widthMeters) || DEFAULT_GARAGE_LAYOUT.door.widthMeters)
            / (Number(garage?.widthMeters) || DEFAULT_GARAGE_LAYOUT.widthMeters)) * 100,
          12,
          96
        )
      : null;
    const garageZones = getGarageZoneBands(garage);
    const ambiguityZone = garageZones.find((zone) => zone.id === ambiguity.targetZone) || null;
    const garageNodes = normalizeGarageNodes(Array.isArray(garage?.nodes) ? garage.nodes : []);
    const aggregateNodeNote = getAggregateNodeNote(topology.nodes || [], primaryRuntime);
    const liveTotalPackets = topology.liveTotalPackets ?? primaryRuntime.packetsInWindow;
    const lastPacketAgeSec = topology.lastPacketAgeSec ?? primaryRuntime.windowAgeSec;
    const liveWindowSeconds = topology.liveWindowSeconds ?? primaryRuntime.windowAgeSec;
    const motionWindowSeconds = topology.motionWindowSeconds ?? primaryRuntime.windowAgeSec;
    const vitalsWindowSeconds = snapshot.pose?.metadata?.vitals_window_seconds ?? topology.vitalsWindowSeconds ?? primaryRuntime.windowAgeSec;
    const mapModeLabel = binarySafeOnly
      ? 'binary-safe-only'
      : ambiguity.active
      ? 'ambiguity safe-mode'
      : activeCoordinate
        ? (coordinate?.displayMode === 'shadow_candidate_zone_anchor'
          ? 'single-target safe (shadow zone overlay)'
          : 'single-target safe')
        : multiTargetDiagnosticActive
          ? (mpState === 'multi'
            ? `multi-person diagnostic (${mpEstimate.personCountEstimate || '?'} est, ${Math.round(mpConfidence * 100)}%)`
            : `multi-person unresolved (${Math.round(mpConfidence * 100)}%)`)
        : diagnosticShadowCoordinate
          ? 'shadow-diagnostic'
        : 'suppressed';
    const v8PredictedClass = typeof v8Shadow.predictedClass === 'string' ? String(v8Shadow.predictedClass) : null;
    const trackBPredictedClass = typeof trackBShadow.predictedClass === 'string' ? String(trackBShadow.predictedClass) : null;
    // Shadow presence only counts when production is NOT confidently empty.
    // If production says empty with >0.80 confidence, shadow signals are likely
    // false positives (Track B warmup noise, V8 calibration drift).
    const productionConfidentlyEmpty = productionBinary === 'empty'
      && (productionBinaryConfidence || 0) > 0.80;
    const shadowPresenceDetected = !ambiguity.active && !activeCoordinate
      && !productionConfidentlyEmpty
      && (
        v8Shadow.binary === 'occupied'
        || v8PredictedClass === 'STATIC'
        || v8PredictedClass === 'MOTION'
        || trackBPredictedClass === 'STATIC'
        || trackBPredictedClass === 'MOTION'
      );
    const shadowConsensusBits = [
      v8PredictedClass ? `V8=${v8PredictedClass}` : null,
      trackBPredictedClass ? `Track B=${trackBPredictedClass}` : null
    ].filter(Boolean);
    const shadowPresenceHeadline = shadowPresenceDetected
      ? (v8PredictedClass === 'STATIC'
        ? 'V8 видит статичное присутствие'
        : v8PredictedClass === 'MOTION'
          ? 'V8 видит движение'
          : trackBPredictedClass === 'MOTION'
            ? 'Track B видит движение'
            : 'Shadow-модель видит присутствие')
      : null;
    const shadowPresenceDetail = shadowPresenceDetected
      ? `Production motion-runtime пока не выдал движение, поэтому объект на карте скрыт. ${shadowConsensusBits.join(' / ') || 'shadow verdict активен.'}`
      : null;
    const signalMapZoneLabel = binarySafeOnly
      ? (productionZone || productionBinary || 'unknown')
      : ambiguity.active
      ? ambiguity.targetZone || coordinate?.ambiguityTargetZone || 'unknown'
      : multiTargetDiagnosticActive
        ? `${mpEstimate.personCountEstimate || mpTracks.length} diagnostic tracks (${mpState})`
      : displayCoordinate?.targetZone || (shadowPresenceDetected ? 'обнаружен shadow-presence' : 'нет активного движения');
    const smoothingLabel = binarySafeOnly
      ? 'binary-safe-only: диагностические координаты скрыты'
      : ambiguity.active
      ? 'отключено в ambiguity safe-mode'
      : activeCoordinate
        ? 'по motion-history и runtime-геометрии'
        : multiTargetDiagnosticActive
          ? `runtime estimator (${mpState}, ${mpTracks.length} tracks)`
        : diagnosticShadowCoordinate
          ? 'мягкое диагностическое сглаживание V8 shadow'
          : (shadowPresenceDetected ? 'сглаживание отключено; доступен только shadow-presence' : 'отключено без active motion');
    const displayCoordinateXcm = binarySafeOnly
      ? null
      : (displayCoordinate?.xMeters != null ? displayCoordinate.xMeters * 100 : coordinate.xCm);
    const displayCoordinateYcm = binarySafeOnly
      ? null
      : (displayCoordinate?.yMeters != null ? displayCoordinate.yMeters * 100 : coordinate.yCm);
    const displayCoordinateSource = binarySafeOnly
      ? 'binary_safe_only'
      : activeCoordinate
      ? (coordinate?.displaySource || getCoordinateSourceText(coordinate))
      : multiTargetDiagnosticActive
        ? `runtime multi-person estimator (${mpState}, conf=${Math.round(mpConfidence * 100)}%)`
      : diagnosticShadowCoordinate
        ? 'V8 shadow diagnostic target'
        : (shadowPresenceDetected ? 'V8 shadow diagnostics (без active motion)' : getCoordinateSourceText(coordinate));
    const displayZoneSource = binarySafeOnly
      ? `${productionZoneSource || 'binary_safe_only'}${productionBinaryConfidence != null ? ` / binary ${Math.round(productionBinaryConfidence * 100)}%` : ''}`
      : coordinate?.displayMode === 'shadow_candidate_zone_anchor'
      ? `${coordinate?.displaySource || 'door_center_candidate_shadow'}${coordinate?.shadowCandidateConfidence != null ? ` (conf ${Math.round(coordinate.shadowCandidateConfidence * 100)}%)` : ''}`
      : `${primaryRuntimeDisplay?.zoneSource || primaryRuntime?.zoneSource || 'unknown'}${primaryRuntimeDisplay?.n02RssiEma != null ? ` (RSSI n02: ${formatNumber(primaryRuntimeDisplay.n02RssiEma, 1)} dBm${primaryRuntimeDisplay?.rssiVotes ? ` / votes: ${escapeHtml(primaryRuntimeDisplay.rssiVotes)}` : ''})` : ''}`;
    const coordinateDisplayLabel = coordinate?.displayGuided ? 'Координата (guided)' : 'Координата';
    const coordinateRawAvailable = coordinate?.displayGuided
      && (coordinate?.rawXcm != null || coordinate?.rawYcm != null);

    const motionProbabilities = Object.entries(motion.probabilities || {});

    this.sections.signal.innerHTML = `
      <div class="surface-grid surface-grid--three">
        <article class="panel">
          <div class="panel__eyebrow">Live sensor слой</div>
          <div class="panel__headline">${escapeHtml(formatNumber(liveTotalPackets))} пакетов</div>
          <div class="kv-list">
            <div class="kv"><span>Свежесть</span><strong>${escapeHtml(formatRelativeTime(lastPacketAgeSec))}</strong></div>
            <div class="kv"><span>Live-окно</span><strong>${escapeHtml(formatRelativeTime(liveWindowSeconds))}</strong></div>
            <div class="kv"><span>Окно движения</span><strong>${escapeHtml(formatRelativeTime(motionWindowSeconds))}</strong></div>
            <div class="kv"><span>Окно vitals</span><strong>${escapeHtml(formatRelativeTime(vitalsWindowSeconds))}</strong></div>
          </div>
          ${aggregateNodeNote ? `<div class="panel__footer">Live sensor слой использует aggregate motion-runtime окно; ${escapeHtml(aggregateNodeNote.toLowerCase())}</div>` : ''}
        </article>

        <article class="panel">
          <div class="panel__eyebrow">Динамика движения / фаз</div>
          <div class="panel__headline">${escapeHtml(displayToken(primaryRuntime.state || motion.label || 'unknown'))}</div>
          <div class="metric-bars">
            ${motionProbabilities.length
              ? motionProbabilities.map(([label, value]) => renderMetricBar(label, Number(value) || 0)).join('')
              : '<div class="muted">Вероятности движения недоступны.</div>'}
          </div>
          <div class="panel__footer">Уверенность движения ${escapeHtml(formatPercent(primaryRuntime.confidence, 0))} / coarse-диагностика ${escapeHtml(displayToken(secondaryRuntime.coarse || 'unknown'))} / активность ${escapeHtml(getMotionActivityText(motion, primaryRuntime))}</div>
        </article>

        <article class="panel">
          <div class="panel__eyebrow">Сигнатура и координата</div>
          <div class="panel__headline">${escapeHtml(getFingerprintLabelText(fingerprint))}</div>
          <div class="kv-list">
            <div class="kv"><span>Запас</span><strong>${escapeHtml(getFingerprintMarginText(fingerprint))}</strong></div>
            <div class="kv"><span>${escapeHtml(coordinateDisplayLabel)}</span><strong>${escapeHtml(formatNumber(coordinate.xCm, 1))} / ${escapeHtml(formatNumber(coordinate.yCm, 1))} см</strong></div>
            ${coordinateRawAvailable ? `
              <div class="kv"><span>Координата raw</span><strong>${escapeHtml(formatNumber(coordinate.rawXcm, 1))} / ${escapeHtml(formatNumber(coordinate.rawYcm, 1))} см</strong></div>
              <div class="kv"><span>Display mode</span><strong>${escapeHtml(displayToken(coordinate.displayMode || 'raw_coordinate'))} / ${escapeHtml(displayToken(coordinate.displayReason || 'raw_runtime_coordinate'))}</strong></div>
            ` : ''}
            <div class="kv"><span>Источник координаты</span><strong>${escapeHtml(getCoordinateSourceText(coordinate))}</strong></div>
          </div>
        </article>
      </div>

      <div class="surface-grid surface-grid--two">
        <article class="panel">
          <div class="panel__eyebrow">Карта гаража и датчики</div>
          <div class="garage-map-shell">
            <div class="garage-map">
              ${garageZones.map((zone) => `
                <div class="garage-map__zone garage-map__zone--${zone.id}" style="top:${zone.top}%;height:${zone.height}%">
                  <span>${zone.label}</span>
                </div>
              `).join('')}
              ${(() => {
                const w = Number(garage?.widthMeters) || DEFAULT_GARAGE_LAYOUT.widthMeters;
                const h = Number(garage?.heightMeters) || DEFAULT_GARAGE_LAYOUT.heightMeters;
                const subzones = [
                  garage?.zones?.zone3 || DEFAULT_GARAGE_LAYOUT.zones.zone3,
                  garage?.zones?.zone4 || DEFAULT_GARAGE_LAYOUT.zones.zone4
                ].filter(Boolean);
                return subzones.map((sz) => {
                  const left = ((sz.xMin + w / 2) / w) * 100;
                  const right = ((sz.xMax + w / 2) / w) * 100;
                  const top = (1 - sz.yMax / h) * 100;
                  const bottom = (1 - sz.yMin / h) * 100;
                  return '<div class="garage-map__subzone" style="'
                    + 'left:' + left.toFixed(1) + '%;'
                    + 'top:' + top.toFixed(1) + '%;'
                    + 'width:' + (right - left).toFixed(1) + '%;'
                    + 'height:' + (bottom - top).toFixed(1) + '%">'
                    + '<span>' + escapeHtml(sz.label) + '</span></div>';
                }).join('');
              })()}
              <div class="garage-map__centerline garage-map__centerline--x"></div>
              <div class="garage-map__centerline garage-map__centerline--y"></div>
              <svg class="garage-map__overlay" viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true">
                ${garagePath ? `<polyline class="garage-map__trail" points="${garagePath}"></polyline>` : ''}
              </svg>
              ${ambiguity.active && ambiguityZone ? `
                <div class="garage-map__ambiguity-zone garage-map__ambiguity-zone--${ambiguityZone.id}" style="top:${ambiguityZone.top}%;height:${ambiguityZone.height}%"></div>
              ` : ''}
              ${garageDoor ? `
                <div class="garage-map__door" style="left:${garageDoor.left}%;top:${garageDoor.top}%;width:${garageDoorWidth.toFixed(1)}%">
                  <span>дверь</span>
                </div>
              ` : ''}
              ${garageNodes.map((node) => {
                const nodePoint = mapGarageCoordinateToPercent(node, garage);
                if (!nodePoint) {
                  return '';
                }
                return `
                  <div class="garage-map__sensor garage-map__sensor--${escapeHtml(node.zone || 'unknown')}" style="left:${nodePoint.left}%;top:${nodePoint.top}%">
                    <strong>${escapeHtml(node.nodeId)}</strong>
                  </div>
                `;
              }).join('')}
              ${multiTargetDiagnosticActive ? multiTargetDiagnosticPoints.map((point, index) => {
                const track = multiTargetDiagnosticCoordinates[index] || {};
                const trackLabel = track.source === 'production' ? 'prod' : (track.source || `#${index + 1}`);
                const trackConf = track.trackConfidence != null ? `${Math.round(track.trackConfidence * 100)}%` : '';
                return `
                <div class="garage-map__candidate-target garage-map__candidate-target--${track.source === 'production' ? 'prod' : 'shadow'}" style="left:${point.left}%;top:${point.top}%" title="${escapeHtml(track.id || '')} ${escapeHtml(track.trackClass || '')} ${trackConf}">
                  <span class="garage-map__candidate-core"></span>
                  <small>${escapeHtml(trackLabel)}</small>
                </div>`;
              }).join('') : ''}
              ${ambiguity.active ? `
                <div class="garage-map__ambiguity-card">
                  <strong>${escapeHtml(ambiguity.headline || 'несколько людей / позиция неоднозначна')}</strong>
                  <span>${escapeHtml(ambiguity.detail || 'single-target marker скрыт, raw координата остаётся только диагностикой')}</span>
                </div>
              ` : multiTargetDiagnosticActive ? `
                <div class="garage-map__presence-card garage-map__presence-card--mp-estimator">
                  <strong>${escapeHtml(mpState === 'multi'
                    ? `${mpEstimate.personCountEstimate || mpTracks.length} диагностические цели (runtime estimator)`
                    : `multi-person unresolved — точное разделение невозможно`)}</strong>
                  <span>${escapeHtml(mpState === 'multi'
                    ? `Оценщик runtime оценил ${mpEstimate.personCountEstimate || '?'} человек (уверенность ${Math.round(mpConfidence * 100)}%). Это диагностические цели из runtime-сигналов, не подтверждённые цели.`
                    : `Есть признаки нескольких людей (${Math.round(mpConfidence * 100)}%), но exact separation не resolved. ${mpEstimate.estimatorReasons?.join(', ') || ''}`)}</span>
                </div>
              ` : currentPoint ? `
                <div class="garage-map__object ${activeCoordinate ? '' : 'garage-map__object--diagnostic'}" style="left:${currentPoint.left}%;top:${currentPoint.top}%">
                  <span class="garage-map__object-core"></span>
                </div>
                ${shadowPresenceDetected ? `
                  <div class="garage-map__presence-card">
                    <strong>${escapeHtml(shadowPresenceHeadline)}</strong>
                    <span>${escapeHtml(shadowPresenceDetail)}</span>
                  </div>
                ` : ''}
              ` : `
                <div class="garage-map__empty">Motion-runtime сейчас не видит свежего движения. Диагностическая static-координата не показывается как live-объект.</div>
                ${shadowPresenceDetected ? `
                  <div class="garage-map__presence-card">
                    <strong>${escapeHtml(shadowPresenceHeadline)}</strong>
                    <span>${escapeHtml(shadowPresenceDetail)}</span>
                  </div>
                ` : ''}
              `}
            </div>
            <div class="garage-map__summary">
              <div class="garage-map__metric">
                <span>Текущая зона</span>
                <strong>${escapeHtml(displayMaybeToken(signalMapZoneLabel))}</strong>
              </div>
              <div class="garage-map__metric">
                <span>Источник зоны</span>
                <strong>${escapeHtml(displayZoneSource)}</strong>
              </div>
              <div class="garage-map__metric">
                <span>Координата</span>
                <strong>${escapeHtml(formatNumber(displayCoordinateXcm, 1))} / ${escapeHtml(formatNumber(displayCoordinateYcm, 1))} см</strong>
              </div>
              <div class="garage-map__metric">
                <span>Источник координат</span>
                <strong>${escapeHtml(displayCoordinateSource)}</strong>
              </div>
              <div class="garage-map__metric">
                <span>Режим карты</span>
                <strong>${escapeHtml(mapModeLabel)}</strong>
              </div>
              <div class="garage-map__metric">
                <span>Сглаживание</span>
                <strong>${escapeHtml(smoothingLabel)}</strong>
              </div>
            </div>
          </div>
          <div class="panel__footer">Карта использует реальные размеры гаража и позиции датчиков из motion-runtime. Single-target marker разрешён только после operator-safe gate и только при низкой ambiguity. Если collapse/ambiguity risk высокий, карта уходит в ambiguity safe-mode: точка и хвост скрываются, а raw target остаётся только диагностикой.</div>
        </article>

        <article class="panel">
          <div class="panel__eyebrow">Позиция (epoch4 RF)</div>
          ${(() => {
            const pos = snapshot.live.position;
            if (binarySafeOnly) {
              return `
                <div class="panel__headline" style="opacity:0.8">DIAGNOSTIC HIDDEN</div>
                <div class="panel__footer">Epoch4 RF позиция скрыта в режиме <b>binary_safe_only</b>, чтобы не конфликтовать с основным occupancy verdict.</div>
              `;
            }
            if (!pos) {
              return '<div class="panel__headline" style="opacity:0.5">Загрузка...</div>';
            }
            const confPct = Math.round((pos.confidence || 0) * 100);
            const confTone = confPct >= 70 ? 'tone-ok' : confPct >= 40 ? 'tone-warn' : 'tone-alert';
            const posLabel = pos.position || 'unknown';
            const barWidth = Math.max(5, Math.min(100, confPct));
            return `
              <div class="panel__headline ${confTone}" style="font-size:1.4em">${escapeHtml(posLabel.toUpperCase())}</div>
              <div style="margin:8px 0;background:var(--bg-secondary,#222);border-radius:4px;height:24px;overflow:hidden;position:relative">
                <div style="width:${barWidth}%;height:100%;background:${confPct >= 70 ? '#4caf50' : confPct >= 40 ? '#ff9800' : '#f44336'};border-radius:4px;transition:width 0.3s"></div>
                <span style="position:absolute;top:50%;left:50%;transform:translate(-50%,-50%);font-weight:bold;font-size:13px;color:#fff">${confPct}%</span>
              </div>
              <div class="kv-list">
                ${(pos.top3 || []).map((t, i) => `
                  <div class="kv">
                    <span>${i === 0 ? '1' : i === 1 ? '2' : '3'}</span>
                    <strong>${escapeHtml(t.label)} — ${Math.round((t.probability || 0) * 100)}%</strong>
                  </div>
                `).join('')}
                <div class="kv"><span>Ноды</span><strong>${pos.nodes_ready || 0} / ${pos.nodes_total || 7}</strong></div>
              </div>
            `;
          })()}
        </article>

        <article class="panel">
          <div class="panel__eyebrow">Диагностические прогнозы</div>
          <div class="panel__headline" style="opacity:0.8">СКРЫТЫ</div>
          <div class="panel__footer">На основной поверхности оставлены только актуальные production/latest-model verdicts. Shadow, fallback и multi-person diagnostics убраны, чтобы не смешивать источники.</div>
        </article>
      </div>

      <article class="panel">
        <div class="panel__eyebrow">Сигнал по каждому узлу — live мониторинг (7 ESP32)</div>
        <div id="nodes-live-grid" class="node-signal-grid">
          ${this._renderNodesLiveRows()}
        </div>
        <div id="nodes-live-position" style="margin-top:8px;font-size:12px;opacity:0.8"></div>
        <div class="panel__footer">Обновляется каждые 1.5 сек. RSSI: зелёный > -40, жёлтый -40..-55, красный < -55 dBм. tvar = временная вариация (маркер движения). Sparkline = история RSSI (20 точек).</div>
      </article>

      <div class="signal-dashboard" id="signal-dashboard">
        <article class="panel">
          <div class="panel__eyebrow">Дашборд сигналов — временные ряды</div>
          <div class="signal-dashboard__time-range" id="sd-time-range">
            <label>Диапазон:</label>
            <button class="signal-dashboard__range-btn active" data-sd-range="60">1 мин</button>
            <button class="signal-dashboard__range-btn" data-sd-range="300">5 мин</button>
            <button class="signal-dashboard__range-btn" data-sd-range="900">15 мин</button>
            <button class="signal-dashboard__range-btn" data-sd-range="3600">1 час</button>
            <button class="signal-dashboard__range-btn" data-sd-range="21600">6 часов</button>
            <button class="signal-dashboard__range-btn" data-sd-range="86400">24 часа</button>
            <button class="signal-dashboard__range-btn" data-sd-range="0">Вся история</button>
            <span class="signal-dashboard__range-info" id="sd-range-info">--</span>
          </div>
        </article>

        <div class="signal-dashboard__status-strip" id="sd-status-strip">
          <div class="sd-status-card sd-status-card--neutral">
            <div class="sd-status-card__eyebrow">Runtime / shadow</div>
            <div class="sd-status-card__headline">Ожидание данных...</div>
            <div class="sd-status-card__detail">Поднимаю live-статус и health-флаги.</div>
          </div>
        </div>

        <div class="signal-dashboard__node-cards" id="sd-node-cards"></div>

        <div class="signal-dashboard__charts">
          <div class="sd-chart-panel"><h3>A. RSSI по узлам (дБм)</h3><canvas id="sd-chart-rssi"></canvas></div>
          <div class="sd-chart-panel"><h3>B. Амплитуда по узлам</h3><canvas id="sd-chart-amp"></canvas></div>
          <div class="sd-chart-panel"><h3>C. Temporal Variance по узлам</h3><canvas id="sd-chart-tvar"></canvas></div>
          <div class="sd-chart-panel"><h3>D. Корреляции между узлами</h3><canvas id="sd-chart-corr"></canvas></div>
          <div class="sd-chart-panel"><h3>E. Phase STD по узлам</h3><canvas id="sd-chart-phase"></canvas></div>
          <div class="sd-chart-panel"><h3>F. Бинарное предсказание (занятость)</h3><canvas id="sd-chart-binary"></canvas></div>
        </div>

        <div class="signal-dashboard__event-log">
          <h3>
            <span>Журнал событий</span>
          </h3>
          <div class="sd-event-log" id="sd-event-log">
            <div style="color:var(--operator-text-muted); padding:8px 0; text-align:center;">Скрыт на основной поверхности. Показаны только текущие verdict’ы активной модели.</div>
          </div>
        </div>
      </div>
    `;
    this._initSignalDashboard();
  }

  _refreshSignalLiveSurface() {
    this._renderNodesLiveCards();
    this._sdRenderStatusStrip();
    this._sdRenderNodeCards();
    this._sdRenderEventLog();
    this._sdUpdateCharts();
  }

  // ============================================================
  //  Signal Dashboard — Chart.js time-series monitor
  // ============================================================

  _SD_NODE_IDS = ['node01','node02','node03','node04','node05','node06','node07'];
  _SD_NODE_IPS = ['192.168.0.137','192.168.0.117','192.168.0.144','192.168.0.125','192.168.0.110','192.168.0.132','192.168.0.153'];
  _SD_NODE_COLORS = ['#4fc3f7','#ff9800','#56f39a','#f06292','#ab47bc','#ffc107','#00e5ff'];
  _SD_CORR_PAIRS = [['node04','node05'],['node03','node06'],['node05','node06'],['node01','node03'],['node02','node04']];
  _SD_CORR_COLORS = ['#4fc3f7','#ff9800','#56f39a','#f06292','#ab47bc'];
  _SD_MAX_HISTORY = 100000;
  _SD_SPARKLINE_LEN = 50;
  _SD_LS_KEY = 'csi_signal_history';
  _SD_POLL_MS = 2000;
  _RUNTIME_UI_BACKOFF_MS = 15000;
  _SD_HISTORY_ENDPOINT = '/api/v1/csi/history';
  _SD_HISTORY_MAX_POINTS = 2400;

  _initSignalDashboard() {
    if (typeof Chart === 'undefined') return;
    const container = this.root.querySelector('#signal-dashboard');
    if (!container) return;
    // The whole signal tab DOM is re-rendered часто, поэтому старые chart
    // instances нельзя переиспользовать — они остаются привязаны к удалённым canvas.
    if (!this._sdInitialized) {
      this._sdLoadHistory();
      this._sdBootstrapHistoryFromServer(this._sdSelectedRange);
    }
    if (this._sdCharts) {
      Object.values(this._sdCharts).forEach((chart) => { try { chart.destroy(); } catch (_) {} });
      this._sdCharts = null;
    }
    this._sdInitNodeCards();
    this._sdInitCharts();
    this._sdBindTimeRange();
    this._sdRenderEventLog();
    this._sdRenderStatusStrip();
    // Restore sparklines from recent history
    if (this._sdHistory.length > 0 && Object.keys(this._sdSparklineData).length === 0) {
      const recent = this._sdHistory.slice(-this._SD_SPARKLINE_LEN);
      recent.forEach(entry => {
        this._SD_NODE_IDS.forEach(nid => {
          if (!this._sdSparklineData[nid]) this._sdSparklineData[nid] = [];
          if (entry.node_rssi && entry.node_rssi[nid] != null) {
            this._sdSparklineData[nid].push(entry.node_rssi[nid]);
          }
        });
      });
      this._SD_NODE_IDS.forEach(nid => {
        if (this._sdSparklineData[nid]) {
          this._sdSparklineData[nid] = this._sdSparklineData[nid].slice(-this._SD_SPARKLINE_LEN);
        }
      });
    }
    this._sdRenderNodeCards();
    this._sdUpdateCharts();
    // Start independent polling for dashboard
    if (!this._sdPollTimer) {
      this._sdPollData();
      this._sdPollTimer = setInterval(() => this._sdPollData(), this._SD_POLL_MS);
    }
    this._sdInitialized = true;
  }

  _destroySignalDashboard() {
    if (this._sdPollTimer) {
      clearInterval(this._sdPollTimer);
      this._sdPollTimer = null;
    }
    if (this._sdCharts) {
      Object.values(this._sdCharts).forEach(c => { try { c.destroy(); } catch(_){} });
      this._sdCharts = null;
    }
    this._sdInitialized = false;
  }

  _sdLoadHistory() {
    try {
      const raw = localStorage.getItem(this._SD_LS_KEY);
      if (raw) {
        const parsed = JSON.parse(raw);
        if (Array.isArray(parsed)) this._sdHistory = parsed;
      }
      const evRaw = localStorage.getItem(this._SD_LS_KEY + '_events');
      if (evRaw) {
        const parsed = JSON.parse(evRaw);
        if (Array.isArray(parsed)) this._sdEvents = parsed;
      }
    } catch(_) {}
    // Restore last binary state
    if (this._sdHistory.length > 0) {
      const last = this._sdHistory[this._sdHistory.length - 1];
      if (last.binary_prob != null) {
        this._sdLastBinary = last.binary_prob >= 0.25 ? 'occupied' : 'empty';
      }
    }
  }

  _sdMergeHistoryEntries(primary = [], secondary = []) {
    const merged = new Map();
    const upsert = (entry) => {
      const ts = Number(entry?.timestamp);
      if (!Number.isFinite(ts)) return;
      const key = Math.round(ts / 1000);
      const normalized = {
        timestamp: ts,
        node_rssi: { ...(entry?.node_rssi || {}) },
        node_amp: { ...(entry?.node_amp || {}) },
        node_tvar: { ...(entry?.node_tvar || {}) },
        correlations: { ...(entry?.correlations || {}) },
        phase_stds: { ...(entry?.phase_stds || {}) },
        binary_prob: entry?.binary_prob ?? null
      };
      if (!merged.has(key)) {
        merged.set(key, normalized);
        return;
      }
      const current = merged.get(key);
      current.timestamp = Math.max(current.timestamp, normalized.timestamp);
      current.node_rssi = { ...current.node_rssi, ...normalized.node_rssi };
      current.node_amp = { ...current.node_amp, ...normalized.node_amp };
      current.node_tvar = { ...current.node_tvar, ...normalized.node_tvar };
      current.correlations = { ...current.correlations, ...normalized.correlations };
      current.phase_stds = { ...current.phase_stds, ...normalized.phase_stds };
      if (normalized.binary_prob != null) {
        current.binary_prob = normalized.binary_prob;
      }
    };
    primary.forEach(upsert);
    secondary.forEach(upsert);
    return [...merged.values()].sort((a, b) => a.timestamp - b.timestamp);
  }

  _sdGetHistoryRangeKey(rangeSec = this._sdSelectedRange) {
    const normalized = Number(rangeSec || 0);
    return normalized > 0 ? String(normalized) : 'all';
  }

  _sdBuildHistoryEndpoint(rangeSec = this._sdSelectedRange) {
    const params = new URLSearchParams({
      max_points: String(this._SD_HISTORY_MAX_POINTS)
    });
    const normalized = Number(rangeSec || 0);
    if (normalized > 0) {
      params.set('range_sec', String(normalized));
    }
    return `${this._SD_HISTORY_ENDPOINT}?${params.toString()}`;
  }

  async _sdBootstrapHistoryFromServer(rangeSec = this._sdSelectedRange, { force = false } = {}) {
    const rangeKey = this._sdGetHistoryRangeKey(rangeSec);
    if (!force && this._sdLoadedHistoryRangeKey === rangeKey) return;
    if (this._sdServerHistoryPromise && this._sdPendingHistoryRangeKey === rangeKey) {
      await this._sdServerHistoryPromise;
      return;
    }
    this._sdServerHistoryPromise = (async () => {
      this._sdPendingHistoryRangeKey = rangeKey;
      try {
        const resp = await fetch(this._sdBuildHistoryEndpoint(rangeSec), { signal: AbortSignal.timeout(15000) });
        if (!resp.ok) return;
        const payload = await resp.json();
        const entries = Array.isArray(payload?.entries) ? payload.entries : [];
        this._sdArchiveMeta = payload?.meta || null;
        this._sdHistory = entries;
        this._sdLoadedHistoryRangeKey = rangeKey;
        this._sdSaveHistory();
        this._sdUpdateCharts();
      } catch (_) {
        // Fallback silently to browser-local history.
      } finally {
        this._sdServerHistoryPromise = null;
        this._sdPendingHistoryRangeKey = null;
      }
    })();
    await this._sdServerHistoryPromise;
  }

  _sdSaveHistory() {
    try {
      if (this._sdHistory.length > this._SD_MAX_HISTORY) {
        this._sdHistory = this._sdHistory.slice(this._sdHistory.length - this._SD_MAX_HISTORY);
      }
      localStorage.setItem(this._SD_LS_KEY, JSON.stringify(this._sdHistory));
      localStorage.setItem(this._SD_LS_KEY + '_events', JSON.stringify(this._sdEvents.slice(-500)));
    } catch(_) {}
  }

  _sdInitNodeCards() {
    const container = this.root.querySelector('#sd-node-cards');
    if (!container) return;
    this._SD_NODE_IDS.forEach(nid => {
      if (!this._sdSparklineData[nid]) this._sdSparklineData[nid] = [];
    });
    this._sdRenderNodeCards();
  }

  _sdRenderNodeCards() {
    const container = this.root.querySelector('#sd-node-cards');
    if (!container) return;
    container.innerHTML = this._SD_NODE_IDS.map((id, i) => `
      <div class="sd-node-card offline" id="sd-nc-${id}">
        <div class="sd-node-card__header">
          <div>
            <span class="sd-node-card__name" style="color:${this._SD_NODE_COLORS[i]}">${id}</span>
            <span class="sd-node-card__ip">${this._SD_NODE_IPS[i]}</span>
          </div>
          <span class="sd-node-card__status offline" id="sd-nc-st-${id}">\u041E\u0416\u0418\u0414\u0410\u041D\u0418\u0415</span>
        </div>
        <div class="sd-node-card__metrics">
          <div class="sd-node-card__metric"><span class="sd-node-card__metric-label">RSSI</span><span class="sd-node-card__metric-value" id="sd-nc-rssi-${id}">--</span></div>
          <div class="sd-node-card__metric"><span class="sd-node-card__metric-label">Amp</span><span class="sd-node-card__metric-value" id="sd-nc-amp-${id}">--</span></div>
          <div class="sd-node-card__metric"><span class="sd-node-card__metric-label">Tvar</span><span class="sd-node-card__metric-value" id="sd-nc-tvar-${id}">--</span></div>
          <div class="sd-node-card__metric"><span class="sd-node-card__metric-label">PhStd</span><span class="sd-node-card__metric-value" id="sd-nc-phase-${id}">--</span></div>
          <div class="sd-node-card__metric"><span class="sd-node-card__metric-label">PPS</span><span class="sd-node-card__metric-value" id="sd-nc-pps-${id}">--</span></div>
          <div class="sd-node-card__metric"><span class="sd-node-card__metric-label">Пакеты</span><span class="sd-node-card__metric-value" id="sd-nc-pkts-${id}">--</span></div>
        </div>
        <div class="sd-node-card__sparkline"><canvas id="sd-spark-${id}"></canvas></div>
      </div>
    `).join('');
    this._SD_NODE_IDS.forEach((nodeId) => {
      if (this._sdNodeState[nodeId]) {
        this._sdUpdateNodeCard(nodeId, this._sdNodeState[nodeId]);
      } else if (this._sdSparklineData[nodeId]?.length) {
        this._sdDrawSparkline(nodeId);
      }
    });
  }

  _sdUpdateNodeCard(nodeId, data) {
    this._sdNodeState[nodeId] = { ...data };
    const card = this.root.querySelector(`#sd-nc-${nodeId}`);
    const stEl = this.root.querySelector(`#sd-nc-st-${nodeId}`);
    if (!card || !stEl) return;
    const rssi = data.rssi;
    const health = this._getNodeHealthInfo(nodeId);
    const mgmtOk = health ? Boolean(health.management_ok) : null;
    let status = 'offline';
    let statusText = '\u041D\u041E\u0414\u0410 \u041D\u0415\u0414\u041E\u0421\u0422\u0423\u041F\u041D\u0410';
    if (data.online) {
      if (mgmtOk === false) {
        status = 'weak';
        statusText = 'CSI \u0410\u041A\u0422\u0418\u0412\u0415\u041D';
      } else {
        status = (rssi != null && rssi > -70) ? 'online' : 'weak';
        statusText = status === 'online' ? 'OK' : 'WEAK';
      }
    } else if (mgmtOk === true) {
      status = 'weak';
      statusText = 'CSI \u041D\u0415\u0422';
    }
    card.className = `sd-node-card ${status}`;
    stEl.className = `sd-node-card__status ${status}`;
    stEl.textContent = statusText;
    const set = (sfx, val) => {
      const el = this.root.querySelector(`#sd-nc-${sfx}-${nodeId}`);
      if (el) el.textContent = val;
    };
    set('rssi', rssi != null ? `${rssi} дБм` : '--');
    set('amp', data.amp_mean != null ? data.amp_mean.toFixed(1) : '--');
    set('tvar', data.temporal_var != null ? data.temporal_var.toFixed(3) : '--');
    set('phase', data.phase_std != null ? data.phase_std.toFixed(3) : '--');
    set('pps', data.pps != null ? data.pps.toFixed(1) : '--');
    set('pkts', data.packets != null ? String(data.packets) : '--');
    // Sparkline
    if (rssi != null) {
      if (!this._sdSparklineData[nodeId]) this._sdSparklineData[nodeId] = [];
      this._sdSparklineData[nodeId].push(rssi);
      if (this._sdSparklineData[nodeId].length > this._SD_SPARKLINE_LEN) {
        this._sdSparklineData[nodeId] = this._sdSparklineData[nodeId].slice(-this._SD_SPARKLINE_LEN);
      }
    }
    this._sdDrawSparkline(nodeId);
  }

  _sdDrawSparkline(nodeId) {
    const canvas = this.root.querySelector(`#sd-spark-${nodeId}`);
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    const dpr = window.devicePixelRatio || 1;
    const rect = canvas.parentElement.getBoundingClientRect();
    if (rect.width < 1) return;
    canvas.width = rect.width * dpr;
    canvas.height = rect.height * dpr;
    ctx.scale(dpr, dpr);
    const w = rect.width, h = rect.height;
    ctx.clearRect(0, 0, w, h);
    const data = this._sdSparklineData[nodeId] || [];
    if (data.length < 2) return;
    const min = Math.min(...data) - 2;
    const max = Math.max(...data) + 2;
    const range = max - min || 1;
    const idx = this._SD_NODE_IDS.indexOf(nodeId);
    const color = this._SD_NODE_COLORS[idx] || '#4fc3f7';
    ctx.strokeStyle = color;
    ctx.lineWidth = 1.2;
    ctx.beginPath();
    data.forEach((v, i) => {
      const x = (i / (data.length - 1)) * w;
      const y = h - ((v - min) / range) * h;
      if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
    });
    ctx.stroke();
  }

  _sdMakeChartConfig(yLabel, datasets, suggestedMin, suggestedMax) {
    return {
      type: 'line',
      data: { datasets },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: false,
        interaction: { mode: 'index', intersect: false },
        scales: {
          x: {
            type: 'linear',
            title: { display: false },
            ticks: {
              callback: v => {
                const d = new Date(v);
                return d.getHours().toString().padStart(2, '0') + ':' +
                  d.getMinutes().toString().padStart(2, '0') + ':' +
                  d.getSeconds().toString().padStart(2, '0');
              },
              maxTicksLimit: 8
            },
            grid: { color: 'rgba(30,45,74,0.3)' }
          },
          y: {
            title: { display: true, text: yLabel, font: { size: 10 } },
            suggestedMin, suggestedMax,
            grid: { color: 'rgba(30,45,74,0.3)' }
          }
        },
        plugins: {
          legend: { display: true, position: 'top', labels: { boxWidth: 10, padding: 6, font: { size: 9 } } },
          tooltip: {
            callbacks: {
              title: items => {
                if (!items.length) return '';
                return new Date(items[0].parsed.x).toLocaleTimeString('ru-RU');
              }
            }
          }
        },
        elements: { point: { radius: 0 }, line: { borderWidth: 1.5 } }
      }
    };
  }

  _sdMakeNodeDatasets() {
    return this._SD_NODE_IDS.map((id, i) => ({
      label: id,
      borderColor: this._SD_NODE_COLORS[i],
      backgroundColor: this._SD_NODE_COLORS[i] + '22',
      data: [],
      tension: 0.3
    }));
  }

  _sdMakeCorrDatasets() {
    return this._SD_CORR_PAIRS.map(([a, b], i) => ({
      label: `${a}-${b}`,
      borderColor: this._SD_CORR_COLORS[i],
      backgroundColor: this._SD_CORR_COLORS[i] + '22',
      data: [],
      tension: 0.3
    }));
  }

  _sdInitCharts() {
    if (this._sdCharts) {
      Object.values(this._sdCharts).forEach(c => { try { c.destroy(); } catch(_){} });
    }
    Chart.defaults.color = '#91a3bc';
    Chart.defaults.borderColor = 'rgba(120,145,180,0.12)';
    Chart.defaults.font.family = "'SF Mono','Fira Code','JetBrains Mono',monospace";
    Chart.defaults.font.size = 10;
    const h = 200;
    this.root.querySelectorAll('.sd-chart-panel canvas').forEach(c => {
      c.parentElement.style.height = (h + 40) + 'px';
      c.style.height = h + 'px';
    });
    const get = (id) => this.root.querySelector(`#${id}`);
    this._sdCharts = {};
    this._sdCharts.rssi = new Chart(get('sd-chart-rssi'), this._sdMakeChartConfig('дБм', this._sdMakeNodeDatasets(), -90, -30));
    this._sdCharts.amp = new Chart(get('sd-chart-amp'), this._sdMakeChartConfig('Амплитуда', this._sdMakeNodeDatasets(), 0, undefined));
    this._sdCharts.tvar = new Chart(get('sd-chart-tvar'), this._sdMakeChartConfig('Temporal Var', this._sdMakeNodeDatasets(), 0, undefined));
    this._sdCharts.corr = new Chart(get('sd-chart-corr'), this._sdMakeChartConfig('Корреляция', this._sdMakeCorrDatasets(), -1, 1));
    this._sdCharts.phase = new Chart(get('sd-chart-phase'), this._sdMakeChartConfig('Phase STD', this._sdMakeNodeDatasets(), 0, undefined));
    const binaryDs = [{
      label: 'P(occupied)',
      borderColor: '#ff6d87',
      backgroundColor: 'rgba(255,109,135,0.1)',
      data: [],
      fill: true,
      tension: 0.3
    }, {
      label: 'Порог 0.25',
      borderColor: '#ffb35c',
      borderDash: [6, 3],
      data: [],
      pointRadius: 0,
      tension: 0
    }];
    this._sdCharts.binary = new Chart(get('sd-chart-binary'), this._sdMakeChartConfig('P(occupied)', binaryDs, 0, 1));
  }

  _sdGetFilteredHistory() {
    if (this._sdSelectedRange === 0 || this._sdHistory.length === 0) return this._sdHistory;
    const cutoff = Date.now() - this._sdSelectedRange * 1000;
    let lo = 0, hi = this._sdHistory.length - 1;
    while (lo < hi) {
      const mid = (lo + hi) >> 1;
      if (this._sdHistory[mid].timestamp < cutoff) lo = mid + 1; else hi = mid;
    }
    return this._sdHistory.slice(lo);
  }

  _sdUpdateCharts() {
    if (!this._sdCharts) return;
    const filtered = this._sdGetFilteredHistory();
    if (filtered.length === 0) return;
    const span = filtered.length > 1 ? (filtered[filtered.length - 1].timestamp - filtered[0].timestamp) / 1000 : 0;
    const infoEl = this.root.querySelector('#sd-range-info');
    if (infoEl) {
      const bucket = this._sdArchiveMeta?.bucket_sec;
      const sourceSuffix = this._sdArchiveMeta?.archive_points
        ? ` | архив ${this._sdArchiveMeta.archive_points} т.`
        : '';
      const bucketSuffix = bucket ? ` | bucket ${bucket}s` : '';
      infoEl.textContent = `${filtered.length} точек | ${this._sdFormatDuration(span)}${sourceSuffix}${bucketSuffix}`;
    }
    const rssiData = this._SD_NODE_IDS.map(() => []);
    const ampData = this._SD_NODE_IDS.map(() => []);
    const tvarData = this._SD_NODE_IDS.map(() => []);
    const phaseData = this._SD_NODE_IDS.map(() => []);
    const corrData = this._SD_CORR_PAIRS.map(() => []);
    const binaryData = [];
    const thresholdData = [];
    const maxPoints = 800;
    const step = Math.max(1, Math.floor(filtered.length / maxPoints));
    for (let idx = 0; idx < filtered.length; idx += step) {
      const entry = filtered[idx];
      const t = entry.timestamp;
      this._SD_NODE_IDS.forEach((nid, ni) => {
        const nr = entry.node_rssi || {};
        const na = entry.node_amp || {};
        const nt = entry.node_tvar || {};
        const np = entry.phase_stds || {};
        if (nr[nid] != null) rssiData[ni].push({ x: t, y: nr[nid] });
        if (na[nid] != null) ampData[ni].push({ x: t, y: na[nid] });
        if (nt[nid] != null) tvarData[ni].push({ x: t, y: nt[nid] });
        if (np[nid] != null) phaseData[ni].push({ x: t, y: np[nid] });
      });
      const corrs = entry.correlations || {};
      this._SD_CORR_PAIRS.forEach(([a, b], ci) => {
        const key = `corr_${a}_${b}`;
        if (corrs[key] != null) corrData[ci].push({ x: t, y: corrs[key] });
      });
      if (entry.binary_prob != null) {
        binaryData.push({ x: t, y: entry.binary_prob });
        thresholdData.push({ x: t, y: 0.25 });
      }
    }
    this._SD_NODE_IDS.forEach((_, i) => {
      this._sdCharts.rssi.data.datasets[i].data = rssiData[i];
      this._sdCharts.amp.data.datasets[i].data = ampData[i];
      this._sdCharts.tvar.data.datasets[i].data = tvarData[i];
      this._sdCharts.phase.data.datasets[i].data = phaseData[i];
    });
    this._SD_CORR_PAIRS.forEach((_, i) => {
      this._sdCharts.corr.data.datasets[i].data = corrData[i];
    });
    this._sdCharts.binary.data.datasets[0].data = binaryData;
    this._sdCharts.binary.data.datasets[1].data = thresholdData;
    Object.values(this._sdCharts).forEach(c => c.update('none'));
  }

  _sdFormatDuration(sec) {
    if (sec < 60) return `${Math.round(sec)} сек`;
    if (sec < 3600) return `${Math.round(sec / 60)} мин`;
    if (sec < 86400) return `${(sec / 3600).toFixed(1)} ч`;
    return `${(sec / 86400).toFixed(1)} дн`;
  }

  _sdBindTimeRange() {
    const container = this.root.querySelector('#sd-time-range');
    if (!container) return;
    container.querySelectorAll('.signal-dashboard__range-btn').forEach(btn => {
      const rangeVal = parseInt(btn.dataset.sdRange);
      btn.classList.toggle('active', rangeVal === this._sdSelectedRange);
      // Remove old listener by cloning
      const newBtn = btn.cloneNode(true);
      newBtn.classList.toggle('active', rangeVal === this._sdSelectedRange);
      btn.parentNode.replaceChild(newBtn, btn);
      newBtn.addEventListener('click', async () => {
        container.querySelectorAll('.signal-dashboard__range-btn').forEach(b => b.classList.remove('active'));
        newBtn.classList.add('active');
        this._sdSelectedRange = rangeVal;
        await this._sdBootstrapHistoryFromServer(rangeVal, { force: true });
        this._sdUpdateCharts();
      });
    });
  }

  _sdAddEvent(from, to, confidence) {
    return;
  }

  _sdRenderEventLog() {
    const el = this.root.querySelector('#sd-event-log');
    const countEl = this.root.querySelector('#sd-event-count');
    if (!el) return;
    if (countEl) countEl.textContent = '';
    el.innerHTML = '<div style="color:var(--operator-text-muted); padding:8px 0; text-align:center;">Скрыт на основной поверхности. Показаны только текущие verdict’ы активной модели.</div>';
  }

  _sdBuildHealthPayload(statusData) {
    const dropout = statusData?.dropout_summary || {};
    const quality = statusData?.signal_quality || {};
    const degraded = Array.isArray(dropout?.degraded_nodes) ? dropout.degraded_nodes : [];
    const offline = Array.isArray(dropout?.offline_nodes) ? dropout.offline_nodes : [];
    const flags = [];
    const ampDrift = Number.isFinite(Number(quality?.amp_drift_max)) ? Number(quality.amp_drift_max) : null;
    const phaseJump = Number.isFinite(Number(quality?.phase_jump_max)) ? Number(quality.phase_jump_max) : null;
    const deadSc = Number.isFinite(Number(quality?.dead_sc_max)) ? Number(quality.dead_sc_max) : null;
    const coherence = Number.isFinite(Number(quality?.phase_coherence_mean)) ? Number(quality.phase_coherence_mean) : null;
    if ((degraded.length + offline.length) > 0) {
      flags.push({
        label: offline.length ? 'dropout нод' : 'деградация нод',
        severity: offline.length ? 'risk' : 'warn',
        detail: [...degraded, ...offline].join(', ') || 'часть нод нестабильна'
      });
    }
    if (ampDrift != null && ampDrift >= 0.2) {
      flags.push({
        label: 'common-mode drift',
        severity: ampDrift >= 0.35 ? 'risk' : 'warn',
        detail: `amp ${ampDrift.toFixed(3)}`
      });
    }
    if (phaseJump != null && phaseJump >= 0.25) {
      flags.push({
        label: 'скачки фазы',
        severity: phaseJump >= 0.45 ? 'risk' : 'warn',
        detail: `jump ${phaseJump.toFixed(3)}`
      });
    }
    if (deadSc != null && deadSc >= 0.15) {
      flags.push({
        label: 'dead/null SC',
        severity: deadSc >= 0.3 ? 'risk' : 'warn',
        detail: `dead ${deadSc.toFixed(3)}`
      });
    }
    if (coherence != null && coherence <= 0.55) {
      flags.push({
        label: 'низкая coherence',
        severity: coherence <= 0.4 ? 'risk' : 'warn',
        detail: `coh ${coherence.toFixed(3)}`
      });
    }
    if ((degraded.length + offline.length) === 1 && (Number(dropout?.healthy_total_count || 0) >= 4)) {
      flags.push({
        label: 'single-node glitch',
        severity: 'warn',
        detail: [...degraded, ...offline][0] || 'одна нода выбивается'
      });
    }
    const tone = flags.some(item => item.severity === 'risk')
      ? 'risk'
      : flags.some(item => item.severity === 'warn')
        ? 'warn'
        : 'ok';
    return {
      tone,
      coreOnlineCount: Number(dropout?.core_online_count || 0),
      healthyCoreCount: Number(dropout?.healthy_core_count || 0),
      degraded,
      offline,
      ampDrift,
      phaseJump,
      deadSc,
      coherence,
      flags
    };
  }

  _sdBuildShadowPayload(statusData) {
    const candidate = statusData?.door_center_candidate_shadow || {};
    const prototypeShadow = statusData?.prototype_zone_shadow || {};
    const prototype = prototypeShadow?.last_prediction || prototypeShadow || {};
    const temporal = statusData?.temporal_zone_overlay_shadow || {};
    const stableZone = candidate?.stable_zone || candidate?.stableZone || null;
    const candidateZone = candidate?.candidate_zone || candidate?.zone || null;
    const productionZone = statusData?.target_zone || 'unknown';
    return {
      binary: statusData?.binary_prediction || statusData?.binary || 'unknown',
      primaryZone: stableZone || candidateZone || productionZone,
      productionZone,
      stableZone,
      candidateZone,
      agreement: candidate?.agreement || 'not_ready',
      confidence: Number.isFinite(Number(candidate?.confidence)) ? Number(candidate.confidence) : null,
      prototypeZone: prototype?.zone || prototypeShadow?.zone || null,
      prototypeZoneRaw: prototype?.zone_raw || prototypeShadow?.zone_raw || null,
      temporalZone: temporal?.zone || null,
      thresholdZone: temporal?.threshold_zone || null,
      directionalScore: Number.isFinite(Number(temporal?.directional_score)) ? Number(temporal.directional_score) : null,
      status: candidate?.status || temporal?.status || prototype?.status || prototypeShadow?.status || 'not_ready'
    };
  }

  // ── Signal Quality Summary Card ──
  _sdRenderSignalQualitySummary() {
    const csiRaw = this.snapshot?.csi || {};
    const ttvar = csiRaw.truth_tvar || this._sdTruthTvar || {};
    const t = {
      ...(this._sdTruthOccupancy || {}),
      verdict: ttvar.truth_verdict || this._sdTruthOccupancy?.verdict,
      confidence: Number.isFinite(Number(ttvar.truth_conf)) ? Number(ttvar.truth_conf) : this._sdTruthOccupancy?.confidence,
      tvarMedian: Number.isFinite(Number(ttvar.tvar_median)) ? Number(ttvar.tvar_median) : this._sdTruthOccupancy?.tvarMedian
    };
    const nodesActive = csiRaw.nodes_active != null ? csiRaw.nodes_active : this._sdNodesActive;
    const totalNodes = this._SD_NODE_IDS.length;
    const ppsTotal = csiRaw.pps != null ? parseFloat(csiRaw.pps) : this._sdPpsTotal;
    const tvarMed = t?.tvarMedian;

    // Determine how many nodes have recent data
    const lastEntry = this._sdHistory.length > 0 ? this._sdHistory[this._sdHistory.length - 1] : null;
    let activeCount = nodesActive != null ? nodesActive : 0;
    if (activeCount === 0 && lastEntry) {
      activeCount = this._SD_NODE_IDS.filter(nid => lastEntry.node_tvar?.[nid] != null).length;
    }

    // Color coding: green=all good, yellow=degraded, red=critical
    let qualityTone = 'ok';
    let qualityLabel = 'Healthy';
    if (activeCount < totalNodes * 0.5 || (ppsTotal != null && ppsTotal < 10)) {
      qualityTone = 'risk';
      qualityLabel = 'Critical';
    } else if (activeCount < totalNodes || (ppsTotal != null && ppsTotal < 50)) {
      qualityTone = 'warn';
      qualityLabel = 'Degraded';
    }

    // Determine verdict source
    const backend = csiRaw.decision_model_backend || this._sdDecisionBackend || 'unknown';
    let sourceLabel = 'production';
    if (backend === 'truth_tvar_override') sourceLabel = 'truth_tvar_override';
    else if (backend.includes('diagnostic') || backend.includes('shadow')) sourceLabel = 'diagnostic';

    return `
      <div class="sd-status-card sd-status-card--${qualityTone}" style="border-left:4px solid ${qualityTone === 'ok' ? '#4caf50' : qualityTone === 'warn' ? '#ff9800' : '#ff5252'}">
        <div class="sd-status-card__eyebrow">Signal Quality Summary</div>
        <div class="sd-status-card__headline">${qualityLabel} <span style="font-size:13px;opacity:0.7">${activeCount}/${totalNodes} nodes</span></div>
        <div class="sd-status-card__meta">
          <span>tvar_med=${tvarMed != null ? tvarMed.toFixed(2) : '--'}</span>
          <span>pps=${ppsTotal != null ? ppsTotal.toFixed(0) : '--'}</span>
          <span>source: <b style="color:${sourceLabel === 'truth_tvar_override' ? '#4caf50' : sourceLabel === 'diagnostic' ? '#ab47bc' : 'inherit'}">${escapeHtml(sourceLabel)}</b></span>
        </div>
      </div>
    `;
  }

  // ── Decision Backend Label Card ──
  _sdRenderDecisionBackendCard() {
    const csiRaw = this.snapshot?.csi || {};
    const backend = csiRaw.decision_model_backend || this._sdDecisionBackend;
    const version = csiRaw.decision_model_version || this._sdDecisionModelVersion;
    if (!backend) return '';

    let backendColor = 'inherit';
    let backendTone = 'neutral';
    if (backend === 'truth_tvar_override') {
      backendColor = '#4caf50';
      backendTone = 'ok';
    } else if (backend.includes('v8_empty') || backend.includes('empty_priority')) {
      backendColor = '#ff5252';
      backendTone = 'risk';
    } else if (backend.includes('v48') || backend.includes('random_forest')) {
      backendColor = '#90a4ae';
      backendTone = 'neutral';
    } else if (backend.includes('mesh') || backend.includes('v60')) {
      backendColor = '#4fc3f7';
      backendTone = 'neutral';
    }

    return `
      <div class="sd-status-card sd-status-card--${backendTone}" style="border-left:4px solid ${backendColor}">
        <div class="sd-status-card__eyebrow">Decision Backend</div>
        <div class="sd-status-card__headline" style="font-size:14px;color:${backendColor}">${escapeHtml(backend)}</div>
        <div class="sd-status-card__meta">
          <span>model: ${escapeHtml(version || 'unknown')}</span>
        </div>
      </div>
    `;
  }

  _sdRenderOccupancyPolicyCard() {
    const snapshot = this.snapshot || {};
    const csiRaw = snapshot.csi || {};
    const primaryRuntime = snapshot?.live?.primaryRuntime || {};
    const truthTvar = csiRaw.truth_tvar || this._sdTruthTvar || {};
    const emptySubregime = snapshot?.live?.emptySubregimeShadow
      || snapshot?.live?.empty_subregime_shadow
      || csiRaw.empty_subregime_shadow
      || csiRaw.emptySubregimeShadow
      || {};
    const v8Shadow = snapshot?.live?.v8Shadow || snapshot?.live?.v7Shadow || snapshot?.live?.v15Shadow || {};
    const backend = String(csiRaw.decision_model_backend || this._sdDecisionBackend || 'unknown');
    const primaryBinary = primaryRuntime.binary || csiRaw.binary || 'unknown';
    const primaryZone = primaryRuntime.targetZone || primaryRuntime.zone || csiRaw.target_zone || csiRaw.zone || 'unknown';
    const primaryMotion = primaryRuntime.motionState || csiRaw.motion_state || 'unknown';

    const policyMode = backend.includes('truth_tvar')
      ? (truthTvar.override_fired ? 'truth_tvar_override' : 'truth_tvar_review')
      : backend.includes('v8_empty') || backend.includes('empty_priority')
        ? 'v8_empty_guard'
        : backend.includes('track_b')
          ? 'track_b_shadow'
          : backend.includes('hysteresis')
            ? 'hysteresis'
            : 'production';
    const tone = policyMode === 'truth_tvar_override' ? 'ok' : policyMode === 'v8_empty_guard' ? 'warn' : 'neutral';

    const primaryChips = [
      `binary=${primaryBinary}`,
      `zone=${primaryZone}`,
      `motion=${primaryMotion}`
    ];
    return `
      <div class="sd-status-card sd-status-card--${tone}">
        <div class="sd-status-card__eyebrow">Runtime policy / occupancy</div>
        <div class="sd-status-card__headline">${escapeHtml(policyMode)}</div>
        <div class="sd-status-card__detail">
          backend=${escapeHtml(backend)} · показан только активный production/latest-model verdict без shadow и fallback слоёв.
        </div>
        <div class="sd-status-card__chips" style="margin-top:10px">
          ${primaryChips.map((chip) => `<span class="sd-flag-chip sd-flag-chip--ok">${escapeHtml(chip)}</span>`).join('')}
        </div>
      </div>
    `;
  }

  _sdRenderShadowZonePathsCard() {
    const snapshot = this.snapshot || {};
    const csiRaw = snapshot.csi || {};
    const paths = [
      {
        id: 'prototype_zone_shadow',
        label: 'prototype',
        value: snapshot?.live?.prototypeZoneShadow || snapshot?.live?.prototype_zone_shadow || csiRaw.prototype_zone_shadow || csiRaw.prototypeZoneShadow || {}
      },
      {
        id: 'temporal_zone_overlay_shadow',
        label: 'temporal',
        value: snapshot?.live?.temporalZoneOverlayShadow || snapshot?.live?.temporal_zone_overlay_shadow || csiRaw.temporal_zone_overlay_shadow || csiRaw.temporalZoneOverlayShadow || {}
      },
      {
        id: 'garage_ratio_v3_shadow',
        label: 'garage_ratio_v3',
        value: snapshot?.live?.garageRatioV3Shadow || snapshot?.live?.garage_ratio_v3_shadow || csiRaw.garage_ratio_v3_shadow || csiRaw.garageRatioV3Shadow || {}
      },
      {
        id: 'garage_ratio_v2_shadow',
        label: 'garage_ratio_v2',
        value: snapshot?.live?.garageRatioV2Shadow || snapshot?.live?.garage_ratio_v2_shadow || csiRaw.garage_ratio_v2_shadow || csiRaw.garageRatioV2Shadow || {}
      },
      {
        id: 'door_center_candidate_shadow',
        label: 'door_center_candidate',
        value: snapshot?.live?.doorCenterCandidateShadow || snapshot?.live?.door_center_candidate_shadow || csiRaw.door_center_candidate_shadow || csiRaw.doorCenterCandidateShadow || {}
      }
    ];

    const readZone = (value) => {
      const zone = value?.zone
        || value?.targetZone
        || value?.predictedZone
        || value?.candidate_zone
        || value?.stable_zone
        || value?.candidateZone
        || value?.stableZone
        || value?.rawPredictedZone
        || value?.raw_predicted_zone
        || value?.zone_raw
        || value?.predicted_zone
        || value?.last_prediction?.zone
        || value?.lastPrediction?.zone
        || 'n/a';
      const detail = [
        value?.status || null,
        value?.agreement ? `agr=${value.agreement}` : null,
        value?.directionalScore != null ? `dir=${Number(value.directionalScore).toFixed(3)}` : null,
        value?.candidate_name || value?.candidateName || null
      ].filter(Boolean).join(' · ');
      return { zone: String(zone || 'n/a'), detail: String(detail || '').trim() };
    };

    return `
      <div class="sd-status-card sd-status-card--warn">
        <div class="sd-status-card__eyebrow">Shadow-only zone paths</div>
        <div class="sd-status-card__headline">prototype · temporal · garage ratio · door-center</div>
        <div class="sd-status-card__detail">
          Показаны только shadow-пути зоны. Production target_zone здесь не меняется и остаётся боевым.
        </div>
        <div class="sd-status-card__chips" style="margin-top:10px">
          ${paths.map((path) => {
            const { zone, detail } = readZone(path.value);
            const hasZone = zone && zone !== 'n/a' && zone !== 'unknown';
            const chipTone = hasZone ? 'ok' : 'risk';
            const chipTitle = detail ? `${path.id} · ${detail}` : path.id;
            return `<span class="sd-flag-chip sd-flag-chip--${chipTone}" title="${escapeHtml(chipTitle)}">${escapeHtml(`${path.label}=${zone}`)}</span>`;
          }).join('')}
        </div>
      </div>
    `;
  }

  // ── Multi-Person Count Indicator ──
  _sdRenderMultiPersonCard() {
    const mp = this._sdMultiPerson;
    if (!mp || mp.person_count == null) return '';

    const count = mp.person_count;
    const conf = mp.confidence != null ? (mp.confidence * 100).toFixed(0) : '--';
    const source = mp.source || 'unknown';
    const tone = count > 1 ? 'warn' : 'neutral';

    return `
      <div class="sd-status-card sd-status-card--${tone}">
        <div class="sd-status-card__eyebrow">Multi-Person Count <span style="font-size:10px;opacity:0.6">(diagnostic estimate)</span></div>
        <div class="sd-status-card__headline">${count} ${count === 1 ? 'person' : 'persons'} <span style="font-size:13px;opacity:0.7">${conf}%</span></div>
        <div class="sd-status-card__meta">
          <span>source: ${escapeHtml(source)}</span>
        </div>
      </div>
    `;
  }

  // ── Raw Feature Gauges ──
  _sdRenderRawFeatureGauges() {
    const t = this._sdTruthOccupancy;
    if (!t) return '';

    const tvarMed = t.tvarMedian;
    const ampStdMed = t.ampStdMedian;
    const rssiStdMed = t.rssiStdMedian;
    const ppsTotal = this._sdPpsTotal;

    const makeGauge = (label, value, max, threshold, unit) => {
      const pct = value != null ? Math.min(100, Math.max(0, (value / max) * 100)) : 0;
      const threshPct = threshold != null ? Math.min(100, (threshold / max) * 100) : null;
      const valStr = value != null ? value.toFixed(2) : '--';
      const overThresh = threshold != null && value != null && value > threshold;
      const barColor = overThresh ? '#ff9800' : '#4caf50';
      return `
        <div style="flex:1;min-width:110px;max-width:180px">
          <div style="font-size:10px;opacity:0.6;margin-bottom:2px">${escapeHtml(label)}</div>
          <div style="font-size:14px;font-weight:600;margin-bottom:3px">${valStr}<span style="font-size:10px;opacity:0.5"> ${escapeHtml(unit)}</span></div>
          <div style="background:rgba(255,255,255,0.08);border-radius:3px;height:8px;position:relative;overflow:hidden">
            ${threshPct != null ? `<div style="position:absolute;left:${threshPct}%;top:0;bottom:0;width:1px;background:#ff5252;z-index:2" title="threshold ${threshold}"></div>` : ''}
            <div style="width:${pct}%;height:100%;background:${barColor};border-radius:3px;transition:width 0.3s"></div>
          </div>
        </div>
      `;
    };

    return `
      <div style="display:flex;gap:12px;flex-wrap:wrap;padding:8px 0;border-top:1px solid rgba(255,255,255,0.06);margin-top:4px">
        ${makeGauge('TVAR median', tvarMed, 15, TRUTH_TVAR_UI_THRESHOLD, '')}
        ${makeGauge('AMP_STD median', ampStdMed, 10, null, '')}
        ${makeGauge('RSSI_STD median', rssiStdMed, 10, null, '')}
        ${makeGauge('PPS total', ppsTotal, 200, null, 'p/s')}
      </div>
    `;
  }

  _sdRenderTruthOccupancyCard() {
    const csiRaw = this.snapshot?.csi || {};
    const ttvar = csiRaw.truth_tvar || this._sdTruthTvar || {};
    const v8guard = csiRaw.v8_empty_priority_guard || this._sdV8Guard || {};
    const t = {
      ...(this._sdTruthOccupancy || {}),
      verdict: ttvar.truth_verdict || this._sdTruthOccupancy?.verdict,
      confidence: Number.isFinite(Number(ttvar.truth_conf)) ? Number(ttvar.truth_conf) : this._sdTruthOccupancy?.confidence,
      tvarMedian: Number.isFinite(Number(ttvar.tvar_median)) ? Number(ttvar.tvar_median) : this._sdTruthOccupancy?.tvarMedian
    };
    if (!t || t.verdict === 'unknown') {
      return `
        <div class="sd-status-card sd-status-card--neutral">
          <div class="sd-status-card__eyebrow">Truth-backed Occupancy (TVAR)</div>
          <div class="sd-status-card__headline">Ожидание данных...</div>
          <div class="sd-status-card__detail">Нужно минимум 3 ноды с tvar > 0</div>
        </div>
      `;
    }

    const tone = t.verdict === 'occupied' ? 'warn' : 'ok';
    const verdictLabel = t.verdict === 'occupied' ? 'OCCUPIED' : 'EMPTY';
    const confPct = Math.round(t.confidence * 100);
    const tvarStr = t.tvarMedian != null ? t.tvarMedian.toFixed(2) : '--';
    const ampStdStr = t.ampStdMedian != null ? t.ampStdMedian.toFixed(2) : '--';
    const rssiStdStr = t.rssiStdMedian != null ? t.rssiStdMedian.toFixed(2) : '--';

    // Visual bar for tvar relative to thresholds
    const barPct = Math.min(100, Math.max(0, (t.tvarMedian / 10) * 100));
    const threshPct = (TRUTH_TVAR_UI_THRESHOLD / 10) * 100;
    const overrideFired = ttvar.override_fired === true;
    const v8Vetoed = v8guard.truth_tvar_veto === true;

    // Node-by-node tvar sparkline bars
    const nodeTvars = ttvar.node_tvars || {};
    const nodeTvarBars = Object.entries(nodeTvars).map(([nid, val]) => {
      const pct = Math.min(100, Math.max(0, (val / 15) * 100));
      const color = val > TRUTH_TVAR_UI_THRESHOLD ? '#ff9800' : '#4caf50';
      const label = nid.replace('node', 'n');
      return `<span style="display:inline-flex;align-items:center;gap:2px;font-size:10px;margin-right:4px" title="${nid}: ${val}">
        <span style="opacity:0.6">${label}</span>
        <span style="display:inline-block;width:30px;height:6px;background:rgba(255,255,255,0.1);border-radius:3px;position:relative;overflow:hidden">
          <span style="position:absolute;left:0;top:0;bottom:0;width:${pct}%;background:${color};border-radius:3px"></span>
        </span>
      </span>`;
    }).join('');

    return `
      <div class="sd-status-card sd-status-card--${tone}" style="border-left:4px solid ${t.verdict === 'occupied' ? '#ff9800' : '#4caf50'}">
        <div class="sd-status-card__eyebrow">Truth-backed Occupancy (TVAR threshold)</div>
        <div class="sd-status-card__headline" style="font-size:18px">${verdictLabel} <span style="font-size:13px;opacity:0.7">${confPct}%</span></div>
        ${overrideFired ? `<div style="margin:4px 0;padding:3px 8px;border-radius:4px;background:rgba(76,175,80,0.2);border:1px solid rgba(76,175,80,0.4);font-size:11px;font-weight:600;color:#4caf50">TVAR OVERRIDE ACTIVE <span style="font-weight:400;opacity:0.8">truth_verdict=${escapeHtml(ttvar.truth_verdict || '--')}, conf=${(ttvar.truth_conf || 0).toFixed(2)}</span></div>` : ''}
        ${v8Vetoed ? `<div style="margin:4px 0;padding:3px 8px;border-radius:4px;background:rgba(255,82,82,0.15);border:1px solid rgba(255,82,82,0.3);font-size:11px;color:#ff5252">V8 empty guard VETOED by TVAR <span style="opacity:0.7">(tvar_med=${v8guard.truth_tvar_median || '--'})</span></div>` : ''}
        <div style="margin:6px 0;background:rgba(255,255,255,0.08);border-radius:4px;height:12px;position:relative;overflow:hidden">
          <div style="position:absolute;left:${threshPct}%;top:0;bottom:0;width:2px;background:#ff5252;z-index:2" title="threshold ${TRUTH_TVAR_UI_THRESHOLD.toFixed(1)}"></div>
          <div style="width:${barPct}%;height:100%;background:${t.verdict === 'occupied' ? '#ff9800' : '#4caf50'};border-radius:4px;transition:width 0.3s"></div>
        </div>
        <div class="sd-status-card__meta">
          <span>tvar_med=${tvarStr}</span>
          <span>amp_std=${ampStdStr}</span>
          <span>rssi_std=${rssiStdStr}</span>
        </div>
        ${nodeTvarBars ? `<div style="margin:4px 0;line-height:1.6">${nodeTvarBars}</div>` : ''}
        <div class="sd-status-card__detail">
          Порог: tvar_median ≥ ${TRUTH_TVAR_UI_THRESHOLD.toFixed(1)} = occupied. Основано на truth-backed анализе текущего runtime.
        </div>
      </div>
    `;
  }

  _sdRenderStatusStrip() {
    const container = this.root.querySelector('#sd-status-strip');
    if (!container) return;
    const health = this._sdHealth;
    const shadow = this._sdShadow;
    if (!health && !shadow) {
      container.innerHTML = `
        <div class="sd-status-card sd-status-card--neutral">
          <div class="sd-status-card__eyebrow">Runtime</div>
          <div class="sd-status-card__headline">Ожидание данных...</div>
          <div class="sd-status-card__detail">Поднимаю live-статус и активную production-модель.</div>
        </div>
      `;
      return;
    }
    const healthTone = health?.tone || 'neutral';
    const flags = Array.isArray(health?.flags) ? health.flags : [];
    const sigQualHtml = this._sdRenderSignalQualitySummary();
    const occupancyPolicyHtml = this._sdRenderOccupancyPolicyCard();
    const backendHtml = this._sdRenderDecisionBackendCard();

    container.innerHTML = `
      ${sigQualHtml}
      ${occupancyPolicyHtml}
      <div class="sd-status-card sd-status-card--${healthTone}">
        <div class="sd-status-card__eyebrow">Здоровье узлов</div>
        <div class="sd-status-card__headline">${escapeHtml(`${health?.healthyCoreCount ?? 0}/${health?.coreOnlineCount ?? 0} core online`)}</div>
        <div class="sd-status-card__detail">
          degraded: ${escapeHtml((health?.degraded || []).join(', ') || '\u043D\u0435\u0442')} \u00B7 \u043D\u0435\u0434\u043E\u0441\u0442\u0443\u043F\u043D\u044B: ${escapeHtml((health?.offline || []).join(', ') || '\u043D\u0435\u0442')}
        </div>
        <div class="sd-status-card__meta">
          <span>amp drift=${escapeHtml(health?.ampDrift != null ? health.ampDrift.toFixed(3) : '--')}</span>
          <span>phase jump=${escapeHtml(health?.phaseJump != null ? health.phaseJump.toFixed(3) : '--')}</span>
          <span>coh=${escapeHtml(health?.coherence != null ? health.coherence.toFixed(3) : '--')}</span>
        </div>
      </div>
      <div class="sd-status-card sd-status-card--${flags.length ? healthTone : 'ok'}">
        <div class="sd-status-card__eyebrow">Anomaly flags</div>
        <div class="sd-status-card__headline">${flags.length ? `${flags.length} flags` : 'stable'}</div>
        <div class="sd-status-card__chips">
          ${flags.length
            ? flags.map((flag) => `<span class="sd-flag-chip sd-flag-chip--${escapeHtml(flag.severity)}" title="${escapeHtml(flag.detail || '')}">${escapeHtml(flag.label)}</span>`).join('')
            : '<span class="sd-flag-chip sd-flag-chip--ok">без аномалий</span>'}
        </div>
        <div class="sd-status-card__detail">
          ${flags.length ? escapeHtml(flags.map((flag) => `${flag.label}: ${flag.detail}`).join(' · ')) : 'Общий сдвиг и packet-glitch сейчас не детектируются.'}
        </div>
      </div>
      ${backendHtml}
    `;
  }

  async _sdPollData() {
    const [statusData, nodesData] = await Promise.all([
      this._fetchRuntimeUiJson('/api/v1/csi/status'),
      this._fetchRuntimeUiJson('/api/v1/csi/nodes/live')
    ]);
    const hasLiveWindow = Boolean(
      (safeNumber(statusData?.pps, 0) || 0) > 0
      || (safeNumber(statusData?.packets_in_window, 0) || 0) > 0
      || (safeNumber(statusData?.nodes_active, 0) || 0) > 0
    );
    const featData = this._runtimeUiOptionalSurface.csiFeaturesEnabled && hasLiveWindow
      ? await this._fetchRuntimeUiJson('/api/v1/csi/features')
      : null;
    const now = Date.now();
    const entry = {
      timestamp: now,
      node_rssi: {},
      node_amp: {},
      node_tvar: {},
      correlations: {},
      phase_stds: {},
      binary_prob: null
    };
    let binary = 'unknown';
    let binaryConf = 0;
    if (statusData) {
      binary = statusData.binary || 'unknown';
      binaryConf = parseFloat(statusData.binary_confidence || 0);
      this._sdHealth = this._sdBuildHealthPayload(statusData);
      this._sdShadow = this._sdBuildShadowPayload(statusData);
      if (binary === 'occupied') entry.binary_prob = binaryConf;
      else if (binary === 'empty') entry.binary_prob = 1.0 - binaryConf;
      else entry.binary_prob = 0.5;
      if (this._sdLastBinary !== null && this._sdLastBinary !== binary && binary !== 'unknown') {
        this._sdAddEvent(this._sdLastBinary, binary, binaryConf);
      }
      if (binary !== 'unknown') this._sdLastBinary = binary;
      // Extract telemetry fields for enhanced panels
      this._sdTruthTvar = statusData.truth_tvar || null;
      this._sdMultiPerson = statusData.multi_person || null;
      this._sdDecisionBackend = statusData.decision_model_backend || null;
      this._sdDecisionModelVersion = statusData.decision_model_version || null;
      this._sdV8Guard = statusData.v8_empty_priority_guard || null;
      this._sdPpsTotal = statusData.pps != null ? parseFloat(statusData.pps) : null;
      this._sdNodesActive = statusData.nodes_active != null ? statusData.nodes_active : null;
    }
    if (nodesData && nodesData.nodes) {
      nodesData.nodes.forEach(n => {
        const nid = n.node_id;
        if (!this._SD_NODE_IDS.includes(nid)) return;
        entry.node_rssi[nid] = n.rssi != null ? n.rssi : null;
        entry.node_amp[nid] = n.amp_mean != null ? n.amp_mean : null;
        entry.node_tvar[nid] = n.temporal_var != null ? n.temporal_var : null;
        const nodePps = n.packets_window != null ? n.packets_window / 2.0 : null;
        this._sdUpdateNodeCard(nid, {
          online: n.online,
          rssi: n.rssi,
          amp_mean: n.amp_mean,
          temporal_var: n.temporal_var,
          phase_std: null,
          pps: nodePps,
          packets: n.packets
        });
      });
    }
    if (featData && featData.features) {
      const f = featData.features;
      this._SD_NODE_IDS.forEach((nid, ni) => {
        const phaseKey = `${nid}_phase_std`;
        const phaseKey2 = `csi_${nid}_phase_std`;
        const phaseKey3 = `n${ni}_sq_phase_jump_rate`;
        const phaseKey4 = `${nid}_phase_coherence`;
        const val = f[phaseKey] ?? f[phaseKey2] ?? f[phaseKey3] ?? f[phaseKey4] ?? null;
        if (val != null) {
          entry.phase_stds[nid] = parseFloat(val);
          const el = this.root.querySelector(`#sd-nc-phase-${nid}`);
          if (el) el.textContent = parseFloat(val).toFixed(3);
        }
        if (entry.node_rssi[nid] == null && f[`${nid}_rssi_mean`] != null) {
          entry.node_rssi[nid] = parseFloat(f[`${nid}_rssi_mean`]);
        }
        if (entry.node_amp[nid] == null && f[`${nid}_amp_mean`] != null) {
          entry.node_amp[nid] = parseFloat(f[`${nid}_amp_mean`]);
        }
        if (entry.node_tvar[nid] == null && f[`${nid}_tvar`] != null) {
          entry.node_tvar[nid] = parseFloat(f[`${nid}_tvar`]);
        }
      });
      this._SD_CORR_PAIRS.forEach(([a, b]) => {
        const key = `corr_${a}_${b}`;
        const key2 = `corr_${b}_${a}`;
        const val = f[key] ?? f[key2] ?? null;
        if (val != null) entry.correlations[key] = parseFloat(val);
      });
    }
    this._sdTruthOccupancy = null;
    this._sdRenderStatusStrip();

    this._sdHistory.push(entry);
    if (this._sdHistory.length % 10 === 0) this._sdSaveHistory();
    this._sdUpdateCharts();
  }

  // ============================================================
  //  Truth-backed occupancy detector (client-side fallback only)
  //  Uses TVAR median as primary discriminator and mirrors runtime
  //  thresholds as closely as possible.
  // ============================================================

  _sdComputeTruthOccupancy(entry) {
    const tvars = [];
    const ampStds = [];
    const rssiStds = [];
    this._SD_NODE_IDS.forEach(nid => {
      const tvar = entry.node_tvar?.[nid];
      if (tvar != null && tvar > 0) tvars.push(tvar);
    });

    // Also compute amp_std and rssi_std from recent history (last 5 entries)
    const recentLen = Math.min(5, this._sdHistory.length);
    if (recentLen >= 2) {
      this._SD_NODE_IDS.forEach(nid => {
        const vals = [];
        const rssiVals = [];
        for (let i = this._sdHistory.length - recentLen; i < this._sdHistory.length; i++) {
          const h = this._sdHistory[i];
          if (h.node_amp?.[nid] != null) vals.push(h.node_amp[nid]);
          if (h.node_rssi?.[nid] != null) rssiVals.push(h.node_rssi[nid]);
        }
        if (vals.length >= 2) {
          const mean = vals.reduce((a, b) => a + b, 0) / vals.length;
          const std = Math.sqrt(vals.reduce((a, v) => a + (v - mean) ** 2, 0) / vals.length);
          ampStds.push(std);
        }
        if (rssiVals.length >= 2) {
          const mean = rssiVals.reduce((a, b) => a + b, 0) / rssiVals.length;
          const std = Math.sqrt(rssiVals.reduce((a, v) => a + (v - mean) ** 2, 0) / rssiVals.length);
          rssiStds.push(std);
        }
      });
    }

    if (tvars.length < 3) {
      return { verdict: 'unknown', tvarMedian: null, ampStdMedian: null, rssiStdMedian: null, confidence: 0, reason: 'insufficient_nodes' };
    }

    tvars.sort((a, b) => a - b);
    const tvarMedian = tvars[Math.floor(tvars.length / 2)];

    ampStds.sort((a, b) => a - b);
    const ampStdMedian = ampStds.length > 0 ? ampStds[Math.floor(ampStds.length / 2)] : null;

    rssiStds.sort((a, b) => a - b);
    const rssiStdMedian = rssiStds.length > 0 ? rssiStds[Math.floor(rssiStds.length / 2)] : null;

    // Decision: tvar_median is the primary feature (zero overlap in truth data)
    // Runtime uses a stricter occupied threshold of 4.0.
    const TVAR_THRESHOLD = TRUTH_TVAR_UI_THRESHOLD;
    const TVAR_CONFIDENT_OCCUPIED = TRUTH_TVAR_UI_CONFIDENT_OCCUPIED;
    const TVAR_CONFIDENT_EMPTY = TRUTH_TVAR_UI_CONFIDENT_EMPTY;

    let verdict;
    let confidence;
    if (tvarMedian >= TVAR_CONFIDENT_OCCUPIED) {
      verdict = 'occupied';
      confidence = Math.min(1.0, 0.8 + (tvarMedian - TVAR_CONFIDENT_OCCUPIED) * 0.04);
    } else if (tvarMedian >= TVAR_THRESHOLD) {
      verdict = 'occupied';
      confidence = 0.6 + (tvarMedian - TVAR_THRESHOLD) / (TVAR_CONFIDENT_OCCUPIED - TVAR_THRESHOLD) * 0.2;
    } else if (tvarMedian <= TVAR_CONFIDENT_EMPTY) {
      verdict = 'empty';
      confidence = Math.min(1.0, 0.8 + (TVAR_CONFIDENT_EMPTY - tvarMedian) * 0.2);
    } else {
      // Gray zone between empty and occupied thresholds
      verdict = 'empty';
      confidence = 0.5 + (TVAR_THRESHOLD - tvarMedian) / (TVAR_THRESHOLD - TVAR_CONFIDENT_EMPTY) * 0.3;
    }

    return { verdict, tvarMedian, ampStdMedian, rssiStdMedian, confidence, reason: 'tvar_threshold' };
  }

  renderModel() {
    const truth = AGENT7_OPERATOR_TRUTH;
    const primaryRuntime = this.snapshot?.live?.primaryRuntime || {};
    const trackBShadow = this.snapshot?.live?.trackBShadow || {};
    const v15Shadow = this.snapshot?.live?.v8Shadow || this.snapshot?.live?.v7Shadow || this.snapshot?.live?.v15Shadow || {};
    const v27Binary7NodeShadow = this.snapshot?.live?.v27Binary7NodeShadow || {};
    const zoneCalibrationShadow = this.snapshot?.live?.zoneCalibrationShadow || {};
    const garageRatioV2Shadow = this.snapshot?.live?.garageRatioV2Shadow || {};
    const emptySubregimeShadow = this.snapshot?.live?.emptySubregimeShadow || {};
    const fewshotCalibration = this.snapshot?.recording?.fewshotCalibration || {};
    const runtimeModels = this.snapshot?.runtimeModels || {};
    const models = Array.isArray(runtimeModels.items) ? runtimeModels.items : [];
    const sortedModels = sortRuntimeModelsByFreshness(models);
    const latestRuntimeModel = sortedModels[0] || null;
    const zoneGate = buildDoorCenterCalibrationGate(zoneCalibrationShadow, fewshotCalibration);
    const trackAConnected = Boolean(primaryRuntime.running && primaryRuntime.modelLoaded);
    const selectedRuntimeView = this.runtimeViewSelection === UI_RUNTIME_VIEW_OPTIONS.TRACK_B
      ? UI_RUNTIME_VIEW_OPTIONS.TRACK_B
      : this.runtimeViewSelection === UI_RUNTIME_VIEW_OPTIONS.V15
        ? UI_RUNTIME_VIEW_OPTIONS.V15
        : this.runtimeViewSelection === UI_RUNTIME_VIEW_OPTIONS.V27_7NODE
          ? UI_RUNTIME_VIEW_OPTIONS.V27_7NODE
        : this.runtimeViewSelection === UI_RUNTIME_VIEW_OPTIONS.GARAGE_V2
          ? UI_RUNTIME_VIEW_OPTIONS.GARAGE_V2
        : UI_RUNTIME_VIEW_OPTIONS.TRACK_A;
    const trackBHeadline = trackBShadow.predictedClass
      ? String(trackBShadow.predictedClass).toLowerCase()
      : (trackBShadow.status || 'unknown');
    const v15Headline = v15Shadow.predictedClass
      ? String(v15Shadow.predictedClass).toLowerCase()
      : (v15Shadow.status || 'unknown');
    const v27BinaryHeadline = v27Binary7NodeShadow.binary
      ? String(v27Binary7NodeShadow.binary).toLowerCase()
      : (v27Binary7NodeShadow.status || 'unknown');
    const binary7NodeCandidateName = v27Binary7NodeShadow.candidateName || v27Binary7NodeShadow.track || 'V42 binary balanced';
    const garageV2Headline = garageRatioV2Shadow.predictedZone
      ? String(garageRatioV2Shadow.predictedZone).toLowerCase()
      : (garageRatioV2Shadow.status || 'unknown');
    const catalogSummary = runtimeModels.loading
      ? UI_LOCALE.models.loading
      : (runtimeModels.actionError || runtimeModels.error)
        ? `${UI_LOCALE.models.actionErrorPrefix} ${runtimeModels.actionError || runtimeModels.error}`
        : UI_LOCALE.models.catalogSummary;
    const latestModelHeadline = latestRuntimeModel?.displayName || latestRuntimeModel?.fileName || 'последняя модель не найдена';
    const latestModelButtonLabel = latestRuntimeModel?.isActive
      ? 'Последняя уже активна'
      : runtimeModels.switching
        ? UI_LOCALE.models.switching
        : 'Сделать последнюю активной';
    const latestModelBadges = latestRuntimeModel ? [
      'последняя',
      latestRuntimeModel.isActive ? UI_LOCALE.models.currentBadge : null,
      latestRuntimeModel.isDefault ? UI_LOCALE.models.defaultBadge : null,
      latestRuntimeModel.loaded ? UI_LOCALE.models.loadedBadge : UI_LOCALE.models.notLoadedBadge,
      latestRuntimeModel.kind || null
    ].filter(Boolean) : [];

    const fewshotZone = this.snapshot?.live?.primaryRuntime || {};
    const fewshotZoneModel = fewshotZone.zoneModel || null;
    const fewshotZoneName = fewshotZone.targetZone || 'unknown';
    const fewshotZoneProbs = fewshotZone.zoneProbabilities || {};
    const fewshotActive = fewshotZoneModel === 'v30_fewshot';

    this.sections.model.innerHTML = `
      <div class="surface-grid surface-grid--four">
        <article class="panel" style="${fewshotActive ? 'border-color: rgba(34, 197, 94, 0.4); box-shadow: 0 0 12px rgba(34, 197, 94, 0.08)' : ''}">
          <div class="panel__eyebrow">V39 fewshot zone — production zone override</div>
          <div class="panel__headline">${escapeHtml(displayMaybeToken(fewshotActive ? fewshotZoneName : 'оффлайн'))}</div>
          <div class="kv-list">
            <div class="kv"><span>Файл</span><strong>v39_fewshot_zone_calibration.pkl</strong></div>
            <div class="kv"><span>Архитектура</span><strong>RandomForest / 26 фич (amp_norm + ratios) / 7 узлов</strong></div>
            <div class="kv"><span>CV balanced accuracy</span><strong>98.62% (1229 окон)</strong></div>
            <div class="kv"><span>Обучающая выборка</span><strong>1229 окон / 3 сессии (614 center / 615 door_passage)</strong></div>
            <div class="kv"><span>Зоны</span><strong>center / door_passage</strong></div>
            <div class="kv"><span>Зона сейчас</span><strong>${escapeHtml(displayMaybeToken(fewshotZoneName))}${Object.keys(fewshotZoneProbs).length ? ' (' + Object.entries(fewshotZoneProbs).map(([k, v]) => k + ': ' + (v * 100).toFixed(0) + '%').join(' / ') + ')' : ''}</strong></div>
            <div class="kv"><span>zone_model backend</span><strong>${escapeHtml(fewshotZoneModel || 'не подключено')}</strong></div>
            <div class="kv"><span>Статус</span><strong>${fewshotActive ? 'активна / production override' : 'оффлайн (бэкенд не запущен)'}</strong></div>
          </div>
          <div class="panel__footer">V39 — RF zone-модель на 26 drift-invariant фичах (amp_norm + inter-node ratios), 1229 окон из 3 сессий. CV BA=0.9862. Production zone override поверх Track A.</div>
        </article>

        <article class="panel">
          <div class="panel__eyebrow">Основной runtime-контракт</div>
          <div class="panel__headline">runtime только по движению</div>
          <div class="kv-list">
            <div class="kv"><span>Основное состояние</span><strong>MOTION_DETECTED / NO_MOTION</strong></div>
            <div class="kv"><span>Поле confidence</span><strong>motion_confidence</strong></div>
            <div class="kv"><span>Текущая модель</span><strong>${escapeHtml(primaryRuntime.modelVersion || UI_LOCALE.common.unknown)}</strong></div>
            <div class="kv"><span>Активный bundle</span><strong>${escapeHtml(runtimeModels.activeModelId || primaryRuntime.modelId || 'bundle не выбран')}</strong></div>
            <div class="kv"><span>Вторичные поля</span><strong>binary / coarse</strong></div>
            <div class="kv"><span>Track A runtime</span><strong>${trackAConnected ? 'подключён / боевой' : 'оффлайн'}</strong></div>
          </div>
          <div class="panel__footer">Track A остаётся текущим production runtime и именно он сейчас выдаёт боевой motion verdict.</div>
        </article>

        <article class="panel">
          <div class="panel__eyebrow">Track B v1 кандидат</div>
          <div class="panel__headline">${escapeHtml(displayMaybeToken(trackBHeadline))}</div>
          <div class="kv-list">
            <div class="kv"><span>Статус</span><strong>${escapeHtml(displayMaybeToken(trackBShadow.status || 'unknown'))} / ${escapeHtml(trackBShadow.loaded ? 'модель загружена' : 'модель не загружена')}</strong></div>
            <div class="kv"><span>Режим</span><strong>только shadow</strong></div>
            <div class="kv"><span>Архитектура</span><strong>raw CSI TCN</strong></div>
            <div class="kv"><span>Последний класс</span><strong>${escapeHtml(displayMaybeToken(trackBHeadline))}</strong></div>
            <div class="kv"><span>Время inference</span><strong>${escapeHtml(formatNumberWithUnit(trackBShadow.inferenceMs, { digits: 2, unit: ' ms', missing: 'ещё нет окна' }))}</strong></div>
          </div>
          <div class="panel__footer">Этот кандидат уже подключён в runtime для тестов, но не участвует в production routing и не появляется в selector каталога Track A‑моделей.</div>
        </article>

        <article class="panel">
          <div class="panel__eyebrow">V8 canonical кандидат</div>
          <div class="panel__headline">${escapeHtml(displayMaybeToken(v15Headline))}</div>
          <div class="kv-list">
            <div class="kv"><span>Статус</span><strong>${escapeHtml(displayMaybeToken(v15Shadow.status || 'unknown'))} / ${escapeHtml(v15Shadow.loaded ? 'модель загружена' : 'модель не загружена')}</strong></div>
            <div class="kv"><span>Режим</span><strong>только shadow / тестовый режим</strong></div>
            <div class="kv"><span>Архитектура</span><strong>warehouse-bound HGB + F2 spectral, seq_len=7</strong></div>
            <div class="kv"><span>Последний класс</span><strong>${escapeHtml(displayMaybeToken(v15Headline))}</strong></div>
            <div class="kv"><span>Буфер / warmup</span><strong>${escapeHtml(formatNumber(v15Shadow.bufferDepth))}/7 / ${escapeHtml(formatNumber(v15Shadow.warmupRemaining))} до ready</strong></div>
            <div class="kv"><span>Время inference</span><strong>${escapeHtml(formatNumberWithUnit(v15Shadow.inferenceMs, { digits: 2, unit: ' ms', missing: 'ещё нет seq=7' }))}</strong></div>
          </div>
          <div class="panel__footer">Именно этот кандидат сейчас нужен для полевого теста. Он уже живёт в runtime shadow и показывается в UI отдельно от Track A selector.</div>
        </article>

        <article class="panel">
          <div class="panel__eyebrow">${escapeHtml(binary7NodeCandidateName)}</div>
          <div class="panel__headline">${escapeHtml(displayMaybeToken(v27BinaryHeadline))}</div>
          <div class="kv-list">
            <div class="kv"><span>Статус</span><strong>${escapeHtml(displayMaybeToken(v27Binary7NodeShadow.status || 'unknown'))} / ${escapeHtml(v27Binary7NodeShadow.loaded ? 'модель загружена' : 'модель не загружена')}</strong></div>
            <div class="kv"><span>Режим</span><strong>binary кандидат / UI тест‑режим</strong></div>
            <div class="kv"><span>Поле backend</span><strong>${escapeHtml(v27Binary7NodeShadow.sourceField || 'v26_shadow')}</strong></div>
            <div class="kv"><span>Последний binary</span><strong>${escapeHtml(displayMaybeToken(v27BinaryHeadline))}</strong></div>
            <div class="kv"><span>Дверь‑центр</span><strong>${escapeHtml(zoneGate.state)} / ${escapeHtml(zoneGate.detail)}</strong></div>
            <div class="kv"><span>P(occupied) / порог</span><strong>${escapeHtml(formatPercent(v27Binary7NodeShadow.occupiedProbability, 0))} / ${escapeHtml(formatNumber(v27Binary7NodeShadow.threshold, 3))}</strong></div>
            <div class="kv"><span>Согласие с primary</span><strong>${escapeHtml(v27Binary7NodeShadow.agreeBinary == null ? 'ещё нет verdict' : (v27Binary7NodeShadow.agreeBinary ? 'binary согласован' : 'binary расходится'))}</strong></div>
            <div class="kv"><span>Время inference</span><strong>${escapeHtml(formatNumberWithUnit(v27Binary7NodeShadow.inferenceMs, { digits: 2, unit: ' ms', missing: 'ещё нет окна' }))}</strong></div>
          </div>
          <div class="panel__footer">Этот binary-кандидат публикуется через архивный контракт v26_shadow; UI показывает фактический candidate name явно для ручного теста.</div>
        </article>

        <article class="panel">
          <div class="panel__eyebrow">Garage Ratio V3 кандидат</div>
          <div class="panel__headline">${escapeHtml(displayMaybeToken(garageV2Headline))}</div>
          <div class="kv-list">
            <div class="kv"><span>Статус</span><strong>${escapeHtml(displayMaybeToken(garageRatioV2Shadow.status || 'unknown'))} / ${escapeHtml(garageRatioV2Shadow.loaded ? 'модель загружена' : 'модель не загружена')}</strong></div>
            <div class="kv"><span>Режим</span><strong>только shadow / garage zoning</strong></div>
            <div class="kv"><span>Архитектура</span><strong>ratio RF-500 + V5 door rescue + causal smooth k=7</strong></div>
            <div class="kv"><span>Последняя зона</span><strong>${escapeHtml(displayMaybeToken(garageV2Headline))}</strong></div>
            <div class="kv"><span>Raw → final</span><strong>${escapeHtml(displayMaybeToken(garageRatioV2Shadow.rawPredictedZone || 'unknown'))} → ${escapeHtml(displayMaybeToken(garageV2Headline))}</strong></div>
            <div class="kv"><span>Door / Center / Deep</span><strong>${escapeHtml(formatPercent(garageRatioV2Shadow.doorProbability, 0))} / ${escapeHtml(formatPercent(garageRatioV2Shadow.centerProbability, 0))} / ${escapeHtml(formatPercent(garageRatioV2Shadow.deepProbability, 0))}</strong></div>
            <div class="kv"><span>Door rescue</span><strong>${garageRatioV2Shadow.doorRescueApplied ? 'сработал' : 'нет'}</strong></div>
            <div class="kv"><span>Smoothing</span><strong>${garageRatioV2Shadow.smoothingApplied ? 'применено' : 'не меняло решение'} / ${escapeHtml(formatNumber(garageRatioV2Shadow.smoothingCount))} из ${escapeHtml(formatNumber(garageRatioV2Shadow.smoothingWindow))}</strong></div>
            <div class="kv"><span>Время inference</span><strong>${escapeHtml(formatNumberWithUnit(garageRatioV2Shadow.inferenceMs, { digits: 2, unit: ' ms', missing: 'ещё нет окна' }))}</strong></div>
          </div>
          <div class="panel__footer">Это текущий лучший гаражный shadow‑кандидат. В рантайме он сглаживается только causal‑majority по последним окнам и не меняет production routing Track A / V5.</div>
        </article>

        <article class="panel">
          <div class="panel__eyebrow">Empty subregime shadow</div>
          <div class="panel__headline">${escapeHtml(displayMaybeToken(emptySubregimeShadow.predictedClass || emptySubregimeShadow.status || 'unknown'))}</div>
          <div class="kv-list">
            <div class="kv"><span>Статус</span><strong>${escapeHtml(displayMaybeToken(emptySubregimeShadow.status || 'unknown'))} / ${escapeHtml(emptySubregimeShadow.loaded ? 'модель загружена' : 'модель не загружена')}</strong></div>
            <div class="kv"><span>Режим</span><strong>diagnostic shadow / false-occupied empty</strong></div>
            <div class="kv"><span>Последний класс</span><strong>${escapeHtml(displayMaybeToken(emptySubregimeShadow.predictedClass || 'unknown'))}</strong></div>
            <div class="kv"><span>Рекомендация</span><strong>${escapeHtml(displayMaybeToken(emptySubregimeShadow.recommendedAction || 'none'))}</strong></div>
            <div class="kv"><span>Empty-like / canonical / diag</span><strong>${escapeHtml(formatPercent(emptySubregimeShadow.emptyLikeRatio, 0))} / ${escapeHtml(formatPercent(emptySubregimeShadow.canonicalEmptyRatio, 0))} / ${escapeHtml(formatPercent(emptySubregimeShadow.diagEmptyRatio, 0))}</strong></div>
            <div class="kv"><span>Occupied-anchor</span><strong>${escapeHtml(formatPercent(emptySubregimeShadow.occupiedAnchorRatio, 0))}</strong></div>
            <div class="kv"><span>Runtime binary</span><strong>${escapeHtml(displayMaybeToken(emptySubregimeShadow.runtimeBinary || 'unknown'))} / ${escapeHtml(formatPercent(emptySubregimeShadow.runtimeBinaryConfidence, 0))}</strong></div>
            <div class="kv"><span>Rescue runtime</span><strong>${emptySubregimeShadow.rescueEnabled ? 'включён' : 'выключен'} / eligible: ${emptySubregimeShadow.rescueEligible ? 'да' : 'нет'} / applied: ${emptySubregimeShadow.rescueApplied ? 'да' : 'нет'}</strong></div>
            <div class="kv"><span>Streak rescue</span><strong>${escapeHtml(formatNumber(emptySubregimeShadow.rescueConsecutive))} / ${escapeHtml(formatNumber(emptySubregimeShadow.rescueRequired))}</strong></div>
            <div class="kv"><span>KNN / centroid</span><strong>${escapeHtml(displayMaybeToken(emptySubregimeShadow.knnPredictedClass || 'unknown'))} / ${escapeHtml(displayMaybeToken(emptySubregimeShadow.centroidPredictedClass || 'unknown'))}</strong></div>
          </div>
          <div class="panel__footer">Диагностический слой для пустого подрежима. Он помогает ловить false-occupied empty состояния, но не должен менять production routing, если rescue path отключён.</div>
        </article>

        <article class="panel">
          <div class="panel__eyebrow">Калибровка зон / shadow centroid</div>
          <div class="panel__headline">${escapeHtml((() => {
            const zc = this.snapshot?.live?.zoneCalibrationShadow || {};
            if (zc.calibrated && zc.zone && zc.zone !== 'unknown') return displayFewshotZone(zc.zone);
            if (zc.status === 'calibrating') return 'калибровка...';
            if (zc.status === 'rejected') return 'отклонено';
            return 'не откалибровано';
          })())}</div>
          <div class="kv-list">
            ${(() => {
              const zc = this.snapshot?.live?.zoneCalibrationShadow || {};
              return `
                <div class="kv"><span>Статус</span><strong>${escapeHtml(zc.status || 'not_calibrated')}</strong></div>
                <div class="kv"><span>Режим</span><strong>только shadow / NearestCentroid</strong></div>
                <div class="kv"><span>Откалибровано</span><strong>${zc.calibrated ? 'да' : 'нет'}${zc.stale ? ' (устарело)' : ''}</strong></div>
                <div class="kv"><span>Зоны</span><strong>${(zc.zonesCalibrated || []).map((item) => displayFewshotZone(item)).join(', ') || 'нет'}</strong></div>
                <div class="kv"><span>Качество</span><strong>${escapeHtml(zc.calibrationQuality || 'не определено')}</strong></div>
                <div class="kv"><span>Зона (raw → smooth)</span><strong>${escapeHtml(displayFewshotZone(zc.zoneRaw || 'unknown'))} → ${escapeHtml(displayFewshotZone(zc.zone || 'unknown'))}</strong></div>
                <div class="kv"><span>Confidence</span><strong>${zc.confidence != null ? formatNumber(zc.confidence, 2) : 'нет'}${zc.lowConfidence ? ' (низкая)' : ''}</strong></div>
                <div class="kv"><span>Smoothing k=5</span><strong>${zc.smoothed ? 'применено' : 'не меняло решение'}</strong></div>
                <div class="kv"><span>Время inference</span><strong>${escapeHtml(formatNumberWithUnit(zc.inferenceMs, { digits: 2, unit: ' ms', missing: 'ещё нет окна' }))}</strong></div>
                ${zc.rejectionReason ? `<div class="kv"><span>Причина отклонения</span><strong>${escapeHtml(zc.rejectionReason)}</strong></div>` : ''}
              `;
            })()}
          </div>
          <div class="panel__footer">Текущий runtime backend здесь остаётся shadow centroid. Новый guided few‑shot flow уже пересобран под live‑геометрию center + door_passage, но future storage/retrain path ещё не внедрён и production V20 не трогает.</div>
        </article>

        <article class="panel">
          <div class="panel__eyebrow">Текущий support‑path</div>
          <div class="panel__headline">${escapeHtml(displayToken(truth.currentBest.runtimePath.mode))}</div>
          <div class="kv-list">
            <div class="kv"><span>Кандидат</span><strong>${escapeHtml(truth.currentBest.runtimePath.candidateName)}</strong></div>
            <div class="kv"><span>Топология</span><strong>${escapeHtml(truth.currentBest.runtimePath.topologySignature)}</strong></div>
            <div class="kv"><span>Порог</span><strong>${escapeHtml(formatNumber(truth.currentBest.runtimePath.threshold, 3))}</strong></div>
            <div class="kv"><span>Только support</span><strong>${truth.currentBest.runtimePath.supportOnly ? UI_LOCALE.common.yes : UI_LOCALE.common.no}</strong></div>
            <div class="kv"><span>Авторитетный</span><strong>${truth.currentBest.runtimePath.authoritative ? UI_LOCALE.common.yes : UI_LOCALE.common.no}</strong></div>
          </div>
          <div class="token-row">${formatList(truth.currentBest.runtimePath.scope)}</div>
        </article>

        <article class="panel">
          <div class="panel__eyebrow">Замороженный offline-baseline</div>
          <div class="panel__headline">${escapeHtml(truth.currentBest.frozenBaseline.baselineName)}</div>
          <div class="kv-list">
            <div class="kv"><span>Порог</span><strong>${escapeHtml(formatNumber(truth.currentBest.frozenBaseline.threshold, 3))}</strong></div>
            <div class="kv"><span>Переключение runtime</span><strong>${truth.currentBest.frozenBaseline.runtimeSwitchForbidden ? 'запрещено' : 'разрешено'}</strong></div>
            <div class="kv"><span>quiet_static_center</span><strong>${escapeHtml(truth.currentBest.runtimePath.quietStaticCenterStatus)}</strong></div>
            <div class="kv"><span>quiet_static_door</span><strong>${escapeHtml(truth.currentBest.runtimePath.quietStaticDoorStatus)}</strong></div>
          </div>
          <div class="token-row">${formatList(truth.currentBest.frozenBaseline.trainingCoreCategories)}</div>
        </article>
      </div>

      <article class="panel">
        <div class="panel__header panel__header--split">
          <div>
          <div class="panel__eyebrow">UI тест‑селектор</div>
            <div class="panel__headline">Какой режим отображать на первом экране</div>
          </div>
        </div>
        <div class="capture-pack__actions">
          <button
            type="button"
            class="capture-pack__button ${selectedRuntimeView === UI_RUNTIME_VIEW_OPTIONS.TRACK_A ? 'capture-pack__button--primary' : 'capture-pack__button--ghost'}"
            data-action="select-ui-runtime-view"
            data-runtime-view="${UI_RUNTIME_VIEW_OPTIONS.TRACK_A}"
          >
            Track A / боевой
          </button>
          <button
            type="button"
            class="capture-pack__button ${selectedRuntimeView === UI_RUNTIME_VIEW_OPTIONS.TRACK_B ? 'capture-pack__button--primary' : 'capture-pack__button--ghost'}"
            data-action="select-ui-runtime-view"
            data-runtime-view="${UI_RUNTIME_VIEW_OPTIONS.TRACK_B}"
          >
            Track B / test
          </button>
          <button
            type="button"
            class="capture-pack__button ${selectedRuntimeView === UI_RUNTIME_VIEW_OPTIONS.V15 ? 'capture-pack__button--primary' : 'capture-pack__button--ghost'}"
            data-action="select-ui-runtime-view"
            data-runtime-view="${UI_RUNTIME_VIEW_OPTIONS.V15}"
          >
            V8 / test
          </button>
          <button
            type="button"
            class="capture-pack__button ${selectedRuntimeView === UI_RUNTIME_VIEW_OPTIONS.V27_7NODE ? 'capture-pack__button--primary' : 'capture-pack__button--ghost'}"
            data-action="select-ui-runtime-view"
            data-runtime-view="${UI_RUNTIME_VIEW_OPTIONS.V27_7NODE}"
          >
            7-node binary / test
          </button>
          <button
            type="button"
            class="capture-pack__button ${selectedRuntimeView === UI_RUNTIME_VIEW_OPTIONS.GARAGE_V2 ? 'capture-pack__button--primary' : 'capture-pack__button--ghost'}"
            data-action="select-ui-runtime-view"
            data-runtime-view="${UI_RUNTIME_VIEW_OPTIONS.GARAGE_V2}"
          >
            Garage V3 / test
          </button>
        </div>
        <div class="panel__footer">
          Сейчас выбран <strong>${escapeHtml(
            selectedRuntimeView === UI_RUNTIME_VIEW_OPTIONS.TRACK_B
                ? 'Track B v1 кандидат'
              : selectedRuntimeView === UI_RUNTIME_VIEW_OPTIONS.V15
                ? 'V8 F2-spectral canonical кандидат'
                : selectedRuntimeView === UI_RUNTIME_VIEW_OPTIONS.V27_7NODE
                  ? binary7NodeCandidateName
                : selectedRuntimeView === UI_RUNTIME_VIEW_OPTIONS.GARAGE_V2
                  ? 'Garage Ratio V3 кандидат'
                : 'Track A боевой'
          )}</strong>.
          Это меняет только режим отображения для теста; backend routing и live‑state этот переключатель не трогает.
        </div>
      </article>

      <div class="surface-grid surface-grid--two">
        <article class="panel">
          <div class="panel__eyebrow">Исключено / вне scope</div>
          <div class="token-row token-row--danger">${formatList(truth.currentBest.frozenBaseline.excludedCategories)}</div>
          <div class="panel__footer">Эти категории остаются вне core operator model line, пока отдельное runtime-решение не изменит контракт.</div>
        </article>

        <article class="panel">
          <div class="panel__eyebrow">Канонический resolved-strong</div>
          <div class="checklist">
            ${truth.canonicalResolvedStrong.mustHave.map((item) => `
              <div class="checklist__item">
                <span class="checklist__bullet"></span>
                <span>${escapeHtml(item)}</span>
              </div>
            `).join('')}
          </div>
          <div class="panel__footer">${escapeHtml(truth.canonicalResolvedStrong.policy)}</div>
        </article>
      </div>

      <article class="panel">
        <div class="panel__header panel__header--split">
          <div>
            <div class="panel__eyebrow">${escapeHtml(UI_LOCALE.models.catalogEyebrow)}</div>
            <div class="panel__headline">${escapeHtml(UI_LOCALE.models.catalogHeadline)}</div>
          </div>
          <button
            type="button"
            class="capture-pack__button capture-pack__button--ghost"
            data-action="refresh-runtime-models"
            ${runtimeModels.loading ? 'disabled' : ''}
          >
            ${escapeHtml(UI_LOCALE.models.refresh)}
          </button>
        </div>
        <div class="panel__footer">${escapeHtml(catalogSummary)} Track B и V8 сюда не входят: этот селектор управляет только совместимыми с Track A runtime bundles и не должен подменять shadow/test candidates.</div>
        ${latestRuntimeModel ? `
          <div class="runtime-model-callout ${latestRuntimeModel.isActive ? 'is-active' : ''}">
            <div class="runtime-model-callout__main">
              <div class="runtime-model-callout__eyebrow">Последняя runtime-ready модель</div>
              <div class="runtime-model-callout__headline">${escapeHtml(latestModelHeadline)}</div>
              <div class="capture-pack__meta">
                ${latestModelBadges.map((badge) => `<span class="token">${escapeHtml(badge)}</span>`).join('')}
                <span class="token">${escapeHtml(UI_LOCALE.models.thresholdLabel)} ${escapeHtml(formatNumber(latestRuntimeModel.threshold, 3))}</span>
              </div>
              <div class="kv-list runtime-model-callout__details">
                <div class="kv"><span>${escapeHtml(UI_LOCALE.models.fileLabel)}</span><strong>${escapeHtml(latestRuntimeModel.fileName || UI_LOCALE.common.noData)}</strong></div>
                <div class="kv"><span>${escapeHtml(UI_LOCALE.models.kindLabel)}</span><strong>${escapeHtml(latestRuntimeModel.kind || UI_LOCALE.common.unknown)}</strong></div>
                <div class="kv"><span>Обновлено</span><strong>${escapeHtml(formatTimestamp(latestRuntimeModel.updatedAt))}</strong></div>
                <div class="kv"><span>${escapeHtml(UI_LOCALE.models.runtimeScopeLabel)}</span><strong>motion-only runtime</strong></div>
                ${latestRuntimeModel.metrics?.f1_macro != null ? `<div class="kv"><span>F1 (CV)</span><strong>${(latestRuntimeModel.metrics.f1_macro * 100).toFixed(2)}%</strong></div>` : ''}
                ${latestRuntimeModel.metrics?.mae_combined != null ? `<div class="kv"><span>MAE</span><strong>${latestRuntimeModel.metrics.mae_combined.toFixed(3)} м</strong></div>` : ''}
                ${latestRuntimeModel.metrics?.n_windows != null ? `<div class="kv"><span>Окон</span><strong>${latestRuntimeModel.metrics.n_windows}</strong></div>` : ''}
              </div>
            </div>
            <div class="capture-pack__actions runtime-model-callout__actions">
              <button
                type="button"
                class="capture-pack__button ${latestRuntimeModel.isActive ? 'capture-pack__button--ghost' : 'capture-pack__button--primary'}"
                data-action="select-runtime-model"
                data-model-id="${escapeHtml(latestRuntimeModel.modelId)}"
                ${latestRuntimeModel.isActive || runtimeModels.switching ? 'disabled' : ''}
              >
                ${escapeHtml(latestModelButtonLabel)}
              </button>
            </div>
          </div>
        ` : ''}
        ${sortedModels.length ? `
          <div class="runtime-model-grid">
            ${sortedModels.map((item) => {
              const isLatest = Boolean(latestRuntimeModel && item.modelId === latestRuntimeModel.modelId);
              const badges = [
                isLatest ? 'последняя' : null,
                item.isActive ? UI_LOCALE.models.currentBadge : null,
                item.isDefault ? UI_LOCALE.models.defaultBadge : null,
                item.loaded ? UI_LOCALE.models.loadedBadge : UI_LOCALE.models.notLoadedBadge,
                item.kind || null
              ].filter(Boolean);

              const buttonLabel = item.isActive
                ? UI_LOCALE.models.active
                : runtimeModels.switching
                  ? UI_LOCALE.models.switching
                  : UI_LOCALE.models.select;

              return `
                <div class="runtime-model-card ${item.isActive ? 'is-active' : ''} ${isLatest ? 'is-latest' : ''}">
                  <div class="runtime-model-card__eyebrow">${escapeHtml(item.version || UI_LOCALE.common.unknown)}</div>
                  <h3>${escapeHtml(item.displayName || item.fileName || UI_LOCALE.common.unknown)}</h3>
                  <p>${escapeHtml(item.fileName || UI_LOCALE.common.unknown)}</p>
                  <div class="capture-pack__meta">
                    ${badges.map((badge) => `<span class="token">${escapeHtml(badge)}</span>`).join('')}
                    <span class="token">${escapeHtml(UI_LOCALE.models.thresholdLabel)} ${escapeHtml(formatNumber(item.threshold, 3))}</span>
                  </div>
                  <div class="kv-list runtime-model-card__details">
                    <div class="kv"><span>${escapeHtml(UI_LOCALE.models.fileLabel)}</span><strong>${escapeHtml(item.fileName || UI_LOCALE.common.noData)}</strong></div>
                    <div class="kv"><span>${escapeHtml(UI_LOCALE.models.kindLabel)}</span><strong>${escapeHtml(item.kind || UI_LOCALE.common.unknown)}</strong></div>
                    <div class="kv"><span>Обновлено</span><strong>${escapeHtml(formatTimestamp(item.updatedAt))}</strong></div>
                    <div class="kv"><span>${escapeHtml(UI_LOCALE.models.runtimeScopeLabel)}</span><strong>motion-only runtime</strong></div>
                    ${item.metrics?.f1_macro != null ? `<div class="kv"><span>F1 (CV)</span><strong>${(item.metrics.f1_macro * 100).toFixed(2)}%</strong></div>` : ''}
                    ${item.metrics?.mae_combined != null ? `<div class="kv"><span>MAE</span><strong>${item.metrics.mae_combined.toFixed(3)} м</strong></div>` : ''}
                    ${item.metrics?.empty_accuracy != null ? `<div class="kv"><span>Empty Acc.</span><strong>${(item.metrics.empty_accuracy * 100).toFixed(2)}%</strong></div>` : ''}
                    ${item.metrics?.n_windows != null ? `<div class="kv"><span>Окон</span><strong>${item.metrics.n_windows}</strong></div>` : ''}
                    ${item.metrics?.n_recordings != null ? `<div class="kv"><span>Записей</span><strong>${item.metrics.n_recordings}</strong></div>` : ''}
                  </div>
                  <div class="capture-pack__actions">
                    <button
                      type="button"
                      class="capture-pack__button ${item.isActive ? 'capture-pack__button--ghost' : 'capture-pack__button--primary'}"
                      data-action="select-runtime-model"
                      data-model-id="${escapeHtml(item.modelId)}"
                      ${item.isActive || runtimeModels.switching ? 'disabled' : ''}
                    >
                      ${escapeHtml(buttonLabel)}
                    </button>
                  </div>
                </div>
              `;
            }).join('')}
          </div>
        ` : `
          <div class="runtime-model-empty">${escapeHtml(runtimeModels.loading ? UI_LOCALE.models.loading : UI_LOCALE.models.empty)}</div>
        `}
      </article>

      <article class="panel">
        <div class="panel__eyebrow">Границы confidence по failure</div>
        <div class="family-map">
          ${truth.failureFamilies.robustCore.map((item) => `
            <div class="family-map__item tone-warn">
              <strong>${escapeHtml(item.label)}</strong>
              <span>${escapeHtml(item.rule)}</span>
            </div>
          `).join('')}
          ${truth.failureFamilies.conditionalSubtype.map((item) => `
            <div class="family-map__item tone-neutral">
              <strong>${escapeHtml(item.label)}</strong>
              <span>${escapeHtml(item.rule)}</span>
            </div>
          `).join('')}
        </div>
      </article>
    `;
  }

  getSearchFilteredForensicRuns(manifest, query = this.forensicQuery) {
    const normalizedInput = String(query || '').trim().toLowerCase();
    const normalizedQuery = normalizeSearchValue(normalizedInput);
    if (!normalizedInput) {
      return manifest;
    }

    return manifest.filter((item) => {
      const classification = item.classification || {};
      const haystack = [
        item.run_id,
        item.display_label,
        item.label,
        item.operator_summary_preview,
        item.fate_group,
        classification.status,
        classification.label,
        classification.failure_family,
        classification.evidence_sensitivity
      ]
        .filter(Boolean)
        .flatMap((value) => {
          const rawValue = String(value).toLowerCase();
          const normalizedValue = normalizeSearchValue(value);
          return rawValue === normalizedValue ? [rawValue] : [rawValue, normalizedValue];
        });
      return haystack.some((value) => value.includes(normalizedInput) || value.includes(normalizedQuery));
    });
  }

  getVisibleForensicRuns(manifest, options = {}) {
    const {
      fateFilter = this.forensicFateFilter,
      query = this.forensicQuery
    } = options;
    const searchFilteredRuns = this.getSearchFilteredForensicRuns(manifest, query);
    if (fateFilter === 'all') {
      return searchFilteredRuns;
    }
    return searchFilteredRuns.filter((item) => (item.fate_group || 'incomplete') === fateFilter);
  }

  buildForensicFateCounts(manifest, searchFilteredRuns) {
    const totals = Object.fromEntries(FATE_GROUPS.map((item) => [item.id, 0]));
    const visible = Object.fromEntries(FATE_GROUPS.map((item) => [item.id, 0]));

    totals.all = manifest.length;
    visible.all = searchFilteredRuns.length;

    manifest.forEach((item) => {
      const group = item.fate_group || 'incomplete';
      if (group in totals) {
        totals[group] += 1;
      }
    });

    searchFilteredRuns.forEach((item) => {
      const group = item.fate_group || 'incomplete';
      if (group in visible) {
        visible[group] += 1;
      }
    });

    return { totals, visible };
  }

  renderForensicRunCard(item, selectedRunId) {
    const classification = item.classification || {};
    const failureFamily = classification.failure_family || (classification.status !== 'canonical_resolved_strong' ? classification.label : null);
    const missingArtifacts = item.missing_artifacts || [];
    const evidenceTone = classification.evidence_sensitivity === 'robust'
      ? 'ok'
      : classification.evidence_sensitivity === 'contamination_sensitive'
        ? 'warn'
        : 'neutral';
    const preview = item.operator_summary_preview || UI_LOCALE.forensics.previewUnavailable;

    return `
      <button
        type="button"
        class="forensic-run-card ${item.run_id === selectedRunId ? 'is-active' : ''}"
        data-forensic-run-id="${escapeHtml(item.run_id)}"
      >
        <div class="forensic-run-card__head">
          <strong>${escapeHtml(item.display_label || item.run_id)}</strong>
          <span>${escapeHtml(formatTimestamp(item.sort_ts))}</span>
        </div>
        <div class="forensic-run-card__meta">${escapeHtml(item.run_id)}</div>
        <div class="forensic-run-card__preview">${escapeHtml(preview)}</div>
        <div class="forensic-run-card__tags">
          ${renderStatusPill(classificationBadgeLabel(classification.status || 'classification_unavailable'), classificationTone(classification.status))}
          ${failureFamily ? renderStatusPill(displayToken(failureFamily), 'warn') : ''}
          ${renderStatusPill(sensitivityBadgeLabel(classification.evidence_sensitivity || 'unknown'), evidenceTone)}
          ${missingArtifacts.length ? renderStatusPill(`не хватает ${missingArtifacts.length}`, 'risk') : renderStatusPill(UI_LOCALE.common.full, 'ok')}
        </div>
      </button>
    `;
  }

  renderForensicRunList(runs, selectedRunId) {
    if (!runs.length) {
      return `
        <div class="selector-empty">
          ${this.forensicQuery.trim()
            ? `${escapeHtml(UI_LOCALE.forensics.emptyByQueryPrefix)} "${escapeHtml(this.forensicQuery.trim())}".`
            : UI_LOCALE.forensics.empty}
        </div>
      `;
    }

    if (this.forensicViewMode === 'fate') {
      const sections = FATE_GROUPS
        .filter((item) => item.id !== 'all')
        .map((group) => ({
          ...group,
          runs: runs.filter((item) => (item.fate_group || 'incomplete') === group.id)
        }))
        .filter((group) => group.runs.length);

      if (!sections.length) {
        return `<div class="selector-empty">${escapeHtml(UI_LOCALE.forensics.emptyByGroup)}</div>`;
      }

      return sections.map((group) => `
        <section class="forensic-group">
          <div class="forensic-group__head">
            <div class="forensic-group__title">
              <span class="forensic-group__label">${escapeHtml(group.label)}</span>
              ${renderStatusPill(`${group.runs.length}`, group.tone)}
            </div>
          </div>
          <div class="forensic-group__list">
            ${group.runs.map((item) => this.renderForensicRunCard(item, selectedRunId)).join('')}
          </div>
        </section>
      `).join('');
    }

    return runs.map((item) => this.renderForensicRunCard(item, selectedRunId)).join('');
  }

  renderArtifactStatusCards(detail, summary) {
    const availability = detail?.availability || summary?.availability || {};
    const artifactPaths = detail?.artifact_paths || {};
    const missingArtifacts = detail?.missing_artifacts || summary?.missing_artifacts || [];
    const artifacts = [
      { key: 'watcher', label: 'Watcher-артефакт' },
      { key: 'raw_step', label: 'Raw-step артефакт' },
      { key: 'bundle', label: 'Paired forensic bundle' },
      { key: 'started', label: 'Стартовый сигнал' },
      { key: 'finished', label: 'Финишный сигнал' }
    ];

    return artifacts.map((artifact) => {
      const present = Boolean(availability[artifact.key]);
      const path = artifactPaths[artifact.key];
      return `
        <div class="artifact-status-card ${present ? 'is-present tone-info' : 'is-missing tone-risk'}">
          <span>${escapeHtml(artifact.label)}</span>
          <strong>${present ? 'есть' : 'нет'}</strong>
          <small>${present ? 'готов к разбору' : 'для выбранного run не найден'}</small>
          <code>${escapeHtml(path || `missing:${artifact.key}`)}</code>
        </div>
      `;
    }).join('') + (missingArtifacts.length
      ? `<div class="artifact-status-note tone-risk">Неполный bundle: ${escapeHtml(missingArtifacts.map((item) => displayToken(item)).join(', '))}</div>`
      : '');
  }

  renderForensics() {
    const truth = AGENT7_OPERATOR_TRUTH;
    const support = this.snapshot?.live?.supportPath || {};
    const forensics = this.snapshot?.forensics || {};
    const manifest = Array.isArray(forensics.manifest) ? forensics.manifest : [];
    const searchFilteredRuns = this.getSearchFilteredForensicRuns(manifest);
    const visibleRuns = this.getVisibleForensicRuns(manifest);
    const orderedVisibleRuns = this.getOrderedForensicRuns(manifest);
    const fateCounts = this.buildForensicFateCounts(manifest, searchFilteredRuns);
    const selectedRunId = orderedVisibleRuns.some((item) => item.run_id === forensics.selectedRunId)
      ? forensics.selectedRunId
      : (orderedVisibleRuns[0]?.run_id || manifest[0]?.run_id || null);
    const shouldScrollToSelection = Boolean(
      selectedRunId
      && (
        this.pendingForensicScrollRunId === selectedRunId
        || this.lastRenderedForensicRunId !== selectedRunId
      )
    );
    const selectedSummary = manifest.find((item) => item.run_id === selectedRunId) || orderedVisibleRuns[0] || null;
    const selectedRun = forensics.selectedRun?.run_id === selectedRunId ? forensics.selectedRun : null;
    const warmIndicator = buildForensicWarmIndicator(orderedVisibleRuns, selectedRunId, forensics.cacheState);

    const classification = selectedRun?.classification || selectedSummary?.classification || {};
    const ordered = selectedRun?.ordered_semantics || {};
    const resolved = selectedRun?.resolved_strong_assessment || {};
    const evidence = selectedRun?.evidence || {};
    const watcher = selectedRun?.watcher || {};
    const rawStep = selectedRun?.raw_step || {};
    const pairedBundle = selectedRun?.paired_bundle || {};
    const signals = selectedRun?.signals || {};
    const scenarioWindows = watcher.scenario_phase_windows?.length
      ? watcher.scenario_phase_windows
      : (pairedBundle.scenario_phase_windows || []);
    const failedCriteria = resolved.failed_criteria || [];
    const criteriaEntries = Object.entries(resolved.criteria || {});
    const sequenceStages = watcher.sequence?.stages || [];
    const truthChecks = Object.entries(watcher.truth_preserving_checks || {});

    const classificationStatus = classification.status || 'classification_unavailable';
    const classificationToneValue = classificationTone(classificationStatus);
    const failureFamily = classification.failure_family || ordered.ordered_failure_mode || null;
    const missingArtifacts = selectedRun?.missing_artifacts || selectedSummary?.missing_artifacts || [];
    const orderedFailureMode = ordered.ordered_failure_mode || 'режим не определён';
    const evidenceSensitivity = evidence.sensitivity || classification.evidence_sensitivity || 'unknown';
    const evidenceTone = evidenceSensitivity === 'robust'
      ? 'ok'
      : evidenceSensitivity === 'contamination_sensitive'
        ? 'warn'
        : 'neutral';

    let inspectorBody = '';

    if (!selectedSummary) {
      inspectorBody = `
        <article class="panel">
          <div class="panel__eyebrow">Инспектор run</div>
          <p class="panel__text">
            ${escapeHtml(UI_LOCALE.forensics.inspectorUnavailable)}
          </p>
        </article>
      `;
    } else {
      const operatorSummary = selectedRun?.operator_summary
        || 'Операторское summary пока недоступно; используйте панели ниже.';

      inspectorBody = `
        <section class="hero-panel hero-panel--compact">
          <div class="hero-panel__copy">
            <div class="eyebrow">Форензика / инспектор run</div>
            <h2>${escapeHtml(selectedRun?.display_label || selectedSummary.display_label || selectedSummary.run_id)}</h2>
            <div class="hero-summary">${escapeHtml(operatorSummary)}</div>
            <p>
              Live support‑path остаётся <strong>только support</strong>; narrative выше собирается на сервере из watcher/raw/bundle evidence и не подменяет primary motion verdict.
            </p>
            <div class="hero-tags">
              ${renderStatusPill(classificationBadgeLabel(classificationStatus), classificationToneValue)}
              ${failureFamily ? renderStatusPill(displayToken(failureFamily), 'warn') : ''}
              ${renderStatusPill(sensitivityBadgeLabel(evidenceSensitivity), evidenceTone)}
              ${missingArtifacts.length ? renderStatusPill(`не хватает ${missingArtifacts.length}`, 'risk') : renderStatusPill('полный bundle', 'ok')}
              ${forensics.loadingRun ? renderStatusPill('загрузка run', 'info') : ''}
            </div>
          </div>
          <div class="hero-panel__rail">
            <div class="hero-stat">
              <span>Run ID</span>
              <strong>${escapeHtml(selectedSummary.run_id)}</strong>
              <small>Захвачен ${escapeHtml(formatTimestamp(selectedSummary.sort_ts || selectedRun?.sort_ts))}</small>
            </div>
            <div class="hero-stat">
              <span>Ordered failure mode</span>
              <strong>${escapeHtml(displayToken(orderedFailureMode))}</strong>
              <small>${escapeHtml(displayToken(ordered.sequence_final_state || 'sequence_state_unavailable'))}</small>
            </div>
            <div class="hero-stat">
              <span>Live support readout</span>
              <strong>${escapeHtml(displayToken(support.contextValidity || 'unknown'))} / ${escapeHtml(displayToken(support.status || 'unknown'))}</strong>
              <small>${escapeHtml(displayToken(support.invalidationReason || support.reason || 'no_live_invalidation_reason'))}</small>
            </div>
            ${warmIndicator ? `
              <div class="hero-stat hero-stat--warm" data-warm-tone="${escapeHtml(warmIndicator.tone)}">
                <span>Прогрев соседей</span>
                <strong>${escapeHtml(warmIndicator.label)}</strong>
                <small>${escapeHtml(warmIndicator.detail)}</small>
              </div>
            ` : ''}
          </div>
        </section>

        ${forensics.selectedRunError ? `
          <article class="panel panel--danger">
            <div class="panel__eyebrow">Ошибка загрузки выбранного run</div>
            <p class="panel__text">${escapeHtml(forensics.selectedRunError)}</p>
          </article>
        ` : ''}

        <div class="surface-grid surface-grid--three">
          <article class="panel">
            <div class="panel__eyebrow">Классификация</div>
            <div class="panel__headline">${escapeHtml(displayToken(classificationStatus))}</div>
            <div class="kv-list">
              <div class="kv"><span>Failure family</span><strong>${escapeHtml(displayToken(failureFamily || 'family не определён'))}</strong></div>
              <div class="kv"><span>Канонический resolved-strong</span><strong>${escapeHtml(formatBoolean(resolved.canonical_resolved_strong))}</strong></div>
              <div class="kv"><span>Assessment ready</span><strong>${escapeHtml(formatBoolean(resolved.ready ?? classification.ready))}</strong></div>
              <div class="kv"><span>Чувствительность evidence</span><strong>${escapeHtml(displayToken(evidenceSensitivity))}</strong></div>
            </div>
          </article>

          <article class="panel">
            <div class="panel__eyebrow">Первый сильный pulse</div>
            <div class="panel__headline">${escapeHtml(formatMarkerSummary(ordered.first_strong_pulse))}</div>
            <div class="kv-list">
              <div class="kv"><span>Фаза</span><strong>${escapeHtml(displayToken(ordered.first_strong_pulse_phase || ordered.first_strong_pulse?.scenario_phase_label || 'фаза не зафиксирована'))}</strong></div>
              <div class="kv"><span>Причина shadow</span><strong>${escapeHtml(displayToken(ordered.first_strong_pulse?.shadow_invalidation_reason || ordered.first_strong_pulse?.shadow_reason || 'причина не зафиксирована'))}</strong></div>
              <div class="kv"><span>Валидность контекста</span><strong>${escapeHtml(displayToken(ordered.first_strong_pulse?.shadow_context_validity || 'контекст не оценён'))}</strong></div>
            </div>
          </article>

          <article class="panel">
            <div class="panel__eyebrow">Первое назначение направления</div>
            <div class="panel__headline">${escapeHtml(formatMarkerSummary(ordered.first_direction_assignment))}</div>
            <div class="kv-list">
              <div class="kv"><span>Назначенная сторона</span><strong>${escapeHtml(displayToken(ordered.first_direction_assignment?.assigned_side || 'сторона не назначена'))}</strong></div>
              <div class="kv"><span>Фаза</span><strong>${escapeHtml(displayToken(ordered.first_direction_assignment_phase || ordered.first_direction_assignment?.scenario_phase_label || 'фаза не зафиксирована'))}</strong></div>
              <div class="kv"><span>Ожидаемое направление</span><strong>${escapeHtml(displayToken(ordered.first_direction_assignment?.shadow_pending_direction || 'ожидаемое направление не рассчитано'))}</strong></div>
            </div>
          </article>
        </div>

        <article class="panel">
          <div class="panel__eyebrow">Полнота артефактов</div>
          <div class="artifact-status-grid">
            ${this.renderArtifactStatusCards(selectedRun, selectedSummary)}
          </div>
        </article>

        <div class="surface-grid surface-grid--two">
          <article class="panel">
            <div class="panel__eyebrow">Ordered semantics</div>
            <div class="kv-list">
              <div class="kv"><span>Ordered failure mode</span><strong>${escapeHtml(displayToken(orderedFailureMode))}</strong></div>
              <div class="kv"><span>Финальное состояние sequence</span><strong>${escapeHtml(displayToken(ordered.sequence_final_state || watcher.sequence?.final_state || 'состояние sequence не зафиксировано'))}</strong></div>
              <div class="kv"><span>Первый resolution event</span><strong>${escapeHtml(formatMarkerSummary(ordered.first_resolution_event))}</strong></div>
              <div class="kv"><span>Маркер context invalid</span><strong>${escapeHtml(formatMarkerSummary(ordered.first_context_invalid))}</strong></div>
              <div class="kv"><span>Неожиданное событие</span><strong>${escapeHtml(formatMarkerSummary(ordered.first_unexpected_event))}</strong></div>
              <div class="kv"><span>Exit-first prebaseline aliasing</span><strong>${escapeHtml(formatBoolean(ordered.exit_first_prebaseline_aliasing))}</strong></div>
            </div>
            ${scenarioWindows.length
              ? `<div class="token-row">${scenarioWindows.map((item) => `<span class="token">${escapeHtml(`${displayToken(item.label)}:${formatNumber(item.start_sec, 1)}-${formatNumber(item.end_sec, 1)}с`)}</span>`).join('')}</div>`
              : '<div class="panel__footer">Scenario windows для выбранного run недоступны.</div>'}
          </article>

          <article class="panel">
            <div class="panel__eyebrow">Resolved-strong gate</div>
            ${criteriaEntries.length ? `
              <div class="criteria-grid">
                ${criteriaEntries.map(([key, value]) => `
                  <div class="criteria-item ${value ? 'is-passed tone-ok' : 'is-failed tone-risk'}">
                    <span>${escapeHtml(displayToken(key))}</span>
                    <strong>${escapeHtml(formatBoolean(value))}</strong>
                  </div>
                `).join('')}
              </div>
            ` : `
              <p class="panel__text">
                Resolved-strong assessment пока недоступен. Обычно это значит, что paired forensic bundle отсутствует или неполон.
              </p>
            `}
            <div class="panel__footer">
              ${failedCriteria.length
                ? `Критерии вне нормы: ${escapeHtml(failedCriteria.map((item) => displayToken(item)).join(', '))}`
                : 'Для выбранного run проваленные критерии не зафиксированы.'}
            </div>
          </article>
        </div>

        <div class="surface-grid surface-grid--two">
          <article class="panel">
            <div class="panel__eyebrow">Устойчивость evidence</div>
            <p class="panel__text">${escapeHtml(evidence.sensitivity_reason || classification.evidence_sensitivity_reason || 'Чувствительность evidence для выбранного run недоступна.')}</p>
            <div class="truth-stack">
              <div class="truth-item ${toneClass(evidenceTone)}">
                <span>Evidence выбранного run</span>
                <strong>${escapeHtml(displayToken(evidenceSensitivity))}</strong>
              </div>
              <div class="truth-item tone-info">
                <span>Устойчиво для truth</span>
                <strong>${escapeHtml(formatBoolean(evidence.robust_for_selected_run))}</strong>
              </div>
              <div class="truth-item tone-warn">
                <span>Чувствительно к тайминг-сдвигу</span>
                <strong>${escapeHtml(formatBoolean(evidence.contamination_sensitive_for_selected_run))}</strong>
              </div>
            </div>
            <div class="panel__footer">${escapeHtml(truth.contaminationNote.summary)}</div>
          </article>

          <article class="panel">
            <div class="panel__eyebrow">Сводка run end-to-end</div>
            <div class="kv-list">
            <div class="kv"><span>Предпроверка watcher OK</span><strong>${escapeHtml(formatBoolean(watcher.preflight_ok))}</strong></div>
            <div class="kv"><span>Операционная готовность</span><strong>${escapeHtml(formatBoolean(watcher.preflight?.operational_ready))}</strong></div>
            <div class="kv"><span>Порог</span><strong>${escapeHtml(formatNumber(watcher.preflight?.threshold, 3))}</strong></div>
            <div class="kv"><span>Область runtime</span><strong>${escapeHtml((watcher.preflight?.runtime_scope || []).map((item) => displayToken(item)).join(', ') || 'scope не передан') }</strong></div>
              <div class="kv"><span>Финальное состояние sequence</span><strong>${escapeHtml(displayToken(watcher.sequence?.final_state || 'состояние sequence не зафиксировано'))}</strong></div>
              <div class="kv"><span>Зафиксировано стадий</span><strong>${escapeHtml(formatNumber(sequenceStages.length))}</strong></div>
            </div>
            <div class="token-row">
              ${sequenceStages.length
                ? sequenceStages.map((stage) => `<span class="token">${escapeHtml(`${displayToken(stage.stage)} @ ${formatTimestamp(stage.captured_at || stage.ts)}`)}</span>`).join('')
                : '<span class="muted">Watcher-стадии не зафиксированы.</span>'}
            </div>
            <div class="token-row">
              ${truthChecks.length
                ? truthChecks.map(([key, value]) => renderStatusPill(`${key}:${Array.isArray(value) ? value.length : value}`, Array.isArray(value) ? (value.length ? 'warn' : 'ok') : value ? 'warn' : 'ok')).join('')
                : '<span class="muted">Truth-preserving checks недоступны.</span>'}
            </div>
          </article>
        </div>

        <div class="surface-grid surface-grid--two">
          <article class="panel">
            <div class="panel__eyebrow">Пути артефактов / сигналы</div>
            <div class="artifact-groups">
              ${['watcher', 'raw_step', 'bundle', 'started', 'finished'].map((key) => `
                <div class="artifact-group">
                  <strong>${escapeHtml(displayToken(key))}</strong>
                  <code>${escapeHtml(selectedRun?.artifact_paths?.[key] || `missing:${key}`)}</code>
                </div>
              `).join('')}
            </div>
            <div class="kv-list">
              <div class="kv"><span>Старт записи</span><strong>${escapeHtml(formatTimestamp(signals.started?.recording_started_at || signals.started?.signal_written_at))}</strong></div>
              <div class="kv"><span>Финиш записи</span><strong>${escapeHtml(formatTimestamp(signals.finished?.recording_finished_at || signals.finished?.signal_written_at))}</strong></div>
              <div class="kv"><span>Захвачено строк</span><strong>${escapeHtml(formatNumber(signals.finished?.rows_captured))}</strong></div>
            </div>
          </article>

          <article class="panel">
            <div class="panel__eyebrow">Prompt / phase cues</div>
            <div class="prompt-stack">
              <div class="prompt-block">
                <span>Label</span>
                <p>${escapeHtml(rawStep.label || selectedSummary.label || 'label не передан')}</p>
              </div>
              <div class="prompt-block">
                <span>Setup prompt</span>
                <p>${escapeHtml(rawStep.setup_prompt || 'Setup prompt для этого run недоступен.')}</p>
              </div>
              <div class="prompt-block">
                <span>Scenario prompt</span>
                <p>${escapeHtml(rawStep.prompt || 'Scenario prompt для этого run недоступен.')}</p>
              </div>
              <div class="prompt-block">
                <span>Phase cues</span>
                <p>${escapeHtml((rawStep.phase_cues || []).map((item) => displayToken(item)).join(', ') || 'Phase cues не зафиксированы.')}</p>
              </div>
            </div>
          </article>
        </div>

        <div class="surface-grid surface-grid--two">
          <article class="panel">
            <div class="panel__eyebrow">Watcher timeline excerpt</div>
            <div class="panel__footer">${escapeHtml(`сэмплов series: ${watcher.series_count ?? 0}`)}</div>
            ${renderInspectorTable(
              [
                { key: 'elapsed_sec', label: 'Прошло, с' },
                { key: 'occupancy_state', label: 'Occupancy debug' },
                { key: 'occupancy_event', label: 'Событие' },
                { key: 'shadow_status', label: 'Shadow‑статус' },
                { key: 'shadow_context_validity', label: 'Контекст' },
                { key: 'shadow_pending_direction', label: 'Ожидаемое направление' },
                { key: 'live_total_packets', label: 'Пакеты' },
                { key: 'markers', label: 'Маркеры' }
              ],
              watcher.series_excerpt || [],
              'Watcher-артефакт отсутствует или не содержит извлечённого series-excerpt.'
            )}
          </article>

          <article class="panel">
            <div class="panel__eyebrow">Raw-step excerpt</div>
            <div class="panel__footer">${escapeHtml(`сэмплов: ${rawStep.samples ?? 'raw-step не прислал'} / секунд: ${rawStep.seconds ?? 'raw-step не прислал'}`)}</div>
            ${renderInspectorTable(
              [
                { key: 'sample_index', label: 'Сэмпл' },
                { key: 'elapsed_sec', label: 'Прошло, с' },
                { key: 'occupancy_state', label: 'Occupancy debug' },
                { key: 'motion_state', label: 'Движение' },
                { key: 'activity', label: 'Активность' },
                { key: 'presence', label: 'Presence debug' },
                { key: 'live_total_packets', label: 'Пакеты' },
                { key: 'topology_signature', label: 'Топология' }
              ],
              rawStep.rows_excerpt || [],
              'Raw-step артефакт отсутствует или не содержит извлечённых строк.'
            )}
          </article>
        </div>

        <article class="panel">
          <div class="panel__eyebrow">Paired bundle timeline</div>
          <div class="panel__footer">
            ${escapeHtml(`watcher-строк: ${pairedBundle.sample_counts?.watcher_series ?? 'bundle не прислал'} / raw-строк: ${pairedBundle.sample_counts?.raw_step_rows ?? 'bundle не прислал'} / paired-строк: ${pairedBundle.sample_counts?.paired_rows ?? 'bundle не прислал'}`)}
          </div>
          ${renderInspectorTable(
            [
              { key: 'window_index', label: 'Окно' },
              { key: 'timestamp', label: 'Timestamp' },
              { key: 'phase_label', label: 'Фаза' },
              { key: 'ordered_sequence_markers', label: 'Маркеры' },
              { key: 'ordered_failure_mode', label: 'Failure mode' },
              { key: 'watcher_shadow_status', label: 'Shadow‑статус' },
              { key: 'motion_state', label: 'Движение' },
              { key: 'live_total_packets', label: 'Пакеты' }
            ],
            pairedBundle.paired_rows_excerpt || [],
            'Paired forensic bundle отсутствует или не содержит paired rows excerpt.'
          )}
        </article>
      `;
    }

    this.sections.forensics.innerHTML = `
      <div class="surface-grid surface-grid--forensics">
        <aside class="panel forensic-selector-panel">
          <div class="panel__eyebrow">${escapeHtml(UI_LOCALE.forensics.selectorEyebrow)}</div>
          <div class="selector-view-modes">
            <button
              type="button"
              class="selector-mode ${this.forensicViewMode === 'time' ? 'is-active' : ''}"
              data-forensic-view="time"
            >
              <span class="selector-shortcut">M</span>
              ${escapeHtml(UI_LOCALE.forensics.viewTime)}
            </button>
            <button
              type="button"
              class="selector-mode ${this.forensicViewMode === 'fate' ? 'is-active' : ''}"
              data-forensic-view="fate"
            >
              <span class="selector-shortcut">M</span>
              ${escapeHtml(UI_LOCALE.forensics.viewFate)}
            </button>
          </div>
          <div class="selector-toolbar">
            <input
              class="selector-input"
              type="search"
              placeholder="${escapeHtml(UI_LOCALE.forensics.searchPlaceholder)}"
              value="${escapeHtml(this.forensicQuery)}"
              data-role="forensic-filter"
            />
            <button type="button" class="selector-refresh" data-action="refresh-forensics">
              ${escapeHtml(UI_LOCALE.forensics.refresh)}
            </button>
          </div>
          <div class="selector-filters">
            ${FATE_GROUPS.map((group) => {
              const total = fateCounts.totals[group.id] ?? 0;
              const visible = fateCounts.visible[group.id] ?? 0;
              const hasSearch = Boolean(this.forensicQuery.trim());
              const countLabel = hasSearch && visible !== total ? `${visible}/${total}` : `${total}`;
              const hotkey = Object.entries(FATE_GROUP_HOTKEYS).find(([, groupId]) => groupId === group.id)?.[0];
              return `
                <button
                  type="button"
                  class="selector-filter ${this.forensicFateFilter === group.id ? 'is-active' : ''}"
                  data-forensic-fate="${group.id}"
                >
                  ${hotkey ? `<span class="selector-shortcut">${escapeHtml(hotkey)}</span>` : ''}
                  <span>${escapeHtml(group.label)}</span>
                  ${renderStatusPill(countLabel, fateGroupTone(group.id))}
                </button>
              `;
            }).join('')}
          </div>
          <div class="selector-meta">
            <span>${escapeHtml(String(orderedVisibleRuns.length))} видно / ${escapeHtml(String(manifest.length))} всего</span>
            <span>
              ${forensics.loadingManifest
                ? UI_LOCALE.forensics.manifestRefreshing
                : `${this.forensicViewMode === 'fate' ? UI_LOCALE.forensics.modeFate : UI_LOCALE.forensics.modeTime} / manifest ${escapeHtml(formatTimestamp(forensics.manifestLoadedAt))}`}
            </span>
          </div>
          <div class="selector-hotkeys">${escapeHtml(UI_LOCALE.forensics.hotkeysHint)}</div>
          ${forensics.manifestError ? `<div class="selector-empty selector-empty--error">${escapeHtml(forensics.manifestError)}</div>` : ''}
          <div class="forensic-run-list">
            ${this.renderForensicRunList(orderedVisibleRuns, selectedRunId)}
          </div>
        </aside>

        <div class="forensic-inspector-stack">
          ${inspectorBody}
        </div>
      </div>
    `;

    this.lastRenderedForensicRunId = selectedRunId || null;
    if (shouldScrollToSelection) {
      this.syncForensicRunScroll(selectedRunId);
      this.pendingForensicScrollRunId = null;
    }
    this.scheduleForensicPrefetch(orderedVisibleRuns, selectedRunId);
  }

  renderValidation() {
    if (!this.sections.validation) {
      return;
    }
    const validation = this.snapshot?.validation || {};
    const status = validation.status || {};
    const summary = status.summary || {};
    const segments = Array.isArray(status.segments) ? status.segments : [];
    const filtered = this.validationFilter === 'all'
      ? segments
      : segments.filter((seg) => seg.validation_status === this.validationFilter);
    const detail = validation.selectedSegmentDetail;

    const summaryCards = `
      <div class="summary-stack">
        <div class="summary-card tone-info">
          <div class="summary-card__label">Всего сегментов</div>
          <div class="summary-card__value">${escapeHtml(formatNumber(summary.total_segments))}</div>
        <div class="summary-card__meta">источник: двойная валидация</div>
        </div>
        <div class="summary-card tone-success">
        <div class="summary-card__label">Согласовано</div>
          <div class="summary-card__value">${escapeHtml(formatPercent(summary.validated_pct || 0))}</div>
          <div class="summary-card__meta">${escapeHtml(formatNumber(summary.validated_count))} сегментов</div>
        </div>
        <div class="summary-card tone-warn">
        <div class="summary-card__label">Неоднозначно</div>
          <div class="summary-card__value">${escapeHtml(formatPercent(summary.ambiguous_pct || 0))}</div>
          <div class="summary-card__meta">${escapeHtml(formatNumber(summary.ambiguous_count))} сегментов</div>
        </div>
        <div class="summary-card tone-danger">
        <div class="summary-card__label">Конфликт</div>
          <div class="summary-card__value">${escapeHtml(formatPercent(summary.conflict_pct || 0))}</div>
          <div class="summary-card__meta">${escapeHtml(formatNumber(summary.conflict_count))} сегментов</div>
        </div>
      </div>
    `;

    const rows = filtered.slice(0, 200).map((seg) => `
      <div class="inspector-table__row" style="--columns:6" data-action="validation-select" data-segment-id="${escapeHtml(seg.segment_id)}">
        <div class="inspector-table__cell">${escapeHtml(seg.segment_id || '—')}</div>
        <div class="inspector-table__cell">${escapeHtml(formatNumber(seg.start_sec, 2))}–${escapeHtml(formatNumber(seg.end_sec, 2))}с</div>
        <div class="inspector-table__cell">${escapeHtml(seg.video_label || '—')}</div>
        <div class="inspector-table__cell">${escapeHtml(seg.csi_label || '—')}</div>
        <div class="inspector-table__cell">${escapeHtml(formatNumber(seg.similarity_score, 3))}</div>
        <div class="inspector-table__cell">${escapeHtml(seg.validation_status || '—')}</div>
      </div>
    `).join('');

    const table = `
      <div class="inspector-table">
        <div class="inspector-table__head" style="--columns:6">
          <div class="inspector-table__cell">Сегмент</div>
          <div class="inspector-table__cell">Время</div>
          <div class="inspector-table__cell">Видео</div>
          <div class="inspector-table__cell">CSI</div>
          <div class="inspector-table__cell">Сходство</div>
          <div class="inspector-table__cell">Статус</div>
        </div>
        ${rows || `<div class="inspector-empty">Нет сегментов</div>`}
      </div>
    `;

    const detailPanel = detail ? `
      <div class="panel" style="margin-top: 16px;">
        <div class="panel__eyebrow">Сегмент</div>
        <div class="panel__headline">${escapeHtml(detail.segment_id || '')}</div>
        <div class="panel__text">Видео: ${escapeHtml(detail.video_label || '—')} · CSI: ${escapeHtml(detail.csi_label || '—')} · сходство ${escapeHtml(formatNumber(detail.similarity_score, 3))}</div>
        <div class="hero-tags">
          ${renderStatusPill(`статус: ${detail.validation_status || '—'}`, detail.validation_status === 'conflict' ? 'danger' : detail.validation_status === 'ambiguous' ? 'warn' : 'ok')}
        </div>
        <div class="capture-console__actions" style="margin-top: 10px;">
          <button type="button" class="capture-pack__button" data-action="validation-resolve" data-segment-id="${escapeHtml(detail.segment_id)}" data-resolution="confirm_video">Принять видео</button>
          <button type="button" class="capture-pack__button capture-pack__button--ghost" data-action="validation-resolve" data-segment-id="${escapeHtml(detail.segment_id)}" data-resolution="accept_csi">Принять CSI</button>
          <button type="button" class="capture-pack__button capture-pack__button--ghost" data-action="validation-resolve" data-segment-id="${escapeHtml(detail.segment_id)}" data-resolution="mark_ambiguous">Неоднозначно</button>
        </div>
      </div>
    ` : '';

    this.sections.validation.innerHTML = `
      ${summaryCards}
      <article class="panel" style="margin-top: 16px;">
        <div class="panel__eyebrow">Фильтр</div>
        <div class="row">
          <select data-role="validation-filter">
            ${['all', 'validated', 'ambiguous', 'conflict'].map((statusKey) => {
              const label = statusKey === 'all'
                ? 'все'
                : statusKey === 'validated'
                  ? 'согласовано'
                  : statusKey === 'ambiguous'
                    ? 'неоднозначно'
                    : 'конфликт';
              return `<option value="${statusKey}" ${statusKey === this.validationFilter ? 'selected' : ''}>${label}</option>`;
            }).join('')}
          </select>
          <button class="capture-pack__button capture-pack__button--ghost" data-action="validation-refresh">Обновить</button>
          <button class="capture-pack__button" data-action="validation-batch-approve">Подтвердить все validated</button>
        </div>
        <div class="panel__text">${validation.error ? escapeHtml(validation.error) : ''}</div>
        ${table}
      </article>
      ${detailPanel}
    `;

    if (!validation.status && !validation.loading) {
      void this.service.refreshValidationStatus();
    }
  }

  renderLabeling() {
    if (!this.sections.labeling) {
      return;
    }
    const reviewIndexUrl = 'http://127.0.0.1:8124/index.html';
    const reviewRootPath = '/Users/arsen/Desktop/wifi-densepose/output/garage_guided_review_dense1';
    this.sections.labeling.innerHTML = `
      <article class="panel">
        <div class="panel__eyebrow">Разметка и QC</div>
        <div class="panel__headline">Единый обзор разметки</div>
        <div class="panel__text">
          Это точка входа для всех ручных видео‑разметок и их проверки. Никаких отдельных UI: один индекс и единый viewer.
        </div>
        <div class="capture-pack__actions" style="margin-top: 10px;">
          <a class="capture-pack__button" href="${reviewIndexUrl}" target="_blank" rel="noopener">Открыть индекс разметки</a>
        </div>
        <div class="panel__footer">
          Если индекс не открывается, запусти локальный сервер из каталога:<br>
          <code>cd ${reviewRootPath} && python3 -m http.server 8124</code>
        </div>
      </article>
      <article class="panel" style="margin-top: 16px;">
        <div class="panel__eyebrow">Локальные артефакты</div>
        <div class="panel__text">Папка разметки: <code>${reviewRootPath}</code></div>
      </article>
    `;
  }

  initFp2Tab() {
    if (this.fp2Tab || !this.sections.fp2) {
      return;
    }
    if (!this.sections.fp2.dataset.fp2Ready) {
      this.sections.fp2.innerHTML = `
        <div class="panel">
          <div class="panel__eyebrow">FP2 мониторинг</div>
          <div class="panel__text">Live‑данные FP2 через /api/v1/fp2/current и /api/v1/fp2/ws.</div>
        </div>
        <div class="fp2-toolbar" style="margin-top: 12px;">
          <button id="fp2Refresh" class="btn btn--secondary">Обновить</button>
          <button id="fp2StreamToggle" class="btn btn--primary">Старт стрима</button>
          <select id="fp2EntitySelect" class="zone-select" style="min-width: 280px;"></select>
          <button id="fp2EntityAuto" class="btn btn--secondary">Автовыбор Entity</button>
        </div>
        <div class="fp2-grid">
          <div class="fp2-card">
            <h3>Статус FP2</h3>
            <div class="fp2-kv"><span>API</span><span id="fp2ApiStatus" class="chip">-</span></div>
            <div class="fp2-kv"><span>Stream</span><span id="fp2StreamStatus" class="chip">disconnected</span></div>
            <div class="fp2-kv"><span>Entity</span><code id="fp2EntityId">-</code></div>
            <div class="fp2-kv"><span>Последнее обновление</span><span id="fp2UpdatedAt">-</span></div>
            <div class="fp2-kv"><span>Presence</span><span id="fp2PresenceValue" class="presence-pill absent">НЕТ</span></div>
          </div>
          <div class="fp2-card">
            <h3>Метрики</h3>
            <div class="fp2-kv"><span>Людей</span><strong id="fp2PersonsCount">0</strong></div>
            <div class="fp2-kv"><span>Зон</span><strong id="fp2ZonesCount">0</strong></div>
            <div class="fp2-kv"><span>FP2 Entities в HA</span><strong id="fp2EntitiesCount">0</strong></div>
            <div class="fp2-kv"><span>Текущая зона</span><strong id="fp2CurrentZone">-</strong></div>
            <div class="fp2-kv"><span>Длительность присутствия</span><strong id="fp2PresenceDuration">0s</strong></div>
            <ul id="fp2HistoryList" class="fp2-history-list"></ul>
          </div>
        </div>
        <div class="fp2-card">
          <h3>Движение</h3>
          <ul id="fp2MovementList" class="fp2-history-list fp2-movement-list"></ul>
        </div>
        <div class="fp2-card">
          <h3>Карта перемещений</h3>
          <canvas id="fp2MovementCanvas" width="960" height="260" style="width: 100%; height: 260px;"></canvas>
        </div>
        <div class="fp2-card">
          <h3>Realtime‑график</h3>
          <canvas id="fp2RealtimeGraph" width="960" height="200" style="width: 100%; height: 200px; background: #1a1a2e; border-radius: 8px;"></canvas>
          <div class="fp2-graph-legend">
            <span class="legend-item"><span class="legend-color present"></span> Есть</span>
            <span class="legend-item"><span class="legend-color absent"></span> Нет</span>
          </div>
        </div>
        <div class="fp2-card">
          <h3>Сырые данные</h3>
          <pre id="fp2RawOutput" class="fp2-raw-output">{}</pre>
        </div>
      `;
      this.sections.fp2.dataset.fp2Ready = 'true';
    }
    this.fp2Tab = new FP2Tab(this.sections.fp2);
    this.fp2Tab.init().catch((error) => {
      console.error('Failed to initialize FP2 tab:', error);
    });
  }

  renderFp2() {
    if (!this.sections.fp2) {
      return;
    }
    if (this.tabManager?.getActiveTab() === 'fp2') {
      this.initFp2Tab();
    }
  }

  renderGuidedCapturePackCard(pack, recording) {
    const summary = getGuidedCapturePackSummary(pack);
    const guidedStatus = recording.guided?.status || 'idle';
    const recordingMode = getRecordingMode(recording);
    const foreignRecordingActive = Boolean(recording.status?.recording) && recordingMode && recordingMode !== 'guided';
    const activePackId = recording.guided?.packId || null;
    const isSelected = (recording.selectedPackId || activePackId) === pack.id;
    const isActivePack = activePackId === pack.id && isGuidedActiveStatus(guidedStatus);
    const isAnotherPackActive = activePackId && activePackId !== pack.id && isGuidedActiveStatus(guidedStatus);
    const preflightReady = Boolean(recording.preflight?.ok);
    const preflightTone = recording.preflightLoading ? 'info' : preflightReady ? 'ok' : recording.preflightError ? 'risk' : 'warn';
    const preflightLabel = recording.preflightLoading
      ? UI_LOCALE.capture.preflightRunning
      : preflightReady
        ? UI_LOCALE.capture.preflightReady
        : recording.preflightError
          ? UI_LOCALE.capture.preflightFail
          : UI_LOCALE.capture.preflightMissing;

    return `
      <article class="capture-pack ${isSelected ? 'is-selected' : ''} ${isActivePack ? 'is-active' : ''}">
        <button type="button" class="capture-pack__body" data-pack-select="${escapeHtml(pack.id)}">
          <div class="capture-pack__eyebrow">${escapeHtml(`${pack.code} / ${pack.shortLabel}`)}</div>
          <h3>${escapeHtml(pack.name)}</h3>
          <p>${escapeHtml(pack.description)}</p>
          <div class="capture-pack__meta">
            ${isSelected ? renderStatusPill('выбран', 'ok') : ''}
            ${renderStatusPill('архив', 'warn')}
            ${renderStatusPill(`${summary.clipCount} ${UI_LOCALE.capture.clips}`, 'info')}
            ${renderStatusPill(`${UI_LOCALE.capture.activeTime} ${formatDurationCompact(summary.activeSeconds)}`, 'neutral')}
            ${renderStatusPill(`${UI_LOCALE.capture.totalTime} ${formatDurationCompact(summary.totalSeconds)}`, 'neutral')}
            ${renderStatusPill(pack.withVideo ? UI_LOCALE.capture.videoOn : UI_LOCALE.capture.noVideo, pack.withVideo ? 'warn' : 'neutral')}
            ${renderStatusPill(pack.voiceEnabledByDefault ? UI_LOCALE.capture.voiceDefault : UI_LOCALE.capture.voiceOff, pack.voiceEnabledByDefault ? 'ok' : 'neutral')}
          </div>
          <div class="token-row capture-pack__steps">
            ${pack.steps.map((step, index) => `<span class="token">${escapeHtml(`${index + 1}. ${step.label}`)}</span>`).join('')}
          </div>
        </button>
        <div class="capture-pack__actions">
          <button
            type="button"
            class="capture-pack__button ${isSelected ? 'capture-pack__button--ghost' : 'capture-pack__button--primary'}"
            data-pack-select="${escapeHtml(pack.id)}"
            ${isActivePack || isAnotherPackActive || foreignRecordingActive ? 'disabled' : ''}
          >
            ${escapeHtml(isSelected ? 'Пакет выбран' : 'Выбрать пакет')}
          </button>
          <button type="button" class="capture-pack__button capture-pack__button--ghost" data-action="capture-preflight" data-pack-id="${escapeHtml(pack.id)}">
            ${escapeHtml(UI_LOCALE.capture.rerunPreflight)}
          </button>
          <button
            type="button"
            class="capture-pack__button capture-pack__button--primary"
            data-action="capture-start"
            data-pack-id="${escapeHtml(pack.id)}"
            ${isAnotherPackActive || isActivePack || foreignRecordingActive ? 'disabled' : ''}
          >
            ${escapeHtml(UI_LOCALE.capture.startGuided)}
          </button>
        </div>
        <div class="capture-pack__footer">
          ${renderStatusPill(preflightLabel, preflightTone)}
          ${isSelected && !isActivePack ? renderStatusPill('готов к предпроверке и старту', 'ok') : ''}
          ${isActivePack ? renderStatusPill(guidedStatus === 'cueing' ? UI_LOCALE.capture.statusCueing : UI_LOCALE.capture.statusRunning, guidedStatus === 'cueing' ? 'info' : 'risk') : ''}
          ${recordingMode === 'manual' ? renderStatusPill('backend занят ручной записью', 'warn') : ''}
          ${recordingMode === 'freeform' ? renderStatusPill('backend занят freeform-записью', 'warn') : ''}
        </div>
      </article>
    `;
  }

  renderGuidedCaptureConsole(recording) {
    const activePack = getGuidedCapturePack(recording.guided?.packId || recording.selectedPackId);
    const guided = recording.guided || {};
    const status = guided.status || 'idle';
    const currentStep = guided.currentStep;
    const recordingStatus = recording.status || {};
    const guidedActive = isGuidedActiveStatus(status);
    const recordingMode = getRecordingMode(recording);
    const manualActive = recordingMode === 'manual';
    const freeformActive = recordingMode === 'freeform';
    const summary = getGuidedCapturePackSummary(activePack);
    const preflight = recording.preflight || {};
    const nodeEntries = Object.entries(preflight.nodes || {});
    const readyNodes = nodeEntries.filter(([, info]) => info?.ok).length;
    const videoChecked = Boolean(preflight.video?.checked);
    const videoReady = videoChecked ? Boolean(preflight.video?.available) : true;
    const displayVoiceEnabled = ['cueing', 'running', 'paused', 'stopping', 'completed', 'cancelled', 'error', 'preflight_failed'].includes(status)
      ? guided.voiceEnabled
      : activePack?.voiceEnabledByDefault !== false;
    const displayWithVideo = ['cueing', 'running', 'paused', 'stopping', 'completed', 'cancelled', 'error', 'preflight_failed'].includes(status)
      ? guided.withVideo
      : activePack?.withVideo !== false;
    const activeCountdown = currentStep ? formatCountdown(guided.stepEndsAt) : 'таймер шага не запущен';
    const pauseCountdown = status === 'paused' ? formatCountdown(guided.pauseUntil) : 'пауза не активна';
    const nextStep = ['completed', 'cancelled', 'error'].includes(status)
      ? null
      : activePack?.steps?.[currentStep ? currentStep.index + 1 : 0] || null;
    const currentInstruction = currentStep?.instruction || activePack?.description || UI_LOCALE.capture.progressNoSelection;
    const currentHeadline = currentStep
      ? `${UI_LOCALE.capture.stepProgress} ${currentStep.index + 1}/${currentStep.totalSteps} · ${currentStep.label}`
      : activePack
        ? `${activePack.code} · ${activePack.name}`
        : UI_LOCALE.capture.statusIdle;

    let statusLabel = UI_LOCALE.capture.statusIdle;
    if (status === 'cueing') {
      statusLabel = UI_LOCALE.capture.statusCueing;
    } else if (status === 'running') {
      statusLabel = UI_LOCALE.capture.statusRunning;
    } else if (status === 'paused') {
      statusLabel = UI_LOCALE.capture.waitingNext;
    } else if (status === 'stopping') {
      statusLabel = UI_LOCALE.capture.statusStopping;
    } else if (status === 'completed') {
      statusLabel = UI_LOCALE.capture.statusCompleted;
    } else if (status === 'cancelled') {
      statusLabel = UI_LOCALE.capture.statusCancelled;
    } else if (status === 'preflight_failed') {
      statusLabel = UI_LOCALE.capture.preflightFail;
    } else if (status === 'error') {
      statusLabel = UI_LOCALE.capture.statusError;
    }

    const backendRecordingLabel = guidedActive
      ? status === 'cueing'
        ? UI_LOCALE.capture.statusCueing
        : UI_LOCALE.capture.recordingLive
      : manualActive
        ? 'backend занят ручной записью'
        : freeformActive
          ? 'backend занят freeform-записью'
        : UI_LOCALE.capture.progressReady;
    const backendRecordingDetail = guidedActive
      ? status === 'cueing'
        ? guided.sequencePhase === 'prompt'
          ? UI_LOCALE.capture.voiceSequencing
          : guided.sequencePhase === 'countdown'
            ? `${UI_LOCALE.capture.countdownSequencing}: ${guided.countdownValue ?? '?'}`
            : UI_LOCALE.capture.startCueSequencing
        : `${formatDurationCompact(recordingStatus.elapsed_sec)} / ${formatNumber(recordingStatus.chunk_pps, 1)} pps`
      : manualActive
        ? `${formatDurationCompact(recordingStatus.elapsed_sec)} / ${formatNumber(recordingStatus.chunk_pps, 1)} pps`
        : freeformActive
          ? `${formatDurationCompact(recordingStatus.elapsed_sec)} / ${formatNumber(recordingStatus.chunk_pps, 1)} pps`
        : `Предпроверка ${preflight.ok ? UI_LOCALE.common.ready : UI_LOCALE.common.unavailable}`;

    return `
      <div class="capture-console">
        <div class="hero-panel hero-panel--compact">
          <div class="hero-panel__copy">
            <div class="eyebrow">${escapeHtml(UI_LOCALE.capture.currentInstruction)}</div>
            <h2>${escapeHtml(currentHeadline)}</h2>
            <p>${escapeHtml(currentInstruction)}</p>
            <div class="hero-tags">
              ${renderStatusPill(statusLabel, captureTone(status))}
              ${activePack ? renderStatusPill(`${activePack.code} / ${summary.clipCount} ${UI_LOCALE.capture.clips}`, 'info') : ''}
              ${renderStatusPill(displayVoiceEnabled ? UI_LOCALE.capture.voiceOn : UI_LOCALE.capture.voiceOff, displayVoiceEnabled ? 'ok' : 'neutral')}
              ${renderStatusPill(displayWithVideo ? UI_LOCALE.capture.videoOn : UI_LOCALE.capture.noVideo, displayWithVideo ? 'warn' : 'neutral')}
            </div>
            <div class="hero-summary">
              ${status === 'cueing'
                ? guided.sequencePhase === 'prompt'
                  ? 'Озвучиваю инструкцию шага. Обратный отсчёт начнётся после окончания подсказки.'
                  : guided.sequencePhase === 'countdown'
                    ? `Идёт обратный отсчёт. Старт через ${escapeHtml(String(guided.countdownValue ?? '?'))} с.`
                    : 'Даю финальную команду старта. Запись начнётся сразу после сигнала.'
                : status === 'running'
                ? `Идёт запись шага ${escapeHtml(String((currentStep?.index ?? 0) + 1))}. До авто-стопа ${escapeHtml(activeCountdown)}.`
                : status === 'paused'
                  ? `Шаг завершён. Следующий клип стартует через ${escapeHtml(pauseCountdown)}.`
                  : status === 'completed'
                    ? `Пакет завершён без terminal. Последний фрагмент: ${escapeHtml(getGuidedLastChunkText(guided, recordingStatus))}.`
                    : status === 'cancelled'
                      ? 'guided-запуск остановлен оператором. Можно перезапустить пакет с этого же экрана.'
                      : status === 'preflight_failed'
                        ? `Предпроверка не прошла: ${escapeHtml(guided.lastError || recording.preflightError || UI_LOCALE.common.unavailable)}`
                      : status === 'error'
                          ? `guided-запуск завершился ошибкой: ${escapeHtml(guided.lastError || recording.actionError || UI_LOCALE.common.unavailable)}`
                          : manualActive
                            ? `Пакет сейчас не запущен. Backend занят ручной записью ${escapeHtml(getRecordingLabelText(recordingStatus))}.`
                            : freeformActive
                              ? `Пакет сейчас не запущен. Backend занят freeform-записью ${escapeHtml(getRecordingLabelText(recordingStatus))}.`
                          : 'Выбери пакет, сделай предпроверку и запускай клипы прямо из UI.'}
            </div>
          </div>
          <div class="hero-panel__rail">
            <div class="hero-stat">
              <span>${escapeHtml(UI_LOCALE.capture.packSelected)}</span>
              <strong>${escapeHtml(activePack ? `${activePack.code} · ${activePack.name}` : UI_LOCALE.capture.progressNoSelection)}</strong>
              <small>${escapeHtml(activePack ? activePack.shortLabel : UI_LOCALE.capture.manualFallbackText)}</small>
            </div>
            <div class="hero-stat">
              <span>${escapeHtml(backendRecordingLabel)}</span>
              <strong>${escapeHtml(guidedActive ? getRecordingLabelText(recordingStatus, currentStep?.label) : manualActive || freeformActive ? getRecordingLabelText(recordingStatus) : (currentStep?.label || 'шаг ещё не выбран'))}</strong>
              <small>${escapeHtml(backendRecordingDetail)}</small>
            </div>
            <div class="hero-stat">
              <span>${escapeHtml(UI_LOCALE.capture.nextStep)}</span>
              <strong>${escapeHtml(nextStep?.label || UI_LOCALE.capture.completedLabel)}</strong>
              <small>${escapeHtml(nextStep?.instruction || 'Следующий шаг появится после старта пакета.')}</small>
            </div>
          </div>
        </div>

        <div class="surface-grid surface-grid--two capture-console__grid">
          <article class="panel">
            <div class="panel__eyebrow">${escapeHtml(UI_LOCALE.capture.preflightPanel)}</div>
            <div class="kv-list">
              <div class="kv"><span>${escapeHtml(UI_LOCALE.capture.nodesReady)}</span><strong>${escapeHtml(`${readyNodes}/${Math.max(nodeEntries.length, 4)}`)}</strong></div>
              <div class="kv"><span>${escapeHtml(UI_LOCALE.capture.videoReady)}</span><strong>${escapeHtml(videoChecked ? formatBoolean(videoReady) : UI_LOCALE.common.optional)}</strong></div>
              <div class="kv"><span>${escapeHtml(UI_LOCALE.capture.operationalReady)}</span><strong>${escapeHtml(formatBoolean(preflight.ok))}</strong></div>
              <div class="kv"><span>${escapeHtml(UI_LOCALE.capture.lastChunk)}</span><strong>${escapeHtml(getGuidedLastChunkText(guided, recordingStatus))}</strong></div>
            </div>
            <div class="hero-tags">
              ${recording.preflightLoading ? renderStatusPill(UI_LOCALE.capture.preflightRunning, 'info') : ''}
              ${recording.preflightError ? renderStatusPill(recording.preflightError, 'risk') : ''}
              ${preflight.ok ? renderStatusPill(UI_LOCALE.capture.preflightReady, 'ok') : ''}
            </div>
            <div class="capture-console__actions">
              <button
                type="button"
                class="capture-pack__button capture-pack__button--ghost"
                data-action="capture-preflight"
                data-pack-id="${escapeHtml(activePack?.id || recording.selectedPackId || '')}"
                ${(activePack?.id || recording.selectedPackId) && !manualActive && !freeformActive ? '' : 'disabled'}
              >
                ${escapeHtml(UI_LOCALE.capture.rerunPreflight)}
              </button>
              <button
                type="button"
                class="capture-pack__button capture-pack__button--primary"
                data-action="${isGuidedActiveStatus(status) ? 'capture-stop' : 'capture-start'}"
                data-pack-id="${escapeHtml(activePack?.id || recording.selectedPackId || '')}"
                ${(activePack?.id || recording.selectedPackId) && (!manualActive && !freeformActive || isGuidedActiveStatus(status)) ? '' : 'disabled'}
              >
                ${escapeHtml(isGuidedActiveStatus(status) ? UI_LOCALE.capture.stopGuided : UI_LOCALE.capture.startGuided)}
              </button>
            </div>
          </article>

          <article class="panel">
            <div class="panel__eyebrow">${escapeHtml(UI_LOCALE.capture.stepLog)}</div>
            <div class="capture-log-list">
              ${guided.logs.length
                ? guided.logs.map((entry) => `
                  <div class="capture-log-entry capture-log-entry--${escapeHtml(entry.status || 'idle')}">
                    <div class="capture-log-entry__head">
                      <strong>${escapeHtml(entry.stepLabel || entry.stepId || UI_LOCALE.common.unknown)}</strong>
                      ${renderStatusPill(displayToken(entry.status || 'idle'), captureTone(entry.status))}
                    </div>
                    <div class="capture-log-entry__meta">
                      <span>${escapeHtml(entry.recordingLabel || 'метка шага не пришла')}</span>
                      <span>${escapeHtml(entry.startedAt ? formatTimestamp(entry.startedAt) : 'ожидаю старт')}</span>
                      <span>${escapeHtml(entry.finishedAt ? formatTimestamp(entry.finishedAt) : `план ${formatDurationCompact(entry.expectedDurationSec)}`)}</span>
                    </div>
                    <p>${escapeHtml(entry.error || entry.lastChunkLabel || entry.instruction || UI_LOCALE.common.noDetail)}</p>
                  </div>
                `).join('')
                : `<div class="empty-state">${escapeHtml(UI_LOCALE.capture.noPackLogs)}</div>`}
            </div>
            <div class="panel__footer">${escapeHtml(UI_LOCALE.capture.manualFallbackText)}</div>
          </article>
        </div>
      </div>
    `;
  }

  renderManualRecordingConsole(recording) {
    const manual = recording.manual || {};
    const teacherSource = getTeacherSourceSelection(recording);
    const preflight = recording.preflight || {};
    const startupSignalGuard = getStartupSignalGuard(recording);
    const nodeEntries = Array.isArray(preflight.nodes)
      ? preflight.nodes
      : Object.entries(preflight.nodes || {}).map(([name, item]) => ({
          name,
          ...(item || {})
        }));
    const readyNodes = nodeEntries.filter((item) => item?.ok).length;
    const totalNodes = Math.max(nodeEntries.length, 4);
    const videoChecked = Boolean(preflight.video?.checked);
    const videoReady = videoChecked ? Boolean(preflight.video?.available) : true;
    const status = recording.status || {};
    const recordingMode = getRecordingMode(recording);
    const guidedActive = recordingMode === 'guided';
    const freeformActive = recordingMode === 'freeform';
    const manualActive = recordingMode === 'manual';
    const disableForm = manualActive || guidedActive || freeformActive;
    const selectedPreset = getManualCapturePreset(manual.labelPresetId);
    const selectedVariant = getManualCapturePresetVariant(manual.labelPresetId, manual.labelVariantId);
    const generatedLabel = selectedPreset?.id === 'custom' ? '' : (selectedPreset?.labelValue || '');
    const generatedNotes = [selectedPreset?.notesPrefix, selectedVariant?.notes].filter(Boolean).join(', ');
    const currentLabel = status.label || manual.label || UI_LOCALE.capture.manualIdle;
    const currentStateText = manualActive
      ? UI_LOCALE.capture.manualActive
      : guidedActive
        ? 'Сейчас занят guided-пакетом'
        : freeformActive
          ? 'Сейчас занят freeform-режимом'
        : UI_LOCALE.capture.manualIdle;
    const manualTeacherKind = manual.withVideo
      ? normalizeTeacherSourceKind(teacherSource.selectedKind)
      : TEACHER_SOURCE_KIND.NONE;
    const manualTeacherLabel = getTeacherSourceKindLabel(manualTeacherKind);
    const manualTeacherDetail = manual.withVideo
      ? getTeacherSourceSelectionDetail(teacherSource)
      : 'При отключенном видео используется teacher_source_kind=none.';

    return `
      <div class="manual-recorder">
        <div class="panel__eyebrow">${escapeHtml(UI_LOCALE.capture.manualEyebrow)}</div>
        <div class="panel__headline">${escapeHtml(UI_LOCALE.capture.manualHeadline)}</div>
        <div class="panel__text">${escapeHtml(UI_LOCALE.capture.manualSummary)}</div>
        <div class="recording-archive__notice">Архивный путь совместимости: используй только если канонический freeform невозможен и это осознанное исключение.</div>
        <div class="panel__footer manual-recorder__selection-note">Текущий teacher contract для manual preflight/start: ${escapeHtml(manualTeacherLabel)} · ${escapeHtml(manualTeacherDetail)}</div>

        <div class="manual-recorder__grid">
          <label class="manual-recorder__field">
            <span>${escapeHtml(UI_LOCALE.capture.manualLabelCatalog)}</span>
            <select
              class="manual-recorder__input"
              data-role="manual-recording-field"
              data-field="labelPresetId"
              ${disableForm ? 'disabled' : ''}
            >
              ${MANUAL_CAPTURE_PRESETS.map((preset) => `
                <option value="${escapeHtml(preset.id)}" ${String(manual.labelPresetId || 'custom') === preset.id ? 'selected' : ''}>${escapeHtml(preset.label)}</option>
              `).join('')}
            </select>
          </label>

          <label class="manual-recorder__field">
            <span>${escapeHtml(UI_LOCALE.capture.manualLabelVariant)}</span>
            <select
              class="manual-recorder__input"
              data-role="manual-recording-field"
              data-field="labelVariantId"
              ${disableForm ? 'disabled' : ''}
            >
              ${(selectedPreset?.variants || []).map((variant) => `
                <option value="${escapeHtml(variant.id)}" ${String(manual.labelVariantId || selectedPreset?.variants?.[0]?.id || '') === variant.id ? 'selected' : ''}>${escapeHtml(variant.label)}</option>
              `).join('')}
            </select>
          </label>

          <label class="manual-recorder__field manual-recorder__field--wide">
            <span>${escapeHtml(UI_LOCALE.capture.manualLabel)}</span>
            <input
              type="text"
              class="manual-recorder__input"
              data-role="manual-recording-field"
              data-field="label"
              value="${escapeHtml(manual.label || '')}"
              placeholder="${escapeHtml(generatedLabel || 'авто или из каталога')}"
              ${disableForm ? 'disabled' : ''}
            >
          </label>

          <label class="manual-recorder__field">
            <span>${escapeHtml(UI_LOCALE.capture.manualPersons)}</span>
            <select
              class="manual-recorder__input"
              data-role="manual-recording-field"
              data-field="personCount"
              ${disableForm ? 'disabled' : ''}
            >
              ${[0, 1, 2, 3, 4].map((value) => `
                <option value="${value}" ${Number(manual.personCount) === value ? 'selected' : ''}>${value}</option>
              `).join('')}
            </select>
          </label>

          <label class="manual-recorder__field">
            <span>${escapeHtml(UI_LOCALE.capture.manualChunk)}</span>
            <select
              class="manual-recorder__input"
              data-role="manual-recording-field"
              data-field="chunkSec"
              ${disableForm ? 'disabled' : ''}
            >
              ${[
                { value: 30, label: '30 с' },
                { value: 60, label: '1 мин' },
                { value: 120, label: '2 мин' },
                { value: 300, label: '5 мин' }
              ].map((item) => `
                <option value="${item.value}" ${Number(manual.chunkSec) === item.value ? 'selected' : ''}>${item.label}</option>
              `).join('')}
            </select>
          </label>

          <label class="manual-recorder__field manual-recorder__field--wide">
            <span>${escapeHtml(UI_LOCALE.capture.manualMotionType)}</span>
            <select
              class="manual-recorder__input"
              data-role="manual-recording-field"
              data-field="motionType"
              ${disableForm ? 'disabled' : ''}
            >
              ${[
                { value: '', label: 'без тега' },
                { value: 'empty', label: 'пусто' },
                { value: 'static', label: 'статика' },
                { value: 'breathing', label: 'дыхание' },
                { value: 'in_place_motion', label: 'движение на месте' },
                { value: 'transition', label: 'переходное движение' },
                { value: 'walking', label: 'ходьба' },
                { value: 'mixed', label: 'смешанный' },
                { value: 'entry_exit', label: 'вход / выход' }
              ].map((item) => `
                <option value="${escapeHtml(item.value)}" ${String(manual.motionType || '') === item.value ? 'selected' : ''}>${escapeHtml(item.label)}</option>
              `).join('')}
            </select>
          </label>

          <label class="manual-recorder__field manual-recorder__field--wide">
            <span>${escapeHtml(UI_LOCALE.capture.manualNotes)}</span>
            <input
              type="text"
              class="manual-recorder__input"
              data-role="manual-recording-field"
              data-field="notes"
              value="${escapeHtml(manual.notes || '')}"
              placeholder="${escapeHtml(generatedNotes || 'опционально')}"
              ${disableForm ? 'disabled' : ''}
            >
          </label>
        </div>

        <div class="panel__footer manual-recorder__selection-note manual-recorder__selection-note--scenario">
          ${escapeHtml(
            selectedPreset?.id === 'custom'
              ? UI_LOCALE.capture.manualSelectionHintCustom
              : `${UI_LOCALE.capture.manualSelectionHintPreset}: ${selectedPreset.label}${selectedVariant ? ` · ${selectedVariant.label}` : ''}`
          )}
        </div>
        <div class="panel__footer manual-recorder__selection-note">
          ${escapeHtml(UI_LOCALE.capture.manualManualEditHint)}
        </div>

        <div class="manual-recorder__toggles">
          <label class="manual-recorder__toggle">
            <input type="checkbox" data-role="manual-recording-field" data-field="withVideo" ${manual.withVideo ? 'checked' : ''} ${disableForm ? 'disabled' : ''}>
            <span>${escapeHtml(UI_LOCALE.capture.manualVideo)}</span>
          </label>
          <label class="manual-recorder__toggle">
            <input type="checkbox" data-role="manual-recording-field" data-field="voicePrompt" ${manual.voicePrompt !== false ? 'checked' : ''} ${disableForm ? 'disabled' : ''}>
            <span>${escapeHtml(UI_LOCALE.capture.manualVoice)}</span>
          </label>
          <label class="manual-recorder__toggle">
            <input type="checkbox" data-role="manual-recording-field" data-field="skipPreflight" ${manual.skipPreflight ? 'checked' : ''} ${disableForm ? 'disabled' : ''}>
            <span>${escapeHtml(UI_LOCALE.capture.manualSkipPreflight)}</span>
          </label>
        </div>

        <div class="panel__footer">${escapeHtml(UI_LOCALE.capture.manualLabelAuto)}</div>

        <div class="hero-tags">
          ${renderStatusPill('архивная ветка', 'warn')}
          ${manual.withVideo ? renderStatusPill('видео-override', 'info') : renderStatusPill('без teacher-видео', 'risk')}
          ${manual.skipPreflight ? renderStatusPill('пропуск предпроверки', 'risk') : renderStatusPill('предпроверка обязательна', 'ok')}
          ${manualActive ? renderStatusPill(UI_LOCALE.capture.manualActive, 'risk') : ''}
          ${guidedActive ? renderStatusPill('guided-пакет активен', 'warn') : ''}
          ${freeformActive ? renderStatusPill('freeform-режим активен', 'warn') : ''}
          ${renderStatusPill(getStartupSignalGuardLabel(startupSignalGuard), getStartupSignalGuardTone(startupSignalGuard))}
          ${recording.preflightLoading ? renderStatusPill(UI_LOCALE.capture.preflightRunning, 'info') : ''}
          ${recording.preflightError ? renderStatusPill(recording.preflightError, 'risk') : ''}
          ${preflight.ok ? renderStatusPill(UI_LOCALE.capture.preflightReady, 'ok') : ''}
        </div>
        ${recording.actionError ? `<div class="empty-state empty-state--error">${escapeHtml(recording.actionError)}</div>` : ''}

        <div class="capture-console__actions manual-recorder__actions">
          <button
            type="button"
            class="capture-pack__button capture-pack__button--ghost"
            data-action="manual-preflight"
            data-manual-video="${manual.withVideo ? 'true' : 'false'}"
            ${manualActive ? 'disabled' : ''}
          >
            ${escapeHtml(UI_LOCALE.capture.manualPreflight)}
          </button>
          <button
            type="button"
            class="capture-pack__button capture-pack__button--primary"
            data-action="${manualActive ? 'manual-stop' : 'manual-start'}"
            ${guidedActive || freeformActive ? 'disabled' : ''}
          >
            ${escapeHtml(manualActive ? UI_LOCALE.capture.manualStop : UI_LOCALE.capture.manualStart)}
          </button>
        </div>

        <div class="surface-grid surface-grid--two manual-recorder__status-grid">
          <article class="panel">
            <div class="panel__eyebrow">${escapeHtml(UI_LOCALE.capture.manualStatus)}</div>
            <div class="kv-list">
              <div class="kv"><span>Состояние</span><strong>${escapeHtml(currentStateText)}</strong></div>
              <div class="kv"><span>Метка</span><strong>${escapeHtml(getRecordingLabelText(status, currentLabel))}</strong></div>
              <div class="kv"><span>Длительность</span><strong>${escapeHtml(manualActive ? formatDurationCompact(status.elapsed_sec) : formatDurationCompact(manual.chunkSec))}</strong></div>
              <div class="kv"><span>${escapeHtml(UI_LOCALE.capture.manualLastChunk)}</span><strong>${escapeHtml(getLastChunkText(status))}</strong></div>
            </div>
          </article>

          <article class="panel">
            <div class="panel__eyebrow">${escapeHtml(UI_LOCALE.capture.manualChecks)}</div>
            <div class="kv-list">
              <div class="kv"><span>${escapeHtml(UI_LOCALE.capture.nodesReady)}</span><strong>${escapeHtml(`${readyNodes}/${totalNodes}`)}</strong></div>
              <div class="kv"><span>${escapeHtml(UI_LOCALE.capture.videoReady)}</span><strong>${escapeHtml(videoChecked ? formatBoolean(videoReady) : UI_LOCALE.common.optional)}</strong></div>
              <div class="kv"><span>${escapeHtml(UI_LOCALE.capture.operationalReady)}</span><strong>${escapeHtml(formatBoolean(preflight.ok))}</strong></div>
              <div class="kv"><span>PPS</span><strong>${escapeHtml(manualActive ? `${formatNumber(status.chunk_pps, 1)} pps` : 'ещё не пишет')}</strong></div>
              <div class="kv"><span>Guard</span><strong>${escapeHtml(getStartupSignalGuardLabel(startupSignalGuard))}</strong></div>
              <div class="kv"><span>Guard fact</span><strong>${escapeHtml(`${formatNumber(startupSignalGuard.metrics.activeCoreNodes ?? 0)} nodes / ${formatNumber(startupSignalGuard.metrics.packets ?? 0)} packets / ${formatNumber(startupSignalGuard.metrics.pps, 1)} pps`)}</strong></div>
            </div>
          </article>
        </div>
      </div>
    `;
  }

  renderFreeformRecordingConsole(recording) {
    const freeform = recording.freeform || {};
    const teacherSource = getTeacherSourceSelection(recording);
    const lastSummary = freeform.lastSummary || null;
    const startupSignalGuard = getStartupSignalGuard(recording);
    const stopResult = getRecordingStopResult(recording);
    const canonical = getCanonicalRecordingState(this.snapshot);
    const preflight = canonical.preflight || {};
    const status = recording.status || {};
    const guidedActive = canonical.guidedActive;
    const manualActive = canonical.manualActive;
    const freeformActive = canonical.freeformActive;
    const legacyFreeformActive = canonical.legacyFreeformActive;
    const disableForm = freeformActive || guidedActive || manualActive;
    const personCountValue = String(freeform.personCount || canonical.personCount || 1);
    const roleHintText = getFreeformRoleHintText(freeform.personCount || canonical.personCount || 1);
    const currentLabel = status.label || freeform.label || 'freeform-метка будет сгенерирована';
    const currentStateText = freeformActive
      ? UI_LOCALE.capture.freeformActive
      : legacyFreeformActive
        ? 'Канонический flow ждёт завершения архивного freeform без видео'
        : guidedActive
          ? 'Канонический flow ждёт завершения архивного guided‑пакета'
        : manualActive
          ? 'Канонический flow ждёт завершения ручной записи'
          : 'Канонический freeform ждёт preflight и явный старт';
    const activeNodes = freeformActive ? getActiveNodeCount(status) : canonical.readyNodes;
    const summaryNodePackets = Object.entries(lastSummary?.nodePackets || {}).sort(([left], [right]) => left.localeCompare(right));
    const summaryArtifactPath = lastSummary?.lastChunk?.summary_path || lastSummary?.lastChunk?.clip_path || null;
    const summaryArtifactHref = buildLocalFileHref(summaryArtifactPath);
    const summaryArtifactLabel = lastSummary?.lastChunk?.summary_path
      ? UI_LOCALE.capture.freeformOpenSummary
      : UI_LOCALE.capture.freeformOpenClip;
    const selectedTeacherKind = normalizeTeacherSourceKind(teacherSource.selectedKind);
    const showLegacyTeacherSource = this.runtimeRecordingUi.showLegacyTeacherSource || selectedTeacherKind === TEACHER_SOURCE_KIND.NONE;
    const teacherChoiceHint = selectedTeacherKind === TEACHER_SOURCE_KIND.PIXEL_RTSP
      ? 'Самый сильный канонический путь: Pixel RTSP через атомарный teacher-контракт.'
      : selectedTeacherKind === TEACHER_SOURCE_KIND.MAC_CAMERA
        ? 'Резервный путь: явная контрактная конфигурация Mac Camera вместо неявного значения Darwin по умолчанию.'
        : 'Архивный путь. Подходит только для совместимости.';
    const teacherSourceFieldLabel = selectedTeacherKind === TEACHER_SOURCE_KIND.PIXEL_RTSP
      ? 'RTSP URL'
      : selectedTeacherKind === TEACHER_SOURCE_KIND.MAC_CAMERA
        ? 'Выбор устройства'
        : 'Архивная заметка';
    const teacherSourceFieldValue = selectedTeacherKind === TEACHER_SOURCE_KIND.PIXEL_RTSP
      ? (teacherSource.pixelRtspUrl || DEFAULT_PIXEL_RTSP_URL)
      : selectedTeacherKind === TEACHER_SOURCE_KIND.MAC_CAMERA
        ? (teacherSource.macDevice || DEFAULT_MAC_CAMERA_DEVICE)
        : 'teacher_source_kind=none';
    const teacherStateText = canonical.teacher.stateLabel === 'available'
      ? 'источник teacher доступен'
      : canonical.teacher.stateLabel === 'unavailable'
        ? 'источник teacher недоступен'
      : canonical.teacher.stateLabel === 'legacy_selected'
          ? 'источник teacher архив/деградация'
        : 'источник teacher не проверен';
    const truthStateText = canonical.truth.label === 'с видео'
      ? 'truth полный'
      : canonical.truth.label === 'доверие потеряно'
        ? 'доверие потеряно'
        : canonical.truth.label === 'деградация'
          ? 'truth деградирован'
          : canonical.truth.label;
    const startDisabled = !freeformActive && !canonical.startReady;
    const blockReasons = recording.actionError
      ? [recording.actionError, ...canonical.blockReasons.filter((item) => item !== recording.actionError)]
      : canonical.blockReasons;
    const deadOnStartBanner = stopResult?.deadOnStart
      ? `
        <div class="empty-state empty-state--error">
          <strong>csi_dead_on_start</strong><br>
          ${escapeHtml(stopResult.message || 'CSI сигнал не пошёл. Запись остановлена.')}<br>
          Guard: ${escapeHtml(getStartupSignalGuardLabel(startupSignalGuard))}
        </div>
      `
      : '';

    return `
      <div class="manual-recorder freeform-recorder canonical-recorder">
        <div class="panel__eyebrow">Основной операторский путь</div>
        <div class="panel__headline">Свободная запись одной персоны / видео по умолчанию</div>
        <div class="panel__text">Текущий практический поток: garage router + все антенны. Источник teacher должен быть явным, предпроверка честной, а голосовые подсказки остаются частью процесса.</div>

        <div class="hero-tags">
          ${renderStatusPill('garage router + все антенны', 'info')}
          ${renderStatusPill('видео по умолчанию', 'warn')}
          ${renderStatusPill(teacherStateText, canonical.teacher.tone)}
          ${renderStatusPill(truthStateText, canonical.truth.tone)}
          ${renderStatusPill(canonical.voiceEnabled ? 'голосовые подсказки включены' : 'голосовые подсказки выключены', canonical.voiceEnabled ? 'ok' : 'neutral')}
          ${Number(personCountValue || 1) === 1 ? renderStatusPill('одна персона по умолчанию', 'ok') : renderStatusPill('многоперсонный режим', 'warn')}
          ${freeformActive ? renderStatusPill('идёт primary operator session', 'risk') : ''}
          ${legacyFreeformActive ? renderStatusPill('архивный freeform без видео', 'risk') : ''}
          ${guidedActive ? renderStatusPill('архивный guided активен', 'warn') : ''}
          ${manualActive && !legacyFreeformActive ? renderStatusPill('ручной режим активен', 'warn') : ''}
          ${renderStatusPill(getStartupSignalGuardLabel(startupSignalGuard), getStartupSignalGuardTone(startupSignalGuard))}
          ${recording.preflightLoading ? renderStatusPill(UI_LOCALE.capture.preflightRunning, 'info') : ''}
        </div>

        <div class="surface-grid surface-grid--two manual-recorder__status-grid canonical-recorder__status-grid">
          <article class="panel">
            <div class="panel__eyebrow">Источник teacher</div>
            <div class="kv-list">
              <div class="kv"><span>Выбранный contract</span><strong>${escapeHtml(canonical.teacher.selectionLabel)}</strong></div>
              <div class="kv"><span>Источник runtime</span><strong>${escapeHtml(canonical.teacher.selected ? canonical.teacher.label : 'не выбран')}</strong></div>
              <div class="kv"><span>Контракт видео</span><strong>${escapeHtml(canonical.teacher.required ? UI_LOCALE.common.required : UI_LOCALE.common.optional)}</strong></div>
              <div class="kv"><span>Состояние</span><strong>${escapeHtml(teacherStateText)}</strong></div>
              <div class="kv"><span>Источник</span><strong>${escapeHtml(canonical.teacher.detail)}</strong></div>
            </div>
            <div class="panel__footer">${escapeHtml(canonical.teacher.reason)}</div>
          </article>

          <article class="panel">
            <div class="panel__eyebrow">${escapeHtml(UI_LOCALE.capture.preflightPanel)}</div>
            <div class="kv-list">
              <div class="kv"><span>${escapeHtml(UI_LOCALE.capture.nodesReady)}</span><strong>${escapeHtml(`${canonical.readyNodes}/${canonical.totalNodes}`)}</strong></div>
              <div class="kv"><span>${escapeHtml(UI_LOCALE.capture.videoReady)}</span><strong>${escapeHtml(canonical.videoChecked ? formatBoolean(canonical.videoAvailable) : 'ожидает явную проверку')}</strong></div>
              <div class="kv"><span>${escapeHtml(UI_LOCALE.capture.operationalReady)}</span><strong>${escapeHtml(canonical.videoChecked ? formatBoolean(Boolean(preflight.ok && canonical.videoAvailable)) : 'нет')}</strong></div>
              <div class="kv"><span>${escapeHtml(UI_LOCALE.capture.freeformNodesActive)}</span><strong>${escapeHtml(freeformActive ? `${activeNodes}/${Math.max(activeNodes, DEFAULT_VISIBLE_NODE_COUNT)}` : `${canonical.readyNodes}/${canonical.totalNodes}`)}</strong></div>
            </div>
            <div class="panel__footer">${escapeHtml(recording.preflightError || preflight.error || (preflight.ok ? 'Предпроверка подтвердила узлы и источник teacher с видео.' : 'Без предпроверки старт остаётся заблокирован.'))}</div>
          </article>

          <article class="panel">
            <div class="panel__eyebrow">Слой truth</div>
            <div class="kv-list">
              <div class="kv"><span>Статус</span><strong>${escapeHtml(truthStateText)}</strong></div>
              <div class="kv"><span>Живое доверие</span><strong>${escapeHtml(displayToken(this.snapshot?.live?.trust?.label || 'unknown'))}</strong></div>
              <div class="kv"><span>Support‑контекст</span><strong>${escapeHtml(displayToken(this.snapshot?.live?.supportPath?.contextValidity || 'unknown'))}</strong></div>
              <div class="kv"><span>Активные источники</span><strong>${escapeHtml(`${Math.max(Number(this.snapshot?.live?.topology?.sourceCount) || 0, freeformActive ? activeNodes : canonical.readyNodes)}/${Math.max(Number(this.snapshot?.live?.topology?.sourceCount) || 0, freeformActive ? activeNodes : canonical.readyNodes, DEFAULT_VISIBLE_NODE_COUNT)}`)}</strong></div>
            </div>
            <div class="panel__footer">${escapeHtml(canonical.truth.summary)}</div>
          </article>

          <article class="panel">
            <div class="panel__eyebrow">${escapeHtml(UI_LOCALE.capture.freeformStatus)}</div>
            <div class="kv-list">
              <div class="kv"><span>Состояние</span><strong>${escapeHtml(currentStateText)}</strong></div>
              <div class="kv"><span>${escapeHtml(UI_LOCALE.capture.freeformLabel)}</span><strong>${escapeHtml(getRecordingLabelText(status, currentLabel))}</strong></div>
              <div class="kv"><span>${escapeHtml(UI_LOCALE.capture.freeformRoleHint)}</span><strong>${escapeHtml(roleHintText)}</strong></div>
              <div class="kv"><span>Прошло</span><strong>${escapeHtml(freeformActive ? formatDurationCompact(status.elapsed_sec) : 'до явной остановки')}</strong></div>
            </div>
            <div class="panel__footer">${escapeHtml(freeformActive ? 'Во время активной сессии слой truth отслеживается отдельно и больше не считается автоматически валидным.' : 'Канонический старт открывается только после честной предпроверки и проверки источника teacher.')}</div>
          </article>

          <article class="panel">
            <div class="panel__eyebrow">CSI-guard после старта</div>
            <div class="kv-list">
              <div class="kv"><span>Статус</span><strong>${escapeHtml(getStartupSignalGuardLabel(startupSignalGuard))}</strong></div>
              <div class="kv"><span>Пауза</span><strong>${escapeHtml(formatDurationCompact(startupSignalGuard.thresholds.graceSec))}</strong></div>
              <div class="kv"><span>Мин. узлов</span><strong>${escapeHtml(formatNumber(startupSignalGuard.thresholds.minActiveCoreNodes))}</strong></div>
              <div class="kv"><span>Мин. пакетов</span><strong>${escapeHtml(formatNumber(startupSignalGuard.thresholds.minPackets))}</strong></div>
              <div class="kv"><span>Мин. pps</span><strong>${escapeHtml(formatNumber(startupSignalGuard.thresholds.minPps, 1))} pps</strong></div>
              <div class="kv"><span>Факт</span><strong>${escapeHtml(`${formatNumber(startupSignalGuard.metrics.activeCoreNodes ?? 0)} узлов / ${formatNumber(startupSignalGuard.metrics.packets ?? 0)} пакетов / ${formatNumber(startupSignalGuard.metrics.pps, 1)} pps`)}</strong></div>
            </div>
            <div class="panel__footer">${escapeHtml(startupSignalGuard.reason)}</div>
          </article>
        </div>

        ${deadOnStartBanner}

        <div class="manual-recorder__grid">
          <label class="manual-recorder__field">
            <span>Источник teacher</span>
            <select
              class="manual-recorder__input"
              data-role="teacher-source-field"
              data-field="selectedKind"
              ${disableForm ? 'disabled' : ''}
            >
              <option value="${TEACHER_SOURCE_KIND.PIXEL_RTSP}" ${selectedTeacherKind === TEACHER_SOURCE_KIND.PIXEL_RTSP ? 'selected' : ''}>Pixel RTSP (основной)</option>
              <option value="${TEACHER_SOURCE_KIND.MAC_CAMERA}" ${selectedTeacherKind === TEACHER_SOURCE_KIND.MAC_CAMERA ? 'selected' : ''}>Камера Mac (резерв)</option>
              ${showLegacyTeacherSource ? `<option value="${TEACHER_SOURCE_KIND.NONE}" ${selectedTeacherKind === TEACHER_SOURCE_KIND.NONE ? 'selected' : ''}>none (архивный/деградированный)</option>` : ''}
            </select>
          </label>

          ${selectedTeacherKind === TEACHER_SOURCE_KIND.PIXEL_RTSP ? `
            <label class="manual-recorder__field">
              <span>${escapeHtml(teacherSourceFieldLabel)}</span>
              <input
                type="url"
                class="manual-recorder__input"
                data-role="teacher-source-field"
                data-field="pixelRtspUrl"
                value="${escapeHtml(teacherSourceFieldValue)}"
                placeholder="rtsp://..."
                ${disableForm ? 'disabled' : ''}
              >
            </label>
          ` : selectedTeacherKind === TEACHER_SOURCE_KIND.MAC_CAMERA ? `
            <label class="manual-recorder__field">
              <span>${escapeHtml(teacherSourceFieldLabel)}</span>
              <input
                type="text"
                class="manual-recorder__input"
                data-role="teacher-source-field"
                data-field="macDevice"
                value="${escapeHtml(teacherSourceFieldValue)}"
                placeholder="0"
                ${disableForm ? 'disabled' : ''}
              >
            </label>
          ` : `
            <div class="manual-recorder__field">
              <span>${escapeHtml(teacherSourceFieldLabel)}</span>
              <div class="manual-recorder__input manual-recorder__input--locked">${escapeHtml(teacherSourceFieldValue)}</div>
            </div>
          `}

          <div class="manual-recorder__field">
            <span>Контракт teacher</span>
            <div class="manual-recorder__input manual-recorder__input--locked">${escapeHtml(teacherChoiceHint)}</div>
          </div>

          <label class="manual-recorder__field">
            <span>${escapeHtml(UI_LOCALE.capture.freeformPersonCount)}</span>
            <select
              class="manual-recorder__input"
              data-role="freeform-recording-field"
              data-field="personCount"
              ${disableForm ? 'disabled' : ''}
            >
              <option value="1" ${personCountValue === '1' ? 'selected' : ''}>1</option>
              <option value="2" ${personCountValue === '2' ? 'selected' : ''}>2</option>
              <option value="3" ${personCountValue === '3' ? 'selected' : ''}>3+</option>
            </select>
          </label>

          <label class="manual-recorder__field">
            <span>${escapeHtml(UI_LOCALE.capture.freeformChunk)}</span>
            <select
              class="manual-recorder__input"
              data-role="freeform-recording-field"
              data-field="chunkSec"
              ${disableForm ? 'disabled' : ''}
            >
              ${[
                { value: 60, label: '1 мин' },
                { value: 120, label: '2 мин' },
                { value: 300, label: '5 мин' },
                { value: 600, label: '10 мин' }
              ].map((item) => `
                <option value="${item.value}" ${Number(freeform.chunkSec || 60) === item.value ? 'selected' : ''}>${item.label}</option>
              `).join('')}
            </select>
          </label>

          <div class="manual-recorder__field">
            <span>${escapeHtml(UI_LOCALE.capture.freeformMandatoryVideo)}</span>
            <div class="manual-recorder__input manual-recorder__input--locked">${escapeHtml(UI_LOCALE.common.required)}</div>
          </div>

          <label class="manual-recorder__field manual-recorder__field--wide">
            <span>${escapeHtml(UI_LOCALE.capture.freeformLabel)}</span>
            <input
              type="text"
              class="manual-recorder__input"
              data-role="freeform-recording-field"
              data-field="label"
              value="${escapeHtml(freeform.label || '')}"
              placeholder="auto: freeform_pN_..."
              ${disableForm ? 'disabled' : ''}
            >
          </label>

          <label class="manual-recorder__field manual-recorder__field--wide">
            <span>${escapeHtml(UI_LOCALE.capture.freeformNotes)}</span>
            <textarea
              class="manual-recorder__input manual-recorder__textarea"
              data-role="freeform-recording-field"
              data-field="notes"
              placeholder="${escapeHtml(UI_LOCALE.capture.freeformNotesHint)}"
              ${disableForm ? 'disabled' : ''}
            >${escapeHtml(freeform.notes || '')}</textarea>
          </label>
        </div>

        <div class="panel__footer manual-recorder__selection-note freeform-recorder__selection-note--role">
          ${escapeHtml(`Одна персона по умолчанию: ${getFreeformRoleHintText(1)}. Текущий выбор: ${roleHintText}`)}
        </div>
        ${!showLegacyTeacherSource ? `
          <div class="panel__footer manual-recorder__selection-note">
            <button type="button" class="capture-pack__button capture-pack__button--ghost" data-action="toggle-legacy-teacher-source" ${disableForm ? 'disabled' : ''}>Показать архивный source none</button>
          </div>
        ` : `
          <div class="panel__footer manual-recorder__selection-note">
            ${escapeHtml('Архивный source none показан только как опция advanced. Для канонического старта нужен источник teacher с видео.')}
          </div>
        `}
        <div class="panel__footer manual-recorder__selection-note">
          ${escapeHtml(`${UI_LOCALE.capture.freeformLabelAuto} Источник teacher с видео обязателен для канонического старта.`)}
        </div>

        <div class="manual-recorder__toggles">
          <label class="manual-recorder__toggle">
            <input type="checkbox" checked disabled>
            <span>${escapeHtml(UI_LOCALE.capture.freeformMandatoryVideo)}</span>
          </label>
          <label class="manual-recorder__toggle">
            <input type="checkbox" data-role="freeform-recording-field" data-field="voiceCue" ${freeform.voiceCue !== false ? 'checked' : ''} ${disableForm ? 'disabled' : ''}>
            <span>${escapeHtml(UI_LOCALE.capture.freeformVoiceCue)}</span>
          </label>
        </div>

        <div class="capture-console__actions manual-recorder__actions">
          <button
            type="button"
            class="capture-pack__button capture-pack__button--ghost"
            data-action="freeform-preflight"
            ${freeformActive ? 'disabled' : ''}
          >
            ${escapeHtml(UI_LOCALE.capture.freeformPreflight)}
          </button>
          <button
            type="button"
            class="capture-pack__button capture-pack__button--primary"
            data-action="${freeformActive ? 'freeform-stop' : 'freeform-start'}"
            ${freeformActive ? '' : startDisabled ? 'disabled' : ''}
          >
            ${escapeHtml(freeformActive ? UI_LOCALE.capture.freeformStop : UI_LOCALE.capture.freeformStart)}
          </button>
        </div>

        ${blockReasons.length ? `
          <div class="recording-honesty-note recording-honesty-note--${escapeHtml(freeformActive ? canonical.truth.tone : 'warn')}">
            <strong>${escapeHtml(freeformActive ? 'Честное состояние сессии' : 'Почему старт сейчас заблокирован')}</strong>
            <ul class="recording-honesty-list">
              ${blockReasons.map((reason) => `<li>${escapeHtml(reason)}</li>`).join('')}
            </ul>
          </div>
        ` : ''}

        ${lastSummary && !freeformActive ? `
          <article class="panel freeform-summary">
            <div class="panel__eyebrow">${escapeHtml(UI_LOCALE.capture.freeformLastSummary)}</div>
            <div class="kv-list">
              <div class="kv"><span>${escapeHtml(UI_LOCALE.capture.freeformLabel)}</span><strong>${escapeHtml(lastSummary.label || 'метка stop-result не пришла')}</strong></div>
              <div class="kv"><span>${escapeHtml(UI_LOCALE.capture.freeformStoppedAt)}</span><strong>${escapeHtml(formatTimestamp(lastSummary.stoppedAt))}</strong></div>
              <div class="kv"><span>${escapeHtml(UI_LOCALE.capture.freeformDuration)}</span><strong>${escapeHtml(formatDurationCompact(lastSummary.durationSec))}</strong></div>
              <div class="kv"><span>${escapeHtml(UI_LOCALE.capture.freeformTotalChunks)}</span><strong>${escapeHtml(lastSummary.totalChunks != null ? formatNumber(lastSummary.totalChunks) : 'backend не прислал total_chunks')}</strong></div>
              <div class="kv"><span>${escapeHtml(UI_LOCALE.capture.freeformTotalPackets)}</span><strong>${escapeHtml(lastSummary.totalPackets != null ? formatNumber(lastSummary.totalPackets) : 'backend не прислал total_packets')}</strong></div>
              <div class="kv"><span>${escapeHtml(UI_LOCALE.capture.freeformLastChunk)}</span><strong>${escapeHtml(lastSummary.lastChunk?.label || 'backend не прислал last_chunk')}</strong></div>
              <div class="kv"><span>${escapeHtml(UI_LOCALE.capture.freeformMandatoryVideo)}</span><strong>${escapeHtml(lastSummary.withVideo ? 'записывалось' : 'backend не подтвердил видео')}</strong></div>
              <div class="kv"><span>${escapeHtml(UI_LOCALE.capture.freeformRoleHint)}</span><strong>${escapeHtml(getFreeformRoleHintText(lastSummary.personCount || freeform.personCount || 1))}</strong></div>
            </div>
            <div class="panel__footer">${escapeHtml(UI_LOCALE.capture.freeformSummarySource)}</div>
            ${summaryArtifactHref ? `
              <div class="capture-console__actions manual-recorder__actions">
                <a
                  class="capture-pack__button capture-pack__button--ghost"
                  href="${escapeHtml(summaryArtifactHref)}"
                  target="_blank"
                  rel="noreferrer"
                >
                  ${escapeHtml(summaryArtifactLabel)}
                </a>
              </div>
            ` : ''}
            <div class="token-row capture-pack__steps">
              ${summaryNodePackets.length
                ? summaryNodePackets.map(([nodeName, count]) => `<span class="token">${escapeHtml(`${nodeName}: ${formatNumber(count)}`)}</span>`).join('')
                : `<span class="muted">${escapeHtml('backend не прислал node_packets')}</span>`}
            </div>
          </article>
        ` : ''}
      </div>
    `;
  }

  renderFewshotCalibrationConsole(recording) {
    const fewshot = recording.fewshotCalibration || {};
    const protocol = getFewshotCalibrationProtocol(fewshot.protocolId || FEWSHOT_CALIBRATION_PROTOCOLS[0]?.id);
    const zoneShadow = this.snapshot?.live?.zoneCalibrationShadow || {};
    const primaryRuntime = this.snapshot?.live?.primaryRuntime || {};
    const liveNodes = Math.max(
      Number(primaryRuntime.nodesActive) || 0,
      Number(this.snapshot?.live?.topology?.sourceCount) || 0
    );
    const recordingMode = getRecordingMode(recording);
    const fewshotActive = ACTIVE_FEWSHOT_STATUSES.includes(fewshot.status || 'idle');
    const csiBackendStatus = this.snapshot?.csi?.status || null;
    const csiBackendMessage = this.snapshot?.csi?.status_message || null;
    const csiHealthy = csiBackendStatus
      ? csiBackendStatus === 'healthy'
      : (Boolean(this.snapshot?.csi?.running) && Boolean(this.snapshot?.csi?.model_loaded));
    const canStart = !fewshotActive
      && !recordingMode
      && csiHealthy
      && liveNodes >= 3;
    const blockedReasons = [];
    if (csiBackendStatus && csiBackendStatus !== 'healthy') {
      blockedReasons.push(csiBackendMessage || `CSI runtime сейчас в состоянии ${displayToken(csiBackendStatus)}.`);
    } else {
      if (!this.snapshot?.csi?.running) {
        blockedReasons.push('CSI runtime не запущен.');
      }
      if (this.snapshot?.csi?.running && !this.snapshot?.csi?.model_loaded) {
        blockedReasons.push('CSI runtime поднят, но модель не загружена.');
      }
    }
    if (liveNodes < 3) {
      blockedReasons.push('Нужно минимум 3 активные ноды, чтобы calibration windows были валидны.');
    }
    if (recordingMode === 'freeform') {
      blockedReasons.push('Сейчас идёт freeform-запись. Few-shot calibration ждёт завершения записи.');
    } else if (recordingMode === 'guided') {
      blockedReasons.push('Сейчас активен архивный guided‑пакет. Few‑shot calibration ждёт освобождения backend.');
    } else if (recordingMode === 'manual') {
      blockedReasons.push('Сейчас идёт ручная запись. Few-shot calibration ждёт освобождения backend.');
    }
    if (recording.actionError && !blockedReasons.includes(recording.actionError)) {
      blockedReasons.unshift(recording.actionError);
    }

    const currentStep = fewshot.currentStep || null;
    const fitResult = fewshot.fitResult || null;
  const runtimeWindowNote = 'Текущий shadow backend собирает окна на native cadence runtime и не гарантирует ровно 10 research‑окон на шаг.';
    const researchTransitionNote = 'Переходный шаг нужен для будущего few-shot storage path. Сейчас он идёт как guided cue и НЕ попадает в текущий centroid fit.';

    return `
      <article class="panel">
        <div class="panel__eyebrow">Руководимая few-shot калибровка</div>
        <div class="panel__headline">${escapeHtml(protocol.name)}</div>
        <div class="panel__text">Live‑геометрия уже пересобрана в <strong>center</strong> и <strong>door_passage</strong>. Deep здесь не используется. Этот UI пока не меняет production V20 и работает только как shadow‑калибровка.</div>

        <div class="hero-tags">
          ${renderStatusPill('только shadow', 'warn')}
          ${renderStatusPill(`ожидаемая LODO BA ${formatNumber(protocol.expectedDateLodoBa, 2)}`, 'ok')}
          ${renderStatusPill(`окна: ${formatNumber(protocol.totalWindows)}`, 'info')}
          ${renderStatusPill(`время: ${formatDurationCompact(protocol.totalDurationSec)}`, 'info')}
          ${fewshotActive ? renderStatusPill(`идёт ${escapeHtml(fewshot.status)}`, 'risk') : renderStatusPill('готов к старту', canStart ? 'ok' : 'warn')}
          ${renderStatusPill(`живые узлы: ${formatNumber(liveNodes)}`, liveNodes >= 3 ? 'ok' : 'warn')}
        </div>

        <div class="surface-grid surface-grid--three manual-recorder__status-grid">
          <article class="panel">
            <div class="panel__eyebrow">Граница runtime</div>
            <div class="kv-list">
              <div class="kv"><span>Боевой режим</span><strong>V20 occupancy</strong></div>
              <div class="kv"><span>Живая геометрия</span><strong>center vs door_passage</strong></div>
              <div class="kv"><span>Цель исследования</span><strong>${escapeHtml(formatNumber(protocol.totalWindows))} окон / ${escapeHtml(formatDurationCompact(protocol.totalDurationSec))}</strong></div>
              <div class="kv"><span>Текущий runtime support</span><strong>только shadow centroid</strong></div>
            </div>
            <div class="panel__footer">${escapeHtml(runtimeWindowNote)}</div>
          </article>

          <article class="panel">
            <div class="panel__eyebrow">Backend shadow centroid</div>
            <div class="kv-list">
              <div class="kv"><span>Статус</span><strong>${escapeHtml(zoneShadow.status || 'not_calibrated')}</strong></div>
              <div class="kv"><span>Качество</span><strong>${escapeHtml(zoneShadow.calibrationQuality || 'not_calibrated')}</strong></div>
              <div class="kv"><span>Окна center</span><strong>${escapeHtml(formatNumber(zoneShadow.nCalWindows?.center, 0))}</strong></div>
              <div class="kv"><span>Окна door</span><strong>${escapeHtml(formatNumber(zoneShadow.nCalWindows?.door, 0))}</strong></div>
              <div class="kv"><span>Последняя зона</span><strong>${escapeHtml(displayFewshotZone(zoneShadow.zone || 'unknown'))}</strong></div>
              <div class="kv"><span>Уверенность</span><strong>${zoneShadow.confidence != null ? escapeHtml(formatNumber(zoneShadow.confidence, 2)) : 'ещё нет окна'}</strong></div>
            </div>
            <div class="panel__footer">${escapeHtml(zoneShadow.rejectionReason || 'Текущий backend использует только явные шаги center/door и не подменяет production verdict.')}</div>
          </article>

          <article class="panel">
            <div class="panel__eyebrow">Состояние прогона</div>
            <div class="kv-list">
              <div class="kv"><span>Протокол</span><strong>${escapeHtml(protocol.shortLabel)}</strong></div>
              <div class="kv"><span>Статус</span><strong>${escapeHtml(fewshot.status || 'idle')}</strong></div>
              <div class="kv"><span>Текущий шаг</span><strong>${escapeHtml(currentStep ? `${currentStep.index + 1}/${currentStep.totalSteps} · ${currentStep.label}` : 'не выбран')}</strong></div>
              <div class="kv"><span>Таймер</span><strong>${escapeHtml(currentStep && fewshot.stepEndsAt ? formatCountdown(fewshot.stepEndsAt) : (fewshot.status === 'paused' ? formatCountdown(fewshot.pauseUntil) : 'не запущен'))}</strong></div>
              <div class="kv"><span>Подгонка</span><strong>${escapeHtml(fitResult ? (fitResult.ok === false ? 'ошибка' : 'готово') : 'ещё нет')}</strong></div>
              <div class="kv"><span>Последняя ошибка</span><strong>${escapeHtml(fewshot.lastError || 'нет')}</strong></div>
            </div>
            <div class="panel__footer">${escapeHtml(fitResult?.error || (fitResult ? `zones=${(fitResult.zones_calibrated || []).join(', ') || 'n/a'}` : researchTransitionNote))}</div>
          </article>
        </div>

        <div class="capture-console__actions manual-recorder__actions">
          ${FEWSHOT_CALIBRATION_PROTOCOLS.map((item) => `
            <button
              type="button"
              class="capture-pack__button ${(protocol.id === item.id && !fewshotActive) ? 'capture-pack__button--ghost' : 'capture-pack__button--primary'}"
              data-action="fewshot-calibration-start"
              data-protocol-id="${escapeHtml(item.id)}"
              ${fewshotActive || (!canStart && protocol.id !== item.id) || (!canStart && protocol.id === item.id) ? (fewshotActive ? 'disabled' : 'disabled') : ''}
            >
              ${escapeHtml(`Старт ${item.shortLabel}`)}
            </button>
          `).join('')}
          <button
            type="button"
            class="capture-pack__button capture-pack__button--ghost"
            data-action="fewshot-calibration-stop"
            ${fewshotActive ? '' : 'disabled'}
          >
            Остановить калибровку
          </button>
          <button
            type="button"
            class="capture-pack__button capture-pack__button--ghost"
            data-action="fewshot-calibration-reset"
            ${fewshotActive ? 'disabled' : ''}
          >
            Сбросить shadow‑калибровку
          </button>
        </div>

        ${blockedReasons.length ? `
          <div class="recording-honesty-note recording-honesty-note--warn">
            <strong>Почему старт few-shot сейчас заблокирован</strong>
            <ul class="recording-honesty-list">
              ${blockedReasons.map((reason) => `<li>${escapeHtml(reason)}</li>`).join('')}
            </ul>
          </div>
        ` : ''}

        <div class="surface-grid surface-grid--two">
          <article class="panel">
            <div class="panel__eyebrow">Шаги протокола</div>
            <div class="workflow-list">
              ${protocol.steps.map((step, index) => `
                <div class="workflow-item">
                  <span>${index + 1}</span>
                  <p>
                    <strong>${escapeHtml(step.label)}</strong><br>
                    Зона: ${escapeHtml(displayFewshotZone(step.displayZone))} · ${escapeHtml(formatDurationCompact(step.durationSec))} · цель ${escapeHtml(formatNumber(step.targetWindows))} исследовательских окон<br>
                    ${escapeHtml(step.instruction)}
                    ${step.researchOnly ? '<br><em>Только исследование: не идёт в текущую подгонку centroid.</em>' : ''}
                  </p>
                </div>
              `).join('')}
            </div>
          </article>

          <article class="panel">
            <div class="panel__eyebrow">Журнал прогона</div>
            ${fewshot.logs?.length ? `
              <div class="capture-console__log">
                ${fewshot.logs.map((entry, index) => `
                  <div class="capture-console__entry">
                    <strong>${escapeHtml(`${index + 1}. ${entry.stepLabel}`)}</strong><br>
                    status=${escapeHtml(entry.status || 'unknown')} · zone=${escapeHtml(displayFewshotZone(entry.displayZone || entry.captureZone || 'unknown'))}${entry.researchOnly ? ' · только исследование' : ''}<br>
                    ${entry.captureStopPayload?.windows_collected != null ? `windows=${escapeHtml(formatNumber(entry.captureStopPayload.windows_collected, 0))} · ` : ''}${entry.error ? `error=${escapeHtml(entry.error)}` : ''}
                  </div>
                `).join('')}
              </div>
            ` : `
              <div class="empty-state">Лог пуст. После старта здесь появятся шаги и capture status.</div>
            `}
          </article>
        </div>
      </article>
    `;
  }

  renderRecordingArchive(recording) {
    const guidedOpen = this.runtimeRecordingUi.showLegacyGuided;
    const manualOpen = this.runtimeRecordingUi.showLegacyManual;
    const showArchive = guidedOpen || manualOpen;

    if (!showArchive) {
      return '';
    }

    return `
      <div class="recording-archive">
        <div class="panel__eyebrow">Архивный режим</div>
        <div class="panel__headline">Старые ветки записи (не основной путь)</div>
          <div class="panel__text">Показывается только по запросу. Канонический путь — guided и freeform с видео.</div>
        <div class="hero-tags">
          ${renderStatusPill('guided = архивный', 'warn')}
          ${renderStatusPill('manual = совместимость', 'warn')}
        </div>
        <div class="capture-console__actions recording-archive__actions">
          <button
            type="button"
            class="capture-pack__button capture-pack__button--ghost"
            data-action="toggle-legacy-guided"
          >
            ${escapeHtml(guidedOpen ? 'Скрыть архивные guided' : 'Показать архивные guided')}
          </button>
          <button
            type="button"
            class="capture-pack__button capture-pack__button--ghost"
            data-action="toggle-legacy-manual"
          >
            ${escapeHtml(manualOpen ? 'Скрыть архивный manual' : 'Показать архивный manual')}
          </button>
        </div>

        ${guidedOpen ? `
          <div class="recording-archive__section">
            <div class="surface-grid surface-grid--two">
              <article class="panel">
                <div class="panel__eyebrow">Архивные guided‑пакеты</div>
                <div class="panel__text">Исторические пакеты без video‑backed по умолчанию.</div>
                <div class="capture-pack-grid">
                  ${GUIDED_CAPTURE_PACKS.map((pack) => this.renderGuidedCapturePackCard(pack, recording)).join('')}
                </div>
        ${recording.actionError ? `<div class="empty-state empty-state--error">${escapeHtml(recording.actionError)}</div>` : ''}
              </article>

              <article class="panel panel--capture">
                ${this.renderGuidedCaptureConsole(recording, getGuidedCapturePack(recording.guided?.packId || recording.selectedPackId))}
              </article>
            </div>
          </div>
        ` : ''}

        ${manualOpen ? `
          <div class="recording-archive__section">
            <article class="panel">
              ${this.renderManualRecordingConsole(recording)}
            </article>
          </div>
        ` : ''}
      </div>
    `;
  }

  renderRuntime() {
    const snapshot = this.snapshot;
    const metrics = snapshot.metrics?.metrics || {};
    const process = metrics.process || {};
    const cpu = metrics.cpu || {};
    const memory = metrics.memory || {};
    const disk = metrics.disk || {};
    const statusServices = snapshot.status?.services || {};
    const metricsService = statusServices.metrics || {};
    const healthServiceStatus = statusServices.health || {};
    const cpuValue = firstDefinedValue(process.cpu_percent, cpu.percent);
    const memoryMb = firstDefinedValue(
      process.memory_mb,
      memory.used_gb != null ? Number(memory.used_gb) * 1024 : null
    );
    const uptimeSeconds = firstDefinedValue(process.uptime_seconds, metricsService.uptime, healthServiceStatus.uptime);
    const cpuHeadline = process.cpu_percent != null ? 'CPU процесса' : 'CPU системы';
    const memoryHeadline = process.memory_mb != null ? 'Память процесса' : 'Память системы';
    const uptimeHeadline = process.uptime_seconds != null ? 'Аптайм процесса' : 'Аптайм API';
    const uptimeFooter = process.pid != null
      ? `pid ${escapeHtml(formatNumber(process.pid))}`
      : 'backend не публикует pid';
    const secondaryRuntime = snapshot.live.secondaryRuntime || {};
    const recording = snapshot.recording || {
      status: null,
      preflight: null,
      preflightLoading: false,
      preflightError: null,
      actionError: null,
      selectedPackId: GUIDED_CAPTURE_PACKS[0]?.id || null,
      guided: {
        status: 'idle',
        logs: []
      }
    };
    this.sections.runtime.innerHTML = `
      ${this.renderFewshotCalibrationConsole(recording)}

      <article class="panel">
        ${this.renderFreeformRecordingConsole(recording)}
      </article>

      <article class="panel">
        ${this.renderRecordingArchive(recording)}
      </article>

      <div class="surface-grid surface-grid--four">
        <article class="panel panel--metric">
          <div class="panel__eyebrow">${cpuHeadline}</div>
          <div class="panel__headline">${escapeHtml(formatNumberWithUnit(cpuValue, { digits: 1, unit: '%', missing: 'backend не прислал CPU-метрику' }))}</div>
          <div class="panel__footer">хост ${escapeHtml(formatNumber(cpu.percent, 1))}% / ${escapeHtml(formatNumber(cpu.count))} ядер</div>
        </article>
        <article class="panel panel--metric">
          <div class="panel__eyebrow">${memoryHeadline}</div>
          <div class="panel__headline">${escapeHtml(formatNumberWithUnit(memoryMb, { digits: 1, unit: ' MB', missing: 'backend не прислал memory-метрику' }))}</div>
          <div class="panel__footer">система ${escapeHtml(formatNumber(memory.percent, 1))}% занято</div>
        </article>
        <article class="panel panel--metric">
          <div class="panel__eyebrow">${uptimeHeadline}</div>
          <div class="panel__headline">${escapeHtml(formatRelativeTime(uptimeSeconds))}</div>
          <div class="panel__footer">${uptimeFooter}</div>
        </article>
        <article class="panel panel--metric">
          <div class="panel__eyebrow">Диск занят</div>
          <div class="panel__headline">${escapeHtml(formatNumber(disk.percent, 1))}%</div>
          <div class="panel__footer">${escapeHtml(formatNumber(disk.used_gb, 1))} / ${escapeHtml(formatNumber(disk.total_gb, 1))} GB</div>
        </article>
      </div>

      <div class="surface-grid surface-grid--one">
        <article class="panel">
          <div class="panel__eyebrow">Здоровье сервисов</div>
          <div class="service-grid">
            ${snapshot.services.map((service) => `
              <div class="service-card ${toneClass(statusTone(service.status))}">
                <span>${escapeHtml(service.name)}</span>
                <strong>${escapeHtml(displayToken(service.status))}</strong>
                <small>${escapeHtml(service.detail || (service.running ? UI_LOCALE.common.running : UI_LOCALE.common.noDetail))}</small>
              </div>
            `).join('')}
          </div>
        </article>
      </div>

      <div class="surface-grid surface-grid--two">
        <article class="panel">
          <div class="panel__eyebrow">Corpus / видимость артефактов</div>
          <div class="artifact-groups">
            ${AGENT7_OPERATOR_TRUTH.artifactRegistry.map((group) => `
              <div class="artifact-group">
                <strong>${escapeHtml(group.group)}</strong>
                ${group.items.map((item) => `<code>${escapeHtml(item)}</code>`).join('')}
              </div>
            `).join('')}
          </div>
        </article>

        <article class="panel">
          <div class="panel__eyebrow">Операторский порядок</div>
          <div class="workflow-list">
            ${AGENT7_OPERATOR_TRUTH.operatorWorkflow.map((item, index) => `
              <div class="workflow-item">
                <span>${index + 1}</span>
                <p>${escapeHtml(item)}</p>
              </div>
            `).join('')}
          </div>
        </article>
      </div>
    `;
  }
}
