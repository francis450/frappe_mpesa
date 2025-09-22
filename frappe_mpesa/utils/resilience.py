# Copyright (c) 2025, Njoroge Francis and contributors
# For license information, please see license.txt

import frappe
from frappe import _
import time
import random
import functools
import threading
from datetime import datetime, timedelta
from typing import Callable, Any, Dict, Optional, List
from enum import Enum
import requests


class CircuitState(Enum):
    """Circuit breaker states"""
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class RetryableError(Exception):
    """Exception that indicates operation should be retried"""
    pass


class NonRetryableError(Exception):
    """Exception that indicates operation should not be retried"""
    pass


class CircuitBreakerError(Exception):
    """Exception raised when circuit breaker is open"""
    pass


class ExponentialBackoff:
    """Exponential backoff with jitter for retry operations"""

    def __init__(self,
                 initial_delay: float = 1.0,
                 max_delay: float = 60.0,
                 multiplier: float = 2.0,
                 jitter: bool = True):
        self.initial_delay = initial_delay
        self.max_delay = max_delay
        self.multiplier = multiplier
        self.jitter = jitter

    def get_delay(self, attempt: int) -> float:
        """Calculate delay for given attempt number (0-based)"""
        delay = self.initial_delay * (self.multiplier ** attempt)
        delay = min(delay, self.max_delay)

        if self.jitter:
            # Add random jitter (±25%)
            jitter_range = delay * 0.25
            delay += random.uniform(-jitter_range, jitter_range)

        return max(0, delay)


class CircuitBreaker:
    """Circuit breaker pattern implementation for API resilience"""

    def __init__(self,
                 failure_threshold: int = 5,
                 recovery_timeout: float = 60.0,
                 expected_exception: type = Exception,
                 name: str = "default"):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.expected_exception = expected_exception
        self.name = name

        self._failure_count = 0
        self._last_failure_time = None
        self._state = CircuitState.CLOSED
        self._lock = threading.Lock()

    @property
    def state(self) -> CircuitState:
        """Get current circuit breaker state"""
        with self._lock:
            return self._state

    @property
    def failure_count(self) -> int:
        """Get current failure count"""
        with self._lock:
            return self._failure_count

    def _should_attempt_reset(self) -> bool:
        """Check if circuit should attempt to reset from open to half-open"""
        if self._last_failure_time is None:
            return False

        return (datetime.now() - self._last_failure_time).total_seconds() >= self.recovery_timeout

    def _record_success(self):
        """Record successful operation"""
        with self._lock:
            self._failure_count = 0
            self._state = CircuitState.CLOSED
            self._last_failure_time = None

    def _record_failure(self):
        """Record failed operation"""
        with self._lock:
            self._failure_count += 1
            self._last_failure_time = datetime.now()

            if self._failure_count >= self.failure_threshold:
                self._state = CircuitState.OPEN

    def call(self, func: Callable, *args, **kwargs) -> Any:
        """Execute function with circuit breaker protection"""
        with self._lock:
            if self._state == CircuitState.OPEN:
                if self._should_attempt_reset():
                    self._state = CircuitState.HALF_OPEN
                else:
                    raise CircuitBreakerError(
                        f"Circuit breaker '{self.name}' is OPEN. "
                        f"Failures: {self._failure_count}/{self.failure_threshold}"
                    )

        try:
            result = func(*args, **kwargs)
            self._record_success()
            return result

        except self.expected_exception as e:
            self._record_failure()

            # Log circuit breaker state changes
            if self.state == CircuitState.OPEN:
                frappe.log_error(
                    f"Circuit breaker '{self.name}' opened after {self._failure_count} failures",
                    "Circuit Breaker Open"
                )

            raise e


class ResilientRequester:
    """Resilient HTTP requester with retry logic and circuit breaker"""

    def __init__(self,
                 max_retries: int = 3,
                 circuit_breaker: Optional[CircuitBreaker] = None,
                 backoff: Optional[ExponentialBackoff] = None,
                 timeout_config: Optional[Dict[str, float]] = None):
        self.max_retries = max_retries
        self.circuit_breaker = circuit_breaker or CircuitBreaker(name="http_requests")
        self.backoff = backoff or ExponentialBackoff()

        # Default timeout configuration
        self.timeout_config = timeout_config or {
            'connect_timeout': 10.0,
            'read_timeout': 30.0,
            'total_timeout': 60.0
        }

    def _is_retryable_error(self, exception: Exception) -> bool:
        """Determine if error is retryable"""
        if isinstance(exception, requests.exceptions.Timeout):
            return True
        elif isinstance(exception, requests.exceptions.ConnectionError):
            return True
        elif isinstance(exception, requests.exceptions.HTTPError):
            # Retry on 5xx server errors, not 4xx client errors
            if hasattr(exception, 'response') and exception.response:
                return 500 <= exception.response.status_code < 600
        elif isinstance(exception, RetryableError):
            return True

        return False

    def _prepare_timeout(self) -> tuple:
        """Prepare timeout tuple for requests"""
        return (
            self.timeout_config['connect_timeout'],
            self.timeout_config['read_timeout']
        )

    def request(self, method: str, url: str, **kwargs) -> requests.Response:
        """Make resilient HTTP request with retries and circuit breaker"""

        def _make_request():
            timeout = self._prepare_timeout()
            kwargs.setdefault('timeout', timeout)

            response = requests.request(method, url, **kwargs)
            response.raise_for_status()
            return response

        last_exception = None

        for attempt in range(self.max_retries + 1):
            try:
                # Use circuit breaker for the actual request
                response = self.circuit_breaker.call(_make_request)

                frappe.logger().debug(
                    f"HTTP {method} {url} succeeded on attempt {attempt + 1}"
                )
                return response

            except Exception as e:
                last_exception = e

                # Don't retry if circuit breaker is open
                if isinstance(e, CircuitBreakerError):
                    frappe.log_error(
                        f"Request failed due to open circuit breaker: {str(e)}",
                        "Circuit Breaker"
                    )
                    raise e

                # Don't retry if it's not a retryable error
                if not self._is_retryable_error(e):
                    frappe.log_error(
                        f"Non-retryable error on {method} {url}: {str(e)}",
                        "HTTP Non-Retryable Error"
                    )
                    raise NonRetryableError(f"Non-retryable error: {str(e)}") from e

                # Don't retry if we've exhausted attempts
                if attempt >= self.max_retries:
                    break

                # Calculate delay and wait
                delay = self.backoff.get_delay(attempt)

                frappe.logger().warning(
                    f"HTTP {method} {url} failed on attempt {attempt + 1}/{self.max_retries + 1}. "
                    f"Retrying in {delay:.2f}s. Error: {str(e)}"
                )

                time.sleep(delay)

        # All retries exhausted
        frappe.log_error(
            f"Request failed after {self.max_retries + 1} attempts: {str(last_exception)}",
            "HTTP Max Retries Exceeded"
        )
        raise RetryableError(f"Max retries exceeded: {str(last_exception)}") from last_exception


def with_retry(max_retries: int = 3,
               backoff: Optional[ExponentialBackoff] = None,
               retryable_exceptions: tuple = (Exception,)):
    """Decorator to add retry logic to functions"""

    if backoff is None:
        backoff = ExponentialBackoff()

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            last_exception = None

            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)

                except retryable_exceptions as e:
                    last_exception = e

                    if attempt >= max_retries:
                        break

                    delay = backoff.get_delay(attempt)

                    frappe.logger().warning(
                        f"Function {func.__name__} failed on attempt {attempt + 1}. "
                        f"Retrying in {delay:.2f}s. Error: {str(e)}"
                    )

                    time.sleep(delay)

            raise last_exception

        return wrapper
    return decorator


def get_resilient_requester(service_name: str = "mpesa") -> ResilientRequester:
    """Get configured resilient requester for Mpesa services"""

    # Get timeout settings from Mpesa Settings
    try:
        from frappe_mpesa.utils import get_mpesa_settings
        settings = get_mpesa_settings()

        timeout_config = {
            'connect_timeout': getattr(settings, 'connect_timeout', 10.0),
            'read_timeout': getattr(settings, 'read_timeout', 30.0),
            'total_timeout': getattr(settings, 'total_timeout', 60.0)
        }

        max_retries = getattr(settings, 'max_retries', 3)

    except Exception:
        # Fallback to defaults if settings unavailable
        timeout_config = {
            'connect_timeout': 10.0,
            'read_timeout': 30.0,
            'total_timeout': 60.0
        }
        max_retries = 3

    # Create circuit breaker for this service
    circuit_breaker = CircuitBreaker(
        failure_threshold=5,
        recovery_timeout=60.0,
        expected_exception=Exception,
        name=f"{service_name}_api"
    )

    # Create backoff strategy
    backoff = ExponentialBackoff(
        initial_delay=1.0,
        max_delay=30.0,
        multiplier=2.0,
        jitter=True
    )

    return ResilientRequester(
        max_retries=max_retries,
        circuit_breaker=circuit_breaker,
        backoff=backoff,
        timeout_config=timeout_config
    )


@frappe.whitelist()
def get_circuit_breaker_status(service_name: str = "mpesa") -> Dict[str, Any]:
    """Get circuit breaker status for monitoring"""
    try:
        requester = get_resilient_requester(service_name)

        return {
            "service": service_name,
            "state": requester.circuit_breaker.state.value,
            "failure_count": requester.circuit_breaker.failure_count,
            "failure_threshold": requester.circuit_breaker.failure_threshold,
            "recovery_timeout": requester.circuit_breaker.recovery_timeout,
            "last_failure_time": requester.circuit_breaker._last_failure_time.isoformat()
                                if requester.circuit_breaker._last_failure_time else None
        }

    except Exception as e:
        return {
            "service": service_name,
            "error": str(e),
            "state": "unknown"
        }


@frappe.whitelist()
def reset_circuit_breaker(service_name: str = "mpesa") -> Dict[str, str]:
    """Manually reset circuit breaker"""
    try:
        requester = get_resilient_requester(service_name)
        requester.circuit_breaker._record_success()

        frappe.logger().info(f"Circuit breaker '{service_name}' manually reset")

        return {
            "success": True,
            "message": f"Circuit breaker for '{service_name}' has been reset"
        }

    except Exception as e:
        frappe.log_error(f"Failed to reset circuit breaker: {str(e)}", "Circuit Breaker Reset")
        return {
            "success": False,
            "message": str(e)
        }