import frappe
from frappe import _
import requests
import json
from frappe_mpesa.utils import get_mpesa_settings, log_mpesa_transaction
from frappe_mpesa.auth import get_mpesa_auth
from frappe_mpesa.utils.resilience import (
	get_resilient_requester,
	RetryableError,
	NonRetryableError,
	CircuitBreakerError
)


class MpesaAPIBase:
	"""Base class for Mpesa API operations"""
	
	def __init__(self):
		self.settings = get_mpesa_settings()
		self.auth = get_mpesa_auth()
		self.resilient_requester = get_resilient_requester("mpesa_api")
		
	def make_request(self, endpoint, data=None, method="POST", log_transaction=True, retry_auth=True):
		"""Make HTTP request to Mpesa API with resilience and automatic token refresh"""
		if not self.settings.is_enabled:
			frappe.throw(_("Mpesa integration is not enabled"))

		url = self.settings.get_full_url(endpoint)

		def _perform_request():
			"""Internal function to perform the actual request"""
			headers = self.auth.get_auth_headers()

			# Prepare request arguments based on method
			if method.upper() == "POST":
				kwargs = {"json": data} if data else {}
			elif method.upper() == "GET":
				kwargs = {"params": data} if data else {}
			else:
				raise NonRetryableError(_("Unsupported HTTP method: {0}").format(method))

			kwargs["headers"] = headers

			try:
				response = self.resilient_requester.request(method, url, **kwargs)
				return response

			except requests.exceptions.HTTPError as e:
				# Handle 401 Unauthorized - invalidate token and raise retryable error for auth retry
				if e.response and e.response.status_code == 401:
					frappe.logger().info("Received 401, invalidating token for retry")
					self.auth.invalidate_token()

					# If this is our first auth retry attempt, make it retryable
					if retry_auth:
						raise RetryableError(f"Authentication failed, token invalidated: {str(e)}") from e
					else:
						raise NonRetryableError(f"Authentication failed after token refresh: {str(e)}") from e

				# For other HTTP errors, let the resilient requester handle retry logic
				raise

		try:
			# Perform the resilient request
			response = _perform_request()

			# Parse JSON response
			try:
				result = response.json()
			except json.JSONDecodeError as e:
				error_msg = _("Invalid JSON response from Mpesa API")
				frappe.log_error(f"JSON decode error: {str(e)}", "Mpesa API JSON Error")
				raise NonRetryableError(error_msg) from e

			# Log successful transaction
			if log_transaction:
				log_mpesa_transaction(
					transaction_type=endpoint,
					request_data=data,
					response_data=result,
					status="Success"
				)

			return result

		except CircuitBreakerError as e:
			error_msg = _("Mpesa API circuit breaker is open: {0}").format(str(e))
			frappe.log_error(error_msg, "Mpesa API Circuit Breaker")

			if log_transaction:
				log_mpesa_transaction(
					transaction_type=endpoint,
					request_data=data,
					response_data={"error": error_msg, "circuit_breaker": "open"},
					status="Circuit Breaker Open"
				)

			frappe.throw(error_msg)

		except (RetryableError, NonRetryableError) as e:
			error_msg = _("Mpesa API request failed: {0}").format(str(e))
			frappe.log_error(f"Mpesa API Error: {error_msg}", "Mpesa API Error")

			if log_transaction:
				log_mpesa_transaction(
					transaction_type=endpoint,
					request_data=data,
					response_data={"error": error_msg},
					status="Failed"
				)

			frappe.throw(error_msg)

		except Exception as e:
			error_msg = _("Unexpected error in Mpesa API request: {0}").format(str(e))
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