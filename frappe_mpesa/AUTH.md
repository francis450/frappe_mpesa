# Mpesa Authentication Module

The authentication module (`frappe_mpesa.auth`) provides robust OAuth token management for the Safaricom Daraja API integration.

## Features

### 🔐 Automatic Token Management
- **Token Caching**: Access tokens are cached in Redis/memory for optimal performance
- **Auto-Refresh**: Tokens are automatically refreshed before expiration
- **Error Recovery**: Failed requests trigger automatic token refresh and retry

### ⚡ Performance Optimized
- **Smart Caching**: Tokens cached with 5-minute expiry buffer
- **Connection Pooling**: Reuses HTTP connections for better performance
- **Timeout Handling**: 30-second request timeouts prevent hanging

### 🛡️ Security Features
- **Secure Storage**: Sensitive credentials handled securely
- **Token Invalidation**: Manual and automatic token cleanup
- **Environment Isolation**: Separate tokens for Sandbox/Production

### 📊 Monitoring & Health Checks
- **Token Status**: Real-time token validity monitoring
- **Health Checks**: Scheduled authentication health monitoring
- **Error Logging**: Comprehensive error tracking and alerting

## Usage

### Basic Usage

```python
from frappe_mpesa.auth import mpesa_auth

# Get access token (automatically cached)
token = mpesa_auth.get_access_token()

# Get authenticated headers for API requests
headers = mpesa_auth.get_auth_headers()

# Test authentication
result = mpesa_auth.test_authentication()
```

### API Methods

#### `get_access_token(force_refresh=False)`
Returns a valid access token, using cache when possible.
- `force_refresh`: Force new token request ignoring cache

#### `get_auth_headers()`
Returns HTTP headers with Authorization token for API requests.

#### `test_authentication()`
Tests authentication and returns status information.

#### `get_token_status()`
Returns detailed information about cached token status.

#### `invalidate_token()`
Clears cached token (useful when credentials change).

### Whitelisted Methods

The following methods are available via Frappe's REST API:

- `frappe_mpesa.auth.get_access_token`
- `frappe_mpesa.auth.test_authentication`
- `frappe_mpesa.auth.get_token_status`
- `frappe_mpesa.auth.invalidate_token`

### JavaScript Integration

The Mpesa Settings form includes enhanced JavaScript functionality:

```javascript
// Test authentication
frappe.call({
    method: 'frappe_mpesa.auth.test_authentication',
    callback: function(r) {
        console.log('Auth result:', r.message);
    }
});

// Get token status
frappe.call({
    method: 'frappe_mpesa.auth.get_token_status',
    callback: function(r) {
        console.log('Token status:', r.message);
    }
});
```

## Scheduled Tasks

### Hourly Tasks
- **`monitor_auth_health`**: Monitors token status and logs health information
- **`refresh_token_if_needed`**: Proactively refreshes tokens before expiration

### Daily Tasks
- **`cleanup_auth_logs`**: Removes old authentication error logs

## Error Handling

The authentication module provides comprehensive error handling:

### Common Errors
- **Invalid Credentials**: Wrong Consumer Key/Secret
- **Network Issues**: Connection timeouts or failures
- **API Errors**: Safaricom API errors (rate limits, etc.)
- **Token Expiry**: Automatic refresh on 401 responses

### Error Recovery
- **Automatic Retry**: Failed requests automatically retry with fresh token
- **Graceful Degradation**: Clear error messages for end users
- **Logging**: All errors logged for debugging and monitoring

## Configuration

Authentication is configured through the Mpesa Settings doctype:

### Required Fields
- **Consumer Key**: API consumer key from Safaricom
- **Consumer Secret**: API consumer secret from Safaricom
- **Environment**: Sandbox or Production
- **Base URL**: API base URL (auto-set based on environment)

### Security Considerations
- Consumer Secret is stored as a password field
- Tokens are cached with appropriate expiry times
- Environment changes automatically invalidate cached tokens
- Credential changes automatically clear token cache

## Best Practices

### Performance
- Use the singleton `mpesa_auth` instance for consistency
- Let the module handle token caching automatically
- Don't manually manage tokens unless necessary

### Security
- Regularly rotate API credentials
- Monitor authentication logs for suspicious activity
- Use Production environment only with valid credentials

### Monitoring
- Check token status regularly in production
- Monitor scheduled task logs for authentication health
- Set up alerts for authentication failures

## Integration with Base API

The authentication module integrates seamlessly with the base API class:

```python
from frappe_mpesa.api import MpesaAPIBase

class MyMpesaAPI(MpesaAPIBase):
    def make_payment(self, data):
        # Headers with authentication automatically included
        return self.make_request('/payment/endpoint', data)
```

The base API class automatically:
- Includes authentication headers
- Handles 401 responses with token refresh
- Retries failed requests once after token refresh
- Logs all transactions for audit trail

## Troubleshooting

### Token Issues
1. **Token not cached**: Check if Mpesa integration is enabled
2. **Authentication fails**: Verify Consumer Key/Secret in settings
3. **401 errors**: Check if credentials are valid for the environment

### Performance Issues
1. **Slow requests**: Check network connectivity to Safaricom API
2. **Cache issues**: Restart Redis or clear cache manually
3. **Memory usage**: Monitor cache size and cleanup old tokens

### Environment Issues
1. **Wrong endpoint**: Verify environment setting matches credentials
2. **Sandbox vs Production**: Ensure credentials match environment
3. **URL issues**: Check base URL configuration