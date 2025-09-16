# Copyright (c) 2025, Njoroge Francis and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import now, flt
import json


class MpesaB2CTransaction(Document):
	def validate(self):
		"""Validate B2C transaction"""
		self.validate_transaction_data()
		
	def validate_transaction_data(self):
		"""Validate required transaction data"""
		if self.amount <= 0:
			frappe.throw(_("Amount must be greater than zero"))
			
		if not self.phone_number:
			frappe.throw(_("Phone number is required"))
			
		if not self.transaction_id:
			frappe.throw(_("Transaction ID is required"))
		
		# Validate phone number format
		from frappe_mpesa.utils import format_phone_number
		try:
			self.phone_number = format_phone_number(self.phone_number)
		except Exception as e:
			frappe.throw(_("Invalid phone number format: {0}").format(str(e)))
	
	def before_insert(self):
		"""Set default values before insert"""
		if not self.initiated_at:
			self.initiated_at = now()
		
		if not self.status:
			self.status = "Initiated"
	
	def update_from_callback(self, callback_data):
		"""Update transaction from Mpesa callback"""
		try:
			result = callback_data.get('Result', {})
			
			self.result_type = result.get('ResultType')
			self.result_code = result.get('ResultCode')
			self.result_desc = result.get('ResultDesc')
			self.originator_conversation_id = result.get('OriginatorConversationID')
			self.conversation_id = result.get('ConversationID')
			self.transaction_id = result.get('TransactionID')
			
			# Update status based on result code
			if self.result_code == '0':
				self.status = "Completed"
				self.completed_at = now()
				
				# Extract additional details from callback metadata
				result_parameters = result.get('ResultParameters', {}).get('ResultParameter', [])
				for param in result_parameters:
					key = param.get('Key')
					value = param.get('Value')
					
					if key == 'TransactionAmount':
						self.transaction_amount = flt(value)
					elif key == 'TransactionReceipt':
						self.transaction_receipt = value
					elif key == 'ReceiverPartyPublicName':
						self.receiver_party_public_name = value
					elif key == 'TransactionCompletedDateTime':
						# Parse the datetime if needed
						self.transaction_completed_date = value
					elif key == 'B2CUtilityAccountAvailableFunds':
						# Log available funds for monitoring
						frappe.log_error(f"B2C Available Funds: {value}", "Mpesa B2C Funds")
					elif key == 'B2CWorkingAccountAvailableFunds':
						# Log working account funds
						frappe.log_error(f"B2C Working Funds: {value}", "Mpesa B2C Funds")
			else:
				self.status = "Failed"
				self.completed_at = now()
			
			# Store raw callback data
			self.callback_response = json.dumps(callback_data, indent=2)
			
			# Save the document
			self.save(ignore_permissions=True)
			
			# Create corresponding payment entry if successful
			if self.result_code == '0' and self.reference_doctype and self.reference_name:
				self.create_payment_entry()
			
		except Exception as e:
			frappe.log_error(f"Error updating B2C transaction from callback: {str(e)}", 
				"Mpesa B2C Callback Error")
			self.status = "Failed"
			self.result_desc = f"Callback processing error: {str(e)}"
			self.save(ignore_permissions=True)
	
	def create_payment_entry(self):
		"""Create payment entry for successful B2C transaction"""
		try:
			settings = frappe.get_single("Mpesa Settings")
			
			if not settings.expense_account_head:
				frappe.log_error("Expense account head not configured in Mpesa Settings", 
					"Mpesa B2C Payment Entry")
				return
			
			# Check if payment entry already exists
			existing_payment = frappe.db.exists("Payment Entry", {
				"reference_no": self.transaction_receipt or self.transaction_id
			})
			
			if existing_payment:
				frappe.log_error(f"Payment entry already exists for B2C transaction: {self.transaction_id}", 
					"Mpesa B2C Payment Entry")
				return
			
			# Determine the reference document details
			reference_doc = None
			if self.reference_doctype and self.reference_name:
				reference_doc = frappe.get_doc(self.reference_doctype, self.reference_name)
			
			# Create payment entry
			payment_entry = frappe.new_doc("Payment Entry")
			payment_entry.payment_type = "Pay"
			
			# Set party details based on reference document
			if reference_doc:
				if self.reference_doctype == "Purchase Invoice":
					payment_entry.party_type = "Supplier"
					payment_entry.party = reference_doc.supplier
					payment_entry.paid_from = reference_doc.credit_to
				elif self.reference_doctype == "Salary Slip":
					payment_entry.party_type = "Employee"
					payment_entry.party = reference_doc.employee
					# Use default payable account for employee
					company = reference_doc.company
					payable_account = frappe.get_value("Company", company, "default_payable_account")
					payment_entry.paid_from = payable_account
				else:
					# Generic handling
					payment_entry.party_type = "Supplier"  # Default to supplier
					payment_entry.party = self.recipient_name
			else:
				# Create without specific party
				payment_entry.party_type = "Supplier"
				payment_entry.party = self.recipient_name
			
			payment_entry.posting_date = self.transaction_completed_date or self.completed_at.date()
			payment_entry.paid_to = settings.expense_account_head
			payment_entry.paid_amount = self.transaction_amount or self.amount
			payment_entry.received_amount = self.transaction_amount or self.amount
			payment_entry.reference_no = self.transaction_receipt or self.transaction_id
			payment_entry.reference_date = self.transaction_completed_date or self.completed_at.date()
			payment_entry.mode_of_payment = "Mpesa"
			payment_entry.remarks = f"Mpesa B2C payment to {self.recipient_name} - {self.phone_number} - Receipt: {self.transaction_receipt or self.transaction_id}"
			
			# Add reference to original document if exists
			if reference_doc:
				payment_entry.append("references", {
					"reference_doctype": self.reference_doctype,
					"reference_name": self.reference_name,
					"allocated_amount": self.transaction_amount or self.amount
				})
			
			payment_entry.insert(ignore_permissions=True)
			payment_entry.submit()
			
			frappe.log_error(f"B2C Payment entry created: {payment_entry.name} for transaction: {self.transaction_id}", 
				"Mpesa B2C Payment Success")
			
		except Exception as e:
			frappe.log_error(f"Error creating B2C payment entry: {str(e)}", "Mpesa B2C Payment Entry Error")
	
	def get_status_color(self):
		"""Get status indicator color"""
		status_colors = {
			"Initiated": "blue",
			"Pending": "orange", 
			"Completed": "green",
			"Failed": "red",
			"Timeout": "grey"
		}
		return status_colors.get(self.status, "grey")