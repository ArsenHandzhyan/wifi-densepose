// FP2 Service for WiFi-DensePose UI

import { API_CONFIG } from '../config/api.config.js';
import { wsService } from './websocket.service.js';

export class FP2Service {
  constructor() {
    this.streamConnection = null;
    this.subscribers = [];
    this.connectionState = 'disconnected';
    this.lastData = null;
    this.lastError = null;
    const origin =
      typeof window !== 'undefined' &&
      window.location &&
      window.location.origin &&
      window.location.origin !== 'null'
        ? window.location.origin
        : null;

    this.baseUrls = [
      API_CONFIG.BASE_URL
    ].filter(Boolean);
    this.selectedEntityId = this.readSelectedEntityId();
  }

  getStorage() {
    if (typeof localStorage !== 'undefined' && typeof localStorage?.getItem === 'function') {
      return localStorage;
    }
    return null;
  }

  readSelectedEntityId() {
    const storage = this.getStorage();
    return storage ? (storage.getItem('fp2_selected_entity_id') || null) : null;
  }

  extractErrorMessage(payload) {
    if (!payload) {
      return null;
    }

    if (typeof payload === 'string') {
      return payload;
    }

    if (Array.isArray(payload)) {
      for (const item of payload) {
        const message = this.extractErrorMessage(item);
        if (message) {
          return message;
        }
      }
      return null;
    }

    if (typeof payload !== 'object') {
      return null;
    }

    for (const key of ['message', 'detail', 'error', 'title']) {
      const message = this.extractErrorMessage(payload[key]);
      if (message) {
        return message;
      }
    }

    return null;
  }

  buildHttpError(response, payload) {
    const fallbackMessage = `HTTP ${response.status}: ${response.statusText}`;
    const error = new Error(this.extractErrorMessage(payload) || fallbackMessage);
    error.name = 'Fp2ApiError';
    error.status = response.status;
    error.statusText = response.statusText;
    error.payload = payload;
    return error;
  }

  buildStreamError(payload) {
    const error = new Error(payload?.message || 'FP2 stream error');
    error.name = 'Fp2StreamError';
    error.payload = payload;
    if (payload?.error === 'fp2_upstream_unavailable') {
      error.status = 503;
    }
    return error;
  }

  extractErrorDetail(error) {
    if (error?.payload && typeof error.payload === 'object' && typeof error.payload.error === 'string') {
      return error.payload;
    }
    return error?.payload?.error?.message
      || error?.payload?.detail
      || error?.payload?.error
      || error?.payload
      || null;
  }

  isUpstreamUnavailableError(error) {
    const detail = this.extractErrorDetail(error);
    return Boolean(
      detail
      && (
        detail === 'fp2_upstream_unavailable'
        || detail.error === 'fp2_upstream_unavailable'
      )
    );
  }

  buildUnavailablePoseData(detail = {}, context = 'current') {
    const entityId = detail?.entity_id || this.selectedEntityId || null;
    return {
      timestamp: new Date().toISOString(),
      frame_id: 'fp2_upstream_unavailable',
      persons: [],
      zone_summary: {},
      processing_time_ms: 0,
      metadata: {
        source: 'fp2',
        presence: null,
        fp2_state: 'upstream_unavailable',
        upstream_available: false,
        stale: false,
        unavailable: true,
        fallback_context: context,
        entity_id: entityId,
        last_error: detail?.last_error || null,
        message: detail?.message || 'FP2 upstream unavailable',
        cached_snapshot_available: Boolean(detail?.cached_snapshot_available),
      }
    };
  }

  async requestWithFallback(path) {
    let lastError = null;
    for (const baseUrl of this.baseUrls) {
      try {
        const response = await fetch(`${baseUrl}${path}`, {
          method: 'GET',
          headers: {
            'Accept': 'application/json'
          }
        });
        if (!response.ok) {
          const payload = await response.json().catch(() => ({
            message: `HTTP ${response.status}: ${response.statusText}`
          }));
          throw this.buildHttpError(response, payload);
        }
        return await response.json();
      } catch (error) {
        lastError = error;
      }
    }
    throw lastError || new Error('FP2 request failed');
  }

  async getStatus() {
    return this.requestWithFallback(API_CONFIG.ENDPOINTS.FP2.STATUS);
  }

  async getCurrent() {
    const query = this.selectedEntityId
      ? `?entity_id=${encodeURIComponent(this.selectedEntityId)}`
      : '';
    try {
      const data = await this.requestWithFallback(`${API_CONFIG.ENDPOINTS.FP2.CURRENT}${query}`);
      this.lastData = data;
      this.lastError = null;
      return data;
    } catch (error) {
      this.lastError = error;
      if (this.isUpstreamUnavailableError(error)) {
        const unavailableData = this.buildUnavailablePoseData(
          this.extractErrorDetail(error),
          'current'
        );
        this.lastData = unavailableData;
        return unavailableData;
      }
      throw error;
    }
  }

  async getEntities() {
    return this.requestWithFallback(API_CONFIG.ENDPOINTS.FP2.ENTITIES);
  }

  async getRecommendedEntity() {
    return this.requestWithFallback(API_CONFIG.ENDPOINTS.FP2.RECOMMENDED);
  }

  setSelectedEntity(entityId) {
    this.selectedEntityId = entityId || null;
    const storage = this.getStorage();
    if (!storage) {
      return;
    }
    if (this.selectedEntityId) {
      storage.setItem('fp2_selected_entity_id', this.selectedEntityId);
    } else {
      storage.removeItem('fp2_selected_entity_id');
    }
  }

  getSelectedEntity() {
    return this.selectedEntityId;
  }

  async startStream() {
    if (this.streamConnection) {
      return this.streamConnection;
    }

    this.connectionState = 'connecting';
    this.notify({ type: 'connection_state', state: this.connectionState });

    const wsPath = this.selectedEntityId
      ? `${API_CONFIG.ENDPOINTS.FP2.WS}?entity_id=${encodeURIComponent(this.selectedEntityId)}`
      : API_CONFIG.ENDPOINTS.FP2.WS;

    this.streamConnection = await wsService.connect(
      wsPath,
      {},
      {
        onOpen: () => {
          this.connectionState = 'connected';
          this.lastError = null;
          this.notify({ type: 'connection_state', state: this.connectionState });
        },
        onMessage: (data) => {
          if (data?.type === 'error') {
            const error = this.buildStreamError(data);
            this.lastError = error;
            this.connectionState = 'error';
            this.notify({ type: 'connection_state', state: this.connectionState, error });
            if (this.isUpstreamUnavailableError(error)) {
              const unavailableData = this.buildUnavailablePoseData(data, 'stream');
              this.lastData = unavailableData;
              this.notify({ type: 'data', payload: unavailableData });
              return;
            }
            this.notify({ type: 'error', error, payload: data });
            return;
          }
          this.lastData = data;
          this.lastError = null;
          this.notify({ type: 'data', payload: data });
        },
        onError: (error) => {
          this.lastError = error;
          this.connectionState = 'error';
          this.notify({ type: 'connection_state', state: this.connectionState, error });
        },
        onClose: () => {
          this.connectionState = 'disconnected';
          this.streamConnection = null;
          this.notify({ type: 'connection_state', state: this.connectionState });
        }
      }
    );

    return this.streamConnection;
  }

  stopStream() {
    if (!this.streamConnection) {
      return;
    }
    wsService.disconnect(this.streamConnection);
    this.streamConnection = null;
    this.connectionState = 'disconnected';
    this.notify({ type: 'connection_state', state: this.connectionState });
  }

  subscribe(callback) {
    this.subscribers.push(callback);
    return () => {
      const index = this.subscribers.indexOf(callback);
      if (index > -1) {
        this.subscribers.splice(index, 1);
      }
    };
  }

  notify(message) {
    this.subscribers.forEach((subscriber) => {
      try {
        subscriber(message);
      } catch (error) {
        console.error('FP2 subscriber error:', error);
      }
    });
  }
}

export const fp2Service = new FP2Service();
