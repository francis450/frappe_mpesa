# Copyright (c) 2025, Njoroge Francis and contributors
# For license information, please see license.txt

import frappe
from frappe import _
import requests
import base64
import json
from datetime import datetime, timedelta
from frappe.utils import now_datetime, get_datetime
from frappe_mpesa.utils import get_mpesa_settings


class MpesaAuth:
	"""Handle Mpesa API authentication and token management"""
	
	def __init__(self):
		self.settings = get_mpesa_settings()
		self.cache_key = "mpesa_access_token"
		self.token_expiry_buffer = 300  # 5 minutes buffer before token expires
		
	def get_access_token(self, force_refresh=False):
		"""Get valid access token with automatic refresh"""
		if not self.settings.is_enabled:
			frappe.throw(_("Mpesa integration is not enabled"))
			
		# Try to get cached token first
		if not force_refresh:
			cached_token = self._get_cached_token()
			if cached_token:
				return cached_token
				
		# Request new token
		return self._request_new_token()
	
	def _get_cached_token(self):
		"""Get token from cache if still valid"""
		try:
			cache_data = frappe.cache().get_value(self.cache_key)
			if not cache_data:
				return None
				
			token_data = json.loads(cache_data)
			token = token_data.get('access_token')
			expires_at = get_datetime(token_data.get('expires_at'))
			
			# Check if token is still valid (with buffer)
			current_time = now_datetime()
			if expires_at > current_time + timedelta(seconds=self.token_expiry_buffer):
				return token
				
		except (json.JSONDecodeError, TypeError, ValueError) as e:
			frappe.log_error(f"Error reading cached token: {str(e)}", "Mpesa Auth Cache")
			
		return None
	
	def _request_new_token(self):
		"""Request new access token from Safaricom API"""
		if not self.settings.consumer_key or not self.settings.consumer_secret:
			frappe.throw(_("Consumer Key and Consumer Secret are required for authentication"))
			
		# Create basic auth header
		auth_string = f"{self.settings.consumer_key}:{self.settings.get_password('consumer_secret')}"
		auth_bytes = auth_string.encode('ascii')
		auth_b64 = base64.b64encode(auth_bytes).decode('ascii')
		
		headers = {
			'Authorization': f'Basic {auth_b64}',
			'Content-Type': 'application/json'
		}
		
		url = self.settings.get_full_url(self.settings.oauth_url)
		
		try:
			response = requests.get(url, headers=headers, timeout=30)
			response.raise_for_status()
			
			result = response.json()
			access_token = result.get('access_token')
			expires_in = result.get('expires_in', 3600)  # Default to 1 hour
			
			if not access_token:
				frappe.throw(_("No access token received from Mpesa API"))
				
			# Cache the token
			self._cache_token(access_token, expires_in)
			
			frappe.logger().info("Successfully obtained new Mpesa access token")
			return access_token
			
		except requests.exceptions.Timeout:
			error_msg = _("Timeout while requesting access token from Mpesa API")
			frappe.log_error(error_msg, "Mpesa Auth Timeout")
			frappe.throw(error_msg)
			
		except requests.exceptions.ConnectionError:
			error_msg = _("Failed to connect to Mpesa authentication server")
			frappe.log_error(error_msg, "Mpesa Auth Connection Error")
			frappe.throw(error_msg)
			
		except requests.exceptions.HTTPError as e:
			try:
				error_response = e.response.json()
				error_code = error_response.get('error', 'unknown_error')
				error_description = error_response.get('error_description', str(e))
				error_msg = _("Authentication failed: {0} - {1}").format(error_code, error_description)
			except (json.JSONDecodeError, AttributeError):
				error_msg = _("HTTP Error {0}: {1}").format(e.response.status_code, e.response.text)
				
			frappe.log_error(f"Mpesa Auth HTTP Error: {error_msg}", "Mpesa Auth Error")
			frappe.throw(error_msg)
			
		except json.JSONDecodeError:
			error_msg = _("Invalid JSON response from Mpesa authentication server")
			frappe.log_error(error_msg, "Mpesa Auth JSON Error")
			frappe.throw(error_msg)
			
		except Exception as e:
			error_msg = _("Unexpected authentication error: {0}").format(str(e))
			frappe.log_error(f"Mpesa Auth Unexpected Error: {error_msg}", "Mpesa Auth Error")
			frappe.throw(error_msg)
	
	def _cache_token(self, access_token, expires_in):
		"""Cache the access token with expiry"""
		expires_at = now_datetime() + timedelta(seconds=int(expires_in))
		
		cache_data = {
			'access_token': access_token,
			'expires_at': expires_at.isoformat(),
			'cached_at': now_datetime().isoformat()
		}
		
		# Cache for the full expiry time
		frappe.cache().set_value(
			self.cache_key, 
			json.dumps(cache_data), 
			expires_in_sec=int(expires_in)
		)
	
	def invalidate_token(self):
		"""Invalidate cached token (useful for error scenarios)"""
		frappe.cache().delete_value(self.cache_key)
		frappe.logger().info("Mpesa access token cache invalidated")
	
	def get_auth_headers(self):
		"""Get headers with valid access token for API requests"""
		access_token = self.get_access_token()
		return {
			'Authorization': f'Bearer {access_token}',
			'Content-Type': 'application/json'
		}
	
	def test_authentication(self):
		"""Test authentication by requesting a token"""
		try:
			token = self.get_access_token(force_refresh=True)
			if token:
				return {
					'success': True,
					'message': _('Authentication successful'),
					'token_preview': f"{token[:10]}...{token[-10:]}" if len(token) > 20 else token
				}
		except Exception as e:
			return {
				'success': False,
				'message': str(e)
			}
	
	def get_token_status(self):
		"""Get current token status information"""
		try:
			cache_data = frappe.cache().get_value(self.cache_key)
			if not cache_data:
				return {
					'cached': False,
					'message': _('No token cached')
				}
				
			token_data = json.loads(cache_data)
			expires_at = get_datetime(token_data.get('expires_at'))
			cached_at = get_datetime(token_data.get('cached_at'))
			current_time = now_datetime()
			
			time_remaining = expires_at - current_time
			
			return {
				'cached': True,
				'expires_at': expires_at,
				'cached_at': cached_at,
				'time_remaining_seconds': int(time_remaining.total_seconds()),
				'is_valid': time_remaining.total_seconds() > self.token_expiry_buffer,
				'message': _('Token expires in {0} seconds').format(int(time_remaining.total_seconds()))
			}
			
		except Exception as e:
			return {
				'cached': False,
				'error': str(e),
				'message': _('Error reading token status')
			}


# Global instance for easy access - initialized lazily
_mpesa_auth_instance = None

def get_mpesa_auth():
	"""Get or create the global MpesaAuth instance"""
	global _mpesa_auth_instance
	if _mpesa_auth_instance is None:
		_mpesa_auth_instance = MpesaAuth()
	return _mpesa_auth_instance

# Backward compatibility: create mpesa_auth as a function that returns the instance
def mpesa_auth():
	"""Get the global MpesaAuth instance - backward compatibility function"""
	return get_mpesa_auth()


@frappe.whitelist()
def get_access_token(force_refresh=False):
	"""Public API to get access token"""
	return get_mpesa_auth().get_access_token(force_refresh=force_refresh)


@frappe.whitelist()
def test_authentication():
	"""Public API to test authentication"""
	return get_mpesa_auth().test_authentication()


@frappe.whitelist()
def get_token_status():
	"""Public API to get token status"""
	return get_mpesa_auth().get_token_status()


@frappe.whitelist()
def invalidate_token():
	"""Public API to invalidate cached token"""
	get_mpesa_auth().invalidate_token()
	return {'success': True, 'message': _('Token cache cleared')}