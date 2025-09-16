import frappe
from frappe import _
import requests
import json
from frappe_mpesa.utils import get_mpesa_settings, log_mpesa_transaction
from frappe_mpesa.auth import get_mpesa_auth


class MpesaAPIBase:
	"""Base class for Mpesa API operations"""
	
	def __init__(self):
		self.settings = get_mpesa_settings()
		self.auth = get_mpesa_auth()
		
	def make_request(self, endpoint, data=None, method="POST", log_transaction=True, retry_auth=True):
		"""Make HTTP request to Mpesa API with automatic token refresh"""
		if not self.settings.is_enabled:
			frappe.throw(_("Mpesa integration is not enabled"))
			
		url = self.settings.get_full_url(endpoint)
		
		try:
			headers = self.auth.get_auth_headers()
			
			if method.upper() == "POST":
				response = requests.post(url, json=data, headers=headers, timeout=30)
			elif method.upper() == "GET":
				response = requests.get(url, headers=headers, timeout=30)
			else:
				frappe.throw(_("Unsupported HTTP method: {0}").format(method))
				
			# Handle 401 Unauthorized - try refreshing token once
			if response.status_code == 401 and retry_auth:
				frappe.logger().info("Received 401, attempting token refresh")
				self.auth.invalidate_token()
				return self.make_request(endpoint, data, method, log_transaction, retry_auth=False)
				
			response.raise_for_status()
			result = response.json()
			
			if log_transaction:
				log_mpesa_transaction(
					transaction_type=endpoint,
					request_data=data,
					response_data=result,
					status="Success" if response.status_code == 200 else "Failed"
				)
				
			return result
			
		except requests.exceptions.Timeout:
			error_msg = _("Request timeout while connecting to Mpesa API")
			frappe.log_error(error_msg, "Mpesa API Timeout")
			frappe.throw(error_msg)
			
		except requests.exceptions.ConnectionError:
			error_msg = _("Failed to connect to Mpesa API")
			frappe.log_error(error_msg, "Mpesa API Connection Error")
			frappe.throw(error_msg)
			
		except requests.exceptions.HTTPError as e:
			error_msg = _("HTTP Error {0}: {1}").format(e.response.status_code, e.response.text)
			frappe.log_error(f"Mpesa API HTTP Error: {error_msg}", "Mpesa API Error")
			
			if log_transaction:
				log_mpesa_transaction(
					transaction_type=endpoint,
					request_data=data,
					response_data={"error": error_msg},
					status="Failed"
				)
				
			frappe.throw(error_msg)
			
		except json.JSONDecodeError:
			error_msg = _("Invalid JSON response from Mpesa API")
			frappe.log_error(error_msg, "Mpesa API JSON Error")
			frappe.throw(error_msg)
			
		except Exception as e:
			error_msg = _("Unexpected error: {0}").format(str(e))
			frappe.log_error(f"Mpesa API Unexpected Error: {error_msg}", "Mpesa API Error")
			
			if log_transaction:
				log_mpesa_transaction(
					transaction_type=endpoint,
					request_data=data,
					response_data={"error": error_msg},
					status="Failed"
				)
				
			frappe.throw(error_msg)
	
	def validate_response(self, response, required_fields=None):
		"""Validate API response"""
		if not isinstance(response, dict):
			frappe.throw(_("Invalid response format from Mpesa API"))
			
		# Check for error in response
		if "errorCode" in response or "Error" in response:
			error_code = response.get("errorCode") or response.get("Error", {}).get("errorCode")
			error_message = response.get("errorMessage") or response.get("Error", {}).get("errorMessage")
			frappe.throw(_("Mpesa API Error {0}: {1}").format(error_code, error_message))
			
		# Check required fields
		if required_fields:
			missing_fields = [field for field in required_fields if field not in response]
			if missing_fields:
				frappe.throw(_("Missing required fields in response: {0}").format(", ".join(missing_fields)))
				
		return True