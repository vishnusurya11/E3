# YouTube Token Management Improvements

## Overview
Enhanced YouTube OAuth token management system to handle token expiration and renewal automatically.

## Problem Solved
- **Original Issue**: YouTube credentials expire, causing uploads to fail with "Token has been expired or revoked" error
- **Root Cause**: Access tokens expire after 1 hour, refresh tokens can expire/be revoked

## Solution Implemented

### 1. Enhanced Token Validation
- Added `validate_youtube_credentials()` function with timezone-aware expiry checking
- Pre-flight validation before all YouTube operations
- Warnings when tokens expire within 30 minutes
- Detailed status reporting

### 2. Automatic Retry Logic
- Maximum 2 retry attempts for credential acquisition
- First attempt uses existing credentials with refresh
- Second attempt forces full re-authentication
- Comprehensive error handling for various failure scenarios

### 3. Improved Error Detection
- Better handling of `invalid_grant` errors
- Detection of expired vs revoked tokens
- Clear user messaging for different error types

### 4. Token Management Utilities
- **`check_youtube_token_status()`**: Check credential status without operations
- **`force_youtube_reauth()`**: Clear credentials and force re-authentication
- **`validate_youtube_credentials_standalone()`**: Detailed credential validation report

### 5. Management CLI
- **`youtube_token_manager.py`**: Simple command-line utility
  - `python youtube_token_manager.py status` - Check token status
  - `python youtube_token_manager.py validate` - Detailed validation report
  - `python youtube_token_manager.py reauth` - Force re-authentication

## Key Improvements in audiobook_helper.py

### Before
```python
credentials = get_youtube_credentials()
if not credentials:
    return False
```

### After
```python
max_retries = 2
for attempt in range(max_retries):
    credentials = get_youtube_credentials(force_refresh=attempt > 0)
    if credentials:
        is_valid, status_msg = validate_youtube_credentials(credentials)
        if is_valid:
            break
    # Retry with fresh authentication if failed
```

## YouTube Token Lifecycle Handling

### Access Tokens
- **Lifespan**: 1 hour
- **Handling**: Automatic refresh using refresh token
- **Validation**: Pre-operation expiry checking

### Refresh Tokens
- **Expiry Causes**:
  - 6+ months of inactivity
  - User revocation
  - Google security policies
  - 50+ tokens per OAuth client
- **Handling**: Automatic detection and full re-authentication flow

## Testing
- Comprehensive test suite (`test_youtube_credentials.py`)
- Validates missing, valid, expiring, and expired credential scenarios
- Production-tested with actual YouTube upload operations

## Usage Examples

### Check Current Status
```bash
python youtube_token_manager.py status
```

### Force Re-authentication
```bash
python youtube_token_manager.py reauth
```

### Detailed Validation
```bash
python youtube_token_manager.py validate
```

## Benefits
1. **Automatic Recovery**: YouTube uploads continue even when tokens expire
2. **Proactive Monitoring**: Early warnings before token expiration
3. **Better UX**: Clear error messages and guided re-authentication
4. **Reliability**: Retry logic handles transient failures
5. **Maintainability**: Standalone utilities for token management

## Files Modified
- `audiobook_agent/audiobook_helper.py`: Enhanced YouTube upload function
- `youtube_token_manager.py`: New management CLI
- `test_youtube_credentials.py`: Test suite

## Next Steps
- Monitor token refresh patterns in production
- Consider implementing automatic periodic token refresh
- Add token age tracking and rotation recommendations