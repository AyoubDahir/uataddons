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
    salesperson_id = fields.Many2one(
        'res.users',
        string='Salesperson',
        help='Leave empty for all salespeople'
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
        """Get daily summary: revenue, order count, avg order value"""
        params = {
            'start': self.start_date,
            'end': self.end_date,
            'company_id': self.company_id.id,
            'salesperson_id': self.salesperson_id.id if self.salesperson_id else None
        }

        sql = """
        SELECT 
            DATE(so.order_date) as sale_date,
            COUNT(DISTINCT so.id) as order_count,
            SUM(so.grand_total / NULLIF(so.rate, 0)) as revenue_usd,
            SUM(so.grand_total) as revenue_shillings,
            AVG(so.grand_total / NULLIF(so.rate, 0)) as avg_order_usd,
            AVG(so.grand_total) as avg_order_shillings
        FROM idil_sale_order so
        WHERE so.state = 'confirmed'
          AND so.order_date BETWEEN %(start)s AND %(end)s
          AND so.company_id = %(company_id)s
          AND (%(salesperson_id)s IS NULL OR so.user_id = %(salesperson_id)s)
        GROUP BY DATE(so.order_date)
        ORDER BY sale_date
        """

        self.env.cr.execute(sql, params)
        return self.env.cr.dictfetchall()

    def _get_products_breakdown_data(self):
        """Get products sold per day"""
        params = {
            'start': self.start_date,
            'end': self.end_date,
            'company_id': self.company_id.id,
            'salesperson_id': self.salesperson_id.id if self.salesperson_id else None
        }

        sql = """
        SELECT 
            DATE(so.order_date) as sale_date,
            p.name as product_name,
            SUM(sol.quantity) as qty_sold,
            SUM(sol.quantity * sol.price_unit / NULLIF(so.rate, 0)) as revenue_usd,
            SUM(sol.quantity * sol.price_unit) as revenue_shillings
        FROM idil_sale_order_line sol
        JOIN idil_sale_order so ON sol.order_id = so.id
        JOIN my_product_product p ON sol.product_id = p.id
        WHERE so.state = 'confirmed'
          AND so.order_date BETWEEN %(start)s AND %(end)s
          AND so.company_id = %(company_id)s
          AND (%(salesperson_id)s IS NULL OR so.user_id = %(salesperson_id)s)
        GROUP BY DATE(so.order_date), p.name
        ORDER BY sale_date, revenue_usd DESC
        """

        self.env.cr.execute(sql, params)
        return self.env.cr.dictfetchall()

    def _get_payment_methods_data(self):
        """Get payment method breakdown per day"""
        params = {
            'start': self.start_date,
            'end': self.end_date,
            'company_id': self.company_id.id,
            'salesperson_id': self.salesperson_id.id if self.salesperson_id else None
        }

        sql = """
        SELECT 
            DATE(so.order_date) as sale_date,
            COALESCE(so.payment_method, 'Not Specified') as payment_method,
            COUNT(*) as transaction_count,
            SUM(so.grand_total / NULLIF(so.rate, 0)) as amount_usd,
            SUM(so.grand_total) as amount_shillings
        FROM idil_sale_order so
        WHERE so.state = 'confirmed'
          AND so.order_date BETWEEN %(start)s AND %(end)s
          AND so.company_id = %(company_id)s
          AND (%(salesperson_id)s IS NULL OR so.user_id = %(salesperson_id)s)
        GROUP BY DATE(so.order_date), so.payment_method
        ORDER BY sale_date, amount_usd DESC
        """

        self.env.cr.execute(sql, params)
        return self.env.cr.dictfetchall()

    def _get_salesperson_performance_data(self):
        """Get salesperson performance per day"""
        params = {
            'start': self.start_date,
            'end': self.end_date,
            'company_id': self.company_id.id,
            'salesperson_id': self.salesperson_id.id if self.salesperson_id else None
        }

        sql = """
        SELECT 
            DATE(so.order_date) as sale_date,
            COALESCE(u.name, 'Unknown') as salesperson,
            COUNT(so.id) as orders,
            SUM(so.grand_total / NULLIF(so.rate, 0)) as revenue_usd,
            SUM(so.grand_total) as revenue_shillings
        FROM idil_sale_order so
        LEFT JOIN res_users u ON so.user_id = u.id
        WHERE so.state = 'confirmed'
          AND so.order_date BETWEEN %(start)s AND %(end)s
          AND so.company_id = %(company_id)s
          AND (%(salesperson_id)s IS NULL OR so.user_id = %(salesperson_id)s)
        GROUP BY DATE(so.order_date), u.name
        ORDER BY sale_date, revenue_usd DESC
        """

        self.env.cr.execute(sql, params)
        return self.env.cr.dictfetchall()

    def generate_pdf_report(self):
        """Generate PDF report"""
        data = {
            'start_date': self.start_date,
            'end_date': self.end_date,
            'salesperson_id': self.salesperson_id.id if self.salesperson_id else None,
            'salesperson_name': self.salesperson_id.name if self.salesperson_id else 'All Salespeople',
            'report_type': self.report_type,
            'currency_display': self.currency_display,
            'daily_summary': self._get_daily_summary_data(),
            'products_breakdown': self._get_products_breakdown_data(),
            'payment_methods': self._get_payment_methods_data(),
            'salesperson_performance': self._get_salesperson_performance_data(),
        }
        
        return self.env.ref('idil.action_report_daily_sales').report_action(self, data=data)

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
        company = self.env['res.company'].browse(data.get('company_id', self.env.company.id))
        
        return {
            'doc_ids': docids,
            'doc_model': 'idil.daily.sales.report.wizard',
            'data': data,
            'start_date': data.get('start_date'),
            'end_date': data.get('end_date'),
            'salesperson_name': data.get('salesperson_name'),
            'report_type': data.get('report_type'),
            'currency_display': data.get('currency_display'),
            'daily_summary': data.get('daily_summary', []),
            'products_breakdown': data.get('products_breakdown', []),
            'payment_methods': data.get('payment_methods', []),
            'salesperson_performance': data.get('salesperson_performance', []),
            'company': company,
        }
