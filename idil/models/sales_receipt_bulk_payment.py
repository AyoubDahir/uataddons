from venv import logger
from odoo import models, fields, api
from odoo.exceptions import UserError, ValidationError


class ReceiptBulkPayment(models.Model):
    _name = "idil.receipt.bulk.payment"
    _description = "Bulk Sales Receipt Payment"
    _inherit = ["mail.thread", "mail.activity.mixin"]

    company_id = fields.Many2one(
        "res.company", default=lambda s: s.env.company, required=True
    )
    name = fields.Char(string="Reference", default="New", readonly=True, copy=False)
    partner_type = fields.Selection(
        [("salesperson", "Salesperson"), ("customer", "Customer")],
        string="Type",
        required=True,
    )
    salesperson_id = fields.Many2one("idil.sales.sales_personnel", string="Salesperson")
    customer_id = fields.Many2one("idil.customer.registration", string="Customer")
    amount_to_pay = fields.Float(
        string="Total Amount to Pay", required=True, store=True
    )

    date = fields.Date(default=fields.Date.context_today, string="Date", required=True)
    line_ids = fields.One2many(
        "idil.receipt.bulk.payment.line",
        "bulk_receipt_payment_id",
        string="Receipt Lines",
    )

    due_receipt_amount = fields.Float(
        string="Total Due Receipt Amount",
        compute="_compute_due_receipt",
        store=False,
    )
    due_receipt_count = fields.Integer(
        string="Number of Due Receipts",
        compute="_compute_due_receipt",
        store=False,
    )
    payment_method_ids = fields.One2many(
        "idil.receipt.bulk.payment.method",
        "bulk_receipt_payment_id",
        string="Payment Methods",
    )
    payment_methods_total = fields.Float(
        string="Payment Methods Total", compute="_compute_payment_methods_total"
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
        tracking=True,
    )

    rate = fields.Float(
        string="Exchange Rate",
        compute="_compute_exchange_rate",
        store=True,
        readonly=True,
        tracking=True,
    )
    # 🆕 Add state field
    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("pending", "Pending"),
            ("confirmed", "Confirmed"),
            ("cancel", "Cancelled"),
        ],
        string="Status",
        default="draft",
        tracking=True,
    )

    @api.depends("currency_id", "date", "company_id")
    def _compute_exchange_rate(self):
        Rate = self.env["res.currency.rate"].sudo()
        for order in self:
            order.rate = 0.0
            if not order.currency_id:
                continue

            doc_date = (
                fields.Date.to_date(order.date) if order.date else fields.Date.today()
            )

            rate_rec = Rate.search(
                [
                    ("currency_id", "=", order.currency_id.id),
                    ("name", "<=", doc_date),
                    ("company_id", "in", [order.company_id.id, False]),
                ],
                order="company_id desc, name desc",
                limit=1,
            )

            order.rate = rate_rec.rate or 0.0

    @api.depends("payment_method_ids.payment_amount")
    def _compute_payment_methods_total(self):
        for rec in self:
            rec.payment_methods_total = sum(
                l.payment_amount for l in rec.payment_method_ids
            )

    @api.constrains("amount_to_pay", "payment_method_ids")
    def _check_payment_method_total(self):
        for rec in self:
            if rec.payment_method_ids:
                total_method = sum(l.payment_amount for l in rec.payment_method_ids)
                if abs(total_method - rec.amount_to_pay) > 0.01:
                    raise ValidationError(
                        "Sum of payment methods must equal Amount to Pay."
                    )

    @api.depends("salesperson_id", "customer_id", "partner_type")
    def _compute_due_receipt(self):
        for rec in self:
            if rec.partner_type == "salesperson" and rec.salesperson_id:
                receipts = rec.env["idil.sales.receipt"].search(
                    [
                        ("salesperson_id", "=", rec.salesperson_id.id),
                        ("payment_status", "=", "pending"),
                    ]
                )
            elif rec.partner_type == "customer" and rec.customer_id:
                receipts = rec.env["idil.sales.receipt"].search(
                    [
                        ("customer_id", "=", rec.customer_id.id),
                        ("payment_status", "=", "pending"),
                    ]
                )
            else:
                receipts = rec.env["idil.sales.receipt"]
            rec.due_receipt_amount = sum(r.due_amount - r.paid_amount for r in receipts)
            rec.due_receipt_count = len(receipts)

    @api.onchange("salesperson_id", "customer_id", "amount_to_pay", "partner_type")
    def _onchange_lines(self):
        self.line_ids = [(5, 0, 0)]
        if self.partner_type == "salesperson" and self.salesperson_id:
            domain = [
                ("salesperson_id", "=", self.salesperson_id.id),
                ("payment_status", "=", "pending"),
            ]
        elif self.partner_type == "customer" and self.customer_id:
            domain = [
                ("customer_id", "=", self.customer_id.id),
                ("payment_status", "=", "pending"),
            ]
        else:
            return
        receipts = self.env["idil.sales.receipt"].search(
            domain, order="receipt_date asc"
        )
        remaining_payment = self.amount_to_pay
        lines = []
        for receipt in receipts:
            if remaining_payment <= 0:
                break
            to_pay = min(receipt.due_amount - receipt.paid_amount, remaining_payment)
            if to_pay > 0:
                lines.append(
                    (
                        0,
                        0,
                        {
                            "receipt_id": receipt.id,
                            "receipt_date": receipt.receipt_date,  # Make sure this field exists and is set in the receipt
                            "due_amount": receipt.due_amount,
                            "paid_amount": receipt.paid_amount,
                            "remaining_amount": receipt.due_amount
                            - receipt.paid_amount,
                            "paid_now": to_pay,
                        },
                    )
                )
                remaining_payment -= to_pay
        self.line_ids = lines

    @api.constrains("amount_to_pay", "salesperson_id", "customer_id", "partner_type")
    def _check_amount(self):
        for rec in self:
            if rec.partner_type == "salesperson" and rec.salesperson_id:
                receipts = rec.env["idil.sales.receipt"].search(
                    [
                        ("salesperson_id", "=", rec.salesperson_id.id),
                        ("payment_status", "=", "pending"),
                    ]
                )
            elif rec.partner_type == "customer" and rec.customer_id:
                receipts = rec.env["idil.sales.receipt"].search(
                    [
                        ("customer_id", "=", rec.customer_id.id),
                        ("payment_status", "=", "pending"),
                    ]
                )
            else:
                continue
            total_due = sum(r.due_amount - r.paid_amount for r in receipts)
            if rec.amount_to_pay > total_due:
                raise ValidationError(
                    f"Total Amount to Pay ({rec.amount_to_pay}) cannot exceed total due ({total_due})."
                )

    @api.constrains("payment_method_ids")
    def _check_at_least_one_payment_method(self):
        for rec in self:
            if not rec.payment_method_ids:
                raise ValidationError("At least one payment method must be added.")

    def action_confirm_payment(self):
        try:
            with self.env.cr.savepoint():
                ChartAccount = self.env["idil.chart.account"]

                if self.state != "draft":
                    return

                if not self.payment_method_ids:
                    raise UserError("At least one payment method is required.")

                if self.amount_to_pay <= 0:
                    raise UserError("Payment amount must be greater than zero.")

                if not self.line_ids:
                    raise UserError("No receipt lines to apply payment to.")

                trx_source = self.env["idil.transaction.source"].search(
                    [("name", "=", "Bulk Receipt")], limit=1
                )
                if not trx_source:
                    raise UserError("Transaction source 'Bulk Receipt' not found.")

                remaining_receipts = self.line_ids.filtered(
                    lambda l: l.receipt_id.due_amount > l.receipt_id.paid_amount
                )
                if not remaining_receipts:
                    raise UserError("No valid receipts with remaining due amount.")

                # Helper: convert between USD and SL based on self.rate (SL per 1 USD)
                # Adjust if you later support more pairs.
                def _convert(amount, from_cur, to_cur, rate):
                    if from_cur.id == to_cur.id:
                        return amount
                    from_name = (from_cur.name or "").upper()
                    to_name = (to_cur.name or "").upper()
                    # Common aliases for Somali Shilling
                    is_sl = lambda n: n in (
                        "SL",
                        "SOS",
                        "SLSH",
                        "SO SHILLING",
                        "SOMALI SHILLING",
                    )
                    if from_name == "USD" and is_sl(to_name):
                        return amount * rate  # USD -> SL
                    if is_sl(from_name) and to_name == "USD":
                        return amount / rate  # SL -> USD
                    raise UserError(
                        f"Unsupported currency pair: {from_cur.name} -> {to_cur.name}"
                    )

                for method in self.payment_method_ids:
                    payment_account = method.payment_account_id
                    if not payment_account:
                        raise UserError("Missing payment account.")

                    remaining_amount = (
                        method.payment_amount
                    )  # in receipt/AR currency (e.g., SL)
                    if remaining_amount <= 0:
                        continue

                    pay_cur = payment_account.currency_id

                    for line in remaining_receipts:
                        receipt = line.receipt_id
                        due_balance = receipt.due_amount - receipt.paid_amount

                        if due_balance <= 0 or remaining_amount <= 0:
                            continue

                        # Amount to settle on this receipt (in AR currency)
                        to_pay = min(due_balance, remaining_amount)

                        # Determine AR account (and AR currency)
                        if self.partner_type == "salesperson":
                            ar_account = receipt.salesperson_id.account_receivable_id
                            is_salesperson = True
                        elif self.partner_type == "customer":
                            ar_account = receipt.customer_id.account_receivable_id
                            is_salesperson = False
                        else:
                            raise UserError("Invalid partner type.")

                        ar_cur = ar_account.currency_id
                        rate = self.rate

                        # Find FX clearing accounts per currency
                        # Source clearing = payment currency
                        # Target clearing = AR currency
                        source_clearing_account = ChartAccount.search(
                            [
                                ("name", "=", "Exchange Clearing Account"),
                                ("currency_id", "=", pay_cur.id),
                            ],
                            limit=1,
                        )
                        target_clearing_account = ChartAccount.search(
                            [
                                ("name", "=", "Exchange Clearing Account"),
                                ("currency_id", "=", ar_cur.id),
                            ],
                            limit=1,
                        )
                        if not source_clearing_account or not target_clearing_account:
                            raise ValidationError(
                                "Exchange Clearing Accounts must exist for BOTH the payment currency and the receivable (AR) currency."
                            )

                        # ----- Create transaction booking -----
                        trx_booking = self.env["idil.transaction_booking"].create(
                            {
                                "order_number": (
                                    receipt.sales_order_id.name
                                    if receipt.sales_order_id
                                    else "/"
                                ),
                                "trx_source_id": trx_source.id,
                                "payment_method": "other",
                                "customer_id": (
                                    receipt.customer_id.id
                                    if receipt.customer_id
                                    else False
                                ),
                                "reffno": self.name,
                                "rate": rate,
                                "sale_order_id": (
                                    receipt.sales_order_id.id
                                    if receipt.sales_order_id
                                    else False
                                ),
                                "payment_status": (
                                    "paid" if to_pay >= due_balance else "partial_paid"
                                ),
                                "customer_opening_balance_id": receipt.customer_opening_balance_id.id,
                                "trx_date": self.date,
                                "amount": to_pay,  # base amounts are in AR currency
                            }
                        )

                        booking_lines_to_link = []

                        if pay_cur.id == ar_cur.id:
                            # Same currency: DR Bank, CR AR
                            dr_line = self.env["idil.transaction_bookingline"].create(
                                {
                                    "transaction_booking_id": trx_booking.id,
                                    "bulk_receipt_payment_id": self.id,
                                    "transaction_type": "dr",
                                    "account_number": payment_account.id,
                                    "dr_amount": to_pay,
                                    "cr_amount": 0.0,
                                    "transaction_date": self.date,
                                    "description": f"Bulk Receipt - {self.name}",
                                    "customer_opening_balance_id": receipt.customer_opening_balance_id.id,
                                }
                            )
                            cr_line = self.env["idil.transaction_bookingline"].create(
                                {
                                    "transaction_booking_id": trx_booking.id,
                                    "bulk_receipt_payment_id": self.id,
                                    "transaction_type": "cr",
                                    "account_number": ar_account.id,
                                    "dr_amount": 0.0,
                                    "cr_amount": to_pay,
                                    "transaction_date": self.date,
                                    "description": f"Bulk Receipt - {self.name}",
                                    "customer_opening_balance_id": receipt.customer_opening_balance_id.id,
                                }
                            )
                            booking_lines_to_link += [dr_line.id, cr_line.id]

                        else:
                            # Cross currency: 4 lines (Bank & Source clearing in payment currency; Target clearing & AR in AR currency)
                            pay_amt_src = _convert(
                                to_pay, ar_cur, pay_cur, rate
                            )  # AR -> payment currency

                            # DR Bank (payment currency)
                            dr_bank = self.env["idil.transaction_bookingline"].create(
                                {
                                    "transaction_booking_id": trx_booking.id,
                                    "bulk_receipt_payment_id": self.id,
                                    "transaction_type": "dr",
                                    "account_number": payment_account.id,
                                    "dr_amount": pay_amt_src,
                                    "cr_amount": 0.0,
                                    "transaction_date": self.date,
                                    "description": f"Bulk Receipt FX - {self.name} (Bank)",
                                    "customer_opening_balance_id": receipt.customer_opening_balance_id.id,
                                }
                            )
                            # CR Source FX Clearing (payment currency)
                            cr_src_clear = self.env[
                                "idil.transaction_bookingline"
                            ].create(
                                {
                                    "transaction_booking_id": trx_booking.id,
                                    "bulk_receipt_payment_id": self.id,
                                    "transaction_type": "cr",
                                    "account_number": source_clearing_account.id,
                                    "dr_amount": 0.0,
                                    "cr_amount": pay_amt_src,
                                    "transaction_date": self.date,
                                    "description": f"Bulk Receipt FX - {self.name} (Source Clearing)",
                                    "customer_opening_balance_id": receipt.customer_opening_balance_id.id,
                                }
                            )
                            # DR Target FX Clearing (AR currency)
                            dr_tgt_clear = self.env[
                                "idil.transaction_bookingline"
                            ].create(
                                {
                                    "transaction_booking_id": trx_booking.id,
                                    "bulk_receipt_payment_id": self.id,
                                    "transaction_type": "dr",
                                    "account_number": target_clearing_account.id,
                                    "dr_amount": to_pay,
                                    "cr_amount": 0.0,
                                    "transaction_date": self.date,
                                    "description": f"Bulk Receipt FX - {self.name} (Target Clearing)",
                                    "customer_opening_balance_id": receipt.customer_opening_balance_id.id,
                                }
                            )
                            # CR Accounts Receivable (AR currency)
                            cr_ar = self.env["idil.transaction_bookingline"].create(
                                {
                                    "transaction_booking_id": trx_booking.id,
                                    "bulk_receipt_payment_id": self.id,
                                    "transaction_type": "cr",
                                    "account_number": ar_account.id,
                                    "dr_amount": 0.0,
                                    "cr_amount": to_pay,
                                    "transaction_date": self.date,
                                    "description": f"Bulk Receipt - {self.name}",
                                    "customer_opening_balance_id": receipt.customer_opening_balance_id.id,
                                }
                            )
                            booking_lines_to_link += [
                                dr_bank.id,
                                cr_src_clear.id,
                                dr_tgt_clear.id,
                                cr_ar.id,
                            ]
                        # ----- Sales Payment record -----
                        payment = self.env["idil.sales.payment"].create(
                            {
                                "sales_receipt_id": receipt.id,
                                "bulk_receipt_payment_id": self.id,
                                "payment_method_ids": [(4, method.id)],
                                "transaction_booking_ids": [(4, trx_booking.id)],
                                # Link detailed booking lines too (optional if your model uses it)
                                "transaction_bookingline_ids": [
                                    (4, bl_id) for bl_id in booking_lines_to_link
                                ],
                                "payment_account": payment_account.id,
                                "payment_date": self.date,
                                "paid_amount": to_pay,  # AR currency
                            }
                        )
                        method.write({"sales_payment_id": payment.id})
                        line.paid_now += to_pay
                        # ----- Ledger side-effects -----
                        if is_salesperson:
                            self.env["idil.salesperson.transaction"].create(
                                {
                                    "sales_person_id": receipt.salesperson_id.id,
                                    "bulk_receipt_payment_id": self.id,
                                    "date": self.date,
                                    "sales_payment_id": payment.id,
                                    "sales_receipt_id": receipt.id,
                                    "order_id": (
                                        receipt.sales_order_id.id
                                        if receipt.sales_order_id
                                        else False
                                    ),
                                    "transaction_type": "in",
                                    "amount": to_pay,
                                    "description": f"Bulk Payment - Receipt {receipt.id} - Order {receipt.sales_order_id.name if receipt.sales_order_id else ''}",
                                }
                            )
                        else:
                            self.env["idil.customer.sale.payment"].create(
                                {
                                    "order_id": (
                                        receipt.cusotmer_sale_order_id.id
                                        if receipt.cusotmer_sale_order_id
                                        else False
                                    ),
                                    "customer_id": receipt.customer_id.id,
                                    "bulk_receipt_payment_id": self.id,
                                    "payment_method": "cash",
                                    "sales_payment_id": payment.id,
                                    "sales_receipt_id": receipt.id,
                                    "account_id": payment_account.id,
                                    "amount": to_pay,
                                    "date": self.date,
                                }
                            )

                        if receipt.cusotmer_sale_order_id:
                            receipt.cusotmer_sale_order_id._compute_total_paid()
                            receipt.cusotmer_sale_order_id._compute_balance_due()

                        # Deduct from method allocation (in AR currency)
                        remaining_amount -= to_pay

                    if remaining_amount > 0:
                        raise UserError(
                            f"⚠️ Payment method '{payment_account.name}' has {remaining_amount:.2f} unallocated."
                        )

                self.state = "confirmed"

        except Exception as e:
            logger.error(f"transaction failed: {str(e)}")
            raise ValidationError(f"Transaction failed: {str(e)}")

    @api.model
    def create(self, vals):
        if vals.get("name", "New") == "New":
            vals["name"] = (
                self.env["ir.sequence"].next_by_code("idil.receipt.bulk.payment.seq")
                or "BRP/0001"
            )
        return super().create(vals)

    def write(self, vals):
        for rec in self:
            if rec.state == "confirmed":
                allowed_fields = {"amount_to_pay"}
                incoming_fields = set(vals.keys())

                # If there's any field being updated that's not allowed
                if not incoming_fields.issubset(allowed_fields):
                    raise ValidationError(
                        "This record is confirmed and cannot be modified.\n"
                        "Only 'amount_to_pay' can be adjusted automatically when a sales payment is deleted."
                    )
        return super().write(vals)

    #
    def unlink(self):
        """Full rollback of action_confirm_payment, then delete the bulk.
        - Restores receipt paid/remaining/status
        - Deletes salesperson/customer side-ledger rows
        - Deletes booking lines and booking headers
        - Unlinks/clears sales_payment_id on methods, deletes sales payments
        - Resets line.paid_now and recomputes affected sales orders
        - Removes lines & methods, then the bulk itself
        """
        try:
            with self.env.cr.savepoint():
                for rec in self:
                    # Gather only payments created by/linked to this bulk
                    payments = self.env["idil.sales.payment"].search(
                        [("bulk_receipt_payment_id", "=", rec.id)]
                    )
                    if rec.state == "confirmed":
                        # 1) Reverse per-payment effects in the exact opposite order
                        for pmt in payments:
                            # b) Remove side-ledger rows tied to this payment
                            self.env["idil.salesperson.transaction"].search(
                                [("sales_payment_id", "=", pmt.id)]
                            ).unlink()
                            self.env["idil.customer.sale.payment"].search(
                                [("sales_payment_id", "=", pmt.id)]
                            ).unlink()
                            # c) Remove booking lines and booking headers created during confirm
                            #    (they were linked to the sales payment via many2manys)
                            pmt.transaction_bookingline_ids.unlink()
                            pmt.transaction_booking_ids.unlink()

                            # d) Detach method link (if any) for cleanliness, then delete payment
                            rec.payment_method_ids.filtered(
                                lambda m: m.sales_payment_id
                                and m.sales_payment_id.id == pmt.id
                            ).write({"sales_payment_id": False})
                            pmt.unlink()

                        # 2) Reset each line's 'paid_now' that we incremented during confirm
                        rec.line_ids.write({"paid_now": 0.0})

                        # 3) Recompute affected orders once receipts are restored
                        affected_receipts = rec.line_ids.mapped("receipt_id")
                        for r in affected_receipts:
                            if r.cusotmer_sale_order_id:
                                r.cusotmer_sale_order_id._compute_total_paid()
                                r.cusotmer_sale_order_id._compute_balance_due()

                        # 4) Cleanup lines & methods used by this bulk
                        rec.payment_method_ids.unlink()
                        rec.line_ids.unlink()

                    # 5) Finally delete the bulk record itself
                    super(ReceiptBulkPayment, rec).unlink()
                return True
        except Exception as e:
            logger.error(f"transaction failed: {str(e)}")
            raise ValidationError(f"Transaction failed: {str(e)}")


class ReceiptBulkPaymentLine(models.Model):
    _name = "idil.receipt.bulk.payment.line"
    _description = "Bulk Receipt Payment Line"

    bulk_receipt_payment_id = fields.Many2one(
        "idil.receipt.bulk.payment", string="Bulk Payment"
    )
    receipt_id = fields.Many2one("idil.sales.receipt", string="Receipt", required=True)
    receipt_date = fields.Datetime(related="receipt_id.receipt_date", store=True)
    due_amount = fields.Float(related="receipt_id.due_amount", store=True)
    paid_amount = fields.Float(related="receipt_id.paid_amount", store=True)
    remaining_amount = fields.Float(compute="_compute_remaining_amount", store=True)
    paid_now = fields.Float(string="Paid Now", store=True)

    customer_id = fields.Many2one(
        related="receipt_id.customer_id",
        string="Customer",
        readonly=True,
    )
    salesperson_id = fields.Many2one(
        related="receipt_id.salesperson_id",
        string="Salesperson",
        readonly=True,
    )
    receipt_status = fields.Selection(
        related="receipt_id.payment_status",
        string="Status",
        readonly=True,
    )

    @api.depends("due_amount", "paid_amount")
    def _compute_remaining_amount(self):
        for rec in self:
            rec.remaining_amount = (rec.due_amount or 0) - (rec.paid_amount or 0)


class ReceiptBulkPaymentMethod(models.Model):
    _name = "idil.receipt.bulk.payment.method"
    _description = "Bulk Receipt Payment Method"

    company_id = fields.Many2one(
        "res.company", default=lambda s: s.env.company, required=True
    )
    bulk_receipt_payment_id = fields.Many2one(
        "idil.receipt.bulk.payment", string="Bulk Payment"
    )
    payment_account_id = fields.Many2one(
        "idil.chart.account",
        string="Payment Account",
        required=True,
        domain=[("account_type", "in", ["cash", "bank_transfer", "sales_expense"])],
    )

    account_currency_id = fields.Many2one(
        related="payment_account_id.currency_id",
        store=True,
        readonly=True,
        string="Account Currency",
    )
    # Currency fields
    currency_id = fields.Many2one(
        "res.currency",
        string="Exchange Currency",
        required=True,
        default=lambda self: self.env["res.currency"].search(
            [("name", "=", "SL")], limit=1
        ),
        readonly=True,
        tracking=True,
    )

    # Allow per-line edits & persistence
    rate = fields.Float(
        string="Exchange Rate",
        compute="_compute_exchange_rate",
        store=True,
        tracking=True,
        help="Exchange rate for this payment line. Defaults from the parent, but can be overridden here.",
    )

    # USD mirror field (editable)
    usd_amount = fields.Float(string="USD Amount")

    payment_amount = fields.Float(string="Amount", required=True)
    note = fields.Char(string="Memo/Reference")
    sales_payment_id = fields.Many2one(
        "idil.sales.payment",
        string="Linked Sales Payment",
        ondelete="cascade",  # This makes it auto-delete if sales payment is deleted
    )
    payment_date = fields.Datetime(
        string="Payment Date",
        compute="_compute_payment_datetime",
    )

    @api.depends("bulk_receipt_payment_id.date")
    def _compute_payment_datetime(self):
        for rec in self:
            rec.payment_date = (
                fields.Datetime.to_datetime(rec.bulk_receipt_payment_id.date)
                if rec.bulk_receipt_payment_id and rec.bulk_receipt_payment_id.date
                else False
            )

    @api.depends("currency_id", "payment_date", "company_id")
    def _compute_exchange_rate(self):
        Rate = self.env["res.currency.rate"].sudo()
        for order in self:
            order.rate = 0.0
            if not order.currency_id:
                continue

            doc_date = (
                fields.Date.to_date(order.payment_date)
                if order.payment_date
                else fields.Date.today()
            )

            rate_rec = Rate.search(
                [
                    ("currency_id", "=", order.currency_id.id),
                    ("name", "<=", doc_date),
                    ("company_id", "in", [order.company_id.id, False]),
                ],
                order="company_id desc, name desc",
                limit=1,
            )

            order.rate = rate_rec.rate or 0.0

    @api.onchange("usd_amount", "rate")
    def _onchange_usd_amount_or_rate(self):
        """Typing USD updates local amount."""
        if self.usd_amount and self.rate:
            self.payment_amount = self.usd_amount * self.rate

    @api.onchange("payment_amount")
    def _onchange_payment_amount(self):
        """Typing local amount updates USD (only if rate set)."""
        if self.payment_amount and self.rate:
            self.usd_amount = self.payment_amount / self.rate
