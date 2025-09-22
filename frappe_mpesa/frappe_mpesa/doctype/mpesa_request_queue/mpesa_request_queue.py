# Copyright (c) 2025, Njoroge Francis and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import now_datetime, add_to_date
import json


class MpesaRequestQueue(Document):
	def validate(self):
		"""Validate queue item before saving"""
		self.validate_request_data()
		self.validate_retry_settings()

	def validate_request_data(self):
		"""Validate that request data is valid JSON"""
		if self.request_data:
			try:
				json.loads(self.request_data)
			except json.JSONDecodeError:
				frappe.throw(_("Request data must be valid JSON"))

	def validate_retry_settings(self):
		"""Validate retry configuration"""
		if self.max_retries < 0:
			frappe.throw(_("Max retries cannot be negative"))

		if self.retry_count > self.max_retries:
			frappe.throw(_("Retry count cannot exceed max retries"))

		if not self.next_retry_at:
			self.next_retry_at = now_datetime()

	def before_save(self):
		"""Set default values before saving"""
		if self.is_new():
			if not self.next_retry_at:
				self.next_retry_at = now_datetime()

	def retry_request(self):
		"""Manually retry this queued request"""
		if self.status in ["Completed", "Failed"]:
			if self.retry_count >= self.max_retries:
				frappe.throw(_("Cannot retry: Maximum retry attempts exceeded"))

		# Reset for retry
		self.status = "Queued"
		self.next_retry_at = now_datetime()
		self.error_message = ""
		self.save()

		frappe.msgprint(_("Request queued for retry"))

	def get_request_data_dict(self):
		"""Get request data as dictionary"""
		if not self.request_data:
			return {}

		try:
			return json.loads(self.request_data)
		except json.JSONDecodeError:
			return {}

	def set_request_data_dict(self, data_dict):
		"""Set request data from dictionary"""
		self.request_data = json.dumps(data_dict, indent=2)

	def get_response_data_dict(self):
		"""Get response data as dictionary"""
		if not self.response_data:
			return {}

		try:
			return json.loads(self.response_data)
		except json.JSONDecodeError:
			return {}

	def mark_completed(self, response_data=None):
		"""Mark request as completed"""
		self.status = "Completed"
		self.completed_at = now_datetime()

		if response_data:
			self.response_data = json.dumps(response_data, indent=2)

		self.save()

	def mark_failed(self, error_message, schedule_retry=True):
		"""Mark request as failed and optionally schedule retry"""
		self.retry_count += 1
		self.error_message = error_message
		self.last_retry_at = now_datetime()

		if schedule_retry and self.retry_count < self.max_retries:
			# Schedule for retry with exponential backoff
			backoff_delay = min(300, 30 * (2 ** (self.retry_count - 1)))  # Max 5 minutes
			self.next_retry_at = add_to_date(now_datetime(), seconds=backoff_delay)
			self.status = "Retrying"
		else:
			# Mark as permanently failed
			self.status = "Failed"
			self.failed_at = now_datetime()

		self.save()

	@staticmethod
	def get_queue_statistics():
		"""Get queue statistics"""
		stats = {}

		# Count by status
		for status in ["Queued", "Retrying", "Completed", "Failed"]:
			count = frappe.db.count("Mpesa Request Queue", {"status": status})
			stats[status.lower()] = count

		# Count by priority
		for priority in ["1", "2", "3"]:
			count = frappe.db.count("Mpesa Request Queue", {
				"priority": priority,
				"status": ["in", ["Queued", "Retrying"]]
			})
			stats[f"priority_{priority}"] = count

		# Count by request type
		request_types = frappe.db.sql("""
			SELECT request_type, COUNT(*) as count
			FROM `tabMpesa Request Queue`
			WHERE status IN ('Queued', 'Retrying')
			GROUP BY request_type
		""", as_dict=True)

		stats["by_type"] = {item["request_type"]: item["count"] for item in request_types}

		return stats


@frappe.whitelist()
def retry_queue_item(queue_item_name):
	"""Retry a specific queue item"""
	queue_item = frappe.get_doc("Mpesa Request Queue", queue_item_name)
	queue_item.retry_request()
	return {"success": True, "message": _("Request queued for retry")}


@frappe.whitelist()
def get_queue_statistics():
	"""Get queue statistics for dashboard"""
	return MpesaRequestQueue.get_queue_statistics()


@frappe.whitelist()
def bulk_retry_failed():
	"""Retry all failed requests that can be retried"""
	failed_items = frappe.get_all(
		"Mpesa Request Queue",
		filters={
			"status": "Failed",
			"retry_count": ["<", "max_retries"]
		},
		fields=["name"]
	)

	retried_count = 0
	for item in failed_items:
		try:
			queue_item = frappe.get_doc("Mpesa Request Queue", item.name)
			queue_item.retry_request()
			retried_count += 1
		except Exception as e:
			frappe.log_error(f"Failed to retry queue item {item.name}: {str(e)}", "Bulk Retry Error")

	return {
		"success": True,
		"message": _("Retried {0} failed requests").format(retried_count),
		"retried_count": retried_count
	}


@frappe.whitelist()
def cleanup_old_queue_items(days=30):
	"""Clean up old completed/failed queue items"""
	cutoff_date = add_to_date(now_datetime(), days=-int(days))

	deleted_count = frappe.db.sql("""
		DELETE FROM `tabMpesa Request Queue`
		WHERE status IN ('Completed', 'Failed')
		AND (completed_at < %s OR failed_at < %s)
	""", (cutoff_date, cutoff_date))

	frappe.db.commit()
	deleted_count = deleted_count[0] if deleted_count else 0

	return {
		"success": True,
		"message": _("Cleaned up {0} old queue items").format(deleted_count),
		"deleted_count": deleted_count
	}