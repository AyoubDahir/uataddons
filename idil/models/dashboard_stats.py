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

        # 2. Monthly Purchases (Last 6 Months) - Simplified for now
        # In a real scenario, we'd group by date. Here we'll mock or do a simple search.
        # Let's just return the counts for now, we can refine the chart data in the next step
        # if we know the exact date fields.
        
        return {
            'purchase_count': purchase_count,
            'vendor_trx_count': vendor_trx_count,
            'purchase_return_count': purchase_return_count,
            'product_count': product_count,
        }
