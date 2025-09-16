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
	generate_transaction_id,
	log_mpesa_transaction
)


class MpesaB2C(MpesaAPIBase):
	"""Mpesa B2C (Business to Customer) API implementation"""
	
	def __init__(self):
		super().__init__()
	
	def initiate_payment(self, phone_number, amount, command_id="BusinessPayment", 
						 remarks=None, occasion=None, recipient_name=None,
						 reference_doctype=None, reference_name=None):
		"""Initiate B2C payment"""
		
		# Validate inputs
		phone_number = format_phone_number(phone_number)
		amount = validate_amount(amount)
		
		if not remarks:
			remarks = f"B2C Payment to {phone_number}"
		if not occasion:
			occasion = "Payment"
		
		# Validate command ID
		valid_commands = ["BusinessPayment", "SalaryPayment", "PromotionPayment"]
		if command_id not in valid_commands:
			frappe.throw(_("Invalid command ID. Must be one of: {0}").format(", ".join(valid_commands)))
		
		# Validate required B2C settings
		if not self.settings.initiator_name:
			frappe.throw(_("Initiator name is required for B2C transactions"))
		if not self.settings.security_credential:
			frappe.throw(_("Security credential is required for B2C transactions"))
		
		# Generate transaction ID
		transaction_id = generate_transaction_id("B2C")
		
		# Set result and queue timeout URLs
		from frappe.utils import get_url
		from urllib.parse import urljoin
		site_url = get_url()
		result_url = urljoin(site_url, "/api/method/frappe_mpesa.api.webhook_handlers.b2c_result_callback")
		queue_timeout_url = urljoin(site_url, "/api/method/frappe_mpesa.api.webhook_handlers.b2c_timeout_callback")
		
		# Prepare request data
		request_data = {
			"InitiatorName": self.settings.initiator_name,
			"SecurityCredential": self.settings.get_password('security_credential'),
			"CommandID": command_id,
			"Amount": amount,
			"PartyA": self.settings.shortcode,
			"PartyB": phone_number,
			"Remarks": remarks,
			"QueueTimeOutURL": queue_timeout_url,
			"ResultURL": result_url,
			"Occasion": occasion
		}
		
		try:
			# Create B2C transaction record first
			b2c_transaction = frappe.new_doc("Mpesa B2C Transaction")
			b2c_transaction.transaction_id = transaction_id
			b2c_transaction.amount = amount
			b2c_transaction.phone_number = phone_number
			b2c_transaction.command_id = command_id
			b2c_transaction.recipient_name = recipient_name
			b2c_transaction.reference_doctype = reference_doctype
			b2c_transaction.reference_name = reference_name
			b2c_transaction.remarks = remarks
			b2c_transaction.occasion = occasion
			b2c_transaction.status = "Initiated"
			b2c_transaction.insert(ignore_permissions=True)
			
			# Make API request
			response = self.make_request(
				endpoint=self.settings.b2c_url,
				data=request_data,
				method="POST"
			)
			
			# Validate response
			self.validate_response(response, ["ResponseCode", "ResponseDescription"])
			
			# Update transaction with response data
			b2c_transaction.originator_conversation_id = response.get("OriginatorConversationID")
			b2c_transaction.conversation_id = response.get("ConversationID")
			b2c_transaction.raw_response_data = json.dumps(response, indent=2)
			
			if response.get("ResponseCode") == "0":
				b2c_transaction.status = "Pending"
			else:
				b2c_transaction.status = "Failed"
				b2c_transaction.result_desc = response.get("ResponseDescription")
			
			b2c_transaction.save(ignore_permissions=True)
			frappe.db.commit()
			
			return {
				"success": True,
				"transaction_id": transaction_id,
				"originator_conversation_id": response.get("OriginatorConversationID"),
				"conversation_id": response.get("ConversationID"),
				"response_code": response.get("ResponseCode"),
				"response_description": response.get("ResponseDescription"),
				"request_data": request_data,
				"response_data": response
			}
			
		except Exception as e:
			error_msg = str(e)
			frappe.log_error(f"B2C payment failed: {error_msg}", "Mpesa B2C")
			
			# Update transaction status to failed if it was created
			try:
				if 'b2c_transaction' in locals():
					b2c_transaction.status = "Failed"
					b2c_transaction.result_desc = error_msg
					b2c_transaction.save(ignore_permissions=True)
					frappe.db.commit()
			except:
				pass
			
			return {
				"success": False,
				"message": error_msg,
				"request_data": request_data
			}


@frappe.whitelist()
def initiate_b2c_payment(phone_number, amount, command_id="BusinessPayment", 
						 remarks=None, occasion=None, recipient_name=None,
						 reference_doctype=None, reference_name=None):
	"""Initiate B2C payment and create transaction record"""
	
	try:
		# Create Mpesa B2C instance
		mpesa_b2c = MpesaB2C()
		
		# Initiate payment
		result = mpesa_b2c.initiate_payment(
			phone_number=phone_number,
			amount=amount,
			command_id=command_id,
			remarks=remarks,
			occasion=occasion,
			recipient_name=recipient_name,
			reference_doctype=reference_doctype,
			reference_name=reference_name
		)
		
		if result.get("success"):
			frappe.msgprint(_("B2C payment initiated successfully. Transaction ID: {0}").format(
				result.get("transaction_id")))
		else:
			frappe.throw(_("Failed to initiate B2C payment: {0}").format(result.get("message")))
		
		return result
		
	except Exception as e:
		frappe.log_error(f"B2C payment initiation error: {str(e)}", "Mpesa B2C Initiation")
		frappe.throw(_("Error initiating B2C payment: {0}").format(str(e)))


@frappe.whitelist()
def pay_supplier(supplier, amount, purchase_invoice=None, remarks=None):
	"""Pay supplier via B2C"""
	try:
		# Get supplier details
		supplier_doc = frappe.get_doc("Supplier", supplier)
		
		if not supplier_doc.mobile_no:
			frappe.throw(_("Supplier {0} does not have a mobile number").format(supplier))
		
		# Set default remarks
		if not remarks:
			if purchase_invoice:
				remarks = f"Payment for Purchase Invoice {purchase_invoice}"
			else:
				remarks = f"Payment to {supplier_doc.supplier_name}"
		
		# Initiate B2C payment
		result = initiate_b2c_payment(
			phone_number=supplier_doc.mobile_no,
			amount=amount,
			command_id="BusinessPayment",
			remarks=remarks,
			recipient_name=supplier_doc.supplier_name,
			reference_doctype="Purchase Invoice" if purchase_invoice else None,
			reference_name=purchase_invoice
		)
		
		return result
		
	except Exception as e:
		frappe.log_error(f"Supplier payment error: {str(e)}", "Mpesa B2C Supplier Payment")
		frappe.throw(_("Error paying supplier: {0}").format(str(e)))


@frappe.whitelist()
def pay_employee_salary(employee, amount, salary_slip=None, remarks=None):
	"""Pay employee salary via B2C"""
	try:
		# Get employee details
		employee_doc = frappe.get_doc("Employee", employee)
		
		if not employee_doc.cell_number:
			frappe.throw(_("Employee {0} does not have a mobile number").format(employee))
		
		# Set default remarks
		if not remarks:
			if salary_slip:
				remarks = f"Salary payment for {salary_slip}"
			else:
				remarks = f"Salary payment to {employee_doc.employee_name}"
		
		# Initiate B2C payment
		result = initiate_b2c_payment(
			phone_number=employee_doc.cell_number,
			amount=amount,
			command_id="SalaryPayment",
			remarks=remarks,
			recipient_name=employee_doc.employee_name,
			reference_doctype="Salary Slip" if salary_slip else None,
			reference_name=salary_slip
		)
		
		return result
		
	except Exception as e:
		frappe.log_error(f"Employee salary payment error: {str(e)}", "Mpesa B2C Salary Payment")
		frappe.throw(_("Error paying employee salary: {0}").format(str(e)))