// FP2 Service for WiFi-DensePose UI

import { API_CONFIG } from '../config/api.config.js';
import { wsService } from './websocket.service.js';

export class FP2Service {
  constructor() {
    this.streamConnection = null;
    this.subscribers = [];
    this.connectionState = 'disconnected';
    this.lastData = null;
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
    this.selectedEntityId = null;
    if (typeof window !== 'undefined' && window.localStorage) {
      window.localStorage.removeItem('fp2_selected_entity_id');
    }
  }

  async requestWithFallback(path, options = {}) {
    let lastError = null;
    for (const baseUrl of this.baseUrls) {
      try {
        const response = await fetch(`${baseUrl}${path}`, {
          method: options.method || 'GET',
          headers: {
            'Accept': 'application/json',
            ...(options.headers || {})
          },
          body: options.body
        });
        if (!response.ok) {
          throw new Error(`HTTP ${response.status}`);
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
    const data = await this.requestWithFallback(API_CONFIG.ENDPOINTS.FP2.CURRENT);
    this.lastData = data;
    return data;
  }

  async getLayoutState() {
    return this.requestWithFallback(API_CONFIG.ENDPOINTS.FP2.LAYOUT_STATE);
  }

  async saveLayoutState(payload, scope = null) {
    return this.requestWithFallback(API_CONFIG.ENDPOINTS.FP2.LAYOUT_STATE, {
      method: 'PUT',
      headers: {
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({
        payload,
        scope
      })
    });
  }

  async getEntities() {
    return this.requestWithFallback(API_CONFIG.ENDPOINTS.FP2.ENTITIES);
  }

  async getRecommendedEntity() {
    return this.requestWithFallback(API_CONFIG.ENDPOINTS.FP2.RECOMMENDED);
  }

  async writeCloudResource(resourceId, value, refreshState = true) {
    return this.requestWithFallback(API_CONFIG.ENDPOINTS.FP2.CLOUD_RESOURCE_WRITE, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({
        resource_id: resourceId,
        value,
        refresh_state: refreshState
      })
    });
  }

  async writeCloudResources(updates, refreshState = true) {
    const list = Array.isArray(updates) ? updates.filter(Boolean) : [];
    if (!list.length) {
      return null;
    }

    let lastResult = null;
    for (let index = 0; index < list.length; index += 1) {
      const update = list[index];
      lastResult = await this.writeCloudResource(
        update.resourceId,
        update.value,
        refreshState && index === list.length - 1
      );
    }

    return lastResult;
  }

  async enableRealtimeCoordinates() {
    return this.writeCloudResource('4.22.85', 1, true);
  }

  setSelectedEntity(entityId) {
    this.selectedEntityId = null;
    if (typeof window !== 'undefined' && window.localStorage) {
      localStorage.removeItem('fp2_selected_entity_id');
    }
  }

  getSelectedEntity() {
    return null;
  }

  async startStream() {
    if (this.streamConnection) {
      return this.streamConnection;
    }

    this.connectionState = 'connecting';
    this.notify({ type: 'connection_state', state: this.connectionState });

    this.streamConnection = await wsService.connect(
      API_CONFIG.ENDPOINTS.FP2.WS,
      {},
      {
        onOpen: () => {
          this.connectionState = 'connected';
          this.notify({ type: 'connection_state', state: this.connectionState });
        },
        onMessage: (data) => {
          this.lastData = data;
          this.notify({ type: 'data', payload: data });
        },
        onError: (error) => {
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
