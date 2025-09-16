# Copyright (c) 2025, Njoroge Francis and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import now_datetime, add_to_date
from frappe_mpesa.auth import mpesa_auth
from frappe_mpesa.utils import get_mpesa_settings


def monitor_auth_health():
	"""Monitor authentication health and log status"""
	try:
		settings = get_mpesa_settings()
		if not settings.is_enabled:
			return
			
		status = mpesa_auth.get_token_status()
		
		# Log token status for monitoring
		frappe.logger().info(f"Mpesa Auth Health Check: {status}")
		
		# Alert if token will expire soon (less than 30 minutes)
		if status.get('cached') and status.get('time_remaining_seconds', 0) < 1800:
			frappe.logger().warning("Mpesa access token expires in less than 30 minutes")
			
		# Test authentication if no valid token
		if not status.get('is_valid'):
			test_result = mpesa_auth.test_authentication()
			if not test_result.get('success'):
				frappe.log_error(
					f"Mpesa authentication test failed: {test_result.get('message')}", 
					"Mpesa Auth Health"
				)
				
	except Exception as e:
		frappe.log_error(f"Error in Mpesa auth health check: {str(e)}", "Mpesa Auth Health")


def cleanup_auth_logs():
	"""Clean up old authentication logs"""
	try:
		# Clean up error logs older than 30 days
		cutoff_date = add_to_date(now_datetime(), days=-30)
		
		frappe.db.sql("""
			DELETE FROM `tabError Log` 
			WHERE creation < %s 
			AND error LIKE '%Mpesa Auth%'
		""", cutoff_date)
		
		frappe.db.commit()
		frappe.logger().info("Cleaned up old Mpesa authentication logs")
		
	except Exception as e:
		frappe.log_error(f"Error cleaning up auth logs: {str(e)}", "Mpesa Auth Cleanup")


def refresh_token_if_needed():
	"""Proactively refresh token if it's close to expiring"""
	try:
		settings = get_mpesa_settings()
		if not settings.is_enabled:
			return
			
		status = mpesa_auth.get_token_status()
		
		# Refresh token if it expires in less than 10 minutes
		if status.get('cached') and status.get('time_remaining_seconds', 0) < 600:
			frappe.logger().info("Proactively refreshing Mpesa access token")
			mpesa_auth.get_access_token(force_refresh=True)
			
	except Exception as e:
		frappe.log_error(f"Error in proactive token refresh: {str(e)}", "Mpesa Auth Refresh")