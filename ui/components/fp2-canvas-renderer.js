// FP2 Canvas Renderer Mixin — extracted from FP2Tab.js
// Handles: canvas initialization, DPI scaling, drawing helpers,
// movement map, coordinate map, room profile shell, trails,
// realtime graph, RSSI gauge, angle dial, quality monitor.

import { t, tp } from '../services/i18n.js?v=20260313-v46';
import { hasTargetCoordinates } from '../services/fp2.target-filter.js?v=20260308-v2';

const TARGET_COLORS = ['#4ade80', '#38bdf8', '#f472b6', '#facc15', '#a78bfa', '#fb923c'];

export const FP2CanvasRendererMixin = {
  initCanvas() {
    const canvas = this.elements.movementCanvas;
    if (!canvas) return;
    this.canvasCtx = canvas.getContext('2d');
    this.drawMovementMap([], false, [], null, false);
  },

  initRssiGauge() {
    const canvas = this.elements.rssiGauge;
    if (!canvas) return;
    this.rssiCtx = canvas.getContext('2d');
    this.drawRssiGauge(null);
  },

  initAngleDial() {
    const canvas = this.elements.angleDial;
    if (!canvas) return;
    this.angleCtx = canvas.getContext('2d');
    this.drawAngleDial(null);
  },

  initRealtimeGraph() {
    const canvas = this.container.querySelector('#fp2RealtimeGraph');
    if (!canvas) return;
    this.graphCanvas = canvas;
    this.graphCtx = canvas.getContext('2d');
    this.graphData = [];
    this.maxGraphPoints = 120;
    this.drawRealtimeGraph();
  },

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
  },

  initCoordinateQualityMonitor() {
    const canvas = this.container.querySelector('#fp2CoordinateQualityCanvas');
    if (!canvas) return;
    this.coordinateQualityCanvas = canvas;
    this.coordinateQualityCtx = canvas.getContext('2d');
    this.drawCoordinateQualityGraph();
  },

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
    if ('imageSmoothingEnabled' in ctx) ctx.imageSmoothingEnabled = true;
    if ('imageSmoothingQuality' in ctx) ctx.imageSmoothingQuality = 'high';
    return { width: cssWidth, height: cssHeight };
  },

  fitCanvasText(ctx, text, maxWidth) {
    const normalized = String(text ?? '');
    if (!normalized || !Number.isFinite(maxWidth) || maxWidth <= 0) return '';
    if (ctx.measureText(normalized).width <= maxWidth) return normalized;

    let trimmed = normalized;
    while (trimmed.length > 1 && ctx.measureText(`${trimmed}…`).width > maxWidth) {
      trimmed = trimmed.slice(0, -1);
    }
    return `${trimmed}…`;
  },

  fitCanvasTextLines(ctx, text, maxWidth, maxLines = 2) {
    const normalized = String(text ?? '').replace(/\s+/g, ' ').trim();
    if (!normalized || !Number.isFinite(maxWidth) || maxWidth <= 0 || maxLines <= 0) return [];
    if (ctx.measureText(normalized).width <= maxWidth) return [normalized];

    const words = normalized.split(' ');
    if (words.length === 1) return [this.fitCanvasText(ctx, normalized, maxWidth)];

    const lines = [];
    let current = '';

    for (let i = 0; i < words.length; i += 1) {
      const word = words[i];
      const candidate = current ? `${current} ${word}` : word;
      if (ctx.measureText(candidate).width <= maxWidth) {
        current = candidate;
        continue;
      }

      if (current) {
        lines.push(current);
      }

      if (lines.length >= maxLines - 1) {
        const remainder = [word, ...words.slice(i + 1)].join(' ');
        lines.push(this.fitCanvasText(ctx, remainder, maxWidth));
        return lines.slice(0, maxLines);
      }

      current = word;
      if (ctx.measureText(current).width > maxWidth) {
        lines.push(this.fitCanvasText(ctx, current, maxWidth));
        current = '';
      }
    }

    if (current) {
      lines.push(current);
    }

    return lines.slice(0, maxLines);
  },

  drawCanvasTag(ctx, x, y, text, options = {}) {
    const value = String(text ?? '').trim();
    if (!value) return;

    const {
      bounds = null,
      maxWidth = 180,
      paddingX = 10,
      paddingY = 6,
      font = '600 12px Inter, system-ui, sans-serif',
      color = options.textColor || '#e2e8f0',
      background = 'rgba(8, 15, 28, 0.82)',
      border = 'rgba(148, 163, 184, 0.2)',
      radius = 999,
      align = 'center'
    } = options;

    ctx.save();
    ctx.font = font;
    const fitted = this.fitCanvasText(ctx, value, maxWidth);
    const textWidth = ctx.measureText(fitted).width;
    const boxWidth = Math.ceil(textWidth + paddingX * 2);
    const boxHeight = 28;
    let boxX = align === 'left' ? x : x - boxWidth / 2;
    let boxY = y;

    if (bounds) {
      const minX = Number.isFinite(bounds.left) ? bounds.left : boxX;
      const maxX = Number.isFinite(bounds.right) ? bounds.right : boxX + boxWidth;
      const minY = Number.isFinite(bounds.top) ? bounds.top : boxY;
      const maxY = Number.isFinite(bounds.bottom) ? bounds.bottom : boxY + boxHeight;
      boxX = Math.min(Math.max(boxX, minX), Math.max(minX, maxX - boxWidth));
      boxY = Math.min(Math.max(boxY, minY), Math.max(minY, maxY - boxHeight));
    }

    this.drawRoundedRect(ctx, boxX, boxY, boxWidth, boxHeight, radius);
    ctx.fillStyle = background;
    ctx.fill();
    ctx.strokeStyle = border;
    ctx.lineWidth = 1;
    ctx.stroke();

    ctx.fillStyle = color;
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillText(fitted, boxX + boxWidth / 2, boxY + boxHeight / 2 + 1);
    ctx.restore();
  },

  drawCanvasTextBubble(ctx, x, y, lines, options = {}) {
    const visibleLines = (lines || []).filter(Boolean);
    if (!visibleLines.length) return;

    const {
      bounds = null,
      offsetX = 14,
      offsetY = -18,
      paddingX = 10,
      paddingY = 7,
      titleFont = '700 13px Inter, system-ui, sans-serif',
      bodyFont = '600 12px Inter, system-ui, sans-serif',
      background = 'rgba(8, 15, 28, 0.82)',
      border = 'rgba(148, 163, 184, 0.18)',
      titleColor = '#e2e8f0',
      bodyColor = '#94a3b8',
      radius = 10,
      maxWidth = null
    } = options;

    ctx.save();
    const maxBubbleContentWidth = (() => {
      if (Number.isFinite(maxWidth) && maxWidth > 24) return maxWidth;
      if (!bounds) return null;
      const left = Number.isFinite(bounds.left) ? bounds.left : 0;
      const right = Number.isFinite(bounds.right) ? bounds.right : 0;
      const available = right - left - paddingX * 2 - 8;
      return available > 24 ? available : null;
    })();
    const fonts = visibleLines.map((_, index) => (index === 0 ? titleFont : bodyFont));
    const fittedLines = visibleLines.map((line, index) => {
      ctx.font = fonts[index];
      return maxBubbleContentWidth ? this.fitCanvasText(ctx, line, maxBubbleContentWidth) : line;
    });
    const lineMetrics = fittedLines.map((line, index) => {
      ctx.font = fonts[index];
      return ctx.measureText(line).width;
    });
    const lineHeights = fittedLines.map((_, index) => (index === 0 ? 15 : 14));
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
    fittedLines.forEach((line, index) => {
      ctx.font = fonts[index];
      ctx.fillStyle = index === 0 ? titleColor : bodyColor;
      ctx.fillText(line, boxX + paddingX, cursorY);
      cursorY += lineHeights[index] + 2;
    });
    ctx.restore();
  },

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
      this.getCsiRenderMode(),
      this.state.activeRoomProfileId,
      this.state.selectedRoomItemId || 'none',
      this.state.editLayoutMode ? 1 : 0,
      targetSig,
      rawSig,
      zoneSig,
      layoutSig,
      trailSig,
      this.getCoordinateSnapshotState() === 'frozen'
        ? 1
        : (this.getCoordinateSnapshotState() === 'last_known' ? 2 : 0)
    ].join('~');
  },

  renderAnimatedMap(force = false) {
    if (!this.state.pageVisible && !force) {
      this.state.pendingVisualRefresh = true;
      return;
    }
    const baseTargets = this.getCoordinateSnapshotState() !== 'live'
      ? (this.state.rawTargets || []).filter((target) => this.hasCoordinates(target))
      : (this.state.targets || []).filter((target) => this.hasCoordinates(target));
    const displayTargets = this.projectTargetsForDisplay(baseTargets, this.lastCurrentData);
    const displayAllTargets = this.projectTargetsForDisplay(this.state.rawTargets || [], this.lastCurrentData);
    const signature = this.buildMapRenderSignature(displayTargets, displayAllTargets);
    if (!force && signature === this.state.lastMapSignature) {
      return;
    }
    this.state.lastMapSignature = signature;
    this.drawMovementMap(
      this.state.zones,
      this.state.currentPresenceActive,
      displayTargets,
      displayAllTargets,
      this.state.currentSensorAngle,
      this.state.currentAvailability
    );
  },

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
        ctx.strokeStyle = 'rgba(74,222,128,0.3)';
        ctx.lineWidth = 2;
        ctx.beginPath();
        ctx.arc(px, py, 22, 0, Math.PI * 2);
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
  },

  getFixedRoomProjection(width, height, profile) {
    const marginX = 42;
    const marginTop = 40;
    const marginBottom = 56;
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
      boundary: geometry.boundary || null,
      originX: toCanvasX(0),
      originY: toCanvasY(0),
      toCanvasX,
      toCanvasY
    };
  },

  drawRoomProfileShell(ctx, projection, profile, sensorAngle, available, presence) {
    const { roomRect, originX, originY, widthCm, depthCm, calibrated } = projection;
    const accent = profile?.accent || '#38bdf8';
    const calibration = this.getCalibrationDraft(profile);

    this.drawRoundedRect(ctx, roomRect.x, roomRect.y, roomRect.width, roomRect.height, 18);
    ctx.fillStyle = available && presence ? 'rgba(34,211,238,0.06)' : 'rgba(15,23,42,0.55)';
    ctx.fill();
    ctx.lineWidth = 2;
    ctx.strokeStyle = `${accent}aa`;
    ctx.stroke();

    ctx.fillStyle = '#f8fafc';
    ctx.font = '700 13px Inter, system-ui, sans-serif';
    ctx.fillText(this.getRoomProfileLabel(profile), roomRect.x + 16, roomRect.y + 28);
    ctx.fillStyle = 'rgba(148,163,184,0.75)';
    ctx.font = '600 11px Inter, system-ui, sans-serif';
    ctx.fillText(
      `${this.formatLengthCm(widthCm, { preferMeters: true })} × ${this.formatLengthCm(depthCm, { preferMeters: true })}${calibrated ? ` · ${t('fp2.layout.calibrated_short')}` : ''}`,
      roomRect.x + 16,
      roomRect.y + 46
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
    ctx.font = '600 11px Inter, system-ui, sans-serif';
    ctx.fillText(t('fp2.sensor_label'), originX - 18, originY + 22);
  },

  drawRoomBoundaryOutline(ctx, projection, boundaryLike, { draft = false } = {}) {
    const points = Array.isArray(boundaryLike?.points) ? boundaryLike.points : [];
    if (!projection || !points.length) return;

    const { roomRect, toCanvasX, toCanvasY } = projection;
    const canvasPoints = points.map((point) => ({
      x: toCanvasX(point.xCm),
      y: toCanvasY(point.yCm)
    }));
    const metrics = this.getRoomBoundaryMetrics(boundaryLike);
    const centroid = canvasPoints.reduce((acc, point) => ({
      x: acc.x + point.x,
      y: acc.y + point.y
    }), { x: 0, y: 0 });
    centroid.x /= canvasPoints.length;
    centroid.y /= canvasPoints.length;

    ctx.save();
    ctx.beginPath();
    canvasPoints.forEach((point, index) => {
      if (index === 0) ctx.moveTo(point.x, point.y);
      else ctx.lineTo(point.x, point.y);
    });
    if (canvasPoints.length >= 3) {
      ctx.closePath();
      ctx.fillStyle = draft ? 'rgba(250, 204, 21, 0.10)' : 'rgba(34, 211, 238, 0.08)';
      ctx.fill();
    }
    ctx.strokeStyle = draft ? 'rgba(250, 204, 21, 0.96)' : 'rgba(34, 211, 238, 0.92)';
    ctx.lineWidth = draft ? 2.4 : 2.1;
    if (draft) {
      ctx.setLineDash([10, 6]);
    }
    ctx.stroke();
    ctx.setLineDash([]);

    canvasPoints.forEach((point, index) => {
      ctx.beginPath();
      ctx.arc(point.x, point.y, index === canvasPoints.length - 1 && draft ? 5 : 4, 0, Math.PI * 2);
      ctx.fillStyle = draft ? '#facc15' : '#22d3ee';
      ctx.fill();
      ctx.strokeStyle = 'rgba(8, 15, 28, 0.95)';
      ctx.lineWidth = 1.2;
      ctx.stroke();
    });

    if (canvasPoints.length >= 3) {
      this.drawCanvasTag(
        ctx,
        centroid.x,
        centroid.y - 16,
        `${this.formatRoomBoundaryShape(metrics.shapeType)} · ${this.formatAreaCm2(metrics.areaCm2)}`,
        {
          bounds: {
            left: roomRect.x + 12,
            top: roomRect.y + 12,
            right: roomRect.x + roomRect.width - 12,
            bottom: roomRect.y + roomRect.height - 12
          },
          maxWidth: Math.min(260, roomRect.width * 0.58),
          font: '700 12px Inter, system-ui, sans-serif',
          background: draft ? 'rgba(120, 53, 15, 0.82)' : 'rgba(8, 15, 28, 0.84)',
          border: draft ? 'rgba(250, 204, 21, 0.36)' : 'rgba(34, 211, 238, 0.28)',
          textColor: '#f8fafc'
        }
      );
    }
    ctx.restore();
  },

  drawRoomLayoutItems(ctx, projection, items = []) {
    if (!items.length) return;

    const { roomRect, widthCm, depthCm, toCanvasX, toCanvasY } = projection;
    const scaleX = roomRect.width / Math.max(1, widthCm);
    const scaleY = roomRect.height / Math.max(1, depthCm);
    const inEditMode = Boolean(this.state.editLayoutMode);
    const compactMap = roomRect.width < 420;

    items.forEach((item) => {
      const def = getRoomItemDefinition(item.type);
      const width = Math.max(10, item.widthCm * scaleX);
      const depth = Math.max(10, item.depthCm * scaleY);
      const centerX = toCanvasX(item.x);
      const centerY = toCanvasY(item.y);
      const isSelected = item.id === this.state.selectedRoomItemId;
      const icon = this.getRoomItemIcon(item);
      const labelText = this.getRoomItemLabel(item);
      const labelBounds = {
        left: roomRect.x + 10,
        right: roomRect.x + roomRect.width - 10,
        top: roomRect.y + 10,
        bottom: roomRect.y + roomRect.height - 10
      };

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
      const iconFontPx = Math.max(14, Math.min(24, Math.round(minBox / 2.5)));
      const labelFontPx = Math.max(12, Math.min(14, Math.round(minBox / 3.8)));
      const shouldDrawInlineLabel = false;

      ctx.fillStyle = '#e2e8f0';
      ctx.font = `700 ${iconFontPx}px Inter, system-ui, sans-serif`;
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      ctx.shadowColor = 'rgba(8, 15, 28, 0.85)';
      ctx.shadowBlur = 8;

      let inlineLabelLines = [];
      if (shouldDrawInlineLabel) {
        ctx.font = `700 ${labelFontPx}px Inter, system-ui, sans-serif`;
        inlineLabelLines = this.fitCanvasTextLines(ctx, labelText, Math.max(52, width - 22), 2);
      }
      const iconOffsetY = inlineLabelLines.length ? -Math.min(12, depth * 0.14) : 0;
      ctx.font = `700 ${iconFontPx}px Inter, system-ui, sans-serif`;
      ctx.fillText(icon, 0, iconOffsetY);

      if (inlineLabelLines.length) {
        ctx.font = `700 ${labelFontPx}px Inter, system-ui, sans-serif`;
        const lineWidths = inlineLabelLines.map((line) => ctx.measureText(line).width);
        const backgroundWidth = Math.max(46, Math.max(...lineWidths) + 18);
        const lineGap = labelFontPx + 1;
        const backgroundHeight = inlineLabelLines.length * lineGap + 10;
        const labelY = Math.min(depth / 2 - backgroundHeight / 2 - 8, 20);
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
        inlineLabelLines.forEach((line, index) => {
          const lineYOffset = ((index - (inlineLabelLines.length - 1) / 2) * lineGap) + 1;
          ctx.fillText(line, 0, labelY + lineYOffset);
        });
      }
      ctx.shadowBlur = 0;
      ctx.shadowColor = 'transparent';

      if (isSelected && inEditMode) {
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

      const shouldDrawExternalLabel = isSelected && inEditMode;
      if (shouldDrawExternalLabel) {
        const tagY = centerY - (depth / 2) - 34 < labelBounds.top
          ? centerY + (depth / 2) + 10
          : centerY - (depth / 2) - 30;
        this.drawCanvasTag(ctx, centerX, tagY, labelText, {
          bounds: labelBounds,
          maxWidth: Math.min(compactMap ? 180 : 260, Math.max(120, roomRect.width * (compactMap ? 0.26 : 0.34))),
          font: `700 ${Math.max(10, Math.min(compactMap ? 12 : 13, labelFontPx))}px Inter, system-ui, sans-serif`,
          background: isSelected ? 'rgba(8, 15, 28, 0.94)' : 'rgba(8, 15, 28, 0.86)',
          border: isSelected ? 'rgba(248,250,252,0.38)' : 'rgba(148, 163, 184, 0.22)'
        });
      }
    });
    ctx.textAlign = 'left';
    ctx.textBaseline = 'alphabetic';
    ctx.font = '12px Inter, system-ui, sans-serif';
  },

  drawCoordinateMap(ctx, width, height, targets, allTargets, sensorAngle, available, roomProfile, presence) {
    if (roomProfile?.kind === 'fixed') {
      const projection = this.getFixedRoomProjection(width, height, roomProfile);
      this.state.lastRoomProjection = projection;
      const { roomRect, originX, originY, toCanvasX, toCanvasY } = projection;
      const snapshotState = this.getCoordinateSnapshotState();
      const staleSnapshot = snapshotState !== 'live';
      const compactMap = roomRect.width < 420 || width < 860;
      const suppressedTargets = (allTargets || []).filter((target) => target.filtered_out && this.hasCoordinates(target));
      const roomItems = this.getActiveRoomLayoutItems(roomProfile);
      const roomStructures = this.getActiveRoomStructuralAreas(roomProfile);
      const walkableAreas = this.getActiveRoomWalkableAreas(roomProfile);
      const roomBoundary = this.getStoredRoomBoundary(roomProfile);
      const boundaryDraft = this.getRoomBoundaryDraft(roomProfile);
      const boundaryPreview = boundaryDraft && (boundaryDraft.points || []).length
        ? boundaryDraft
        : roomBoundary;
      const recentTrace = false;

      this.drawRoomProfileShell(ctx, projection, roomProfile, sensorAngle, available, presence);
      this.drawRoomBoundaryOutline(ctx, projection, boundaryPreview, {
        draft: Boolean(boundaryDraft)
      });
      this.drawRoomWalkableAreas(ctx, projection, walkableAreas);
      this.drawRoomStructuralAreas(ctx, projection, roomStructures);
      this.drawRoomLayoutItems(ctx, projection, roomItems);
      this.drawRoomStructureDraft(ctx, projection, this.state.roomStructureDraft);

      ctx.save();
      ctx.beginPath();
      this.drawRoundedRect(ctx, roomRect.x, roomRect.y, roomRect.width, roomRect.height, 18);
      ctx.clip();

      const trail = this.state.trailHistory;
      if (trail.length > 1 && (!staleSnapshot || recentTrace)) {
        const getTrailKey = (target) => String(target?.target_id ?? target?.id ?? '');
        const activeKeys = new Set(
          (targets.length ? targets : (trail.at(-1)?.targets || []))
            .map(getTrailKey)
            .filter(Boolean)
        );
        const byId = new Map();
        trail.forEach(snapshot => {
          snapshot.targets.forEach(target => {
            const key = getTrailKey(target);
            if (activeKeys.size && key && !activeKeys.has(key)) return;
            if (!byId.has(key || `trail_${byId.size}`)) byId.set(key || `trail_${byId.size}`, []);
            byId.get(key || `trail_${byId.size}`).push(target);
          });
        });

        let colorIndex = 0;
        byId.forEach(points => {
          const visiblePoints = points.slice(-10);
          if (visiblePoints.length < 2) {
            colorIndex++;
            return;
          }

          const color = TARGET_COLORS[colorIndex % TARGET_COLORS.length];
          colorIndex++;
          for (let i = 1; i < visiblePoints.length; i++) {
            const opacity = 0.035 + (i / visiblePoints.length) * 0.085;
            ctx.globalAlpha = opacity;
            ctx.strokeStyle = color;
            ctx.lineWidth = 1.05;
            ctx.beginPath();
            ctx.moveTo(toCanvasX(visiblePoints[i - 1].x), toCanvasY(visiblePoints[i - 1].y));
            ctx.lineTo(toCanvasX(visiblePoints[i].x), toCanvasY(visiblePoints[i].y));
            ctx.stroke();
          }
          ctx.globalAlpha = 1;
        });
      }

      targets.forEach((target, i) => {
        const px = toCanvasX(target.x);
        const py = toCanvasY(target.y);
        const color = TARGET_COLORS[i % TARGET_COLORS.length];
        const isHeld = Boolean(target.held);

        // Line from sensor to target — dashed for held coordinates
        if (isHeld) {
          ctx.setLineDash([6, 5]);
        }
        ctx.strokeStyle = staleSnapshot ? `${color}33` : (isHeld ? `${color}44` : `${color}55`);
        ctx.lineWidth = staleSnapshot ? 1.1 : 1.5;
        ctx.beginPath();
        ctx.moveTo(originX, originY);
        ctx.lineTo(px, py);
        ctx.stroke();
        if (isHeld) {
          ctx.setLineDash([]);
        }

        if (!staleSnapshot && !isHeld) {
          const gradient = ctx.createRadialGradient(px, py, 0, px, py, compactMap ? 16 : 20);
          gradient.addColorStop(0, `${color}36`);
          gradient.addColorStop(1, `${color}00`);
          ctx.fillStyle = gradient;
          ctx.beginPath();
          ctx.arc(px, py, compactMap ? 16 : 20, 0, Math.PI * 2);
          ctx.fill();
        }

        // Held targets: semi-transparent fill + dashed ring
        ctx.globalAlpha = isHeld ? 0.55 : 1.0;
        ctx.fillStyle = color;
        ctx.beginPath();
        ctx.arc(px, py, i === 0 ? 8 : 6, 0, Math.PI * 2);
        ctx.fill();
        if (isHeld) {
          ctx.setLineDash([3, 3]);
          ctx.strokeStyle = 'rgba(251,191,36,0.7)';
          ctx.lineWidth = 1.8;
          ctx.beginPath();
          ctx.arc(px, py, 12, 0, Math.PI * 2);
          ctx.stroke();
          ctx.setLineDash([]);
        } else {
          ctx.strokeStyle = staleSnapshot ? 'rgba(255,255,255,0.82)' : '#fff';
          ctx.lineWidth = staleSnapshot ? 1.2 : 1.5;
          ctx.stroke();
        }
        ctx.globalAlpha = 1.0;
        this.drawCanvasTextBubble(
          ctx,
          px,
          py,
          [
            String(target.target_id || `target_${i}`) + (isHeld ? ' ⏳' : ''),
            `${Math.round(target.distance || 0)} cm · ${Math.round(target.angle || 0)}°`
          ],
          {
            bounds: {
              left: roomRect.x + 8,
              right: roomRect.x + roomRect.width - 8,
              top: roomRect.y + 8,
              bottom: roomRect.y + roomRect.height - 8
            },
            maxWidth: compactMap ? 128 : 164,
            offsetX: staleSnapshot ? 10 : 14,
            offsetY: staleSnapshot ? -14 : -18,
            background: staleSnapshot ? 'rgba(8, 15, 28, 0.9)' : 'rgba(8, 15, 28, 0.82)',
            border: staleSnapshot ? 'rgba(148, 163, 184, 0.22)' : 'rgba(148, 163, 184, 0.18)'
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
      ctx.restore();

      ctx.fillStyle = available
        ? (targets.length > 0 ? 'rgba(74,222,128,0.9)' : 'rgba(251,191,36,0.9)')
        : 'rgba(248,113,113,0.9)';
      ctx.font = '700 12px Inter, system-ui, sans-serif';
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

      return;
    }

    const margin = 40;
    const plotLeft = margin;
    const plotTop = 30;
    const plotWidth = width - margin * 2;
    const plotHeight = height - margin - 20;
    const originX = plotLeft + plotWidth / 2;
    const originY = plotTop + plotHeight / 2;
    // Use a stable maxAbs: expand instantly when targets move outward,
    // but shrink slowly so the scale doesn't jitter between frames.
    const frameMax = Math.max(400, ...targets.flatMap(t => [Math.abs(t.x || 0), Math.abs(t.y || 0)]));
    if (!this.state._radarMaxAbs || frameMax > this.state._radarMaxAbs) {
      this.state._radarMaxAbs = frameMax;
    } else {
      // Shrink by at most 2% per frame toward the current value
      this.state._radarMaxAbs = this.state._radarMaxAbs * 0.98 + frameMax * 0.02;
    }
    const maxAbs = this.state._radarMaxAbs;

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
      this.drawFovCone(ctx, originX, originY, rayLen, rad, fovHalf, {
        fill: 'rgba(250,204,21,0.05)',
        edge: 'rgba(250,204,21,0.12)',
        edgeWidth: 1
      });

      ctx.strokeStyle = 'rgba(250,204,21,0.5)';
      ctx.lineWidth = 2;
      ctx.setLineDash([6, 4]);
      ctx.beginPath(); ctx.moveTo(originX, originY); ctx.lineTo(rx, ry); ctx.stroke();
      ctx.setLineDash([]);

      ctx.fillStyle = 'rgba(250,204,21,0.85)';
      ctx.font = '600 10px Inter, system-ui, sans-serif';
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
    ctx.font = '700 12px Inter, system-ui, sans-serif';
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
    ctx.font = '600 10px Inter, system-ui, sans-serif';
    ctx.fillText('+Y', originX + 4, plotTop + 8);
    ctx.fillText('-Y', originX + 4, plotTop + plotHeight - 4);
    ctx.fillText('+X', plotLeft + plotWidth - 18, originY - 4);
    ctx.fillText('-X', plotLeft + 4, originY - 4);
  },

  drawRoundedRect(ctx, x, y, w, h, r) {
    const radius = Math.max(0, Math.min(Number(r) || 0, Math.abs(w) / 2, Math.abs(h) / 2));
    ctx.beginPath();
    ctx.moveTo(x + radius, y);
    ctx.lineTo(x + w - radius, y);
    ctx.quadraticCurveTo(x + w, y, x + w, y + radius);
    ctx.lineTo(x + w, y + h - radius);
    ctx.quadraticCurveTo(x + w, y + h, x + w - radius, y + h);
    ctx.lineTo(x + radius, y + h);
    ctx.quadraticCurveTo(x, y + h, x, y + h - radius);
    ctx.lineTo(x, y + radius);
    ctx.quadraticCurveTo(x, y, x + radius, y);
    ctx.closePath();
  },

  drawFovCone(ctx, originX, originY, rayLen, rad, fovHalf, options = {}) {
    const {
      fill = 'rgba(250,204,21,0.05)',
      edge = 'rgba(250,204,21,0.12)',
      edgeWidth = 1
    } = options;

    const leftX = originX + Math.cos(rad - fovHalf) * rayLen;
    const leftY = originY - Math.sin(rad - fovHalf) * rayLen;
    const rightX = originX + Math.cos(rad + fovHalf) * rayLen;
    const rightY = originY - Math.sin(rad + fovHalf) * rayLen;

    ctx.beginPath();
    ctx.moveTo(originX, originY);
    ctx.lineTo(leftX, leftY);
    ctx.lineTo(rightX, rightY);
    ctx.closePath();
    ctx.fillStyle = fill;
    ctx.fill();

    ctx.strokeStyle = edge;
    ctx.lineWidth = edgeWidth;
    ctx.beginPath();
    ctx.moveTo(originX, originY);
    ctx.lineTo(leftX, leftY);
    ctx.moveTo(originX, originY);
    ctx.lineTo(rightX, rightY);
    ctx.stroke();
  },

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
  },

  stopGraphAnimation() {
    if (this.graphAnimationId) {
      cancelAnimationFrame(this.graphAnimationId);
      this.graphAnimationId = null;
    }
  },

  updateGraphData(presence, targetCount = 0) {
    this.graphData.push({ timestamp: Date.now(), presence: presence ? 1 : 0, targets: targetCount });
    if (this.graphData.length > this.maxGraphPoints) this.graphData.shift();
    if (this.state.pageVisible) {
      this.drawRealtimeGraph();
    } else {
      this.state.pendingVisualRefresh = true;
    }
  },

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
  },

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
  },

};
