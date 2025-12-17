from odoo import models, fields, api, exceptions
from odoo.exceptions import ValidationError
import logging
from odoo.tools.float_utils import float_compare


_logger = logging.getLogger(__name__)


class VendorTransaction(models.Model):
    _name = "idil.vendor_transaction"
    _description = "Vendor Transaction"
    _order = "id desc"

    order_number = fields.Char(string="Order Number")
    transaction_number = fields.Char(string="Transaction Number")
    transaction_date = fields.Date(
        string="Transaction Date", default=lambda self: fields.Date.today()
    )

    vendor_id = fields.Many2one(
        "idil.vendor.registration", string="Vendor", ondelete="restrict", required=True
    )
    vendor_name = fields.Char(
        related="vendor_id.name", string="Vendor Name", readonly=True
    )
    vendor_phone = fields.Char(
        related="vendor_id.phone", string="Vendor Phone", readonly=True
    )
    vendor_email = fields.Char(
        related="vendor_id.email", string="Vendor Email", readonly=True
    )

    amount = fields.Float(string="Transaction Amount", store=True)
    paid_amount = fields.Float(string="Paid Amount", store=True)
    remaining_amount = fields.Float(string="Due Amount", store=True)
    amount_paying = fields.Float(string="Amount Paying", store=True)

    payment_method = fields.Selection(
        [
            ("cash", "Cash"),
            ("ap", "A/P"),
            ("bank_transfer", "Bank Transfer"),
            ("other", "Other"),
            ("internal", "Internal"),
        ],
        string="Payment Method",
    )
    payment_status = fields.Selection(
        [("pending", "Pending"), ("paid", "Paid"), ("partial_paid", "Partial Paid")],
        string="Payment Status",
        help="Description or additional information about the payment status.",
    )

    reffno = fields.Char(string="Reference Number")

    currency_id = fields.Many2one(
        "res.currency",
        string="Currency",
        default=lambda self: self.env.company.currency_id,
    )

    cash_account_id = fields.Many2one(
        "idil.chart.account",
        string="Asset Account",
        help="Payment Account to be used for the vendor payment -- asset accounts.",
        domain="[('code', 'like', '1'), ('currency_id', '=', currency_id)]",
        # Domain to filter accounts starting with '1' and in USD
    )

    transaction_booking_id = fields.Many2one(
        "idil.transaction_booking", string="Transaction Booking", ondelete="cascade"
    )
    payment_ids = fields.One2many(
        "idil.vendor_payment", "vendor_transaction_id", string="Vendor Payments"
    )

    product_purchase_order_id = fields.Many2one(
        "idil.product.purchase.order",
        string="Product Purchase Order",
        ondelete="cascade",
    )

    def write(self, vals):
        for record in self:
            if "amount_paying" in vals:
                _logger.debug(f"Validating cash account for record {record.id}")
                cash_account_id = vals.get("cash_account_id", record.cash_account_id.id)
                if not cash_account_id:
                    raise exceptions.ValidationError(
                        "Please select a cash account before updating the paid amount."
                    )
                if not record._check_cash_account_balance(
                    cash_account_id, vals.get("amount_paying", 0)
                ):
                    raise exceptions.ValidationError(
                        "The cash account balance is not enough to cover the paid amount."
                    )

        res = super(VendorTransaction, self).write(vals)

        for record in self:
            if "amount_paying" in vals:
                payment_id = record._create_vendor_payment(vals["amount_paying"])
                record._update_booking_payment(vals["amount_paying"], payment_id)

        return res

    def _check_cash_account_balance(self, cash_account_id, paid_amount):

        _logger.debug(f"Checking cash account balance for record {self.id}")
        total_debit = sum(
            self.env["idil.transaction_bookingline"]
            .search(
                [
                    ("account_number", "=", cash_account_id),
                    ("transaction_type", "=", "dr"),
                ]
            )
            .mapped("dr_amount")
        )
        total_credit = sum(
            self.env["idil.transaction_bookingline"]
            .search(
                [
                    ("account_number", "=", cash_account_id),
                    ("transaction_type", "=", "cr"),
                ]
            )
            .mapped("cr_amount")
        )
        available_balance = total_debit - total_credit
        _logger.debug(
            f"Available balance: {available_balance}, Paid amount: {paid_amount}"
        )
        return available_balance >= paid_amount

    def _update_booking_payment(self, new_paid_amount, payment_id):
        # Use vendor's account payable for the debit transaction
        try:
            with self.env.cr.savepoint():
                account_payable = self.vendor_id.account_payable_id
                payable_currency = account_payable.currency_id
                cash_currency = self.cash_account_id.currency_id

                if self.transaction_booking_id:
                    previous_paid_amount = self.transaction_booking_id.amount_paid
                    updated_paid_amount = previous_paid_amount + new_paid_amount

                    self.transaction_booking_id.write(
                        {
                            "amount_paid": updated_paid_amount,
                            "remaining_amount": self.transaction_booking_id.amount
                            - updated_paid_amount,
                        }
                    )

                    # Check if currencies match
                    if payable_currency.id == cash_currency.id:
                        # Same currency - simple 2-line booking
                        # Create the debit line
                        self.env["idil.transaction_bookingline"].create(
                            {
                                "transaction_booking_id": self.transaction_booking_id.id,
                                "account_number": account_payable.id,
                                "transaction_type": "dr",
                                "dr_amount": new_paid_amount,
                                "cr_amount": 0,
                                "transaction_date": fields.Date.today(),
                                "vendor_payment_id": payment_id,
                            }
                        )

                        # Create the credit line
                        self.env["idil.transaction_bookingline"].create(
                            {
                                "transaction_booking_id": self.transaction_booking_id.id,
                                "account_number": self.cash_account_id.id,
                                "transaction_type": "cr",
                                "cr_amount": new_paid_amount,
                                "dr_amount": 0,
                                "transaction_date": fields.Date.today(),
                                "vendor_payment_id": payment_id,
                            }
                        )
                    else:
                        # Different currencies - use 4-line clearing account pattern
                        # Get exchange rate
                        rate = self.transaction_booking_id.rate
                        if not rate or rate <= 0:
                            raise ValidationError(
                                "Exchange rate is required for cross-currency payments."
                            )

                        # Calculate amounts in both currencies
                        amount_payable_currency = new_paid_amount  # Amount in vendor's payable currency

                        # Convert to cash currency
                        if payable_currency.name == "USD" and cash_currency.name == "SL":
                            amount_cash_currency = new_paid_amount * rate
                        elif payable_currency.name == "SL" and cash_currency.name == "USD":
                            amount_cash_currency = new_paid_amount / rate
                        else:
                            raise ValidationError(
                                f"Unhandled currency conversion from {payable_currency.name} to {cash_currency.name}"
                            )

                        # Get clearing accounts
                        source_clearing = self.env["idil.chart.account"].search(
                            [
                                ("name", "=", "Exchange Clearing Account"),
                                ("currency_id", "=", payable_currency.id),
                            ],
                            limit=1,
                        )
                        target_clearing = self.env["idil.chart.account"].search(
                            [
                                ("name", "=", "Exchange Clearing Account"),
                                ("currency_id", "=", cash_currency.id),
                            ],
                            limit=1,
                        )

                        if not source_clearing or not target_clearing:
                            raise ValidationError(
                                "Exchange Clearing Accounts are required for cross-currency payments."
                            )

                        # Line 1: DR Account Payable (payable currency)
                        self.env["idil.transaction_bookingline"].create(
                            {
                                "transaction_booking_id": self.transaction_booking_id.id,
                                "account_number": account_payable.id,
                                "transaction_type": "dr",
                                "dr_amount": amount_payable_currency,
                                "cr_amount": 0,
                                "transaction_date": fields.Date.today(),
                                "vendor_payment_id": payment_id,
                            }
                        )

                        # Line 2: CR Source Clearing (payable currency)
                        self.env["idil.transaction_bookingline"].create(
                            {
                                "transaction_booking_id": self.transaction_booking_id.id,
                                "account_number": source_clearing.id,
                                "transaction_type": "cr",
                                "dr_amount": 0,
                                "cr_amount": amount_payable_currency,
                                "transaction_date": fields.Date.today(),
                                "vendor_payment_id": payment_id,
                            }
                        )

                        # Line 3: DR Target Clearing (cash currency)
                        self.env["idil.transaction_bookingline"].create(
                            {
                                "transaction_booking_id": self.transaction_booking_id.id,
                                "account_number": target_clearing.id,
                                "transaction_type": "dr",
                                "dr_amount": amount_cash_currency,
                                "cr_amount": 0,
                                "transaction_date": fields.Date.today(),
                                "vendor_payment_id": payment_id,
                            }
                        )

                        # Line 4: CR Cash Account (cash currency)
                        self.env["idil.transaction_bookingline"].create(
                            {
                                "transaction_booking_id": self.transaction_booking_id.id,
                                "account_number": self.cash_account_id.id,
                                "transaction_type": "cr",
                                "dr_amount": 0,
                                "cr_amount": amount_cash_currency,
                                "transaction_date": fields.Date.today(),
                                "vendor_payment_id": payment_id,
                            }
                        )

                    # Recompute remaining amount after booking lines are created
                    existing_payments = sum(
                        self.env["idil.transaction_bookingline"]
                        .search(
                            [
                                (
                                    "transaction_booking_id",
                                    "=",
                                    self.transaction_booking_id.id,
                                ),
                                (
                                    "order_line",
                                    "=",
                                    None,
                                ),  # Check if order_line is null
                            ]
                        )
                        .mapped("dr_amount")
                    )
                    _logger.debug(
                        f"Existing payments: {existing_payments}, Paid amount: {self.paid_amount}, Amount: {self.amount_paying}"
                    )
                    # self.remaining_amount = self.amount - (existing_payments)
                    self.remaining_amount = (
                        self.transaction_booking_id.amount - updated_paid_amount
                    )

                    self.paid_amount = updated_paid_amount

                    if remaining_amount == 0:
                        self.transaction_booking_id.payment_status = "paid"
                        self.payment_status = "paid"
                    elif updated_paid_amount == 0:
                        self.transaction_booking_id.payment_status = "pending"
                        self.payment_status = "pending"
                    else:
                        self.transaction_booking_id.payment_status = "partial_paid"
                        self.payment_status = "partial_paid"
        except Exception as e:
            _logger.error(f"transaction failed: {str(e)}")
            raise ValidationError(f"Transaction failed: {str(e)}")

    def _create_vendor_payment(self, amount_paid):
        vendor_payment = self.env["idil.vendor_payment"].create(
            {
                "vendor_id": self.vendor_id.id,
                "vendor_transaction_id": self.id,
                "amount_paid": amount_paid,
            }
        )
        return vendor_payment.id

    def unlink(self):
        for record in self:
            if record.product_purchase_order_id:
                # Ensure the linked purchase order still exists
                purchase_order = self.env["idil.product.purchase.order"].browse(
                    record.product_purchase_order_id.id
                )
                if purchase_order.exists():
                    raise ValidationError(
                        f"You cannot delete this Vendor Transaction because it is still linked to a Product Purchase Order: '{purchase_order.name}'."
                    )
        return super(VendorTransaction, self).unlink()
