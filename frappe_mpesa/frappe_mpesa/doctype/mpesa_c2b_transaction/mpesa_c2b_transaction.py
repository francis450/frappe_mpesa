# Copyright (c) 2025, Njoroge Francis and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import now, flt, get_datetime
import json


class MpesaC2BTransaction(Document):
	def validate(self):
		"""Validate C2B transaction"""
		self.validate_transaction_data()
		self.check_for_duplicates()
		
	def validate_transaction_data(self):
		"""Validate required transaction data"""
		if self.amount <= 0:
			frappe.throw(_("Amount must be greater than zero"))
			
		if not self.phone_number:
			frappe.throw(_("Phone number is required"))
			
		if not self.trans_id:
			frappe.throw(_("Transaction ID is required"))
	
	def check_for_duplicates(self):
		"""Check for duplicate transactions"""
		if self.is_new():
			existing = frappe.db.exists("Mpesa C2B Transaction", {
				"trans_id": self.trans_id,
				"name": ["!=", self.name]
			})
			
			if existing:
				self.status = "Duplicate"
				frappe.log_error(f"Duplicate C2B transaction: {self.trans_id}", "Mpesa C2B Duplicate")
	
	def after_insert(self):
		"""Process transaction after insert"""
		if self.status == "Received":
			self.process_transaction()
	
	def process_transaction(self):
		"""Process the C2B transaction"""
		try:
			self.status = "Processing"
			self.save(ignore_permissions=True)
			
			# Try to match with existing sales invoice
			sales_invoice = self.find_matching_invoice()
			
			if sales_invoice:
				self.sales_invoice = sales_invoice.name
				self.create_payment_entry(sales_invoice)
			else:
				# Create payment entry without invoice
				self.create_payment_entry()
			
			self.status = "Completed"
			self.processed_at = now()
			self.save(ignore_permissions=True)
			
		except Exception as e:
			self.status = "Failed"
			self.notes = f"Processing failed: {str(e)}"
			self.processed_at = now()
			self.save(ignore_permissions=True)
			frappe.log_error(f"C2B processing failed: {str(e)}", "Mpesa C2B Processing")
	
	def find_matching_invoice(self):
		"""Find matching sales invoice based on bill reference or invoice number"""
		if not self.bill_ref_number and not self.invoice_number:
			return None
		
		# Try to find by invoice number first
		if self.invoice_number:
			invoice = frappe.db.exists("Sales Invoice", {
				"name": self.invoice_number,
				"docstatus": 1,
				"outstanding_amount": [">", 0]
			})
			if invoice:
				return frappe.get_doc("Sales Invoice", invoice)
		
		# Try to find by bill reference number
		if self.bill_ref_number:
			# Search in sales invoice name or custom field
			invoice = frappe.db.exists("Sales Invoice", {
				"name": self.bill_ref_number,
				"docstatus": 1,
				"outstanding_amount": [">", 0]
			})
			if invoice:
				return frappe.get_doc("Sales Invoice", invoice)
			
			# Search in customer field if bill reference matches phone number
			customer = frappe.db.exists("Customer", {
				"mobile_no": self.phone_number
			})
			if customer:
				invoices = frappe.get_all("Sales Invoice", 
					filters={
						"customer": customer,
						"docstatus": 1,
						"outstanding_amount": [">", 0]
					},
					order_by="creation desc",
					limit=1
				)
				if invoices:
					return frappe.get_doc("Sales Invoice", invoices[0].name)
		
		return None
	
	def create_payment_entry(self, sales_invoice=None):
		"""Create payment entry for the C2B transaction"""
		settings = frappe.get_single("Mpesa Settings")
		
		if not settings.default_account_head:
			frappe.throw(_("Default account head not configured in Mpesa Settings"))
		
		# Check if payment entry already exists
		existing_payment = frappe.db.exists("Payment Entry", {
			"reference_no": self.trans_id
		})
		
		if existing_payment:
			self.payment_entry = existing_payment
			return
		
		# Create payment entry
		payment_entry = frappe.new_doc("Payment Entry")
		payment_entry.payment_type = "Receive"
		payment_entry.party_type = "Customer"
		
		# Determine customer
		if sales_invoice:
			payment_entry.party = sales_invoice.customer
			payment_entry.paid_to = sales_invoice.debit_to
		else:
			# Find customer by phone number or create default customer
			customer = self.get_or_create_customer()
			payment_entry.party = customer
			# Use default receivable account
			company = frappe.defaults.get_user_default("Company")
			receivable_account = frappe.get_value("Company", company, "default_receivable_account")
			payment_entry.paid_to = receivable_account
		
		payment_entry.posting_date = get_datetime(self.trans_time).date()
		payment_entry.paid_from = settings.default_account_head
		payment_entry.paid_amount = self.amount
		payment_entry.received_amount = self.amount
		payment_entry.reference_no = self.trans_id
		payment_entry.reference_date = get_datetime(self.trans_time).date()
		payment_entry.mode_of_payment = "Mpesa"
		
		# Set remarks
		payer_name = f"{self.first_name or ''} {self.middle_name or ''} {self.last_name or ''}".strip()
		payment_entry.remarks = f"Mpesa C2B payment from {payer_name} - {self.phone_number} - Receipt: {self.trans_id}"
		
		# Add reference to sales invoice if exists
		if sales_invoice:
			allocated_amount = min(self.amount, sales_invoice.outstanding_amount)
			payment_entry.append("references", {
				"reference_doctype": "Sales Invoice",
				"reference_name": sales_invoice.name,
				"allocated_amount": allocated_amount
			})
		
		payment_entry.insert(ignore_permissions=True)
		payment_entry.submit()
		
		self.payment_entry = payment_entry.name
		
		frappe.log_error(f"Payment entry created: {payment_entry.name} for C2B transaction: {self.trans_id}", 
			"Mpesa C2B Payment Success")
	
	def get_or_create_customer(self):
		"""Get existing customer or create new one based on phone number"""
		# Try to find existing customer by phone number
		customer = frappe.db.get_value("Customer", {"mobile_no": self.phone_number}, "name")
		
		if customer:
			return customer
		
		# Create new customer
		payer_name = f"{self.first_name or ''} {self.middle_name or ''} {self.last_name or ''}".strip()
		if not payer_name:
			payer_name = f"Customer {self.phone_number}"
		
		customer_doc = frappe.new_doc("Customer")
		customer_doc.customer_name = payer_name
		customer_doc.mobile_no = self.phone_number
		customer_doc.customer_group = "Individual"  # Default customer group
		customer_doc.territory = "Kenya"  # Default territory
		customer_doc.insert(ignore_permissions=True)
		
		return customer_doc.name