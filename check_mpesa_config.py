#!/usr/bin/env python3

import frappe
from frappe_mpesa.utils import get_mpesa_settings
from frappe_mpesa.auth import test_authentication, get_token_status

def check_mpesa_configuration():
    """Check M-Pesa configuration and test authentication"""
    print("=== M-Pesa Configuration Check ===\n")

    try:
        # 1. Check M-Pesa Settings
        print("1. Checking M-Pesa Settings...")
        settings = get_mpesa_settings()

        print(f"   Environment: {settings.environment}")
        print(f"   Is Enabled: {settings.is_enabled}")
        print(f"   Base URL: {settings.base_url}")
        print(f"   OAuth URL: {settings.oauth_url}")
        print(f"   Express URL: {settings.express_url}")
        print(f"   Consumer Key: {'✅ Set' if settings.consumer_key else '❌ Not Set'}")
        print(f"   Consumer Secret: {'✅ Set' if settings.consumer_secret else '❌ Not Set'}")
        print(f"   Shortcode: {settings.shortcode or 'Not Set'}")
        print(f"   Passkey: {'✅ Set' if settings.passkey else '❌ Not Set'}")

        if not settings.is_enabled:
            print("   ⚠️  WARNING: M-Pesa integration is DISABLED!")
            print("   Please enable it in M-Pesa Settings to proceed.")
            return False

        if not settings.consumer_key or not settings.consumer_secret:
            print("   ❌ ERROR: Consumer Key and/or Consumer Secret missing!")
            print("   Please configure your M-Pesa API credentials.")
            return False

        print("   ✅ Basic settings look good!")

    except Exception as e:
        print(f"   ❌ ERROR getting M-Pesa settings: {str(e)}")
        return False

    try:
        # 2. Test Authentication
        print("\n2. Testing M-Pesa Authentication...")
        result = test_authentication()

        if result.get('success'):
            print("   ✅ Authentication successful!")
            print(f"   Token preview: {result.get('token_preview', 'N/A')}")
        else:
            print(f"   ❌ Authentication failed!")
            print(f"   Error: {result.get('message', 'Unknown error')}")
            return False

    except Exception as e:
        print(f"   ❌ Authentication test error: {str(e)}")
        return False

    try:
        # 3. Check Token Status
        print("\n3. Checking Token Status...")
        status = get_token_status()

        if status.get('cached'):
            print(f"   Token cached: ✅ Yes")
            print(f"   Is valid: {'✅ Yes' if status.get('is_valid') else '❌ No'}")
            print(f"   Time remaining: {status.get('time_remaining_seconds', 0)} seconds")
            print(f"   Expires at: {status.get('expires_at', 'N/A')}")
        else:
            print(f"   Token cached: ❌ No")
            print(f"   Message: {status.get('message', 'N/A')}")

    except Exception as e:
        print(f"   ❌ Token status check error: {str(e)}")

    print("\n4. Checking Full API URL Construction...")
    try:
        base_url = settings.base_url or ""
        oauth_path = settings.oauth_url or ""
        full_url = settings.get_full_url(oauth_path) if hasattr(settings, 'get_full_url') else f"{base_url}{oauth_path}"
        print(f"   Full OAuth URL: {full_url}")

        # Check if URL looks correct
        if "sandbox.safaricom.co.ke" in full_url or "api.safaricom.co.ke" in full_url:
            print("   ✅ URL looks correct for Safaricom API")
        else:
            print(f"   ⚠️  WARNING: URL doesn't look like standard Safaricom endpoint")

    except Exception as e:
        print(f"   ❌ URL construction error: {str(e)}")

    print("\n=== Configuration Check Complete ===")
    return True

if __name__ == "__main__":
    check_mpesa_configuration()