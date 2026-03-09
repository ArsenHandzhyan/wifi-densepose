const TRACK_STALE_MS = 15000;

export function hasTargetCoordinates(target) {
  return Number.isFinite(target?.x) && Number.isFinite(target?.y) && (target.x !== 0 || target.y !== 0);
}

function getPerimeterMarginCm(profile) {
  return Math.max(35, Math.min(90, Number(profile?.perimeterMarginCm) || 55));
}

function isFixedProfile(profile) {
  return profile?.kind === 'fixed' && Number.isFinite(profile?.widthCm) && Number.isFinite(profile?.depthCm);
}

function isInteriorPoint(x, y, profile) {
  if (!isFixedProfile(profile)) return false;
  const margin = getPerimeterMarginCm(profile);
  const innerHalfWidth = Math.max(60, profile.widthCm / 2 - margin * 1.6);
  const innerStartY = Math.max(120, margin * 2.1);
  const innerEndY = Math.max(innerStartY + 40, profile.depthCm - margin);
  return Math.abs(x) <= innerHalfWidth && y >= innerStartY && y <= innerEndY;
}

function isPerimeterPoint(x, y, profile) {
  if (!isFixedProfile(profile)) return false;
  const margin = getPerimeterMarginCm(profile);
  const nearSideWall = Math.abs(x) >= profile.widthCm / 2 - margin;
  const nearSensorWall = y <= Math.max(90, margin * 1.6);
  const nearFarWall = y >= profile.depthCm - margin;
  return nearSideWall || nearSensorWall || nearFarWall;
}

function buildTrackSummary(track, target, sampleAtMs) {
  const ageSec = track?.firstSeenAtMs ? Math.max(0, (sampleAtMs - track.firstSeenAtMs) / 1000) : 0;
  const spanX = Number.isFinite(track?.minX) && Number.isFinite(track?.maxX) ? track.maxX - track.minX : 0;
  const spanY = Number.isFinite(track?.minY) && Number.isFinite(track?.maxY) ? track.maxY - track.minY : 0;
  const pathSpanCm = Math.sqrt(spanX * spanX + spanY * spanY);
  return {
    ageSec,
    pathSpanCm,
    maxDistanceCm: Math.max(Number(track?.maxDistanceCm) || 0, Number(target?.distance) || 0),
    samples: Number(track?.samples) || 0,
    enteredInterior: Boolean(track?.enteredInterior)
  };
}

export function updateTargetTrackState(previousTracks = {}, targets = [], sampleAtMs = Date.now(), profile = null) {
  const nextTracks = {};
  const activeTargets = Array.isArray(targets) ? targets : [];

  activeTargets.forEach((target) => {
    if (!hasTargetCoordinates(target)) return;
    const targetId = String(target.target_id || '');
    if (!targetId) return;

    const x = Number(target.x) || 0;
    const y = Number(target.y) || 0;
    const existing = previousTracks?.[targetId] || {};

    nextTracks[targetId] = {
      firstSeenAtMs: existing.firstSeenAtMs || sampleAtMs,
      lastSeenAtMs: sampleAtMs,
      samples: Number(existing.samples || 0) + 1,
      minX: Number.isFinite(existing.minX) ? Math.min(existing.minX, x) : x,
      maxX: Number.isFinite(existing.maxX) ? Math.max(existing.maxX, x) : x,
      minY: Number.isFinite(existing.minY) ? Math.min(existing.minY, y) : y,
      maxY: Number.isFinite(existing.maxY) ? Math.max(existing.maxY, y) : y,
      maxDistanceCm: Math.max(Number(existing.maxDistanceCm) || 0, Number(target.distance) || 0),
      enteredInterior: Boolean(existing.enteredInterior) || isInteriorPoint(x, y, profile)
    };
  });

  Object.entries(previousTracks || {}).forEach(([targetId, track]) => {
    if (nextTracks[targetId]) return;
    const lastSeenAtMs = Number(track?.lastSeenAtMs) || 0;
    if (sampleAtMs - lastSeenAtMs <= TRACK_STALE_MS) {
      nextTracks[targetId] = track;
    }
  });

  return nextTracks;
}

export function classifyTargets(targets = [], trackState = {}, profile = null, antiAnimalFilterEnabled = false, sampleAtMs = Date.now()) {
  const classifiedTargets = (Array.isArray(targets) ? targets : []).map((target) => {
    const track = trackState?.[target.target_id] || null;
    const summary = buildTrackSummary(track, target, sampleAtMs);
    const perimeter = hasTargetCoordinates(target) ? isPerimeterPoint(target.x, target.y, profile) : false;
    const fixedProfile = isFixedProfile(profile);
    const humanDistanceThreshold = fixedProfile ? Math.max(200, profile.depthCm * 0.4) : 200;
    const humanLike = summary.enteredInterior
      || summary.ageSec >= 4
      || summary.pathSpanCm >= 100
      || summary.maxDistanceCm >= humanDistanceThreshold;

    let classification = 'uncertain';
    if (humanLike) {
      classification = 'human';
    } else if (
      antiAnimalFilterEnabled
      && fixedProfile
      && perimeter
      && summary.ageSec < 4
      && summary.pathSpanCm < 100
      && summary.maxDistanceCm < Math.max(220, profile.depthCm * 0.55)
    ) {
      classification = 'animal_like';
    }

    return {
      ...target,
      track_age_sec: summary.ageSec,
      track_path_cm: summary.pathSpanCm,
      track_samples: summary.samples,
      entered_interior: summary.enteredInterior,
      target_classification: classification,
      filtered_out: antiAnimalFilterEnabled && classification === 'animal_like'
    };
  });

  return {
    allTargets: classifiedTargets,
    visibleTargets: classifiedTargets.filter((target) => !target.filtered_out),
    filteredTargets: classifiedTargets.filter((target) => target.filtered_out)
  };
}

export function applyTargetCountsToZones(zones = [], visibleTargets = [], filteredTargets = []) {
  const visibleCounts = {};
  const filteredCounts = {};

  (visibleTargets || []).forEach((target) => {
    const zoneId = String(target.zone_id || 'detection_area');
    visibleCounts[zoneId] = (visibleCounts[zoneId] || 0) + 1;
  });

  (filteredTargets || []).forEach((target) => {
    const zoneId = String(target.zone_id || 'detection_area');
    filteredCounts[zoneId] = (filteredCounts[zoneId] || 0) + 1;
  });

  return (zones || []).map((zone) => {
    const zoneId = String(zone.zone_id || zone.id || 'detection_area');
    return {
      ...zone,
      target_count: visibleCounts[zoneId] || 0,
      suppressed_count: filteredCounts[zoneId] || 0
    };
  });
}
