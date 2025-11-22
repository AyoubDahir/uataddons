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

        # 3. Comprehensive Metrics (Vendors, Payments, Adjustments)
        # Active Vendors
        vendor_count = self.env['idil.vendor.registration'].search_count([('active', '=', True)])
        
        # Vendor Payments
        vendor_transactions = self.env['idil.vendor_transaction'].search([])
        total_paid = sum(vendor_transactions.mapped('paid_amount'))
        total_payable = sum(vendor_transactions.mapped('remaining_amount'))
        
        # Stock Adjustments
        adjustment_count = self.env['idil.stock.adjustment'].search_count([])
        adjustment_value = sum(self.env['idil.stock.adjustment'].search([]).mapped('total_amount'))

        return {
            'purchase_count': purchase_count,
            'vendor_trx_count': vendor_trx_count,
            'purchase_return_count': purchase_return_count,
            'product_count': product_count,
            'total_spend': total_spend,
            'pending_count': pending_count,
            'stock_value': stock_value,
            'low_stock_count': low_stock_count,
            'vendor_count': vendor_count,
            'total_paid': total_paid,
            'total_payable': total_payable,
            'adjustment_count': adjustment_count,
            'adjustment_value': adjustment_value,
            # Sales Metrics
            'total_sales': sum(self.env['idil.sale.order'].search([('state', '=', 'confirmed')]).mapped('order_total')),
            'active_customers': self.env['idil.customer.registration'].search_count([('status', '=', True)]),
            'pending_sales_orders': self.env['idil.sale.order'].search_count([('state', '=', 'draft')]),
            'sales_returns_count': self.env['idil.sale.return'].search_count([]),
            'total_sales_receipts': sum(self.env['idil.sales.receipt'].search([('payment_status', '=', 'paid')]).mapped('paid_amount')),
            'customer_orders_count': self.env['idil.customer.sale.order'].search_count([]),
        }
