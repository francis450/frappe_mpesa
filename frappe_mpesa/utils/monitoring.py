# Copyright (c) 2025, Njoroge Francis and contributors
# For license information, please see license.txt

import frappe
from frappe import _
import json
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from frappe.utils import now_datetime, add_to_date, get_datetime, flt
from frappe_mpesa.utils import get_mpesa_settings
from frappe_mpesa.utils.resilience import get_circuit_breaker_status


class MpesaMonitor:
    """Comprehensive monitoring and alerting for Mpesa integration"""

    def __init__(self):
        self.settings = get_mpesa_settings()

    def get_health_status(self) -> Dict[str, Any]:
        """Get comprehensive health status of Mpesa integration"""
        try:
            health_status = {
                "overall_status": "healthy",
                "timestamp": now_datetime().isoformat(),
                "components": {},
                "alerts": [],
                "metrics": {}
            }

            # Check authentication health
            auth_status = self._check_auth_health()
            health_status["components"]["authentication"] = auth_status

            # Check API health
            api_status = self._check_api_health()
            health_status["components"]["api"] = api_status

            # Check queue health
            queue_status = self._check_queue_health()
            health_status["components"]["queue"] = queue_status

            # Check transaction processing health
            transaction_status = self._check_transaction_health()
            health_status["components"]["transactions"] = transaction_status

            # Check circuit breaker status
            circuit_status = self._check_circuit_breaker_health()
            health_status["components"]["circuit_breaker"] = circuit_status

            # Generate alerts based on component status
            health_status["alerts"] = self._generate_alerts(health_status["components"])

            # Calculate overall status
            health_status["overall_status"] = self._calculate_overall_status(health_status["components"])

            # Get key metrics
            health_status["metrics"] = self._get_key_metrics()

            return health_status

        except Exception as e:
            frappe.log_error(f"Error getting health status: {str(e)}", "Mpesa Health Check")
            return {
                "overall_status": "error",
                "error": str(e),
                "timestamp": now_datetime().isoformat()
            }

    def _check_auth_health(self) -> Dict[str, Any]:
        """Check authentication component health"""
        try:
            from frappe_mpesa.auth import get_mpesa_auth

            auth = get_mpesa_auth()
            token_status = auth.get_token_status()

            if not token_status.get("cached"):
                return {
                    "status": "warning",
                    "message": "No cached token",
                    "details": token_status
                }

            if not token_status.get("is_valid"):
                return {
                    "status": "error",
                    "message": "Token expired or invalid",
                    "details": token_status
                }

            time_remaining = token_status.get("time_remaining_seconds", 0)
            if time_remaining < 600:  # Less than 10 minutes
                return {
                    "status": "warning",
                    "message": f"Token expires soon ({time_remaining}s)",
                    "details": token_status
                }

            return {
                "status": "healthy",
                "message": "Authentication working properly",
                "details": token_status
            }

        except Exception as e:
            return {
                "status": "error",
                "message": f"Auth check failed: {str(e)}",
                "details": {"error": str(e)}
            }

    def _check_api_health(self) -> Dict[str, Any]:
        """Check API component health"""
        try:
            # Check recent API errors
            cutoff_time = add_to_date(now_datetime(), hours=-1)

            error_count = frappe.db.count("Error Log", {
                "creation": [">=", cutoff_time],
                "error": ["like", "%Mpesa API%"]
            })

            if error_count > 10:  # More than 10 API errors in last hour
                return {
                    "status": "error",
                    "message": f"High API error rate: {error_count} errors in last hour",
                    "details": {"error_count": error_count, "timeframe": "1 hour"}
                }

            elif error_count > 5:
                return {
                    "status": "warning",
                    "message": f"Elevated API error rate: {error_count} errors in last hour",
                    "details": {"error_count": error_count, "timeframe": "1 hour"}
                }

            return {
                "status": "healthy",
                "message": "API calls working normally",
                "details": {"error_count": error_count, "timeframe": "1 hour"}
            }

        except Exception as e:
            return {
                "status": "error",
                "message": f"API health check failed: {str(e)}",
                "details": {"error": str(e)}
            }

    def _check_queue_health(self) -> Dict[str, Any]:
        """Check request queue health"""
        try:
            from frappe_mpesa.utils.queue_manager import get_queue_manager

            queue_manager = get_queue_manager()
            queue_status = queue_manager.get_queue_status()

            queued_count = queue_status.get("queued", 0) + queue_status.get("retrying", 0)
            failed_count = queue_status.get("failed", 0)

            # Check for high queue backlog
            if queued_count > 100:
                return {
                    "status": "error",
                    "message": f"High queue backlog: {queued_count} pending items",
                    "details": queue_status
                }

            elif queued_count > 50:
                return {
                    "status": "warning",
                    "message": f"Moderate queue backlog: {queued_count} pending items",
                    "details": queue_status
                }

            # Check for high failure rate
            total_processed = queue_status.get("completed", 0) + failed_count
            if total_processed > 0:
                failure_rate = (failed_count / total_processed) * 100
                if failure_rate > 20:  # More than 20% failure rate
                    return {
                        "status": "warning",
                        "message": f"High queue failure rate: {failure_rate:.1f}%",
                        "details": queue_status
                    }

            return {
                "status": "healthy",
                "message": "Queue processing normally",
                "details": queue_status
            }

        except Exception as e:
            return {
                "status": "error",
                "message": f"Queue health check failed: {str(e)}",
                "details": {"error": str(e)}
            }

    def _check_transaction_health(self) -> Dict[str, Any]:
        """Check transaction processing health"""
        try:
            cutoff_time = add_to_date(now_datetime(), hours=-24)

            # Check STK Push transactions
            stk_stats = frappe.db.sql("""
                SELECT
                    COUNT(*) as total,
                    SUM(CASE WHEN status = 'Completed' THEN 1 ELSE 0 END) as completed,
                    SUM(CASE WHEN status = 'Failed' THEN 1 ELSE 0 END) as failed,
                    SUM(CASE WHEN status = 'Pending' THEN 1 ELSE 0 END) as pending
                FROM `tabMpesa Express Transaction`
                WHERE creation >= %s
            """, cutoff_time, as_dict=True)

            stk_data = stk_stats[0] if stk_stats else {}
            total_stk = stk_data.get("total", 0)

            if total_stk > 0:
                success_rate = (stk_data.get("completed", 0) / total_stk) * 100
                pending_count = stk_data.get("pending", 0)

                # Check for low success rate
                if success_rate < 70:
                    return {
                        "status": "error",
                        "message": f"Low STK Push success rate: {success_rate:.1f}%",
                        "details": stk_data
                    }

                # Check for high pending count
                if pending_count > 50:
                    return {
                        "status": "warning",
                        "message": f"High pending STK Push count: {pending_count}",
                        "details": stk_data
                    }

            return {
                "status": "healthy",
                "message": "Transaction processing normal",
                "details": stk_data
            }

        except Exception as e:
            return {
                "status": "error",
                "message": f"Transaction health check failed: {str(e)}",
                "details": {"error": str(e)}
            }

    def _check_circuit_breaker_health(self) -> Dict[str, Any]:
        """Check circuit breaker status"""
        try:
            cb_status = get_circuit_breaker_status("mpesa")

            if cb_status.get("state") == "open":
                return {
                    "status": "error",
                    "message": "Circuit breaker is OPEN",
                    "details": cb_status
                }

            elif cb_status.get("state") == "half_open":
                return {
                    "status": "warning",
                    "message": "Circuit breaker is HALF-OPEN",
                    "details": cb_status
                }

            failure_count = cb_status.get("failure_count", 0)
            threshold = cb_status.get("failure_threshold", 5)

            if failure_count > threshold * 0.8:  # More than 80% of threshold
                return {
                    "status": "warning",
                    "message": f"Circuit breaker nearing threshold: {failure_count}/{threshold}",
                    "details": cb_status
                }

            return {
                "status": "healthy",
                "message": "Circuit breaker closed and healthy",
                "details": cb_status
            }

        except Exception as e:
            return {
                "status": "error",
                "message": f"Circuit breaker check failed: {str(e)}",
                "details": {"error": str(e)}
            }

    def _generate_alerts(self, components: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Generate alerts based on component status"""
        alerts = []

        for component_name, component_data in components.items():
            status = component_data.get("status")
            message = component_data.get("message", "")

            if status == "error":
                alerts.append({
                    "severity": "critical",
                    "component": component_name,
                    "message": message,
                    "timestamp": now_datetime().isoformat()
                })

            elif status == "warning":
                alerts.append({
                    "severity": "warning",
                    "component": component_name,
                    "message": message,
                    "timestamp": now_datetime().isoformat()
                })

        return alerts

    def _calculate_overall_status(self, components: Dict[str, Any]) -> str:
        """Calculate overall system status"""
        statuses = [comp.get("status", "unknown") for comp in components.values()]

        if "error" in statuses:
            return "error"
        elif "warning" in statuses:
            return "warning"
        elif all(status == "healthy" for status in statuses):
            return "healthy"
        else:
            return "unknown"

    def _get_key_metrics(self) -> Dict[str, Any]:
        """Get key performance metrics"""
        try:
            cutoff_24h = add_to_date(now_datetime(), hours=-24)
            cutoff_1h = add_to_date(now_datetime(), hours=-1)

            metrics = {}

            # Transaction volume metrics
            stk_volume_24h = frappe.db.count("Mpesa Express Transaction", {"creation": [">=", cutoff_24h]})
            stk_volume_1h = frappe.db.count("Mpesa Express Transaction", {"creation": [">=", cutoff_1h]})

            metrics["transaction_volume"] = {
                "stk_push_24h": stk_volume_24h,
                "stk_push_1h": stk_volume_1h
            }

            # Success rate metrics
            stk_success_24h = frappe.db.count("Mpesa Express Transaction", {
                "creation": [">=", cutoff_24h],
                "status": "Completed"
            })

            if stk_volume_24h > 0:
                metrics["success_rate_24h"] = (stk_success_24h / stk_volume_24h) * 100
            else:
                metrics["success_rate_24h"] = 0

            # Error rate metrics
            error_count_1h = frappe.db.count("Error Log", {
                "creation": [">=", cutoff_1h],
                "error": ["like", "%Mpesa%"]
            })

            metrics["error_rate_1h"] = error_count_1h

            # Queue metrics
            from frappe_mpesa.utils.queue_manager import get_queue_manager
            queue_manager = get_queue_manager()
            queue_status = queue_manager.get_queue_status()

            metrics["queue"] = {
                "pending": queue_status.get("queued", 0) + queue_status.get("retrying", 0),
                "failed": queue_status.get("failed", 0),
                "completed": queue_status.get("completed", 0)
            }

            # Auth token metrics
            from frappe_mpesa.auth import get_mpesa_auth
            auth = get_mpesa_auth()
            token_status = auth.get_token_status()

            if token_status.get("cached"):
                metrics["auth_token_remaining_seconds"] = token_status.get("time_remaining_seconds", 0)
            else:
                metrics["auth_token_remaining_seconds"] = 0

            return metrics

        except Exception as e:
            frappe.log_error(f"Error getting metrics: {str(e)}", "Mpesa Metrics")
            return {"error": str(e)}

    def send_alerts(self, alerts: List[Dict[str, Any]]) -> bool:
        """Send alerts via configured notification methods"""
        try:
            if not alerts:
                return True

            critical_alerts = [alert for alert in alerts if alert.get("severity") == "critical"]

            if critical_alerts:
                # Send critical alerts immediately
                self._send_critical_alerts(critical_alerts)

            # Log all alerts
            for alert in alerts:
                frappe.log_error(
                    f"Mpesa {alert['severity'].upper()} Alert: {alert['message']}",
                    f"Mpesa {alert['component'].title()} Alert"
                )

            return True

        except Exception as e:
            frappe.log_error(f"Error sending alerts: {str(e)}", "Mpesa Alert System")
            return False

    def _send_critical_alerts(self, alerts: List[Dict[str, Any]]):
        """Send critical alerts via email/SMS if configured"""
        try:
            # This would integrate with your notification system
            # For now, we'll just create error logs with high priority

            alert_summary = "\n".join([
                f"• {alert['component']}: {alert['message']}"
                for alert in alerts
            ])

            frappe.log_error(
                f"CRITICAL MPESA ALERTS:\n{alert_summary}",
                "Mpesa Critical Alerts"
            )

            # TODO: Integrate with email/SMS notification system
            # - Send email to admin users
            # - Send SMS to on-call personnel
            # - Create Slack/Teams notifications
            # - Integrate with monitoring tools (Datadog, New Relic, etc.)

        except Exception as e:
            frappe.log_error(f"Error sending critical alerts: {str(e)}", "Critical Alert Error")


# Global monitor instance
_monitor_instance = None

def get_mpesa_monitor() -> MpesaMonitor:
    """Get the global MpesaMonitor instance"""
    global _monitor_instance
    if _monitor_instance is None:
        _monitor_instance = MpesaMonitor()
    return _monitor_instance


@frappe.whitelist()
def get_health_status() -> Dict[str, Any]:
    """API endpoint to get Mpesa health status"""
    monitor = get_mpesa_monitor()
    return monitor.get_health_status()


@frappe.whitelist()
def get_monitoring_dashboard_data() -> Dict[str, Any]:
    """Get comprehensive monitoring data for dashboard"""
    try:
        monitor = get_mpesa_monitor()
        health_status = monitor.get_health_status()

        # Add additional dashboard-specific data
        dashboard_data = {
            "health": health_status,
            "charts": {
                "transaction_volume": _get_transaction_volume_chart(),
                "success_rate": _get_success_rate_chart(),
                "error_distribution": _get_error_distribution_chart()
            }
        }

        return dashboard_data

    except Exception as e:
        frappe.log_error(f"Error getting dashboard data: {str(e)}", "Mpesa Dashboard")
        return {"error": str(e)}


def _get_transaction_volume_chart() -> Dict[str, Any]:
    """Get transaction volume chart data"""
    try:
        # Get hourly transaction volume for last 24 hours
        data = frappe.db.sql("""
            SELECT
                DATE_FORMAT(creation, '%Y-%m-%d %H:00:00') as hour,
                COUNT(*) as count
            FROM `tabMpesa Express Transaction`
            WHERE creation >= DATE_SUB(NOW(), INTERVAL 24 HOUR)
            GROUP BY hour
            ORDER BY hour
        """, as_dict=True)

        return {
            "labels": [item["hour"] for item in data],
            "datasets": [{
                "label": "STK Push Transactions",
                "data": [item["count"] for item in data]
            }]
        }

    except Exception as e:
        frappe.log_error(f"Error getting transaction volume chart: {str(e)}", "Chart Error")
        return {"error": str(e)}


def _get_success_rate_chart() -> Dict[str, Any]:
    """Get success rate chart data"""
    try:
        # Get hourly success rate for last 24 hours
        data = frappe.db.sql("""
            SELECT
                DATE_FORMAT(creation, '%Y-%m-%d %H:00:00') as hour,
                COUNT(*) as total,
                SUM(CASE WHEN status = 'Completed' THEN 1 ELSE 0 END) as completed
            FROM `tabMpesa Express Transaction`
            WHERE creation >= DATE_SUB(NOW(), INTERVAL 24 HOUR)
            GROUP BY hour
            ORDER BY hour
        """, as_dict=True)

        success_rates = []
        for item in data:
            if item["total"] > 0:
                success_rates.append((item["completed"] / item["total"]) * 100)
            else:
                success_rates.append(0)

        return {
            "labels": [item["hour"] for item in data],
            "datasets": [{
                "label": "Success Rate (%)",
                "data": success_rates
            }]
        }

    except Exception as e:
        frappe.log_error(f"Error getting success rate chart: {str(e)}", "Chart Error")
        return {"error": str(e)}


def _get_error_distribution_chart() -> Dict[str, Any]:
    """Get error distribution chart data"""
    try:
        # Get error distribution for last 24 hours
        data = frappe.db.sql("""
            SELECT
                error,
                COUNT(*) as count
            FROM `tabError Log`
            WHERE creation >= DATE_SUB(NOW(), INTERVAL 24 HOUR)
            AND error LIKE '%Mpesa%'
            GROUP BY error
            ORDER BY count DESC
            LIMIT 10
        """, as_dict=True)

        return {
            "labels": [item["error"][:50] + "..." if len(item["error"]) > 50 else item["error"] for item in data],
            "datasets": [{
                "label": "Error Count",
                "data": [item["count"] for item in data]
            }]
        }

    except Exception as e:
        frappe.log_error(f"Error getting error distribution chart: {str(e)}", "Chart Error")
        return {"error": str(e)}