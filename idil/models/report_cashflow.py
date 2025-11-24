from odoo import models, fields, api, _

class CashFlowReportWizard(models.TransientModel):
    _name = "idil.cashflow.report.wizard"
    _description = "Cash Flow Statement Wizard"

    start_date = fields.Date(string="Start Date", required=True, default=fields.Date.context_today)
    end_date = fields.Date(string="End Date", required=True, default=fields.Date.context_today)
    company_id = fields.Many2one('res.company', string='Company', required=True, default=lambda self: self.env.company)

    def generate_report(self):
        data = {
            'start_date': self.start_date,
            'end_date': self.end_date,
            'company_id': self.company_id.id,
            'company_name': self.company_id.name,
        }
        return self.env.ref('idil.action_report_cashflow').report_action(self, data=data)

class ReportCashFlow(models.AbstractModel):
    _name = 'report.idil.report_cashflow_template'
    _description = 'Cash Flow Statement Report'

    @api.model
    def _get_report_values(self, docids, data=None):
        start_date = data.get('start_date')
        end_date = data.get('end_date')
        company_id = data.get('company_id')

        # 1. Get Cash Accounts
        cash_accounts = self.env['idil.chart.account'].search([
            ('account_type', 'in', ['cash', 'bank_transfer']),
            ('company_id', '=', company_id)
        ])
        cash_account_ids = cash_accounts.ids

        # 2. Fetch Transactions for Cash Accounts
        # We need to look at lines affecting cash accounts
        domain = [
            ('account_number', 'in', cash_account_ids),
            ('transaction_date', '>=', start_date),
            ('transaction_date', '<=', end_date),
            ('company_id', '=', company_id)
        ]
        
        # We need to join with transaction_booking to get the source
        # But we can also just search lines and access .transaction_booking_id.trx_source_id
        lines = self.env['idil.transaction_bookingline'].search(domain)

        # 3. Categorize
        operating_inflows = {}
        operating_outflows = {}
        
        total_inflow = 0.0
        total_outflow = 0.0

        for line in lines:
            # Determine amount: Debit increases Cash (Inflow), Credit decreases Cash (Outflow)
            # Assuming Cash is an Asset account where Dr = Increase, Cr = Decrease
            
            amount = 0.0
            is_inflow = False
            
            if line.transaction_type == 'dr':
                amount = line.dr_amount
                is_inflow = True
            elif line.transaction_type == 'cr':
                amount = line.cr_amount
                is_inflow = False
            
            if amount == 0:
                continue

            source = line.transaction_booking_id.trx_source_id
            source_name = source.name if source else "Manual/Other"
            
            # Grouping logic
            if is_inflow:
                total_inflow += amount
                if source_name in operating_inflows:
                    operating_inflows[source_name] += amount
                else:
                    operating_inflows[source_name] = amount
            else:
                total_outflow += amount
                if source_name in operating_outflows:
                    operating_outflows[source_name] += amount
                else:
                    operating_outflows[source_name] = amount

        # Format for report
        inflows_list = [{'name': k, 'amount': v} for k, v in operating_inflows.items()]
        outflows_list = [{'name': k, 'amount': v} for k, v in operating_outflows.items()]
        
        net_cash_flow = total_inflow - total_outflow

        company = self.env['res.company'].browse(company_id)

        return {
            'doc_ids': docids,
            'doc_model': 'idil.cashflow.report.wizard',
            'data': data,
            'start_date': start_date,
            'end_date': end_date,
            'inflows': inflows_list,
            'outflows': outflows_list,
            'total_inflow': total_inflow,
            'total_outflow': total_outflow,
            'net_cash_flow': net_cash_flow,
            'company_name': data.get('company_name'),
            'company': company, # Pass the recordset for external_layout
        }
