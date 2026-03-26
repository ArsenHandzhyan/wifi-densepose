// API Configuration for WiFi-DensePose UI

export const API_CONFIG = {
  BASE_URL: 'https://wifi-densepose-qtgc.onrender.com',  // Render backend
  LOCAL_RUNTIME_URL: 'http://127.0.0.1:8000', // Canonical local operator runtime
  LOCAL_UI_URL: 'http://127.0.0.1:3000', // Canonical local CSI operator UI / forensic server
  API_VERSION: '/api/v1',
  WS_PREFIX: 'ws://',
  WSS_PREFIX: 'wss://',
  
  // Mock server configuration (only for testing)
  MOCK_SERVER: {
    ENABLED: false,  // Set to true only for testing without backend
    AUTO_DETECT: false,  // Disabled: always use real backend in local FP2 mode
  },
  
  // API Endpoints
  ENDPOINTS: {
    // Root & Info
    ROOT: '/',
    INFO: '/api/v1/info',
    STATUS: '/api/v1/status',
    METRICS: '/api/v1/metrics',
    
    // Health
    HEALTH: {
      SYSTEM: '/health/health',
      READY: '/health/ready',
      LIVE: '/health/live',
      METRICS: '/health/metrics',
      VERSION: '/health/version'
    },
    
    // Pose
    POSE: {
      CURRENT: '/api/v1/pose/current',
      ANALYZE: '/api/v1/pose/analyze',
      ZONE_OCCUPANCY: '/api/v1/pose/zones/{zone_id}/occupancy',
      ZONES_SUMMARY: '/api/v1/pose/zones/summary',
      HISTORICAL: '/api/v1/pose/historical',
      ACTIVITIES: '/api/v1/pose/activities',
      CALIBRATE: '/api/v1/pose/calibrate',
      CALIBRATION_STATUS: '/api/v1/pose/calibration/status',
      STATS: '/api/v1/pose/stats'
    },

    // CSI runtime
    CSI: {
      STATUS: '/api/v1/csi/status',
      MODELS: '/api/v1/csi/models',
      MODEL_SELECT: '/api/v1/csi/model/select',
      ZONE: {
        STATUS: '/api/v1/csi/zone/status',
        START: '/api/v1/csi/zone/calibrate/start',
        STOP: '/api/v1/csi/zone/calibrate/stop',
        FIT: '/api/v1/csi/zone/calibrate/fit',
        RESET: '/api/v1/csi/zone/calibrate/reset'
      },
      FEWSHOT: {
        STATUS: '/api/v1/csi/fewshot/status',
        START: '/api/v1/csi/fewshot/session/start',
        STEP_START: '/api/v1/csi/fewshot/session/step/start',
        STEP_COMPLETE: '/api/v1/csi/fewshot/session/step/complete',
        FINALIZE: '/api/v1/csi/fewshot/session/finalize',
        RESET: '/api/v1/csi/fewshot/session/reset'
      },
      TTS: {
        STATUS: '/api/v1/csi/tts/status',
        SPEAK: '/api/v1/csi/tts/speak',
        STOP: '/api/v1/csi/tts/stop'
      },
      RECORD: {
        PREFLIGHT: '/api/v1/csi/record/preflight',
        START: '/api/v1/csi/record/start',
        STOP: '/api/v1/csi/record/stop',
        STATUS: '/api/v1/csi/record/status'
      }
    },
    
    // Streaming
    STREAM: {
      STATUS: '/api/v1/stream/status',
      START: '/api/v1/stream/start',
      STOP: '/api/v1/stream/stop',
      CLIENTS: '/api/v1/stream/clients',
      DISCONNECT_CLIENT: '/api/v1/stream/clients/{client_id}',
      BROADCAST: '/api/v1/stream/broadcast',
      METRICS: '/api/v1/stream/metrics',
      // WebSocket endpoints
      WS_POSE: '/api/v1/stream/pose',
      WS_EVENTS: '/api/v1/stream/events'
    },

    // FP2
    FP2: {
      STATUS: '/api/v1/fp2/status',
      CURRENT: '/api/v1/fp2/current',
      ENTITIES: '/api/v1/fp2/entities',
      RECOMMENDED: '/api/v1/fp2/recommended-entity',
      WS: '/api/v1/fp2/ws'
    },
    
    // Development (only in dev mode)
    DEV: {
      CONFIG: '/api/v1/dev/config',
      RESET: '/api/v1/dev/reset'
    }
  },
  
  // Default request options
  DEFAULT_HEADERS: {
    'Content-Type': 'application/json',
    'Accept': 'application/json'
  },
  
  // Rate limiting
  RATE_LIMITS: {
    REQUESTS_PER_MINUTE: 60,
    BURST_LIMIT: 10
  },
  
  // WebSocket configuration
  WS_CONFIG: {
    RECONNECT_DELAY: 5000,
    MAX_RECONNECT_ATTEMPTS: 5,
    PING_INTERVAL: 30000,
    MESSAGE_TIMEOUT: 10000
  }
};

// Helper function to build API URLs
export function buildApiUrl(endpoint, params = {}) {
  let url = `${API_CONFIG.BASE_URL}${endpoint}`;
  
  // Replace path parameters
  Object.keys(params).forEach(key => {
    if (url.includes(`{${key}}`)) {
      url = url.replace(`{${key}}`, params[key]);
      delete params[key];
    }
  });
  
  // Add query parameters
  const queryParams = new URLSearchParams(params);
  if (queryParams.toString()) {
    url += `?${queryParams.toString()}`;
  }
  
  return url;
}

// Helper function to build WebSocket URLs
export function buildWsUrl(endpoint, params = {}) {
  const baseUrl = API_CONFIG.BASE_URL;
  const isHttps = baseUrl.startsWith('https://');
  const protocol = isHttps ? API_CONFIG.WSS_PREFIX : API_CONFIG.WS_PREFIX;
  const host = baseUrl.replace(/^https?:\/\//, '');
  let url = `${protocol}${host}${endpoint}`;
  
  // Add query parameters
  const queryParams = new URLSearchParams(params);
  if (queryParams.toString()) {
    url += `?${queryParams.toString()}`;
  }
  
  return url;
}
