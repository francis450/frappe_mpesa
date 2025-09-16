# Copyright (c) 2025, Njoroge Francis and contributors
# For license information, please see license.txt

import frappe
from frappe import _
import base64
import hashlib
from datetime import datetime
import secrets
import string


def get_mpesa_settings():
	"""Get Mpesa Settings singleton"""
	return frappe.get_single("Mpesa Settings")


def generate_password(shortcode, passkey, timestamp):
	"""Generate password for Mpesa Express API"""
	data_to_encode = f"{shortcode}{passkey}{timestamp}"
	encoded_string = base64.b64encode(data_to_encode.encode()).decode('utf-8')
	return encoded_string


def generate_timestamp():
	"""Generate timestamp in the format required by Mpesa API"""
	return datetime.now().strftime('%Y%m%d%H%M%S')


def format_phone_number(phone_number):
	"""Format phone number to Mpesa format (254XXXXXXXXX)"""
	if not phone_number:
		return None
		
	# Remove any non-digit characters
	phone = ''.join(filter(str.isdigit, phone_number))
	
	# Handle different formats
	if phone.startswith('254'):
		return phone
	elif phone.startswith('0'):
		return '254' + phone[1:]
	elif phone.startswith('7') or phone.startswith('1'):
		return '254' + phone
	else:
		frappe.throw(_("Invalid phone number format: {0}").format(phone_number))


def validate_amount(amount):
	"""Validate amount for Mpesa transactions"""
	try:
		amount_float = float(amount)
		if amount_float <= 0:
			frappe.throw(_("Amount must be greater than zero"))
		if amount_float > 70000:  # Mpesa daily limit
			frappe.throw(_("Amount exceeds Mpesa daily limit of KES 70,000"))
		return int(amount_float)  # Mpesa expects integer amounts
	except (ValueError, TypeError):
		frappe.throw(_("Invalid amount: {0}").format(amount))


def generate_transaction_id(prefix="MP"):
	"""Generate unique transaction ID"""
	timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
	random_part = ''.join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(6))
	return f"{prefix}{timestamp}{random_part}"


def log_mpesa_transaction(transaction_type, request_data, response_data, status="Pending"):
	"""Log Mpesa transaction for audit trail"""
	try:
		# This will be implemented when we create the transaction log doctype
		frappe.logger().info(f"Mpesa {transaction_type}: {request_data} -> {response_data}")
	except Exception as e:
		frappe.log_error(f"Failed to log transaction: {str(e)}", "Mpesa Transaction Log")


def get_error_message(error_code):
	"""Get user-friendly error messages for Mpesa error codes"""
	error_messages = {
		"0": "Success",
		"1": "Insufficient Funds",
		"2": "Less Than Minimum Transaction Value",
		"3": "More Than Maximum Transaction Value", 
		"4": "Would Exceed Daily Transfer Limit",
		"5": "Would Exceed Minimum Balance",
		"6": "Unresolved Primary Party",
		"7": "Unresolved Receiver Party",
		"8": "Would Exceed Maximum Balance",
		"11": "Debit Account Invalid",
		"12": "Credit Account Invalid",
		"13": "Unresolved Debit Account",
		"14": "Unresolved Credit Account",
		"15": "Duplicate Detected",
		"17": "Internal Failure",
		"20": "Unresolved Initiator",
		"26": "Traffic blocking condition in place",
		"1001": "Duplicate Transaction",
		"1019": "Invalid Initator Identifier",
		"1032": "Request cancelled by user",
		"1037": "DS timeout",
	}
	
	return error_messages.get(str(error_code), f"Unknown error code: {error_code}")


def is_valid_mpesa_receipt(receipt_id):
	"""Validate Mpesa receipt ID format"""
	if not receipt_id:
		return False
		
	# Mpesa receipt IDs are typically 10 characters alphanumeric
	if len(receipt_id) < 8 or len(receipt_id) > 12:
		return False
		
	return receipt_id.isalnum()


def sanitize_callback_data(data):
	"""Sanitize callback data from Mpesa"""
	if isinstance(data, dict):
		sanitized = {}
		for key, value in data.items():
			if isinstance(value, (dict, list)):
				sanitized[key] = sanitize_callback_data(value)
			else:
				sanitized[key] = str(value) if value is not None else ""
		return sanitized
	elif isinstance(data, list):
		return [sanitize_callback_data(item) for item in data]
	else:
		return str(data) if data is not None else ""