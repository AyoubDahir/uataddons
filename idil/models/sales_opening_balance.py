from odoo import models, fields, api, exceptions
from datetime import datetime
from datetime import date
import re
from odoo.exceptions import ValidationError, UserError
import logging

_logger = logging.getLogger(__name__)


class SalesOpeningBalance(models.Model):
    _name = "idil.sales.opening.balance"
    _description = "Sales Team Opening Balance"
    _order = "id desc"

    company_id = fields.Many2one(
        "res.company", default=lambda s: s.env.company, required=True
    )
    name = fields.Char(string="Reference", default="New", readonly=True, copy=False)
    date = fields.Date(
        string="Opening Date", default=fields.Date.context_today, required=True
    )
    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("posted", "Posted"),
            ("cancel", "Cancelled"),
        ],
        string="Status",
        default="draft",
        readonly=True,
    )
    line_ids = fields.One2many(
        "idil.sales.opening.balance.line", "opening_balance_id", string="Lines"
    )
    internal_comment = fields.Text(string="Internal Comment")

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
        compute="_compute_exchange_rate",
        store=True,
        readonly=True,
    )
    total_due_balance = fields.Float(
        string="Total Due Balance",
        compute="_compute_total_due_balance",
        store=False,
    )

    # ─────────────────────────────────────────────────────────────────────────
    # Computed fields
    # ─────────────────────────────────────────────────────────────────────────

    @api.depends("line_ids")
    def _compute_total_due_balance(self):
        for record in self:
            receipts = self.env["idil.sales.receipt"].search(
                [("sales_opening_balance_id", "=", record.id)]
            )
            record.total_due_balance = sum(receipts.mapped("remaining_amount"))

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

    # ─────────────────────────────────────────────────────────────────────────
    # Helper / utility methods
    # ─────────────────────────────────────────────────────────────────────────

    def _require_rate(self, currency_id, date, company_id):
        """Return a positive FX rate or raise a clear ValidationError."""
        Rate = self.env["res.currency.rate"].sudo()
        doc_date = fields.Date.to_date(date) if date else fields.Date.today()
        rec = Rate.search(
            [
                ("currency_id", "=", currency_id),
                ("name", "<=", doc_date),
                ("company_id", "in", [company_id, False]),
            ],
            order="company_id desc, name desc",
            limit=1,
        )
        rate = rec.rate or 0.0
        if rate <= 0.0:
            currency = self.env["res.currency"].browse(currency_id)
            raise ValidationError(
                f"No valid exchange rate (> 0) found for currency '{currency.name}' "
                f"on or before {doc_date}. Please add a rate in Accounting ▸ Configuration ▸ Currencies."
            )
        return rate

    def _get_equity_account(self):
        account = self.env["idil.chart.account"].search(
            [("name", "=", "Opening Balance Account")], limit=1
        )
        if not account:
            raise ValidationError(
                "Opening Balance Account not found. Please configure it."
            )
        return account

    def _get_trx_source(self):
        source = self.env["idil.transaction.source"].search(
            [("name", "=", "Sales Opening Balance")], limit=1
        )
        if not source:
            raise ValidationError(
                'Transaction source "Sales Opening Balance" not found.'
            )
        return source

    def _get_clearing_accounts(self, source_currency_id, target_currency_id):
        """Return (source_clearing, target_clearing) accounts."""
        source_clearing = self.env["idil.chart.account"].search(
            [
                ("name", "=", "Exchange Clearing Account"),
                ("currency_id", "=", source_currency_id),
            ],
            limit=1,
        )
        target_clearing = self.env["idil.chart.account"].search(
            [
                ("name", "=", "Exchange Clearing Account"),
                ("currency_id", "=", target_currency_id),
            ],
            limit=1,
        )
        if not source_clearing or not target_clearing:
            raise ValidationError(
                "Exchange clearing accounts are required for currency conversion. "
                "Please configure them in the chart of accounts."
            )
        return source_clearing, target_clearing

    def _validate_no_payments_block(self):
        """Raise if any receipt has been paid or external transactions exist."""
        for line in self.line_ids:
            paid_receipt = self.env["idil.sales.receipt"].search(
                [
                    ("sales_opening_balance_id", "=", self.id),
                    ("salesperson_id", "=", line.sales_person_id.id),
                    ("paid_amount", ">", 0),
                ],
                limit=1,
            )
            if paid_receipt:
                raise ValidationError(
                    f"Cannot modify opening balance for '{line.sales_person_id.name}': "
                    "a payment has already been received against this entry."
                )
            external_txn = self.env["idil.salesperson.transaction"].search(
                [
                    ("sales_person_id", "=", line.sales_person_id.id),
                    ("sales_opening_balance_id", "!=", self.id),
                    ("amount", ">", 0),
                ],
                limit=1,
            )
            if external_txn:
                raise ValidationError(
                    f"Cannot modify opening balance for '{line.sales_person_id.name}': "
                    "another transaction already exists for this salesperson."
                )

    # ─────────────────────────────────────────────────────────────────────────
    # Core booking logic – separated methods
    # ─────────────────────────────────────────────────────────────────────────

    def _clear_generated_records(self):
        """Delete all bookings, booking-lines, receipts and salesperson
        transactions that were generated for this opening balance."""
        bookings = self.env["idil.transaction_booking"].search(
            [("sales_opening_balance_id", "=", self.id)]
        )
        for booking in bookings:
            booking.booking_lines.unlink()
        bookings.unlink()

        self.env["idil.salesperson.transaction"].search(
            [("sales_opening_balance_id", "=", self.id)]
        ).unlink()

        # Pass context flag so SalesReceipt.unlink() allows deletion
        # of receipts that originated from this opening balance.
        self.env["idil.sales.receipt"].with_context(
            skip_opening_balance_protection=True
        ).search([("sales_opening_balance_id", "=", self.id)]).unlink()

    def _create_booking_for_line(self, line, equity_account, trx_source):
        """Create a transaction_booking for one opening-balance line.

        • Same currency (receivable == equity):  2 booking lines
              DR  Salesperson Receivable
              CR  Opening Balance Account

        • Different currencies:                  4 booking lines  (exchange flow)
              DR  Salesperson Receivable     (source currency)
              CR  Exchange Clearing          (source currency)
              DR  Exchange Clearing          (target currency)
              CR  Opening Balance Account    (target currency)
        """
        receivable_account = line.sales_person_id.account_receivable_id
        receivable_currency = receivable_account.currency_id
        equity_currency = equity_account.currency_id
        same_currency = receivable_currency == equity_currency

        rate = self.rate
        # Rate is only mandatory when a conversion is needed
        if not same_currency and rate <= 0:
            raise ValidationError(
                f"Exchange rate must be greater than zero when currencies differ. "
                f"Please set a valid rate for currency '{self.currency_id.name}'."
            )

        booking = self.env["idil.transaction_booking"].create(
            {
                "trx_date": self.date,
                "reffno": self.name,
                "payment_status": "pending",
                "payment_method": "opening_balance",
                "amount": line.amount,
                "amount_paid": 0.0,
                "rate": rate,
                "remaining_amount": line.amount,
                "trx_source_id": trx_source.id,
                "sales_person_id": line.sales_person_id.id,
                "sales_opening_balance_id": self.id,
            }
        )

        desc = f"Opening Balance for {line.sales_person_id.name}"

        if same_currency:
            # ── 2-line flow: no exchange needed ───────────────────────────────
            self.env["idil.transaction_bookingline"].create(
                [
                    # 1. DR Salesperson Receivable
                    {
                        "transaction_booking_id": booking.id,
                        "sales_opening_balance_id": self.id,
                        "account_number": receivable_account.id,
                        "transaction_type": "dr",
                        "dr_amount": line.amount,
                        "cr_amount": 0.0,
                        "transaction_date": self.date,
                        "description": desc,
                    },
                    # 2. CR Opening Balance Account
                    {
                        "transaction_booking_id": booking.id,
                        "sales_opening_balance_id": self.id,
                        "account_number": equity_account.id,
                        "transaction_type": "cr",
                        "dr_amount": 0.0,
                        "cr_amount": line.amount,
                        "transaction_date": self.date,
                        "description": desc,
                    },
                ]
            )
        else:
            # ── 4-line flow: currency exchange required ────────────────────────
            source_clearing, target_clearing = self._get_clearing_accounts(
                receivable_currency.id,
                equity_currency.id,
            )
            converted_amount = line.amount / rate

            self.env["idil.transaction_bookingline"].create(
                [
                    # 1. DR Salesperson Receivable (source currency)
                    {
                        "transaction_booking_id": booking.id,
                        "sales_opening_balance_id": self.id,
                        "account_number": receivable_account.id,
                        "transaction_type": "dr",
                        "dr_amount": line.amount,
                        "cr_amount": 0.0,
                        "transaction_date": self.date,
                        "description": desc,
                    },
                    # 2. CR Exchange Clearing (source currency)
                    {
                        "transaction_booking_id": booking.id,
                        "sales_opening_balance_id": self.id,
                        "account_number": source_clearing.id,
                        "transaction_type": "cr",
                        "dr_amount": 0.0,
                        "cr_amount": line.amount,
                        "transaction_date": self.date,
                        "description": desc,
                    },
                    # 3. DR Exchange Clearing (target currency)
                    {
                        "transaction_booking_id": booking.id,
                        "sales_opening_balance_id": self.id,
                        "account_number": target_clearing.id,
                        "transaction_type": "dr",
                        "dr_amount": converted_amount,
                        "cr_amount": 0.0,
                        "transaction_date": self.date,
                        "description": desc,
                    },
                    # 4. CR Opening Balance Account (target currency)
                    {
                        "transaction_booking_id": booking.id,
                        "sales_opening_balance_id": self.id,
                        "account_number": equity_account.id,
                        "transaction_type": "cr",
                        "dr_amount": 0.0,
                        "cr_amount": converted_amount,
                        "transaction_date": self.date,
                        "description": desc,
                    },
                ]
            )
        return booking

    def _create_receipt_for_line(self, line):
        """Create an idil.sales.receipt for one opening-balance line."""
        return self.env["idil.sales.receipt"].create(
            {
                "salesperson_id": line.sales_person_id.id,
                "due_amount": line.amount,
                "paid_amount": 0.0,
                "remaining_amount": line.amount,
                "receipt_date": self.date,
                "sales_opening_balance_id": self.id,
            }
        )

    def _create_salesperson_transaction_for_line(self, line):
        """Create an idil.salesperson.transaction for one opening-balance line."""
        return self.env["idil.salesperson.transaction"].create(
            {
                "sales_person_id": line.sales_person_id.id,
                "sales_opening_balance_id": self.id,
                "date": self.date,
                "transaction_type": "out",
                "amount": line.amount,
                "description": f"Opening Balance for ({line.sales_person_id.name})",
            }
        )

    def _generate_all_records(self):
        """(Re-)generate bookings, receipts and salesperson transactions for
        every line on this opening balance.  Call after clearing old records."""
        equity_account = self._get_equity_account()
        trx_source = self._get_trx_source()

        for line in self.line_ids:
            if not line.sales_person_id.account_receivable_id:
                raise ValidationError(
                    f"Salesperson '{line.sales_person_id.name}' has no receivable account configured."
                )
            self._create_booking_for_line(line, equity_account, trx_source)
            self._create_receipt_for_line(line)
            self._create_salesperson_transaction_for_line(line)

    # ─────────────────────────────────────────────────────────────────────────
    # Confirm button
    # ─────────────────────────────────────────────────────────────────────────

    def action_confirm(self):
        """Validate, generate all accounting records and mark as Posted."""
        for record in self:
            if record.state == "posted":
                raise UserError("This opening balance is already posted.")
            if record.state == "cancel":
                raise UserError("A cancelled opening balance cannot be confirmed.")
            if not record.line_ids:
                raise ValidationError(
                    "Please add at least one salesperson line before confirming."
                )

            # Check for duplicate salesperson lines across other non-cancelled documents
            for line in record.line_ids:
                existing = self.env["idil.sales.opening.balance.line"].search(
                    [
                        ("sales_person_id", "=", line.sales_person_id.id),
                        ("opening_balance_id.state", "!=", "cancel"),
                        ("opening_balance_id", "!=", record.id),
                    ],
                    limit=1,
                )
                if existing:
                    raise ValidationError(
                        f"Salesperson '{line.sales_person_id.name}' already has a posted "
                        "opening balance entry. You cannot create another one."
                    )

            try:
                with self.env.cr.savepoint():
                    # Clear any previously generated records (idempotent)
                    record._clear_generated_records()
                    # Recreate everything from current lines
                    record._generate_all_records()
                    # Mark as posted
                    record.write({"state": "posted"})
            except Exception as e:
                _logger.error(f"action_confirm failed: {str(e)}")
                raise ValidationError(f"Confirm failed: {str(e)}")

    def action_cancel(self):
        """Cancel the opening balance (only if no payments received)."""
        for record in self:
            if record.state == "cancel":
                raise UserError("Already cancelled.")
            record._validate_no_payments_block()
            try:
                with self.env.cr.savepoint():
                    record._clear_generated_records()
                    record.write({"state": "cancel"})
            except Exception as e:
                _logger.error(f"action_cancel failed: {str(e)}")
                raise ValidationError(f"Cancel failed: {str(e)}")

    def action_reset_to_draft(self):
        """Reset a posted or cancelled record back to Draft.

        Clears all generated records (bookings, receipts, salesperson
        transactions) so the record can be freely edited and re-confirmed.
        Blocked if any payment has already been received.
        """
        for record in self:
            if record.state == "draft":
                raise UserError("Record is already in Draft.")
            # Block if payments exist
            record._validate_no_payments_block()
            try:
                with self.env.cr.savepoint():
                    record._clear_generated_records()
                    # bypass write() override (which would try to regenerate records)
                    super(SalesOpeningBalance, record).write({"state": "draft"})
            except Exception as e:
                _logger.error(f"action_reset_to_draft failed: {str(e)}")
                raise ValidationError(f"Reset to Draft failed: {str(e)}")

    # ─────────────────────────────────────────────────────────────────────────
    # ORM overrides
    # ─────────────────────────────────────────────────────────────────────────

    @api.model
    def create(self, vals):
        """Save record in DRAFT.  No bookings / receipts / transactions yet."""
        try:
            with self.env.cr.savepoint():
                # Pre-create duplicate check
                line_vals_list = vals.get("line_ids", [])
                for command in line_vals_list:
                    if command[0] == 0:
                        line_vals = command[2]
                        sp_id = line_vals.get("sales_person_id")
                        if sp_id:
                            existing = self.env[
                                "idil.sales.opening.balance.line"
                            ].search(
                                [
                                    ("sales_person_id", "=", sp_id),
                                    ("opening_balance_id.state", "!=", "cancel"),
                                ],
                                limit=1,
                            )
                            if existing:
                                raise ValidationError(
                                    f"Salesperson '{existing.sales_person_id.name}' already has "
                                    "an opening balance entry. You cannot create another one."
                                )

                # Assign sequence
                if vals.get("name", "New") == "New":
                    vals["name"] = (
                        self.env["ir.sequence"].next_by_code(
                            "idil.sales.opening.balance"
                        )
                        or "New"
                    )

                # Always start in draft – no generated records yet
                vals["state"] = "draft"
                return super().create(vals)

        except Exception as e:
            _logger.error(f"create failed: {str(e)}")
            raise ValidationError(f"Create failed: {str(e)}")

    def write(self, vals):
        """Update the record.

        • Draft  → plain update, no generated-record changes.
        • Posted → validate no payments, clear old generated records,
                   recreate them from the (now-updated) lines.
        """
        try:
            with self.env.cr.savepoint():
                # Separate posted records from draft/cancelled records
                posted = self.filtered(lambda r: r.state == "posted")
                others = self - posted

                # For posted records, block if payments exist BEFORE we write
                for record in posted:
                    record._validate_no_payments_block()

                # Apply the write for all records
                res = super().write(vals)

                # For posted records: clear & regenerate
                for record in posted:
                    record._clear_generated_records()
                    record._generate_all_records()

                return res

        except Exception as e:
            _logger.error(f"write failed: {str(e)}")
            raise ValidationError(f"Write failed: {str(e)}")

    def unlink(self):
        try:
            with self.env.cr.savepoint():
                for opening_balance in self:
                    # If already cancelled, tell user it is already logically deleted
                    if opening_balance.state == "cancel":
                        raise ValidationError(
                            f"'{opening_balance.name}' has already been cancelled. "
                            f"It is already treated as deleted logically."
                        )

                    # If posted, validate first and clear generated records
                    if opening_balance.state == "posted":
                        opening_balance._validate_no_payments_block()
                        opening_balance._clear_generated_records()

                    # If draft, do not hard delete — just cancel it
                    opening_balance.state = "cancel"

                raise ValidationError(
                    "Hard delete is not allowed. The record has been cancelled instead."
                )

        except Exception as e:
            _logger.error(f"unlink failed: {str(e)}")
            raise ValidationError(f"Delete failed: {str(e)}")


# ─────────────────────────────────────────────────────────────────────────────
# Opening Balance Line
# ─────────────────────────────────────────────────────────────────────────────


class SalesOpeningBalanceLine(models.Model):
    _name = "idil.sales.opening.balance.line"
    _description = "Sales Opening Balance Line"
    _order = "id desc"

    opening_balance_id = fields.Many2one(
        "idil.sales.opening.balance", string="Opening Balance", ondelete="cascade"
    )
    sales_person_id = fields.Many2one(
        "idil.sales.sales_personnel",
        string="Salesperson",
        required=True,
        domain=[("account_receivable_id", "!=", False)],
    )
    account_id = fields.Many2one(
        "idil.chart.account", string="Account", readonly=True, store=True
    )
    account_currency_id = fields.Many2one(
        "res.currency",
        string="Account Currency",
        related="account_id.currency_id",
        readonly=True,
        store=True,
    )
    amount = fields.Float(string="Opening Amount", required=True)

    # ─────────────────────────────────────────────────────────────────────────
    # onchange / constrains
    # ─────────────────────────────────────────────────────────────────────────

    @api.onchange("sales_person_id")
    def _onchange_sales_person_id(self):
        for line in self:
            if line.sales_person_id:
                line.account_id = line.sales_person_id.account_receivable_id.id
            else:
                line.account_id = False

    @api.constrains("account_id")
    def _check_account_id(self):
        for rec in self:
            if not rec.account_id:
                raise ValidationError(
                    "Please select a salesperson with a valid Receivable Account."
                )

    # ─────────────────────────────────────────────────────────────────────────
    # ORM overrides
    # ─────────────────────────────────────────────────────────────────────────

    @api.model
    def create(self, vals):
        """Always populate account_id from the salesperson if missing."""
        if not vals.get("account_id") and vals.get("sales_person_id"):
            salesperson = self.env["idil.sales.sales_personnel"].browse(
                vals["sales_person_id"]
            )
            vals["account_id"] = salesperson.account_receivable_id.id
        return super().create(vals)

    def unlink(self):
        """Delete a line and clean up all generated records linked to it."""
        try:
            with self.env.cr.savepoint():
                Receipt = self.env["idil.sales.receipt"]
                Transaction = self.env["idil.salesperson.transaction"]
                Booking = self.env["idil.transaction_booking"]

                # Gather receipt targets before deletion (FK may be gone after super().unlink())
                receipt_targets = []

                for line in self:
                    opening_balance = line.opening_balance_id

                    # 1. Prevent deletion if payment received
                    paid_receipt = Receipt.search(
                        [
                            ("sales_opening_balance_id", "=", opening_balance.id),
                            ("salesperson_id", "=", line.sales_person_id.id),
                            ("paid_amount", ">", 0),
                        ],
                        limit=1,
                    )
                    if paid_receipt:
                        raise ValidationError(
                            f"Cannot delete the line for '{line.sales_person_id.name}': "
                            "a payment has already been received."
                        )

                    # 2. Prevent deletion if an external transaction exists
                    external_txn = Transaction.search(
                        [
                            ("sales_person_id", "=", line.sales_person_id.id),
                            ("sales_opening_balance_id", "!=", opening_balance.id),
                            ("amount", ">", 0),
                        ],
                        limit=1,
                    )
                    if external_txn:
                        raise ValidationError(
                            f"Cannot delete the line for '{line.sales_person_id.name}': "
                            "another transaction already exists for this salesperson."
                        )

                    # 3. Remove booking + booking lines
                    booking = Booking.search(
                        [
                            ("sales_opening_balance_id", "=", opening_balance.id),
                            ("sales_person_id", "=", line.sales_person_id.id),
                        ],
                        limit=1,
                    )
                    if booking:
                        booking.booking_lines.unlink()
                        booking.unlink()

                    # 4. Remove salesperson transaction
                    txn = Transaction.search(
                        [
                            ("sales_opening_balance_id", "=", opening_balance.id),
                            ("sales_person_id", "=", line.sales_person_id.id),
                        ],
                        limit=1,
                    )
                    if txn:
                        txn.unlink()

                    # 5. Schedule receipt removal (done after super().unlink())
                    receipt_targets.append(
                        {
                            "salesperson_id": line.sales_person_id.id,
                            "opening_balance_id": opening_balance.id,
                        }
                    )

                # 6. Delete the opening balance lines
                res = super().unlink()

                # 7. Remove receipts after lines are gone
                for target in receipt_targets:
                    receipt = Receipt.search(
                        [
                            (
                                "sales_opening_balance_id",
                                "=",
                                target["opening_balance_id"],
                            ),
                            ("salesperson_id", "=", target["salesperson_id"]),
                        ],
                        limit=1,
                    )
                    if receipt:
                        receipt.unlink()

                return res

        except Exception as e:
            _logger.error(f"line unlink failed: {str(e)}")
            raise ValidationError(f"Delete failed: {str(e)}")
