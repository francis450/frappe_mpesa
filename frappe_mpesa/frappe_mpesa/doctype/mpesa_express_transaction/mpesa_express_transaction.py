# Copyright (c) 2025, Njoroge Francis and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import now, get_datetime, add_to_date
from frappe_mpesa.utils import format_phone_number, validate_amount, generate_transaction_id


class MpesaExpressTransaction(Document):
	def validate(self):
		"""Validate the transaction before saving"""
		self.validate_phone_number()
		self.validate_amount()
		self.set_timestamps()
		
	def validate_phone_number(self):
		"""Validate and format phone number"""
		if self.phone_number:
			self.phone_number = format_phone_number(self.phone_number)
			
	def validate_amount(self):
		"""Validate transaction amount"""
		if self.amount:
			self.amount = validate_amount(self.amount)
			
	def set_timestamps(self):
		"""Set appropriate timestamps"""
		if not self.created_at:
			self.created_at = now()
		self.updated_at = now()
		
		# Set status-specific timestamps
		if self.status == "Success" and not self.processed_at:
			self.processed_at = now()
		elif self.status in ["Failed", "Cancelled", "Timeout"] and not self.failed_at:
			self.failed_at = now()
	
	def before_save(self):
		"""Actions before saving the document"""
		self.set_timestamps()
	
	def update_from_callback(self, callback_data):
		"""Update transaction from Mpesa callback"""
		self.callback_received = 1
		self.callback_data = callback_data
		
		# Extract key information from callback
		if callback_data:
			result_code = str(callback_data.get("Body", {}).get("stkCallback", {}).get("ResultCode", ""))
			result_desc = callback_data.get("Body", {}).get("stkCallback", {}).get("ResultDesc", "")
			
			if result_code == "0":
				# Success
				self.status = "Success"
				self.response_description = result_desc
				
				# Extract transaction details
				callback_metadata = callback_data.get("Body", {}).get("stkCallback", {}).get("CallbackMetadata", {})
				items = callback_metadata.get("Item", [])
				
				for item in items:
					name = item.get("Name", "")
					value = item.get("Value")
					
					if name == "MpesaReceiptNumber":
						self.mpesa_receipt_number = value
					elif name == "TransactionDate":
						# Convert transaction date from format: 20231216143022
						if value:
							date_str = str(value)
							if len(date_str) == 14:
								formatted_date = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]} {date_str[8:10]}:{date_str[10:12]}:{date_str[12:14]}"
								self.transaction_date = get_datetime(formatted_date)
			else:
				# Failed or cancelled
				self.status = "Failed"
				self.response_description = result_desc
				
		self.save(ignore_permissions=True)
		
		# Create payment entry if successful
		if self.status == "Success" and not self.payment_entry:
			self.create_payment_entry()
			
	def create_payment_entry(self):
		"""Create payment entry for successful transaction"""
		try:
			if not self.sales_invoice:
				return
				
			# Get the sales invoice
			invoice = frappe.get_doc("Sales Invoice", self.sales_invoice)
			
			# Create payment entry
			payment_entry = frappe.new_doc("Payment Entry")
			payment_entry.payment_type = "Receive"
			payment_entry.party_type = "Customer"
			payment_entry.party = invoice.customer
			payment_entry.posting_date = self.transaction_date or now()
			payment_entry.paid_amount = self.amount
			payment_entry.received_amount = self.amount
			payment_entry.reference_no = self.mpesa_receipt_number
			payment_entry.reference_date = self.transaction_date or now()
			payment_entry.remarks = f"Mpesa Express payment via {self.phone_number}"
			
			# Set accounts from Mpesa settings
			settings = frappe.get_single("Mpesa Settings")
			if settings.default_account_head:
				payment_entry.paid_to = settings.default_account_head
			
			# Add reference to the invoice
			payment_entry.append("references", {
				"reference_doctype": "Sales Invoice",
				"reference_name": self.sales_invoice,
				"allocated_amount": self.amount
			})
			
			payment_entry.insert(ignore_permissions=True)
			payment_entry.submit()
			
			# Update this transaction with payment entry reference
			self.payment_entry = payment_entry.name
			self.save(ignore_permissions=True)
			
			frappe.msgprint(_("Payment Entry {0} created successfully").format(payment_entry.name))
			
		except Exception as e:
			frappe.log_error(f"Failed to create payment entry for {self.name}: {str(e)}", "Mpesa Express Payment Entry")
			
	def retry_transaction(self):
		"""Retry failed transaction"""
		if self.status not in ["Failed", "Timeout", "Cancelled"]:
			frappe.throw(_("Can only retry failed, timeout or cancelled transactions"))
			
		# Reset status and timestamps
		self.status = "Pending"
		self.callback_received = 0
		self.callback_data = None
		self.response_code = None
		self.response_description = None
		self.failed_at = None
		
		# Call STK push again
		from frappe_mpesa.api.mpesa_express import initiate_stk_push
		result = initiate_stk_push(
			phone_number=self.phone_number,
			amount=self.amount,
			account_reference=self.account_reference,
			transaction_desc=self.transaction_desc,
			sales_invoice=self.sales_invoice
		)
		
		if result.get("success"):
			self.checkout_request_id = result.get("checkout_request_id")
			self.merchant_request_id = result.get("merchant_request_id")
			self.save(ignore_permissions=True)
			frappe.msgprint(_("Transaction retry initiated successfully"))
		else:
			frappe.throw(_("Failed to retry transaction: {0}").format(result.get("message")))


@frappe.whitelist()
def retry_mpesa_transaction(transaction_name):
	"""Retry a failed Mpesa transaction"""
	doc = frappe.get_doc("Mpesa Express Transaction", transaction_name)
	doc.retry_transaction()
	return {"success": True, "message": "Transaction retry initiated"}


@frappe.whitelist()
def check_transaction_status(transaction_name):
	"""Check the current status of a transaction"""
	doc = frappe.get_doc("Mpesa Express Transaction", transaction_name)
	return {
		"name": doc.name,
		"status": doc.status,
		"phone_number": doc.phone_number,
		"amount": doc.amount,
		"mpesa_receipt_number": doc.mpesa_receipt_number,
		"callback_received": doc.callback_received
	}