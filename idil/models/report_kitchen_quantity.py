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
        """Aggregate product quantities based on filters"""
        domain = [
            ('order_id.order_date', '>=', self.start_date),
            ('order_id.order_date', '<=', self.end_date)
        ]
        
        if self.salesperson_id:
            domain.append(('order_id.salesperson_id', '=', self.salesperson_id.id))
            
        # We can filter by state if needed, e.g., only confirmed orders
        # domain.append(('order_id.state', '=', 'confirmed'))

        # Fetch lines directly
        lines = self.env['idil.salesperson.place.order.line'].search(domain)
        
        # Aggregate data
        product_data = {}
        for line in lines:
            product = line.product_id
            if product.id not in product_data:
                product_data[product.id] = {
                    'product_name': product.name,
                    'quantity': 0.0,
                    'uom': product.uom_id.name if product.uom_id else ''
                }
            product_data[product.id]['quantity'] += line.quantity
            
        return list(product_data.values())

    def action_print_report(self):
        data = {
            'start_date': self.start_date,
            'end_date': self.end_date,
            'salesperson_name': self.salesperson_id.name if self.salesperson_id else 'All',
            'products': self._get_report_data()
        }
        return self.env.ref('idil.action_report_kitchen_quantity').report_action(self, data=data)

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
