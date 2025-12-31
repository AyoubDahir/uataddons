from odoo.exceptions import ValidationError
from odoo import models, fields, api, _

import logging

_logger = logging.getLogger(__name__)


class Vendor(models.Model):
    _name = "idil.vendor.registration"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _description = "Vendor Registration"
    _sql_constraints = [
        ("unique_email", "UNIQUE(email)", "The email must be unique."),
        ("unique_phone", "UNIQUE(phone)", "The phone number must be unique."),
    ]

    # Basic Details
    name = fields.Char(string="Name", required=True, tracking=True)
    phone = fields.Char(string="Phone", required=True, tracking=True)
    email = fields.Char(string="Email", tracking=True)
    type = fields.Selection(
        [("company", "Company"), ("individual", "Individual")],
        string="Type",
        required=True,
        tracking=True,
    )

    # Supplier Details
    supplier_type = fields.Selection(
        [
            ("local", "Local Supplier"),
            ("international", "International Supplier"),
        ],
        string="Supplier Type",
        required=True,
        tracking=True,
    )

    status = fields.Boolean(string="Status", tracking=True)
    active = fields.Boolean(string="Active", default=True, tracking=True)
    image = fields.Binary(string="Image")
    currency_id = fields.Many2one(
        "res.currency",
        string="Currency",
        required=True,
        default=lambda self: self.env.company.currency_id,
    )

    # Accounting Section
    account_payable_id = fields.Many2one(
        "idil.chart.account",
        string="Account Payable",
        domain="[('account_type', '=', 'payable'), ('header_name', '=', 'Liabilities') ,('currency_id', '=', currency_id)]",
        help="This account will be used instead of the default one as the payable account for the current vendor",
        required=True,
    )

    account_receivable_id = fields.Many2one(
        "idil.chart.account",
        string="Account Receivable",
        domain=[
            ("account_type", "=", "receivable"),
            ("header_name", "=", "Assets"),
            ("currency_id", "=", currency_id),
        ],
        help="This account will be used instead of the default one as the receivable account for the current vendor",
    )
    financial_transactions = fields.One2many(
        "idil.transaction_booking",
        "vendor_id",
        string="Financial Transactions",
        help="Displays financial transactions related to this vendor.",
    )

    # Opening Balance
    opening_balance = fields.Float(
        string="Opening Balance",
        default=0.0,
        help="The initial balance for the vendor when they are registered.",
    )
    vendor_transaction_ids = fields.One2many(
        "idil.vendor_transaction", "vendor_id", string="Vendor Transactions"
    )

    total_due_amount = fields.Float(
        string="Total Due Amount",
        compute="_compute_total_due_amount",
        store=False,  # Change to True if you want it stored
    )
    # Evaluation
    evaluation_score = fields.Float(
        string="Evaluation Score",
        digits=(3, 2),
        tracking=True,
        help="Final vendor evaluation score (0–5).",
    )

    evaluation_state = fields.Selection(
        [
            ("pending", "Pending"),
            ("approved", "Approved"),
            ("blocked", "Blocked"),
        ],
        string="Evaluation Status",
        default="pending",
        tracking=True,
    )
    # Payment term
    payment_term = fields.Selection(
        [
            ("cash", "Cash"),
            ("7_days", "7 Days"),
            ("15_days", "15 Days"),
            ("30_days", "30 Days"),
            ("60_days", "60 Days"),
        ],
        string="Payment Term",
        tracking=True,
    )
    is_local_supplier = fields.Boolean(
        string="Local Procurement",
        default=False,
        tracking=True,
    )

    is_international_supplier = fields.Boolean(
        string="International Procurement",
        default=False,
        tracking=True,
    )

    default_shipping_port = fields.Char(
        string="Default Shipping Port",
        tracking=True,
    )

    incoterm = fields.Selection(
        [
            ("exw", "EXW"),
            ("fob", "FOB"),
            ("cif", "CIF"),
            ("dap", "DAP"),
        ],
        string="Incoterm",
        tracking=True,
    )

    vendor_status = fields.Selection(
        [
            ("active", "Active"),
            ("suspended", "Suspended"),
            ("blacklisted", "Blacklisted"),
        ],
        string="Vendor Status",
        default="active",
        tracking=True,
    )

    trade_license_no = fields.Char(string="Trade License No")
    tax_number = fields.Char(string="Tax Number")
    contract_document = fields.Binary(string="Contract Document")

    @api.onchange("supplier_type")
    def _onchange_supplier_type(self):
        self.is_local_supplier = self.supplier_type == "local"
        self.is_international_supplier = self.supplier_type == "international"

    @api.constrains("evaluation_score")
    def _check_evaluation_score(self):
        for v in self:
            if v.evaluation_score and v.evaluation_score <= 2.5:
                v.evaluation_state = "blocked"

    @api.onchange("currency_id")
    def _onchange_currency_id(self):
        # Clear selected accounts
        self.account_payable_id = False
        self.account_receivable_id = False

    @api.depends("vendor_transaction_ids.remaining_amount")
    def _compute_total_due_amount(self):
        for vendor in self:
            vendor.total_due_amount = sum(
                vendor.vendor_transaction_ids.mapped("remaining_amount")
            )

    @api.model
    def create(self, vals):
        vendor = super(Vendor, self).create(vals)

        return vendor

    def write(self, vals):
        res = super(Vendor, self).write(vals)

        return res

    @api.constrains("phone")
    def _check_phone(self):
        for record in self:
            if not record.phone.isdigit() or len(record.phone) < 10:
                raise ValidationError(
                    "Phone number must be at least 10 digits and contain only numbers."
                )

    # Method to set vendor as inactive
    def set_inactive(self):
        self.active = False

    # Method to set vendor as active
    def set_active(self):
        self.active = True


class VendorBalanceReport(models.TransientModel):
    _name = "idil.vendor.balance.report"
    _description = "Vendor Balance Report"

    vendor_id = fields.Many2one("idil.vendor.registration", string="Vendor Id")
    vendor_name = fields.Char(string="Vendor Name")
    vendor_tel = fields.Char(string="Vendor Phone number")
    account_id = fields.Many2one("idil.chart.account", string="Account", store=True)
    account_name = fields.Char(string="Account Name")
    account_code = fields.Char(string="Account Code")
    balance = fields.Float(
        string="Balance", store=True
    )  # Assuming you want to store and display this field

    @api.model
    def generate_vendor_balances_report(self):
        self.search([]).unlink()  # Clear existing records to avoid stale data
        account_balances = self._get_vendor_balances()
        for balance in account_balances:
            self.create(
                {
                    "vendor_id": balance["vendor_id"],
                    "vendor_name": balance["vendor_name"],
                    "vendor_tel": balance["vendor_tel"],
                    "account_id": balance["account_id"],
                    "account_name": balance["account_name"],
                    "account_code": balance["account_code"],
                    "balance": balance[
                        "balance"
                    ],  # Make sure to store the calculated balance here
                }
            )

        return {
            "type": "ir.actions.act_window",
            "name": "Vendor Balances",
            "view_mode": "tree",
            "res_model": "idil.vendor.balance.report",
            "domain": [
                ("balance", "<>", 0)
            ],  # Ensures only accounts with non-zero balances are shown
            "context": {"group_by": ["vendor_name"]},
            "target": "new",
        }

    def _get_vendor_balances(self):
        vendor_balances = []
        vendor_personnel = self.env["idil.vendor.registration"].search(
            [("active", "=", True)]
        )
        for vendor in vendor_personnel:
            # Initialize balance for each salesperson.
            booking_lines_balance = 0
            purchase_orders = self.env["idil.purchase_order"].search(
                [("vendor_id", "=", vendor.id)]
            )
            for order in purchase_orders:
                bookings = self.env["idil.transaction_booking"].search(
                    [("order_number", "=", order.id)]
                )
                for booking in bookings:
                    # Filter booking lines by account number equal to salesperson's receivable account.
                    booking_lines = self.env["idil.transaction_bookingline"].search(
                        [
                            ("transaction_booking_id", "=", booking.id),
                            ("account_number", "=", vendor.account_payable_id.id),
                        ]
                    )
                    # Calculate debit and credit sums for filtered booking lines.
                    debit = sum(
                        booking_lines.filtered(
                            lambda r: r.transaction_type == "dr"
                        ).mapped("dr_amount")
                    )
                    credit = sum(
                        booking_lines.filtered(
                            lambda r: r.transaction_type == "cr"
                        ).mapped("cr_amount")
                    )
                    booking_lines_balance += debit - credit

            # Debugging: Log the calculated balance for each salesperson.
            _logger.debug(
                f"Vendor Person: {vendor.name}, Balance: {booking_lines_balance}"
            )

            vendor_balances.append(
                {
                    "vendor_id": vendor.id,
                    "vendor_name": vendor.name,
                    "vendor_tel": vendor.phone,
                    "account_id": (
                        vendor.account_payable_id.id
                        if vendor.account_payable_id
                        else ""
                    ),
                    "account_name": (
                        vendor.account_payable_id.name
                        if vendor.account_payable_id
                        else False
                    ),
                    "account_code": (
                        vendor.account_payable_id.code
                        if vendor.account_payable_id
                        else ""
                    ),
                    "balance": booking_lines_balance,
                }
            )

        return vendor_balances


class VendorTransactionReport(models.TransientModel):
    _name = "idil.vendor.transaction.report"
    _description = "Vendor Transaction Report"

    date = fields.Date(string="Date")
    reference = fields.Char(string="Reference")
    vendor_name = fields.Char(string="Vendor Name")
    vendor_tel = fields.Char(string="Vendor Phone Number")
    invoice = fields.Char(string="Invoice")
    description = fields.Char(string="Description")
    account_name = fields.Char(string="Account Name")
    account_code = fields.Char(string="Account Code")
    account_id = fields.Many2one("idil.chart.account", string="Account")
    debit = fields.Float(string="Dr")
    credit = fields.Float(string="Cr")
    balance = fields.Float(string="Balance")

    @api.model
    def generate_vendor_transaction_report(self):
        self.search([]).unlink()  # Clear existing records
        vendors = self.env["idil.vendor.registration"].search([("active", "=", True)])

        for vendor in vendors:
            # Use account IDs for transaction searches
            account_ids = [
                vendor.account_payable_id.id,
                vendor.account_receivable_id.id,
            ]
            transactions = self.env["idil.transaction_bookingline"].search(
                [("account_number", "in", account_ids)],
                order="transaction_booking_id asc, id asc",
            )
            running_balance = 0

            for transaction in transactions:
                if transaction.transaction_type == "dr":
                    running_balance += transaction.dr_amount
                elif transaction.transaction_type == "cr":
                    running_balance -= transaction.cr_amount

                self.create(
                    {
                        "vendor_name": vendor.name,
                        "vendor_tel": vendor.phone,
                        "account_name": transaction.account_number.name,  # Directly using the related field
                        "account_id": transaction.account_number.id,  # Use account ID
                        "date": transaction.transaction_date,
                        "reference": vendor.phone,
                        "description": vendor.phone or "N/A",
                        "debit": (
                            transaction.dr_amount
                            if transaction.transaction_type == "dr"
                            else 0
                        ),
                        "credit": (
                            transaction.cr_amount
                            if transaction.transaction_type == "cr"
                            else 0
                        ),
                        "balance": abs(running_balance),  # Reflecting running balance
                    }
                )

        return {
            "type": "ir.actions.act_window",
            "name": "Vendor Transaction Report",
            "view_mode": "tree",
            "res_model": "idil.vendor.transaction.report",
            "domain": [],
            "context": {"group_by": ["vendor_name"]},
            "target": "new",
        }
