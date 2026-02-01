from odoo import models, fields, api, _
from odoo.exceptions import UserError
import io
import base64
from datetime import datetime

class DailySalesReportWizard(models.TransientModel):
    _name = 'idil.daily.sales.report.wizard'
    _description = 'Daily Sales Report Wizard'

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
    sales_source = fields.Selection([
        ('all', 'All Sales'),
        ('salesperson', 'Salesperson Sales'),
        ('customer', 'Customer Sales'),
        ('staff', 'Staff Sales')
    ], string='Sales Source', default='all', required=True)

    include_returns = fields.Boolean(
        string='Include Returns',
        default=True,
        help='If checked, sales returns will be deducted from totals.'
    )

    salesperson_id = fields.Many2one(
        'idil.sales.sales_personnel',
        string='Person',
        help='Select a specific salesperson.'
    )
    
    employee_id = fields.Many2one(
        'idil.employee',
        string='Person',
        help='Select a specific staff member.'
    )
    
    customer_id = fields.Many2one(
        'idil.customer.registration',
        string='Person',
        help='Select a specific customer.'
    )
    
    report_type = fields.Selection([
        ('summary', 'Summary'),
        ('detailed', 'Detailed')
    ], string='Report Type', default='summary', required=True)
    
    currency_display = fields.Selection([
        ('usd', 'USD Only'),
        ('shilling', 'Shillings Only'),
        ('both', 'Both Currencies')
    ], string='Currency Display', default='usd', required=True)
    
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        required=True,
        default=lambda self: self.env.company
    )

    @api.constrains('start_date', 'end_date')
    def _check_dates(self):
        for record in self:
            if record.start_date and record.end_date:
                if record.start_date > record.end_date:
                    # Auto-swap dates
                    record.start_date, record.end_date = record.end_date, record.start_date

    def _get_daily_summary_data(self):
        """Get daily summary: revenue, order count, avg order value (Unified)"""
        params = {
            'start': self.start_date,
            'end': self.end_date,
            'company_id': self.company_id.id,
            'salesperson_id': self.salesperson_id.id if self.salesperson_id else None,
            'employee_id': self.employee_id.id if self.employee_id else None,
            'customer_id': self.customer_id.id if self.customer_id else None,
            'source': self.sales_source,
            'include_returns': self.include_returns
        }

        sql = """
        SELECT 
            DATE(sale_date) as sale_date,
            COUNT(id) as order_count,
            SUM(amount_usd) as revenue_usd,
            SUM(amount_shillings) as revenue_shillings,
            AVG(amount_usd) as avg_order_usd,
            AVG(amount_shillings) as avg_order_shillings
        FROM (
            -- 1. Salesperson Sales
            SELECT 
                id,
                order_date as sale_date,
                (order_total / NULLIF(rate, 0)) as amount_usd,
                order_total as amount_shillings
            FROM idil_sale_order 
            WHERE state = 'confirmed'
              AND DATE(order_date) BETWEEN %(start)s AND %(end)s
              AND company_id = %(company_id)s
              AND (%(salesperson_id)s IS NULL OR sales_person_id = %(salesperson_id)s)
              AND (%(source)s IN ('all', 'salesperson'))

            UNION ALL

            -- 2. Customer Sales
            SELECT 
                id,
                order_date as sale_date,
                (order_total / NULLIF(rate, 0)) as amount_usd,
                order_total as amount_shillings
            FROM idil_customer_sale_order
            WHERE state = 'confirmed'
              AND DATE(order_date) BETWEEN %(start)s AND %(end)s
              AND company_id = %(company_id)s
              AND (%(customer_id)s IS NULL OR customer_id = %(customer_id)s)
              AND (%(source)s IN ('all', 'customer'))

            UNION ALL

            -- 3. Staff Sales
            SELECT 
                id,
                sales_date as sale_date,
                (total_amount / NULLIF(rate, 0)) as amount_usd,
                total_amount as amount_shillings
            FROM idil_staff_sales
            WHERE state = 'confirmed'
              AND DATE(sales_date) BETWEEN %(start)s AND %(end)s
              AND company_id = %(company_id)s
              AND (%(employee_id)s IS NULL OR employee_id = %(employee_id)s)
              AND (%(source)s IN ('all', 'staff'))

            UNION ALL

            -- 4. Salesperson Returns (Negative)
            SELECT 
                id,
                return_date as sale_date,
                - (total_subtotal / NULLIF(rate, 0)) as amount_usd,
                - total_subtotal as amount_shillings
            FROM idil_sale_return
            WHERE state = 'confirmed'
              AND DATE(return_date) BETWEEN %(start)s AND %(end)s
              AND company_id = %(company_id)s
              AND (%(salesperson_id)s IS NULL OR salesperson_id = %(salesperson_id)s)
              AND (%(source)s IN ('all', 'salesperson'))
              AND %(include_returns)s IS TRUE

            UNION ALL

            -- 5. Customer Returns (Negative)
            SELECT 
                id,
                return_date as sale_date,
                - (total_return / NULLIF(rate, 0)) as amount_usd,
                - total_return as amount_shillings
            FROM idil_customer_sale_return
            WHERE state = 'confirmed'
              AND DATE(return_date) BETWEEN %(start)s AND %(end)s
              AND company_id = %(company_id)s
              AND (%(customer_id)s IS NULL OR customer_id = %(customer_id)s)
              AND (%(source)s IN ('all', 'customer'))
              AND %(include_returns)s IS TRUE
        ) as combined_sales
        GROUP BY DATE(sale_date)
        ORDER BY sale_date
        """

        self.env.cr.execute(sql, params)
        return self.env.cr.dictfetchall()

    def _get_products_breakdown_data(self):
        """Get products sold per day (Unified)"""
        params = {
            'start': self.start_date,
            'end': self.end_date,
            'company_id': self.company_id.id,
            'salesperson_id': self.salesperson_id.id if self.salesperson_id else None,
            'employee_id': self.employee_id.id if self.employee_id else None,
            'customer_id': self.customer_id.id if self.customer_id else None,
            'source': self.sales_source,
            'include_returns': self.include_returns
        }

        sql = """
        SELECT 
            DATE(sale_date) as sale_date,
            product_name,
            SUM(qty_sold) as qty_sold,
            SUM(revenue_usd) as revenue_usd,
            SUM(revenue_shillings) as revenue_shillings
        FROM (
            -- 1. Salesperson Sales
            SELECT 
                so.order_date as sale_date,
                p.name as product_name,
                sol.quantity as qty_sold,
                (sol.quantity * sol.price_unit / NULLIF(so.rate, 0)) as revenue_usd,
                (sol.quantity * sol.price_unit) as revenue_shillings
            FROM idil_sale_order_line sol
            JOIN idil_sale_order so ON sol.order_id = so.id
            JOIN my_product_product p ON sol.product_id = p.id
            WHERE so.state = 'confirmed'
              AND DATE(so.order_date) BETWEEN %(start)s AND %(end)s
              AND so.company_id = %(company_id)s
              AND (%(salesperson_id)s IS NULL OR so.sales_person_id = %(salesperson_id)s)
              AND (%(source)s IN ('all', 'salesperson'))

            UNION ALL

            -- 2. Customer Sales
            SELECT 
                so.order_date as sale_date,
                p.name as product_name,
                sol.quantity as qty_sold,
                (sol.quantity * sol.price_unit / NULLIF(so.rate, 0)) as revenue_usd,
                (sol.quantity * sol.price_unit) as revenue_shillings
            FROM idil_customer_sale_order_line sol
            JOIN idil_customer_sale_order so ON sol.order_id = so.id
            JOIN my_product_product p ON sol.product_id = p.id
            WHERE so.state = 'confirmed'
              AND DATE(so.order_date) BETWEEN %(start)s AND %(end)s
              AND so.company_id = %(company_id)s
              AND (%(customer_id)s IS NULL OR so.customer_id = %(customer_id)s)
              AND (%(source)s IN ('all', 'customer'))

            UNION ALL

            -- 3. Staff Sales
            SELECT 
                so.sales_date as sale_date,
                p.name as product_name,
                sol.quantity as qty_sold,
                (sol.total / NULLIF(so.rate, 0)) as revenue_usd,
                sol.total as revenue_shillings
            FROM idil_staff_sales_line sol
            JOIN idil_staff_sales so ON sol.sales_id = so.id
            JOIN my_product_product p ON sol.product_id = p.id
            WHERE so.state = 'confirmed'
              AND DATE(so.sales_date) BETWEEN %(start)s AND %(end)s
              AND so.company_id = %(company_id)s
              AND (%(employee_id)s IS NULL OR so.employee_id = %(employee_id)s)
              AND (%(source)s IN ('all', 'staff'))

            UNION ALL

            -- 4. Salesperson Returns (Negative)
            SELECT 
                sr.return_date as sale_date,
                p.name as product_name,
                - srl.returned_quantity as qty_sold,
                - (srl.returned_quantity * srl.price_unit / NULLIF(sr.rate, 0)) as revenue_usd,
                - (srl.returned_quantity * srl.price_unit) as revenue_shillings
            FROM idil_sale_return_line srl
            JOIN idil_sale_return sr ON srl.return_id = sr.id
            JOIN my_product_product p ON srl.product_id = p.id
            WHERE sr.state = 'confirmed'
              AND DATE(sr.return_date) BETWEEN %(start)s AND %(end)s
              AND sr.company_id = %(company_id)s
              AND (%(salesperson_id)s IS NULL OR sr.salesperson_id = %(salesperson_id)s)
              AND (%(source)s IN ('all', 'salesperson'))
              AND %(include_returns)s IS TRUE

            UNION ALL

            -- 5. Customer Returns (Negative)
            SELECT 
                sr.return_date as sale_date,
                p.name as product_name,
                - srl.return_quantity as qty_sold,
                - (srl.return_quantity * srl.price_unit / NULLIF(sr.rate, 0)) as revenue_usd,
                - (srl.return_quantity * srl.price_unit) as revenue_shillings
            FROM idil_customer_sale_return_line srl
            JOIN idil_customer_sale_return sr ON srl.return_id = sr.id
            JOIN my_product_product p ON srl.product_id = p.id
            WHERE sr.state = 'confirmed'
              AND DATE(sr.return_date) BETWEEN %(start)s AND %(end)s
              AND sr.company_id = %(company_id)s
              AND (%(customer_id)s IS NULL OR sr.customer_id = %(customer_id)s)
              AND (%(source)s IN ('all', 'customer'))
              AND %(include_returns)s IS TRUE
        ) as combined_products
        GROUP BY DATE(sale_date), product_name
        ORDER BY sale_date, revenue_usd DESC
        """

        self.env.cr.execute(sql, params)
        return self.env.cr.dictfetchall()

    def _get_payment_methods_data(self):
        """Get payment method breakdown per day (Unified)"""
        params = {
            'start': self.start_date,
            'end': self.end_date,
            'company_id': self.company_id.id,
            'source': self.sales_source
        }

        sql = """
        SELECT 
            DATE(payment_date) as sale_date,
            payment_method,
            COUNT(*) as transaction_count,
            SUM(amount_usd) as amount_usd,
            SUM(amount_shillings) as amount_shillings
        FROM (
            -- 1. Salesperson Payments
            SELECT 
                p.payment_date as payment_date,
                COALESCE(pm.name, acc.name, 'Unknown') as payment_method,
                (p.paid_amount / NULLIF(r.rate, 0)) as amount_usd,
                p.paid_amount as amount_shillings
            FROM idil_sales_payment p
            JOIN idil_sales_receipt r ON p.sales_receipt_id = r.id
            JOIN idil_chart_account acc ON p.payment_account = acc.id
            LEFT JOIN idil_payment_method pm ON pm.account_id = acc.id
            WHERE DATE(p.payment_date) BETWEEN %(start)s AND %(end)s
              AND r.company_id = %(company_id)s
              AND (r.sales_order_id IS NOT NULL)
              AND (%(source)s IN ('all', 'salesperson'))

            UNION ALL

            -- 2. Customer Payments
            SELECT 
                p.date as payment_date,
                pm.name as payment_method,
                (p.amount / NULLIF(r.rate, 0)) as amount_usd,
                p.amount as amount_shillings
            FROM idil_customer_sale_payment p
            JOIN idil_sales_receipt r ON p.sales_receipt_id = r.id
            JOIN idil_payment_method pm ON p.payment_method_id = pm.id
            WHERE DATE(p.date) BETWEEN %(start)s AND %(end)s
              AND r.company_id = %(company_id)s
              AND (r.cusotmer_sale_order_id IS NOT NULL)
              AND (%(source)s IN ('all', 'customer'))
        ) as combined_payments
        GROUP BY DATE(payment_date), payment_method
        ORDER BY sale_date, amount_usd DESC
        """

        self.env.cr.execute(sql, params)
        return self.env.cr.dictfetchall()

    def _get_detailed_source_data(self):
        """Get detailed sales data grouped by source for the report sections"""
        params = {
            'start': self.start_date,
            'end': self.end_date,
            'company_id': self.company_id.id,
            'salesperson_id': self.salesperson_id.id if self.salesperson_id else None,
            'employee_id': self.employee_id.id if self.employee_id else None,
            'customer_id': self.customer_id.id if self.customer_id else None,
            'source': self.sales_source,
            'include_returns': self.include_returns
        }

        # 1. Salesperson Sales
        sql_sp = """
            SELECT 
                COALESCE(sp.name, 'Unknown Salesperson') as source_name,
                p.name as product_name,
                SUM(sol.quantity) as qty,
                AVG(sol.price_unit) as unit_price,
                SUM(sol.quantity * sol.price_unit / NULLIF(so.rate, 0)) as total_usd,
                SUM(sol.quantity * sol.price_unit) as total_shillings
            FROM idil_sale_order_line sol
            JOIN idil_sale_order so ON sol.order_id = so.id
            JOIN my_product_product p ON sol.product_id = p.id
            LEFT JOIN idil_sales_sales_personnel sp ON so.sales_person_id = sp.id
            WHERE so.state = 'confirmed'
              AND DATE(so.order_date) BETWEEN %(start)s AND %(end)s
              AND so.company_id = %(company_id)s
              AND (%(salesperson_id)s IS NULL OR so.sales_person_id = %(salesperson_id)s)
              AND (%(source)s IN ('all', 'salesperson'))
            GROUP BY sp.name, p.name
            ORDER BY sp.name, p.name
        """
        
        # 2. Customer Sales
        sql_cust = """
            SELECT 
                COALESCE(cust.name, 'Customer') as source_name,
                p.name as product_name,
                SUM(sol.quantity) as qty,
                AVG(sol.price_unit) as unit_price,
                SUM(sol.quantity * sol.price_unit / NULLIF(so.rate, 0)) as total_usd,
                SUM(sol.quantity * sol.price_unit) as total_shillings
            FROM idil_customer_sale_order_line sol
            JOIN idil_customer_sale_order so ON sol.order_id = so.id
            JOIN my_product_product p ON sol.product_id = p.id
            LEFT JOIN idil_customer_registration cust ON so.customer_id = cust.id
            WHERE so.state = 'confirmed'
              AND DATE(so.order_date) BETWEEN %(start)s AND %(end)s
              AND so.company_id = %(company_id)s
              AND (%(customer_id)s IS NULL OR so.customer_id = %(customer_id)s)
              AND (%(source)s IN ('all', 'customer'))
            GROUP BY cust.name, p.name
            ORDER BY cust.name, p.name
        """

        # 3. Staff Sales
        sql_staff = """
            SELECT 
                COALESCE(emp.name, 'Employee') as source_name,
                p.name as product_name,
                SUM(sol.quantity) as qty,
                AVG(sol.total / NULLIF(sol.quantity, 0)) as unit_price,
                SUM(sol.total / NULLIF(so.rate, 0)) as total_usd,
                SUM(sol.total) as total_shillings
            FROM idil_staff_sales_line sol
            JOIN idil_staff_sales so ON sol.sales_id = so.id
            JOIN my_product_product p ON sol.product_id = p.id
            LEFT JOIN idil_employee emp ON so.employee_id = emp.id
            WHERE so.state = 'confirmed'
              AND DATE(so.sales_date) BETWEEN %(start)s AND %(end)s
              AND so.company_id = %(company_id)s
              AND (%(employee_id)s IS NULL OR so.employee_id = %(employee_id)s)
              AND (%(source)s IN ('all', 'staff'))
            GROUP BY emp.name, p.name
            ORDER BY emp.name, p.name
        """

        self.env.cr.execute(sql_sp, params)
        sp_data = self.env.cr.dictfetchall()
        
        self.env.cr.execute(sql_cust, params)
        cust_data = self.env.cr.dictfetchall()
        
        self.env.cr.execute(sql_staff, params)
        staff_data = self.env.cr.dictfetchall()

        return {
            'salesperson_sales': sp_data,
            'customer_sales': cust_data,
            'staff_sales': staff_data
        }

    def _get_salesperson_performance_data(self):
        """Get salesperson/source performance per day (Unified)"""
        params = {
            'start': self.start_date,
            'end': self.end_date,
            'company_id': self.company_id.id,
            'salesperson_id': self.salesperson_id.id if self.salesperson_id else None,
            'employee_id': self.employee_id.id if self.employee_id else None,
            'customer_id': self.customer_id.id if self.customer_id else None,
            'source': self.sales_source,
            'include_returns': self.include_returns
        }

        sql = """
        SELECT 
            DATE(sale_date) as sale_date,
            salesperson,
            COUNT(id) as orders,
            SUM(revenue_usd) as revenue_usd,
            SUM(revenue_shillings) as revenue_shillings
        FROM (
            -- 1. Salesperson Sales
            SELECT 
                so.id,
                so.order_date as sale_date,
                COALESCE(sp.name, 'Unknown Salesperson') as salesperson,
                (so.order_total / NULLIF(so.rate, 0)) as revenue_usd,
                so.order_total as revenue_shillings
            FROM idil_sale_order so
            LEFT JOIN idil_sales_sales_personnel sp ON so.sales_person_id = sp.id
            WHERE so.state = 'confirmed'
              AND DATE(so.order_date) BETWEEN %(start)s AND %(end)s
              AND so.company_id = %(company_id)s
              AND (%(salesperson_id)s IS NULL OR so.sales_person_id = %(salesperson_id)s)
              AND (%(source)s IN ('all', 'salesperson'))

            UNION ALL

            -- 2. Customer Sales
            SELECT 
                so.id,
                so.order_date as sale_date,
                COALESCE(cust.name, 'Customer Sales') as salesperson,
                (so.order_total / NULLIF(so.rate, 0)) as revenue_usd,
                so.order_total as revenue_shillings
            FROM idil_customer_sale_order so
            LEFT JOIN idil_customer_registration cust ON so.customer_id = cust.id
            WHERE so.state = 'confirmed'
              AND DATE(so.order_date) BETWEEN %(start)s AND %(end)s
              AND so.company_id = %(company_id)s
              AND (%(customer_id)s IS NULL OR so.customer_id = %(customer_id)s)
              AND (%(source)s IN ('all', 'customer'))

            UNION ALL

            -- 3. Staff Sales
            SELECT 
                st.id,
                st.sales_date as sale_date,
                COALESCE(emp.name, 'Staff Sales') as salesperson,
                (st.total_amount / NULLIF(st.rate, 0)) as revenue_usd,
                st.total_amount as revenue_shillings
            FROM idil_staff_sales st
            LEFT JOIN idil_employee emp ON st.employee_id = emp.id
            WHERE st.state = 'confirmed'
              AND DATE(st.sales_date) BETWEEN %(start)s AND %(end)s
              AND st.company_id = %(company_id)s
              AND (%(employee_id)s IS NULL OR st.employee_id = %(employee_id)s)
              AND (%(source)s IN ('all', 'staff'))

            UNION ALL

            -- 4. Salesperson Returns (Negative)
            SELECT 
                sr.id,
                sr.return_date as sale_date,
                COALESCE(sp.name, 'Unknown Salesperson') as salesperson,
                - (sr.total_subtotal / NULLIF(sr.rate, 0)) as revenue_usd,
                - sr.total_subtotal as revenue_shillings
            FROM idil_sale_return sr
            LEFT JOIN idil_sales_sales_personnel sp ON sr.salesperson_id = sp.id
            WHERE sr.state = 'confirmed'
              AND DATE(sr.return_date) BETWEEN %(start)s AND %(end)s
              AND sr.company_id = %(company_id)s
              AND (%(salesperson_id)s IS NULL OR sr.salesperson_id = %(salesperson_id)s)
              AND (%(source)s IN ('all', 'salesperson'))
              AND %(include_returns)s IS TRUE

            UNION ALL

            -- 5. Customer Returns (Negative)
            SELECT 
                sr.id,
                sr.return_date as sale_date,
                COALESCE(cust.name, 'Customer Sales') as salesperson,
                - (sr.total_return / NULLIF(sr.rate, 0)) as revenue_usd,
                - sr.total_return as revenue_shillings
            FROM idil_customer_sale_return sr
            LEFT JOIN idil_customer_registration cust ON sr.customer_id = cust.id
            WHERE sr.state = 'confirmed'
              AND DATE(sr.return_date) BETWEEN %(start)s AND %(end)s
              AND sr.company_id = %(company_id)s
              AND (%(customer_id)s IS NULL OR sr.customer_id = %(customer_id)s)
              AND (%(source)s IN ('all', 'customer'))
              AND %(include_returns)s IS TRUE
        ) as combined_performance
        GROUP BY DATE(sale_date), salesperson
        ORDER BY sale_date, revenue_usd DESC
        """

        self.env.cr.execute(sql, params)
        return self.env.cr.dictfetchall()

    def generate_pdf_report(self):
        """Generate PDF report"""
        return self._generate_report(report_type='pdf')

    def view_report(self):
        """View report in browser (HTML)"""
        return self._generate_report(report_type='html')

    def _generate_report(self, report_type='pdf'):
        """Common logic for report generation"""
        daily_summary = self._get_daily_summary_data()
        detailed_source_data = self._get_detailed_source_data()
        payment_methods = self._get_payment_methods_data()
        salesperson_performance = self._get_salesperson_performance_data()
        
        # Calculate Source Totals
        sp_total_usd = sum(d['total_usd'] or 0 for d in detailed_source_data['salesperson_sales'])
        sp_total_sh = sum(d['total_shillings'] or 0 for d in detailed_source_data['salesperson_sales'])
        
        cust_total_usd = sum(d['total_usd'] or 0 for d in detailed_source_data['customer_sales'])
        cust_total_sh = sum(d['total_shillings'] or 0 for d in detailed_source_data['customer_sales'])
        
        staff_total_usd = sum(d['total_usd'] or 0 for d in detailed_source_data['staff_sales'])
        staff_total_sh = sum(d['total_shillings'] or 0 for d in detailed_source_data['staff_sales'])

        total_orders = sum(d['order_count'] for d in daily_summary)
        total_revenue_usd = sum(d['revenue_usd'] or 0 for d in daily_summary)
        total_revenue_shillings = sum(d['revenue_shillings'] or 0 for d in daily_summary)

        # Percentages
        sp_pct = (sp_total_usd / total_revenue_usd * 100) if total_revenue_usd else 0
        cust_pct = (cust_total_usd / total_revenue_usd * 100) if total_revenue_usd else 0
        staff_pct = (staff_total_usd / total_revenue_usd * 100) if total_revenue_usd else 0

        data = {
            'start_date': self.start_date,
            'end_date': self.end_date,
            'company_id': self.company_id.id,
            'salesperson_id': self.salesperson_id.id if self.salesperson_id else None,
            'salesperson_name': self.salesperson_id.name if self.salesperson_id else 'All Salespeople',
            'report_type': self.report_type,
            'currency_display': self.currency_display,
            'daily_summary': daily_summary,
            'detailed_source_data': detailed_source_data,
            'payment_methods': payment_methods,
            'salesperson_performance': salesperson_performance,
            'total_orders': total_orders,
            'total_revenue_usd': total_revenue_usd,
            'total_revenue_shillings': total_revenue_shillings,
            'sp_total_usd': sp_total_usd,
            'sp_total_sh': sp_total_sh,
            'cust_total_usd': cust_total_usd,
            'cust_total_sh': cust_total_sh,
            'staff_total_usd': staff_total_usd,
            'staff_total_sh': staff_total_sh,
            'sp_pct': sp_pct,
            'cust_pct': cust_pct,
            'staff_pct': staff_pct,
        }
        
        report_action = self.env.ref('idil.action_report_daily_sales')
        action = report_action.report_action(self, data=data)
        if report_type == 'html':
            action['report_type'] = 'qweb-html'
        return action

    def generate_excel_report(self):
        """Generate Excel report"""
        try:
            import xlsxwriter
        except ImportError:
            raise UserError(_('Please install xlsxwriter: pip install xlsxwriter'))

        # Get data
        daily_summary = self._get_daily_summary_data()
        products = self._get_products_breakdown_data()
        payments = self._get_payment_methods_data()
        salespeople = self._get_salesperson_performance_data()

        # Create Excel file in memory
        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output, {'in_memory': True})

        # Formats
        header_format = workbook.add_format({
            'bold': True,
            'bg_color': '#4472C4',
            'font_color': 'white',
            'border': 1
        })
        date_format = workbook.add_format({'num_format': 'dd/mm/yyyy'})
        currency_format = workbook.add_format({'num_format': '$#,##0.00'})
        number_format = workbook.add_format({'num_format': '#,##0.00'})

        # Sheet 1: Daily Summary
        ws1 = workbook.add_worksheet('Daily Summary')
        ws1.write(0, 0, 'Date', header_format)
        ws1.write(0, 1, 'Orders', header_format)
        ws1.write(0, 2, 'Revenue (USD)', header_format)
        ws1.write(0, 3, 'Revenue (Shillings)', header_format)
        ws1.write(0, 4, 'Avg Order (USD)', header_format)

        row = 1
        for record in daily_summary:
            ws1.write(row, 0, record['sale_date'], date_format)
            ws1.write(row, 1, record['order_count'])
            ws1.write(row, 2, record['revenue_usd'] or 0, currency_format)
            ws1.write(row, 3, record['revenue_shillings'] or 0, number_format)
            ws1.write(row, 4, record['avg_order_usd'] or 0, currency_format)
            row += 1

        # Sheet 2: Products
        ws2 = workbook.add_worksheet('Products')
        ws2.write(0, 0, 'Date', header_format)
        ws2.write(0, 1, 'Product', header_format)
        ws2.write(0, 2, 'Quantity', header_format)
        ws2.write(0, 3, 'Revenue (USD)', header_format)
        ws2.write(0, 4, 'Revenue (Shillings)', header_format)

        row = 1
        for record in products:
            ws2.write(row, 0, record['sale_date'], date_format)
            ws2.write(row, 1, record['product_name'])
            ws2.write(row, 2, record['qty_sold'] or 0)
            ws2.write(row, 3, record['revenue_usd'] or 0, currency_format)
            ws2.write(row, 4, record['revenue_shillings'] or 0, number_format)
            row += 1

        # Sheet 3: Payment Methods
        ws3 = workbook.add_worksheet('Payment Methods')
        ws3.write(0, 0, 'Date', header_format)
        ws3.write(0, 1, 'Payment Method', header_format)
        ws3.write(0, 2, 'Transactions', header_format)
        ws3.write(0, 3, 'Amount (USD)', header_format)
        ws3.write(0, 4, 'Amount (Shillings)', header_format)

        row = 1
        for record in payments:
            ws3.write(row, 0, record['sale_date'], date_format)
            ws3.write(row, 1, record['payment_method'])
            ws3.write(row, 2, record['transaction_count'])
            ws3.write(row, 3, record['amount_usd'] or 0, currency_format)
            ws3.write(row, 4, record['amount_shillings'] or 0, number_format)
            row += 1

        # Sheet 4: Salespeople
        ws4 = workbook.add_worksheet('Salespeople')
        ws4.write(0, 0, 'Date', header_format)
        ws4.write(0, 1, 'Salesperson', header_format)
        ws4.write(0, 2, 'Orders', header_format)
        ws4.write(0, 3, 'Revenue (USD)', header_format)
        ws4.write(0, 4, 'Revenue (Shillings)', header_format)

        row = 1
        for record in salespeople:
            ws4.write(row, 0, record['sale_date'], date_format)
            ws4.write(row, 1, record['salesperson'])
            ws4.write(row, 2, record['orders'])
            ws4.write(row, 3, record['revenue_usd'] or 0, currency_format)
            ws4.write(row, 4, record['revenue_shillings'] or 0, number_format)
            row += 1

        workbook.close()
        output.seek(0)
        
        # Return as downloadable file
        filename = f'Daily_Sales_Report_{self.start_date}_{self.end_date}.xlsx'
        attachment = self.env['ir.attachment'].create({
            'name': filename,
            'type': 'binary',
            'datas': base64.b64encode(output.read()),
            'mimetype': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        })

        return {
            'type': 'ir.actions.act_url',
            'url': f'/web/content/{attachment.id}?download=true',
            'target': 'self',
        }


class ReportDailySales(models.AbstractModel):
    _name = 'report.idil.report_daily_sales_template'
    _description = 'Daily Sales Report'

    @api.model
    def _get_report_values(self, docids, data=None):
        import logging
        _logger = logging.getLogger(__name__)
        
        _logger.info("=" * 50)
        _logger.info("REPORT VALUES DEBUG")
        _logger.info(f"Doc IDs: {docids}")
        if data:
            _logger.info(f"Data keys: {data.keys()}")
            if 'daily_summary' in data:
                _logger.info(f"Daily Summary Count: {len(data['daily_summary'])}")
                if len(data['daily_summary']) > 0:
                    _logger.info(f"First Daily Record Type: {type(data['daily_summary'][0])}")
                    _logger.info(f"First Daily Record Date: {data['daily_summary'][0].get('sale_date')} (Type: {type(data['daily_summary'][0].get('sale_date'))})")
        else:
            _logger.warning("DATA IS NONE OR EMPTY")
        _logger.info("=" * 50)

        company = self.env['res.company'].browse(data.get('company_id', self.env.company.id))
        docs = self.env['idil.daily.sales.report.wizard'].browse(docids)
        
        return {
            'doc_ids': docids,
            'doc_model': 'idil.daily.sales.report.wizard',
            'docs': docs,
            'data': data,
            'start_date': data.get('start_date'),
            'end_date': data.get('end_date'),
            'salesperson_name': data.get('salesperson_name'),
            'report_type': data.get('report_type'),
            'currency_display': data.get('currency_display'),
            'daily_summary': data.get('daily_summary', []),
            'products_breakdown': data.get('products_breakdown', []),
            'detailed_source_data': data.get('detailed_source_data', {}),
            'payment_methods': data.get('payment_methods', []),
            'salesperson_performance': data.get('salesperson_performance', []),
            'total_orders': data.get('total_orders', 0),
            'total_revenue_usd': data.get('total_revenue_usd', 0.0),
            'total_revenue_shillings': data.get('total_revenue_shillings', 0.0),
            'sp_total_usd': data.get('sp_total_usd', 0.0),
            'sp_total_sh': data.get('sp_total_sh', 0.0),
            'cust_total_usd': data.get('cust_total_usd', 0.0),
            'cust_total_sh': data.get('cust_total_sh', 0.0),
            'staff_total_usd': data.get('staff_total_usd', 0.0),
            'staff_total_sh': data.get('staff_total_sh', 0.0),
            'sp_pct': data.get('sp_pct', 0.0),
            'cust_pct': data.get('cust_pct', 0.0),
            'staff_pct': data.get('staff_pct', 0.0),
            'company': company,
        }
