from odoo import models, fields, api, tools

class ViewAllSales(models.Model):
    _name = "idil.view.all.sales"
    _description = "View All Sales"
    _auto = False
    _order = "date desc"

    ref = fields.Char(string="Reference", readonly=True)
    date = fields.Datetime(string="Date", readonly=True)
    sale_type = fields.Selection([
        ('salesperson', 'Salesperson Sale'),
        ('customer', 'Customer Sale'),
        ('staff', 'Staff Sale')
    ], string="Sale Type", readonly=True)
    party_name = fields.Char(string="Party Name", readonly=True)
    amount = fields.Float(string="Amount", readonly=True)
    state = fields.Selection([
        ('draft', 'Draft'),
        ('confirmed', 'Confirmed'),
        ('done', 'Done'),
        ('cancel', 'Cancelled')
    ], string="Status", readonly=True)
    currency_id = fields.Many2one('res.currency', string="Currency", readonly=True)

    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute("""
            CREATE OR REPLACE VIEW idil_view_all_sales AS (
                -- 1. Salesperson Sales
                SELECT
                    so.id::text || '-salesperson' as id,
                    so.name as ref,
                    so.order_date as date,
                    'salesperson' as sale_type,
                    sp.name as party_name,
                    so.order_total as amount,
                    so.state as state,
                    so.currency_id as currency_id
                FROM idil_sale_order so
                LEFT JOIN idil_sales_sales_personnel sp ON so.sales_person_id = sp.id

                UNION ALL

                -- 2. Customer Sales
                SELECT
                    cso.id::text || '-customer' as id,
                    cso.name as ref,
                    cso.order_date as date,
                    'customer' as sale_type,
                    cust.name as party_name,
                    cso.order_total as amount,
                    cso.state as state,
                    cso.currency_id as currency_id
                FROM idil_customer_sale_order cso
                LEFT JOIN idil_customer_registration cust ON cso.customer_id = cust.id

                UNION ALL

                -- 3. Staff Sales
                SELECT
                    ss.id::text || '-staff' as id,
                    ss.name as ref,
                    ss.sales_date as date,
                    'staff' as sale_type,
                    emp.name as party_name,
                    ss.total_amount as amount,
                    ss.state as state,
                    ss.currency_id as currency_id
                FROM idil_staff_sales ss
                LEFT JOIN idil_employee emp ON ss.employee_id = emp.id
            )
        """)
