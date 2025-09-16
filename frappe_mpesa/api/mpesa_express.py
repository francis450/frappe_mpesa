# Copyright (c) 2025, Njoroge Francis and contributors
# For license information, please see license.txt

import frappe
from frappe import _
import json
from datetime import datetime
from frappe_mpesa.api import MpesaAPIBase
from frappe_mpesa.utils import (
	get_mpesa_settings,
	format_phone_number,
	validate_amount,
	generate_password,
	generate_timestamp,
	generate_transaction_id,
	log_mpesa_transaction
)


class MpesaExpress(MpesaAPIBase):
	"""Mpesa Express (STK Push) API implementation"""
	
	def __init__(self):
		super().__init__()
	
	def initiate_payment(self, phone_number, amount, account_reference, transaction_desc, callback_url=None):
		"""Initiate STK push payment"""
		
		# Validate inputs
		phone_number = format_phone_number(phone_number)
		amount = validate_amount(amount)
		
		if not account_reference:
			frappe.throw(_("Account reference is required"))
		if not transaction_desc:
			frappe.throw(_("Transaction description is required"))
		
		# Get timestamp and password
		timestamp = generate_timestamp()
		password = generate_password(
			self.settings.shortcode,
			self.settings.get_password('passkey'),
			timestamp
		)
		
		# Set callback URL
		if not callback_url:
			from frappe.utils import get_url
			from urllib.parse import urljoin
			site_url = get_url()
			callback_url = urljoin(site_url, "/api/method/frappe_mpesa.api.webhook_handlers.mpesa_express_callback")
		
		# Prepare request data
		request_data = {
			"BusinessShortCode": self.settings.shortcode,
			"Password": password,
			"Timestamp": timestamp,
			"TransactionType": "CustomerPayBillOnline",
			"Amount": amount,
			"PartyA": phone_number,
			"PartyB": self.settings.shortcode,
			"PhoneNumber": phone_number,
			"CallBackURL": callback_url,
			"AccountReference": account_reference,
			"TransactionDesc": transaction_desc
		}
		
		try:
			# Make API request
			response = self.make_request(
				endpoint=self.settings.express_url,
				data=request_data,
				method="POST"
			)
			
			# Validate response
			self.validate_response(response, ["ResponseCode", "ResponseDescription"])
			
			return {
				"success": True,
				"checkout_request_id": response.get("CheckoutRequestID"),
				"merchant_request_id": response.get("MerchantRequestID"),
				"response_code": response.get("ResponseCode"),
				"response_description": response.get("ResponseDescription"),
				"customer_message": response.get("CustomerMessage"),
				"request_data": request_data,
				"response_data": response
			}
			
		except Exception as e:
			error_msg = str(e)
			frappe.log_error(f"STK Push failed: {error_msg}", "Mpesa Express")
			
			return {
				"success": False,
				"message": error_msg,
				"request_data": request_data
			}


@frappe.whitelist()
def initiate_stk_push(phone_number, amount, account_reference, transaction_desc, 
					  sales_invoice=None, customer=None, reference_doctype=None, reference_name=None):
	"""Initiate STK push and create transaction record"""
	
	try:
		# Create Mpesa Express instance
		mpesa_express = MpesaExpress()
		
		# Initiate payment
		result = mpesa_express.initiate_payment(
			phone_number=phone_number,
			amount=amount,
			account_reference=account_reference,
			transaction_desc=transaction_desc
		)
		
		# Create transaction record
		transaction = frappe.new_doc("Mpesa Express Transaction")
		transaction.phone_number = format_phone_number(phone_number)
		transaction.amount = validate_amount(amount)
		transaction.account_reference = account_reference
		transaction.transaction_desc = transaction_desc
		
		# Set reference documents
		if sales_invoice:
			transaction.sales_invoice = sales_invoice
			transaction.reference_doctype = "Sales Invoice"
			transaction.reference_name = sales_invoice
			
			# Get customer from sales invoice if not provided
			if not customer:
				invoice = frappe.get_doc("Sales Invoice", sales_invoice)
				customer = invoice.customer
				
		if customer:
			transaction.customer = customer
		if reference_doctype and reference_name:
			transaction.reference_doctype = reference_doctype
			transaction.reference_name = reference_name
		
		# Set response data
		transaction.request_data = result.get("request_data", {})
		transaction.response_data = result.get("response_data", {})
		
		if result.get("success"):
			transaction.status = "Pending"
			transaction.checkout_request_id = result.get("checkout_request_id")
			transaction.merchant_request_id = result.get("merchant_request_id")
			transaction.response_code = result.get("response_code")
			transaction.response_description = result.get("response_description")
		else:
			transaction.status = "Failed"
			transaction.response_description = result.get("message")
		
		transaction.insert(ignore_permissions=True)
		
		# Return response
		if result.get("success"):
			return {
				"success": True,
				"message": _("STK push initiated successfully. Customer will receive a prompt on their phone."),
				"transaction_name": transaction.name,
				"checkout_request_id": result.get("checkout_request_id"),
				"merchant_request_id": result.get("merchant_request_id"),
				"customer_message": result.get("customer_message")
			}
		else:
			return {
				"success": False,
				"message": result.get("message"),
				"transaction_name": transaction.name
			}
			
	except Exception as e:
		frappe.log_error(f"STK Push initiation failed: {str(e)}", "Mpesa Express")
		return {
			"success": False,
			"message": _("Failed to initiate payment: {0}").format(str(e))
		}


@frappe.whitelist(allow_guest=True)
def stk_callback():
	"""Handle STK push callback from Mpesa"""
	try:
		# Get callback data from request
		callback_data = frappe.local.form_dict
		
		if not callback_data:
			# Try getting from request body
			callback_data = json.loads(frappe.request.get_data())
		
		frappe.log_error(f"STK Callback received: {json.dumps(callback_data, indent=2)}", "Mpesa STK Callback")
		
		# Extract checkout request ID
		checkout_request_id = None
		if "Body" in callback_data:
			stk_callback = callback_data.get("Body", {}).get("stkCallback", {})
			checkout_request_id = stk_callback.get("CheckoutRequestID")
		
		if not checkout_request_id:
			frappe.log_error("No CheckoutRequestID in callback", "Mpesa STK Callback")
			return {"ResultCode": 1, "ResultDesc": "Invalid callback data"}
		
		# Find corresponding transaction
		transactions = frappe.get_all(
			"Mpesa Express Transaction",
			filters={"checkout_request_id": checkout_request_id},
			limit=1
		)
		
		if not transactions:
			frappe.log_error(f"No transaction found for CheckoutRequestID: {checkout_request_id}", "Mpesa STK Callback")
			return {"ResultCode": 1, "ResultDesc": "Transaction not found"}
		
		# Update transaction with callback data
		transaction = frappe.get_doc("Mpesa Express Transaction", transactions[0].name)
		transaction.update_from_callback(callback_data)
		
		return {"ResultCode": 0, "ResultDesc": "Success"}
		
	except Exception as e:
		frappe.log_error(f"STK Callback processing failed: {str(e)}", "Mpesa STK Callback")
		return {"ResultCode": 1, "ResultDesc": "Callback processing failed"}


@frappe.whitelist()
def get_stk_push_status(checkout_request_id):
	"""Get STK push status by checkout request ID"""
	try:
		transactions = frappe.get_all(
			"Mpesa Express Transaction",
			filters={"checkout_request_id": checkout_request_id},
			fields=["name", "status", "phone_number", "amount", "mpesa_receipt_number", "callback_received"],
			limit=1
		)
		
		if transactions:
			return {
				"success": True,
				"transaction": transactions[0]
			}
		else:
			return {
				"success": False,
				"message": _("Transaction not found")
			}
			
	except Exception as e:
		frappe.log_error(f"Failed to get STK push status: {str(e)}", "Mpesa Express")
		return {
			"success": False,
			"message": str(e)
		}