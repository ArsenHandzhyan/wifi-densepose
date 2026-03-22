// FP2 Formatting Helpers — extracted from FP2Tab.js
// Pure display-formatting methods that depend only on i18n `t()`.

import { t } from '../services/i18n.js?v=20260315-v48';

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

export const FP2FormattersMixin = {
  formatZoneName(zoneId, index) {
    if (!zoneId) return `Zone ${index + 1}`;
    if (zoneId === 'detection_area') return t('fp2.zone.detection_area');
    if (/^occupancy_\d+$/i.test(zoneId)) return `Zone ${index + 1}`;
    const match = String(zoneId).match(/^zone[_-]?(\d+)$/i);
    if (match) return t('fp2.zone.generic', { number: match[1] });
    return zoneId.replace(/^zone[_-]?/i, '').replace(/[_-]+/g, ' ').replace(/\s+/g, ' ').trim();
  },

  formatTransport(transport) {
    const normalized = String(transport || '').replace(/_/g, ' ').trim().toLowerCase();
    if (!normalized) return t('transport.fp2');
    if (normalized === 'aqara cloud') return t('transport.aqara_cloud');
    if (normalized === 'homekit / hap') return t('transport.homekit_hap');
    if (normalized === 'csi' || normalized === 'csi sensors') return t('transport.csi');
    return String(transport).replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
  },

  formatSource(source, transport) {
    const normalizedSource = String(source || '').replace(/\s+/g, ' ').trim().toLowerCase();
    const normalizedTransport = String(transport || '').replace(/_/g, ' ').trim().toLowerCase();

    if (normalizedSource === 'aqara_cloud' || normalizedSource === 'aqara cloud') {
      return 'aqara_cloud';
    }
    if (normalizedSource === 'homekit_hap' || normalizedSource === 'homekit / hap') {
      return 'homekit_hap';
    }
    if (normalizedSource === 'csi' || normalizedSource === 'csi_sensors' || normalizedTransport === 'csi sensors') {
      return 'csi';
    }
    if (!normalizedSource || normalizedSource === 'fp2') {
      if (normalizedTransport === 'aqara cloud') return 'aqara_cloud';
      if (normalizedTransport === 'homekit / hap') return 'homekit_hap';
      if (normalizedTransport === 'csi sensors') return 'csi';
      return 'fp2';
    }

    return String(source).replace(/\s+/g, '_').toLowerCase();
  },

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
  },

  formatEndpoint(ip, port) { return ip ? (port ? `${ip}:${port}` : ip) : '-'; },

  formatNetworkInfo(wifi) {
    const parts = [];
    if (wifi.ssid) parts.push(wifi.ssid);
    if (wifi.channel && wifi.channel !== '-') parts.push(`ch ${wifi.channel}`);
    if (wifi.signal_strength && wifi.signal_strength !== '-') parts.push(`${wifi.signal_strength} dBm`);
    return parts.join(' · ') || '-';
  },

  getLocale() {
    return document.documentElement.lang === 'ru' ? 'ru-RU' : 'en-US';
  },

  formatTimestamp(timestamp) {
    if (!timestamp) return new Date().toLocaleTimeString(this.getLocale());
    const d = new Date(timestamp);
    return Number.isNaN(d.getTime())
      ? new Date().toLocaleTimeString(this.getLocale())
      : d.toLocaleTimeString(this.getLocale());
  },

  formatDateTime(timestamp) {
    if (!timestamp) return '-';
    const d = new Date(timestamp);
    if (Number.isNaN(d.getTime())) return '-';
    return d.toLocaleString(this.getLocale(), {
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
      day: '2-digit',
      month: '2-digit'
    });
  },

  formatDeviceTimestamp(ts) {
    if (!Number.isFinite(ts)) return '-';
    const d = new Date(ts * 1000);
    if (Number.isNaN(d.getTime())) return '-';
    const ageSec = (Date.now() - d.getTime()) / 1000;
    return `${d.toLocaleTimeString(this.getLocale())} (${this.formatAgeSeconds(ageSec, true)})`;
  },

  formatOnlineState(online) { return online === true ? t('common.online') : online === false ? t('common.offline') : '-'; },
  formatDbm(v) { return Number.isFinite(v) ? `${Math.round(v)} dBm` : '-'; },
  formatDegrees(v) { return Number.isFinite(v) ? `${Math.round(v)}°` : '-'; },
  formatLengthCm(v, { preferMeters = false } = {}) {
    if (!Number.isFinite(v)) return '-';
    if (preferMeters) {
      return `${(Number(v) / 100).toFixed(2)} m`;
    }
    const abs = Math.abs(Number(v));
    return abs >= 100 ? `${(Number(v) / 100).toFixed(2)} m` : `${Math.round(Number(v))} cm`;
  },
  parseLengthToCm(value, { assumeMetersBelow = 25 } = {}) {
    if (value === null || value === undefined) return null;
    const raw = String(value).trim().toLowerCase();
    if (!raw) return null;
    const normalized = raw.replace(',', '.');
    const numeric = Number.parseFloat(normalized.replace(/[^0-9+\-.]/g, ''));
    if (!Number.isFinite(numeric)) return null;
    if (raw.includes('см') || raw.includes('cm')) return Math.round(numeric);
    if (raw.includes(' м') || raw.endsWith('м') || raw.includes('m')) return Math.round(numeric * 100);
    if ((raw.includes(',') || raw.includes('.')) && Math.abs(numeric) < 100) return Math.round(numeric * 100);
    if (Math.abs(numeric) <= assumeMetersBelow) return Math.round(numeric * 100);
    return Math.round(numeric);
  },
  formatAreaCm2(v) {
    if (!Number.isFinite(v)) return '-';
    return `${(Number(v) / 10000).toFixed(2)} m²`;
  },
  formatDistance(v) { return Number.isFinite(v) ? `${v.toFixed(1)} cm` : '-'; },
  formatAngle(v) { return Number.isFinite(v) ? `${v.toFixed(1)}°` : '-'; },
  formatMeters(v) { return Number.isFinite(v) ? `${v.toFixed(v >= 10 ? 0 : 1)} m` : '-'; },
  fmtCoord(v) { return Number.isFinite(v) ? `${Math.round(v)}` : '-'; },
  fmtDelta(v) { return Number.isFinite(v) ? `${v >= 0 ? '+' : ''}${Math.round(v)}` : '-'; },

  formatMovementEventCode(v) {
    if (v === null || v === undefined || v === '') return '-';
    const labelKey = MOVEMENT_LABELS[v];
    return labelKey ? `${t(labelKey)} (${v})` : t('fp2.state.code', { code: v });
  },

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
  },

  formatFallStateCode(v) {
    if (v === null || v === undefined || v === '') return '-';
    const labelKey = FALL_LABELS[v];
    return labelKey ? `${t(labelKey)} (${v})` : t('fp2.state.code', { code: v });
  },

  formatTargetClassification(value) {
    if (!value) return t('fp2.target.class.uncertain');
    return t(`fp2.target.class.${value}`);
  },

  formatTargetContinuityState(value) {
    if (!value) return t('fp2.target.continuity.unknown');
    return t(`fp2.target.continuity.${value}`);
  },

  formatTargetContinuityValue(target) {
    const label = this.formatTargetContinuityState(target?.continuity_state);
    const continuityGainCm = Number(target?.continuity_gain_cm);
    const stabilizationOffsetCm = Number(target?.stabilization_offset_cm);

    if (Number.isFinite(continuityGainCm) && Math.abs(continuityGainCm) >= 0.5) {
      return `${label} · ${continuityGainCm >= 0 ? '+' : ''}${continuityGainCm.toFixed(1)} cm`;
    }

    if (Number.isFinite(stabilizationOffsetCm)) {
      return `${label} · ${stabilizationOffsetCm.toFixed(1)} cm`;
    }

    return label;
  },

  getTargetsHintLabel({ showCsiEstimate, occupancyEvidenceMode, metadata }) {
    if (!showCsiEstimate) {
      if (metadata?.fp2_reference_fresh) {
        return t('fp2.hero.targets_hint_confirmed');
      }
      return t('fp2.hero.targets_hint_live');
    }

    switch (String(occupancyEvidenceMode || '')) {
      case 'csi_motion_estimate':
        return t('fp2.hero.targets_hint_motion_estimate');
      case 'csi_static_breathing_estimate':
        return t('fp2.hero.targets_hint_static_breathing');
      case 'csi_static_estimate':
      case 'csi_presence_estimate':
        return t('fp2.hero.targets_hint_static');
      case 'held_presence':
        return t('fp2.hero.targets_hint_held');
      case 'stale':
        return t('fp2.hero.targets_hint_stale');
      case 'reference_confirmed':
        return t('fp2.hero.targets_hint_confirmed');
      default:
        return t('fp2.hero.targets_hint_static');
    }
  },

  formatAgeSeconds(ageSec, withAgo = false) {
    if (!Number.isFinite(ageSec)) return '-';
    const rounded = ageSec.toFixed(ageSec < 10 ? 1 : 0);
    return withAgo
      ? t('common.seconds_ago', { count: rounded })
      : t('common.seconds_short', { count: rounded });
  },

  getPacketAge(pushTime) {
    if (!Number.isFinite(pushTime)) return '-';
    const ageSec = Math.max(0, Date.now() / 1000 - pushTime);
    return this.formatAgeSeconds(ageSec);
  },

  resolveSampleTimestampMs(iso, devTs) {
    const parsed = iso ? Date.parse(iso) : NaN;
    if (Number.isFinite(parsed)) return parsed;
    if (Number.isFinite(devTs)) return devTs * 1000;
    return Date.now();
  },

  getPresenceDuration() {
    if (!this.state.presenceStartedAt) return t('common.seconds_short', { count: 0 });
    const sec = Math.max(0, Math.floor((Date.now() - this.state.presenceStartedAt) / 1000));
    const m = Math.floor(sec / 60);
    const s = sec % 60;
    if (m === 0) {
      return t('common.seconds_short', { count: s });
    }
    return t('common.minutes_seconds', { minutes: m, seconds: s });
  },

  resourceLabel(rid, fallbackLabel) {
    const key = RESOURCE_LABELS[rid];
    if (key) return t(key);
    const zoneLabel = this.resourceZoneLabel(rid);
    if (zoneLabel) return zoneLabel;
    return fallbackLabel || rid;
  },

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
  },

  formatEventType(type) {
    return t(`fp2.event_type.${type}`);
  }
};
