# Copyright (c) 2025, Njoroge Francis and Contributors
# See license.txt

import frappe
import unittest
from unittest.mock import patch, MagicMock


class TestMpesaSettings(unittest.TestCase):
	def setUp(self):
		"""Set up test dependencies"""
		self.settings = frappe.get_single("Mpesa Settings")
		
	def test_validate_environment_settings(self):
		"""Test environment validation"""
		# Test production environment
		self.settings.environment = "Production"
		self.settings.base_url = "https://sandbox.safaricom.co.ke"
		self.settings.validate_environment_settings()
		self.assertEqual(self.settings.base_url, "https://api.safaricom.co.ke")
		
		# Test sandbox environment
		self.settings.environment = "Sandbox"
		self.settings.base_url = "https://api.safaricom.co.ke"
		self.settings.validate_environment_settings()
		self.assertEqual(self.settings.base_url, "https://sandbox.safaricom.co.ke")
		
	def test_validate_credentials_enabled(self):
		"""Test credential validation when enabled"""
		self.settings.is_enabled = 1
		self.settings.consumer_key = ""
		
		with self.assertRaises(frappe.ValidationError):
			self.settings.validate_credentials()
			
	def test_validate_credentials_disabled(self):
		"""Test credential validation when disabled"""
		self.settings.is_enabled = 0
		self.settings.consumer_key = ""
		
		# Should not raise error when disabled
		try:
			self.settings.validate_credentials()
		except frappe.ValidationError:
			self.fail("validate_credentials() raised ValidationError when disabled")
			
	@patch('frappe_mpesa.frappe_mpesa.doctype.mpesa_settings.mpesa_settings.requests.get')
	def test_get_access_token_success(self, mock_get):
		"""Test successful access token retrieval"""
		# Mock successful response
		mock_response = MagicMock()
		mock_response.json.return_value = {'access_token': 'test_token_123'}
		mock_response.raise_for_status.return_value = None
		mock_get.return_value = mock_response
		
		self.settings.is_enabled = 1
		self.settings.consumer_key = "test_key"
		self.settings.consumer_secret = "test_secret"
		
		token = self.settings.get_access_token()
		self.assertEqual(token, 'test_token_123')
		
	@patch('frappe_mpesa.frappe_mpesa.doctype.mpesa_settings.mpesa_settings.requests.get')
	def test_get_access_token_failure(self, mock_get):
		"""Test failed access token retrieval"""
		# Mock failed response
		mock_get.side_effect = Exception("Connection failed")
		
		self.settings.is_enabled = 1
		self.settings.consumer_key = "test_key"
		self.settings.consumer_secret = "test_secret"
		
		with self.assertRaises(frappe.ValidationError):
			self.settings.get_access_token()
			
	def test_get_api_headers(self):
		"""Test API headers generation"""
		with patch.object(self.settings, 'get_access_token', return_value='test_token'):
			headers = self.settings.get_api_headers()
			expected_headers = {
				'Content-Type': 'application/json',
				'Authorization': 'Bearer test_token'
			}
			self.assertEqual(headers, expected_headers)
			
	def test_get_full_url(self):
		"""Test full URL generation"""
		self.settings.base_url = "https://sandbox.safaricom.co.ke"
		url = self.settings.get_full_url("/mpesa/stkpush/v1/processrequest")
		expected_url = "https://sandbox.safaricom.co.ke/mpesa/stkpush/v1/processrequest"
		self.assertEqual(url, expected_url)