// Copyright (c) 2025, Njoroge Francis and contributors
// For license information, please see license.txt

frappe.listview_settings['Mpesa Express Transaction'] = {
	add_fields: ["status", "phone_number", "amount", "mpesa_receipt_number", "callback_received"],
	get_indicator: function(doc) {
		if (doc.status === "Success") {
			return [__("Success"), "green", "status,=,Success"];
		} else if (doc.status === "Pending") {
			return [__("Pending"), "orange", "status,=,Pending"];
		} else if (doc.status === "Failed") {
			return [__("Failed"), "red", "status,=,Failed"];
		} else if (doc.status === "Cancelled") {
			return [__("Cancelled"), "red", "status,=,Cancelled"];
		} else if (doc.status === "Timeout") {
			return [__("Timeout"), "red", "status,=,Timeout"];
		}
	},
	onload: function(listview) {
		// Add bulk retry button for failed transactions
		listview.page.add_menu_item(__("Retry Failed Transactions"), function() {
			let selected = listview.get_checked_items();
			if (selected.length === 0) {
				frappe.msgprint(__("Please select transactions to retry"));
				return;
			}
			
			let failed_transactions = selected.filter(item => 
				['Failed', 'Timeout', 'Cancelled'].includes(item.status)
			);
			
			if (failed_transactions.length === 0) {
				frappe.msgprint(__("No failed transactions selected"));
				return;
			}
			
			frappe.confirm(
				__("Are you sure you want to retry {0} failed transaction(s)?", [failed_transactions.length]),
				function() {
					retry_bulk_transactions(failed_transactions, listview);
				}
			);
		});
		
		// Add refresh button for pending transactions
		listview.page.add_menu_item(__("Refresh Pending Status"), function() {
			let selected = listview.get_checked_items();
			if (selected.length === 0) {
				frappe.msgprint(__("Please select transactions to refresh"));
				return;
			}
			
			let pending_transactions = selected.filter(item => item.status === 'Pending');
			
			if (pending_transactions.length === 0) {
				frappe.msgprint(__("No pending transactions selected"));
				return;
			}
			
			refresh_transaction_status(pending_transactions, listview);
		});
	}
};

function retry_bulk_transactions(transactions, listview) {
	let promises = transactions.map(txn => {
		return frappe.call({
			method: 'frappe_mpesa.frappe_mpesa.doctype.mpesa_express_transaction.mpesa_express_transaction.retry_mpesa_transaction',
			args: {
				transaction_name: txn.name
			}
		});
	});
	
	Promise.all(promises).then(function(results) {
		let successful = results.filter(r => r.message && r.message.success).length;
		let failed = results.length - successful;
		
		frappe.show_alert({
			message: __("{0} transactions retried successfully, {1} failed", [successful, failed]),
			indicator: successful > failed ? 'green' : 'orange'
		});
		
		listview.refresh();
	});
}

function refresh_transaction_status(transactions, listview) {
	let promises = transactions.map(txn => {
		return frappe.call({
			method: 'frappe_mpesa.frappe_mpesa.doctype.mpesa_express_transaction.mpesa_express_transaction.check_transaction_status',
			args: {
				transaction_name: txn.name
			}
		});
	});
	
	Promise.all(promises).then(function(results) {
		frappe.show_alert({
			message: __("Transaction status refreshed for {0} transactions", [results.length]),
			indicator: 'green'
		});
		
		listview.refresh();
	});
}