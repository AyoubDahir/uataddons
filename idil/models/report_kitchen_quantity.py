from odoo import models, fields, api, _

class KitchenQuantityReportWizard(models.TransientModel):
    _name = 'idil.kitchen.report.wizard'
    _description = 'Kitchen Quantity Report Wizard'

    start_date = fields.Date(
        string='Start Date',
        required=True,
        default=fields.Date.context_today
    )
    end_date = fields.Date(
        string='End Date',
        required=True,
        default=fields.Date.context_today
    )
    salesperson_id = fields.Many2one(
        'idil.sales.sales_personnel',
        string='Sales Team',
        help='Filter by specific sales team/person'
    )
    
    def _get_report_data(self):
        """Aggregate product quantities from Salesperson, Customer and Staff orders (DRAFT ONLY)"""
        from datetime import datetime, time, timedelta

        # Ensure we cover the full day for start and end dates
        start_dt = datetime.combine(self.start_date, time.min)
        end_dt = datetime.combine(self.end_date, time.max)
        
        # Base filter: Draft state and date range
        base_domain = [
            ('order_id.order_date', '>=', start_dt),
            ('order_id.order_date', '<=', end_dt),
            ('order_id.state', '=', 'draft')
        ]
        
        # 1. Salesperson Orders
        sp_domain = list(base_domain)
        if self.salesperson_id:
            sp_domain.append(('order_id.salesperson_id', '=', self.salesperson_id.id))
        
        sp_lines = self.env['idil.salesperson.place.order.line'].search(sp_domain)
        
        # 2. Customer Orders
        cust_lines = self.env['idil.customer.place.order.line'].search(base_domain)

        # 3. Staff Orders
        staff_lines = self.env['idil.staff.place.order.line'].search(base_domain)
        
        # Aggregate data
        product_data = {}
        
        def add_to_data(line, source_type):
            product = line.product_id
            if product.id not in product_data:
                product_data[product.id] = {
                    'product_name': product.name,
                    'sp_qty': 0.0,
                    'cust_qty': 0.0,
                    'staff_qty': 0.0,
                    'total_qty': 0.0,
                    'uom': product.uom_id.name if product.uom_id else ''
                }
            
            qty = line.quantity
            if source_type == 'sp':
                product_data[product.id]['sp_qty'] += qty
            elif source_type == 'cust':
                product_data[product.id]['cust_qty'] += qty
            else:
                product_data[product.id]['staff_qty'] += qty
            product_data[product.id]['total_qty'] += qty

        for line in sp_lines:
            add_to_data(line, 'sp')
        
        for line in cust_lines:
            add_to_data(line, 'cust')

        for line in staff_lines:
            add_to_data(line, 'staff')
            
        return sorted(list(product_data.values()), key=lambda x: x['product_name'])

    def action_print_report(self):
        """Generate PDF Report"""
        return self._generate_report('pdf')

    def view_report(self):
        """Show Report as HTML"""
        return self._generate_report('html')

    def _generate_report(self, report_type='pdf'):
        data = {
            'start_date': self.start_date,
            'end_date': self.end_date,
            'salesperson_name': self.salesperson_id.name if self.salesperson_id else 'All',
            'products': self._get_report_data()
        }
        report_action = self.env.ref('idil.action_report_kitchen_quantity')
        action = report_action.report_action(self, data=data)
        if report_type == 'html':
            action['report_type'] = 'qweb-html'
        return action

class ReportKitchenQuantity(models.AbstractModel):
    _name = 'report.idil.report_kitchen_quantity_template'
    _description = 'Kitchen Quantity Report Template'

    @api.model
    def _get_report_values(self, docids, data=None):
        docs = self.env['idil.kitchen.report.wizard'].browse(docids)
        return {
            'doc_ids': docids,
            'doc_model': 'idil.kitchen.report.wizard',
            'docs': docs,
            'data': data,
        }
