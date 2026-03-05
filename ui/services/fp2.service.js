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
    this.selectedEntityId = localStorage.getItem('fp2_selected_entity_id') || null;
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
    const query = this.selectedEntityId
      ? `?entity_id=${encodeURIComponent(this.selectedEntityId)}`
      : '';
    const data = await this.requestWithFallback(`${API_CONFIG.ENDPOINTS.FP2.CURRENT}${query}`);
    this.lastData = data;
    return data;
  }

  async getEntities() {
    return this.requestWithFallback(API_CONFIG.ENDPOINTS.FP2.ENTITIES);
  }

  async getRecommendedEntity() {
    return this.requestWithFallback(API_CONFIG.ENDPOINTS.FP2.RECOMMENDED);
  }

  setSelectedEntity(entityId) {
    this.selectedEntityId = entityId || null;
    if (this.selectedEntityId) {
      localStorage.setItem('fp2_selected_entity_id', this.selectedEntityId);
    } else {
      localStorage.removeItem('fp2_selected_entity_id');
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
