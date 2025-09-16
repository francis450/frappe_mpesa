# Copyright (c) 2025, Njoroge Francis and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import get_url
import base64
import requests
from urllib.parse import urljoin


class MpesaSettings(Document):
	def validate(self):
		"""Validate the Mpesa Settings"""
		self.validate_environment_settings()
		self.validate_credentials()
		self.validate_callback_urls()
		
	def validate_environment_settings(self):
		"""Validate environment-specific settings"""
		# Set defaults if not provided
		if not self.environment:
			self.environment = "Sandbox"
			
		if not self.base_url:
			self.base_url = "https://sandbox.safaricom.co.ke"
			
		if not self.oauth_url:
			self.oauth_url = "/oauth/v1/generate?grant_type=client_credentials"
			
		if not self.express_url:
			self.express_url = "/mpesa/stkpush/v1/processrequest"
			
		if not self.c2b_register_url:
			self.c2b_register_url = "/mpesa/c2b/v1/registerurl"
			
		if not self.c2b_simulate_url:
			self.c2b_simulate_url = "/mpesa/c2b/v1/simulate"
			
		if not self.b2c_url:
			self.b2c_url = "/mpesa/b2c/v1/paymentrequest"
			
		if not self.transaction_status_url:
			self.transaction_status_url = "/mpesa/transactionstatus/v1/query"
			
		# Update base URL based on environment
		if self.environment == "Production":
			if self.base_url == "https://sandbox.safaricom.co.ke":
				self.base_url = "https://api.safaricom.co.ke"
		elif self.environment == "Sandbox":
			if self.base_url == "https://api.safaricom.co.ke":
				self.base_url = "https://sandbox.safaricom.co.ke"
				
	def validate_credentials(self):
		"""Validate required credentials based on configuration"""
		if self.is_enabled:
			if not self.consumer_key or not self.consumer_secret:
				frappe.throw(_("Consumer Key and Consumer Secret are required when Mpesa is enabled"))
			
			if not self.passkey:
				frappe.throw(_("Passkey is required for Mpesa Express transactions"))
				
			if not self.shortcode:
				frappe.throw(_("Business Short Code is required"))
				
			if not self.base_url:
				frappe.throw(_("Base URL is required"))
				
			if not self.oauth_url:
				frappe.throw(_("OAuth URL is required"))
				
			if not self.express_url:
				frappe.throw(_("Mpesa Express URL is required"))
				
			if not self.c2b_register_url:
				frappe.throw(_("C2B Register URL is required"))
				
	def validate_callback_urls(self):
		"""Auto-generate callback URLs if not provided"""
		site_url = get_url()
		
		if not self.validation_url:
			self.validation_url = urljoin(site_url, "/api/method/frappe_mpesa.api.mpesa.c2b_validation")
			
		if not self.confirmation_url:
			self.confirmation_url = urljoin(site_url, "/api/method/frappe_mpesa.api.mpesa.c2b_confirmation")
			
		if not self.result_url:
			self.result_url = urljoin(site_url, "/api/method/frappe_mpesa.api.mpesa.payment_result")
			
		if not self.timeout_url:
			self.timeout_url = urljoin(site_url, "/api/method/frappe_mpesa.api.mpesa.payment_timeout")
			
		if not self.queue_timeout_url:
			self.queue_timeout_url = urljoin(site_url, "/api/method/frappe_mpesa.api.mpesa.queue_timeout")
	
	def get_access_token(self):
		"""Get OAuth access token from Safaricom (deprecated - use frappe_mpesa.auth instead)"""
		from frappe_mpesa.auth import mpesa_auth
		return mpesa_auth.get_access_token()
	
	def get_api_headers(self, include_auth=True):
		"""Get standard API headers for Mpesa requests"""
		if include_auth:
			from frappe_mpesa.auth import mpesa_auth
			return mpesa_auth.get_auth_headers()
		else:
			return {'Content-Type': 'application/json'}
	
	def get_full_url(self, endpoint):
		"""Get full URL for an API endpoint"""
		return urljoin(self.base_url, endpoint)
	
	@staticmethod
	def get_mpesa_settings():
		"""Get the current Mpesa Settings singleton"""
		if not frappe.db.exists("Mpesa Settings", "Mpesa Settings"):
			# Create default settings if doesn't exist
			doc = frappe.new_doc("Mpesa Settings")
			doc.save(ignore_permissions=True)
			
		return frappe.get_single("Mpesa Settings")
	
	def test_connection(self):
		"""Test connection to Mpesa API"""
		from frappe_mpesa.auth import test_authentication
		result = test_authentication()
		
		if result.get('success'):
			frappe.msgprint(_("Connection to Mpesa API successful! Token: {0}").format(
				result.get('token_preview', 'Hidden')
			))
			return True
		else:
			frappe.throw(_("Connection failed: {0}").format(result.get('message')))
			return False


@frappe.whitelist()
def test_mpesa_connection():
	"""Test Mpesa API connection from client side"""
	settings = frappe.get_single("Mpesa Settings")
	return settings.test_connection()