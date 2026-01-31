from odoo import models, fields, api, _

from odoo.exceptions import ValidationError, UserError
import logging

_logger = logging.getLogger(__name__)


class AccountHeader(models.Model):
    _name = "idil.chart.account.header"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _description = "Idil Chart of Accounts Header"

    company_id = fields.Many2one(
        "res.company", default=lambda s: s.env.company, required=True
    )
    code = fields.Char(string="Header Code", required=True)
    name = fields.Char(string="Header Name", required=True)

    sub_header_ids = fields.One2many(
        "idil.chart.account.subheader", "header_id", string="Sub Headers"
    )

    _sql_constraints = [
        # Unique per company
        (
            "uniq_header_code_company",
            "unique(company_id, code)",
            "Header Code must be unique per company.",
        ),
        (
            "uniq_header_name_company",
            "unique(company_id, name)",
            "Header Name must be unique per company.",
        ),
    ]

    @api.constrains("code", "name", "company_id")
    def _check_header_uniqueness_verbose(self):
        for rec in self:
            if not rec.company_id:
                continue
            # code
            if rec.code:
                other = self.search(
                    [
                        ("id", "!=", rec.id),
                        ("company_id", "=", rec.company_id.id),
                        ("code", "=", rec.code),
                    ],
                    limit=1,
                )
                if other:
                    raise ValidationError(
                        f"Duplicate Header Code in company '{rec.company_id.name}'.\n"
                        f"Your record: Code='{rec.code}', Name='{rec.name}'.\n"
                        f"Existing: Code='{other.code}', Name='{other.name}' (ID {other.id})."
                    )
            # name
            if rec.name:
                other = self.search(
                    [
                        ("id", "!=", rec.id),
                        ("company_id", "=", rec.company_id.id),
                        ("name", "=", rec.name),
                    ],
                    limit=1,
                )
                if other:
                    raise ValidationError(
                        f"Duplicate Header Name in company '{rec.company_id.name}'.\n"
                        f"Your record: Name='{rec.name}', Code='{rec.code}'.\n"
                        f"Existing: Name='{other.name}', Code='{other.code}' (ID {other.id})."
                    )

    @api.model
    def get_bs_report_data(self, company_id, report_date):
        # Retrieve all headers without filtering by company
        headers = self.search([])
        print(f"Number of headers found: {len(headers)}")

        for header in headers:
            print(
                f"Processing Header: {header.name} with {len(header.sub_header_ids)} sub-headers"
            )
            for subheader in header.sub_header_ids:
                print(
                    f"Processing Sub-header: {subheader.name} with {len(subheader.account_ids)} accounts"
                )
                for account in subheader.account_ids:
                    # Pass company_id to get balance only for the selected company
                    balance = account.get_balance_as_of_date_for_bs(
                        report_date, company_id
                    )
                    print(f"Account: {account.name}, Balance: {balance}")

        usd_currency = self.env.ref("base.USD")
        # Data structure for the template
        report_data = {
            "assets": {"headers": [], "total": 0},
            "liabilities": {"headers": [], "total": 0},
            "equity": {"headers": [], "total": 0},
            "net_profit_loss": 0,
            "is_balanced": False,
            "difference": 0,
            "currency_symbol": usd_currency.symbol,
        }

        total_pl_balance = 0

        for header in headers:
            header_total = 0
            # Identify category based on first digit
            first_digit = header.code[:1]
            category = None
            if first_digit == "1":
                category = "assets"
            elif first_digit == "2":
                category = "liabilities"
            elif first_digit == "3":
                category = "equity"

            # Note: 4, 5, 6 etc. are PL and don't get their own BS section,
            # but we iterate through all to compute Net Profit/Loss
            is_credit_nature = first_digit in ["2", "3", "4", "7", "9"]

            subheaders_data = []

            for subheader in header.sub_header_ids:
                subheader_total = 0
                accounts_data = []

                for account in subheader.account_ids:
                    # Point 1: Hide specific clearing accounts
                    if account.code in ["100998", "100994"]:
                        continue

                    balance = account.get_balance_as_of_date_for_bs(
                        report_date, company_id
                    )

                    # Accumulate for Net Profit/Loss (relying on PL flag)
                    if account.FinancialReporting == "PL":
                        total_pl_balance += balance

                    if account.FinancialReporting == "BS" and category:
                        # Skip zero balance accounts for the display
                        if abs(balance) < 0.001:
                            continue

                        # Flip sign for display if it's a Credit nature category
                        display_balance = -balance if is_credit_nature else balance

                        accounts_data.append(
                            {
                                "account_id": account.id,
                                "account_code": account.code,
                                "account_name": account.name,
                                "balance": "${:,.3f}".format(display_balance),
                            }
                        )
                        subheader_total += balance

                if accounts_data:
                    display_subheader_total = (
                        -subheader_total if is_credit_nature else subheader_total
                    )
                    subheaders_data.append(
                        {
                            "sub_header_name": subheader.name,
                            "accounts": accounts_data,
                            "sub_header_total": "${:,.3f}".format(
                                display_subheader_total
                            ),
                        }
                    )
                    header_total += subheader_total

            if subheaders_data and category:
                display_header_total = (
                    -header_total if is_credit_nature else header_total
                )
                report_data[category]["headers"].append(
                    {
                        "header_name": header.name,
                        "sub_headers": subheaders_data,
                        "header_total": "${:,.3f}".format(display_header_total),
                    }
                )
                report_data[category]["total"] += header_total

        # Net Profit/Loss (Current Year Earnings)
        # Reversing sign because Profit is a net Credit (negative in my net Dr-Cr calc)
        report_data["net_profit_loss"] = -total_pl_balance

        # Balance Check: Assets = Liabilities + Equity + Net Profit
        total_assets = report_data["assets"]["total"]
        total_liab_equity = (
            report_data["liabilities"]["total"]
            + report_data["equity"]["total"]
            - total_pl_balance
        )

        # We use Liabilities and Equity totals as positive values for comparison
        # (Liability and Equity totals in the dict are currently 'debit' sums, so they are likely negative)
        asset_sum = total_assets
        liab_sum = -report_data["liabilities"]["total"]
        equity_sum = -report_data["equity"]["total"]
        profit_sum = -total_pl_balance

        report_data["difference"] = asset_sum - (liab_sum + equity_sum + profit_sum)
        report_data["is_balanced"] = abs(report_data["difference"]) < 0.01

        # Format totals for display
        report_data["total_assets_formatted"] = "${:,.3f}".format(asset_sum)
        report_data["total_liabilities_formatted"] = "${:,.3f}".format(liab_sum)
        report_data["total_equity_formatted"] = "${:,.3f}".format(
            equity_sum + profit_sum
        )
        report_data["total_liab_equity_formatted"] = "${:,.3f}".format(
            liab_sum + equity_sum + profit_sum
        )
        report_data["net_profit_formatted"] = "${:,.3f}".format(profit_sum)

    @api.model
    def get_trial_balance_report_data(self, company_id, report_date):
        company = (
            self.env["res.company"].browse(company_id)
            if company_id
            else self.env.company
        )
        r_date = report_date or fields.Date.today()

        headers = self.search([])
        report_data = {
            "headers": [],
            "grand_total_debit": 0,
            "grand_total_credit": 0,
            "grand_total_balance": 0,
            "report_date": r_date,
            "company_name": company.name,
            "company_id": company.id,
        }

        total_dr = 0
        total_cr = 0

        for header in headers:
            header_dr = 0
            header_cr = 0
            subheaders_data = []

            for subheader in header.sub_header_ids:
                subheader_dr = 0
                subheader_cr = 0
                accounts_data = []

                for account in subheader.account_ids:
                    dr, cr = account.get_dr_cr_balance_usd(report_date, company_id)
                    # Skip zero balance accounts
                    if abs(dr) < 0.001 and abs(cr) < 0.001:
                        continue

                    net = dr - cr
                    accounts_data.append(
                        {
                            "code": account.code,
                            "name": account.name,
                            "debit": "${:,.3f}".format(dr),
                            "credit": "${:,.3f}".format(cr),
                            "balance": "${:,.3f}".format(net),
                        }
                    )
                    subheader_dr += dr
                    subheader_cr += cr

                if accounts_data:
                    subheaders_data.append(
                        {
                            "name": subheader.name,
                            "accounts": accounts_data,
                            "total_debit": "${:,.3f}".format(subheader_dr),
                            "total_credit": "${:,.3f}".format(subheader_cr),
                        }
                    )
                    header_dr += subheader_dr
                    header_cr += subheader_cr

            if subheaders_data:
                report_data["headers"].append(
                    {
                        "name": header.name,
                        "sub_headers": subheaders_data,
                        "total_debit": "${:,.3f}".format(header_dr),
                        "total_credit": "${:,.3f}".format(header_cr),
                    }
                )
                total_dr += header_dr
                total_cr += header_cr

        report_data["grand_total_debit"] = "${:,.3f}".format(total_dr)
        report_data["grand_total_credit"] = "${:,.3f}".format(total_cr)
        report_data["grand_total_balance"] = "${:,.3f}".format(total_dr - total_cr)

        return report_data

    @api.model
    def get_income_statement_advanced_data(self, company_id, report_date):
        company = (
            self.env["res.company"].browse(company_id)
            if company_id
            else self.env.company
        )
        r_date = report_date or fields.Date.today()
        headers = self.search([])

        report_data = {
            "revenue": {"headers": [], "total": 0},
            "cogs": {"headers": [], "total": 0},
            "expenses": {"headers": [], "total": 0},
            "other": {"headers": [], "total": 0},
            "net_profit": 0,
            "report_date": r_date,
            "company_name": company.name,
            "company_id": company.id,
        }

        for header in headers:
            first_digit = header.code[:1]
            category = None
            if first_digit == "4":
                category = "revenue"
            elif first_digit == "5":
                category = "cogs"
            elif first_digit == "6":
                category = "expenses"
            elif first_digit in ["7", "8", "9"]:
                category = "other"

            if not category:
                continue

            is_credit_nature = first_digit in ["4", "7", "9"]

            header_total = 0
            subheaders_data = []

            for subheader in header.sub_header_ids:
                subheader_total = 0
                accounts_data = []

                for account in subheader.account_ids:
                    dr, cr = account.get_dr_cr_balance_usd(r_date, company_id)
                    balance = dr - cr

                    if abs(balance) < 0.001:
                        continue

                    display_balance = -balance if is_credit_nature else balance

                    accounts_data.append(
                        {
                            "code": account.code,
                            "name": account.name,
                            "balance": "${:,.3f}".format(display_balance),
                        }
                    )
                    subheader_total += balance

                if accounts_data:
                    display_subheader_total = (
                        -subheader_total if is_credit_nature else subheader_total
                    )
                    subheaders_data.append(
                        {
                            "name": subheader.name,
                            "accounts": accounts_data,
                            "total": "${:,.3f}".format(display_subheader_total),
                        }
                    )
                    header_total += subheader_total

            if subheaders_data:
                display_header_total = (
                    -header_total if is_credit_nature else header_total
                )
                report_data[category]["headers"].append(
                    {
                        "name": header.name,
                        "sub_headers": subheaders_data,
                        "total": "${:,.3f}".format(display_header_total),
                    }
                )
                report_data[category]["total"] += header_total

        total_balance = (
            report_data["revenue"]["total"]
            + report_data["cogs"]["total"]
            + report_data["expenses"]["total"]
            + report_data["other"]["total"]
        )
        report_data["net_profit"] = -total_balance
        report_data["net_profit_formatted"] = "${:,.3f}".format(-total_balance)

        for cat in ["revenue", "cogs", "expenses", "other"]:
            if cat in ["revenue", "other"]:
                report_data[cat]["total_formatted"] = "${:,.3f}".format(
                    -report_data[cat]["total"]
                )
            else:
                report_data[cat]["total_formatted"] = "${:,.3f}".format(
                    report_data[cat]["total"]
                )

        return report_data

    @api.model
    def get_account_statement_advanced_data(
        self, account_id, start_date, end_date, company_id
    ):
        account = self.env["idil.chart.account"].browse(account_id)
        company = (
            self.env["res.company"].browse(company_id)
            if company_id
            else self.env.company
        )

        # Opening Balance computation in USD
        opening_transactions = self.env["idil.transaction_bookingline"].search(
            [
                ("account_number", "=", account.id),
                ("transaction_date", "<", start_date),
                ("company_id", "=", company.id),
            ]
        )

        opening_dr = 0
        opening_cr = 0
        for trx in opening_transactions:
            rate = (
                trx.rate
                or account._get_conversion_rate(
                    trx.currency_id.id, trx.transaction_date
                )
                or 1.0
            )
            if trx.currency_id.name == "USD":
                rate = 1.0
            opening_dr += trx.dr_amount / rate
            opening_cr += trx.cr_amount / rate

        opening_balance = opening_dr - opening_cr

        # Period Transactions
        transactions = self.env["idil.transaction_bookingline"].search(
            [
                ("account_number", "=", account.id),
                ("transaction_date", ">=", start_date),
                ("transaction_date", "<=", end_date),
                ("company_id", "=", company.id),
            ],
            order="transaction_date asc, id asc",
        )

        lines = []
        running_balance = opening_balance
        total_dr = 0
        total_cr = 0

        for trx in transactions:
            rate = (
                trx.rate
                or account._get_conversion_rate(
                    trx.currency_id.id, trx.transaction_date
                )
                or 1.0
            )
            if trx.currency_id.name == "USD":
                rate = 1.0

            dr_usd = trx.dr_amount / rate
            cr_usd = trx.cr_amount / rate
            running_balance += dr_usd - cr_usd

            total_dr += dr_usd
            total_cr += cr_usd

            lines.append(
                {
                    "date": trx.transaction_date,
                    "ref": (
                        trx.transaction_booking_id.transaction_number
                        if trx.transaction_booking_id
                        else ""
                    ),
                    "description": trx.description or "",
                    "debit": "${:,.3f}".format(dr_usd),
                    "credit": "${:,.3f}".format(cr_usd),
                    "balance": "${:,.3f}".format(running_balance),
                }
            )

        return {
            "account_name": account.name,
            "account_code": account.code,
            "currency": account.currency_id.name,
            "company_name": company.name,
            "company_id": company.id,
            "start_date": start_date,
            "end_date": end_date,
            "opening_balance": "${:,.3f}".format(opening_balance),
            "lines": lines,
            "total_debit": "${:,.3f}".format(total_dr),
            "total_credit": "${:,.3f}".format(total_cr),
            "closing_balance": "${:,.3f}".format(running_balance),
            "report_date": fields.Date.today(),
        }

    @api.model
    def get_cash_flow_advanced_data(self, company_id, start_date, end_date):
        company = (
            self.env["res.company"].browse(company_id)
            if company_id
            else self.env.company
        )
        usd_currency = self.env.ref("base.USD")

        # 1) Cash / Bank accounts
        cash_accounts = self.env["idil.chart.account"].search(
            [
                ("account_type", "in", ["cash", "bank_transfer"]),
                ("company_id", "=", company.id),
            ]
        )
        cash_account_ids = cash_accounts.ids

        # 2) Booking lines for cash accounts (date range)
        domain = [
            ("account_number", "in", cash_account_ids),
            ("transaction_date", ">=", start_date),
            ("transaction_date", "<=", end_date),
            ("company_id", "=", company.id),
        ]
        lines = self.env["idil.transaction_bookingline"].search(domain)

        categories = {
            "operating": {
                "inflows": {},
                "outflows": {},
                "total_in": 0.0,
                "total_out": 0.0,
            },
            "investing": {
                "inflows": {},
                "outflows": {},
                "total_in": 0.0,
                "total_out": 0.0,
            },
            "financing": {
                "inflows": {},
                "outflows": {},
                "total_in": 0.0,
                "total_out": 0.0,
            },
        }

        def to_usd(amount, line):
            """Convert line amount to USD if needed."""
            if not amount:
                return 0.0

            line_currency = line.currency_id or (
                line.account_number.currency_id if line.account_number else None
            )
            if not line_currency or line_currency.id == usd_currency.id:
                return amount

            booking = line.transaction_booking_id
            tx_rate = (
                booking.rate
                or self._get_conversion_rate(line_currency.id, line.transaction_date)
                or 1.0
            )

            # ASSUMPTION: tx_rate = (local per 1 USD) e.g. SL per USD
            return amount / tx_rate

        for line in lines:
            booking = line.transaction_booking_id
            if not booking:
                continue

            # Skip pure cash-to-cash internal transfers
            all_accounts = booking.booking_lines.mapped("account_number")
            if all(
                acc and acc.account_type in ["cash", "bank_transfer"]
                for acc in all_accounts
            ):
                continue

            raw_amount = (line.dr_amount or 0.0) - (line.cr_amount or 0.0)
            if abs(raw_amount) < 0.000001:
                continue

            amount_usd = to_usd(raw_amount, line)
            is_inflow = amount_usd > 0

            other_lines = booking.booking_lines.filtered(
                lambda bl: bl.account_number
                and bl.account_number.account_type not in ["cash", "bank_transfer"]
            )
            if not other_lines:
                continue

            def other_line_strength(bl):
                return abs((bl.dr_amount or 0.0) - (bl.cr_amount or 0.0))

            main_other = max(other_lines, key=other_line_strength)
            other_account = main_other.account_number

            cat = "operating"
            if other_account.FinancialReporting == "PL":
                cat = "operating"
            elif other_account.FinancialReporting == "BS":
                code = other_account.code or ""
                name = (other_account.name or "").lower()
                if code.startswith(("15", "16")) or any(
                    w in name for w in ["equipment", "machinery", "vehicle", "building"]
                ):
                    cat = "investing"
                elif code.startswith("3") or any(
                    w in name
                    for w in ["equity", "capital", "loan", "drawing", "dividend"]
                ):
                    cat = "financing"

            label = other_account.name or "Unclassified"
            amt = abs(amount_usd)

            if is_inflow:
                categories[cat]["inflows"][label] = (
                    categories[cat]["inflows"].get(label, 0.0) + amt
                )
                categories[cat]["total_in"] += amt
            else:
                categories[cat]["outflows"][label] = (
                    categories[cat]["outflows"].get(label, 0.0) + amt
                )
                categories[cat]["total_out"] += amt

        def pack_cat(slug):
            c = categories[slug]
            return {
                "inflows": [
                    {"name": k, "amount": "${:,.3f}".format(v)}
                    for k, v in c["inflows"].items()
                ],
                "outflows": [
                    {"name": k, "amount": "${:,.3f}".format(v)}
                    for k, v in c["outflows"].items()
                ],
                "total_in": "${:,.3f}".format(c["total_in"]),
                "total_out": "${:,.3f}".format(c["total_out"]),
                "net": "${:,.3f}".format(c["total_in"] - c["total_out"]),
                "net_raw": c["total_in"] - c["total_out"],
            }

        report_data = {
            "operating": pack_cat("operating"),
            "investing": pack_cat("investing"),
            "financing": pack_cat("financing"),
            "company_name": company.name,
            "company_id": company.id,
            "start_date": start_date,
            "end_date": end_date,
            "report_date": fields.Date.today(),
        }

        report_data["net_cash_flow"] = "${:,.3f}".format(
            report_data["operating"]["net_raw"]
            + report_data["investing"]["net_raw"]
            + report_data["financing"]["net_raw"]
        )

        # ==========================================================
        # ✅ ADD: Income Statement ordered block (no signature changes)
        # ==========================================================

        Header = self.env["idil.chart.account.header"]
        SubHeader = self.env["idil.chart.account.subheader"]
        Account = self.env["idil.chart.account"]

        # Use end_date as Income Statement "as of"
        is_report_date = end_date

        def acc_signed_usd(acc):
            dr, cr = acc.get_dr_cr_balance_usd(is_report_date, company.id)
            return (dr or 0.0) - (cr or 0.0)

        def build_pl_by_header(prefix, filter_func=None, mode="income"):
            """
            mode:
            - income: amount = -(dr-cr)
            - expense: amount = +(dr-cr)
            """
            out = []
            total = 0.0

            headers = Header.search([("code", "=like", f"{prefix}%")], order="code")
            for h in headers:
                h_dict = {
                    "code": h.code,
                    "name": h.name,
                    "subheaders": [],
                    "total": 0.0,
                }

                subs = SubHeader.search([("header_id", "=", h.id)], order="name")
                for s in subs:
                    s_dict = {"name": s.name, "accounts": [], "total": 0.0}

                    accs = Account.search(
                        [("subheader_id", "=", s.id), ("company_id", "=", company.id)],
                        order="code",
                    )

                    for acc in accs:
                        if filter_func and not filter_func(acc):
                            continue

                        signed = acc_signed_usd(acc)
                        amount = (-signed) if mode == "income" else signed

                        if abs(amount) > 0.001:
                            s_dict["accounts"].append(
                                {
                                    "code": acc.code or "",
                                    "name": acc.name or "",
                                    "amount": amount,
                                }
                            )
                            s_dict["total"] += amount

                    if s_dict["accounts"]:
                        h_dict["subheaders"].append(s_dict)
                        h_dict["total"] += s_dict["total"]

                if h_dict["subheaders"]:
                    out.append(h_dict)
                    total += h_dict["total"]

            return out, total

        # Income (4xxx)
        income_sections, total_income = build_pl_by_header(
            "4", filter_func=None, mode="income"
        )

        # COGS (5xxx where account_type == 'cogs')
        def only_cogs(acc):
            return getattr(acc, "account_type", None) == "cogs"

        cogs_sections, total_cogs = build_pl_by_header(
            "5", filter_func=only_cogs, mode="expense"
        )

        gross_profit = total_income - total_cogs

        # Other expenses (5xxx except cogs)
        def not_cogs(acc):
            return getattr(acc, "account_type", None) != "cogs"

        expense_sections, total_expenses = build_pl_by_header(
            "5", filter_func=not_cogs, mode="expense"
        )

        net_profit = gross_profit - total_expenses

        report_data["income_statement"] = {
            "income_sections": income_sections,
            "total_income": total_income,
            "cogs_sections": cogs_sections,
            "total_cogs": total_cogs,
            "gross_profit": gross_profit,
            "expense_sections": expense_sections,
            "total_expenses": total_expenses,
            "net_profit": net_profit,
        }

        return report_data

    # @api.model
    # def get_cash_flow_advanced_data(self, company_id, start_date, end_date):
    #     company = (
    #         self.env["res.company"].browse(company_id)
    #         if company_id
    #         else self.env.company
    #     )
    #     usd_currency = self.env.ref("base.USD")

    #     # 1) Cash / Bank accounts
    #     cash_accounts = self.env["idil.chart.account"].search(
    #         [
    #             ("account_type", "in", ["cash", "bank_transfer"]),
    #             ("company_id", "=", company.id),
    #         ]
    #     )
    #     cash_account_ids = cash_accounts.ids

    #     # 2) Booking lines for cash accounts (date range)
    #     domain = [
    #         ("account_number", "in", cash_account_ids),
    #         ("transaction_date", ">=", start_date),
    #         ("transaction_date", "<=", end_date),
    #         ("company_id", "=", company.id),
    #     ]
    #     lines = self.env["idil.transaction_bookingline"].search(domain)

    #     categories = {
    #         "operating": {
    #             "inflows": {},
    #             "outflows": {},
    #             "total_in": 0.0,
    #             "total_out": 0.0,
    #         },
    #         "investing": {
    #             "inflows": {},
    #             "outflows": {},
    #             "total_in": 0.0,
    #             "total_out": 0.0,
    #         },
    #         "financing": {
    #             "inflows": {},
    #             "outflows": {},
    #             "total_in": 0.0,
    #             "total_out": 0.0,
    #         },
    #     }

    #     def to_usd(amount, line):
    #         """Convert line amount to USD if needed."""
    #         if not amount:
    #             return 0.0

    #         line_currency = line.currency_id or (
    #             line.account_number.currency_id if line.account_number else None
    #         )
    #         if not line_currency or line_currency.id == usd_currency.id:
    #             return amount

    #         # rate priority: booking.rate then fallback conversion
    #         booking = line.transaction_booking_id
    #         tx_rate = (
    #             booking.rate
    #             or self._get_conversion_rate(line_currency.id, line.transaction_date)
    #             or 1.0
    #         )

    #         # ASSUMPTION: tx_rate = (local per 1 USD) e.g. SL per USD
    #         # local_amount / rate = USD
    #         return amount / tx_rate

    #     for line in lines:
    #         booking = line.transaction_booking_id
    #         if not booking:
    #             continue

    #         # Skip pure cash-to-cash internal transfers
    #         all_accounts = booking.booking_lines.mapped("account_number")
    #         if all(
    #             acc and acc.account_type in ["cash", "bank_transfer"]
    #             for acc in all_accounts
    #         ):
    #             continue

    #         # Amount on CASH line: dr - cr
    #         raw_amount = (line.dr_amount or 0.0) - (line.cr_amount or 0.0)
    #         if abs(raw_amount) < 0.000001:
    #             continue

    #         amount_usd = to_usd(raw_amount, line)

    #         # Determine inflow/outflow by sign
    #         is_inflow = amount_usd > 0

    #         # Find NON-cash booking lines and choose the main one (largest absolute movement)
    #         other_lines = booking.booking_lines.filtered(
    #             lambda bl: bl.account_number
    #             and bl.account_number.account_type not in ["cash", "bank_transfer"]
    #         )
    #         if not other_lines:
    #             continue

    #         # pick main other line by abs(dr-cr)
    #         def other_line_strength(bl):
    #             return abs((bl.dr_amount or 0.0) - (bl.cr_amount or 0.0))

    #         main_other = max(other_lines, key=other_line_strength)
    #         other_account = main_other.account_number

    #         # Classify category
    #         cat = "operating"
    #         if other_account.FinancialReporting == "PL":
    #             cat = "operating"
    #         elif other_account.FinancialReporting == "BS":
    #             code = other_account.code or ""
    #             name = (other_account.name or "").lower()
    #             if code.startswith(("15", "16")) or any(
    #                 w in name for w in ["equipment", "machinery", "vehicle", "building"]
    #             ):
    #                 cat = "investing"
    #             elif code.startswith("3") or any(
    #                 w in name
    #                 for w in ["equity", "capital", "loan", "drawing", "dividend"]
    #             ):
    #                 cat = "financing"

    #         # Accumulate
    #         label = other_account.name or "Unclassified"
    #         amt = abs(amount_usd)

    #         if is_inflow:
    #             categories[cat]["inflows"][label] = (
    #                 categories[cat]["inflows"].get(label, 0.0) + amt
    #             )
    #             categories[cat]["total_in"] += amt
    #         else:
    #             categories[cat]["outflows"][label] = (
    #                 categories[cat]["outflows"].get(label, 0.0) + amt
    #             )
    #             categories[cat]["total_out"] += amt

    #     def pack_cat(slug):
    #         c = categories[slug]
    #         return {
    #             "inflows": [
    #                 {"name": k, "amount": "${:,.3f}".format(v)}
    #                 for k, v in c["inflows"].items()
    #             ],
    #             "outflows": [
    #                 {"name": k, "amount": "${:,.3f}".format(v)}
    #                 for k, v in c["outflows"].items()
    #             ],
    #             "total_in": "${:,.3f}".format(c["total_in"]),
    #             "total_out": "${:,.3f}".format(c["total_out"]),
    #             "net": "${:,.3f}".format(c["total_in"] - c["total_out"]),
    #             "net_raw": c["total_in"] - c["total_out"],
    #         }

    #     report_data = {
    #         "operating": pack_cat("operating"),
    #         "investing": pack_cat("investing"),
    #         "financing": pack_cat("financing"),
    #         "company_name": company.name,
    #         "company_id": company.id,
    #         "start_date": start_date,
    #         "end_date": end_date,
    #         "report_date": fields.Date.today(),
    #     }

    #     report_data["net_cash_flow"] = "${:,.3f}".format(
    #         report_data["operating"]["net_raw"]
    #         + report_data["investing"]["net_raw"]
    #         + report_data["financing"]["net_raw"]
    #     )

    #     return report_data

    # @api.model
    # def get_cash_flow_advanced_data(self, company_id, start_date, end_date):
    #     company = self.env['res.company'].browse(company_id) if company_id else self.env.company
    #     usd_currency = self.env.ref("base.USD")

    #     # 1. Get Cash Accounts
    #     cash_accounts = self.env['idil.chart.account'].search([
    #         ('account_type', 'in', ['cash', 'bank_transfer']),
    #         ('company_id', '=', company.id)
    #     ])
    #     cash_account_ids = cash_accounts.ids

    #     # 2. Fetch Transactions for Cash Accounts
    #     domain = [
    #         ('account_number', 'in', cash_account_ids),
    #         ('transaction_date', '>=', start_date),
    #         ('transaction_date', '<=', end_date),
    #         ('company_id', '=', company.id)
    #     ]
    #     lines = self.env['idil.transaction_bookingline'].search(domain)

    #     # 3. Categorize
    #     categories = {
    #         'operating': {'inflows': {}, 'outflows': {}, 'total_in': 0, 'total_out': 0},
    #         'investing': {'inflows': {}, 'outflows': {}, 'total_in': 0, 'total_out': 0},
    #         'financing': {'inflows': {}, 'outflows': {}, 'total_in': 0, 'total_out': 0},
    #     }

    #     for line in lines:
    #         booking = line.transaction_booking_id
    #         all_accounts = booking.booking_lines.mapped('account_number')

    #         # Skip internal transfers
    #         if all(acc.account_type in ['cash', 'bank_transfer'] for acc in all_accounts if acc):
    #             continue

    #         other_accounts = [acc for acc in all_accounts if acc and acc.account_type not in ['cash', 'bank_transfer']]
    #         if not other_accounts: continue
    #         other_account = other_accounts[0]

    #         amount_usd = 0.0
    #         if line.transaction_type == 'dr':
    #             amount_usd = line.dr_amount
    #         else:
    #             amount_usd = line.cr_amount

    #         if amount_usd == 0: continue

    #         # Currency Conversion
    #         account_currency = line.currency_id or line.account_number.currency_id
    #         if account_currency and account_currency.id != usd_currency.id:
    #             tx_rate = line.transaction_booking_id.rate or self._get_conversion_rate(account_currency.id, line.transaction_date) or 1.0
    #             amount_usd = amount_usd / tx_rate

    #         # Classify
    #         cat = 'operating'
    #         if other_account.FinancialReporting == 'PL':
    #             cat = 'operating'
    #         elif other_account.FinancialReporting == 'BS':
    #             code = other_account.code or ''
    #             name = (other_account.name or '').lower()
    #             if code.startswith('15') or code.startswith('16') or any(w in name for w in ['equipment', 'machinery', 'vehicle', 'building']):
    #                 cat = 'investing'
    #             elif code.startswith('3') or any(w in name for w in ['equity', 'capital', 'loan', 'drawing', 'dividend']):
    #                 cat = 'financing'

    #         target_dict = categories[cat]['inflows'] if line.transaction_type == 'dr' else categories[cat]['outflows']
    #         label = other_account.name
    #         target_dict[label] = target_dict.get(label, 0) + amount_usd
    #         if line.transaction_type == 'dr':
    #             categories[cat]['total_in'] += amount_usd
    #         else:
    #             categories[cat]['total_out'] += amount_usd

    #     # Format for output
    #     def pack_cat(slug):
    #         c = categories[slug]
    #         return {
    #             'inflows': [{'name': k, 'amount': "${:,.3f}".format(v)} for k, v in c['inflows'].items()],
    #             'outflows': [{'name': k, 'amount': "${:,.3f}".format(v)} for k, v in c['outflows'].items()],
    #             'total_in': "${:,.3f}".format(c['total_in']),
    #             'total_out': "${:,.3f}".format(c['total_out']),
    #             'net': "${:,.3f}".format(c['total_in'] - c['total_out']),
    #             'net_raw': c['total_in'] - c['total_out']
    #         }

    #     report_data = {
    #         'operating': pack_cat('operating'),
    #         'investing': pack_cat('investing'),
    #         'financing': pack_cat('financing'),
    #         'company_name': company.name,
    #         'company_id': company.id,
    #         'start_date': start_date,
    #         'end_date': end_date,
    #         'report_date': fields.Date.today(),
    #     }
    #     report_data['net_cash_flow'] = "${:,.3f}".format(report_data['operating']['net_raw'] + report_data['investing']['net_raw'] + report_data['financing']['net_raw'])

    #     return report_data


class AccountStatementAdvancedWizard(models.TransientModel):
    _name = "report.account.statement.advanced.wizard"
    _description = "Advanced Account Statement Wizard"

    company_id = fields.Many2one(
        "res.company",
        string="Company",
        required=True,
        default=lambda self: self.env.company,
    )
    account_id = fields.Many2one(
        "idil.chart.account",
        string="Account",
        required=True,
    )
    start_date = fields.Date(
        string="Start Date",
        required=True,
        default=lambda self: fields.Date.today().replace(day=1),
    )
    end_date = fields.Date(
        string="End Date",
        required=True,
        default=fields.Date.context_today,
    )

    def generate_report(self):
        self.ensure_one()
        docids = self.env["idil.chart.account.header"].search([], limit=1).ids
        data = {
            "account_id": self.account_id.id,
            "start_date": self.start_date,
            "end_date": self.end_date,
            "company_id": self.company_id.id,
        }
        return {
            "type": "ir.actions.report",
            "report_name": "idil.report_account_statement_advanced_template",
            "report_type": "qweb-html",
            "data": data,
            "docids": docids,
        }


class IncomeStatementAdvancedWizard(models.TransientModel):
    _name = "report.income.statement.advanced.wizard"
    _description = "Advanced Income Statement Wizard"

    company_id = fields.Many2one(
        "res.company",
        string="Company",
        required=True,
        default=lambda self: self.env.company,
    )
    report_date = fields.Date(
        string="Report Date",
        required=True,
        default=fields.Date.context_today,
    )

    def generate_report(self):
        self.ensure_one()
        docids = self.env["idil.chart.account.header"].search([], limit=1).ids
        data = {
            "report_date": self.report_date,
            "company_id": self.company_id.id,
        }
        return {
            "type": "ir.actions.report",
            "report_name": "idil.report_income_statement_advanced_template",
            "report_type": "qweb-html",
            "data": data,
            "docids": docids,
        }


class TrialBalanceAdvancedWizard(models.TransientModel):
    _name = "report.trial.balance.advanced.wizard"
    _description = "Advanced Trial Balance Wizard"

    company_id = fields.Many2one(
        "res.company",
        string="Company",
        required=True,
        default=lambda self: self.env.company,
    )
    report_date = fields.Date(
        string="Report Date",
        required=True,
        default=fields.Date.context_today,
    )

    def generate_report(self):
        self.ensure_one()
        # Ensure docs is not empty by passing some IDs
        docids = self.env["idil.chart.account.header"].search([], limit=1).ids
        data = {
            "report_date": self.report_date,
            "company_id": self.company_id.id,
        }
        return {
            "type": "ir.actions.report",
            "report_name": "idil.report_trial_balance_advanced_template",
            "report_type": "qweb-html",
            "data": data,
            "docids": docids,
        }


class CashFlowAdvancedWizard(models.TransientModel):
    _name = "report.cash.flow.advanced.wizard"
    _description = "Advanced Cash Flow Wizard"

    company_id = fields.Many2one(
        "res.company",
        string="Company",
        required=True,
        default=lambda self: self.env.company,
    )
    start_date = fields.Date(
        string="Start Date",
        required=True,
        default=lambda self: fields.Date.today().replace(day=1),
    )
    end_date = fields.Date(
        string="End Date",
        required=True,
        default=fields.Date.context_today,
    )

    def generate_report(self):
        self.ensure_one()
        docids = self.env["idil.chart.account.header"].search([], limit=1).ids
        data = {
            "start_date": self.start_date,
            "end_date": self.end_date,
            "company_id": self.company_id.id,
        }
        return {
            "type": "ir.actions.report",
            "report_name": "idil.report_cash_flow_advanced_template",
            "report_type": "qweb-html",
            "data": data,
            "docids": docids,
        }


class ReportCurrencyWizard(models.TransientModel):
    _name = "report.currency.wizard"
    _description = "Currency Selection Wizard for Reports"

    company_id = fields.Many2one(
        "res.company",
        string="Company",
        required=True,
        help="Select the company for the report.",
    )
    report_date = fields.Date(
        string="Report Date",
        required=True,
        default=fields.Date.context_today,
        help="Select the date for which the report is to be generated.",
    )

    def generate_report(self):
        self.ensure_one()
        data = {
            "report_name": "Balance Sheet for " + self.company_id.name,
            "report_date": self.report_date,  # Pass the selected date to the report
            "company_id": self.company_id.id,  # Pass the selected company to the report
        }
        context = dict(self.env.context, company_id=self.company_id.id)
        return {
            "type": "ir.actions.report",
            "report_name": "idil.report_bs_template",
            "report_type": "qweb-html",
            "context": context,
            "data": data,
        }


class IncomeReportCurrencyWizard(models.TransientModel):
    _name = "report.income.currency.wizard"
    _description = "Currency Selection Wizard for Income Reports"

    currency_id = fields.Many2one(
        "res.currency",
        string="Currency",
        required=True,
        help="Select the currency for the Income report.",
    )
    report_date = fields.Date(
        string="Report Date",
        required=True,
        default=fields.Date.context_today,
        help="Select the date for which the Income report is to be generated.",
    )

    def generate_income_report(self):
        self.ensure_one()
        data = {
            "currency_id": self.currency_id.id,
            "report_date": self.report_date,  # Pass the selected date to the report
        }
        context = dict(self.env.context, currency_id=self.currency_id.id)
        return {
            "type": "ir.actions.report",
            "report_name": "idil.report_income_statement_template",
            "report_type": "qweb-html",
            "context": context,
            "data": data,
        }


class AccountSubHeader(models.Model):
    _name = "idil.chart.account.subheader"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _description = "Idil Chart of Accounts Sub Header"
    _order = "id desc"

    company_id = fields.Many2one(
        "res.company", default=lambda s: s.env.company, required=True
    )
    sub_header_code = fields.Char(string="Sub Header Code", required=True)
    name = fields.Char(string="Sub Header Name", required=True)
    header_id = fields.Many2one("idil.chart.account.header", string="Header")
    account_ids = fields.One2many(
        "idil.chart.account", "subheader_id", string="Accounts"
    )

    _sql_constraints = [
        (
            "uniq_subheader_code_company",
            "unique(company_id, sub_header_code)",
            "Sub Header Code must be unique per company.",
        ),
        (
            "uniq_subheader_name_company",
            "unique(company_id, name)",
            "Sub Header Name must be unique per company.",
        ),
    ]

    @api.constrains("sub_header_code")
    def _check_subheader_code_length(self):
        for subheader in self:
            if len(subheader.sub_header_code) != 6:
                raise ValidationError("Sub Header Code must be 6 characters long.")

    @api.constrains("sub_header_code", "header_id")
    def _check_subheader_assignment(self):
        for subheader in self:
            header_code = subheader.header_id.code[:3]
            subheader_code = subheader.sub_header_code[:3]
            if not subheader_code.startswith(header_code):
                raise ValidationError(
                    "The first three digits of Sub Header Code must match the Header Code."
                )

    @api.constrains("sub_header_code", "name", "company_id")
    def _check_subheader_uniqueness_verbose(self):
        for rec in self:
            if not rec.company_id:
                continue
            # sub_header_code
            other = self.search(
                [
                    ("id", "!=", rec.id),
                    ("company_id", "=", rec.company_id.id),
                    ("sub_header_code", "=", rec.sub_header_code),
                ],
                limit=1,
            )
            if other:
                raise ValidationError(
                    f"Duplicate Sub Header Code in company '{rec.company_id.name}'.\n"
                    f"Your record: Code='{rec.sub_header_code}', Name='{rec.name}', Header='{rec.header_id.name}'.\n"
                    f"Existing: Code='{other.sub_header_code}', Name='{other.name}', Header='{other.header_id.name}' (ID {other.id})."
                )
            # name
            other = self.search(
                [
                    ("id", "!=", rec.id),
                    ("company_id", "=", rec.company_id.id),
                    ("name", "=", rec.name),
                ],
                limit=1,
            )
            if other:
                raise ValidationError(
                    f"Duplicate Sub Header Name in company '{rec.company_id.name}'.\n"
                    f"Your record: Name='{rec.name}', Code='{rec.sub_header_code}', Header='{rec.header_id.name}'.\n"
                    f"Existing: Name='{other.name}', Code='{other.sub_header_code}', Header='{other.header_id.name}' (ID {other.id})."
                )


class Account(models.Model):
    _name = "idil.chart.account"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _description = "Idil Chart of Accounts"

    company_id = fields.Many2one(
        "res.company", default=lambda s: s.env.company, required=True
    )
    SIGN_SELECTION = [
        ("Dr", "Dr"),
        ("Cr", "Cr"),
    ]

    FINANCIAL_REPORTING_SELECTION = [
        ("BS", "Balance Sheet"),
        ("PL", "Profit and Loss"),
    ]
    account_type = [
        ("cash", "Cash"),
        ("bank_transfer", "Bank"),
        ("payable", "Account Payable"),
        ("discount", "Account Discount"),
        ("commission", "Account Commission"),
        ("receivable", "Account Receivable"),
        ("COGS", "COGS"),
        ("kitchen", "kitchen"),
        ("Owners Equity", "Owners Equity"),
        ("Adjustment", "Adjustment"),
        ("sales_expense", "Sales Expense"),
    ]

    code = fields.Char(string="Account Code", required=True, tracking=True)
    name = fields.Char(string="Account Name", required=True, tracking=True)
    sign = fields.Selection(
        SIGN_SELECTION,
        string="Account Sign",
        compute="_compute_account_sign",
        store=True,
        tracking=True,
    )
    FinancialReporting = fields.Selection(
        FINANCIAL_REPORTING_SELECTION,
        string="Financial Reporting",
        compute="_compute_financial_reporting",
        store=True,
        tracking=True,
    )
    account_type = fields.Selection(
        account_type, string="Account Type", store=True, tracking=True
    )
    subheader_id = fields.Many2one(
        "idil.chart.account.subheader",
        string="Sub Header",
        required=True,
        tracking=True,
    )

    subheader_code = fields.Char(
        related="subheader_id.sub_header_code", string="Sub Header Code", readonly=True
    )
    subheader_name = fields.Char(
        related="subheader_id.name", string="Sub Header Name", readonly=True
    )
    header_code = fields.Char(
        related="subheader_id.header_id.code", string="Header Code", readonly=True
    )

    header_name = fields.Char(
        related="subheader_id.header_id.name",
        string="Header Name",
        readonly=True,
        store=True,
    )
    # Add currency field
    currency_id = fields.Many2one("res.currency", string="Currency", required=True)

    balance = fields.Float(
        string="Current Balance", compute="_compute_balance", store=True
    )

    transaction_bookingline_ids = fields.One2many(
        "idil.transaction_bookingline",
        "account_number",
        string="Transaction Booking Lines",
    )

    _sql_constraints = [
        # Code unique per company, regardless of currency
        (
            "uniq_account_code_company",
            "unique(company_id, code)",
            "Account Code must be unique per company.",
        ),
        # Name unique per company+currency
        (
            "uniq_account_name_company_currency",
            "unique(company_id, name, currency_id)",
            "Account Name must be unique per company and currency.",
        ),
    ]

    @api.constrains("code", "name", "company_id", "currency_id")
    def _check_account_uniqueness_verbose(self):
        for rec in self:
            if not rec.company_id:
                continue

            # --- CODE: unique per company (ignore currency) ---
            if rec.code:
                other_code = self.search(
                    [
                        ("id", "!=", rec.id),
                        ("company_id", "=", rec.company_id.id),
                        ("code", "=", rec.code),
                    ],
                    limit=1,
                )
                if other_code:
                    raise ValidationError(
                        _(
                            "Duplicate Account Code in company '%(company)s'.\n"
                            "Your record: Code='%(code)s', Name='%(name)s', Currency='%(curr)s'.\n"
                            "Existing: Code='%(ecode)s', Name='%(ename)s', Currency='%(ecurr)s' (ID %(eid)s)."
                        )
                        % {
                            "company": rec.company_id.name,
                            "code": rec.code,
                            "name": rec.name,
                            "curr": rec.currency_id.name,
                            "ecode": other_code.code,
                            "ename": other_code.name,
                            "ecurr": other_code.currency_id.name,
                            "eid": other_code.id,
                        }
                    )

            # --- NAME: unique per company+currency ---
            if rec.name and rec.currency_id:
                other_name = self.search(
                    [
                        ("id", "!=", rec.id),
                        ("company_id", "=", rec.company_id.id),
                        ("name", "=", rec.name),
                        ("currency_id", "=", rec.currency_id.id),
                    ],
                    limit=1,
                )
                if other_name:
                    raise ValidationError(
                        _(
                            "Duplicate Account Name for the same currency in company '%(company)s'.\n"
                            "Your record: Name='%(name)s', Currency='%(curr)s', Code='%(code)s'.\n"
                            "Existing: Name='%(ename)s', Currency='%(ecurr)s', Code='%(ecode)s' (ID %(eid)s)."
                        )
                        % {
                            "company": rec.company_id.name,
                            "name": rec.name,
                            "curr": rec.currency_id.name,
                            "code": rec.code,
                            "ename": other_name.name,
                            "ecurr": other_name.currency_id.name,
                            "ecode": other_name.code,
                            "eid": other_name.id,
                        }
                    )

    @api.depends(
        "transaction_bookingline_ids.dr_amount", "transaction_bookingline_ids.cr_amount"
    )
    def _compute_balance(self):
        for account in self:
            # Clear the balance before calculation
            account.balance = 0
            debit_sum = sum(
                account.transaction_bookingline_ids.filtered(
                    lambda l: l.transaction_type == "dr"
                ).mapped("dr_amount")
            )
            credit_sum = sum(
                account.transaction_bookingline_ids.filtered(
                    lambda l: l.transaction_type == "cr"
                ).mapped("cr_amount")
            )
            account.balance = debit_sum - credit_sum

    @api.model
    def read_group(
        self, domain, fields, groupby, offset=0, limit=None, orderby=False, lazy=True
    ):
        if "balance" in fields:
            fields.remove("balance")
        res = super(Account, self).read_group(
            domain, fields, groupby, offset, limit, orderby, lazy
        )
        if "balance" not in fields:
            fields.append("balance")
        if "balance" in fields:
            for line in res:
                if "__domain" in line:
                    accounts = self.search(line["__domain"])
                    # Ensure balances are computed
                    accounts._compute_balance()
                    balance = sum(account.balance for account in accounts)
                    line["balance"] = balance
        return res

    @api.model
    def read(self, fields=None, load="_classic_read"):
        res = super(Account, self).read(fields, load)
        for record in self:
            record._compute_balance()
        return res

    def name_get(self):
        result = []
        for record in self:
            name = f"{record.name} ({record.currency_id.name})"
            result.append((record.id, name))
        return result

    @api.depends("code")
    def _compute_account_sign(self):
        for account in self:
            if account.code:
                first_digit = account.code[0]
                # Determine sign based on the first digit of the account code
                if first_digit in ["1", "5", "6", "8"]:  # Dr accounts
                    account.sign = "Dr"
                elif first_digit in ["2", "3", "4", "7", "9"]:  # Cr accounts
                    account.sign = "Cr"
                else:
                    account.sign = False
            else:
                account.sign = False

    @api.depends("code")
    def _compute_financial_reporting(self):
        for account in self:
            if account.code:
                first_digit = account.code[0]
                # Determine financial reporting based on the first digit of the account code
                if first_digit in [
                    "1",
                    "2",
                    "3",
                ]:  # Assuming 1, 2, 3 represent BS, adjust as needed
                    account.FinancialReporting = "BS"
                elif first_digit in [
                    "4",
                    "5",
                    "6",
                    "7",
                    "8",
                    "9",
                ]:  # Assuming 4, 5 represent PL, adjust as needed
                    account.FinancialReporting = "PL"
                else:
                    account.FinancialReporting = False
            else:
                account.FinancialReporting = False

    def get_balance_as_of_date(self, date):
        self.ensure_one()  # Ensures this is called on a single record
        transactions = self.env["idil.transaction_bookingline"].search(
            [
                ("account_number", "=", self.id),
                (
                    "transaction_date",
                    "<=",
                    date,
                ),  # Filter transactions up to the specified date
            ]
        )
        debit = sum(
            transaction.dr_amount
            for transaction in transactions
            if transaction.transaction_type == "dr"
        )
        credit = sum(
            transaction.cr_amount
            for transaction in transactions
            if transaction.transaction_type == "cr"
        )
        return abs(debit - credit)

    @api.model
    def get_balance_as_of_date_for_bs(self, date, company_id):
        self.ensure_one()
        dr, cr = self.get_dr_cr_balance_usd(date, company_id)
        return dr - cr

    def get_dr_cr_balance_usd(self, date, company_id):
        self.ensure_one()
        # Fetch transactions for the specific account, date, and company
        transactions = self.env["idil.transaction_bookingline"].search(
            [
                ("account_number", "=", self.id),
                ("transaction_date", "<=", date),
                ("company_id", "=", company_id),
            ]
        )

        total_debit_usd = 0
        total_credit_usd = 0

        for transaction in transactions:
            if transaction.currency_id.name == "USD":
                rate = 1.0
            else:
                rate = transaction.rate or self._get_conversion_rate(
                    transaction.currency_id.id, transaction.transaction_date
                )

            if not rate or rate == 0:
                rate = 1.0

            total_debit_usd += transaction.dr_amount / rate
            total_credit_usd += transaction.cr_amount / rate

        return total_debit_usd, total_credit_usd

    @api.model
    def _get_conversion_rate(self, from_currency_id, date):
        # Get the currency models
        from_currency = self.env["res.currency"].browse(from_currency_id)
        to_currency = self.env.ref(
            "base.USD"
        )  # Assuming USD is the to_currency, adjust as needed

        # Ensure currencies are valid
        if not from_currency or not to_currency:
            raise UserError(_("Invalid currency provided"))

        # Get the currency rate model
        currency_rate = self.env["res.currency.rate"]

        # Search for the conversion rate
        # We should filter by 'currency_id' (the currency field) and not 'rate_currency_id'
        rate_record = currency_rate.search(
            [("currency_id", "=", from_currency.id), ("name", "<=", date)],
            limit=1,
            order="name desc",
        )

        if not rate_record:
            raise UserError(
                _("Conversion rate not found for %s to %s as of %s")
                % (from_currency.name, to_currency.name, date)
            )

        return rate_record.rate


class AccountBalanceReport(models.TransientModel):
    _name = "idil.account.balance.report"
    _description = "Account Balance Report"

    type = fields.Char(string="Type")
    subtype = fields.Char(string="subtype")
    account_name = fields.Char(string="Account Name")
    # account_code = fields.Char(string="Account Code")
    account_id = fields.Many2one("idil.chart.account", string="Account", store=True)
    balance = fields.Float(compute="_compute_balance", store=True)
    currency_id = fields.Many2one(
        "res.currency",
        string="Currency",
        related="account_id.currency_id",
        store=True,
        readonly=True,
    )

    @api.depends("account_id")
    def _compute_balance(self):
        for report in self:
            # Initialize balance to 0 for each report entry
            report.balance = 0
            # Find transactions related to this account_code
            transactions = self.env["idil.transaction_bookingline"].search(
                [("account_number", "=", report.account_id.id)]
            )
            debit = sum(
                transactions.filtered(lambda r: r.transaction_type == "dr").mapped(
                    "dr_amount"
                )
            )
            credit = sum(
                transactions.filtered(lambda r: r.transaction_type == "cr").mapped(
                    "cr_amount"
                )
            )
            # Calculate balance
            report.balance = abs(debit - credit)

    @api.model
    def generate_account_balances_report(self):
        self.search([]).unlink()  # Clear existing records to avoid stale data

        account_balances = self._get_account_balances()
        for balance in account_balances:
            self.create(
                {
                    "type": balance["type"],
                    "subtype": balance["subtype"],
                    "account_name": balance["account_name"],
                    "account_id": balance["account_id"],
                }
            )

        return {
            "type": "ir.actions.act_window",
            "name": "Account Balances",
            "view_mode": "tree",
            "res_model": "idil.account.balance.report",
            "domain": [
                ("balance", "<>", 0)
            ],  # Ensures only accounts with non-zero balances are shown
            "context": {"group_by": ["type", "subtype"]},
            "target": "new",
        }

    def _get_account_balances(self):
        account_balances = []
        accounts = self.env["idil.chart.account"].search([])

        for account in accounts:
            account_balances.append(
                {
                    "type": account.header_name,
                    "subtype": account.subheader_name,
                    "account_name": account.name,
                    "account_id": account.id,
                }
            )
        return account_balances
