frappe.ui.form.on('Mpesa Settings', {
	refresh: function(frm) {
		// Add custom buttons
		frm.add_custom_button(__('Test Connection'), function() {
			test_mpesa_connection(frm);
		});
		
		// Show environment indicator (check if dashboard exists)
		if (frm.doc.environment && frm.dashboard && frm.dashboard.add_indicator) {
			let indicator_color = frm.doc.environment === 'Production' ? 'red' : 'orange';
			frm.dashboard.add_indicator(__('Environment: {0}', [frm.doc.environment]), indicator_color);
		}
		
		// Show status indicator (check if dashboard exists)
		if (frm.dashboard && frm.dashboard.add_indicator) {
			if (frm.doc.is_enabled) {
				frm.dashboard.add_indicator(__('Mpesa Integration: Enabled'), 'green');
			} else {
				frm.dashboard.add_indicator(__('Mpesa Integration: Disabled'), 'red');
			}
		}
	},
	
	environment: function(frm) {
		// Auto-update base URL when environment changes
		if (frm.doc.environment === 'Production') {
			frm.set_value('base_url', 'https://api.safaricom.co.ke');
		} else if (frm.doc.environment === 'Sandbox') {
			frm.set_value('base_url', 'https://sandbox.safaricom.co.ke');
		}
	},
	
	is_enabled: function(frm) {
		// Show warning when enabling
		if (frm.doc.is_enabled && frm.doc.environment === 'Production') {
			frappe.msgprint({
				title: __('Warning'),
				indicator: 'orange',
				message: __('You are enabling Mpesa integration in Production mode. Please ensure all credentials are correct.')
			});
		}
	}
});

function test_mpesa_connection(frm) {
	frappe.call({
		method: 'frappe_mpesa.frappe_mpesa.doctype.mpesa_settings.mpesa_settings.test_mpesa_connection',
		callback: function(r) {
			if (r.message) {
				frappe.show_alert({
					message: __('Connection Test Successful'),
					indicator: 'green'
				});
			}
		},
		error: function(r) {
			frappe.show_alert({
				message: __('Connection Test Failed'),
				indicator: 'red'
			});
		}
	});
}