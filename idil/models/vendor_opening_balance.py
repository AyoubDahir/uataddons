from odoo import models, fields, api
from odoo.exceptions import ValidationError, UserError
import logging

_logger = logging.getLogger(__name__)


class VendorOpeningBalance(models.Model):
    _name = "idil.vendor.opening.balance"
    _description = "Vendor Opening Balance"
    _order = "id desc"

    company_id = fields.Many2one(
        "res.company", default=lambda s: s.env.company, required=True
    )
    name = fields.Char(string="Reference", default="New", readonly=True, copy=False)
    date = fields.Date(
        string="Opening Date", default=fields.Date.context_today, required=True
    )
    state = fields.Selection(
        [("draft", "Draft"), ("confirmed", "Confirmed"), ("cancel", "Cancelled")],
        string="Status",
        default="draft",
        readonly=True,
    )
    line_ids = fields.One2many(
        "idil.vendor.opening.balance.line", "opening_balance_id", string="Lines"
    )
    internal_comment = fields.Text(string="Internal Comment")

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
    total_amount = fields.Float(
        string="Total Opening Amount",
        compute="_compute_total_amount",
        currency_field="currency_id",
        store=True,
        readonly=True,
    )

    # ── Audit / tracking fields ────────────────────────────────────────────────
    cancelled_by = fields.Many2one(
        "res.users", string="Cancelled By", readonly=True, copy=False
    )
    cancelled_date = fields.Datetime(string="Cancelled On", readonly=True, copy=False)
    reset_to_draft_by = fields.Many2one(
        "res.users", string="Reset to Draft By", readonly=True, copy=False
    )
    reset_to_draft_date = fields.Datetime(
        string="Reset to Draft On", readonly=True, copy=False
    )

    # ─────────────────────────────────────────────────────────────────────────
    # Computed fields
    # ─────────────────────────────────────────────────────────────────────────

    @api.depends("line_ids.amount")
    def _compute_total_amount(self):
        for rec in self:
            rec.total_amount = sum(line.amount for line in rec.line_ids)

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

    def _get_opening_balance_account(self):
        account = self.env["idil.chart.account"].search(
            [("name", "=", "Opening Balance Account")], limit=1
        )
        if not account:
            raise ValidationError(
                "Opening Balance Account not found. Please configure it."
            )
        if account.currency_id.name != "USD":
            raise ValidationError(
                f"The Opening Balance Account currency must be USD "
                f"(found '{account.currency_id.name}')."
            )
        return account

    def _get_trx_source(self):
        source = self.env["idil.transaction.source"].search(
            [("name", "=", "Vendor Opening Balance")], limit=1
        )
        if not source:
            raise ValidationError(
                'Transaction source "Vendor Opening Balance" not found.'
            )
        return source

    def _get_clearing_accounts(self, vendor_currency_id, equity_currency_id):
        """Return (vendor_clearing, equity_clearing) accounts for currency exchange."""
        vendor_clearing = self.env["idil.chart.account"].search(
            [
                ("name", "=", "Exchange Clearing Account"),
                ("currency_id", "=", vendor_currency_id),
            ],
            limit=1,
        )
        equity_clearing = self.env["idil.chart.account"].search(
            [
                ("name", "=", "Exchange Clearing Account"),
                ("currency_id", "=", equity_currency_id),
            ],
            limit=1,
        )
        if not vendor_clearing or not equity_clearing:
            raise ValidationError(
                "Exchange clearing accounts are required for currency conversion. "
                "Please configure them in the chart of accounts."
            )
        return vendor_clearing, equity_clearing

    def _validate_no_payments_block(self):
        """Raise if any vendor transaction has already been (partially) paid."""
        for line in self.line_ids:
            vendor_tx = self.env["idil.vendor_transaction"].search(
                [
                    ("vendor_id", "=", line.vendor_id.id),
                    ("transaction_booking_id.vendor_opening_balance_id", "=", line.id),
                    ("paid_amount", ">", 0),
                ],
                limit=1,
            )
            if vendor_tx:
                raise ValidationError(
                    f"Cannot modify opening balance for vendor '{line.vendor_id.name}': "
                    f"payment already received on transaction {vendor_tx.transaction_number}."
                )

    def _validate_no_blocking_records(self, line):
        """Block confirm if purchase orders or non-opening-balance vendor transactions exist."""
        purchase_orders = self.env["idil.purchase_order"].search(
            [("vendor_id", "=", line.vendor_id.id)]
        )
        vendor_transactions = self.env["idil.vendor_transaction"].search(
            [
                ("vendor_id", "=", line.vendor_id.id),
                ("reffno", "!=", "Opening Balance"),
                # Exclude transactions that belong to THIS opening balance
                ("transaction_booking_id.vendor_opening_balance_id", "!=", line.id),
            ]
        )
        if purchase_orders or vendor_transactions:
            msg = (
                f"You cannot create an opening balance for vendor '{line.vendor_id.name}' "
                "because there are already related records:\n"
            )
            if purchase_orders:
                msg += "\nPurchase Orders:\n"
                for po in purchase_orders:
                    msg += f"- PO: {po.name}   Date: {getattr(po, 'date_order', '')}\n"
            if vendor_transactions:
                msg += "\nVendor Transactions:\n"
                for vt in vendor_transactions:
                    msg += (
                        f"- Transaction: {vt.transaction_number}   Ref: {vt.reffno}\n"
                    )
            raise ValidationError(msg)

    # ─────────────────────────────────────────────────────────────────────────
    # Core booking logic — separated methods
    # ─────────────────────────────────────────────────────────────────────────

    def _clear_generated_records(self):
        """Delete all bookings, booking-lines and vendor transactions generated
        for every line on this opening balance."""
        for line in self.line_ids:
            bookings = self.env["idil.transaction_booking"].search(
                [("vendor_opening_balance_id", "=", line.id)]
            )
            for booking in bookings:
                # Remove linked vendor transactions first
                self.env["idil.vendor_transaction"].search(
                    [("transaction_booking_id", "=", booking.id)]
                ).unlink()
                booking.booking_lines.unlink()
                booking.unlink()

    def _create_booking_for_line(self, line, opening_balance_account, trx_source):
        """Create a transaction_booking for one vendor opening-balance line.

        • Same currency (vendor payable == USD / Opening Balance Account):
              2 booking lines
              DR  Opening Balance Account   (USD)
              CR  Vendor Payable            (USD)

        • Different currencies (vendor payable != USD):
              4 booking lines  (exchange flow)
              DR  Opening Balance Account   (USD)
              CR  Exchange Clearing         (USD)
              DR  Exchange Clearing         (vendor currency)
              CR  Vendor Payable            (vendor currency)
        """
        vendor_account = line.vendor_id.account_payable_id
        vendor_currency = vendor_account.currency_id
        same_currency = vendor_currency.name == "USD"

        rate = self.rate
        if not same_currency and rate <= 0:
            raise ValidationError(
                "Exchange rate must be greater than zero when currencies differ. "
                f"Please set a valid rate for currency '{self.currency_id.name}'."
            )

        cost_amount_usd = line.amount if same_currency else line.amount / rate

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
                "vendor_id": line.vendor_id.id,
                "vendor_opening_balance_id": line.id,
            }
        )

        desc_vendor = f"Opening Balance for {line.vendor_id.name}"

        if same_currency:
            # ── 2-line flow: no exchange needed ────────────────────────────────
            self.env["idil.transaction_bookingline"].create(
                [
                    # 1. DR Opening Balance Account (USD)
                    {
                        "transaction_booking_id": booking.id,
                        "vendor_opening_balance_id": line.id,
                        "account_number": opening_balance_account.id,
                        "transaction_type": "dr",
                        "dr_amount": cost_amount_usd,
                        "cr_amount": 0.0,
                        "transaction_date": self.date,
                        "description": desc_vendor,
                    },
                    # 2. CR Vendor Payable (USD)
                    {
                        "transaction_booking_id": booking.id,
                        "vendor_opening_balance_id": line.id,
                        "account_number": vendor_account.id,
                        "transaction_type": "cr",
                        "dr_amount": 0.0,
                        "cr_amount": line.amount,
                        "transaction_date": self.date,
                        "description": desc_vendor,
                    },
                ]
            )
        else:
            # ── 4-line flow: currency exchange required ─────────────────────────
            vendor_clearing, equity_clearing = self._get_clearing_accounts(
                vendor_currency.id,
                opening_balance_account.currency_id.id,
            )
            self.env["idil.transaction_bookingline"].create(
                [
                    # 1. DR Opening Balance Account (USD)
                    {
                        "transaction_booking_id": booking.id,
                        "vendor_opening_balance_id": line.id,
                        "account_number": opening_balance_account.id,
                        "transaction_type": "dr",
                        "dr_amount": cost_amount_usd,
                        "cr_amount": 0.0,
                        "transaction_date": self.date,
                        "description": desc_vendor,
                    },
                    # 2. CR Exchange Clearing (USD)
                    {
                        "transaction_booking_id": booking.id,
                        "vendor_opening_balance_id": line.id,
                        "account_number": equity_clearing.id,
                        "transaction_type": "cr",
                        "dr_amount": 0.0,
                        "cr_amount": cost_amount_usd,
                        "transaction_date": self.date,
                        "description": f"Exchange Clearing (USD) for {line.vendor_id.name}",
                    },
                    # 3. DR Exchange Clearing (vendor currency)
                    {
                        "transaction_booking_id": booking.id,
                        "vendor_opening_balance_id": line.id,
                        "account_number": vendor_clearing.id,
                        "transaction_type": "dr",
                        "dr_amount": line.amount,
                        "cr_amount": 0.0,
                        "transaction_date": self.date,
                        "description": f"Exchange Clearing ({vendor_currency.name}) for {line.vendor_id.name}",
                    },
                    # 4. CR Vendor Payable (vendor currency)
                    {
                        "transaction_booking_id": booking.id,
                        "vendor_opening_balance_id": line.id,
                        "account_number": vendor_account.id,
                        "transaction_type": "cr",
                        "dr_amount": 0.0,
                        "cr_amount": line.amount,
                        "transaction_date": self.date,
                        "description": desc_vendor,
                    },
                ]
            )
        return booking

    def _create_vendor_transaction_for_line(self, line, booking):
        """Create an idil.vendor_transaction for one opening-balance line."""
        return self.env["idil.vendor_transaction"].create(
            {
                "order_number": f"VOB-{line.id}",
                "transaction_number": booking.transaction_number,
                "transaction_date": self.date,
                "vendor_id": line.vendor_id.id,
                "amount": line.amount,
                "remaining_amount": line.amount,
                "paid_amount": 0.0,
                "payment_method": "ap",
                "reffno": self.name,
                "transaction_booking_id": booking.id,
                "payment_status": "pending",
            }
        )

    def _generate_all_records(self):
        """(Re-)generate bookings, booking-lines and vendor transactions for
        every line.  Call after _clear_generated_records()."""
        opening_balance_account = self._get_opening_balance_account()
        trx_source = self._get_trx_source()

        for line in self.line_ids:
            if not line.vendor_id.account_payable_id:
                raise ValidationError(
                    f"Vendor '{line.vendor_id.name}' does not have a payable account configured."
                )
            # Block if conflicting external records exist
            self._validate_no_blocking_records(line)

            booking = self._create_booking_for_line(
                line, opening_balance_account, trx_source
            )
            self._create_vendor_transaction_for_line(line, booking)

            # Update vendor's opening_balance field
            line.vendor_id.opening_balance += line.amount

    # ─────────────────────────────────────────────────────────────────────────
    # Action buttons
    # ─────────────────────────────────────────────────────────────────────────

    def action_confirm(self):
        """Validate, generate all accounting records and mark as Confirmed."""
        for record in self:
            if record.state == "confirmed":
                raise UserError("This opening balance is already confirmed.")
            if record.state == "cancel":
                raise UserError("A cancelled opening balance cannot be confirmed.")
            if not record.line_ids:
                raise ValidationError(
                    "Please add at least one vendor line before confirming."
                )
            # Duplicate check across other non-cancelled documents
            for line in record.line_ids:
                existing = self.env["idil.vendor.opening.balance.line"].search(
                    [
                        ("vendor_id", "=", line.vendor_id.id),
                        ("opening_balance_id.state", "!=", "cancel"),
                        ("opening_balance_id", "!=", record.id),
                    ],
                    limit=1,
                )
                if existing:
                    raise ValidationError(
                        f"Vendor '{line.vendor_id.name}' already has a confirmed "
                        "opening balance entry. You cannot create another one."
                    )

            try:
                with self.env.cr.savepoint():
                    # Clear any previously generated records (idempotent)
                    record._clear_generated_records()
                    # Recreate everything from current lines
                    record._generate_all_records()
                    # Mark as confirmed
                    super(VendorOpeningBalance, record).write({"state": "confirmed"})
            except Exception as e:
                _logger.error(f"action_confirm failed: {str(e)}")
                raise ValidationError(f"Confirm failed: {str(e)}")

    def action_cancel(self):
        """Cancel the opening balance.

        Only allowed when the record is in Draft.
        Records who cancelled and at what time.
        """
        for record in self:
            if record.state == "cancel":
                raise UserError("Already cancelled.")
            if record.state == "confirmed":
                raise UserError(
                    "Only Draft records can be cancelled. "
                    "Please use the 'Reset to Draft' button first."
                )
            try:
                with self.env.cr.savepoint():
                    super(VendorOpeningBalance, record).write(
                        {
                            "state": "cancel",
                            "cancelled_by": self.env.user.id,
                            "cancelled_date": fields.Datetime.now(),
                        }
                    )
            except Exception as e:
                _logger.error(f"action_cancel failed: {str(e)}")
                raise ValidationError(f"Cancel failed: {str(e)}")

    def action_reset_to_draft(self):
        """Reset a confirmed or cancelled record back to Draft.

        Clears all generated records so the record can be freely edited
        and re-confirmed.  Blocked if any payment has already been received.
        Records who reset and at what time.
        """
        for record in self:
            if record.state == "draft":
                raise UserError("Record is already in Draft.")
            record._validate_no_payments_block()
            try:
                with self.env.cr.savepoint():
                    # Reset vendor opening_balance counters before clearing
                    if record.state == "confirmed":
                        for line in record.line_ids:
                            line.vendor_id.opening_balance -= line.amount
                    record._clear_generated_records()
                    # Use super() to bypass the write() override
                    super(VendorOpeningBalance, record).write(
                        {
                            "state": "draft",
                            "reset_to_draft_by": self.env.user.id,
                            "reset_to_draft_date": fields.Datetime.now(),
                        }
                    )
            except Exception as e:
                _logger.error(f"action_reset_to_draft failed: {str(e)}")
                raise ValidationError(f"Reset to Draft failed: {str(e)}")

    # ─────────────────────────────────────────────────────────────────────────
    # ORM overrides
    # ─────────────────────────────────────────────────────────────────────────

    @api.model
    def create(self, vals):
        """Save record in DRAFT.  No bookings / vendor transactions yet."""
        try:
            with self.env.cr.savepoint():
                # Duplicate vendor check at create time
                for command in vals.get("line_ids", []):
                    if command[0] == 0:
                        vendor_id = command[2].get("vendor_id")
                        if vendor_id:
                            existing = self.env[
                                "idil.vendor.opening.balance.line"
                            ].search(
                                [
                                    ("vendor_id", "=", vendor_id),
                                    ("opening_balance_id.state", "!=", "cancel"),
                                ],
                                limit=1,
                            )
                            if existing:
                                raise ValidationError(
                                    f"Vendor '{existing.vendor_id.name}' already has an opening balance "
                                    f"of {existing.amount:.2f} in record '{existing.opening_balance_id.name}'. "
                                    "You cannot create another one."
                                )

                # Assign sequence
                if vals.get("name", "New") == "New":
                    vals["name"] = (
                        self.env["ir.sequence"].next_by_code(
                            "idil.vendor.opening.balance"
                        )
                        or "New"
                    )

                # Always start in draft
                vals["state"] = "draft"
                return super().create(vals)

        except Exception as e:
            _logger.error(f"create failed: {str(e)}")
            raise ValidationError(f"Create failed: {str(e)}")

    def write(self, vals):
        """Update the record.

        • Draft      → plain update only.  No generated-record changes
                       (those happen on Confirm).
        • Non-draft  → blocked.  User must press 'Reset to Draft' first.

        State transitions triggered by action buttons use super().write()
        directly and bypass this guard via the internal context flag
        ``_bypass_write_guard``.
        """
        # State-transition writes from action buttons bypass the guard
        if self.env.context.get("_bypass_write_guard"):
            return super().write(vals)

        # Block editing on non-draft records
        non_draft = self.filtered(lambda r: r.state != "draft")
        if non_draft:
            # Allow through if only internal/system fields are being written
            # (e.g. computed field recomputation, state changes from buttons)
            user_facing_keys = set(vals.keys()) - {
                "state",
                "cancelled_by",
                "cancelled_date",
                "reset_to_draft_by",
                "reset_to_draft_date",
                "__last_update",
            }
            if user_facing_keys:
                raise UserError(
                    "This record is not in Draft status and cannot be edited directly.\n"
                    "Please use the 'Reset to Draft' button first, then make your "
                    "changes and confirm again."
                )

        try:
            with self.env.cr.savepoint():
                return super().write(vals)
        except Exception as e:
            _logger.error(f"write failed: {str(e)}")
            raise ValidationError(f"Write failed: {str(e)}")

    def unlink(self):
        """Hard deletion is disabled.  Use Cancel to deactivate a record."""
        raise UserError(
            "Permanent deletion is not allowed.\n"
            "To remove an opening balance, please use the 'Cancel' button instead. "
            "Cancelled records are kept for audit purposes."
        )


# ─────────────────────────────────────────────────────────────────────────────
# Vendor Opening Balance Line
# ─────────────────────────────────────────────────────────────────────────────


class VendorOpeningBalanceLine(models.Model):
    _name = "idil.vendor.opening.balance.line"
    _description = "Vendor Opening Balance Line"
    _order = "id desc"

    opening_balance_id = fields.Many2one(
        "idil.vendor.opening.balance", string="Opening Balance", ondelete="cascade"
    )
    vendor_id = fields.Many2one(
        "idil.vendor.registration",
        string="Vendor",
        required=True,
        domain=[("account_payable_id", "!=", False)],
    )
    account_id = fields.Many2one(
        "idil.chart.account", string="Account", readonly=True, store=True
    )
    amount = fields.Float(string="Opening Amount", required=True)
    account_currency_id = fields.Many2one(
        "res.currency",
        string="Account Currency",
        related="account_id.currency_id",
        store=True,
        readonly=True,
    )

    # ─────────────────────────────────────────────────────────────────────────
    # onchange / constrains
    # ─────────────────────────────────────────────────────────────────────────

    @api.onchange("vendor_id")
    def _onchange_vendor_id(self):
        for line in self:
            if line.vendor_id:
                line.account_id = line.vendor_id.account_payable_id.id
            else:
                line.account_id = False

    @api.constrains("account_id")
    def _check_account_id(self):
        for rec in self:
            if not rec.account_id:
                raise ValidationError(
                    "Please select a vendor with a valid Payable Account."
                )

    # ─────────────────────────────────────────────────────────────────────────
    # ORM overrides
    # ─────────────────────────────────────────────────────────────────────────

    @api.model
    def create(self, vals):
        """Auto-populate account_id from vendor if missing."""
        vendor_id = vals.get("vendor_id")
        if vendor_id:
            existing = self.env["idil.vendor.opening.balance.line"].search(
                [
                    ("vendor_id", "=", vendor_id),
                    ("opening_balance_id.state", "!=", "cancel"),
                ],
                limit=1,
            )
            if existing:
                raise ValidationError(
                    f"Vendor '{existing.vendor_id.name}' already has an opening balance "
                    f"of {existing.amount:.2f} in record '{existing.opening_balance_id.name}'. "
                    "You cannot create another one."
                )
        if not vals.get("account_id") and vendor_id:
            vendor = self.env["idil.vendor.registration"].browse(vendor_id)
            vals["account_id"] = vendor.account_payable_id.id
        return super().create(vals)

    def unlink(self):
        """Delete a line and clean up all generated records linked to it."""
        try:
            with self.env.cr.savepoint():
                for line in self:
                    opening_balance = line.opening_balance_id

                    # 1. Block if vendor transaction has been paid
                    vendor_tx = self.env["idil.vendor_transaction"].search(
                        [
                            ("vendor_id", "=", line.vendor_id.id),
                            (
                                "transaction_booking_id.vendor_opening_balance_id",
                                "=",
                                line.id,
                            ),
                            ("paid_amount", ">", 0),
                        ],
                        limit=1,
                    )
                    if vendor_tx:
                        raise ValidationError(
                            f"Cannot delete the line for vendor '{line.vendor_id.name}': "
                            f"payment already received on transaction {vendor_tx.transaction_number}."
                        )

                    # 2. Clean up bookings + vendor transactions for this line
                    bookings = self.env["idil.transaction_booking"].search(
                        [("vendor_opening_balance_id", "=", line.id)]
                    )
                    for booking in bookings:
                        self.env["idil.vendor_transaction"].search(
                            [("transaction_booking_id", "=", booking.id)]
                        ).unlink()
                        booking.booking_lines.unlink()
                        booking.unlink()

                    # 3. Revert vendor opening_balance counter if confirmed
                    if opening_balance.state == "confirmed":
                        line.vendor_id.opening_balance -= line.amount

                return super().unlink()

        except Exception as e:
            _logger.error(f"line unlink failed: {str(e)}")
            raise ValidationError(f"Delete failed: {str(e)}")
