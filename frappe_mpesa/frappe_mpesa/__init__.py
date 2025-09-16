# Copyright (c) 2025, Njoroge Francis and contributors
# For license information, please see license.txt

__version__ = "1.0.0"

# Import commonly used utilities
from frappe_mpesa.utils import (
	get_mpesa_settings,
	format_phone_number,
	validate_amount,
	generate_transaction_id
)

# Note: auth imports are done lazily to avoid circular import issues
# from frappe_mpesa.auth import mpesa_auth, get_access_token