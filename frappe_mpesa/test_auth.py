# Copyright (c) 2025, Njoroge Francis and Contributors
# See license.txt

import frappe
import unittest
from unittest.mock import patch, MagicMock
import json
from datetime import datetime, timedelta
from frappe_mpesa.auth import MpesaAuth, mpesa_auth


class TestMpesaAuth(unittest.TestCase):
	def setUp(self):
		"""Set up test dependencies"""
		self.auth = MpesaAuth()
		# Clear any existing cache
		self.auth.invalidate_token()
		
	def tearDown(self):
		"""Clean up after tests"""
		self.auth.invalidate_token()
		
	@patch('frappe_mpesa.auth.requests.get')
	def test_request_new_token_success(self, mock_get):
		"""Test successful token request"""
		# Mock successful response
		mock_response = MagicMock()
		mock_response.json.return_value = {
			'access_token': 'test_token_123',
			'expires_in': 3600
		}
		mock_response.raise_for_status.return_value = None
		mock_get.return_value = mock_response
		
		# Mock settings
		with patch.object(self.auth.settings, 'is_enabled', True), \
			 patch.object(self.auth.settings, 'consumer_key', 'test_key'), \
			 patch.object(self.auth.settings, 'get_password', return_value='test_secret'), \
			 patch.object(self.auth.settings, 'get_full_url', return_value='https://test.com/oauth'):
			
			token = self.auth._request_new_token()
			self.assertEqual(token, 'test_token_123')
			
	@patch('frappe_mpesa.auth.requests.get')
	def test_request_new_token_failure(self, mock_get):
		"""Test failed token request"""
		# Mock failed response
		mock_get.side_effect = Exception("Connection failed")
		
		# Mock settings
		with patch.object(self.auth.settings, 'is_enabled', True), \
			 patch.object(self.auth.settings, 'consumer_key', 'test_key'), \
			 patch.object(self.auth.settings, 'get_password', return_value='test_secret'), \
			 patch.object(self.auth.settings, 'get_full_url', return_value='https://test.com/oauth'):
			
			with self.assertRaises(frappe.ValidationError):
				self.auth._request_new_token()
				
	def test_cache_token(self):
		"""Test token caching"""
		test_token = 'test_token_123'
		expires_in = 3600
		
		self.auth._cache_token(test_token, expires_in)
		
		# Verify token is cached
		cached_token = self.auth._get_cached_token()
		self.assertEqual(cached_token, test_token)
		
	def test_get_cached_token_expired(self):
		"""Test that expired tokens are not returned"""
		# Cache a token with very short expiry
		self.auth._cache_token('expired_token', 1)
		
		# Wait for it to expire (simulate)
		import time
		time.sleep(2)
		
		cached_token = self.auth._get_cached_token()
		self.assertIsNone(cached_token)
		
	def test_invalidate_token(self):
		"""Test token invalidation"""
		# Cache a token first
		self.auth._cache_token('test_token', 3600)
		self.assertIsNotNone(self.auth._get_cached_token())
		
		# Invalidate it
		self.auth.invalidate_token()
		self.assertIsNone(self.auth._get_cached_token())
		
	def test_get_auth_headers(self):
		"""Test authentication headers generation"""
		with patch.object(self.auth, 'get_access_token', return_value='test_token'):
			headers = self.auth.get_auth_headers()
			expected_headers = {
				'Authorization': 'Bearer test_token',
				'Content-Type': 'application/json'
			}
			self.assertEqual(headers, expected_headers)
			
	@patch('frappe_mpesa.auth.requests.get')
	def test_get_access_token_with_cache(self, mock_get):
		"""Test access token retrieval with caching"""
		# Mock successful response for first request
		mock_response = MagicMock()
		mock_response.json.return_value = {
			'access_token': 'test_token_123',
			'expires_in': 3600
		}
		mock_response.raise_for_status.return_value = None
		mock_get.return_value = mock_response
		
		# Mock settings
		with patch.object(self.auth.settings, 'is_enabled', True), \
			 patch.object(self.auth.settings, 'consumer_key', 'test_key'), \
			 patch.object(self.auth.settings, 'get_password', return_value='test_secret'), \
			 patch.object(self.auth.settings, 'get_full_url', return_value='https://test.com/oauth'):
			
			# First call should make HTTP request
			token1 = self.auth.get_access_token()
			self.assertEqual(token1, 'test_token_123')
			self.assertEqual(mock_get.call_count, 1)
			
			# Second call should use cache
			token2 = self.auth.get_access_token()
			self.assertEqual(token2, 'test_token_123')
			self.assertEqual(mock_get.call_count, 1)  # Should not increase
			
	def test_get_token_status(self):
		"""Test token status retrieval"""
		# Test with no token cached
		status = self.auth.get_token_status()
		self.assertFalse(status['cached'])
		
		# Cache a token and test status
		self.auth._cache_token('test_token', 3600)
		status = self.auth.get_token_status()
		self.assertTrue(status['cached'])
		self.assertTrue(status['is_valid'])
		self.assertGreater(status['time_remaining_seconds'], 0)
		
	@patch('frappe_mpesa.auth.requests.get')
	def test_test_authentication(self, mock_get):
		"""Test authentication testing"""
		# Mock successful response
		mock_response = MagicMock()
		mock_response.json.return_value = {
			'access_token': 'test_token_123',
			'expires_in': 3600
		}
		mock_response.raise_for_status.return_value = None
		mock_get.return_value = mock_response
		
		# Mock settings
		with patch.object(self.auth.settings, 'is_enabled', True), \
			 patch.object(self.auth.settings, 'consumer_key', 'test_key'), \
			 patch.object(self.auth.settings, 'get_password', return_value='test_secret'), \
			 patch.object(self.auth.settings, 'get_full_url', return_value='https://test.com/oauth'):
			
			result = self.auth.test_authentication()
			self.assertTrue(result['success'])
			self.assertIn('token_preview', result)