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

    salesperson_id = fields.Many2one(
        'idil.sales.sales_personnel',
        string='Salesperson',
        help='Select a specific salesperson. Only applicable for Salesperson Sales.'
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
            'source': self.sales_source
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
            -- Salesperson Sales
            SELECT 
                id,
                order_date as sale_date,
                (order_total / NULLIF(rate, 0)) as amount_usd,
                order_total as amount_shillings
            FROM idil_sale_order 
            WHERE state = 'confirmed'
              AND order_date BETWEEN %(start)s AND %(end)s
              AND company_id = %(company_id)s
              AND (%(salesperson_id)s IS NULL OR sales_person_id = %(salesperson_id)s)
              AND (%(source)s IN ('all', 'salesperson'))

            UNION ALL

            -- Customer Sales
            SELECT 
                id,
                order_date as sale_date,
                (order_total / NULLIF(rate, 0)) as amount_usd,
                order_total as amount_shillings
            FROM idil_customer_sale_order
            WHERE state = 'confirmed'
              AND order_date BETWEEN %(start)s AND %(end)s
              AND company_id = %(company_id)s
              AND %(salesperson_id)s IS NULL
              AND (%(source)s IN ('all', 'customer'))

            UNION ALL

            -- Staff Sales
            SELECT 
                id,
                sales_date as sale_date,
                (total_amount / NULLIF(rate, 0)) as amount_usd,
                total_amount as amount_shillings
            FROM idil_staff_sales
            WHERE state = 'confirmed'
              AND sales_date BETWEEN %(start)s AND %(end)s
              AND company_id = %(company_id)s
              AND %(salesperson_id)s IS NULL
              AND (%(source)s IN ('all', 'staff'))
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
            'source': self.sales_source
        }

        sql = """
        SELECT 
            DATE(sale_date) as sale_date,
            product_name,
            SUM(qty_sold) as qty_sold,
            SUM(revenue_usd) as revenue_usd,
            SUM(revenue_shillings) as revenue_shillings
        FROM (
            -- Salesperson Sales
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
              AND so.order_date BETWEEN %(start)s AND %(end)s
              AND so.company_id = %(company_id)s
              AND (%(salesperson_id)s IS NULL OR so.sales_person_id = %(salesperson_id)s)
              AND (%(source)s IN ('all', 'salesperson'))

            UNION ALL

            -- Customer Sales
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
              AND so.order_date BETWEEN %(start)s AND %(end)s
              AND so.company_id = %(company_id)s
              AND %(salesperson_id)s IS NULL
              AND (%(source)s IN ('all', 'customer'))

            UNION ALL

            -- Staff Sales
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
              AND so.sales_date BETWEEN %(start)s AND %(end)s
              AND so.company_id = %(company_id)s
              AND %(salesperson_id)s IS NULL
              AND (%(source)s IN ('all', 'staff'))
        ) as combined_products
        GROUP BY DATE(sale_date), product_name
        ORDER BY sale_date, revenue_usd DESC
        """

        self.env.cr.execute(sql, params)
        return self.env.cr.dictfetchall()

    def _get_payment_methods_data(self):
        """Get payment method breakdown per day - Not available in current schema"""
        # Payment information is tracked in idil.sales.receipt table, not on sales order
        # Returning empty list for now
        return []

    def _get_salesperson_performance_data(self):
        """Get salesperson/source performance per day (Unified)"""
        params = {
            'start': self.start_date,
            'end': self.end_date,
            'company_id': self.company_id.id,
            'salesperson_id': self.salesperson_id.id if self.salesperson_id else None,
            'source': self.sales_source
        }

        sql = """
        SELECT 
            DATE(sale_date) as sale_date,
            salesperson,
            COUNT(id) as orders,
            SUM(revenue_usd) as revenue_usd,
            SUM(revenue_shillings) as revenue_shillings
        FROM (
            -- Salesperson Sales
            SELECT 
                so.id,
                so.order_date as sale_date,
                COALESCE(sp.name, 'Unknown') as salesperson,
                (so.order_total / NULLIF(so.rate, 0)) as revenue_usd,
                so.order_total as revenue_shillings
            FROM idil_sale_order so
            LEFT JOIN idil_sales_sales_personnel sp ON so.sales_person_id = sp.id
            WHERE so.state = 'confirmed'
              AND so.order_date BETWEEN %(start)s AND %(end)s
              AND so.company_id = %(company_id)s
              AND (%(salesperson_id)s IS NULL OR so.sales_person_id = %(salesperson_id)s)
              AND (%(source)s IN ('all', 'salesperson'))

            UNION ALL

            -- Customer Sales
            SELECT 
                id,
                order_date as sale_date,
                'Customer Sales' as salesperson,
                (order_total / NULLIF(rate, 0)) as revenue_usd,
                order_total as revenue_shillings
            FROM idil_customer_sale_order
            WHERE state = 'confirmed'
              AND order_date BETWEEN %(start)s AND %(end)s
              AND company_id = %(company_id)s
              AND %(salesperson_id)s IS NULL
              AND (%(source)s IN ('all', 'customer'))

            UNION ALL

            -- Staff Sales
            SELECT 
                id,
                sales_date as sale_date,
                'Staff Sales' as salesperson,
                (total_amount / NULLIF(rate, 0)) as revenue_usd,
                total_amount as revenue_shillings
            FROM idil_staff_sales
            WHERE state = 'confirmed'
              AND sales_date BETWEEN %(start)s AND %(end)s
              AND company_id = %(company_id)s
              AND %(salesperson_id)s IS NULL
              AND (%(source)s IN ('all', 'staff'))
        ) as combined_performance
        GROUP BY DATE(sale_date), salesperson
        ORDER BY sale_date, revenue_usd DESC
        """

        self.env.cr.execute(sql, params)
        return self.env.cr.dictfetchall()

    def generate_pdf_report(self):
        """Generate PDF report"""
        import logging
        _logger = logging.getLogger(__name__)
        
        daily_summary = self._get_daily_summary_data()
        products_breakdown = self._get_products_breakdown_data()
        payment_methods = self._get_payment_methods_data()
        salesperson_performance = self._get_salesperson_performance_data()
        
        _logger.info("=" * 50)
        _logger.info("DAILY SALES REPORT DEBUG")
        _logger.info(f"Date Range: {self.start_date} to {self.end_date}")
        _logger.info(f"Salesperson: {self.salesperson_id.name if self.salesperson_id else 'All'}")
        _logger.info(f"Daily Summary Records: {len(daily_summary)}")
        _logger.info(f"Products Records: {len(products_breakdown)}")
        _logger.info(f"Salesperson Performance Records: {len(salesperson_performance)}")
        if daily_summary:
            _logger.info(f"First Daily Record: {daily_summary[0]}")
        _logger.info("=" * 50)
        
        data = {
            'start_date': self.start_date,
            'end_date': self.end_date,
            'company_id': self.company_id.id,
            'salesperson_id': self.salesperson_id.id if self.salesperson_id else None,
            'salesperson_name': self.salesperson_id.name if self.salesperson_id else 'All Salespeople',
            'report_type': self.report_type,
            'currency_display': self.currency_display,
            'daily_summary': daily_summary,
            'products_breakdown': products_breakdown,
            'payment_methods': payment_methods,
            'salesperson_performance': salesperson_performance,
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
            'payment_methods': data.get('payment_methods', []),
            'salesperson_performance': data.get('salesperson_performance', []),
            'company': company,
        }
