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
        """Compute balance sheet structure + Net Profit with rounding + no zero accounts + no tiny negative assets"""
        Header = self.env["idil.chart.account.header"]
        SubHeader = self.env["idil.chart.account.subheader"]
        Account = self.env["idil.chart.account"]

        assets_data = []
        liabilities_data = []
        equity_data = []

        total_assets = 0.0
        total_liabilities = 0.0
        total_equity = 0.0

        # ----------------------------
        # Settings for USD display
        # ----------------------------
        USD_ROUND = 0.01  # show 2 decimals
        EPS_ASSET = (
            0.05  # if asset is between -0.05 and 0 -> force to 0 (rounding drift)
        )

        def round_usd(x):
            # stable rounding to 2 decimals
            return round((x or 0.0) / USD_ROUND) * USD_ROUND

        headers = Header.search([], order="code")

        for header in headers:
            if not header.code or header.code[0] not in ["1", "2", "3"]:
                continue

            header_type = header.code[0]  # '1' assets, '2' liabilities, '3' equity

            header_dict = {
                "name": header.name,
                "code": header.code,
                "subheaders": [],
                "total": 0.0,  # display total
            }

            subheaders = SubHeader.search([("header_id", "=", header.id)], order="name")

            for subheader in subheaders:
                sub_dict = {
                    "name": subheader.name,
                    "accounts": [],
                    "total": 0.0,
                }

                accounts = Account.search(
                    [
                        ("subheader_id", "=", subheader.id),
                        ("company_id", "=", self.company_id.id),
                    ],
                    order="code",
                )

                for account in accounts:
                    # Skip clearing accounts if you want
                    if account.code in ["100994", "100998"]:
                        continue

                    dr_usd, cr_usd = account.get_dr_cr_balance_usd(
                        self.report_date, self.company_id.id
                    )

                    signed = (dr_usd or 0.0) - (cr_usd or 0.0)  # dr - cr

                    # Nature display:
                    # Assets: dr-cr
                    # Liabilities/Equity: cr-dr => -(dr-cr)
                    if header_type in ("2", "3"):
                        display_balance = -signed
                    else:
                        display_balance = signed

                    # ✅ Round FIRST (important!)
                    display_balance = round_usd(display_balance)

                    # ✅ Fix tiny negative assets caused by FX conversion/rounding
                    if (
                        header_type == "1"
                        and display_balance < 0
                        and abs(display_balance) <= EPS_ASSET
                    ):
                        display_balance = 0.0

                    # ✅ Do NOT show zero-balance accounts (after rounding)
                    if abs(display_balance) < USD_ROUND:
                        continue

                    sub_dict["accounts"].append(
                        {
                            "code": account.code or "",
                            "name": account.name or "",
                            "balance": display_balance,
                        }
                    )
                    sub_dict["total"] += display_balance

                # ✅ only keep subheader if it has accounts after filtering
                sub_dict["total"] = round_usd(sub_dict["total"])
                if sub_dict["accounts"]:
                    header_dict["subheaders"].append(sub_dict)
                    header_dict["total"] += sub_dict["total"]

            header_dict["total"] = round_usd(header_dict["total"])
            if header_dict["subheaders"]:
                if header_type == "1":
                    assets_data.append(header_dict)
                    total_assets += header_dict["total"]
                elif header_type == "2":
                    liabilities_data.append(header_dict)
                    total_liabilities += header_dict["total"]
                elif header_type == "3":
                    equity_data.append(header_dict)
                    total_equity += header_dict["total"]

        # ✅ Profit from Income Statement
        net_profit = self._compute_income_statement_net_profit()
        net_profit = round_usd(net_profit)

        total_assets = round_usd(total_assets)
        total_liabilities = round_usd(total_liabilities)
        total_equity = round_usd(total_equity)

        # ✅ Standard equation
        total_liab_equity = round_usd(total_liabilities + total_equity + net_profit)
        fx_diff = round_usd(total_assets - total_liab_equity)

        if abs(fx_diff) >= USD_ROUND:
            # Add FX line inside Equity
            fx_header = {
                "name": "Foreign Exchange Revaluation",
                "code": "FX",
                "subheaders": [
                    {
                        "name": "Unrealized FX Gain/Loss",
                        "accounts": [
                            {
                                "code": "FX",
                                "name": "Foreign Exchange Gain/Loss (Unrealized)",
                                "balance": fx_diff,
                            }
                        ],
                        "total": fx_diff,
                    }
                ],
                "total": fx_diff,
            }

            equity_data.append(fx_header)
            total_equity = round_usd(total_equity + fx_diff)

            # Recompute totals
            total_liab_equity = round_usd(total_liabilities + total_equity + net_profit)

        return {
            "assets": assets_data,
            "liabilities": liabilities_data,
            "equity": equity_data,
            "total_assets": total_assets,
            "total_liabilities": total_liabilities,
            "total_equity": total_equity,
            "net_profit": net_profit,
            "total_liab_equity": total_liab_equity,
            "is_balanced": abs(total_assets - total_liab_equity) < 0.01,
        }

    # def _compute_balance_sheet_data(self):
    #     """Compute balance sheet structure + real Net Profit from Income Statement (4/5)"""
    #     Header = self.env["idil.chart.account.header"]
    #     SubHeader = self.env["idil.chart.account.subheader"]
    #     Account = self.env["idil.chart.account"]

    #     assets_data = []
    #     liabilities_data = []
    #     equity_data = []

    #     total_assets = 0.0
    #     total_liabilities = 0.0
    #     total_equity = 0.0

    #     headers = Header.search([], order="code")

    #     for header in headers:
    #         if not header.code or header.code[0] not in ["1", "2", "3"]:
    #             continue

    #         header_type = header.code[0]  # '1' assets, '2' liabilities, '3' equity

    #         header_dict = {
    #             "name": header.name,
    #             "code": header.code,
    #             "subheaders": [],
    #             "total": 0.0,  # DISPLAY total (already sign-correct)
    #         }

    #         subheaders = SubHeader.search([("header_id", "=", header.id)], order="name")

    #         for subheader in subheaders:
    #             sub_dict = {
    #                 "name": subheader.name,
    #                 "accounts": [],
    #                 "total": 0.0,  # DISPLAY subtotal
    #             }

    #             accounts = Account.search(
    #                 [
    #                     ("subheader_id", "=", subheader.id),
    #                     ("company_id", "=", self.company_id.id),
    #                 ],
    #                 order="code",
    #             )

    #             for account in accounts:
    #                 # Filter out clearing accounts
    #                 if account.code in ["100994", "100998"]:
    #                     continue

    #                 dr_usd, cr_usd = account.get_dr_cr_balance_usd(
    #                     self.report_date, self.company_id.id
    #                 )

    #                 signed = (dr_usd or 0.0) - (cr_usd or 0.0)  # dr-cr

    #                 # ✅ Correct display by nature:
    #                 # Assets: dr-cr
    #                 # Liabilities/Equity: cr-dr => -(dr-cr)
    #                 if header_type in ("2", "3"):
    #                     display_balance = -signed
    #                 else:
    #                     display_balance = signed

    #                 if abs(display_balance) > 0.001:
    #                     sub_dict["accounts"].append(
    #                         {
    #                             "code": account.code or "",
    #                             "name": account.name or "",
    #                             "balance": display_balance,  # <-- keep sign!
    #                         }
    #                     )
    #                     sub_dict["total"] += display_balance

    #             if sub_dict["accounts"]:
    #                 header_dict["subheaders"].append(sub_dict)
    #                 header_dict["total"] += sub_dict["total"]

    #         if header_dict["subheaders"]:
    #             if header_type == "1":
    #                 assets_data.append(header_dict)
    #                 total_assets += header_dict["total"]
    #             elif header_type == "2":
    #                 liabilities_data.append(header_dict)
    #                 total_liabilities += header_dict["total"]
    #             elif header_type == "3":
    #                 equity_data.append(header_dict)
    #                 total_equity += header_dict["total"]

    #     # ✅ Profit from Income Statement (headers 4/5) (profit positive, loss negative)
    #     net_profit = self._compute_income_statement_net_profit()

    #     # ✅ Standard BS:
    #     # Assets should equal Liabilities + Equity + Current Profit
    #     total_liab_equity = total_liabilities + total_equity + net_profit

    #     return {
    #         "assets": assets_data,
    #         "liabilities": liabilities_data,
    #         "equity": equity_data,
    #         "total_assets": total_assets,
    #         "total_liabilities": total_liabilities,
    #         "total_equity": total_equity,
    #         "net_profit": net_profit,
    #         "total_liab_equity": total_liab_equity,
    #         "is_balanced": abs(total_assets - total_liab_equity) < 0.01,
    #     }

    def _compute_income_statement_net_profit(self):
        """
        Compute Net Profit/Loss from Income Statement:
        - header code startswith '4' => Income/Revenue
        - header code startswith '5' => Expense

        Uses: account.get_dr_cr_balance_usd(report_date, company_id)
        Convention:
        signed_balance = dr - cr

        Revenue is typically credit => signed negative
        Expense is typically debit => signed positive

        Return:
        net_profit > 0 => profit
        net_profit < 0 => loss
        """
        Header = self.env["idil.chart.account.header"]
        SubHeader = self.env["idil.chart.account.subheader"]
        Account = self.env["idil.chart.account"]

        report_date = self.report_date
        company_id = self.company_id.id

        income_signed_total = 0.0
        expense_signed_total = 0.0

        headers = Header.search([], order="code")
        for header in headers:
            if not header.code:
                continue

            first = header.code[0]
            if first not in ("4", "5"):
                continue

            subheaders = SubHeader.search([("header_id", "=", header.id)], order="name")
            for subheader in subheaders:
                accounts = Account.search(
                    [
                        ("subheader_id", "=", subheader.id),
                        ("company_id", "=", company_id),
                    ],
                    order="code",
                )

                for account in accounts:
                    # skip clearing if you don't want them in reports
                    if account.code in ["100994", "100998"]:
                        continue

                    dr_usd, cr_usd = account.get_dr_cr_balance_usd(
                        report_date, company_id
                    )
                    signed = (dr_usd or 0.0) - (cr_usd or 0.0)

                    if first == "4":
                        income_signed_total += signed
                    else:
                        expense_signed_total += signed

        # Convert to normal profit:
        # profit = income - expense
        # with signed totals (dr-cr): income is negative, expense positive
        # so profit = (-income_signed_total) - (expense_signed_total)
        net_profit = (-income_signed_total) - (expense_signed_total)

        return net_profit


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
