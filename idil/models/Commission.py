from odoo import models, fields, api
from datetime import datetime
from odoo.exceptions import ValidationError

from odoo.tools.float_utils import float_compare, float_round


class Commission(models.Model):
    _name = "idil.commission"
    _description = "Commission"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "id desc"

    company_id = fields.Many2one(
        "res.company", default=lambda s: s.env.company, required=True
    )
    name = fields.Char(
        string="Commission Reference",
        required=True,
        tracking=True,
        default="New",
        readonly=True,
    )
    # Currency fields
    currency_id = fields.Many2one(
        "res.currency",
        string="Currency",
        required=True,
        default=lambda self: self.env["res.currency"].search(
            [("name", "=", "SL")], limit=1
        ),
        readonly=True,
    )
    rate = fields.Float(
        string="Exchange Rate",
        store=True,
        readonly=True,
        tracking=True,
    )
    manufacturing_order_id = fields.Many2one(
        "idil.manufacturing.order",
        string="Manufacturing Order",
        ondelete="cascade",
        index=True,
        tracking=True,
    )

    employee_id = fields.Many2one(
        "idil.employee", string="Employee", required=True, readonly=True
    )
    commission_amount = fields.Float(
        string="Commission Amount", digits=(16, 5), required=True, readonly=True
    )
    commission_paid = fields.Float(
        string="Commission Paid",
        compute="_compute_commission_paid",
        store=True,
        readonly=True,
    )
    commission_remaining = fields.Float(
        string="Commission Remaining",
        compute="_compute_commission_remaining",
        store=True,
        readonly=True,
    )

    cash_account_id = fields.Many2one(
        "idil.chart.account",
        string="Cash/Bank Account",
        domain=[("account_type", "in", ["cash", "bank_transfer"])],
        help="Select the cash or bank account for transactions.",
    )
    amount = fields.Float(
        string="Amount to Pay", digits=(16, 5), default=0.0, required=True
    )

    payment_status = fields.Selection(
        [("pending", "Pending"), ("partial_paid", "Partial Paid"), ("paid", "Paid")],
        string="Payment Status",
        compute="_compute_payment_status",
        store=True,
        help="Description or additional information about the payment status.",
    )
    date = fields.Date(
        string="Date", default=fields.Date.context_today, required=True, readonly=True
    )
    commission_payment_ids = fields.One2many(
        "idil.commission.payment",
        "commission_id",
        string="Commission Payments",
        readonly=True,
    )
    is_paid = fields.Boolean(string="Paid", default=False)

    # Payment Schedule Fields
    payment_schedule = fields.Selection(
        related="employee_id.commission_payment_schedule",
        store=True,
        string="Payment Schedule",
        readonly=True,
    )

    due_date = fields.Date(
        string="Due Date",
        compute="_compute_due_date",
        store=True,
        help="Date when commission becomes payable based on employee's payment schedule",
    )

    is_payable = fields.Boolean(
        string="Is Payable",
        compute="_compute_is_payable",
        search="_search_is_payable",
        help="True if commission is due for payment today or earlier",
    )

    @api.depends(
        "date",
        "employee_id.commission_payment_schedule",
        "employee_id.commission_payment_day",
    )
    def _compute_due_date(self):
        """Calculate due date based on employee's payment schedule"""
        for commission in self:
            if not commission.employee_id or not commission.date:
                commission.due_date = commission.date
                continue

            if commission.employee_id.commission_payment_schedule == "daily":
                # Due same day as transaction
                commission.due_date = commission.date
            else:  # monthly
                # Due on specified day of next applicable month
                from datetime import date as dt_date
                from dateutil.relativedelta import relativedelta

                transaction_date = fields.Date.from_string(commission.date)
                payment_day = commission.employee_id.commission_payment_day or 1

                # Ensure payment day is valid (1-31)
                payment_day = max(1, min(31, payment_day))

                # Calculate next payment date
                if transaction_date.day < payment_day:
                    # Payment is in the same month
                    try:
                        due_date = transaction_date.replace(day=payment_day)
                    except ValueError:
                        # Handle months with fewer days (e.g., Feb 30)
                        due_date = transaction_date.replace(day=1) + relativedelta(
                            months=1, days=-1
                        )
                else:
                    # Payment is in the next month
                    try:
                        next_month = transaction_date + relativedelta(months=1)
                        due_date = next_month.replace(day=payment_day)
                    except ValueError:
                        # Handle months with fewer days
                        next_month = transaction_date + relativedelta(months=1)
                        due_date = next_month.replace(day=1) + relativedelta(
                            months=1, days=-1
                        )

                commission.due_date = due_date

    @api.depends("due_date", "payment_status")
    def _compute_is_payable(self):
        """Check if commission is due for payment"""
        today = fields.Date.today()
        for commission in self:
            commission.is_payable = (
                commission.payment_status in ["pending", "partial_paid"]
                and commission.due_date
                and commission.due_date <= today
            )

    def _search_is_payable(self, operator, value):
        """Allow searching for payable commissions"""
        today = fields.Date.today()
        if operator == "=" and value:
            return [
                ("payment_status", "in", ["pending", "partial_paid"]),
                ("due_date", "<=", today),
            ]
        else:
            return [
                "|",
                ("payment_status", "=", "paid"),
                ("due_date", ">", today),
            ]

    def pay_commission(self):
        if self.is_paid:
            raise ValidationError("This commission has already been paid.")

        if not self.cash_account_id:
            raise ValidationError(
                "Please select a cash account before paying the commission."
            )

        # Validate account currency consistency
        employee_currency = self.employee_id.account_id.currency_id
        cash_currency = self.cash_account_id.currency_id

        if employee_currency.id != cash_currency.id:
            raise ValidationError(
                "Commission account and cash account must have the same currency to proceed with the transaction."
            )

        precision = self.currency_id.decimal_places or 2
        bal = float_round(
            self._get_cash_account_balance() or 0.0, precision_digits=precision
        )
        amt = float_round(self.amount or 0.0, precision_digits=precision)

        if float_compare(amt, bal, precision_digits=precision) > 0:
            raise ValidationError(_("No sufficient amount in the cash account."))

        precision = self.currency_id.decimal_places or 2

        remaining = float_round(
            self.commission_remaining or 0.0, precision_digits=precision
        )
        amt = float_round(self.amount or 0.0, precision_digits=precision)

        # allow tiny float noise
        if float_compare(amt, remaining, precision_digits=precision) > 0:
            diff = amt - remaining
            raise ValidationError(
                _(
                    "The amount to pay exceeds the remaining commission amount.\n"
                    "Remaining Commission: %s\nAmount to Pay: %s\nDifference: %s"
                )
                % (remaining, amt, diff)
            )

        # optional: snap to exact remaining when very close
        if float_compare(amt, remaining, precision_digits=precision) == 0:
            self.amount = remaining

        payment_vals = {
            "commission_id": self.id,
            "employee_id": self.employee_id.id,
            "amount": self.amount,
            "date": fields.Date.context_today(self),
            "rate": self.rate,
        }
        payment = self.env["idil.commission.payment"].create(payment_vals)
        self.is_paid = True
        self._update_commission_status()
        # Create transaction booking lines for commission payment
        self._create_commission_payment_transaction_lines(payment)

    def _get_cash_account_balance(self):
        self.env.cr.execute(
            """
               SELECT COALESCE(SUM(dr_amount), 0) - COALESCE(SUM(cr_amount), 0)
               FROM idil_transaction_bookingline
               WHERE account_number = %s
           """,
            (self.cash_account_id.id,),
        )
        return self.env.cr.fetchone()[0]

    @api.depends("commission_payment_ids.amount")
    def _compute_commission_paid(self):
        for rec in self:
            precision = rec.currency_id.decimal_places or 2
            paid = sum(rec.commission_payment_ids.mapped("amount")) or 0.0
            paid = float_round(paid, precision_digits=precision)
            if abs(paid) < 10 ** (-(precision + 1)):
                paid = 0.0
            rec.commission_paid = paid

    @api.depends("commission_amount", "commission_paid")
    def _compute_commission_remaining(self):
        for rec in self:
            precision = rec.currency_id.decimal_places or 2
            remaining = (rec.commission_amount or 0.0) - (rec.commission_paid or 0.0)
            remaining = float_round(remaining, precision_digits=precision)

            # snap tiny noise to 0
            if abs(remaining) < 10 ** (-(precision + 1)):
                remaining = 0.0

            rec.commission_remaining = remaining

    @api.depends("commission_amount", "commission_paid")
    def _compute_payment_status(self):
        for rec in self:
            precision = rec.currency_id.decimal_places or 2
            if (
                float_compare(
                    rec.commission_paid,
                    rec.commission_amount,
                    precision_digits=precision,
                )
                >= 0
            ):
                rec.payment_status = "paid"
                rec.is_paid = True
            elif (
                float_compare(rec.commission_paid, 0.0, precision_digits=precision) > 0
            ):
                rec.payment_status = "partial_paid"
                rec.is_paid = False
            else:
                rec.payment_status = "pending"
                rec.is_paid = False

    def _update_commission_status(self):
        self._compute_commission_paid()
        self._compute_commission_remaining()
        self._compute_payment_status()

    def _create_commission_payment_transaction_lines(self, payment):
        Booking = self.env["idil.transaction_booking"]
        BookingLine = self.env["idil.transaction_bookingline"]

        mo = self.manufacturing_order_id
        if not mo:
            raise ValidationError("Commission must be linked to a manufacturing order.")

        # 1) Create main booking (if not already created for this payment)
        booking = payment.booking_id
        if not booking:
            booking = Booking.create(
                {
                    "transaction_number": self.env["ir.sequence"].next_by_code(
                        "idil.transaction_booking"
                    ),
                    "reffno": self.name,  # or mo.name if you prefer
                    "rate": self.rate,
                    "manufacturing_order_id": mo.id,
                    "order_number": mo.name or self.name,
                    "amount": payment.amount,
                    "trx_date": payment.date or fields.Date.context_today(self),
                    "payment_status": "paid",
                }
            )
            payment.booking_id = booking.id

        # (Optional) if you want always to attach to MO booking instead, remove above and set booking = mo.transaction_booking_id

        # 2) Create booking lines using booking.id
        # NOTE: Your comments were swapped: this DR is employee account, CR is cash account.
        debit_line_vals = {
            "transaction_booking_id": booking.id,
            "sl_line": 1,
            "description": "Commission Payment - DR (Employee)",
            "product_id": mo.product_id.id if mo.product_id else False,
            "account_number": self.employee_id.account_id.id,
            "transaction_type": "dr",
            "dr_amount": payment.amount,
            "cr_amount": 0.0,
            "transaction_date": payment.date or fields.Date.today(),
            "commission_payment_id": payment.id,
        }
        BookingLine.create(debit_line_vals)

        credit_line_vals = {
            "transaction_booking_id": booking.id,
            "sl_line": 2,
            "description": "Commission Payment - CR (Cash/Bank)",
            "product_id": mo.product_id.id if mo.product_id else False,
            "account_number": self.cash_account_id.id,
            "transaction_type": "cr",
            "dr_amount": 0.0,
            "cr_amount": payment.amount,
            "transaction_date": payment.date or fields.Date.today(),
            "commission_payment_id": payment.id,
        }
        BookingLine.create(credit_line_vals)

    def unlink(self):
        for rec in self:
            # block ONLY if there are payments
            if rec.commission_payment_ids:
                raise ValidationError(
                    "You cannot delete this commission because it has payment(s)."
                )
        return super(Commission, self).unlink()


class CommissionPayment(models.Model):
    _name = "idil.commission.payment"
    _description = "Commission Payment"
    _order = "id desc"

    company_id = fields.Many2one(
        "res.company", default=lambda s: s.env.company, required=True
    )
    commission_id = fields.Many2one(
        "idil.commission", string="Commission", required=True
    )
    # Currency fields
    currency_id = fields.Many2one(
        "res.currency",
        string="Currency",
        required=True,
        default=lambda self: self.env["res.currency"].search(
            [("name", "=", "SL")], limit=1
        ),
        readonly=True,
    )
    employee_id = fields.Many2one("idil.employee", string="Employee", required=True)
    amount = fields.Float(string="Amount", digits=(16, 5), required=True)
    date = fields.Date(string="Date", default=fields.Date.context_today, required=True)
    booking_line_ids = fields.One2many(
        "idil.transaction_bookingline", "commission_payment_id", string="Booking Lines"
    )
    bulk_payment_line_id = fields.Many2one(
        "idil.commission.bulk.payment.line", string="Bulk Payment Line", readonly=True
    )

    rate = fields.Float(string="Rate", digits=(16, 5), required=True)
    booking_id = fields.Many2one(
        "idil.transaction_booking",
        string="Transaction Booking",
        readonly=True,
        ondelete="set null",
        index=True,
    )

    def unlink(self):
        for record in self:
            record._delete_commission_payment_transaction_lines()
        result = super(CommissionPayment, self).unlink()
        return result

    def _delete_commission_payment_transaction_lines(self):
        booking_lines = self.booking_line_ids
        if booking_lines:
            booking_lines.unlink()
        self.commission_id._update_commission_status()
