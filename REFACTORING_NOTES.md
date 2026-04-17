# Arris Cable Modem Stats - Multi-Modem Refactoring

## Overview

The application has been refactored to use a **class-based interface pattern** for multi-modem support. This replaces the previous scattered function-based approach with a clean, extensible architecture that unifies HTML-scraping modems (SB6183, SB8200, T25) with the API-based S33 modem.

## Architecture

### Abstract Interface (`src/modem_interface.py`)

All modem implementations inherit from `ModemInterface` and must implement three core methods:

```python
class ModemInterface(ABC):
    def authenticate(self, config: Dict, session: Session) -> bool:
        """Authenticate with the modem and store credentials internally."""
        pass

    def fetch_data(self, config: Dict, session: Session) -> RawData:
        """Fetch raw data from the modem (HTML string or JSON dict)."""
        pass

    def parse_data(self, raw_data: RawData) -> Dict[str, List]:
        """Parse raw data into standardized stats dict."""
        pass

    def get_config_keys(self) -> List[str]:
        """Return list of config keys required by this modem."""
        pass
```

### Modem Registry (`src/modem_registry.py`)

A central registry maps modem model names to their classes:

```python
modem = get_modem_instance('sb8200')  # Returns SB8200Modem instance
supported = get_supported_models()    # Returns ['s33', 'sb6183', 'sb8200', 't25']
```

### Modem Implementations

Each modem is now a class that manages its own:
- **Authentication** - Handles credentials, tokens, protocol details
- **Data Fetching** - Retrieves HTML or JSON from the modem
- **Parsing** - Converts raw data to standardized stats format

**Implemented Modems:**
- `SB6183Modem` - Stateless, no authentication required
- `SB8200Modem` - Stores token internally, injects into URL
- `T25Modem` - Handles meta-refresh redirects, form-based auth
- `S33Modem` - JSON API with HNAP/HMAC-MD5 authentication

## Main Loop Simplification

### Before (Function-Based)
```python
# Dynamic imports
module = __import__('arris_stats_' + model)
parse_func = getattr(module, 'parse_html_' + model)
token_func = getattr(module, 'get_token_' + model)

# Scattered logic
token = get_token(config, session)
html = get_html(config, token, session)
stats = parse_func(html)
```

### After (Class-Based)
```python
# Single factory call
modem = get_modem_instance(config['modem_model'])

# Uniform interface
modem.authenticate(config, session)
raw_data = modem.fetch_data(config, session)
stats = modem.parse_data(raw_data)
```

## Configuration

### Backward Compatibility

Old config format with `modem_ip` is automatically detected and normalized. For S33:
- If `modem_model = s33` and only `modem_url` is set, the IP is extracted automatically
- Old config files continue to work without changes

### New Configuration Keys

Added support for:
- `modem_ip` - IP address for S33 and other API-based modems
- `request_timeout` - HTTP request timeout (default: 10 seconds)

Example config for S33:
```ini
modem_model = s33
modem_ip = 192.168.100.1
modem_username = admin
modem_password = mypassword
modem_verify_ssl = False
request_timeout = 10
```

Example config for SB8200:
```ini
modem_model = sb8200
modem_url = https://192.168.100.1/cmconnectionstatus.html
modem_username = admin
modem_password = mypassword
modem_verify_ssl = False
```

## Adding New Modems

To add a new modem model:

1. Create `src/arris_stats_youmodel.py`:
```python
from src.modem_interface import ModemInterface

class YourModem(ModemInterface):
    def get_config_keys(self):
        return ['modem_url', 'modem_username', 'modem_password', 'modem_verify_ssl']

    def authenticate(self, config, session):
        # Your auth logic
        return True

    def fetch_data(self, config, session):
        # Your data fetching logic
        return raw_data

    def parse_data(self, raw_data):
        # Your parsing logic
        return {'downstream': [...], 'upstream': [...]}

# Register it
from src.modem_registry import register_modem
register_modem('yourmodel', YourModem)
```

2. Update tests with mock data:
   - `tests/mockups/yourmodel.html`
   - `tests/mockups/yourmodel.json`
   - Add `parse_html_yourmodel()` function for test compatibility

3. That's it! The modem will be automatically discovered and available.

## Backward Compatibility

- ✅ All old config files work unchanged
- ✅ Legacy functions (e.g., `parse_html_sb8200()`) retained for backward compatibility
- ✅ All existing test mocks and test suite still pass
- ✅ Authentication configuration auto-detected based on modem model

## Testing

All modems can be tested independently:

```python
# Unit test example
modem = SB8200Modem()
with open('tests/mockups/sb8200.html') as f:
    html = f.read()
stats = modem.parse_data(html)
assert 'downstream' in stats
assert 'upstream' in stats
```

## Migration from Old S33 Implementation

If you were previously using the separate S33 implementation:

**Before:**
```python
credential = get_credential(config)
json_data = get_json(config, credential)
stats = parse_json(json_data)
```

**After (same interface as other modems):**
```python
modem = get_modem_instance('s33')
modem.authenticate(config, session)
json_data = modem.fetch_data(config, session)
stats = modem.parse_data(json_data)
```

The main loop handles this automatically.

## File Changes Summary

### New Files
- `src/modem_interface.py` - Abstract base class
- `src/modem_registry.py` - Registry and factory
- `tests/mockups/s33.json` - S33 mock API response

### Modified Files
- `src/arris_stats.py` - Main loop refactored to use modem classes
- `src/arris_stats_sb6183.py` - Converted to SB6183Modem class
- `src/arris_stats_sb8200.py` - Converted to SB8200Modem class
- `src/arris_stats_t25.py` - Converted to T25Modem class
- `src/arris_stats_s33.py` - Converted to S33Modem class
- `src/config.ini.example` - Added modem_ip and request_timeout
- `Dockerfile` - Added modem_ip and request_timeout ENV vars
- `tests/mockups/s33.html` - Created for test compatibility

### Unchanged
- All destination handlers (InfluxDB, AWS Timestream, Splunk, etc.)
- Error handling and logging mechanisms
- Configuration file parsing and validation
- Environment variable support

## Verification Checklist

- [x] All modem classes implement ModemInterface correctly
- [x] Registry contains all four modems (SB6183, SB8200, T25, S33)
- [x] Main loop uses modem factory pattern
- [x] S33 JSON API parsing works with mock data
- [x] Backward compatibility: old configs detected and normalized
- [x] Legacy functions maintained for test suite compatibility
- [x] Config defaults updated with new parameters
- [x] Test mock files created for S33
