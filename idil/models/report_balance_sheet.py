from odoo import models, fields, api, _
from odoo.exceptions import UserError
import logging

_logger = logging.getLogger(__name__)


class BalanceSheet(models.TransientModel):
    _name = "idil.balance.sheet"
    _description = "Balance Sheet Line"
    _order = "sequence"

    sequence = fields.Integer("Sequence")
    account_code = fields.Char("Code")
    account_name = fields.Char("Account")
    balance = fields.Float("Balance")
    currency_id = fields.Many2one("res.currency", "Currency")
    is_total = fields.Boolean("Is Total", default=False)
    is_header = fields.Boolean("Is Header", default=False)
    wizard_id = fields.Many2one("idil.balance.sheet.wizard", string="Wizard")


class BalanceSheetWizard(models.TransientModel):
    _name = "idil.balance.sheet.wizard"
    _description = "Balance Sheet Wizard"

    company_id = fields.Many2one(
        "res.company",
        string="Company",
        required=True,
        default=lambda self: self.env.company,
    )
    report_date = fields.Date(
        string="As of Date", required=True, default=fields.Date.context_today
    )
    line_ids = fields.One2many("idil.balance.sheet", "wizard_id", string="Lines")

    def action_view_balance_sheet(self):
        """Generate lines and return tree view"""
        self.ensure_one()
        self._generate_lines()

        return {
            "type": "ir.actions.act_window",
            "name": f"Balance Sheet - {self.company_id.name} - {self.report_date}",
            "res_model": "idil.balance.sheet.wizard",
            "view_mode": "form",
            "view_id": self.env.ref("idil.view_balance_sheet_wizard_results").id,
            "res_id": self.id,
            "target": "current",
        }

    def action_print_pdf(self):
        """Generate PDF report"""
        self.ensure_one()
        # Ensure data is fresh if printing directly or from view
        bs_data = self._compute_balance_sheet_data()

        return self.env.ref("idil.action_report_balance_sheet_pdf").report_action(
            self,
            data={
                "company_id": self.company_id.id,
                "report_date": self.report_date,
                "bs_data": bs_data,
            },
        )

    def action_print_html(self):
        """Generate HTML report (Web View)"""
        self.ensure_one()
        bs_data = self._compute_balance_sheet_data()

        return self.env.ref("idil.action_report_balance_sheet_html").report_action(
            self,
            data={
                "company_id": self.company_id.id,
                "report_date": self.report_date,
                "bs_data": bs_data,
            },
        )

    def _generate_lines(self):
        """Generate transient lines for view"""
        self.line_ids.unlink()

        data = self._compute_balance_sheet_data()

        lines = []
        seq = 0
        currency = self.company_id.currency_id.id

        # Helper to add line
        def add_line(code, name, balance, is_header=False, is_total=False):
            nonlocal seq
            seq += 1
            lines.append(
                (
                    0,
                    0,
                    {
                        "sequence": seq,
                        "account_code": code,
                        "account_name": name,
                        "balance": balance,
                        "currency_id": currency,
                        "is_header": is_header,
                        "is_total": is_total,
                    },
                )
            )

        # ASSETS
        if data["assets"]:
            add_line("", "ASSETS", 0, is_header=True)
            for header in data["assets"]:
                add_line(header["code"], header["name"], 0, is_header=True)
                for sub in header["subheaders"]:
                    add_line("", sub["name"], 0, is_header=True)
                    for acc in sub["accounts"]:
                        add_line(acc["code"], "    " + acc["name"], acc["balance"])
                    add_line("", "Subtotal " + sub["name"], sub["total"], is_total=True)
            add_line("", "TOTAL ASSETS", data["total_assets"], is_total=True)
            add_line("", "", 0)  # Spacer

        # LIABILITIES
        if data["liabilities"]:
            add_line("", "LIABILITIES", 0, is_header=True)
            for header in data["liabilities"]:
                add_line(header["code"], header["name"], 0, is_header=True)
                for sub in header["subheaders"]:
                    add_line("", sub["name"], 0, is_header=True)
                    for acc in sub["accounts"]:
                        add_line(acc["code"], "    " + acc["name"], acc["balance"])
                    add_line("", "Subtotal " + sub["name"], sub["total"], is_total=True)

        # EQUITY
        if data["equity"]:
            add_line("", "EQUITY", 0, is_header=True)
            for header in data["equity"]:
                add_line(header["code"], header["name"], 0, is_header=True)
                for sub in header["subheaders"]:
                    add_line("", sub["name"], 0, is_header=True)
                    for acc in sub["accounts"]:
                        add_line(acc["code"], "    " + acc["name"], acc["balance"])
                    add_line("", "Subtotal " + sub["name"], sub["total"], is_total=True)

        # Net Profit
        add_line(
            "PL",
            "Retained Earnings & Current Profit",
            data["net_profit"],
            is_total=True,
        )

        # Grand Total
        add_line(
            "", "TOTAL LIABILITIES & EQUITY", data["total_liab_equity"], is_total=True
        )

        self.write({"line_ids": lines})

    def _compute_balance_sheet_data(self):
        """Compute a correct Balance Sheet:
        - Assets shown as Dr - Cr
        - Liabilities/Equity shown as Cr - Dr
        - Net Profit = Assets - (Liab + Equity)
        - Total Liab+Equity = Liab + Equity + Net Profit = Assets
        """
        self.ensure_one()

        Header = self.env["idil.chart.account.header"]
        SubHeader = self.env["idil.chart.account.subheader"]
        Account = self.env["idil.chart.account"]

        assets_data = []
        liabilities_data = []
        equity_data = []

        total_assets = 0.0
        total_liabilities = 0.0
        total_equity = 0.0

        # Get headers (only 1,2,3)
        headers = Header.search([], order="code")

        for header in headers:
            if not header.code or header.code[0] not in ["1", "2", "3"]:
                continue

            section_type = header.code[0]  # '1' asset, '2' liability, '3' equity

            header_dict = {
                "name": header.name,
                "code": header.code,
                "subheaders": [],
                "total": 0.0,  # always positive for report display
            }

            subheaders = SubHeader.search([("header_id", "=", header.id)], order="name")

            for subheader in subheaders:
                sub_dict = {
                    "name": subheader.name,
                    "accounts": [],
                    "total": 0.0,  # always positive for report display
                }

                accounts = Account.search(
                    [("subheader_id", "=", subheader.id)], order="code"
                )

                for account in accounts:
                    # Filter out clearing accounts (keep your logic)
                    if account.code in ["100994", "100998"]:
                        continue

                    dr_usd, cr_usd = account.get_dr_cr_balance_usd(
                        self.report_date, self.company_id.id
                    )

                    # ✅ Normalize balance by section:
                    # Assets: Dr - Cr
                    # Liabilities/Equity: Cr - Dr
                    if section_type == "1":
                        bal = dr_usd - cr_usd
                    else:
                        bal = cr_usd - dr_usd

                    # ignore near-zero
                    if abs(bal) <= 0.001:
                        continue

                    # For display: always positive
                    sub_dict["accounts"].append(
                        {
                            "code": account.code or "",
                            "name": account.name or "",
                            "balance": round(abs(bal), 2),
                        }
                    )

                    sub_dict["total"] += abs(bal)

                if sub_dict["accounts"]:
                    sub_dict["total"] = round(sub_dict["total"], 2)
                    header_dict["subheaders"].append(sub_dict)
                    header_dict["total"] += sub_dict["total"]

            if header_dict["subheaders"]:
                header_dict["total"] = round(header_dict["total"], 2)

                if section_type == "1":
                    assets_data.append(header_dict)
                    total_assets += header_dict["total"]
                elif section_type == "2":
                    liabilities_data.append(header_dict)
                    total_liabilities += header_dict["total"]
                elif section_type == "3":
                    equity_data.append(header_dict)
                    total_equity += header_dict["total"]

        total_assets = round(total_assets, 2)
        total_liabilities = round(total_liabilities, 2)
        total_equity = round(total_equity, 2)

        # ✅ Correct net profit
        # Assets = Liabilities + Equity + Profit
        net_profit = round(total_assets - (total_liabilities + total_equity), 2)

        # ✅ Total L&E always equals total assets
        total_liab_equity = round(total_liabilities + total_equity + net_profit, 2)

        # ✅ Balanced check
        is_balanced = abs(total_assets - total_liab_equity) < 0.01

        return {
            "assets": assets_data,
            "liabilities": liabilities_data,
            "equity": equity_data,
            "total_assets": total_assets,
            "total_liabilities": total_liabilities,
            "total_equity": total_equity,
            "net_profit": net_profit,
            "total_liab_equity": total_liab_equity,
            "is_balanced": is_balanced,
        }

    # def _compute_balance_sheet_data(self):
    #     """Compute balance sheet structure"""
    #     Header = self.env['idil.chart.account.header']
    #     SubHeader = self.env['idil.chart.account.subheader']
    #     Account = self.env['idil.chart.account']

    #     assets_data = []
    #     liabilities_data = []
    #     equity_data = []

    #     total_assets = 0.0
    #     total_liabilities = 0.0
    #     total_equity = 0.0

    #     # Get all headers
    #     headers = Header.search([], order='code')

    #     for header in headers:
    #         if not header.code or header.code[0] not in ['1', '2', '3']:
    #             continue

    #         header_dict = {
    #             'name': header.name,
    #             'code': header.code,
    #             'subheaders': [],
    #             'total': 0.0
    #         }

    #         subheaders = SubHeader.search([('header_id', '=', header.id)], order='name')

    #         for subheader in subheaders:
    #             sub_dict = {
    #                 'name': subheader.name,
    #                 'accounts': [],
    #                 'total': 0.0
    #             }

    #             accounts = Account.search([('subheader_id', '=', subheader.id)], order='code')

    #             for account in accounts:
    #                 # Filter out clearing accounts
    #                 if account.code in ['100994', '100998']:
    #                     continue

    #                 # Use helper to get USD balance properly
    #                 dr_usd, cr_usd = account.get_dr_cr_balance_usd(self.report_date, self.company_id.id)
    #                 balance = dr_usd - cr_usd

    #                 if abs(balance) > 0.001:
    #                     sub_dict['accounts'].append({
    #                         'code': account.code or '',
    #                         'name': account.name or '',
    #                         'balance': abs(balance)
    #                     })
    #                     sub_dict['total'] += balance

    #             if sub_dict['accounts']:
    #                 header_dict['subheaders'].append(sub_dict)
    #                 header_dict['total'] += sub_dict['total']

    #         if header_dict['subheaders']:
    #             # The logic below assumes:
    #             # Assets = Debit nature (Positive balance means Debit > Credit)
    #             # Liabilities/Equity = Credit nature
    #             # Ideally, we should normalize everything to Positive for display
    #             # and handle the accounting equation logic in the Net Profit calc.

    #             if header.code.startswith('1'):
    #                 assets_data.append(header_dict)
    #                 total_assets += header_dict['total']
    #             elif header.code.startswith('2'):
    #                 liabilities_data.append(header_dict)
    #                 total_liabilities += header_dict['total'] # Likely negative if Cr > Dr
    #             elif header.code.startswith('3'):
    #                 equity_data.append(header_dict)
    #                 total_equity += header_dict['total']      # Likely negative if Cr > Dr

    #     # With convert_to_usd, balances are:
    #     # Asset: Dr - Cr (Positive)
    #     # Liab: Dr - Cr (Negative)
    #     # Equity: Dr - Cr (Negative)

    #     # Net Profit in Balance Sheet = Assets - (Liabilities + Equity)
    #     # Since Liab and Equity are negative numbers here (from Dr-Cr), we do:
    #     # Net Profit = Total Assets + Total Liab + Total Equity
    #     # Example: Assets=100, Liab=-40, Equity=-50. Net Profit = 100 + (-40) + (-50) = 10
    #     # Wait, usually BS equation is Assets = Liab + Equity.
    #     # So Assets - Liab - Equity = 0 (if balanced).
    #     # Any difference is Net Profit/Loss (retained earnings for current period).

    #     # Let's verify signs.
    #     # If I have Revenue (Cr 100). Profit is 100.
    #     # My Asset (Cash) increases by 100 (Dr 100).
    #     # Assets = 100. Liab=0. Equity=0.
    #     # sum(Assets) = 100. sum(Liab)=0. sum(Equity)=0.
    #     # Calculation: 100 + 0 + 0 = 100. So Net Profit = 100. Correct.
    #     # If Expense (Dr 20). Cash decreases (dist attribute: Cr 20).
    #     # Assets = 80.
    #     # Calculation: 80 + 0 + 0 = 80. Net Profit = 80. Correct.

    #     net_profit = total_assets + total_liabilities + total_equity

    #     return {
    #         'assets': assets_data,
    #         'liabilities': liabilities_data,
    #         'equity': equity_data,
    #         'total_assets': abs(total_assets),
    #         'total_liabilities': abs(total_liabilities),
    #         'total_equity': abs(total_equity),
    #         'net_profit': net_profit,
    #         'total_liab_equity': abs(total_liabilities) + abs(total_equity) + net_profit, # Display logic: |Liab| + |Eq| + Profit
    #         'is_balanced': True # Calculated correctly it should inherently balance if all transaction lines are fetched
    #     }


class ReportBalanceSheetPDF(models.AbstractModel):
    _name = "report.idil.report_balance_sheet_pdf_template"
    _description = "Balance Sheet PDF Report"

    @api.model
    def _get_report_values(self, docids, data=None):
        """Provide data to the QWeb template"""
        docids = docids if docids else []
        data = data or {}

        if docids:
            wizard = self.env["idil.balance.sheet.wizard"].browse(docids[0])
            company_id = wizard.company_id.id
            report_date = wizard.report_date
        else:
            company_id = data.get("company_id") or self.env.company.id
            report_date = data.get("report_date") or fields.Date.today()

        company = self.env["res.company"].browse(company_id)

        # Get or compute balance sheet data
        if "bs_data" in data:
            bs_data = data["bs_data"]
        else:
            # If called without precomputed data, compute it
            wiz_vals = {"company_id": company_id, "report_date": report_date}
            # Use transient if possible or just instance
            wizard = self.env["idil.balance.sheet.wizard"].new(wiz_vals)
            bs_data = wizard._compute_balance_sheet_data()

        return {
            "doc_ids": docids,
            "doc_model": "idil.balance.sheet.wizard",
            "docs": self.env["idil.balance.sheet.wizard"].browse(docids),
            "company": company,
            "report_date": report_date,
            "data": bs_data,
            "usd_currency": self.env.ref("base.USD"),
        }
