# Copyright (c) 2025, Njoroge Francis and contributors
# For license information, please see license.txt

import frappe
from frappe import _
import json
from datetime import datetime
from frappe_mpesa.api import MpesaAPIBase
from frappe_mpesa.utils import get_mpesa_settings, log_mpesa_transaction


class MpesaC2B(MpesaAPIBase):
	"""Mpesa C2B (Customer to Business) API implementation"""
	
	def __init__(self):
		super().__init__()
	
	def register_urls(self, validation_url=None, confirmation_url=None):
		"""Register C2B validation and confirmation URLs with Mpesa"""
		
		if not validation_url:
			validation_url = self.settings.validation_url
		if not confirmation_url:
			confirmation_url = self.settings.confirmation_url
		
		if not validation_url or not confirmation_url:
			frappe.throw(_("Validation and Confirmation URLs are required for C2B registration"))
		
		# Prepare request data
		request_data = {
			"ShortCode": self.settings.shortcode,
			"ResponseType": "Completed",  # or "Cancelled"
			"ConfirmationURL": confirmation_url,
			"ValidationURL": validation_url
		}
		
		try:
			# Make API request
			response = self.make_request(
				endpoint=self.settings.c2b_register_url,
				data=request_data,
				method="POST"
			)
			
			# Validate response
			self.validate_response(response, ["ResponseCode", "ResponseDescription"])
			
			return {
				"success": True,
				"response_code": response.get("ResponseCode"),
				"response_description": response.get("ResponseDescription"),
				"request_data": request_data,
				"response_data": response
			}
			
		except Exception as e:
			error_msg = str(e)
			frappe.log_error(f"C2B URL registration failed: {error_msg}", "Mpesa C2B")
			
			return {
				"success": False,
				"message": error_msg,
				"request_data": request_data
			}
	
	def simulate_c2b_payment(self, phone_number, amount, bill_ref_number=None):
		"""Simulate C2B payment (for testing in sandbox environment)"""
		
		if self.settings.environment != "Sandbox":
			frappe.throw(_("C2B simulation is only available in Sandbox environment"))
		
		from frappe_mpesa.utils import format_phone_number, validate_amount
		
		# Validate inputs
		phone_number = format_phone_number(phone_number)
		amount = validate_amount(amount)
		
		# Prepare request data
		request_data = {
			"ShortCode": self.settings.shortcode,
			"CommandID": "CustomerPayBillOnline",  # or "CustomerBuyGoodsOnline"
			"Amount": amount,
			"Msisdn": phone_number,
			"BillRefNumber": bill_ref_number or "TEST"
		}
		
		try:
			# Make API request
			response = self.make_request(
				endpoint=self.settings.c2b_simulate_url,
				data=request_data,
				method="POST"
			)
			
			return {
				"success": True,
				"response_data": response,
				"request_data": request_data
			}
			
		except Exception as e:
			error_msg = str(e)
			frappe.log_error(f"C2B simulation failed: {error_msg}", "Mpesa C2B Simulation")
			
			return {
				"success": False,
				"message": error_msg,
				"request_data": request_data
			}


@frappe.whitelist()
def register_c2b_urls():
	"""Register C2B URLs with Mpesa"""
	try:
		c2b = MpesaC2B()
		result = c2b.register_urls()
		
		if result.get("success"):
			frappe.msgprint(_("C2B URLs registered successfully"))
		else:
			frappe.throw(_("Failed to register C2B URLs: {0}").format(result.get("message")))
		
		return result
		
	except Exception as e:
		frappe.log_error(f"C2B URL registration error: {str(e)}", "Mpesa C2B Registration")
		frappe.throw(_("Error registering C2B URLs: {0}").format(str(e)))


@frappe.whitelist()
def simulate_c2b_payment(phone_number, amount, bill_ref_number=None):
	"""Simulate C2B payment for testing"""
	try:
		c2b = MpesaC2B()
		result = c2b.simulate_c2b_payment(phone_number, amount, bill_ref_number)
		
		if result.get("success"):
			frappe.msgprint(_("C2B payment simulated successfully"))
		else:
			frappe.throw(_("Failed to simulate C2B payment: {0}").format(result.get("message")))
		
		return result
		
	except Exception as e:
		frappe.log_error(f"C2B simulation error: {str(e)}", "Mpesa C2B Simulation")
		frappe.throw(_("Error simulating C2B payment: {0}").format(str(e)))