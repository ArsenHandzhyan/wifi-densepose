# FP2 Movement Event Codes Reference

## Quick Reference Table

| Code | Label | Description | Typical Scenario |
|------|-------|-------------|------------------|
| 0 | No event | No movement detected | Empty room, no presence |
| 1 | Static presence | Person present but motionless | Sitting, sleeping, working at desk |
| 2 | Micro-movement | Very small movements detected | Typing, reading, phone use |
| 3 | Significant movement | Clear body movement | Walking in place, gesturing |
| 4 | Large movement | Major position change | Quick walking, running |
| 5 | Approaching | Moving toward sensor | Walking toward FP2 device |
| 6 | Departing | Moving away from sensor | Walking away from FP2 device |
| 7 | Moving | General movement detected | Lateral movement across zones |
| 8 | Static after movement | Recently stopped moving | Sat down after walking |
| 9 | Entering zone | Crossed into monitored zone | Stepped into detection area |
| 10 | Leaving zone | Exited monitored zone | Stepped out of detection area |

## Fall State Codes

| Code | Label | Action Required |
|------|-------|-----------------|
| 0 | No fall detected | Normal operation |
| 1 | Possible fall | Monitor situation |
| 2 | Fall detected | Immediate attention needed |

## Resource IDs

The following Aqara FP2 resource IDs are relevant for movement detection:

- **13.27.85** - Movement Event (codes 0-10)
- **4.31.85** - Fall State (codes 0-2)
- **3.51.85** - Presence (binary: 0 or 1)
- **4.22.700** - Coordinates payload (JSON array of targets)

## Usage Examples

### Interpreting Live Events

```
Movement event Code 7 → "Moving (Code 7)"
Movement event Code 6 → "Departing (Code 6)"
Movement event Code 1 → "Static presence (Code 1)"
```

### Coordinate Stream Status

- **LIVE**: Coordinates updating every <2.5s (active movement)
- **REPEATING**: Same coordinates for 2.5-10s (static presence, normal)
- **SLOW**: Coordinates stale 10-60s (possible connection issue)
- **STALE**: No update >60s (sensor offline or cloud issue)

### Typical Event Sequences

**Person enters and sits:**
1. `Code 9` - Entering zone
2. `Code 7` - Moving (walking to seat)
3. `Code 3` - Significant movement (sitting down)
4. `Code 1` - Static presence (seated, working)
5. `Code 2` - Micro-movement (typing)
6. `Code 6` - Departing (standing up)
7. `Code 10` - Leaving zone

**Person walks past:**
1. `Code 9` - Entering zone
2. `Code 7` - Moving (walking through)
3. `Code 5` - Approaching (getting closer to sensor)
4. `Code 6` - Departing (moving away)
5. `Code 10` - Leaving zone

## Integration Notes

### Cloud API Behavior

The Aqara Cloud API (`open-ger.aqara.com`) provides these codes via resource `13.27.85`. The codes are:

- **Reliable**: Consistently reported across polling cycles
- **Timestamped**: Each update includes device timestamp
- **Complementary**: Work alongside coordinate data from `4.22.700`

### Best Practices

1. **Don't rely solely on codes**: Combine with presence, coordinates, and zone data
2. **Expect repetition**: Cloud API may repeat same code during static periods
3. **Monitor transitions**: Code changes are more meaningful than absolute values
4. **Consider context**: Code 1 (static) + coordinates = seated person; Code 1 alone = possible false positive

### Alert Configuration Recommendations

For safety monitoring:
- Monitor **Fall State** codes (4.31.85)
- Set alerts for Code 2 (Possible fall) and Code 2 (Fall detected)
- Combine with prolonged static presence (>10 min) for wellness checks

For occupancy analytics:
- Log **Movement Event** transitions
- Track time-of-day patterns
- Count unique enter/leave cycles per day

## Troubleshooting

### Issue: Only seeing Code 0 or Code 1
**Cause**: Person is stationary or micro-movements below detection threshold
**Solution**: Check if presence flag is active; verify sensor angle and mounting height

### Issue: Rapid code oscillation (6↔7, 5↔6)
**Cause**: Person at edge of detection zone or moving erratically
**Solution**: Verify zone configuration; check for environmental interference

### Issue: Codes don't match observed behavior
**Cause**: Cloud API latency or temporary synchronization issue
**Solution**: Check coordinate stream status; verify device timestamp freshness

## Related Documentation

- [FP2 Telemetry Console Update](./FP2_TELEMETRY_CONSOLE_UPDATE_2026-03-07.md)
- [FP2 Runtime Status](./FP2_RUNTIME_STATUS_2026-03-07.md)
- Aqara Open API Documentation (European region: `open-ger.aqara.com`)
