# Copyright (c) 2025, Njoroge Francis and contributors
# For license information, please see license.txt

import frappe
from frappe import _
import json
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from frappe.utils import now_datetime, add_to_date, get_datetime
from frappe_mpesa.utils.resilience import get_resilient_requester, RetryableError, NonRetryableError


class RequestQueue:
    """Manages queued requests for retry processing during network interruptions"""

    def __init__(self):
        self.queue_doctype = "Mpesa Request Queue"

    def enqueue_request(self,
                       request_type: str,
                       endpoint: str,
                       data: Dict[str, Any],
                       method: str = "POST",
                       priority: int = 1,
                       reference_doctype: Optional[str] = None,
                       reference_name: Optional[str] = None,
                       max_retries: int = 5) -> str:
        """
        Queue a request for later processing

        Args:
            request_type: Type of request (e.g., 'stk_push', 'b2c_payment')
            endpoint: API endpoint to call
            data: Request payload
            method: HTTP method
            priority: Priority level (1=high, 2=normal, 3=low)
            reference_doctype: Reference document type
            reference_name: Reference document name
            max_retries: Maximum retry attempts

        Returns:
            Queue item name
        """
        try:
            queue_item = frappe.new_doc(self.queue_doctype)
            queue_item.request_type = request_type
            queue_item.endpoint = endpoint
            queue_item.request_data = json.dumps(data)
            queue_item.method = method
            queue_item.priority = priority
            queue_item.reference_doctype = reference_doctype
            queue_item.reference_name = reference_name
            queue_item.max_retries = max_retries
            queue_item.retry_count = 0
            queue_item.status = "Queued"
            queue_item.next_retry_at = now_datetime()

            queue_item.insert(ignore_permissions=True)
            frappe.db.commit()

            frappe.logger().info(f"Queued {request_type} request: {queue_item.name}")
            return queue_item.name

        except Exception as e:
            frappe.log_error(f"Failed to queue request: {str(e)}", "Request Queue Error")
            raise

    def process_queue(self, limit: int = 50) -> Dict[str, int]:
        """
        Process queued requests

        Args:
            limit: Maximum number of items to process

        Returns:
            Processing statistics
        """
        stats = {
            "processed": 0,
            "succeeded": 0,
            "failed": 0,
            "skipped": 0
        }

        try:
            # Get queued items ordered by priority and creation time
            queue_items = frappe.get_all(
                self.queue_doctype,
                filters={
                    "status": ["in", ["Queued", "Retrying"]],
                    "next_retry_at": ["<=", now_datetime()]
                },
                fields=["name"],
                order_by="priority asc, creation asc",
                limit=limit
            )

            for item in queue_items:
                try:
                    result = self._process_queue_item(item.name)
                    stats["processed"] += 1

                    if result["success"]:
                        stats["succeeded"] += 1
                    else:
                        stats["failed"] += 1

                except Exception as e:
                    frappe.log_error(
                        f"Error processing queue item {item.name}: {str(e)}",
                        "Queue Processing Error"
                    )
                    stats["skipped"] += 1

            frappe.logger().info(f"Queue processing completed: {stats}")
            return stats

        except Exception as e:
            frappe.log_error(f"Queue processing failed: {str(e)}", "Queue Processing Error")
            return stats

    def _process_queue_item(self, queue_item_name: str) -> Dict[str, Any]:
        """Process a single queue item"""
        queue_item = frappe.get_doc(self.queue_doctype, queue_item_name)

        try:
            # Parse request data
            request_data = json.loads(queue_item.request_data) if queue_item.request_data else {}

            # Get resilient requester
            requester = get_resilient_requester("queue_processor")

            # Build full URL
            from frappe_mpesa.utils import get_mpesa_settings
            settings = get_mpesa_settings()
            url = settings.get_full_url(queue_item.endpoint)

            # Get auth headers
            from frappe_mpesa.auth import get_mpesa_auth
            headers = get_mpesa_auth().get_auth_headers()

            # Make the request
            kwargs = {"headers": headers}
            if queue_item.method.upper() == "POST":
                kwargs["json"] = request_data
            elif queue_item.method.upper() == "GET":
                kwargs["params"] = request_data

            response = requester.request(queue_item.method, url, **kwargs)
            result = response.json()

            # Update queue item as successful
            queue_item.status = "Completed"
            queue_item.response_data = json.dumps(result)
            queue_item.completed_at = now_datetime()
            queue_item.error_message = ""
            queue_item.save(ignore_permissions=True)
            frappe.db.commit()

            frappe.logger().info(f"Queue item {queue_item_name} processed successfully")

            return {
                "success": True,
                "response": result,
                "message": "Request processed successfully"
            }

        except (RetryableError, NonRetryableError) as e:
            # Handle retry logic
            return self._handle_queue_retry(queue_item, str(e), isinstance(e, RetryableError))

        except Exception as e:
            # Unexpected error - treat as retryable
            return self._handle_queue_retry(queue_item, str(e), True)

    def _handle_queue_retry(self, queue_item: Any, error_message: str, is_retryable: bool) -> Dict[str, Any]:
        """Handle retry logic for failed queue items"""
        queue_item.retry_count += 1
        queue_item.error_message = error_message
        queue_item.last_retry_at = now_datetime()

        if not is_retryable or queue_item.retry_count >= queue_item.max_retries:
            # Mark as failed
            queue_item.status = "Failed"
            queue_item.failed_at = now_datetime()

            frappe.log_error(
                f"Queue item {queue_item.name} failed permanently: {error_message}",
                "Queue Processing Failed"
            )

            success = False
            message = f"Request failed permanently after {queue_item.retry_count} attempts"

        else:
            # Schedule for retry with exponential backoff
            backoff_delay = min(300, 30 * (2 ** (queue_item.retry_count - 1)))  # Max 5 minutes
            queue_item.next_retry_at = add_to_date(now_datetime(), seconds=backoff_delay)
            queue_item.status = "Retrying"

            frappe.logger().warning(
                f"Queue item {queue_item.name} retry {queue_item.retry_count}/{queue_item.max_retries} "
                f"scheduled for {queue_item.next_retry_at}"
            )

            success = False
            message = f"Request scheduled for retry {queue_item.retry_count}/{queue_item.max_retries}"

        queue_item.save(ignore_permissions=True)
        frappe.db.commit()

        return {
            "success": success,
            "message": message,
            "retry_count": queue_item.retry_count
        }

    def get_queue_status(self) -> Dict[str, Any]:
        """Get queue status and statistics"""
        try:
            stats = {}

            # Count by status
            for status in ["Queued", "Retrying", "Completed", "Failed"]:
                count = frappe.db.count(self.queue_doctype, {"status": status})
                stats[status.lower()] = count

            # Get oldest pending item
            oldest_pending = frappe.db.sql("""
                SELECT name, creation, retry_count, error_message
                FROM `tab{}`
                WHERE status IN ('Queued', 'Retrying')
                ORDER BY creation ASC
                LIMIT 1
            """.format(self.queue_doctype), as_dict=True)

            stats["oldest_pending"] = oldest_pending[0] if oldest_pending else None

            # Get recent failures
            recent_failures = frappe.get_all(
                self.queue_doctype,
                filters={
                    "status": "Failed",
                    "failed_at": [">=", add_to_date(now_datetime(), hours=-24)]
                },
                fields=["name", "request_type", "error_message", "failed_at"],
                order_by="failed_at desc",
                limit=10
            )

            stats["recent_failures"] = recent_failures
            stats["total"] = sum([stats.get(status, 0) for status in ["queued", "retrying", "completed", "failed"]])

            return stats

        except Exception as e:
            frappe.log_error(f"Failed to get queue status: {str(e)}", "Queue Status Error")
            return {"error": str(e)}

    def cleanup_old_items(self, days: int = 30) -> int:
        """Clean up old completed/failed queue items"""
        try:
            cutoff_date = add_to_date(now_datetime(), days=-days)

            # Delete old completed items
            deleted_count = frappe.db.sql("""
                DELETE FROM `tab{}`
                WHERE status IN ('Completed', 'Failed')
                AND (completed_at < %s OR failed_at < %s)
            """.format(self.queue_doctype), (cutoff_date, cutoff_date))

            frappe.db.commit()

            deleted_count = deleted_count[0] if deleted_count else 0
            frappe.logger().info(f"Cleaned up {deleted_count} old queue items")

            return deleted_count

        except Exception as e:
            frappe.log_error(f"Failed to cleanup queue items: {str(e)}", "Queue Cleanup Error")
            return 0

    def retry_failed_items(self, max_items: int = 10) -> Dict[str, int]:
        """Retry recently failed items that might be retryable"""
        try:
            # Get failed items from last hour that haven't exceeded max retries
            recent_failures = frappe.get_all(
                self.queue_doctype,
                filters={
                    "status": "Failed",
                    "failed_at": [">=", add_to_date(now_datetime(), hours=-1)],
                    "retry_count": ["<", 5]  # Only retry if we haven't hit max retries
                },
                fields=["name"],
                limit=max_items
            )

            retried_count = 0
            for item in recent_failures:
                try:
                    queue_item = frappe.get_doc(self.queue_doctype, item.name)
                    queue_item.status = "Queued"
                    queue_item.next_retry_at = now_datetime()
                    queue_item.save(ignore_permissions=True)
                    retried_count += 1

                except Exception as e:
                    frappe.log_error(f"Failed to retry queue item {item.name}: {str(e)}", "Queue Retry Error")

            frappe.db.commit()
            frappe.logger().info(f"Retried {retried_count} failed queue items")

            return {"retried": retried_count, "total_failures": len(recent_failures)}

        except Exception as e:
            frappe.log_error(f"Failed to retry failed items: {str(e)}", "Queue Retry Error")
            return {"retried": 0, "error": str(e)}


# Global queue manager instance
_queue_manager = None

def get_queue_manager() -> RequestQueue:
    """Get the global queue manager instance"""
    global _queue_manager
    if _queue_manager is None:
        _queue_manager = RequestQueue()
    return _queue_manager


@frappe.whitelist()
def process_request_queue(limit: int = 50) -> Dict[str, Any]:
    """Process the request queue - can be called via API or scheduled task"""
    queue_manager = get_queue_manager()
    return queue_manager.process_queue(limit)


@frappe.whitelist()
def get_queue_status() -> Dict[str, Any]:
    """Get current queue status"""
    queue_manager = get_queue_manager()
    return queue_manager.get_queue_status()


@frappe.whitelist()
def cleanup_queue(days: int = 30) -> Dict[str, Any]:
    """Clean up old queue items"""
    queue_manager = get_queue_manager()
    deleted_count = queue_manager.cleanup_old_items(days)
    return {"deleted_count": deleted_count}


@frappe.whitelist()
def retry_failed_requests(max_items: int = 10) -> Dict[str, Any]:
    """Retry recently failed requests"""
    queue_manager = get_queue_manager()
    return queue_manager.retry_failed_items(max_items)


def enqueue_mpesa_request(request_type: str,
                         endpoint: str,
                         data: Dict[str, Any],
                         method: str = "POST",
                         priority: int = 2,
                         reference_doctype: Optional[str] = None,
                         reference_name: Optional[str] = None) -> str:
    """
    Convenience function to queue Mpesa requests

    This function can be used by other modules to queue requests
    when immediate processing fails due to network issues
    """
    queue_manager = get_queue_manager()
    return queue_manager.enqueue_request(
        request_type=request_type,
        endpoint=endpoint,
        data=data,
        method=method,
        priority=priority,
        reference_doctype=reference_doctype,
        reference_name=reference_name
    )