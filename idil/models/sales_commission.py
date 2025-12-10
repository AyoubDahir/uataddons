from odoo import models, fields, api
from odoo.exceptions import ValidationError
from datetime import date
from dateutil.relativedelta import relativedelta
import logging

_logger = logging.getLogger(__name__)


class SalesCommission(models.Model):
    _name = "idil.sales.commission"
    _description = "Sales Commission"
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

    # Links
    sale_order_id = fields.Many2one(
        "idil.sale.order",
        string="Sale Order",
        required=True,
        ondelete="cascade",
        index=True,
        tracking=True,
    )
    sales_person_id = fields.Many2one(
        "idil.sales.sales_personnel",
        string="Salesperson",
        required=True,
        readonly=True,
        tracking=True,
    )

    # Currency
    currency_id = fields.Many2one(
        "res.currency",
        string="Currency",
        required=True,
        readonly=True,
    )

    # Amounts
    commission_amount = fields.Float(
        string="Commission Amount",
        digits=(16, 5),
        required=True,
        readonly=True,
        tracking=True,
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

    # Dates
    date = fields.Date(
        string="Date",
        default=fields.Date.context_today,
        required=True,
        readonly=True,
        tracking=True,
    )

    # Payment Schedule Fields
    payment_schedule = fields.Selection(
        related="sales_person_id.commission_payment_schedule",
        store=False,
        string="Payment Schedule",
        readonly=True,
    )

    due_date = fields.Date(
        string="Due Date",
        compute="_compute_due_date",
        store=True,
        help="Date when commission becomes payable based on salesperson's payment schedule",
    )

    is_payable = fields.Boolean(
        string="Is Payable",
        compute="_compute_is_payable",
        search="_search_is_payable",
        help="True if commission is due for payment today or earlier",
    )

    # Payment Status
    payment_status = fields.Selection(
        [("pending", "Pending"), ("partial_paid", "Partial Paid"), ("paid", "Paid")],
        string="Payment Status",
        compute="_compute_payment_status",
        store=True,
        tracking=True,
    )

    # Payment tracking
    payment_ids = fields.One2many(
        "idil.sales.commission.payment",
        "commission_id",
        string="Commission Payments",
        readonly=True,
    )

    # Payment fields (for payment form)
    cash_account_id = fields.Many2one(
        "idil.chart.account",
        string="Cash/Bank Account",
        domain="[('account_type', 'in', ['cash', 'bank_transfer'])]",
        help="Select the cash or bank account for payment.",
    )
    amount_to_pay = fields.Float(
        string="Amount to Pay", digits=(16, 5), default=0.0
    )

    @api.depends("payment_ids.amount")
    def _compute_commission_paid(self):
        for commission in self:
            commission.commission_paid = sum(commission.payment_ids.mapped("amount"))

    @api.depends("commission_amount", "commission_paid")
    def _compute_commission_remaining(self):
        for commission in self:
            commission.commission_remaining = (
                commission.commission_amount - commission.commission_paid
            )

    @api.depends("payment_ids", "payment_ids.amount")
    def _compute_commission_paid(self):
        for commission in self:
            # Use search to ensure we get all payments, including newly created ones
            # This bypasses potential cache issues with the One2many field
            payments = self.env["idil.sales.commission.payment"].search([
                ("commission_id", "=", commission.id)
            ])
            commission.commission_paid = sum(payments.mapped("amount"))

    @api.depends("commission_amount", "commission_paid")
    def _compute_commission_remaining(self):
        for commission in self:
            commission.commission_remaining = (
                commission.commission_amount - commission.commission_paid
            )

    @api.depends("date", "sales_person_id.commission_payment_schedule",
                 "sales_person_id.commission_payment_day")
    def _compute_due_date(self):
        """Calculate due date based on salesperson's payment schedule"""
        for commission in self:
            if not commission.sales_person_id or not commission.date:
                commission.due_date = commission.date
                continue

            if commission.sales_person_id.commission_payment_schedule == "daily":
                # Due same day as transaction
                commission.due_date = commission.date
            else:  # monthly
                # Due on specified day of next applicable month
                transaction_date = fields.Date.from_string(commission.date)
                payment_day = commission.sales_person_id.commission_payment_day or 1

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

    @api.depends("commission_amount", "commission_paid")
    def _compute_payment_status(self):
        for record in self:
            if record.commission_paid >= record.commission_amount:
                record.payment_status = "paid"
            elif record.commission_paid > 0:
                record.payment_status = "partial_paid"
            else:
                record.payment_status = "pending"

    @api.model
    def create(self, vals):
        if vals.get("name", "New") == "New":
            vals["name"] = self.env["ir.sequence"].next_by_code(
                "idil.sales.commission"
            ) or "New"
        return super(SalesCommission, self).create(vals)

    def pay_commission(self):
        """Pay commission to salesperson"""
        self.ensure_one()

        if not self.cash_account_id:
            raise ValidationError(
                "Please select a cash account before paying the commission."
            )

        if self.amount_to_pay <= 0:
            raise ValidationError("Amount to pay must be greater than 0.")

        if self.amount_to_pay > self.commission_remaining:
            raise ValidationError(
                f"The amount to pay ({self.amount_to_pay}) exceeds the remaining "
                f"commission amount ({self.commission_remaining})."
            )

        # Validate commission payable account exists for monthly schedule
        if self.payment_schedule == 'monthly':
            if not self.sales_person_id.commission_payable_account_id:
                raise ValidationError(
                    f"Salesperson '{self.sales_person_id.name}' has monthly commission schedule "
                    "but no Commission Payable Account configured."
                )

        # Create payment record
        payment_vals = {
            "commission_id": self.id,
            "sales_person_id": self.sales_person_id.id,
            "amount": self.amount_to_pay,
            "date": fields.Date.context_today(self),
            "cash_account_id": self.cash_account_id.id,
        }
        payment = self.env["idil.sales.commission.payment"].create(payment_vals)

        # Book accounting entry for commission payment (monthly schedule only)
        # Daily schedule doesn't use Commission Payable, so no clearing entry needed
        if self.payment_schedule == 'monthly':
            trx_source = self.env["idil.transaction.source"].search(
                [("name", "=", "Commission Payment")], limit=1
            )
            if not trx_source:
                # Fallback to Receipt source if Commission Payment doesn't exist
                trx_source = self.env["idil.transaction.source"].search(
                    [("name", "=", "Receipt")], limit=1
                )
            
            # Create transaction booking
            booking = self.env["idil.transaction_booking"].create(
                {
                    "sales_person_id": self.sales_person_id.id,
                    "trx_source_id": trx_source.id if trx_source else False,
                    "trx_date": fields.Date.context_today(self),
                    "amount": self.amount_to_pay,
                    "payment_method": "cash",
                    "payment_status": "paid",
                    "reffno": f"Commission Payment - {self.name}",
                }
            )
            
            # DR Commission Payable (clear the liability)
            self.env["idil.transaction_bookingline"].create(
                {
                    "transaction_booking_id": booking.id,
                    "description": f"Commission Payment - {self.sale_order_id.name}",
                    "account_number": self.sales_person_id.commission_payable_account_id.id,
                    "transaction_type": "dr",
                    "dr_amount": self.amount_to_pay,
                    "cr_amount": 0,
                    "transaction_date": fields.Date.context_today(self),
                }
            )
            
            # CR Cash/Bank (record cash outflow)
            self.env["idil.transaction_bookingline"].create(
                {
                    "transaction_booking_id": booking.id,
                    "description": f"Commission Payment - {self.sale_order_id.name}",
                    "account_number": self.cash_account_id.id,
                    "transaction_type": "cr",
                    "dr_amount": 0,
                    "cr_amount": self.amount_to_pay,
                    "transaction_date": fields.Date.context_today(self),
                }
            )

        # Reset amount_to_pay
        self.amount_to_pay = 0.0

        return {"type": "ir.actions.client", "tag": "reload"}


class SalesCommissionPayment(models.Model):
    _name = "idil.sales.commission.payment"
    _description = "Sales Commission Payment"
    _order = "id desc"

    bulk_payment_line_id = fields.Many2one(
        "idil.sales.commission.bulk.payment.line",
        string="Bulk Payment Line",
        readonly=True,
    )

    company_id = fields.Many2one(
        "res.company", default=lambda s: s.env.company, required=True
    )
    commission_id = fields.Many2one(
        "idil.sales.commission", string="Commission", required=True, ondelete="cascade"
    )
    sales_person_id = fields.Many2one(
        "idil.sales.sales_personnel", string="Salesperson", required=True
    )
    currency_id = fields.Many2one(
        "res.currency",
        string="Currency",
        required=True,
        default=lambda self: self.env["res.currency"].search(
            [("name", "=", "SL")], limit=1
        ),
        readonly=True,
    )
    amount = fields.Float(string="Amount", digits=(16, 5), required=True)
    date = fields.Date(string="Date", default=fields.Date.context_today, required=True)
    cash_account_id = fields.Many2one(
        "idil.chart.account", string="Cash/Bank Account", required=True
    )

    def create(self, vals):
        payment = super(SalesCommissionPayment, self).create(vals)
        # Create salesperson transaction (In - reduces what they owe)
        payment._create_salesperson_transaction()
        
        # Invalidate cache to ensure the new payment is seen by the compute methods
        payment.commission_id.invalidate_recordset(['commission_paid', 'commission_remaining', 'payment_status'])
        
        # Trigger recomputation
        payment.commission_id._compute_commission_paid()
        payment.commission_id._compute_commission_remaining()
        payment.commission_id._compute_payment_status()
        
        return payment

    def _create_salesperson_transaction(self):
        """Post commission payment to salesperson account"""
        self.env["idil.salesperson.transaction"].create(
            {
                "sales_person_id": self.sales_person_id.id,
                "date": self.date,
                "transaction_type": "in",
                "amount": self.amount,
                "description": f"Commission Payment - {self.commission_id.sale_order_id.name}",
            }
        )

    def unlink(self):
        """Delete associated salesperson transaction when payment is deleted"""
        # Store commissions to update before deletion
        commissions = self.mapped('commission_id')
        
        for payment in self:
            # Find and delete the transaction
            transaction = self.env["idil.salesperson.transaction"].search(
                [
                    ("sales_person_id", "=", payment.sales_person_id.id),
                    ("date", "=", payment.date),
                    ("amount", "=", payment.amount),
                    ("transaction_type", "=", "in"),
                    (
                        "description",
                        "=",
                        f"Commission Payment - {payment.commission_id.sale_order_id.name}",
                    ),
                ],
                limit=1,
            )
            if transaction:
                transaction.unlink()

        res = super(SalesCommissionPayment, self).unlink()
        
        # Force recomputation after deletion
        for commission in commissions:
            commission.invalidate_recordset(['commission_paid', 'commission_remaining', 'payment_status'])
            commission._compute_commission_paid()
            commission._compute_commission_remaining()
            commission._compute_payment_status()
            
        return res
