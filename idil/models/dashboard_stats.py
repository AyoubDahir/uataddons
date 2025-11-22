from odoo import models, fields, api
from datetime import datetime, timedelta
from collections import defaultdict

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

    @api.model
    def get_top_products(self, limit=10):
        """
        Get top-selling products by quantity and revenue.
        """
        query = """
            SELECT 
                p.id,
                p.name,
                SUM(sol.quantity) as total_qty,
                SUM(sol.quantity * sol.price_unit) as total_revenue
            FROM idil_sale_order_line sol
            JOIN idil_item p ON p.id = sol.product_id
            JOIN idil_sale_order so ON so.id = sol.order_id
            WHERE so.state = 'confirmed'
            GROUP BY p.id, p.name
            ORDER BY total_revenue DESC
            LIMIT %s
        """
        self.env.cr.execute(query, (limit,))
        results = self.env.cr.dictfetchall()
        
        return {
            'labels': [r['name'] for r in results],
            'quantities': [float(r['total_qty'] or 0) for r in results],
            'revenues': [float(r['total_revenue'] or 0) for r in results],
        }

    @api.model
    def get_hourly_sales(self, date=None):
        """
        Get sales breakdown by hour for a specific date.
        """
        if not date:
            date = fields.Date.today()
        
        # Query to get hourly sales
        query = """
            SELECT 
                EXTRACT(HOUR FROM order_date) as hour,
                COUNT(*) as order_count,
                SUM(order_total) as total_sales
            FROM idil_sale_order
            WHERE DATE(order_date) = %s
            AND state = 'confirmed'
            GROUP BY EXTRACT(HOUR FROM order_date)
            ORDER BY hour
        """
        self.env.cr.execute(query, (date,))
        results = self.env.cr.dictfetchall()
        
        # Fill in missing hours with 0
        hourly_data = {int(r['hour']): float(r['total_sales'] or 0) for r in results}
        
        return {
            'labels': [f"{h:02d}:00" for h in range(24)],
            'data': [hourly_data.get(h, 0) for h in range(24)],
        }

    @api.model
    def get_sales_by_category(self):
        """
        Get sales breakdown by product (Top 5 products).
        Note: Items don't have categories, so we group by product instead.
        """
        query = """
            SELECT 
                p.name as category,
                SUM(sol.quantity * sol.price_unit) as total_sales,
                SUM(sol.quantity) as total_qty
            FROM idil_sale_order_line sol
            JOIN idil_item p ON p.id = sol.product_id
            JOIN idil_sale_order so ON so.id = sol.order_id
            WHERE so.state = 'confirmed'
            GROUP BY p.name
            ORDER BY total_sales DESC
            LIMIT 5
        """
        self.env.cr.execute(query)
        results = self.env.cr.dictfetchall()
        
        return {
            'labels': [r['category'] for r in results],
            'data': [float(r['total_sales'] or 0) for r in results],
            'quantities': [float(r['total_qty'] or 0) for r in results],
        }

    @api.model
    def get_salesperson_leaderboard(self, limit=5):
        """
        Get top salespeople by total sales.
        """
        query = """
            SELECT 
                sp.name as salesperson,
                COUNT(DISTINCT so.id) as order_count,
                SUM(so.order_total) as total_sales,
                SUM(so.commission_amount) as total_commission
            FROM idil_sale_order so
            JOIN idil_sales_sales_personnel sp ON sp.id = so.sales_person_id
            WHERE so.state = 'confirmed'
            GROUP BY sp.id, sp.name
            ORDER BY total_sales DESC
            LIMIT %s
        """
        self.env.cr.execute(query, (limit,))
        results = self.env.cr.dictfetchall()
        
        return {
            'labels': [r['salesperson'] for r in results],
            'sales': [float(r['total_sales'] or 0) for r in results],
            'orders': [int(r['order_count'] or 0) for r in results],
            'commissions': [float(r['total_commission'] or 0) for r in results],
        }

    @api.model
    def get_wastage_stats(self):
        """
        Get wastage statistics from sale returns.
        Critical for bakery operations!
        """
        # Returns in the last 30 days
        date_from = fields.Date.today() - timedelta(days=30)
        
        returns = self.env['idil.sale.return'].search([
            ('return_date', '>=', date_from),
            ('state', '=', 'confirmed')
        ])
        
        total_wastage_value = sum(returns.mapped('total_subtotal'))
        total_wastage_items = self.env['idil.sale.return.line'].search_count([
            ('return_id', 'in', returns.ids)
        ])
        
        # Get top wasted products
        query = """
            SELECT 
                p.name,
                SUM(srl.returned_quantity) as qty,
                SUM(srl.returned_quantity * srl.price_unit) as value
            FROM idil_sale_return_line srl
            JOIN idil_item p ON p.id = srl.product_id
            JOIN idil_sale_return sr ON sr.id = srl.return_id
            WHERE sr.state = 'confirmed'
            AND sr.return_date >= %s
            GROUP BY p.name
            ORDER BY value DESC
            LIMIT 5
        """
        self.env.cr.execute(query, (date_from,))
        top_wasted = self.env.cr.dictfetchall()
        
        return {
            'total_value': total_wastage_value,
            'total_items': total_wastage_items,
            'top_products': {
                'labels': [r['name'] for r in top_wasted],
                'quantities': [float(r['qty'] or 0) for r in top_wasted],
                'values': [float(r['value'] or 0) for r in top_wasted],
            }
        }

    @api.model
    def get_preorder_stats(self):
        """
        Get pre-order statistics.
        Assuming idil.customer.sale.order represents pre-orders.
        """
        pending_preorders = self.env['idil.customer.sale.order'].search_count([
            ('state', '=', 'draft')
        ])
        
        confirmed_preorders = self.env['idil.customer.sale.order'].search_count([
            ('state', '=', 'confirmed')
        ])
        
        preorder_value = sum(
            self.env['idil.customer.sale.order'].search([
                ('state', '=', 'draft')
            ]).mapped('order_total')
        )
        
        return {
            'pending': pending_preorders,
            'confirmed': confirmed_preorders,
            'total_value': preorder_value,
        }

