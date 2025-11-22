from odoo import models, fields, api
from datetime import datetime, timedelta

class IdilDashboard(models.Model):
    _name = 'idil.dashboard'
    _description = 'Idil Dashboard Logic'

    @api.model
    def get_dashboard_stats(self):
        """
        Fetch statistics for the Inventory Dashboard.
        """
        # 1. KPI Counts
        purchase_count = self.env['idil.purchase_order'].search_count([]) # Assuming model name
        vendor_trx_count = self.env['idil.vendor_transaction'].search_count([])
        purchase_return_count = self.env['idil.purchase_return'].search_count([])
        product_count = self.env['idil.item'].search_count([]) # Assuming 'idil.item' is the product model

        # 2. Financial & Actionable Metrics
        # Total Spend (Confirmed Orders)
        total_spend = sum(self.env['idil.purchase_order'].search([('state', '=', 'confirmed')]).mapped('amount'))
        
        # Pending Approvals
        pending_count = self.env['idil.purchase_order'].search_count([('state', '=', 'pending')])
        
        # Total Stock Value (Quantity * Cost Price)
        items = self.env['idil.item'].search([])
        stock_value = sum(item.quantity * item.cost_price for item in items)
        
        # Low Stock Alerts (Quantity < 10)
        low_stock_count = self.env['idil.item'].search_count([('quantity', '<', 10)])

        return {
            'purchase_count': purchase_count,
            'vendor_trx_count': vendor_trx_count,
            'purchase_return_count': purchase_return_count,
            'product_count': product_count,
            'total_spend': total_spend,
            'pending_count': pending_count,
            'stock_value': stock_value,
            'low_stock_count': low_stock_count,
        }
