// Copyright (c) 2025, Njoroge Francis and contributors
// For license information, please see license.txt

// Add Mpesa payment functionality to Sales Invoice
frappe.ui.form.on('Sales Invoice', {
	refresh: function(frm) {
		// Add Mpesa Express button if invoice is submitted and not fully paid
		if (frm.doc.docstatus === 1 && frm.doc.outstanding_amount > 0) {
			frm.add_custom_button(__('Pay via Mpesa'), function() {
				show_mpesa_payment_dialog(frm);
			}, __('Actions'));
		}
		
		// Show existing Mpesa transactions
		if (frm.doc.docstatus === 1) {
			show_mpesa_transactions(frm);
		}
	}
});

function show_mpesa_payment_dialog(frm) {
	let dialog = new frappe.ui.Dialog({
		title: __('Mpesa Express Payment'),
		fields: [
			{
				label: __('Customer Details'),
				fieldtype: 'Section Break'
			},
			{
				label: __('Customer'),
				fieldname: 'customer',
				fieldtype: 'Data',
				read_only: 1,
				default: frm.doc.customer_name || frm.doc.customer
			},
			{
				label: __('Amount'),
				fieldname: 'amount',
				fieldtype: 'Currency',
				default: frm.doc.outstanding_amount,
				reqd: 1
			},
			{
				label: __('Payment Details'),
				fieldtype: 'Section Break'
			},
			{
				label: __('Customer Phone Number'),
				fieldname: 'phone_number',
				fieldtype: 'Data',
				reqd: 1,
				description: __('Enter phone number in format: 0712345678 or 254712345678')
			},
			{
				label: __('Account Reference'),
				fieldname: 'account_reference',
				fieldtype: 'Data',
				default: frm.doc.name,
				reqd: 1
			},
			{
				label: __('Transaction Description'),
				fieldname: 'transaction_desc',
				fieldtype: 'Data',
				default: `Payment for Invoice ${frm.doc.name}`,
				reqd: 1
			}
		],
		primary_action_label: __('Send Payment Request'),
		primary_action: function(values) {
			initiate_mpesa_payment(frm, values, dialog);
		},
		secondary_action_label: __('Cancel')
	});
	
	dialog.show();
	
	// Auto-populate phone number from customer if available
	if (frm.doc.customer) {
		frappe.call({
			method: 'frappe.client.get',
			args: {
				doctype: 'Customer',
				name: frm.doc.customer
			},
			callback: function(r) {
				if (r.message && r.message.mobile_no) {
					dialog.set_value('phone_number', r.message.mobile_no);
				}
			}
		});
	}
}

function initiate_mpesa_payment(frm, values, dialog) {
	// Validate amount
	if (values.amount > frm.doc.outstanding_amount) {
		frappe.msgprint(__('Amount cannot exceed outstanding amount of {0}', [frm.doc.outstanding_amount]));
		return;
	}
	
	if (values.amount <= 0) {
		frappe.msgprint(__('Amount must be greater than zero'));
		return;
	}
	
	// Show loading
	dialog.set_primary_action(__('Sending...'), null);
	dialog.disable_primary_action();
	
	frappe.call({
		method: 'frappe_mpesa.api.mpesa_express.initiate_stk_push',
		args: {
			phone_number: values.phone_number,
			amount: values.amount,
			account_reference: values.account_reference,
			transaction_desc: values.transaction_desc,
			sales_invoice: frm.doc.name,
			customer: frm.doc.customer
		},
		callback: function(r) {
			dialog.hide();
			
			if (r.message && r.message.success) {
				frappe.show_alert({
					message: __('Payment request sent successfully! Customer will receive a prompt on their phone.'),
					indicator: 'green'
				});
				
				// Show transaction details
				frappe.msgprint({
					title: __('Payment Request Sent'),
					message: `
						<p><strong>${__('Transaction ID')}:</strong> ${r.message.transaction_name}</p>
						<p><strong>${__('Amount')}:</strong> KES ${values.amount}</p>
						<p><strong>${__('Phone')}:</strong> ${values.phone_number}</p>
						<p>${r.message.customer_message || __('Customer will receive a payment prompt on their phone.')}</p>
					`,
					indicator: 'green'
				});
				
				// Refresh form to show new transaction
				frm.reload_doc();
				
			} else {
				frappe.show_alert({
					message: r.message ? r.message.message : __('Failed to send payment request'),
					indicator: 'red'
				});
			}
		},
		error: function() {
			dialog.hide();
			frappe.show_alert({
				message: __('Failed to send payment request'),
				indicator: 'red'
			});
		}
	});
}

function show_mpesa_transactions(frm) {
	// Get Mpesa transactions for this invoice
	frappe.call({
		method: 'frappe.client.get_list',
		args: {
			doctype: 'Mpesa Express Transaction',
			filters: {
				sales_invoice: frm.doc.name
			},
			fields: ['name', 'phone_number', 'amount', 'status', 'mpesa_receipt_number', 'creation'],
			order_by: 'creation desc'
		},
		callback: function(r) {
			if (r.message && r.message.length > 0) {
				// Add section to show transactions
				let transactions_html = '<div class="mpesa-transactions"><h5>' + __('Mpesa Transactions') + '</h5>';
				
				r.message.forEach(function(txn) {
					let status_color = get_status_color(txn.status);
					let receipt = txn.mpesa_receipt_number || '-';
					
					transactions_html += `
						<div class="row transaction-row" style="margin-bottom: 10px; padding: 10px; border: 1px solid #ddd; border-radius: 4px;">
							<div class="col-xs-3"><strong>${txn.phone_number}</strong></div>
							<div class="col-xs-2">KES ${txn.amount}</div>
							<div class="col-xs-2"><span class="indicator ${status_color}">${txn.status}</span></div>
							<div class="col-xs-3">${receipt}</div>
							<div class="col-xs-2">
								<a href="/app/mpesa-express-transaction/${txn.name}" target="_blank">View</a>
							</div>
						</div>
					`;
				});
				
				transactions_html += '</div>';
				
				// Add to form sidebar or after customer info
				frm.dashboard.add_section(transactions_html, __('Mpesa Transactions'));
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