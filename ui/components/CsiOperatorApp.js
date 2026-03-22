import { TabManager } from './TabManager.js?v=20260321-track-b-shadow-ui-02';
import { AGENT7_OPERATOR_TRUTH } from '../data/agent7-truth.js?v=20260321-track-b-shadow-ui-02';
import { getOperatorCopy, localizeOperatorToken } from '../data/operator-copy.js?v=20260321-track-b-shadow-ui-02';
import { GUIDED_CAPTURE_PACKS, getGuidedCapturePack, getGuidedCapturePackSummary } from '../data/guided-capture-packs.js?v=20260321-track-b-shadow-ui-02';
import {
  MANUAL_CAPTURE_PRESETS,
  getManualCapturePreset,
  getManualCapturePresetVariant
} from '../data/manual-capture-presets.js?v=20260321-track-b-shadow-ui-02';
import { CsiOperatorService } from '../services/csi-operator.service.js?v=20260321-track-b-shadow-ui-02';

const UI_LOCALE = getOperatorCopy(typeof document !== 'undefined' ? document.documentElement?.lang : 'ru');

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

const FATE_GROUP_HOTKEYS = {
  '1': 'all',
  '2': 'canonical',
  '3': 'failure',
  '4': 'incomplete',
  '5': 'timing_bias'
};
const FORENSIC_SEARCH_PREFETCH_DELAY_MS = 180;
const DEFAULT_GARAGE_LAYOUT = {
  widthMeters: 4.3,
  heightMeters: 7.5,
  zones: {
    doorMaxY: 1.5,
    deepMinY: 5.0
  }
};
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
  TRACK_B: 'track_b'
};

function readUiRuntimeViewSelection() {
  try {
    const raw = window.localStorage?.getItem(UI_RUNTIME_VIEW_STORAGE_KEY);
    return raw === UI_RUNTIME_VIEW_OPTIONS.TRACK_B
      ? UI_RUNTIME_VIEW_OPTIONS.TRACK_B
      : UI_RUNTIME_VIEW_OPTIONS.TRACK_A;
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

function buildRuntimeView(primaryRuntime, trackBShadow, selectedView) {
  if (selectedView === UI_RUNTIME_VIEW_OPTIONS.TRACK_B) {
    const headline = trackBShadow?.predictedClass || trackBShadow?.status || 'unknown';
    return {
      id: UI_RUNTIME_VIEW_OPTIONS.TRACK_B,
      label: 'Track B v1 candidate',
      routeLabel: 'shadow-only',
      state: headline,
      confidence: getTrackBShadowConfidence(trackBShadow),
      modelVersion: 'track_b_v1',
      modelId: 'tcn_v2_track_b_v1_torchscript.pt',
      running: Boolean(trackBShadow?.loaded),
      modelLoaded: Boolean(trackBShadow?.loaded),
      nodesActive: Number(trackBShadow?.nodesWithData) || 0,
      packetsInWindow: primaryRuntime?.packetsInWindow,
      packetsPerSecond: primaryRuntime?.packetsPerSecond,
      windowAgeSec: primaryRuntime?.windowAgeSec,
      targetZone: trackBShadow?.predictedClass || 'unknown',
      targetX: null,
      targetY: null,
      inferenceMs: trackBShadow?.inferenceMs,
      summary: 'UI показывает Track B как тестовый runtime-view; production routing остаётся на Track A.'
    };
  }

  return {
    id: UI_RUNTIME_VIEW_OPTIONS.TRACK_A,
    label: 'Track A production',
    routeLabel: 'production',
    state: primaryRuntime?.state || 'unknown',
    confidence: primaryRuntime?.confidence,
    modelVersion: primaryRuntime?.modelVersion,
    modelId: primaryRuntime?.modelId,
    running: Boolean(primaryRuntime?.running),
    modelLoaded: Boolean(primaryRuntime?.modelLoaded),
    nodesActive: primaryRuntime?.nodesActive,
    packetsInWindow: primaryRuntime?.packetsInWindow,
    packetsPerSecond: primaryRuntime?.packetsPerSecond,
    windowAgeSec: primaryRuntime?.windowAgeSec,
    targetZone: primaryRuntime?.targetZone,
    targetX: primaryRuntime?.targetX,
    targetY: primaryRuntime?.targetY,
    inferenceMs: null,
    summary: 'UI показывает текущий production runtime Track A.'
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
  return `Motion-runtime видит ${activeNodes}/4 источника, но по пакетам доступен только сводный уровень.`;
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
    return 'support-path не прислал статус';
  }
  if ((support.status === 'unknown' || !support.status) && isSupportPathMissing(support)) {
    return 'без live-данных';
  }
  return displayToken(support.status || 'unknown');
}

function getSupportHeadline(support) {
  if (!support) {
    return 'support-path не прислал данные';
  }
  if (isSupportPathMissing(support)) {
    return 'support-path не получен';
  }
  return displayMaybeToken(support.candidateName);
}

function getSupportReasonText(support) {
  if (!support) {
    return 'support-path не прислал причину';
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
      return 'Mac Camera';
    case TEACHER_SOURCE_KIND.NONE:
      return 'none (legacy/degraded)';
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
      return 'Legacy/degraded path без teacher video.';
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
      ? 'Выбран legacy/degraded source none. Канонический freeform не стартует с teacher_source_kind=none.'
      : videoChecked
        ? (videoAvailable
            ? `Preflight подтвердил ${teacherResolvedLabel} как явный teacher source.`
            : (videoError || `Preflight не подтвердил ${teacherResolvedLabel}.`))
        : `Teacher source выбран явно (${teacherSelectionLabel}), но ещё не проверен preflight.`
  };

  let truth = {
    label: 'ожидает preflight',
    tone: 'warn',
    summary: 'Truth-layer ещё не подтверждён: сначала нужен video-backed preflight.'
  };

  const activeVideoBackedSession = Boolean(status.recording && status.with_video);
  const activeTruthTrackedSession = freeformActive || activeVideoBackedSession;

  if ((manualActive && !status.with_video) || legacyFreeformActive) {
    truth = {
      label: 'legacy without teacher',
      tone: 'risk',
      summary: legacyFreeformActive
        ? 'Идёт legacy freeform без video-backed teacher source. Это не каноническая teacher-запись.'
        : 'Идёт legacy-сессия без video-backed teacher source. Это не каноническая teacher-запись.'
    };
  } else if (activeTruthTrackedSession) {
    if (videoChecked && !videoAvailable) {
      truth = {
        label: 'truth lost',
        tone: 'risk',
        summary: videoError || 'Сессия требует видео, но teacher source недоступен.'
      };
    } else if (trust.label === 'offline' || liveSourceCount < 3) {
      truth = {
        label: 'truth lost',
        tone: 'risk',
        summary: trust.label === 'offline'
          ? 'Live runtime ушёл в offline во время teacher-сессии.'
          : `Live coverage просела до ${liveSourceCount}/4 активных источников.`
      };
    } else if (trust.label === 'degraded' || trust.tone === 'warn' || truthInvalidationReason) {
      truth = {
        label: 'degraded',
        tone: 'warn',
        summary: truthInvalidationReason
          ? `Truth coverage деградировал: ${displayToken(truthInvalidationReason)}.`
          : `Live trust сейчас ${displayToken(trust.label || 'degraded')}; teacher truth нужно считать degraded.`
      };
    } else {
      truth = {
        label: 'video-backed',
        tone: 'ok',
        summary: `Teacher-session остаётся video-backed; live trust ${displayToken(trust.label || 'ready')} и ${Math.max(liveSourceCount, readyNodes)}/4 источников активны.`
      };
    }
  } else if (preflight.ok && videoAvailable) {
    truth = {
      label: 'ready',
      tone: 'ok',
      summary: 'Preflight подтвердил video-backed source; можно стартовать каноническую запись.'
    };
  }

  const blockReasons = [];
  if (guidedActive) {
    blockReasons.push('Сейчас активен legacy guided-пакет. Останови его, прежде чем запускать канонический freeform.');
  }
  if (legacyFreeformActive) {
    blockReasons.push('Сейчас идёт legacy freeform без teacher video. Канонический freeform заблокирован, пока эта сессия не завершится.');
  }
  if (manualActive && !legacyFreeformActive) {
    blockReasons.push(status.with_video
      ? 'Сейчас активна ручная запись. Канонический freeform ждёт освобождения backend.'
      : 'Сейчас активна legacy ручная запись без teacher video. Канонический freeform заблокирован.');
  }
  if (!Number.isFinite(Number(freeform.personCount)) || Number(freeform.personCount) < 1) {
    blockReasons.push('Сначала выбери количество людей для freeform-сессии.');
  }
  if (selectedTeacherKind === TEACHER_SOURCE_KIND.NONE) {
    blockReasons.push('Выбран legacy/degraded source none. Для канонического freeform нужен Pixel RTSP или Mac Camera.');
  }
  if (!videoChecked) {
    blockReasons.push('Сначала запусти preflight, чтобы явно проверить teacher source и узлы.');
  }
  if (videoChecked && !videoAvailable) {
    blockReasons.push(videoError || 'Teacher video source недоступен, поэтому start заблокирован.');
  }
  if (videoChecked && !preflight.ok) {
    blockReasons.push(recording.preflightError || preflight.error || 'Preflight не подтвердил operational readiness.');
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
  const sessionId = snapshot?.pose?.runtime_session_id || snapshot?.pose?.metadata?.runtime_session_id;
  return sessionId || 'backend не прислал идентификатор сессии';
}

function getRuntimeStartText(snapshot) {
  const startedTs = snapshot?.pose?.runtime_started_ts || snapshot?.pose?.metadata?.runtime_started_ts;
  return startedTs ? formatTimestamp(startedTs) : 'backend не прислал время старта';
}

function getSupportTopologyText(signature) {
  if (!signature || signature === 'unknown' || signature === 'unavailable') {
    return 'не передана';
  }
  return displayMaybeToken(signature);
}

function getRequiredTopologyText(support) {
  if (isSupportPathMissing(support)) {
    return 'support-path не прислал';
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
  return isSupportPathMissing(support) ? 'support-path не рассчитан' : 'вероятность не передана';
}

function getSupportThresholdText(support) {
  if (support?.threshold != null && !Number.isNaN(Number(support.threshold))) {
    return formatNumber(support.threshold, 3);
  }
  return isSupportPathMissing(support) ? 'support-path не рассчитан' : 'threshold не передан';
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
  return isSupportPathMissing(support) ? 'support-path не активен' : 'время не передано';
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
    return 'диагностическая координата (ambiguity safe-mode)';
  }
  if (coordinate?.activeForMap && coordinate?.operatorXMeters != null && coordinate?.operatorYMeters != null) {
    return 'operator-safe confirmed motion gate';
  }
  if (coordinate?.activeForMap === false && (coordinate?.xCm != null || coordinate?.yCm != null)) {
    return 'диагностическая координата (вне active motion)';
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
    this.sections = {};
    this.forensicQuery = '';
    this.forensicViewMode = 'time';
    this.forensicFateFilter = 'all';
    this.forensicSearchPrefetchTimer = null;
    this.pendingForensicScrollRunId = null;
    this.lastRenderedForensicRunId = null;
    this.signalCoordinateState = null;
    this.runtimeViewSelection = readUiRuntimeViewSelection();
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
    this.unsubscribe = this.service.subscribe((snapshot) => {
      this.snapshot = snapshot;
      this.renderSnapshot();
    });
    await this.service.start();
  }

  dispose() {
    this.root.removeEventListener('click', this.handleRootClick);
    this.root.removeEventListener('input', this.handleRootInput);
    this.root.removeEventListener('change', this.handleRootChange);
    document.removeEventListener('keydown', this.handleGlobalKeydown);
    this.clearForensicSearchPrefetch();
    this.unsubscribe?.();
    this.service.stop();
  }

  selectUiRuntimeView(nextView) {
    const resolved = nextView === UI_RUNTIME_VIEW_OPTIONS.TRACK_B
      ? UI_RUNTIME_VIEW_OPTIONS.TRACK_B
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
      return null;
    }

    const previous = this.signalCoordinateState;
    if (!previous) {
      this.signalCoordinateState = { ...target };
      return target;
    }

    const distance = Math.hypot(target.xMeters - previous.xMeters, target.yMeters - previous.yMeters);
    const alpha = distance > 1.8 ? 0.76 : distance > 0.85 ? 0.54 : 0.34;
    const smoothed = {
      xMeters: previous.xMeters + (target.xMeters - previous.xMeters) * alpha,
      yMeters: previous.yMeters + (target.yMeters - previous.yMeters) * alpha
    };

    this.signalCoordinateState = smoothed;
    return smoothed;
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
      void this.service.refreshForensicRuns(true);
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
      model: this.root.querySelector('#model'),
      forensics: this.root.querySelector('#forensics'),
      runtime: this.root.querySelector('#runtime')
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
    this.renderModel();
    this.renderForensics();
    if (!this.isRuntimeRecorderEditing()) {
      this.renderRuntime();
    }
  }

  renderOverview() {
    const snapshot = this.snapshot;
    const trust = snapshot?.live?.trust || { tone: 'neutral', label: 'booting', summary: 'Идёт загрузка live-runtime…' };
    const topology = snapshot?.live?.topology || {};
    const primaryRuntime = snapshot?.live?.primaryRuntime || {};
    const trackBShadow = snapshot?.live?.trackBShadow || {};
    const runtimeView = buildRuntimeView(primaryRuntime, trackBShadow, this.runtimeViewSelection);
    const topologyLabel = getTopologyHeadline(topology, primaryRuntime);
    const sessionId = getRuntimeSessionText(snapshot);

    this.sections.overview.innerHTML = `
      <div class="summary-stack">
        <div class="summary-card ${toneClass(trust.tone)}">
          <div class="summary-card__label">Доверие</div>
          <div class="summary-card__value">${escapeHtml(displayToken(trust.label))}</div>
          <div class="summary-card__meta">${escapeHtml(trust.summary)}</div>
        </div>
        <div class="summary-card tone-info">
          <div class="summary-card__label">UI runtime-view</div>
          <div class="summary-card__value">${escapeHtml(String(displayMaybeToken(runtimeView.state || 'unknown')).toUpperCase())}</div>
          <div class="summary-card__meta">${escapeHtml(runtimeView.label)} / ${escapeHtml(runtimeView.routeLabel)} / уверенность ${escapeHtml(formatPercent(runtimeView.confidence, 0))}</div>
        </div>
        <div class="summary-card tone-neutral">
          <div class="summary-card__label">Runtime-сессия</div>
          <div class="summary-card__value">${escapeHtml(sessionId)}</div>
          <div class="summary-card__meta">Старт ${escapeHtml(getRuntimeStartText(snapshot))} / топология ${escapeHtml(topologyLabel)}</div>
        </div>
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
    const secondaryRuntime = snapshot.live.secondaryRuntime || {};
    const trackBShadow = snapshot.live.trackBShadow || {};
    const runtimeView = buildRuntimeView(primaryRuntime, trackBShadow, this.runtimeViewSelection);
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

    this.sections.live.innerHTML = `
      <section class="hero-panel">
        <div class="hero-panel__copy">
          <div class="eyebrow">Live-консоль</div>
          <h2>${escapeHtml(String(displayMaybeToken(runtimeView.state || 'unknown')).toUpperCase())}</h2>
          <p>
            ${escapeHtml(runtimeView.label)} сейчас <strong>${escapeHtml(displayMaybeToken(runtimeView.state || 'unknown'))}</strong>
            с уверенностью <strong>${escapeHtml(formatPercent(runtimeView.confidence, 0))}</strong>,
            support-path сейчас <strong>${escapeHtml(getSupportStatusText(support))}</strong>,
            а текущий кадр читается как <strong>${escapeHtml(displayToken(trust.label))}</strong>.
          </p>
          <div class="hero-tags">
            <span class="tag ${toneClass(trust.tone)}">${escapeHtml(trust.summary)}</span>
            <span class="tag tone-info">${escapeHtml(runtimeView.routeLabel)} / уверенность ${escapeHtml(formatPercent(runtimeView.confidence, 0))}</span>
            <span class="tag tone-info">support-path ${escapeHtml(getSupportStatusText({ ...support, status: support.candidateStatus || support.status }))}</span>
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
            <small>${escapeHtml(formatNumber(runtimeView.nodesActive))}/4 узлов / ${escapeHtml(formatNumber(runtimeView.packetsPerSecond, 1))} pps</small>
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
          <div class="panel__eyebrow">Выбранный runtime-view</div>
          <div class="panel__headline">${escapeHtml(displayMaybeToken(runtimeView.state || 'unknown'))}</div>
          <div class="kv-list">
            <div class="kv"><span>Источник</span><strong>${escapeHtml(runtimeView.label)} / ${escapeHtml(runtimeView.routeLabel)}</strong></div>
            <div class="kv"><span>Основная уверенность</span><strong>${escapeHtml(formatPercent(runtimeView.confidence, 0))}</strong></div>
            <div class="kv"><span>Статус runtime</span><strong>${escapeHtml(runtimeView.running ? UI_LOCALE.common.running : 'offline')} / ${escapeHtml(runtimeView.modelLoaded ? 'модель загружена' : 'модель не загружена')}</strong></div>
            <div class="kv"><span>Узлы / packets</span><strong>${escapeHtml(formatNumber(runtimeView.nodesActive))}/4 / ${escapeHtml(formatNumber(runtimeView.packetsInWindow))}</strong></div>
            <div class="kv"><span>PPS / возраст окна</span><strong>${escapeHtml(formatNumber(runtimeView.packetsPerSecond, 1))} / ${escapeHtml(formatRelativeTime(runtimeView.windowAgeSec))}</strong></div>
            <div class="kv"><span>Класс / координата</span><strong>${escapeHtml(displayMaybeToken(runtimeView.targetZone || runtimeView.state || 'unknown'))} / ${escapeHtml(formatNumber(runtimeView.targetX, 1))}, ${escapeHtml(formatNumber(runtimeView.targetY, 1))}</strong></div>
            ${runtimeView.inferenceMs != null ? `<div class="kv"><span>Inference</span><strong>${escapeHtml(formatNumberWithUnit(runtimeView.inferenceMs, { digits: 2, unit: ' ms' }))}</strong></div>` : ''}
          </div>
          <div class="panel__footer">${escapeHtml(runtimeView.summary)}</div>
        </article>

        <article class="panel">
          <div class="panel__eyebrow">Track B shadow</div>
          <div class="panel__headline">${escapeHtml(displayMaybeToken(trackBStatusToken))}</div>
          <div class="kv-list">
            <div class="kv"><span>Роль</span><strong>${escapeHtml(displayToken(trackBShadow.track || 'B_v1'))}</strong></div>
            <div class="kv"><span>Статус</span><strong>${escapeHtml(displayMaybeToken(trackBShadow.status || 'unknown'))} / ${escapeHtml(trackBShadow.loaded ? 'модель загружена' : 'модель не загружена')}</strong></div>
            <div class="kv"><span>Узлы / окно</span><strong>${escapeHtml(formatNumber(trackBShadow.nodesWithData))}/4 / ${escapeHtml(formatRelativeTime(primaryRuntime.windowAgeSec))}</strong></div>
            <div class="kv"><span>Inference</span><strong>${escapeHtml(formatNumberWithUnit(trackBShadow.inferenceMs, { digits: 2, unit: ' ms', missing: 'ещё нет окна' }))}</strong></div>
            <div class="kv"><span>Production routing</span><strong>shadow-only / Track A остаётся боевым</strong></div>
          </div>
          <div class="metric-bars">
            ${trackBProbabilities.length
              ? trackBProbabilities.map(([label, value]) => renderMetricBar(label, Number(value) || 0)).join('')
              : '<div class="muted">Track B ещё не прислал вероятности.</div>'}
          </div>
          <div class="panel__footer">Этот блок нужен только для тестов: Track B считает параллельно и не подменяет production verdict.</div>
        </article>

        <article class="panel">
          <div class="panel__eyebrow">Текущий support-path</div>
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

  renderSignal() {
    const snapshot = this.snapshot;
    const topology = snapshot.live.topology;
    const motion = snapshot.live.motion;
    const live = snapshot.live;
    const primaryRuntime = snapshot.live.primaryRuntime || {};
    const secondaryRuntime = snapshot.live.secondaryRuntime || {};
    const fingerprint = snapshot.live.fingerprint;
    const coordinate = snapshot.live.coordinate;
    const operatorPresence = snapshot.live.operatorPresence || {};
    const ambiguity = snapshot.live.ambiguity || {};
    const activeCoordinate = coordinate?.activeForMap ? {
      ...coordinate,
      xMeters: coordinate.operatorXMeters ?? coordinate.xMeters,
      yMeters: coordinate.operatorYMeters ?? coordinate.yMeters,
      targetZone: coordinate.operatorTargetZone || coordinate.targetZone
    } : null;
    const garage = getGarageLayout(live);
    const smoothedCoordinate = this.getSmoothedSignalCoordinate(activeCoordinate, garage);
    const currentPoint = mapGarageCoordinateToPercent(smoothedCoordinate, garage);
    const garagePath = ambiguity.active
      ? null
      : buildGarageTrackPolyline(buildGarageTrackPoints(coordinate.motionHistory, smoothedCoordinate, garage));
    const garageDoor = mapGarageCoordinateToPercent(garage?.door, garage);
    const garageZones = getGarageZoneBands(garage);
    const ambiguityZone = garageZones.find((zone) => zone.id === ambiguity.targetZone) || null;
    const garageNodes = Array.isArray(garage?.nodes) ? garage.nodes : [];
    const aggregateNodeNote = getAggregateNodeNote(topology.nodes || [], primaryRuntime);
    const liveTotalPackets = topology.liveTotalPackets ?? primaryRuntime.packetsInWindow;
    const lastPacketAgeSec = topology.lastPacketAgeSec ?? primaryRuntime.windowAgeSec;
    const liveWindowSeconds = topology.liveWindowSeconds ?? primaryRuntime.windowAgeSec;
    const motionWindowSeconds = topology.motionWindowSeconds ?? primaryRuntime.windowAgeSec;
    const vitalsWindowSeconds = snapshot.pose?.metadata?.vitals_window_seconds ?? topology.vitalsWindowSeconds ?? primaryRuntime.windowAgeSec;
    const mapModeLabel = ambiguity.active
      ? 'ambiguity safe-mode'
      : activeCoordinate
        ? 'single-target safe'
        : 'suppressed';
    const signalMapZoneLabel = ambiguity.active
      ? ambiguity.targetZone || coordinate?.ambiguityTargetZone || 'unknown'
      : activeCoordinate?.targetZone || 'no_active_motion';
    const smoothingLabel = ambiguity.active
      ? 'отключено в ambiguity safe-mode'
      : activeCoordinate
        ? 'по motion-history и runtime-геометрии'
        : 'отключено без active motion';

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
            <div class="kv"><span>Координата</span><strong>${escapeHtml(formatNumber(coordinate.xCm, 1))} / ${escapeHtml(formatNumber(coordinate.yCm, 1))} см</strong></div>
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
              <div class="garage-map__centerline garage-map__centerline--x"></div>
              <div class="garage-map__centerline garage-map__centerline--y"></div>
              <svg class="garage-map__overlay" viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true">
                ${garagePath ? `<polyline class="garage-map__trail" points="${garagePath}"></polyline>` : ''}
              </svg>
              ${ambiguity.active && ambiguityZone ? `
                <div class="garage-map__ambiguity-zone garage-map__ambiguity-zone--${ambiguityZone.id}" style="top:${ambiguityZone.top}%;height:${ambiguityZone.height}%"></div>
              ` : ''}
              ${garageDoor ? `
                <div class="garage-map__door" style="left:${garageDoor.left}%;top:${garageDoor.top}%">
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
              ${ambiguity.active ? `
                <div class="garage-map__ambiguity-card">
                  <strong>${escapeHtml(ambiguity.headline || 'несколько людей / позиция неоднозначна')}</strong>
                  <span>${escapeHtml(ambiguity.detail || 'single-target marker скрыт, raw координата остаётся только диагностикой')}</span>
                </div>
              ` : currentPoint ? `
                <div class="garage-map__object" style="left:${currentPoint.left}%;top:${currentPoint.top}%">
                  <span class="garage-map__object-core"></span>
                </div>
              ` : '<div class="garage-map__empty">Motion-runtime сейчас не видит свежего движения. Диагностическая static-координата не показывается как live-объект.</div>'}
            </div>
            <div class="garage-map__summary">
              <div class="garage-map__metric">
                <span>Текущая зона</span>
                <strong>${escapeHtml(displayToken(signalMapZoneLabel))}</strong>
              </div>
              <div class="garage-map__metric">
                <span>Координата</span>
                <strong>${escapeHtml(formatNumber(coordinate.xCm, 1))} / ${escapeHtml(formatNumber(coordinate.yCm, 1))} см</strong>
              </div>
              <div class="garage-map__metric">
                <span>Источник</span>
                <strong>${escapeHtml(getCoordinateSourceText(coordinate))}</strong>
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
          <div class="panel__eyebrow">Теневая диагностика</div>
          <div class="diagnostic-grid">
            ${snapshot.live.shadowDiagnostics.map((item) => `
              <div class="diagnostic-card ${toneClass(statusTone(item.status))}">
                <span>${escapeHtml(displayToken(item.label))}</span>
                <strong>${escapeHtml(displayToken(item.prediction))}</strong>
                <small>${escapeHtml(displayToken(item.status))} / ${escapeHtml(displayToken(item.detail))}</small>
              </div>
            `).join('')}
          </div>
        </article>
      </div>

      <article class="panel">
        <div class="panel__eyebrow">Сигнал по каждому узлу</div>
        <div class="node-table">
          ${topology.nodes.map((node) => `
              <div class="node-table__row">
                <div class="node-table__cell node-table__cell--name">${escapeHtml(node.nodeId)}</div>
                <div class="node-table__cell">${escapeHtml(node.active == null ? UI_LOCALE.common.unknown : node.active ? UI_LOCALE.common.live : UI_LOCALE.common.idle)}</div>
                <div class="node-table__cell">${escapeHtml(getNodeSignalScopeText(node))}</div>
                <div class="node-table__cell">${escapeHtml(getNodePacketText(node))}</div>
                <div class="node-table__cell">${escapeHtml(getNodeShareText(node))}</div>
              </div>
            `).join('')}
        </div>
        ${aggregateNodeNote ? `<div class="panel__footer">${escapeHtml(aggregateNodeNote)}</div>` : ''}
      </article>
    `;
  }

  renderModel() {
    const truth = AGENT7_OPERATOR_TRUTH;
    const primaryRuntime = this.snapshot?.live?.primaryRuntime || {};
    const trackBShadow = this.snapshot?.live?.trackBShadow || {};
    const runtimeModels = this.snapshot?.runtimeModels || {};
    const models = Array.isArray(runtimeModels.items) ? runtimeModels.items : [];
    const trackAConnected = Boolean(primaryRuntime.running && primaryRuntime.modelLoaded);
    const selectedRuntimeView = this.runtimeViewSelection === UI_RUNTIME_VIEW_OPTIONS.TRACK_B
      ? UI_RUNTIME_VIEW_OPTIONS.TRACK_B
      : UI_RUNTIME_VIEW_OPTIONS.TRACK_A;
    const trackBHeadline = trackBShadow.predictedClass
      ? String(trackBShadow.predictedClass).toLowerCase()
      : (trackBShadow.status || 'unknown');
    const catalogSummary = runtimeModels.loading
      ? UI_LOCALE.models.loading
      : (runtimeModels.actionError || runtimeModels.error)
        ? `${UI_LOCALE.models.actionErrorPrefix} ${runtimeModels.actionError || runtimeModels.error}`
        : UI_LOCALE.models.catalogSummary;

    this.sections.model.innerHTML = `
      <div class="surface-grid surface-grid--four">
        <article class="panel">
          <div class="panel__eyebrow">Primary runtime-контракт</div>
          <div class="panel__headline">motion-only runtime</div>
          <div class="kv-list">
            <div class="kv"><span>Primary state</span><strong>MOTION_DETECTED / NO_MOTION</strong></div>
            <div class="kv"><span>Поле confidence</span><strong>motion_confidence</strong></div>
            <div class="kv"><span>Текущая модель</span><strong>${escapeHtml(primaryRuntime.modelVersion || UI_LOCALE.common.unknown)}</strong></div>
            <div class="kv"><span>Активный bundle</span><strong>${escapeHtml(runtimeModels.activeModelId || primaryRuntime.modelId || 'bundle не выбран')}</strong></div>
            <div class="kv"><span>Secondary fields</span><strong>binary / coarse</strong></div>
            <div class="kv"><span>Track A runtime</span><strong>${trackAConnected ? 'подключён / production' : 'offline'}</strong></div>
          </div>
          <div class="panel__footer">Track A остаётся текущим production runtime и именно он сейчас выдаёт боевой motion verdict.</div>
        </article>

        <article class="panel">
          <div class="panel__eyebrow">Track B v1 candidate</div>
          <div class="panel__headline">${escapeHtml(displayMaybeToken(trackBHeadline))}</div>
          <div class="kv-list">
            <div class="kv"><span>Статус</span><strong>${escapeHtml(displayMaybeToken(trackBShadow.status || 'unknown'))} / ${escapeHtml(trackBShadow.loaded ? 'модель загружена' : 'модель не загружена')}</strong></div>
            <div class="kv"><span>Режим</span><strong>shadow-only</strong></div>
            <div class="kv"><span>Архитектура</span><strong>raw CSI TCN</strong></div>
            <div class="kv"><span>Последний класс</span><strong>${escapeHtml(displayMaybeToken(trackBHeadline))}</strong></div>
            <div class="kv"><span>Inference</span><strong>${escapeHtml(formatNumberWithUnit(trackBShadow.inferenceMs, { digits: 2, unit: ' ms', missing: 'ещё нет окна' }))}</strong></div>
          </div>
          <div class="panel__footer">Этот кандидат уже подключён в runtime для тестов, но не участвует в production routing и не появляется в selector каталога Track A-моделей.</div>
        </article>

        <article class="panel">
          <div class="panel__eyebrow">Текущий support-path</div>
          <div class="panel__headline">${escapeHtml(displayToken(truth.currentBest.runtimePath.mode))}</div>
          <div class="kv-list">
            <div class="kv"><span>Кандидат</span><strong>${escapeHtml(truth.currentBest.runtimePath.candidateName)}</strong></div>
            <div class="kv"><span>Топология</span><strong>${escapeHtml(truth.currentBest.runtimePath.topologySignature)}</strong></div>
            <div class="kv"><span>Threshold</span><strong>${escapeHtml(formatNumber(truth.currentBest.runtimePath.threshold, 3))}</strong></div>
            <div class="kv"><span>Support-only</span><strong>${truth.currentBest.runtimePath.supportOnly ? UI_LOCALE.common.yes : UI_LOCALE.common.no}</strong></div>
            <div class="kv"><span>Authoritative</span><strong>${truth.currentBest.runtimePath.authoritative ? UI_LOCALE.common.yes : UI_LOCALE.common.no}</strong></div>
          </div>
          <div class="token-row">${formatList(truth.currentBest.runtimePath.scope)}</div>
        </article>

        <article class="panel">
          <div class="panel__eyebrow">Замороженный offline-baseline</div>
          <div class="panel__headline">${escapeHtml(truth.currentBest.frozenBaseline.baselineName)}</div>
          <div class="kv-list">
            <div class="kv"><span>Threshold</span><strong>${escapeHtml(formatNumber(truth.currentBest.frozenBaseline.threshold, 3))}</strong></div>
            <div class="kv"><span>Runtime switch</span><strong>${truth.currentBest.frozenBaseline.runtimeSwitchForbidden ? 'запрещён' : 'разрешён'}</strong></div>
            <div class="kv"><span>quiet_static_center</span><strong>${escapeHtml(truth.currentBest.runtimePath.quietStaticCenterStatus)}</strong></div>
            <div class="kv"><span>quiet_static_door</span><strong>${escapeHtml(truth.currentBest.runtimePath.quietStaticDoorStatus)}</strong></div>
          </div>
          <div class="token-row">${formatList(truth.currentBest.frozenBaseline.trainingCoreCategories)}</div>
        </article>
      </div>

      <article class="panel">
        <div class="panel__header panel__header--split">
          <div>
            <div class="panel__eyebrow">UI test-selector</div>
            <div class="panel__headline">Какой runtime-view показывать на первом экране</div>
          </div>
        </div>
        <div class="capture-pack__actions">
          <button
            type="button"
            class="capture-pack__button ${selectedRuntimeView === UI_RUNTIME_VIEW_OPTIONS.TRACK_A ? 'capture-pack__button--primary' : 'capture-pack__button--ghost'}"
            data-action="select-ui-runtime-view"
            data-runtime-view="${UI_RUNTIME_VIEW_OPTIONS.TRACK_A}"
          >
            Track A / production
          </button>
          <button
            type="button"
            class="capture-pack__button ${selectedRuntimeView === UI_RUNTIME_VIEW_OPTIONS.TRACK_B ? 'capture-pack__button--primary' : 'capture-pack__button--ghost'}"
            data-action="select-ui-runtime-view"
            data-runtime-view="${UI_RUNTIME_VIEW_OPTIONS.TRACK_B}"
          >
            Track B / test
          </button>
        </div>
        <div class="panel__footer">
          Сейчас выбран <strong>${escapeHtml(selectedRuntimeView === UI_RUNTIME_VIEW_OPTIONS.TRACK_B ? 'Track B v1 candidate' : 'Track A production')}</strong>.
          Это меняет только UI runtime-view для теста; backend production routing остаётся на Track A v5.
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
        <div class="panel__footer">${escapeHtml(catalogSummary)} Track B v1 сюда не входит: этот selector управляет только Track A-compatible runtime bundles.</div>
        ${models.length ? `
          <div class="runtime-model-grid">
            ${models.map((item) => {
              const badges = [
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
                <div class="runtime-model-card ${item.isActive ? 'is-active' : ''}">
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
              Live support-path остаётся <strong>support-only</strong>; narrative выше собирается на сервере из watcher/raw/bundle evidence и не подменяет primary motion verdict.
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
              <div class="kv"><span>Pending direction</span><strong>${escapeHtml(displayToken(ordered.first_direction_assignment?.shadow_pending_direction || 'ожидаемое направление не рассчитано'))}</strong></div>
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
              <div class="kv"><span>Watcher preflight OK</span><strong>${escapeHtml(formatBoolean(watcher.preflight_ok))}</strong></div>
              <div class="kv"><span>Operational ready</span><strong>${escapeHtml(formatBoolean(watcher.preflight?.operational_ready))}</strong></div>
              <div class="kv"><span>Threshold</span><strong>${escapeHtml(formatNumber(watcher.preflight?.threshold, 3))}</strong></div>
              <div class="kv"><span>Runtime scope</span><strong>${escapeHtml((watcher.preflight?.runtime_scope || []).map((item) => displayToken(item)).join(', ') || 'scope не передан') }</strong></div>
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
                { key: 'shadow_status', label: 'Shadow-статус' },
                { key: 'shadow_context_validity', label: 'Контекст' },
                { key: 'shadow_pending_direction', label: 'Pending direction' },
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
              { key: 'watcher_shadow_status', label: 'Shadow-статус' },
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
            ${renderStatusPill('legacy', 'warn')}
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
        : `Preflight ${preflight.ok ? UI_LOCALE.common.ready : UI_LOCALE.common.unavailable}`;

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
                      ? 'Guided run остановлен оператором. Можно перезапустить pack с этого же экрана.'
                      : status === 'preflight_failed'
                        ? `Preflight не прошёл: ${escapeHtml(guided.lastError || recording.preflightError || UI_LOCALE.common.unavailable)}`
                      : status === 'error'
                          ? `Guided run завершился ошибкой: ${escapeHtml(guided.lastError || recording.actionError || UI_LOCALE.common.unavailable)}`
                          : manualActive
                            ? `Пакет сейчас не запущен. Backend занят ручной записью ${escapeHtml(getRecordingLabelText(recordingStatus))}.`
                            : freeformActive
                              ? `Пакет сейчас не запущен. Backend занят freeform-записью ${escapeHtml(getRecordingLabelText(recordingStatus))}.`
                          : 'Выбери pack, сделай preflight и запускай клипы прямо из UI.'}
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
              <small>${escapeHtml(nextStep?.instruction || 'Следующий шаг появится после старта pack.')}</small>
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
      : 'manual.withVideo=false -> teacher_source_kind=none';

    return `
      <div class="manual-recorder">
        <div class="panel__eyebrow">${escapeHtml(UI_LOCALE.capture.manualEyebrow)}</div>
        <div class="panel__headline">${escapeHtml(UI_LOCALE.capture.manualHeadline)}</div>
        <div class="panel__text">${escapeHtml(UI_LOCALE.capture.manualSummary)}</div>
        <div class="recording-archive__notice">Legacy compatibility path: используй только если канонический freeform невозможен и это осознанное исключение.</div>
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
          ${renderStatusPill('legacy branch', 'warn')}
          ${manual.withVideo ? renderStatusPill('video-backed override', 'info') : renderStatusPill('no teacher video', 'risk')}
          ${manual.skipPreflight ? renderStatusPill('preflight bypass', 'risk') : renderStatusPill('preflight enforced', 'ok')}
          ${manualActive ? renderStatusPill(UI_LOCALE.capture.manualActive, 'risk') : ''}
          ${guidedActive ? renderStatusPill('guided-пакет активен', 'warn') : ''}
          ${freeformActive ? renderStatusPill('freeform-режим активен', 'warn') : ''}
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
        ? 'Канонический flow ждёт завершения legacy freeform без видео'
      : guidedActive
        ? 'Канонический flow ждёт завершения legacy guided-пакета'
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
      ? 'Strongest canonical path: Pixel RTSP via atomic-style teacher contract.'
      : selectedTeacherKind === TEACHER_SOURCE_KIND.MAC_CAMERA
        ? 'Fallback path: явная Mac Camera contract-конфигурация вместо implicit Darwin default.'
        : 'Legacy/degraded path. Подходит только для archive/manual compatibility.';
    const teacherSourceFieldLabel = selectedTeacherKind === TEACHER_SOURCE_KIND.PIXEL_RTSP
      ? 'RTSP URL'
      : selectedTeacherKind === TEACHER_SOURCE_KIND.MAC_CAMERA
        ? 'Device selector'
        : 'Legacy note';
    const teacherSourceFieldValue = selectedTeacherKind === TEACHER_SOURCE_KIND.PIXEL_RTSP
      ? (teacherSource.pixelRtspUrl || DEFAULT_PIXEL_RTSP_URL)
      : selectedTeacherKind === TEACHER_SOURCE_KIND.MAC_CAMERA
        ? (teacherSource.macDevice || DEFAULT_MAC_CAMERA_DEVICE)
        : 'teacher_source_kind=none';
    const teacherStateText = canonical.teacher.stateLabel === 'available'
      ? 'teacher source доступен'
      : canonical.teacher.stateLabel === 'unavailable'
        ? 'teacher source unavailable'
        : canonical.teacher.stateLabel === 'legacy_selected'
          ? 'teacher source legacy/degraded'
        : 'teacher source не проверен';
    const truthStateText = canonical.truth.label === 'video-backed'
      ? 'truth full'
      : canonical.truth.label === 'truth lost'
        ? 'truth lost'
        : canonical.truth.label === 'degraded'
          ? 'truth degraded'
          : canonical.truth.label;
    const startDisabled = !freeformActive && !canonical.startReady;
    const blockReasons = recording.actionError
      ? [recording.actionError, ...canonical.blockReasons.filter((item) => item !== recording.actionError)]
      : canonical.blockReasons;

    return `
      <div class="manual-recorder freeform-recorder canonical-recorder">
        <div class="panel__eyebrow">Основной операторский путь</div>
        <div class="panel__headline">One-person freeform / video-backed default</div>
        <div class="panel__text">Текущий practical flow: garage router + all antennas. Teacher source должен быть явным, preflight честным, а voice prompts остаются частью процесса.</div>

        <div class="hero-tags">
          ${renderStatusPill('garage router + all antennas', 'info')}
          ${renderStatusPill('video-backed default', 'warn')}
          ${renderStatusPill(teacherStateText, canonical.teacher.tone)}
          ${renderStatusPill(truthStateText, canonical.truth.tone)}
          ${renderStatusPill(canonical.voiceEnabled ? 'voice cues on' : 'voice cues off', canonical.voiceEnabled ? 'ok' : 'neutral')}
          ${Number(personCountValue || 1) === 1 ? renderStatusPill('one-person default', 'ok') : renderStatusPill('multi-person override', 'warn')}
          ${freeformActive ? renderStatusPill('идёт primary operator session', 'risk') : ''}
          ${legacyFreeformActive ? renderStatusPill('legacy freeform без video', 'risk') : ''}
          ${guidedActive ? renderStatusPill('legacy guided активен', 'warn') : ''}
          ${manualActive && !legacyFreeformActive ? renderStatusPill('ручной режим активен', 'warn') : ''}
          ${recording.preflightLoading ? renderStatusPill(UI_LOCALE.capture.preflightRunning, 'info') : ''}
        </div>

        <div class="surface-grid surface-grid--two manual-recorder__status-grid canonical-recorder__status-grid">
          <article class="panel">
            <div class="panel__eyebrow">Teacher source</div>
            <div class="kv-list">
              <div class="kv"><span>Выбранный contract</span><strong>${escapeHtml(canonical.teacher.selectionLabel)}</strong></div>
              <div class="kv"><span>Runtime source</span><strong>${escapeHtml(canonical.teacher.selected ? canonical.teacher.label : 'не выбран')}</strong></div>
              <div class="kv"><span>Video contract</span><strong>${escapeHtml(canonical.teacher.required ? UI_LOCALE.common.required : UI_LOCALE.common.optional)}</strong></div>
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
              <div class="kv"><span>${escapeHtml(UI_LOCALE.capture.freeformNodesActive)}</span><strong>${escapeHtml(freeformActive ? `${activeNodes}/4` : `${canonical.readyNodes}/${canonical.totalNodes}`)}</strong></div>
            </div>
            <div class="panel__footer">${escapeHtml(recording.preflightError || preflight.error || (preflight.ok ? 'Preflight подтвердил узлы и video-backed teacher source.' : 'Без preflight start остаётся заблокирован.'))}</div>
          </article>

          <article class="panel">
            <div class="panel__eyebrow">Truth layer</div>
            <div class="kv-list">
              <div class="kv"><span>Статус</span><strong>${escapeHtml(truthStateText)}</strong></div>
              <div class="kv"><span>Live trust</span><strong>${escapeHtml(displayToken(this.snapshot?.live?.trust?.label || 'unknown'))}</strong></div>
              <div class="kv"><span>Support context</span><strong>${escapeHtml(displayToken(this.snapshot?.live?.supportPath?.contextValidity || 'unknown'))}</strong></div>
              <div class="kv"><span>Активные источники</span><strong>${escapeHtml(`${Math.max(Number(this.snapshot?.live?.topology?.sourceCount) || 0, freeformActive ? activeNodes : canonical.readyNodes)}/4`)}</strong></div>
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
            <div class="panel__footer">${escapeHtml(freeformActive ? 'Во время active session truth-layer отслеживается отдельно и больше не считается автоматически валидным.' : 'Канонический start открывается только после честного preflight и teacher source check.')}</div>
          </article>
        </div>

        <div class="manual-recorder__grid">
          <label class="manual-recorder__field">
            <span>Teacher source</span>
            <select
              class="manual-recorder__input"
              data-role="teacher-source-field"
              data-field="selectedKind"
              ${disableForm ? 'disabled' : ''}
            >
              <option value="${TEACHER_SOURCE_KIND.PIXEL_RTSP}" ${selectedTeacherKind === TEACHER_SOURCE_KIND.PIXEL_RTSP ? 'selected' : ''}>Pixel RTSP (strongest)</option>
              <option value="${TEACHER_SOURCE_KIND.MAC_CAMERA}" ${selectedTeacherKind === TEACHER_SOURCE_KIND.MAC_CAMERA ? 'selected' : ''}>Mac Camera (fallback)</option>
              ${showLegacyTeacherSource ? `<option value="${TEACHER_SOURCE_KIND.NONE}" ${selectedTeacherKind === TEACHER_SOURCE_KIND.NONE ? 'selected' : ''}>none (legacy/degraded)</option>` : ''}
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
            <span>Teacher contract</span>
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
          ${escapeHtml(`One-person default: ${getFreeformRoleHintText(1)}. Текущий выбор: ${roleHintText}`)}
        </div>
        ${!showLegacyTeacherSource ? `
          <div class="panel__footer manual-recorder__selection-note">
            <button type="button" class="capture-pack__button capture-pack__button--ghost" data-action="toggle-legacy-teacher-source" ${disableForm ? 'disabled' : ''}>Показать legacy source none</button>
          </div>
        ` : `
          <div class="panel__footer manual-recorder__selection-note">
            ${escapeHtml('Legacy source none показан только как advanced/archive option. Для канонического старта нужен video-backed teacher source.')}
          </div>
        `}
        <div class="panel__footer manual-recorder__selection-note">
          ${escapeHtml(`${UI_LOCALE.capture.freeformLabelAuto} Video-backed teacher source обязателен для канонического старта.`)}
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
            <strong>${escapeHtml(freeformActive ? 'Honest session state' : 'Почему start сейчас заблокирован')}</strong>
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

  renderRecordingArchive(recording) {
    const guidedOpen = this.runtimeRecordingUi.showLegacyGuided;
    const manualOpen = this.runtimeRecordingUi.showLegacyManual;

    return `
      <div class="recording-archive">
        <div class="panel__eyebrow">Legacy / archive</div>
        <div class="panel__headline">Старые recording branches убраны из primary path</div>
        <div class="panel__text">Motion-only guided packs и manual compatibility recorder сохранены для истории и аварийных кейсов, но больше не выглядят как канонический operator flow.</div>
        <div class="hero-tags">
          ${renderStatusPill('guided = legacy motion-only', 'warn')}
          ${renderStatusPill('manual = compatibility path', 'warn')}
          ${renderStatusPill('не primary по умолчанию', 'ok')}
        </div>
        <div class="capture-console__actions recording-archive__actions">
          <button
            type="button"
            class="capture-pack__button capture-pack__button--ghost"
            data-action="toggle-legacy-guided"
          >
            ${escapeHtml(guidedOpen ? 'Скрыть legacy guided packs' : 'Показать legacy guided packs')}
          </button>
          <button
            type="button"
            class="capture-pack__button capture-pack__button--ghost"
            data-action="toggle-legacy-manual"
          >
            ${escapeHtml(manualOpen ? 'Скрыть legacy manual recorder' : 'Показать legacy manual recorder')}
          </button>
        </div>

        ${guidedOpen ? `
          <div class="recording-archive__section">
            <div class="surface-grid surface-grid--two">
              <article class="panel">
                <div class="panel__eyebrow">Legacy guided packs</div>
                <div class="panel__text">Эти пакеты исторически полезны, но они не video-backed by default и поэтому больше не являются основным операторским путём.</div>
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

      <div class="surface-grid surface-grid--three">
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

        <article class="panel">
          <div class="panel__eyebrow">Активные runtime-paths</div>
          <div class="runtime-paths">
            ${snapshot.live.runtimePaths.map((item) => `
              <div class="runtime-path ${toneClass(statusTone(item.status))}">
                <span>${escapeHtml(item.label)}</span>
                <strong>${escapeHtml(displayToken(item.status))}</strong>
                <small>${escapeHtml(displayToken(item.role))} / ${escapeHtml(displayToken(item.mode))}</small>
              </div>
            `).join('')}
          </div>
        </article>

        <article class="panel">
          <div class="panel__eyebrow">Экспериментальная диагностика</div>
          <div class="kv-list">
            <div class="kv"><span>Binary</span><strong>${escapeHtml(displayToken(secondaryRuntime.binary || 'unknown'))}</strong></div>
            <div class="kv"><span>Binary confidence</span><strong>${escapeHtml(formatPercent(secondaryRuntime.binaryConfidence, 0))}</strong></div>
            <div class="kv"><span>Coarse</span><strong>${escapeHtml(displayToken(secondaryRuntime.coarse || 'unknown'))}</strong></div>
            <div class="kv"><span>Coarse confidence</span><strong>${escapeHtml(formatPercent(secondaryRuntime.coarseConfidence, 0))}</strong></div>
          </div>
          <div class="panel__footer">Эти поля остаются debug-only и не подменяют primary motion verdict.</div>
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
          <div class="panel__eyebrow">Operator workflow</div>
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
