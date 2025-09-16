// Copyright (c) 2025, Njoroge Francis and contributors
// For license information, please see license.txt

frappe.ui.form.on('Mpesa Express Transaction', {
	refresh: function(frm) {
		// Add custom buttons based on status
		if (frm.doc.status === 'Failed' || frm.doc.status === 'Timeout' || frm.doc.status === 'Cancelled') {
			frm.add_custom_button(__('Retry Transaction'), function() {
				retry_transaction(frm);
			}, __('Actions'));
		}
		
		if (frm.doc.checkout_request_id) {
			frm.add_custom_button(__('Check Status'), function() {
				check_transaction_status(frm);
			}, __('Actions'));
		}
		
		// Add status indicator
		if (frm.doc.status) {
			let indicator_color = get_status_color(frm.doc.status);
			frm.dashboard.add_indicator(__('Status: {0}', [frm.doc.status]), indicator_color);
		}
		
		// Show callback status
		if (frm.doc.callback_received) {
			frm.dashboard.add_indicator(__('Callback Received'), 'green');
		} else if (frm.doc.status === 'Pending') {
			frm.dashboard.add_indicator(__('Waiting for Callback'), 'orange');
		}
		
		// Auto-refresh for pending transactions
		if (frm.doc.status === 'Pending' && !frm.is_new()) {
			setTimeout(function() {
				frm.reload_doc();
			}, 10000); // Refresh every 10 seconds
		}
	},
	
	phone_number: function(frm) {
		// Format phone number as user types
		if (frm.doc.phone_number) {
			let formatted = format_phone_number(frm.doc.phone_number);
			if (formatted !== frm.doc.phone_number) {
				frm.set_value('phone_number', formatted);
			}
		}
	},
	
	amount: function(frm) {
		// Validate amount
		if (frm.doc.amount && frm.doc.amount > 70000) {
			frappe.msgprint({
				title: __('Warning'),
				indicator: 'orange',
				message: __('Amount exceeds Mpesa daily limit of KES 70,000')
			});
		}
	}
});

function retry_transaction(frm) {
	frappe.confirm(
		__('Are you sure you want to retry this transaction? This will initiate a new STK push to the customer.'),
		function() {
			frappe.call({
				method: 'frappe_mpesa.frappe_mpesa.doctype.mpesa_express_transaction.mpesa_express_transaction.retry_mpesa_transaction',
				args: {
					transaction_name: frm.doc.name
				},
				callback: function(r) {
					if (r.message && r.message.success) {
						frappe.show_alert({
							message: __('Transaction retry initiated successfully'),
							indicator: 'green'
						});
						frm.reload_doc();
					}
				}
			});
		}
	);
}

function check_transaction_status(frm) {
	frappe.call({
		method: 'frappe_mpesa.frappe_mpesa.doctype.mpesa_express_transaction.mpesa_express_transaction.check_transaction_status',
		args: {
			transaction_name: frm.doc.name
		},
		callback: function(r) {
			if (r.message) {
				let status_msg = __('Current Status: {0}', [r.message.status]);
				if (r.message.mpesa_receipt_number) {
					status_msg += __('<br>Receipt: {0}', [r.message.mpesa_receipt_number]);
				}
				
				frappe.msgprint({
					title: __('Transaction Status'),
					message: status_msg,
					indicator: get_status_color(r.message.status)
				});
				
				frm.reload_doc();
			}
		}
	});
}

function get_status_color(status) {
	switch (status) {
		case 'Success':
			return 'green';
		case 'Pending':
			return 'orange';
		case 'Failed':
		case 'Cancelled':
		case 'Timeout':
			return 'red';
		default:
			return 'gray';
	}
}

function format_phone_number(phone) {
	if (!phone) return phone;
	
	// Remove any non-digit characters
	let digits = phone.replace(/\D/g, '');
	
	// Format based on length and prefix
	if (digits.startsWith('254')) {
		return digits;
	} else if (digits.startsWith('0')) {
		return '254' + digits.substring(1);
	} else if (digits.startsWith('7') || digits.startsWith('1')) {
		return '254' + digits;
	}
	
	return phone; // Return original if format is unclear
}