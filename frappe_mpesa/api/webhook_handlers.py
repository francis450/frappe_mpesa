# Copyright (c) 2025, Njoroge Francis and contributors
# For license information, please see license.txt

import frappe
from frappe import _
import json
from frappe.utils import now, flt, cstr
from frappe_mpesa.utils import sanitize_callback_data, get_error_message
from frappe_mpesa.utils.resilience import with_retry, ExponentialBackoff
import functools


def resilient_webhook_handler(webhook_name: str, max_retries: int = 2):
	"""Decorator for webhook handlers to add resilience and error recovery"""
	def decorator(func):
		@functools.wraps(func)
		def wrapper(*args, **kwargs):
			callback_data = None
			transaction_id = None

			try:
				# Extract callback data for logging
				callback_data = frappe.local.form_dict or {}
				if not callback_data:
					try:
						callback_data = json.loads(frappe.request.get_data().decode('utf-8'))
					except (json.JSONDecodeError, UnicodeDecodeError, AttributeError):
						callback_data = {}

				# Extract transaction identifier for tracking
				if webhook_name == "mpesa_express":
					stk_callback = callback_data.get('Body', {}).get('stkCallback', {})
					transaction_id = stk_callback.get('CheckoutRequestID')
				elif webhook_name == "c2b":
					transaction_id = callback_data.get('TransID')
				elif webhook_name == "b2c":
					result = callback_data.get('Result', {})
					transaction_id = result.get('OriginatorConversationID') or result.get('ConversationID')

				# Log incoming webhook
				frappe.log_error(
					f"{webhook_name.upper()} Webhook received: {json.dumps(callback_data, indent=2)}",
					f"Mpesa {webhook_name.upper()} Webhook"
				)

				# Execute the actual webhook handler
				result = func(*args, **kwargs)

				# Log successful processing
				frappe.logger().info(
					f"{webhook_name.upper()} webhook processed successfully. "
					f"Transaction ID: {transaction_id or 'Unknown'}"
				)

				return result

			except frappe.ValidationError as e:
				# Business logic validation errors - should not be retried
				error_msg = f"Validation error in {webhook_name} webhook: {str(e)}"
				frappe.log_error(error_msg, f"Mpesa {webhook_name.upper()} Validation Error")

				return {
					"status": "error",
					"message": "Validation failed",
					"error_code": "VALIDATION_ERROR"
				}

			except frappe.DoesNotExistError as e:
				# Record not found - log but don't fail the webhook
				error_msg = f"Record not found in {webhook_name} webhook: {str(e)}"
				frappe.log_error(error_msg, f"Mpesa {webhook_name.upper()} Record Not Found")

				return {
					"status": "success",
					"message": "Record not found but webhook acknowledged",
					"warning": "RECORD_NOT_FOUND"
				}

			except frappe.DuplicateEntryError as e:
				# Duplicate processing - this is actually success (idempotency)
				frappe.logger().info(
					f"Duplicate {webhook_name} webhook processed: {str(e)}. "
					f"Transaction ID: {transaction_id or 'Unknown'}"
				)

				return {
					"status": "success",
					"message": "Duplicate webhook processed (idempotent)",
					"warning": "DUPLICATE_PROCESSED"
				}

			except Exception as e:
				# Unexpected errors - these might be retryable
				error_msg = f"Error processing {webhook_name} webhook: {str(e)}"
				frappe.log_error(
					f"{error_msg}\nCallback data: {json.dumps(callback_data, indent=2)}",
					f"Mpesa {webhook_name.upper()} Processing Error"
				)

				# For critical webhooks, we might want to queue for retry
				if webhook_name in ["mpesa_express", "b2c"]:
					_queue_webhook_for_retry(webhook_name, callback_data, str(e))

				return {
					"status": "error",
					"message": "Processing failed",
					"error_code": "PROCESSING_ERROR"
				}

		return wrapper
	return decorator


def _queue_webhook_for_retry(webhook_name: str, callback_data: dict, error_message: str):
	"""Queue failed webhook for retry processing"""
	try:
		# Create a failed webhook entry for manual retry or scheduled retry
		failed_webhook = frappe.new_doc("Mpesa Failed Webhook")
		failed_webhook.webhook_type = webhook_name
		failed_webhook.callback_data = json.dumps(callback_data)
		failed_webhook.error_message = error_message
		failed_webhook.retry_count = 0
		failed_webhook.status = "Pending Retry"
		failed_webhook.save(ignore_permissions=True)
		frappe.db.commit()

		frappe.logger().info(f"Queued {webhook_name} webhook for retry: {failed_webhook.name}")

	except Exception as e:
		frappe.log_error(
			f"Failed to queue webhook for retry: {str(e)}",
			"Webhook Retry Queue Error"
		)


@frappe.whitelist(allow_guest=True)
@resilient_webhook_handler("mpesa_express")
def mpesa_express_callback():
	"""Handle STK Push callback from Mpesa"""
	try:
		# Get callback data
		callback_data = frappe.local.form_dict
		
		if not callback_data:
			callback_data = json.loads(frappe.request.get_data().decode('utf-8'))
		
		# Log the callback for debugging
		frappe.log_error(f"STK Push Callback: {json.dumps(callback_data, indent=2)}", "Mpesa Express Callback")
		
		# Extract callback data
		stk_callback = callback_data.get('Body', {}).get('stkCallback', {})
		
		if not stk_callback:
			frappe.throw(_("Invalid callback data structure"))
		
		merchant_request_id = stk_callback.get('MerchantRequestID')
		checkout_request_id = stk_callback.get('CheckoutRequestID')
		result_code = cstr(stk_callback.get('ResultCode', ''))
		result_desc = stk_callback.get('ResultDesc', '')
		
		if not merchant_request_id or not checkout_request_id:
			frappe.throw(_("Missing required callback parameters"))
		
		# Find the transaction record
		transaction = frappe.get_doc("Mpesa Express Transaction", 
			{"checkout_request_id": checkout_request_id})
		
		if not transaction:
			frappe.log_error(f"Transaction not found for CheckoutRequestID: {checkout_request_id}", 
				"Mpesa Express Callback")
			return {"status": "error", "message": "Transaction not found"}
		
		# Update transaction status
		if result_code == '0':
			# Successful payment
			callback_metadata = stk_callback.get('CallbackMetadata', {}).get('Item', [])
			
			# Extract payment details
			payment_details = {}
			for item in callback_metadata:
				name = item.get('Name')
				value = item.get('Value')
				if name and value is not None:
					payment_details[name] = value
			
			# Update transaction
			transaction.status = "Completed"
			transaction.mpesa_receipt_number = payment_details.get('MpesaReceiptNumber')
			transaction.transaction_date = payment_details.get('TransactionDate')
			transaction.phone_number = payment_details.get('PhoneNumber')
			transaction.amount_paid = flt(payment_details.get('Amount', 0))
			transaction.callback_response = json.dumps(sanitize_callback_data(callback_data))
			transaction.completed_at = now()
			
		else:
			# Failed payment
			transaction.status = "Failed"
			transaction.failure_reason = result_desc
			transaction.callback_response = json.dumps(sanitize_callback_data(callback_data))
			transaction.completed_at = now()
		
		transaction.save(ignore_permissions=True)
		frappe.db.commit()
		
		# Create payment entry if successful and linked to sales invoice
		if result_code == '0' and transaction.reference_doctype == "Sales Invoice":
			create_payment_entry(transaction)
		
		return {"status": "success", "message": "Callback processed successfully"}
		
	except Exception as e:
		frappe.log_error(f"Error processing STK Push callback: {str(e)}", "Mpesa Express Callback Error")
		return {"status": "error", "message": str(e)}


def create_payment_entry(transaction):
	"""Create payment entry for successful Mpesa transaction"""
	try:
		if not transaction.reference_name:
			return
			
		# Get the sales invoice
		sales_invoice = frappe.get_doc("Sales Invoice", transaction.reference_name)
		
		# Check if payment entry already exists
		existing_payment = frappe.db.exists("Payment Entry", {
			"reference_no": transaction.mpesa_receipt_number,
			"party": sales_invoice.customer
		})
		
		if existing_payment:
			frappe.log_error(f"Payment entry already exists for receipt: {transaction.mpesa_receipt_number}", 
				"Mpesa Payment Entry")
			return
		
		# Get Mpesa settings for account mapping
		settings = frappe.get_single("Mpesa Settings")
		
		if not settings.default_account_head:
			frappe.log_error("Default account head not configured in Mpesa Settings", 
				"Mpesa Payment Entry")
			return
		
		# Create payment entry
		payment_entry = frappe.new_doc("Payment Entry")
		payment_entry.payment_type = "Receive"
		payment_entry.party_type = "Customer"
		payment_entry.party = sales_invoice.customer
		payment_entry.posting_date = transaction.transaction_date or transaction.created_at.date()
		payment_entry.paid_from = settings.default_account_head
		payment_entry.paid_to = sales_invoice.debit_to
		payment_entry.paid_amount = transaction.amount_paid
		payment_entry.received_amount = transaction.amount_paid
		payment_entry.reference_no = transaction.mpesa_receipt_number
		payment_entry.reference_date = transaction.transaction_date or transaction.created_at.date()
		payment_entry.mode_of_payment = "Mpesa"
		payment_entry.remarks = f"Mpesa payment via STK Push - Receipt: {transaction.mpesa_receipt_number}"
		
		# Add reference to sales invoice
		payment_entry.append("references", {
			"reference_doctype": "Sales Invoice",
			"reference_name": sales_invoice.name,
			"allocated_amount": transaction.amount_paid
		})
		
		payment_entry.insert(ignore_permissions=True)
		payment_entry.submit()
		
		# Update transaction with payment entry reference
		transaction.payment_entry = payment_entry.name
		transaction.save(ignore_permissions=True)
		
		frappe.db.commit()
		
		frappe.log_error(f"Payment entry created: {payment_entry.name} for Mpesa receipt: {transaction.mpesa_receipt_number}", 
			"Mpesa Payment Entry Success")
		
	except Exception as e:
		frappe.log_error(f"Error creating payment entry: {str(e)}", "Mpesa Payment Entry Error")


@frappe.whitelist(allow_guest=True)
@resilient_webhook_handler("mpesa_timeout")
def mpesa_timeout_callback():
	"""Handle STK Push timeout callback"""
	try:
		callback_data = frappe.local.form_dict
		
		if not callback_data:
			callback_data = json.loads(frappe.request.get_data().decode('utf-8'))
		
		frappe.log_error(f"STK Push Timeout: {json.dumps(callback_data, indent=2)}", "Mpesa Express Timeout")
		
		# Extract timeout data
		checkout_request_id = callback_data.get('CheckoutRequestID')
		
		if checkout_request_id:
			# Find and update transaction
			transaction = frappe.get_doc("Mpesa Express Transaction", 
				{"checkout_request_id": checkout_request_id})
			
			if transaction:
				transaction.status = "Timeout"
				transaction.failure_reason = "Transaction timeout"
				transaction.callback_response = json.dumps(sanitize_callback_data(callback_data))
				transaction.completed_at = now()
				transaction.save(ignore_permissions=True)
				frappe.db.commit()
		
		return {"status": "success", "message": "Timeout processed"}
		
	except Exception as e:
		frappe.log_error(f"Error processing timeout callback: {str(e)}", "Mpesa Express Timeout Error")
		return {"status": "error", "message": str(e)}


@frappe.whitelist(allow_guest=True)
@resilient_webhook_handler("c2b_validation")
def c2b_validation():
	"""Handle C2B validation callback from Mpesa"""
	try:
		# Get callback data
		callback_data = frappe.local.form_dict
		
		if not callback_data:
			callback_data = json.loads(frappe.request.get_data().decode('utf-8'))
		
		# Log the validation request
		frappe.log_error(f"C2B Validation: {json.dumps(callback_data, indent=2)}", "Mpesa C2B Validation")
		
		# Extract validation data
		trans_type = callback_data.get('TransType')
		trans_id = callback_data.get('TransID')
		trans_time = callback_data.get('TransTime')
		trans_amount = callback_data.get('TransAmount')
		business_short_code = callback_data.get('BusinessShortCode')
		bill_ref_number = callback_data.get('BillRefNumber')
		invoice_number = callback_data.get('InvoiceNumber')
		org_account_balance = callback_data.get('OrgAccountBalance')
		third_party_trans_id = callback_data.get('ThirdPartyTransID')
		msisdn = callback_data.get('MSISDN')
		first_name = callback_data.get('FirstName')
		middle_name = callback_data.get('MiddleName')
		last_name = callback_data.get('LastName')
		
		# Perform validation logic here
		# For now, we'll accept all transactions
		# You can add custom validation logic based on your requirements
		
		# Return validation response
		return {
			"ResultCode": 0,
			"ResultDesc": "Accepted"
		}
		
	except Exception as e:
		frappe.log_error(f"Error in C2B validation: {str(e)}", "Mpesa C2B Validation Error")
		return {
			"ResultCode": 1,
			"ResultDesc": "Rejected"
		}


@frappe.whitelist(allow_guest=True)
@resilient_webhook_handler("c2b_confirmation")
def c2b_confirmation():
	"""Handle C2B confirmation callback from Mpesa"""
	try:
		# Get callback data
		callback_data = frappe.local.form_dict
		
		if not callback_data:
			callback_data = json.loads(frappe.request.get_data().decode('utf-8'))
		
		# Log the confirmation
		frappe.log_error(f"C2B Confirmation: {json.dumps(callback_data, indent=2)}", "Mpesa C2B Confirmation")
		
		# Extract confirmation data
		trans_type = callback_data.get('TransType')
		trans_id = callback_data.get('TransID')
		trans_time = callback_data.get('TransTime')
		trans_amount = flt(callback_data.get('TransAmount', 0))
		business_short_code = callback_data.get('BusinessShortCode')
		bill_ref_number = callback_data.get('BillRefNumber')
		invoice_number = callback_data.get('InvoiceNumber')
		org_account_balance = callback_data.get('OrgAccountBalance')
		third_party_trans_id = callback_data.get('ThirdPartyTransID')
		msisdn = callback_data.get('MSISDN')
		first_name = callback_data.get('FirstName')
		middle_name = callback_data.get('MiddleName')
		last_name = callback_data.get('LastName')
		
		if not trans_id or not trans_amount or not msisdn:
			frappe.throw(_("Missing required transaction data"))
		
		# Check if transaction already exists
		existing_transaction = frappe.db.exists("Mpesa C2B Transaction", {"trans_id": trans_id})
		
		if existing_transaction:
			frappe.log_error(f"Duplicate C2B transaction: {trans_id}", "Mpesa C2B Duplicate")
			return {"ResultCode": 0, "ResultDesc": "Success"}
		
		# Create C2B transaction record
		c2b_transaction = frappe.new_doc("Mpesa C2B Transaction")
		c2b_transaction.transaction_type = trans_type
		c2b_transaction.trans_id = trans_id
		c2b_transaction.trans_time = trans_time
		c2b_transaction.amount = trans_amount
		c2b_transaction.phone_number = msisdn
		c2b_transaction.bill_ref_number = bill_ref_number
		c2b_transaction.invoice_number = invoice_number
		c2b_transaction.first_name = first_name
		c2b_transaction.middle_name = middle_name
		c2b_transaction.last_name = last_name
		c2b_transaction.organization_short_code = business_short_code
		c2b_transaction.raw_callback_data = json.dumps(sanitize_callback_data(callback_data))
		c2b_transaction.status = "Received"
		
		c2b_transaction.insert(ignore_permissions=True)
		frappe.db.commit()
		
		# Return success response
		return {
			"ResultCode": 0,
			"ResultDesc": "Success"
		}
		
	except Exception as e:
		frappe.log_error(f"Error processing C2B confirmation: {str(e)}", "Mpesa C2B Confirmation Error")
		return {
			"ResultCode": 1,
			"ResultDesc": f"Error: {str(e)}"
		}


@frappe.whitelist(allow_guest=True)
@resilient_webhook_handler("b2c_result")
def b2c_result_callback():
	"""Handle B2C result callback from Mpesa"""
	try:
		# Get callback data
		callback_data = frappe.local.form_dict
		
		if not callback_data:
			callback_data = json.loads(frappe.request.get_data().decode('utf-8'))
		
		# Log the callback for debugging
		frappe.log_error(f"B2C Result Callback: {json.dumps(callback_data, indent=2)}", "Mpesa B2C Result")
		
		# Extract result data
		result = callback_data.get('Result', {})
		originator_conversation_id = result.get('OriginatorConversationID')
		conversation_id = result.get('ConversationID')
		
		if not originator_conversation_id and not conversation_id:
			frappe.throw(_("Missing conversation IDs in B2C callback"))
		
		# Find the transaction record
		transaction = None
		if originator_conversation_id:
			transaction = frappe.db.exists("Mpesa B2C Transaction", 
				{"originator_conversation_id": originator_conversation_id})
		
		if not transaction and conversation_id:
			transaction = frappe.db.exists("Mpesa B2C Transaction", 
				{"conversation_id": conversation_id})
		
		if not transaction:
			frappe.log_error(f"B2C transaction not found for callback: {callback_data}", 
				"Mpesa B2C Callback")
			return {"status": "error", "message": "Transaction not found"}
		
		# Get the transaction document and update it
		transaction_doc = frappe.get_doc("Mpesa B2C Transaction", transaction)
		transaction_doc.update_from_callback(callback_data)
		
		return {"status": "success", "message": "B2C callback processed successfully"}
		
	except Exception as e:
		frappe.log_error(f"Error processing B2C result callback: {str(e)}", "Mpesa B2C Result Error")
		return {"status": "error", "message": str(e)}


@frappe.whitelist(allow_guest=True)
@resilient_webhook_handler("b2c_timeout")
def b2c_timeout_callback():
	"""Handle B2C timeout callback from Mpesa"""
	try:
		# Get callback data
		callback_data = frappe.local.form_dict
		
		if not callback_data:
			callback_data = json.loads(frappe.request.get_data().decode('utf-8'))
		
		frappe.log_error(f"B2C Timeout Callback: {json.dumps(callback_data, indent=2)}", "Mpesa B2C Timeout")
		
		# Extract timeout data
		originator_conversation_id = callback_data.get('OriginatorConversationID')
		conversation_id = callback_data.get('ConversationID')
		
		if originator_conversation_id or conversation_id:
			# Find and update transaction
			transaction = None
			if originator_conversation_id:
				transaction = frappe.db.exists("Mpesa B2C Transaction", 
					{"originator_conversation_id": originator_conversation_id})
			
			if not transaction and conversation_id:
				transaction = frappe.db.exists("Mpesa B2C Transaction", 
					{"conversation_id": conversation_id})
			
			if transaction:
				transaction_doc = frappe.get_doc("Mpesa B2C Transaction", transaction)
				transaction_doc.status = "Timeout"
				transaction_doc.result_desc = "Transaction timeout"
				transaction_doc.callback_response = json.dumps(sanitize_callback_data(callback_data))
				transaction_doc.completed_at = now()
				transaction_doc.save(ignore_permissions=True)
				frappe.db.commit()
		
		return {"status": "success", "message": "B2C timeout processed"}
		
	except Exception as e:
		frappe.log_error(f"Error processing B2C timeout callback: {str(e)}", "Mpesa B2C Timeout Error")
		return {"status": "error", "message": str(e)}


@frappe.whitelist()
def check_transaction_status(checkout_request_id):
	"""Check the status of an STK Push transaction"""
	try:
		transaction = frappe.get_doc("Mpesa Express Transaction", 
			{"checkout_request_id": checkout_request_id})
		
		return {
			"status": transaction.status,
			"amount": transaction.amount,
			"phone_number": transaction.phone_number,
			"mpesa_receipt_number": transaction.mpesa_receipt_number,
			"transaction_date": transaction.transaction_date,
			"failure_reason": transaction.failure_reason
		}
		
	except frappe.DoesNotExistError:
		return {"status": "not_found", "message": "Transaction not found"}
	except Exception as e:
		frappe.log_error(f"Error checking transaction status: {str(e)}", "Mpesa Transaction Status")
		return {"status": "error", "message": str(e)}