# Diagnostic Tools Migration

## Old Approach (Deprecated)

Previously, diagnostics were split across three separate scripts:
- `gps_healthcheck.py` — Quick 2-second check
- `gps_diagnostic.py` — Comprehensive 30-second test  
- `gps_monitor.py` — Real-time satellite monitor

Each required a separate command and context switch.

## New Unified Approach ✓

**All diagnostics are now in one tool:** `gps_diagnostics.py`

```bash
python3 gps_diagnostics.py
```

Then select which test to run from the menu:
1. Quick Health Check (2 seconds)
2. Comprehensive Diagnostics (30 seconds)
3. Satellite Monitor (continuous)
4. All Tests (sequential)
0. Exit

## Benefits

✓ **Single command** — No need to remember multiple script names  
✓ **Menu-driven** — Clear choices and descriptions  
✓ **Consolidated** — All diagnostics in one place  
✓ **Professional UI** — ASCII art menu and formatted output  
✓ **Sequential running** — Option to run all tests at once  

## Migration Guide

### Before (old way)
```bash
# Check if system ready
python3 gps_healthcheck.py

# Run comprehensive test
python3 gps_diagnostic.py

# Monitor satellites
python3 gps_monitor.py
```

### After (new way)
```bash
# Everything in one menu
python3 gps_diagnostics.py
```

## File Status

| File | Status | Migration |
|------|--------|-----------|
| `gps_healthcheck.py` | Deprecated | Functionality merged into `gps_diagnostics.py` option 1 |
| `gps_diagnostic.py` | Deprecated | Functionality merged into `gps_diagnostics.py` option 2 |
| `gps_monitor.py` | Deprecated | Functionality merged into `gps_diagnostics.py` option 3 |
| `gps_diagnostics.py` | ✓ Active | New unified diagnostic tool |

## Backward Compatibility

The old scripts still exist and work, but `gps_diagnostics.py` is recommended for:
- Easier navigation
- Better organization
- Single entry point for all diagnostics
- Cleaner output formatting

You can keep using the old scripts if preferred, but `gps_diagnostics.py` is the new standard.

## Future Development

When adding new GPS diagnostics:
1. Add the test function to `gps_diagnostics.py`
2. Add menu option
3. Update menu display
4. Update this migration guide

No need to create new standalone scripts.
