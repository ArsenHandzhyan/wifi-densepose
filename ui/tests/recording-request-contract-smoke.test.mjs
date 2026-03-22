import test from 'node:test';
import assert from 'node:assert/strict';

import { CsiOperatorService } from '../services/csi-operator.service.js';
import { apiService } from '../services/api.service.js';

async function capturePreflightRequest(teacherSource) {
  const service = new CsiOperatorService();
  Object.assign(service.state.recording.teacherSource, teacherSource);

  const originalGet = apiService.get;
  let captured = null;

  apiService.get = async (endpoint, params) => {
    captured = { endpoint, params: { ...params } };
    return { ok: true, video: { available: true } };
  };

  try {
    const result = await service.runRecordingPreflight({
      force: false,
      checkVideoOverride: true,
    });
    assert.equal(result?.ok, true);
    return captured;
  } finally {
    apiService.get = originalGet;
  }
}

test('recording preflight sends explicit teacher contract for pixel_rtsp and mac_camera', async () => {
  const pixelRequest = await capturePreflightRequest({
    selectedKind: 'pixel_rtsp',
    pixelRtspUrl: 'rtsp://10.10.0.55:8554/live',
    pixelRtspName: 'Pixel Smoke',
  });

  assert.equal(pixelRequest.endpoint, '/api/v1/csi/record/preflight');
  assert.equal(pixelRequest.params.check_video, true);
  assert.equal(pixelRequest.params.video_required, true);
  assert.equal(pixelRequest.params.teacher_source_kind, 'pixel_rtsp');
  assert.equal(pixelRequest.params.teacher_source_url, 'rtsp://10.10.0.55:8554/live');
  assert.equal(pixelRequest.params.teacher_source_name, 'Pixel Smoke');
  assert.equal(pixelRequest.params.teacher_input_pixel_format, 'nv12');
  assert.ok(!('teacher_device' in pixelRequest.params));

  const macRequest = await capturePreflightRequest({
    selectedKind: 'mac_camera',
    macDevice: '0',
    macDeviceName: 'Камера MacBook Pro',
  });

  assert.equal(macRequest.endpoint, '/api/v1/csi/record/preflight');
  assert.equal(macRequest.params.check_video, true);
  assert.equal(macRequest.params.video_required, true);
  assert.equal(macRequest.params.teacher_source_kind, 'mac_camera');
  assert.equal(macRequest.params.teacher_device, '0');
  assert.equal(macRequest.params.teacher_device_name, 'Камера MacBook Pro');
  assert.equal(macRequest.params.teacher_source_name, 'Mac Camera');
  assert.equal(macRequest.params.teacher_input_pixel_format, 'nv12');
  assert.ok(!('teacher_source_url' in macRequest.params));
});
