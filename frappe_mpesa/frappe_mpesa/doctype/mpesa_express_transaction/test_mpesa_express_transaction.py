# Copyright (c) 2025, Njoroge Francis and Contributors
# See license.txt

import frappe
import unittest
from unittest.mock import patch, MagicMock
from frappe_mpesa.api.mpesa_express import MpesaExpress, initiate_stk_push


class TestMpesaExpressTransaction(unittest.TestCase):
	def setUp(self):
		"""Set up test dependencies"""
		# Create test customer
		if not frappe.db.exists("Customer", "Test Customer"):
			customer = frappe.new_doc("Customer")
			customer.customer_name = "Test Customer"
			customer.customer_type = "Individual"
			customer.save(ignore_permissions=True)
		
		# Create test sales invoice
		if not frappe.db.exists("Sales Invoice", "TEST-INV-001"):
			invoice = frappe.new_doc("Sales Invoice")
			invoice.name = "TEST-INV-001"
			invoice.customer = "Test Customer"
			invoice.append("items", {
				"item_code": "Test Item",
				"qty": 1,
				"rate": 1000
			})
			invoice.save(ignore_permissions=True)
			
	def tearDown(self):
		"""Clean up test data"""
		# Delete test transactions
		frappe.db.delete("Mpesa Express Transaction", {"phone_number": "254712345678"})
		frappe.db.commit()
		
	def test_phone_number_validation(self):
		"""Test phone number formatting"""
		transaction = frappe.new_doc("Mpesa Express Transaction")
		transaction.phone_number = "0712345678"
		transaction.amount = 100
		transaction.account_reference = "TEST001"
		transaction.transaction_desc = "Test payment"
		transaction.validate()
		
		self.assertEqual(transaction.phone_number, "254712345678")
		
	def test_amount_validation(self):
		"""Test amount validation"""
		transaction = frappe.new_doc("Mpesa Express Transaction")
		transaction.phone_number = "254712345678"
		transaction.amount = "100.50"
		transaction.account_reference = "TEST001"
		transaction.transaction_desc = "Test payment"
		transaction.validate()
		
		self.assertEqual(transaction.amount, 100)  # Should be converted to integer
		
	def test_status_timestamps(self):
		"""Test that timestamps are set correctly based on status"""
		transaction = frappe.new_doc("Mpesa Express Transaction")
		transaction.phone_number = "254712345678"
		transaction.amount = 100
		transaction.account_reference = "TEST001"
		transaction.transaction_desc = "Test payment"
		transaction.status = "Success"
		transaction.validate()
		
		self.assertIsNotNone(transaction.processed_at)
		
	def test_callback_processing_success(self):
		"""Test successful callback processing"""
		transaction = frappe.new_doc("Mpesa Express Transaction")
		transaction.phone_number = "254712345678"
		transaction.amount = 100
		transaction.account_reference = "TEST001"
		transaction.transaction_desc = "Test payment"
		transaction.status = "Pending"
		transaction.save(ignore_permissions=True)
		
		# Mock successful callback
		callback_data = {
			"Body": {
				"stkCallback": {
					"ResultCode": "0",
					"ResultDesc": "Success",
					"CallbackMetadata": {
						"Item": [
							{"Name": "MpesaReceiptNumber", "Value": "TEST123456"},
							{"Name": "TransactionDate", "Value": "20231216143022"}
						]
					}
				}
			}
		}
		
		transaction.update_from_callback(callback_data)
		
		self.assertEqual(transaction.status, "Success")
		self.assertEqual(transaction.mpesa_receipt_number, "TEST123456")
		self.assertTrue(transaction.callback_received)
		
	def test_callback_processing_failure(self):
		"""Test failed callback processing"""
		transaction = frappe.new_doc("Mpesa Express Transaction")
		transaction.phone_number = "254712345678"
		transaction.amount = 100
		transaction.account_reference = "TEST001"
		transaction.transaction_desc = "Test payment"
		transaction.status = "Pending"
		transaction.save(ignore_permissions=True)
		
		# Mock failed callback
		callback_data = {
			"Body": {
				"stkCallback": {
					"ResultCode": "1032",
					"ResultDesc": "Request cancelled by user"
				}
			}
		}
		
		transaction.update_from_callback(callback_data)
		
		self.assertEqual(transaction.status, "Failed")
		self.assertEqual(transaction.response_description, "Request cancelled by user")
		self.assertTrue(transaction.callback_received)
		
	@patch('frappe_mpesa.api.mpesa_express.MpesaExpress.make_request')
	def test_initiate_payment_success(self, mock_request):
		"""Test successful payment initiation"""
		# Mock successful API response
		mock_request.return_value = {
			"ResponseCode": "0",
			"ResponseDescription": "Success",
			"CheckoutRequestID": "ws_CO_123456789",
			"MerchantRequestID": "ws_MR_123456789",
			"CustomerMessage": "Success. Request accepted for processing"
		}
		
		mpesa_express = MpesaExpress()
		result = mpesa_express.initiate_payment(
			phone_number="254712345678",
			amount=100,
			account_reference="TEST001",
			transaction_desc="Test payment"
		)
		
		self.assertTrue(result["success"])
		self.assertEqual(result["checkout_request_id"], "ws_CO_123456789")
		self.assertEqual(result["merchant_request_id"], "ws_MR_123456789")
		
	@patch('frappe_mpesa.api.mpesa_express.MpesaExpress.make_request')
	def test_initiate_payment_failure(self, mock_request):
		"""Test failed payment initiation"""
		# Mock API request failure
		mock_request.side_effect = Exception("Invalid phone number")
		
		mpesa_express = MpesaExpress()
		result = mpesa_express.initiate_payment(
			phone_number="254712345678",
			amount=100,
			account_reference="TEST001",
			transaction_desc="Test payment"
		)
		
		self.assertFalse(result["success"])
		self.assertIn("Invalid phone number", result["message"])
		
	@patch('frappe_mpesa.api.mpesa_express.MpesaExpress.initiate_payment')
	def test_initiate_stk_push_integration(self, mock_initiate):
		"""Test STK push integration function"""
		# Mock successful payment initiation
		mock_initiate.return_value = {
			"success": True,
			"checkout_request_id": "ws_CO_123456789",
			"merchant_request_id": "ws_MR_123456789",
			"response_code": "0",
			"response_description": "Success",
			"customer_message": "Success. Request accepted for processing",
			"request_data": {},
			"response_data": {}
		}
		
		result = initiate_stk_push(
			phone_number="254712345678",
			amount=100,
			account_reference="TEST001",
			transaction_desc="Test payment",
			sales_invoice="TEST-INV-001"
		)
		
		self.assertTrue(result["success"])
		self.assertIn("STK push initiated successfully", result["message"])
		
		# Verify transaction was created
		transaction_name = result["transaction_name"]
		transaction = frappe.get_doc("Mpesa Express Transaction", transaction_name)
		self.assertEqual(transaction.phone_number, "254712345678")
		self.assertEqual(transaction.amount, 100)
		self.assertEqual(transaction.sales_invoice, "TEST-INV-001")