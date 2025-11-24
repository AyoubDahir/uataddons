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

        # 3. Categorize into Operating, Investing, Financing
        operating_inflows = {}
        operating_outflows = {}
        investing_inflows = {}
        investing_outflows = {}
        financing_inflows = {}
        financing_outflows = {}
        
        total_operating_in = 0.0
        total_operating_out = 0.0
        total_investing_in = 0.0
        total_investing_out = 0.0
        total_financing_in = 0.0
        total_financing_out = 0.0

        for line in lines:
            # EXCLUDE INTERNAL CASH TRANSFERS
            booking = line.transaction_booking_id
            all_accounts = booking.booking_lines.mapped('account_number')
            
            # Skip if ALL accounts are cash/bank (internal transfer)
            all_cash = all(acc.account_type in ['cash', 'bank_transfer'] for acc in all_accounts if acc)
            if all_cash and len(all_accounts) > 0:
                continue
            
            # Get the "other" account (non-cash)
            other_accounts = [acc for acc in all_accounts 
                             if acc and acc.account_type not in ['cash', 'bank_transfer']]
            
            if not other_accounts:
                continue  # Skip if no other account found
            
            other_account = other_accounts[0]  # Take first non-cash account
            
            # Determine amount and direction
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

            # Classify by account type
            category = 'operating'  # Default
            
            # Check FinancialReporting field
            if other_account.FinancialReporting == 'PL':
                # Profit & Loss accounts (Revenue/Expense) → Operating
                category = 'operating'
            elif other_account.FinancialReporting == 'BS':
                # Balance Sheet accounts - need more analysis
                header_code = other_account.header_code or ''
                account_name = (other_account.name or '').lower()
                
                # Investing: Fixed Assets (typically 15xx or 16xx)
                if header_code.startswith('15') or header_code.startswith('16') or \
                   'equipment' in account_name or 'machinery' in account_name or \
                   'vehicle' in account_name or 'building' in account_name:
                    category = 'investing'
                # Financing: Equity, Loans, Drawings
                elif header_code.startswith('3') or \
                     'equity' in account_name or 'capital' in account_name or \
                     'loan' in account_name or 'drawing' in account_name or \
                     'dividend' in account_name:
                    category = 'financing'
                else:
                    # Other BS accounts (Receivable, Payable, Inventory) → Operating
                    category = 'operating'
            
            source = line.transaction_booking_id.trx_source_id
            source_name = source.name if source else "Other"
            
            # Add to appropriate category
            if category == 'operating':
                if is_inflow:
                    total_operating_in += amount
                    operating_inflows[source_name] = operating_inflows.get(source_name, 0) + amount
                else:
                    total_operating_out += amount
                    operating_outflows[source_name] = operating_outflows.get(source_name, 0) + amount
            elif category == 'investing':
                if is_inflow:
                    total_investing_in += amount
                    investing_inflows[source_name] = investing_inflows.get(source_name, 0) + amount
                else:
                    total_investing_out += amount
                    investing_outflows[source_name] = investing_outflows.get(source_name, 0) + amount
            elif category == 'financing':
                if is_inflow:
                    total_financing_in += amount
                    financing_inflows[source_name] = financing_inflows.get(source_name, 0) + amount
                else:
                    total_financing_out += amount
                    financing_outflows[source_name] = financing_outflows.get(source_name, 0) + amount

        # Format for report
        operating_in_list = [{'name': k, 'amount': v} for k, v in operating_inflows.items()]
        operating_out_list = [{'name': k, 'amount': v} for k, v in operating_outflows.items()]
        investing_in_list = [{'name': k, 'amount': v} for k, v in investing_inflows.items()]
        investing_out_list = [{'name': k, 'amount': v} for k, v in investing_outflows.items()]
        financing_in_list = [{'name': k, 'amount': v} for k, v in financing_inflows.items()]
        financing_out_list = [{'name': k, 'amount': v} for k, v in financing_outflows.items()]
        
        net_operating = total_operating_in - total_operating_out
        net_investing = total_investing_in - total_investing_out
        net_financing = total_financing_in - total_financing_out
        net_cash_flow = net_operating + net_investing + net_financing

        company = self.env['res.company'].browse(company_id)

        return {
            'doc_ids': docids,
            'doc_model': 'idil.cashflow.report.wizard',
            'data': data,
            'start_date': start_date,
            'end_date': end_date,
            # Operating
            'operating_inflows': operating_in_list,
            'operating_outflows': operating_out_list,
            'total_operating_in': total_operating_in,
            'total_operating_out': total_operating_out,
            'net_operating': net_operating,
            # Investing
            'investing_inflows': investing_in_list,
            'investing_outflows': investing_out_list,
            'total_investing_in': total_investing_in,
            'total_investing_out': total_investing_out,
            'net_investing': net_investing,
            # Financing
            'financing_inflows': financing_in_list,
            'financing_outflows': financing_out_list,
            'total_financing_in': total_financing_in,
            'total_financing_out': total_financing_out,
            'net_financing': net_financing,
            # Totals
            'net_cash_flow': net_cash_flow,
            'company_name': data.get('company_name'),
            'company': company,
        }
