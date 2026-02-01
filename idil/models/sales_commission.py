# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import ValidationError
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

    # Payment tracking
    payment_ids = fields.One2many(
        "idil.sales.commission.payment",
        "commission_id",
        string="Commission Payments",
        readonly=True,
    )

    commission_paid = fields.Float(
        string="Commission Paid",
        compute="_compute_paid_remaining_status",
        store=True,
        readonly=True,
    )
    commission_remaining = fields.Float(
        string="Commission Remaining",
        compute="_compute_paid_remaining_status",
        store=True,
        readonly=True,
    )

    payment_status = fields.Selection(
        [
            ("pending", "Pending"),
            ("partial_paid", "Partial Paid"),
            ("paid", "Paid"),
            ("cancelled", "Cancelled"),
            ("reallocated", "Reallocated"),
        ],
        compute="_compute_paid_remaining_status",
        store=True,
        tracking=True,
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

    state = fields.Selection(
        [("normal", "Normal"), ("cancelled_return", "Cancelled (Returned)")],
        default="normal",
        tracking=True,
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

    # Payment fields (for payment form)
    cash_account_id = fields.Many2one(
        "idil.chart.account",
        string="Cash/Bank Account",
        domain="[('account_type', 'in', ['cash', 'bank_transfer'])]",
        help="Select the cash or bank account for payment.",
    )
    amount_to_pay = fields.Float(string="Amount to Pay", digits=(16, 5), default=0.0)

    recovery_shifted = fields.Float(
        string="Recovery Shifted",
        digits=(16, 5),
        default=0.0,
        readonly=True,
        tracking=True,
        help="How much paid commission from this record has already been shifted to recovery bucket.",
    )

    balance_shifted = fields.Float(
        string="Balance Shifted",
        digits=(16, 5),
        default=0.0,
        readonly=True,
        tracking=True,
        help="How much from this commission has been shifted into salesperson balance (to prevent duplicates).",
    )
    balance_used = fields.Float(
        string="Balance Used",
        digits=(16, 5),
        default=0.0,
        readonly=True,
        tracking=True,
    )

    def consume_salesperson_balance(self):
        """
        Use salesperson.commission_balance to pay this commission (once).
        - Deduct from salesperson balance
        - Create an allocation payment (+) on THIS commission
        - Store how much was used in balance_used
        """
        self.ensure_one()

        sp = self.sales_person_id
        if not sp:
            return 0.0

        bal = float(sp.commission_balance or 0.0)
        if bal <= 0:
            return 0.0

        total = float(self.commission_amount or 0.0)

        # paid so far including allocations (safe for repeated calls)
        already_paid = (
            sum(self.payment_ids.mapped("amount")) if self.payment_ids else 0.0
        )

        need = total - already_paid
        if need <= 0:
            return 0.0

        take = min(bal, need)
        if take <= 0:
            return 0.0

        # ✅ deduct wallet so it can't be reused
        sp.commission_balance = bal - take

        # ✅ track on commission
        self.balance_used = float(self.balance_used or 0.0) + take

        # ✅ create allocation payment on this commission (IN)
        self.env["idil.sales.commission.payment"].create(
            {
                "commission_id": self.id,
                "sales_person_id": sp.id,
                "currency_id": self.currency_id.id,
                "amount": take,  # IN
                "is_allocation": True,
                "allocation_ref": f"BAL-IN-{self.sale_order_id.name}",
                "date": fields.Date.context_today(self),
            }
        )

        self.message_post(
            body=(
                f"✅ Commission balance used: {take:,.2f} {self.currency_id.name}. "
                f"Remaining balance: {sp.commission_balance:,.2f}."
            )
        )

        return take

    @api.depends(
        "payment_ids.amount", "payment_ids.is_allocation", "commission_amount", "state"
    )
    def _compute_paid_remaining_status(self):
        for rec in self:
            payments = rec.payment_ids
            eps = 0.00001

            paid_total = sum(payments.mapped("amount")) if payments else 0.0
            real_paid = (
                sum(payments.filtered(lambda p: not p.is_allocation).mapped("amount"))
                if payments
                else 0.0
            )
            alloc_out = (
                abs(
                    sum(
                        payments.filtered(
                            lambda p: p.is_allocation and (p.amount or 0.0) < 0
                        ).mapped("amount")
                    )
                )
                if payments
                else 0.0
            )

            total = float(rec.commission_amount or 0.0)

            # ===============================
            # Returned commissions
            # ===============================
            if rec.state == "cancelled_return":
                # Default: hide numbers once cancelled
                rec.commission_remaining = 0.0

                # If nothing paid at all => Cancelled (hide paid too)
                if abs(real_paid) <= eps:
                    rec.commission_paid = 0.0
                    rec.payment_status = "cancelled"
                    continue

                # If paid > commission => Overpaid (warning)
                if real_paid > total + eps:
                    # show only what is still sitting (not shifted) but keep remaining hidden
                    still_on_this = max(real_paid - alloc_out, 0.0)
                    rec.commission_paid = still_on_this
                    rec.payment_status = "reallocated"
                    continue

                # Fully shifted => Reallocated (hide paid)
                if alloc_out >= real_paid - eps:
                    rec.commission_paid = 0.0
                    rec.payment_status = "reallocated"
                    continue

                # Partially shifted => Partial Reallocated (show only leftover)
                if alloc_out > eps and alloc_out < real_paid - eps:
                    rec.commission_paid = max(real_paid - alloc_out, 0.0)
                    rec.payment_status = "partial_reallocated"
                    continue

                # Not shifted at all but has paid => Partial Paid (needs shift)
                rec.commission_paid = real_paid
                rec.payment_status = "partial_paid"
                continue

            # ===============================
            # Normal commissions
            # ===============================
            remaining = total - paid_total
            rec.commission_paid = paid_total
            rec.commission_remaining = remaining

            if remaining < -eps:
                rec.payment_status = "reallocated"
            elif total and paid_total >= total - eps:
                rec.payment_status = "paid"
            elif paid_total > eps:
                rec.payment_status = "partial_paid"
            else:
                rec.payment_status = "pending"

    @api.depends(
        "date",
        "sales_person_id.commission_payment_schedule",
        "sales_person_id.commission_payment_day",
    )
    def _compute_due_date(self):
        for rec in self:
            if not rec.sales_person_id or not rec.date:
                rec.due_date = rec.date
                continue

            if rec.sales_person_id.commission_payment_schedule == "daily":
                rec.due_date = rec.date
                continue

            # monthly schedule
            transaction_date = fields.Date.from_string(rec.date)
            payment_day = rec.sales_person_id.commission_payment_day or 1
            payment_day = max(1, min(31, payment_day))

            # decide month
            base = (
                transaction_date
                if transaction_date.day < payment_day
                else (transaction_date + relativedelta(months=1))
            )

            # set day, fallback to last day of month
            try:
                rec.due_date = base.replace(day=payment_day)
            except ValueError:
                rec.due_date = base.replace(day=1) + relativedelta(months=1, days=-1)

    @api.depends("due_date", "payment_status")
    def _compute_is_payable(self):
        today = fields.Date.context_today(self)
        for rec in self:
            rec.is_payable = (
                rec.payment_status in ("pending", "partial_paid")
                and rec.due_date
                and rec.due_date <= today
            )

    def _search_is_payable(self, operator, value):
        today = fields.Date.context_today(self)
        if operator == "=" and value:
            return [
                ("payment_status", "in", ["pending", "partial_paid"]),
                ("due_date", "<=", today),
            ]
        return [
            "|",
            ("payment_status", "=", "paid"),
            ("due_date", ">", today),
        ]

    # --------------------------
    # CREATE / ACTIONS (NO SQL)
    # --------------------------
    @api.model
    def create(self, vals):
        if vals.get("name", "New") == "New":
            vals["name"] = (
                self.env["ir.sequence"].next_by_code("idil.sales.commission") or "New"
            )
        return super().create(vals)

    def pay_commission(self):
        """Pay commission to salesperson (NO SQL)."""
        self.ensure_one()

        # daily schedule is not payable
        if self.payment_schedule == "daily":
            raise ValidationError(
                _(
                    "Daily schedule commissions are not payable. "
                    "The salesperson already received their commission at the time of sale (netted from receivables)."
                )
            )

        if self.payment_status == "paid" or (self.commission_remaining or 0.0) <= 0:
            raise ValidationError(_("This commission is already fully paid."))

        if not self.cash_account_id:
            raise ValidationError(
                _("Please select a cash/bank account before paying the commission.")
            )

        if self.amount_to_pay <= 0:
            raise ValidationError(_("Amount to pay must be greater than 0."))

        # avoid overpayment based on current computed remaining
        if self.amount_to_pay > (self.commission_remaining or 0.0):
            raise ValidationError(
                _(
                    "The amount to pay (%.2f) exceeds the remaining commission amount (%.2f)."
                )
                % (self.amount_to_pay, self.commission_remaining or 0.0)
            )

        # optional: round to 2 decimals if your accounting requires it
        payment_amount = round(self.amount_to_pay, 2)

        # monthly schedule requires payable account
        if not self.sales_person_id.commission_payable_account_id:
            raise ValidationError(
                _(
                    "Salesperson '%s' has monthly commission schedule but no Commission Payable Account configured."
                )
                % (self.sales_person_id.name,)
            )

        # create payment record (this will also validate again in payment.create())
        payment = self.env["idil.sales.commission.payment"].create(
            {
                "commission_id": self.id,
                "sales_person_id": self.sales_person_id.id,
                "currency_id": self.currency_id.id,
                "amount": payment_amount,
                "date": fields.Date.context_today(self),
                "cash_account_id": self.cash_account_id.id,
            }
        )

        # Accounting booking for monthly schedule (NO SQL)
        if self.payment_schedule == "monthly":
            trx_source = self.env["idil.transaction.source"].search(
                [("name", "=", "Commission Payment")], limit=1
            )
            if not trx_source:
                trx_source = self.env["idil.transaction.source"].search(
                    [("name", "=", "Receipt")], limit=1
                )

            rate = (
                self.sale_order_id.rate
                if self.sale_order_id and self.sale_order_id.rate
                else 1.0
            )

            booking = self.env["idil.transaction_booking"].create(
                {
                    "sales_person_id": self.sales_person_id.id,
                    "trx_source_id": trx_source.id if trx_source else False,
                    "trx_date": fields.Date.context_today(self),
                    "amount": payment_amount,
                    "payment_method": "commission_payment",
                    "payment_status": "paid",
                    "reffno": f"Commission Payment - {self.name}",
                    "rate": rate,
                    "sale_order_id": (
                        self.sale_order_id.id if self.sale_order_id else False
                    ),
                    # "company_id": self.company_id.id,
                    "currency_id": self.currency_id.id,
                }
            )

            payable_account = self.sales_person_id.commission_payable_account_id
            cash_account = self.cash_account_id

            # DR Commission Payable
            self.env["idil.transaction_bookingline"].create(
                {
                    "transaction_booking_id": booking.id,
                    "description": f"Commission Payment - {self.sale_order_id.name if self.sale_order_id else self.name}",
                    "account_number": payable_account.id,
                    "transaction_type": "dr",
                    "dr_amount": payment_amount,
                    "cr_amount": 0.0,
                    "transaction_date": fields.Date.context_today(self),
                    "company_id": self.company_id.id,
                    "currency_id": self.currency_id.id,
                }
            )

            # CR Cash/Bank
            self.env["idil.transaction_bookingline"].create(
                {
                    "transaction_booking_id": booking.id,
                    "description": f"Commission Payment - {self.sale_order_id.name if self.sale_order_id else self.name}",
                    "account_number": cash_account.id,
                    "transaction_type": "cr",
                    "dr_amount": 0.0,
                    "cr_amount": payment_amount,
                    "transaction_date": fields.Date.context_today(self),
                    "company_id": self.company_id.id,
                    "currency_id": self.currency_id.id,
                }
            )

            payment.write({"transaction_booking_id": booking.id})

        # reset input
        self.amount_to_pay = 0.0

        # bulk flow support
        if self.env.context.get("return_payment_record"):
            return payment

        return {"type": "ir.actions.client", "tag": "reload"}

    def _apply_previous_paid_commission_to_this(self):
        """
        Like receipt allocation:
        - Take paid commission from old cancelled_return commissions (same salesperson+currency)
        - Create negative payment on source commission
        - Create positive payment on this commission
        """
        self.ensure_one()

        Payment = self.env["idil.sales.commission.payment"]
        Comm = self.env["idil.sales.commission"]

        if (self.commission_remaining or 0.0) <= 0:
            return 0.0

        allocation_ref = f"COMM-ALLOC-{self.sale_order_id.name}"

        # Source = old returned commissions with paid > 0
        sources = Comm.search(
            [
                ("sales_person_id", "=", self.sales_person_id.id),
                ("currency_id", "=", self.currency_id.id),
                ("state", "=", "cancelled_return"),
                ("id", "!=", self.id),
            ],
            order="id asc",
        )

        left = float(self.commission_remaining or 0.0)
        applied = 0.0

        for src in sources:
            src_paid = float(src.commission_paid or 0.0)
            if src_paid <= 0:
                continue

            take = min(src_paid, left)
            if take <= 0:
                continue

            # 1) NEGATIVE payment on SOURCE (remove paid from source)
            Payment.create(
                {
                    "commission_id": src.id,
                    "sales_person_id": src.sales_person_id.id,
                    "currency_id": src.currency_id.id,
                    "amount": -take,
                    "date": fields.Date.context_today(self),
                    "cash_account_id": (
                        self.cash_account_id.id if self.cash_account_id else False
                    ),
                    "is_allocation": True,
                    "allocation_ref": allocation_ref,
                }
            )

            # 2) POSITIVE payment on TARGET (apply to this commission)
            Payment.create(
                {
                    "commission_id": self.id,
                    "sales_person_id": self.sales_person_id.id,
                    "currency_id": self.currency_id.id,
                    "amount": take,
                    "date": fields.Date.context_today(self),
                    "cash_account_id": (
                        self.cash_account_id.id if self.cash_account_id else False
                    ),
                    "is_allocation": True,
                    "allocation_ref": allocation_ref,
                }
            )

            applied += take
            left -= take
            if left <= 0:
                break

        return applied

    @api.model
    def fix_all_commission_statuses(self):
        """
        Standard ORM utility:
        recompute stored fields for all commissions.
        (No SQL update, just triggers recompute/store.)
        """
        commissions = self.search([])
        commissions.invalidate_recordset(
            ["commission_paid", "commission_remaining", "payment_status"]
        )
        # recompute store fields
        commissions._compute_paid_remaining_status()

        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Status Fix Complete"),
                "message": _(
                    "Recomputed commission paid/remaining/status for %s records."
                )
                % len(commissions),
                "type": "success",
                "sticky": False,
            },
        }


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
    is_allocation = fields.Boolean(default=False)
    allocation_ref = fields.Char()

    date = fields.Date(string="Date", default=fields.Date.context_today, required=True)

    cash_account_id = fields.Many2one("idil.chart.account", string="Cash/Bank Account")

    transaction_booking_id = fields.Many2one(
        "idil.transaction_booking",
        string="Transaction Booking",
        readonly=True,
        help="Link to the accounting entry for this payment",
    )

    @api.model
    def create(self, vals):
        commission = self.env["idil.sales.commission"].browse(vals.get("commission_id"))

        # daily schedule still blocked
        if commission and commission.payment_schedule == "daily":
            raise ValidationError(_("Daily schedule commissions are not payable."))

        is_alloc = bool(vals.get("is_allocation"))
        amount = float(vals.get("amount") or 0.0)

        # ✅ normal payments must be > 0
        # ✅ allocations can be negative or positive, but not zero
        if (not is_alloc and amount <= 0) or (is_alloc and amount == 0):
            raise ValidationError(_("Invalid commission payment amount."))

        # ✅ Prevent overpay ONLY for normal payments
        if (
            not is_alloc
            and commission
            and amount > (commission.commission_remaining or 0.0)
        ):
            raise ValidationError(
                _("Payment amount (%.2f) exceeds remaining commission (%.2f).")
                % (amount, commission.commission_remaining or 0.0)
            )

        payment = super().create(vals)

        # ✅ Only real cash payments create salesperson transaction
        if not is_alloc:
            payment._create_salesperson_transaction()

        return payment

    @api.constrains("amount", "commission_id", "is_allocation")
    def _check_amount_not_exceed_remaining(self):
        for rec in self:
            if not rec.commission_id:
                continue

            # ✅ Allocation lines can be negative/positive and must NOT be blocked here
            if rec.is_allocation:
                continue

            if rec.commission_id.payment_schedule == "daily":
                raise ValidationError(_("Daily schedule commissions are not payable."))

            # remaining excluding THIS record
            other_paid = sum(
                rec.commission_id.payment_ids.filtered(lambda p: p.id != rec.id).mapped(
                    "amount"
                )
            )
            remaining = (rec.commission_id.commission_amount or 0.0) - other_paid

            if rec.amount > remaining + 0.00001:
                raise ValidationError(
                    _("Payment amount (%.2f) exceeds remaining commission (%.2f).")
                    % (rec.amount, remaining)
                )

    def _create_salesperson_transaction(self):
        """Post commission payment to salesperson account."""
        for rec in self:
            self.env["idil.salesperson.transaction"].create(
                {
                    "sales_person_id": rec.sales_person_id.id,
                    "date": rec.date,
                    "transaction_type": "other",
                    "amount": rec.amount,
                    "description": f"Commission Payment - {rec.commission_id.sale_order_id.name}",
                }
            )

    def unlink(self):
        """Delete associated salesperson transaction when payment is deleted (NO SQL)."""
        commissions = self.mapped("commission_id")

        for pay in self:
            trx = self.env["idil.salesperson.transaction"].search(
                [
                    ("sales_person_id", "=", pay.sales_person_id.id),
                    ("date", "=", pay.date),
                    ("amount", "=", pay.amount),
                    ("transaction_type", "=", "in"),
                    (
                        "description",
                        "=",
                        f"Commission Payment - {pay.commission_id.sale_order_id.name}   ",
                    ),
                ],
                limit=1,
            )
            if trx:
                trx.unlink()

        res = super().unlink()

        # Standard invalidate (stored compute will refresh when accessed)
        commissions.invalidate_recordset(
            ["commission_paid", "commission_remaining", "payment_status"]
        )
        return res
