# 🔧 Aqara FP2 API Troubleshooting Report

**Date**: 2026-03-06  
**Status**: ONGOING - API Error 302  

---

## 📊 Summary

Successfully installed and configured Aqara FP2 Cloud integration for Home Assistant, but **Aqara Cloud API returns error 302 "Missing parameter Appid"** despite multiple fix attempts.

---

## ✅ What Works

1. **Integration Installed** ✅
   - Custom component `aqara_fp2` created
   - Loaded successfully in Home Assistant
   - Version: 1.0.0

2. **Device Configured** ✅
   - Device ID: `54EF4479E003`
   - MAC: `54:EF:44:79:E0:03`
   - IP: `192.168.1.52`
   - Region: Europe (Germany)

3. **Entities Created** ✅
   - `binary_sensor.aqara_fp2` - Occupancy
   - `sensor.aqara_fp2_light_level` - Light level
   - `sensor.aqara_fp2_distance` - Distance

4. **Credentials Saved** ✅
   - All credentials in `.env` file
   - Email: arsenhandzan442@gmail.com
   - Access Token valid until: 2026-03-11

---

## ❌ Current Issue

**Error**: `302 - Missing parameter Appid`

Aqara Cloud API rejects all requests with this error, even though:
- ✅ AppID is passed in URL query string
- ✅ AppID is passed as HTTP header
- ✅ All required parameters are included
- ✅ Tokens are valid (not expired)

---

## 🔍 Attempts to Fix

### Attempt 1: Add Appid Header
```python
headers = {
    "Content-Type": "application/json",
    "Accesstoken": access_token,
    "Appid": app_id,  # Added as header
}
```
**Result**: ❌ Still error 302

### Attempt 2: Manual URL Query String
```python
query_string = f"appid={app_id}&keyid={key_id}&nonce={nonce}&time={timestamp}&sign={sign}"
full_url = f"{base_url}?{query_string}"
```
**Result**: ❌ Still error 302

### Attempt 3: Multiple Intent Formats
Tried different intent names:
- `config.device.getState`
- `device.getState`
- `getDeviceState`
- `Config.device.getState`

**Result**: ❌ All failed with error 302

### Attempt 4: Parameters in Request Body
```python
body_payload = {
    "appid": app_id,
    "keyid": key_id,
    "nonce": nonce,
    "time": timestamp,
    "sign": sign,
    "intent": intent,
    "data": data,
}
```
**Result**: ❌ Still error 302

---

## 🎯 Possible Root Causes

1. **Tokens Expired/Invalid** ❓
   - Access Token expires: 2026-03-11
   - May need refresh or re-authentication

2. **API Format Changed** ❓
   - Aqara may have updated their API requirements
   - New authentication method required?

3. **Wrong App Credentials** ❓
   - Using DEMO APPLICATION credentials
   - May need production app credentials

4. **Regional API Issue** ❓
   - Europe region (open-ger.aqara.com)
   - Server-side problem?

---

## 📁 Files Modified

- `custom_components/aqara_fp2/binary_sensor.py` - Multiple API request formats
- `custom_components/aqara_fp2/const.py` - SCAN_INTERVAL as timedelta
- `custom_components/aqara_fp2/config_flow.py` - Fixed OptionsFlowHandler
- `.env` - All credentials saved
- `scripts/aqara_login.py` - Token refresh script
- `scripts/refresh_aqara_tokens.py` - Auto-update tokens

---

## 🚀 Next Steps

### Option 1: Refresh Tokens
Run token refresh script when Aqara API is working:
```bash
python3 scripts/refresh_aqara_tokens.py
```

### Option 2: Wait for Aqara
Monitor Aqara Cloud API status and try again later

### Option 3: Alternative Integration
Use HomeKit Controller instead of Cloud API (requires device reset)

---

## 📞 Support Resources

- Aqara Dev Platform: https://open.aqara.com/
- API Documentation: https://open.aqara.com/docs/
- Home Assistant Community: https://community.home-assistant.io/

---

## 📝 Technical Details

### Request Format (Format 1)
```
POST https://open-ger.aqara.com/v3.0/open/api?appid=XXX&keyid=XXX&nonce=XXX&time=XXX&sign=XXX
Headers:
  - Content-Type: application/json
  - Accesstoken: XXX
  - Appid: XXX
Body:
  {
    "intent": "config.device.getState",
    "data": {"did": "54EF4479E003"}
  }
```

### Response (Error)
```json
{
  "code": 302,
  "requestId": "...",
  "message": "Request failed. Please try again.",
  "messageDetail": "Missing parameter Appid"
}
```

---

**Current Status**: Integration ready, waiting for API fix  
**Last Update**: 2026-03-06 00:38 UTC
