export const ROOM_PROFILE_STORAGE_KEY = 'fp2_room_profiles_v1';
export const ROOM_PROFILE_ACTIVE_KEY = 'fp2_active_room_profile_v1';
export const ROOM_PROFILE_FILTER_KEY = 'fp2_room_profile_filters_v1';
export const ROOM_PROFILE_CALIBRATION_KEY = 'fp2_room_profile_calibration_v1';
export const ROOM_PROFILE_LAYOUT_KEY = 'fp2_room_profile_layout_v1';
export const ROOM_LAYOUT_TEMPLATE_KEY = 'fp2_room_layout_templates_v1';
export const DEFAULT_ROOM_PROFILE_ID = 'garage';

export const BUILTIN_ROOM_PROFILES = [
  {
    id: 'auto',
    kind: 'auto',
    labelKey: 'fp2.layout.auto',
    accent: '#38bdf8',
    defaultAntiAnimalFilterEnabled: false
  },
  {
    id: 'garage',
    kind: 'fixed',
    labelKey: 'fp2.layout.garage',
    widthCm: 420,
    depthCm: 500,
    accent: '#fbbf24',
    defaultAntiAnimalFilterEnabled: true
  },
  {
    id: 'room',
    kind: 'fixed',
    labelKey: 'fp2.layout.room_profile',
    widthCm: 460,
    depthCm: 380,
    accent: '#4ade80',
    defaultAntiAnimalFilterEnabled: false
  }
];

export const BUILTIN_ROOM_ITEM_LIBRARY = [
  { type: 'sofa', labelKey: 'fp2.layout.item.sofa', widthCm: 170, depthCm: 80, accent: '#64748b', icon: '🛋' },
  { type: 'bed', labelKey: 'fp2.layout.item.bed', widthCm: 180, depthCm: 200, accent: '#94a3b8', icon: '🛏' },
  { type: 'cabinet', labelKey: 'fp2.layout.item.cabinet', widthCm: 160, depthCm: 42, accent: '#6b7280', icon: '🗄' },
  { type: 'tv', labelKey: 'fp2.layout.item.tv', widthCm: 120, depthCm: 18, accent: '#475569', icon: '🖥' },
  { type: 'desk', labelKey: 'fp2.layout.item.desk', widthCm: 140, depthCm: 70, accent: '#78716c', icon: '🧑\u200d💻' },
  { type: 'chair', labelKey: 'fp2.layout.item.chair', widthCm: 55, depthCm: 55, accent: '#9ca3af', icon: '🪑' },
  { type: 'dining_table', labelKey: 'fp2.layout.item.dining_table', widthCm: 120, depthCm: 80, accent: '#8b5e3c', icon: '🍽' },
  { type: 'lamp', labelKey: 'fp2.layout.item.lamp', widthCm: 42, depthCm: 42, accent: '#f59e0b', icon: '💡' },
  { type: 'plant', labelKey: 'fp2.layout.item.plant', widthCm: 40, depthCm: 40, accent: '#22c55e', icon: '🪴' },
  { type: 'door', labelKey: 'fp2.layout.item.door', widthCm: 90, depthCm: 12, accent: '#cbd5e1', icon: '🚪' },
  { type: 'curtain', labelKey: 'fp2.layout.item.curtain', widthCm: 140, depthCm: 16, accent: '#e2e8f0', icon: '🪟' },
  { type: 'bath', labelKey: 'fp2.layout.item.bath', widthCm: 170, depthCm: 80, accent: '#93c5fd', icon: '🛁' },
  { type: 'toilet', labelKey: 'fp2.layout.item.toilet', widthCm: 60, depthCm: 70, accent: '#cbd5e1', icon: '🚽' },
  { type: 'stove', labelKey: 'fp2.layout.item.stove', widthCm: 90, depthCm: 60, accent: '#ef4444', icon: '🍳' }
];

export const BUILTIN_ROOM_TEMPLATES = [
  {
    id: 'empty_room',
    labelKey: 'fp2.layout.template.empty_room',
    items: []
  },
  {
    id: 'living_room',
    labelKey: 'fp2.layout.template.living_room',
    items: [
      { type: 'cabinet', nx: 0.18, ny: 0.08, nw: 0.3, nd: 0.1 },
      { type: 'cabinet', nx: 0.82, ny: 0.08, nw: 0.3, nd: 0.1 },
      { type: 'sofa', nx: 0.22, ny: 0.53, nw: 0.22, nd: 0.18 },
      { type: 'sofa', nx: 0.82, ny: 0.48, nw: 0.18, nd: 0.28 },
      { type: 'door', nx: 0.17, ny: 0.23, nw: 0.14, nd: 0.04 },
      { type: 'plant', nx: 0.09, ny: 0.11, nw: 0.07, nd: 0.07 }
    ]
  },
  {
    id: 'bedroom',
    labelKey: 'fp2.layout.template.bedroom',
    items: [
      { type: 'bed', nx: 0.28, ny: 0.25, nw: 0.32, nd: 0.28 },
      { type: 'cabinet', nx: 0.78, ny: 0.08, nw: 0.24, nd: 0.09 },
      { type: 'lamp', nx: 0.78, ny: 0.28, nw: 0.05, nd: 0.05 },
      { type: 'plant', nx: 0.1, ny: 0.12, nw: 0.06, nd: 0.06 }
    ]
  },
  {
    id: 'bathroom',
    labelKey: 'fp2.layout.template.bathroom',
    items: [
      { type: 'bath', nx: 0.28, ny: 0.2, nw: 0.28, nd: 0.2 },
      { type: 'toilet', nx: 0.76, ny: 0.24, nw: 0.1, nd: 0.12 },
      { type: 'cabinet', nx: 0.76, ny: 0.08, nw: 0.22, nd: 0.08 }
    ]
  },
  {
    id: 'corridor',
    labelKey: 'fp2.layout.template.corridor',
    items: [
      { type: 'cabinet', nx: 0.18, ny: 0.16, nw: 0.26, nd: 0.08 },
      { type: 'door', nx: 0.84, ny: 0.12, nw: 0.12, nd: 0.04 },
      { type: 'plant', nx: 0.84, ny: 0.32, nw: 0.06, nd: 0.06 }
    ]
  },
  {
    id: 'office',
    labelKey: 'fp2.layout.template.office',
    items: [
      { type: 'desk', nx: 0.25, ny: 0.22, nw: 0.26, nd: 0.16 },
      { type: 'chair', nx: 0.25, ny: 0.38, nw: 0.08, nd: 0.08 },
      { type: 'cabinet', nx: 0.82, ny: 0.12, nw: 0.22, nd: 0.08 },
      { type: 'tv', nx: 0.82, ny: 0.52, nw: 0.18, nd: 0.04 }
    ]
  },
  {
    id: 'conference_room',
    labelKey: 'fp2.layout.template.conference_room',
    items: [
      { type: 'dining_table', nx: 0.5, ny: 0.42, nw: 0.3, nd: 0.18 },
      { type: 'chair', nx: 0.36, ny: 0.42, nw: 0.07, nd: 0.07 },
      { type: 'chair', nx: 0.64, ny: 0.42, nw: 0.07, nd: 0.07 },
      { type: 'chair', nx: 0.5, ny: 0.28, nw: 0.07, nd: 0.07 },
      { type: 'chair', nx: 0.5, ny: 0.56, nw: 0.07, nd: 0.07 },
      { type: 'tv', nx: 0.5, ny: 0.1, nw: 0.24, nd: 0.04 }
    ]
  },
  {
    id: 'open_kitchen',
    labelKey: 'fp2.layout.template.open_kitchen',
    items: [
      { type: 'cabinet', nx: 0.22, ny: 0.08, nw: 0.32, nd: 0.09 },
      { type: 'stove', nx: 0.54, ny: 0.08, nw: 0.16, nd: 0.1 },
      { type: 'dining_table', nx: 0.68, ny: 0.48, nw: 0.22, nd: 0.16 },
      { type: 'chair', nx: 0.68, ny: 0.34, nw: 0.07, nd: 0.07 },
      { type: 'chair', nx: 0.82, ny: 0.48, nw: 0.07, nd: 0.07 }
    ]
  }
];

export function normalizeCustomRoomProfile(profile) {
  if (!profile || typeof profile !== 'object') return null;

  const widthCm = Number(profile.widthCm);
  const depthCm = Number(profile.depthCm);
  if (!Number.isFinite(widthCm) || !Number.isFinite(depthCm) || widthCm < 100 || depthCm < 100) {
    return null;
  }

  return {
    id: String(profile.id || `custom-${Date.now()}`),
    kind: 'fixed',
    name: String(profile.name || 'Custom Room').trim() || 'Custom Room',
    widthCm: Math.round(widthCm),
    depthCm: Math.round(depthCm),
    accent: typeof profile.accent === 'string' ? profile.accent : '#22d3ee',
    defaultAntiAnimalFilterEnabled: Boolean(profile.defaultAntiAnimalFilterEnabled)
  };
}

export function buildRoomProfiles(customProfiles) {
  const builtins = BUILTIN_ROOM_PROFILES.map((profile) => ({ ...profile, builtin: true }));
  return builtins.concat((customProfiles || []).map((profile) => ({ ...profile, builtin: false })));
}

export function getRoomItemDefinition(type) {
  return BUILTIN_ROOM_ITEM_LIBRARY.find((item) => item.type === type) || BUILTIN_ROOM_ITEM_LIBRARY[0];
}

function normalizeLayoutItem(item) {
  if (!item || typeof item !== 'object') return null;
  const def = getRoomItemDefinition(item.type);
  const x = Number(item.x);
  const y = Number(item.y);
  const widthCm = Number(item.widthCm);
  const depthCm = Number(item.depthCm);

  if (!Number.isFinite(x) || !Number.isFinite(y)) return null;

  return {
    id: String(item.id || `${item.type || 'item'}-${Date.now()}`),
    type: String(item.type || def.type),
    x: Math.round(x),
    y: Math.round(y),
    widthCm: Number.isFinite(widthCm) && widthCm > 0 ? Math.round(widthCm) : def.widthCm,
    depthCm: Number.isFinite(depthCm) && depthCm > 0 ? Math.round(depthCm) : def.depthCm,
    rotationDeg: Number.isFinite(Number(item.rotationDeg)) ? Number(item.rotationDeg) : 0
  };
}

function normalizeTemplateItem(item) {
  if (!item || typeof item !== 'object') return null;
  const def = getRoomItemDefinition(item.type);
  const nx = Number(item.nx);
  const ny = Number(item.ny);
  const nw = Number(item.nw);
  const nd = Number(item.nd);

  if (!Number.isFinite(nx) || !Number.isFinite(ny)) return null;

  return {
    type: String(item.type || def.type),
    nx: Math.max(0, Math.min(1, nx)),
    ny: Math.max(0, Math.min(1, ny)),
    nw: Number.isFinite(nw) && nw > 0 ? Math.min(1, nw) : null,
    nd: Number.isFinite(nd) && nd > 0 ? Math.min(1, nd) : null,
    rotationDeg: Number.isFinite(Number(item.rotationDeg)) ? Number(item.rotationDeg) : 0
  };
}

function normalizeCustomRoomTemplate(template) {
  if (!template || typeof template !== 'object') return null;
  const name = String(template.name || '').trim();
  if (!name) return null;
  const items = Array.isArray(template.items)
    ? template.items.map(normalizeTemplateItem).filter(Boolean)
    : [];
  return {
    id: String(template.id || `layout-template-${Date.now()}`),
    name,
    items
  };
}

export function buildRoomTemplates(customTemplates) {
  const builtins = BUILTIN_ROOM_TEMPLATES.map((template) => ({ ...template, builtin: true }));
  return builtins.concat((customTemplates || []).map((template) => ({ ...template, builtin: false })));
}

export function readStoredRoomProfiles() {
  if (typeof window === 'undefined' || !window.localStorage) return [];

  try {
    const raw = window.localStorage.getItem(ROOM_PROFILE_STORAGE_KEY);
    const parsed = raw ? JSON.parse(raw) : [];
    if (!Array.isArray(parsed)) return [];
    return parsed.map(normalizeCustomRoomProfile).filter(Boolean);
  } catch (error) {
    console.warn('Failed to read FP2 room profiles:', error);
    return [];
  }
}

export function persistRoomProfiles(customProfiles) {
  if (typeof window === 'undefined' || !window.localStorage) return;
  window.localStorage.setItem(ROOM_PROFILE_STORAGE_KEY, JSON.stringify(customProfiles || []));
}

export function readStoredRoomProfileLayouts() {
  if (typeof window === 'undefined' || !window.localStorage) return {};

  try {
    const raw = window.localStorage.getItem(ROOM_PROFILE_LAYOUT_KEY);
    const parsed = raw ? JSON.parse(raw) : {};
    if (!parsed || typeof parsed !== 'object') return {};
    return Object.fromEntries(
      Object.entries(parsed).map(([profileId, items]) => [
        profileId,
        Array.isArray(items) ? items.map(normalizeLayoutItem).filter(Boolean) : []
      ])
    );
  } catch (error) {
    console.warn('Failed to read FP2 room profile layouts:', error);
    return {};
  }
}

export function persistRoomProfileLayouts(layouts) {
  if (typeof window === 'undefined' || !window.localStorage) return;
  window.localStorage.setItem(ROOM_PROFILE_LAYOUT_KEY, JSON.stringify(layouts || {}));
}

export function readStoredRoomTemplates() {
  if (typeof window === 'undefined' || !window.localStorage) return [];

  try {
    const raw = window.localStorage.getItem(ROOM_LAYOUT_TEMPLATE_KEY);
    const parsed = raw ? JSON.parse(raw) : [];
    if (!Array.isArray(parsed)) return [];
    return parsed.map(normalizeCustomRoomTemplate).filter(Boolean);
  } catch (error) {
    console.warn('Failed to read FP2 room templates:', error);
    return [];
  }
}

export function persistRoomTemplates(templates) {
  if (typeof window === 'undefined' || !window.localStorage) return;
  window.localStorage.setItem(ROOM_LAYOUT_TEMPLATE_KEY, JSON.stringify(templates || []));
}

export function readStoredActiveRoomProfileId() {
  if (typeof window === 'undefined' || !window.localStorage) return DEFAULT_ROOM_PROFILE_ID;
  return window.localStorage.getItem(ROOM_PROFILE_ACTIVE_KEY) || DEFAULT_ROOM_PROFILE_ID;
}

export function persistActiveRoomProfileId(profileId) {
  if (typeof window === 'undefined' || !window.localStorage) return;
  window.localStorage.setItem(ROOM_PROFILE_ACTIVE_KEY, profileId);
}

export function readStoredRoomProfileFilters() {
  if (typeof window === 'undefined' || !window.localStorage) return {};

  try {
    const raw = window.localStorage.getItem(ROOM_PROFILE_FILTER_KEY);
    const parsed = raw ? JSON.parse(raw) : {};
    return parsed && typeof parsed === 'object' ? parsed : {};
  } catch (error) {
    console.warn('Failed to read FP2 room profile filters:', error);
    return {};
  }
}

export function persistRoomProfileFilters(filters) {
  if (typeof window === 'undefined' || !window.localStorage) return;
  window.localStorage.setItem(ROOM_PROFILE_FILTER_KEY, JSON.stringify(filters || {}));
}

export function readStoredRoomProfileCalibration() {
  if (typeof window === 'undefined' || !window.localStorage) return {};

  try {
    const raw = window.localStorage.getItem(ROOM_PROFILE_CALIBRATION_KEY);
    const parsed = raw ? JSON.parse(raw) : {};
    return parsed && typeof parsed === 'object' ? parsed : {};
  } catch (error) {
    console.warn('Failed to read FP2 room profile calibration:', error);
    return {};
  }
}

export function persistRoomProfileCalibration(calibration) {
  if (typeof window === 'undefined' || !window.localStorage) return;
  window.localStorage.setItem(ROOM_PROFILE_CALIBRATION_KEY, JSON.stringify(calibration || {}));
}

export function getRoomProfileById(profiles, profileId) {
  return (profiles || []).find((profile) => profile.id === profileId)
    || (profiles || [])[0]
    || BUILTIN_ROOM_PROFILES[0];
}

export function getRoomTemplateById(templates, templateId) {
  return (templates || []).find((template) => template.id === templateId)
    || (templates || [])[0]
    || BUILTIN_ROOM_TEMPLATES[0];
}

export function getProfileAnimalFilterEnabled(profile, filterOverrides = {}) {
  if (!profile) return false;
  const override = filterOverrides?.[profile.id];
  if (typeof override?.antiAnimalFilterEnabled === 'boolean') {
    return override.antiAnimalFilterEnabled;
  }
  return Boolean(profile.defaultAntiAnimalFilterEnabled);
}

function finiteOrNull(value) {
  return Number.isFinite(Number(value)) ? Number(value) : null;
}

export function normalizeCalibrationOverride(calibration) {
  if (!calibration || typeof calibration !== 'object') return null;

  const leftX = finiteOrNull(calibration.leftX);
  const rightX = finiteOrNull(calibration.rightX);
  const farY = finiteOrNull(calibration.farY);

  if (leftX === null && rightX === null && farY === null) return null;

  return {
    leftX,
    rightX,
    farY,
    capturedAt: calibration.capturedAt || null
  };
}

export function getProfileCalibrationOverride(profile, calibrationOverrides = {}) {
  if (!profile) return null;
  return normalizeCalibrationOverride(calibrationOverrides?.[profile.id]);
}

export function getProfileGeometry(profile, calibrationOverrides = {}) {
  if (!profile || profile.kind !== 'fixed') return null;

  const calibration = getProfileCalibrationOverride(profile, calibrationOverrides) || {};
  const defaultHalfWidth = (Number(profile.widthCm) || 0) / 2;
  const defaultMinX = -defaultHalfWidth;
  const defaultMaxX = defaultHalfWidth;
  const defaultMaxY = Number(profile.depthCm) || 0;
  const rawLeftX = Number.isFinite(calibration.leftX) ? calibration.leftX : defaultMinX;
  const rawRightX = Number.isFinite(calibration.rightX) ? calibration.rightX : defaultMaxX;
  const minX = Math.min(rawLeftX, rawRightX);
  const maxX = Math.max(rawLeftX, rawRightX);
  const minY = 0;
  const maxY = Number.isFinite(calibration.farY) ? calibration.farY : defaultMaxY;

  return {
    minX,
    maxX,
    minY,
    maxY,
    widthCm: Math.max(100, maxX - minX),
    depthCm: Math.max(100, maxY - minY),
    calibrated: Number.isFinite(calibration.leftX) || Number.isFinite(calibration.rightX) || Number.isFinite(calibration.farY),
    calibration
  };
}
