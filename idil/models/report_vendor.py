from odoo import models, fields, api, _
from odoo.exceptions import UserError
from datetime import datetime
import logging

_logger = logging.getLogger(__name__)

class VendorReportWizard(models.TransientModel):
    _name = 'idil.vendor.report.wizard'
    _description = 'Vendor Report Wizard'

    report_type = fields.Selection([
        ('list', 'Vendor Aging & Balances (List)'),
        ('statement', 'Detailed Account Statement'),
        ('summary', 'Executive Vendor Summary'),
        ('items', 'Vendor Purchase Itemization')
    ], string='Report Type', default='list', required=True)

    vendor_id = fields.Many2one(
        'idil.vendor.registration', 
        string='Vendor',
        help='Select a specific vendor.'
    )

    start_date = fields.Date(
        string='Start Date',
        default=fields.Date.context_today
    )
    end_date = fields.Date(
        string='End Date',
        default=fields.Date.context_today,
        required=True
    )

    company_id = fields.Many2one(
        'res.company', 
        string='Company', 
        required=True, 
        default=lambda self: self.env.company
    )

    def generate_report(self):
        self.ensure_one()
        if self.report_type in ['statement', 'items'] and not self.vendor_id:
            raise UserError(_("Please select a vendor for this report type."))

        # Store ID in context to retrieve it later easily if docids are lost
        return self.env.ref('idil.action_report_vendor_unified').with_context(report_wizard_id=self.id).report_action(self, data={
            'id': self.id,
            'report_type': self.report_type,
            'vendor_id': self.vendor_id.id if self.vendor_id else None,
            'start_date': self.start_date,
            'end_date': self.end_date,
            'company_id': self.company_id.id,
        })

    def get_report_data(self, data=None):
        """Main entry point for QWeb to get data based on report type"""
        # If calling from abstract model, self might be empty. Use data.
        rtype = (data or {}).get('report_type') or self.report_type
        
        if rtype == 'list':
            return self._get_vendor_list_data(data)
        elif rtype == 'statement':
            return self._get_vendor_statement_data(data)
        elif rtype == 'summary':
            return self._get_vendor_summary_data(data)
        elif rtype == 'items':
            return self._get_vendor_items_data(data)
        return {}

    def _get_vendor_list_data(self, data=None):
        company_id = (data or {}).get('company_id') or self.company_id.id
        # Search all active vendors
        vendors = self.env['idil.vendor.registration'].search([('active', '=', True)])
        vendor_data = []
        total_due_usd = 0
        total_due_sl = 0

        for vendor in vendors:
            # Liability check - focus on vendor transactions
            trxs_domain = [
                ('vendor_id', '=', vendor.id),
                ('remaining_amount', '>', 0)
            ]
            # company_id filter for transactions
            trxs_domain += ['|', ('company_id', '=', company_id), ('company_id', '=', False)]
            
            trxs = self.env['idil.vendor_transaction'].search(trxs_domain)
            ven_due_sl = sum(trxs.mapped('remaining_amount'))
            
            ven_due_usd = 0
            for t in trxs:
                rate = getattr(t, 'rate', 1.0) or 1.0
                if t.currency_id.name == 'USD': rate = 1.0
                if rate <= 0: rate = 1.0
                ven_due_usd += (t.remaining_amount or 0.0) / rate

            vendor_data.append({
                'name': vendor.name,
                'phone': vendor.phone,
                'type': (vendor.supplier_type or 'Local').capitalize(),
                'due_sl': ven_due_sl,
                'due_usd': ven_due_usd,
            })
            total_due_usd += ven_due_usd
            total_due_sl += ven_due_sl

        return {
            'vendors': sorted(vendor_data, key=lambda x: x['due_usd'], reverse=True),
            'total_due_usd': total_due_usd,
            'total_due_sl': total_due_sl,
            'report_date': fields.Date.today(),
            'start_date': (data or {}).get('start_date'),
            'end_date': (data or {}).get('end_date') or fields.Date.today()
        }

    def _get_vendor_statement_data(self, data=None):
        vendor_id = (data or {}).get('vendor_id') or self.vendor_id.id
        vendor = self.env['idil.vendor.registration'].browse(vendor_id)
        if not vendor: return {'error': 'Vendor not found.'}
        
        payable_acc = vendor.account_payable_id
        if not payable_acc:
            return {'error': 'No payable account assigned to this vendor.'}

        company_id = (data or {}).get('company_id') or self.company_id.id
        start_date = (data or {}).get('start_date') or self.start_date
        end_date = (data or {}).get('end_date') or self.end_date

        # Opening Balance (Liability nature: Cr - Dr)
        opening_domain = [
            ('account_number', '=', payable_acc.id),
            ('transaction_date', '<', start_date),
            '|', ('company_id', '=', company_id), ('company_id', '=', False)
        ]
        opening_lines = self.env['idil.transaction_bookingline'].search(opening_domain)
        opening_bal_usd = 0
        for ln in opening_lines:
            rate = ln.rate or 1.0
            if ln.currency_id.name == 'USD': rate = 1.0
            if rate <= 0: rate = 1.0
            opening_bal_usd += (ln.cr_amount - ln.dr_amount) / rate

        # Current Period
        trans_domain = [
            ('account_number', '=', payable_acc.id),
            ('transaction_date', '>=', start_date),
            ('transaction_date', '<=', end_date),
            '|', ('company_id', '=', company_id), ('company_id', '=', False)
        ]
        lines = self.env['idil.transaction_bookingline'].search(trans_domain, order='transaction_date asc, id asc')
        
        statement_lines = []
        running_bal = opening_bal_usd
        total_dr = 0
        total_cr = 0
        
        for ln in lines:
            rate = ln.rate or 1.0
            if ln.currency_id.name == 'USD': rate = 1.0
            if rate <= 0: rate = 1.0
            
            dr_usd = ln.dr_amount / rate
            cr_usd = ln.cr_amount / rate
            running_bal += (cr_usd - dr_usd)
            
            total_dr += dr_usd
            total_cr += cr_usd
            
            statement_lines.append({
                'date': ln.transaction_date,
                'ref': ln.transaction_booking_id.transaction_number or 'TRX-%s' % ln.id,
                'desc': ln.description or 'Account Entry',
                'debit': dr_usd,
                'credit': cr_usd,
                'balance': running_bal,
            })

        return {
            'vendor_name': vendor.name,
            'vendor_phone': vendor.phone,
            'vendor_email': vendor.email,
            'acc_name': payable_acc.name,
            'acc_code': payable_acc.code,
            'opening_balance': opening_bal_usd,
            'lines': statement_lines,
            'total_debit': total_dr,
            'total_credit': total_cr,
            'closing_balance': running_bal,
            'report_date': fields.Date.context_today(self),
            'start_date': start_date,
            'end_date': end_date
        }

    def _get_vendor_summary_data(self, data=None):
        """Top level summary of vendor activity"""
        vendors = self.env['idil.vendor.registration'].search([])
        summary = {
            'total_vendors': len(vendors),
            'local_count': len(vendors.filtered(lambda v: v.supplier_type == 'local')),
            'intl_count': len(vendors.filtered(lambda v: v.supplier_type == 'international')),
            'total_payable_usd': 0,
            'top_vendors': [],
            'report_date': fields.Date.context_today(self)
        }
        
        list_data = self._get_vendor_list_data(data)
        summary['total_payable_usd'] = list_data['total_due_usd']
        summary['top_vendors'] = list_data['vendors'][:10]
        
        return summary

    def _get_vendor_items_data(self, data=None):
        """Get list of items purchased from this vendor"""
        vendor_id = (data or {}).get('vendor_id') or self.vendor_id.id
        vendor = self.env['idil.vendor.registration'].browse(vendor_id)
        
        # Raw items query
        query_items = """
            SELECT p.name, SUM(r.received_qty) as qty, AVG(r.cost_price) as avg_price, SUM(r.total_cost) as total
            FROM idil_received_purchase r
            JOIN idil_purchase_receipt rpt ON r.receipt_id = rpt.id
            JOIN idil_purchase_receipt_line rl ON r.receipt_line_id = rl.id
            JOIN idil_item p ON rl.item_id = p.id
            WHERE rpt.vendor_id = %s AND r.status = 'confirmed'
            GROUP BY p.name
        """
        
        # Finished products query - Using correct table my_product_product
        query_products = """
            SELECT p.name, SUM(r.received_qty) as qty, AVG(r.cost_price) as avg_price, SUM(r.received_qty * r.cost_price) as total
            FROM idil_received_product_purchase r
            JOIN my_product_product p ON r.product_id = p.id
            WHERE r.vendor_id = %s AND r.status = 'confirmed'
            GROUP BY p.name
        """
        
        self.env.cr.execute(query_items, (vendor.id,))
        items = self.env.cr.dictfetchall()
        
        self.env.cr.execute(query_products, (vendor.id,))
        products = self.env.cr.dictfetchall()
        
        all_lines = items + products
        all_lines.sort(key=lambda x: x['total'], reverse=True)
        
        return {
            'vendor_name': vendor.name,
            'items': all_lines,
            'total_items_cost': sum(r['total'] for r in all_lines),
            'report_date': fields.Date.today()
        }

class ReportVendorUnified(models.AbstractModel):
    _name = 'report.idil.report_vendor_unified_template'
    _description = 'Unified Vendor Report'

    @api.model
    def _get_report_values(self, docids, data=None):
        # Determine wizard ID
        wiz_id = (data or {}).get('id') or self.env.context.get('active_id') or (docids[0] if docids else None)
        wizard = self.env['idil.vendor.report.wizard'].browse(wiz_id)
        
        report_data = {}
        if wizard:
            report_data = wizard.get_report_data(data)
        elif data:
            # Try to run statically if data is present
            dummy_wiz = self.env['idil.vendor.report.wizard'].new(data)
            report_data = dummy_wiz.get_report_data(data)

        return {
            'doc_ids': docids,
            'doc_model': 'idil.vendor.report.wizard',
            'docs': wizard,
            'rd': report_data,
            'company': wizard.company_id or self.env.company,
        }
