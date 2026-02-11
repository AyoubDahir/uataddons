from venv import logger
from odoo import api, fields, models, _

from odoo.exceptions import ValidationError


class IdilItemOpeningBalance(models.Model):
    _name = "idil.item.opening.balance"
    _description = "Multi-Item Opening Balance"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "id desc"

    company_id = fields.Many2one(
        "res.company", default=lambda s: s.env.company, required=True
    )

    name = fields.Char(string="Reference", readonly=True, default="New")

    source_warehouse_id = fields.Many2one(
        "idil.warehouse",
        string="🏬 Warehouse",
        required=True,
        tracking=True,
    )

    source_location_id = fields.Many2one(
        "idil.warehouse.location",
        string="📌 Location",
        required=True,
        tracking=True,
        domain="[('warehouse_id', '=', source_warehouse_id), ('active', '=', True)]",
    )

    date = fields.Date(string="Date", default=fields.Date.today, required=True)
    state = fields.Selection(
        [("draft", "Draft"), ("confirmed", "Confirmed")],
        default="confirmed",
        tracking=True,
    )
    note = fields.Text(string="Note")
    line_ids = fields.One2many(
        "idil.item.opening.balance.line",
        "opening_balance_id",
        string="Items",
        copy=True,
    )
    total_amount = fields.Float(
        string="Total Amount", compute="_compute_total_amount", store=True
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
        compute="_compute_exchange_rate",
        store=True,
        readonly=True,
    )

    @api.constrains("company_id", "source_warehouse_id", "source_location_id", "state")
    def _check_unique_opening_balance_per_location(self):
        """
        Only ONE confirmed opening balance is allowed per Company + Warehouse + Location.
        """
        for rec in self:
            if (
                not rec.company_id
                or not rec.source_warehouse_id
                or not rec.source_location_id
            ):
                continue

            # ✅ Apply rule only when confirmed (recommended)
            if rec.state != "confirmed":
                continue

            domain = [
                ("id", "!=", rec.id),
                ("company_id", "=", rec.company_id.id),
                ("source_warehouse_id", "=", rec.source_warehouse_id.id),
                ("source_location_id", "=", rec.source_location_id.id),
                ("state", "=", "confirmed"),
            ]

            exists = self.search_count(domain)
            if exists:
                raise ValidationError(
                    _(
                        "Opening Balance already exists for:\n"
                        "Company: %(company)s\n"
                        "Warehouse: %(wh)s\n"
                        "Location: %(loc)s\n\n"
                        "Only ONE confirmed Opening Balance is allowed per Warehouse/Location."
                    )
                    % {
                        "company": rec.company_id.display_name,
                        "wh": rec.source_warehouse_id.display_name,
                        "loc": rec.source_location_id.display_name,
                    }
                )

    @api.depends("currency_id", "date", "company_id")
    def _compute_exchange_rate(self):
        Rate = self.env["res.currency.rate"].sudo()
        for order in self:
            order.rate = 0.0
            if not order.currency_id:
                continue

            # Use the order's date; fallback to today if missing
            doc_date = (
                fields.Date.to_date(order.date) if order.date else fields.Date.today()
            )

            # Get latest rate on or before the doc_date, preferring the order's company, then global (company_id False)
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

    @api.depends("line_ids.total")
    def _compute_total_amount(self):
        for rec in self:
            rec.total_amount = sum(line.total for line in rec.line_ids)

    def action_populate_zero_qty_items(self):
        """
        Fills the line_ids one2many in the UI with all zero-qty items,
        SKIPPING any already-present lines.
        DOES NOT save records to the DB until the main form is saved.
        """
        all_zero_items = self.env["idil.item"].search([("quantity", "=", 0)])
        existing_item_ids = self.line_ids.mapped("item_id").ids
        new_lines = []
        for item in all_zero_items:
            if item.id in existing_item_ids:
                continue
            new_lines.append(
                (
                    0,
                    0,
                    {
                        "item_id": item.id,
                        "quantity": 25,
                        "cost_price": item.cost_price,
                    },
                )
            )
        # Append new zero-qty lines to existing ones
        self.line_ids = (
            list(
                self.line_ids._origin.ids
                and [(4, id) for id in self.line_ids._origin.ids]
                or []
            )
            + new_lines
        )

    # Above: add new, retain any already present (to avoid removing manually entered)

    def _validate_before_post(self):
        """Common pre-posting checks. Raises ValidationError with a clear list."""
        for rec in self:

            # Required source
            source = self.env["idil.transaction.source"].search(
                [("name", "=", "Inventory Opening Balance")], limit=1
            )
            if not source:
                raise ValidationError(
                    _("Transaction Source 'Inventory Opening Balance' not found.")
                )

            # Equity (Opening Balance) account
            # Keep your original search behavior; fall back without currency if needed
            EquityAccount = self.env["idil.chart.account"].search(
                [("name", "=", "Opening Balance Account")], limit=1
            )
            if not EquityAccount:
                raise ValidationError(
                    _("Chart of Account 'Opening Balance Account' not found.")
                )

            # Collect issues
            missing_accounts = []
            bad_qty = []
            bad_cost = []

            for ln in rec.line_ids:
                if not ln.item_id:
                    missing_accounts.append(_("A line has no Item selected."))
                    continue

                # Business sanity checks
                if ln.quantity is None or ln.quantity <= 0:
                    bad_qty.append(f"{ln.item_id.display_name} (qty={ln.quantity})")
                if ln.cost_price is None or ln.cost_price < 0:
                    bad_cost.append(f"{ln.item_id.display_name} (cost={ln.cost_price})")

                # The key guard: asset account must exist
                if not ln.item_id.asset_account_id:
                    missing_accounts.append(ln.item_id.display_name)

            errors = []
            if missing_accounts:
                errors.append(
                    _("- Missing asset account on items:\n  • ")
                    + "\n  • ".join(sorted(set(missing_accounts)))
                    + _("\n  Set 'Asset Account' on each Item, then try again.")
                )
            if bad_qty:
                errors.append(
                    _("- Invalid quantity (must be > 0) for:\n  • ")
                    + "\n  • ".join(sorted(set(bad_qty)))
                )
            if bad_cost:
                errors.append(
                    _("- Invalid cost price (must be ≥ 0) for:\n  • ")
                    + "\n  • ".join(sorted(set(bad_cost)))
                )

            if errors:
                raise ValidationError(
                    _("Cannot post Opening Balance:\n\n") + "\n\n".join(errors)
                )

            # Optional: warn on zero exchange rate
            # (Block if you want strict behavior)
            if rec.rate is None:
                raise ValidationError(
                    _("Exchange rate is not computed. Please save the document first.")
                )
            # if rec.rate == 0:
            #     raise ValidationError(_("Exchange rate is 0. Set a valid rate before posting."))

            # Return validated reusable references
            return {
                "source": source,
                "equity_account": EquityAccount,
            }

    def confirm_opening_balance(self):
        try:
            with self.env.cr.savepoint():
                self._validate_before_post()

                TransactionBooking = self.env["idil.transaction_booking"]
                TransactionSource = self.env["idil.transaction.source"]
                ItemMovement = self.env["idil.item.movement"]
                ChartAccount = self.env["idil.chart.account"]

                EquityAccount = ChartAccount.search(
                    [("name", "=", "Opening Balance Account")], limit=1
                )
                if not EquityAccount:
                    raise ValidationError(
                        "Opening Balance Account not found. Please configure it."
                    )

                source = TransactionSource.search(
                    [("name", "=", "Inventory Opening Balance")], limit=1
                )
                if not source:
                    raise ValidationError(
                        "Transaction Source 'Inventory Opening Balance' not found."
                    )

                for line in self.line_ids:
                    item = line.item_id

                    # Validate stock is not already positive
                    if item.quantity != 0:
                        raise ValidationError(
                            f"Cannot create opening balance. Item '{item.name}' already has stock: {item.quantity}"
                        )

                    # Update stock
                    item.quantity = line.quantity

                    # Calculate amount in item's currency
                    amount = line.quantity * line.cost_price

                    # Determine currencies (use account currency)
                    item_currency = item.asset_account_id.currency_id
                    equity_currency = EquityAccount.currency_id

                    # Create transaction booking (header)
                    trx = TransactionBooking.create(
                        {
                            "transaction_number": self.env["ir.sequence"].next_by_code(
                                "idil.transaction_booking"
                            ),
                            "reffno": item.name,
                            "rate": self.rate or 1,
                            "item_opening_balance_id": self.id,
                            "trx_date": self.date,
                            "amount": amount,
                            "amount_paid": amount,
                            "remaining_amount": 0,
                            "payment_status": "paid",
                            "payment_method": "other",
                            "trx_source_id": source.id,
                        }
                    )

                    booking_lines_vals = []

                    # ✅ Case 1: SAME currency -> 2 lines only (NO clearing)
                    if item_currency.id == equity_currency.id:
                        booking_lines_vals = [
                            # 1) DR Asset
                            {
                                "transaction_booking_id": trx.id,
                                "item_opening_balance_id": self.id,
                                "description": f"Opening Balance for {item.name}",
                                "item_id": item.id,
                                "account_number": item.asset_account_id.id,
                                "transaction_type": "dr",
                                "dr_amount": amount,
                                "cr_amount": 0,
                                "rate": self.rate or 1,
                                "transaction_date": self.date,
                            },
                            # 2) CR Opening Balance / Equity
                            {
                                "transaction_booking_id": trx.id,
                                "item_opening_balance_id": self.id,
                                "description": f"Opening Balance for {item.name}",
                                "item_id": item.id,
                                "account_number": EquityAccount.id,
                                "transaction_type": "cr",
                                "dr_amount": 0,
                                "cr_amount": amount,
                                "rate": self.rate or 1,
                                "transaction_date": self.date,
                            },
                        ]

                    # ✅ Case 2: DIFFERENT currencies -> 4 lines with clearing
                    else:
                        if not self.rate or self.rate <= 0:
                            raise ValidationError(
                                "Exchange rate is required for currency conversion."
                            )

                        # Convert amount to equity currency
                        if item_currency.name == "SL" and equity_currency.name == "USD":
                            amount_for_equity = amount / self.rate
                        elif (
                            item_currency.name == "USD" and equity_currency.name == "SL"
                        ):
                            amount_for_equity = amount * self.rate
                        else:
                            raise ValidationError(
                                f"Unhandled conversion from {item_currency.name} to {equity_currency.name}."
                            )

                        # Find clearing accounts for both currencies
                        source_clearing_account = ChartAccount.search(
                            [
                                ("name", "=", "Exchange Clearing Account"),
                                ("currency_id", "=", item_currency.id),
                            ],
                            limit=1,
                        )
                        target_clearing_account = ChartAccount.search(
                            [
                                ("name", "=", "Exchange Clearing Account"),
                                ("currency_id", "=", equity_currency.id),
                            ],
                            limit=1,
                        )
                        if not source_clearing_account or not target_clearing_account:
                            raise ValidationError(
                                "Exchange Clearing Accounts must exist for both the item and equity account currencies."
                            )

                        booking_lines_vals = [
                            # 1) DR Asset (item currency)
                            {
                                "transaction_booking_id": trx.id,
                                "item_opening_balance_id": self.id,
                                "description": f"Opening Balance for {item.name}",
                                "item_id": item.id,
                                "account_number": item.asset_account_id.id,
                                "transaction_type": "dr",
                                "dr_amount": amount,
                                "cr_amount": 0,
                                "rate": self.rate,
                                "transaction_date": self.date,
                            },
                            # 2) CR Source Clearing (item currency)
                            {
                                "transaction_booking_id": trx.id,
                                "item_opening_balance_id": self.id,
                                "description": f"Opening Balance - Source Clearing for {item.name}",
                                "item_id": item.id,
                                "account_number": source_clearing_account.id,
                                "transaction_type": "cr",
                                "dr_amount": 0,
                                "cr_amount": amount,
                                "rate": self.rate,
                                "transaction_date": self.date,
                            },
                            # 3) DR Target Clearing (equity currency)
                            {
                                "transaction_booking_id": trx.id,
                                "item_opening_balance_id": self.id,
                                "description": f"Opening Balance - Target Clearing for {item.name}",
                                "item_id": item.id,
                                "account_number": target_clearing_account.id,
                                "transaction_type": "dr",
                                "dr_amount": amount_for_equity,
                                "cr_amount": 0,
                                "rate": self.rate,
                                "transaction_date": self.date,
                            },
                            # 4) CR Opening Balance (equity currency)
                            {
                                "transaction_booking_id": trx.id,
                                "item_opening_balance_id": self.id,
                                "description": f"Opening Balance for {item.name}",
                                "item_id": item.id,
                                "account_number": EquityAccount.id,
                                "transaction_type": "cr",
                                "cr_amount": amount_for_equity,
                                "dr_amount": 0,
                                "rate": self.rate,
                                "transaction_date": self.date,
                            },
                        ]

                    # Create booking lines
                    trx.booking_lines.create(booking_lines_vals)

                    # Create movement log
                    ItemMovement.create(
                        {
                            "item_id": item.id,
                            "transaction_number": self.name,
                            "item_opening_balance_id": self.id,
                            "date": self.date,
                            "quantity": line.quantity,
                            "source": f"Opening Balance Inventory for Item {item.name}",
                            "destination": "Inventory",
                            "movement_type": "in",
                            "related_document": f"idil.item.opening.balance.line,{line.id}",
                            "source_warehouse_id": self.source_warehouse_id.id,
                            "source_location_id": self.source_location_id.id,
                        }
                    )

                # Update state to confirmed
                self.state = "confirmed"

        except Exception as e:
            logger.error(f"transaction failed: {str(e)}")
            raise ValidationError(f"Transaction failed: {str(e)}")

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", "New") == "New":
                vals["name"] = self.env["ir.sequence"].next_by_code(
                    "idil.item.opening.balance"
                )
        records = super().create(vals_list)
        for record in records:
            if record.state == "confirmed":
                record.confirm_opening_balance()
        return records

    def write(self, vals):
        try:
            with self.env.cr.savepoint():
                TransactionBooking = self.env["idil.transaction_booking"]
                ItemMovement = self.env["idil.item.movement"]

                for record in self:
                    # Revert stock
                    for line in record.line_ids:
                        line.item_id.quantity -= line.quantity

                    # Delete related bookings
                    trx_to_delete = TransactionBooking.search(
                        [("item_opening_balance_id", "=", record.id)]
                    )
                    trx_to_delete.booking_lines.unlink()
                    trx_to_delete.unlink()

                    # Delete related item movements
                    movement_to_delete = ItemMovement.search(
                        [("item_opening_balance_id", "=", record.id)]
                    )
                    movement_to_delete.unlink()

                # Write new values (lines, date, etc.)
                result = super(IdilItemOpeningBalance, self).write(vals)

                # Rebuild all booking/stock/movement logic freshly
                for record in self:
                    record._rebuild_confirmed_balance()

                return result
        except Exception as e:
            logger.error(f"transaction failed: {str(e)}")
            raise ValidationError(f"Transaction failed: {str(e)}")

    def _rebuild_confirmed_balance(self):
        try:
            with self.env.cr.savepoint():
                TransactionBooking = self.env["idil.transaction_booking"]
                TransactionSource = self.env["idil.transaction.source"]
                ItemMovement = self.env["idil.item.movement"]
                ChartAccount = self.env["idil.chart.account"]

                EquityAccount = ChartAccount.search(
                    [("name", "=", "Opening Balance Account")],
                    limit=1,
                )
                if not EquityAccount:
                    raise ValidationError(
                        "Opening Balance Account not found. Please configure it."
                    )

                source = TransactionSource.search(
                    [("name", "=", "Inventory Opening Balance")], limit=1
                )
                if not source:
                    raise ValidationError(
                        "Transaction Source 'Inventory Opening Balance' not found."
                    )

                for line in self.line_ids:
                    item = line.item_id

                    # Update stock
                    item.quantity += line.quantity

                    # Amount in item/account currency
                    amount = line.quantity * line.cost_price

                    # ✅ Use SAME currency logic as confirm_opening_balance
                    item_currency = item.asset_account_id.currency_id
                    equity_currency = EquityAccount.currency_id

                    # Create booking header
                    trx = TransactionBooking.create(
                        {
                            "transaction_number": self.env["ir.sequence"].next_by_code(
                                "idil.transaction_booking"
                            ),
                            "rate": self.rate or 1,
                            "reffno": item.name,
                            "item_opening_balance_id": self.id,
                            "trx_date": self.date,
                            "amount": amount,
                            "amount_paid": amount,
                            "remaining_amount": 0,
                            "payment_status": "paid",
                            "payment_method": "other",
                            "trx_source_id": source.id,
                        }
                    )

                    # ✅ SAME currency -> 2 lines only
                    if item_currency.id == equity_currency.id:
                        trx.booking_lines.create(
                            [
                                # 1) DR Asset
                                {
                                    "transaction_booking_id": trx.id,
                                    "item_opening_balance_id": self.id,
                                    "description": f"Opening Balance for {item.name}",
                                    "item_id": item.id,
                                    "account_number": item.asset_account_id.id,
                                    "transaction_type": "dr",
                                    "dr_amount": amount,
                                    "cr_amount": 0,
                                    "rate": self.rate or 1,
                                    "transaction_date": self.date,
                                },
                                # 2) CR Opening Balance / Equity
                                {
                                    "transaction_booking_id": trx.id,
                                    "item_opening_balance_id": self.id,
                                    "description": f"Opening Balance for {item.name}",
                                    "item_id": item.id,
                                    "account_number": EquityAccount.id,
                                    "transaction_type": "cr",
                                    "dr_amount": 0,
                                    "cr_amount": amount,
                                    "rate": self.rate or 1,
                                    "transaction_date": self.date,
                                },
                            ]
                        )

                    # ✅ DIFFERENT currencies -> 4 lines with clearing
                    else:
                        if not self.rate or self.rate <= 0:
                            raise ValidationError(
                                "Exchange rate is required for currency conversion."
                            )

                        # Convert to equity currency
                        if item_currency.name == "SL" and equity_currency.name == "USD":
                            amount_for_equity = amount / self.rate
                        elif (
                            item_currency.name == "USD" and equity_currency.name == "SL"
                        ):
                            amount_for_equity = amount * self.rate
                        else:
                            raise ValidationError(
                                f"Unhandled conversion from {item_currency.name} to {equity_currency.name}."
                            )

                        source_clearing_account = ChartAccount.search(
                            [
                                ("name", "=", "Exchange Clearing Account"),
                                ("currency_id", "=", item_currency.id),
                            ],
                            limit=1,
                        )
                        target_clearing_account = ChartAccount.search(
                            [
                                ("name", "=", "Exchange Clearing Account"),
                                ("currency_id", "=", equity_currency.id),
                            ],
                            limit=1,
                        )
                        if not source_clearing_account or not target_clearing_account:
                            raise ValidationError(
                                "Exchange Clearing Accounts must exist for both the item and equity account currencies."
                            )

                        trx.booking_lines.create(
                            [
                                # 1) DR Asset (item currency)
                                {
                                    "transaction_booking_id": trx.id,
                                    "item_opening_balance_id": self.id,
                                    "description": f"Opening Balance for {item.name}",
                                    "item_id": item.id,
                                    "account_number": item.asset_account_id.id,
                                    "transaction_type": "dr",
                                    "dr_amount": amount,
                                    "cr_amount": 0,
                                    "rate": self.rate,
                                    "transaction_date": self.date,
                                },
                                # 2) CR Source Clearing (item currency)
                                {
                                    "transaction_booking_id": trx.id,
                                    "item_opening_balance_id": self.id,
                                    "description": f"Opening Balance - Source Clearing for {item.name}",
                                    "item_id": item.id,
                                    "account_number": source_clearing_account.id,
                                    "transaction_type": "cr",
                                    "dr_amount": 0,
                                    "cr_amount": amount,
                                    "rate": self.rate,
                                    "transaction_date": self.date,
                                },
                                # 3) DR Target Clearing (equity currency)
                                {
                                    "transaction_booking_id": trx.id,
                                    "item_opening_balance_id": self.id,
                                    "description": f"Opening Balance - Target Clearing for {item.name}",
                                    "item_id": item.id,
                                    "account_number": target_clearing_account.id,
                                    "transaction_type": "dr",
                                    "dr_amount": amount_for_equity,
                                    "cr_amount": 0,
                                    "rate": self.rate,
                                    "transaction_date": self.date,
                                },
                                # 4) CR Opening Balance (equity currency)
                                {
                                    "transaction_booking_id": trx.id,
                                    "item_opening_balance_id": self.id,
                                    "description": f"Opening Balance for {item.name}",
                                    "item_id": item.id,
                                    "account_number": EquityAccount.id,
                                    "transaction_type": "cr",
                                    "dr_amount": 0,
                                    "cr_amount": amount_for_equity,
                                    "rate": self.rate,
                                    "transaction_date": self.date,
                                },
                            ]
                        )

                    # Movement
                    ItemMovement.create(
                        {
                            "item_id": item.id,
                            "item_opening_balance_id": self.id,
                            "transaction_number": self.name,
                            "date": self.date,
                            "quantity": line.quantity,
                            "source": f"Opening Balance Inventory for Item {item.name}",
                            "destination": "Inventory",
                            "movement_type": "in",
                            "related_document": f"idil.item.opening.balance.line,{line.id}",
                            "source_warehouse_id": self.source_warehouse_id.id,
                            "source_location_id": self.source_location_id.id,
                        }
                    )

        except Exception as e:
            logger.error(f"transaction failed: {str(e)}")
            raise ValidationError(f"Transaction failed: {str(e)}")

    def unlink(self):
        try:
            with self.env.cr.savepoint():
                TransactionBooking = self.env["idil.transaction_booking"]
                ItemMovement = self.env["idil.item.movement"]

                for record in self:
                    # Revert item stock

                    for line in record.line_ids:
                        item = line.item_id
                        if item.quantity < line.quantity:
                            raise ValidationError(
                                f"Cannot delete opening balance for item '{item.name}' because its current stock ({item.quantity}) is less than the opening balance quantity ({line.quantity}). "
                                "This means the item has already been used in manufacturing or other transactions. "
                                "To proceed, you must first delete the related manufacturing or stock usage records that consumed this item."
                            )

                    for line in record.line_ids:
                        line.item_id.quantity -= line.quantity

                    # Delete related booking lines and bookings
                    trx_to_delete = TransactionBooking.search(
                        [("item_opening_balance_id", "=", record.id)]
                    )
                    trx_to_delete.booking_lines.unlink()
                    trx_to_delete.unlink()

                    # Delete related item movements
                    movement_to_delete = ItemMovement.search(
                        [("item_opening_balance_id", "=", record.id)]
                    )
                    movement_to_delete.unlink()

                return super(IdilItemOpeningBalance, self).unlink()
        except Exception as e:
            logger.error(f"transaction failed: {str(e)}")
            raise ValidationError(f"Transaction failed: {str(e)}")


class IdilItemOpeningBalanceLine(models.Model):
    _name = "idil.item.opening.balance.line"
    _description = "Opening Balance Line"
    _order = "id desc"

    opening_balance_id = fields.Many2one(
        "idil.item.opening.balance", string="Opening Balance", ondelete="cascade"
    )
    item_id = fields.Many2one("idil.item", string="Item", required=True)
    quantity = fields.Float(string="Quantity", required=True)
    cost_price = fields.Float(string="Cost Price", store=True)
    total = fields.Float(string="Total", compute="_compute_total", store=True)

    @api.onchange("item_id")
    def _onchange_item_id(self):
        if self.item_id:
            self.cost_price = self.item_id.cost_price

    @api.depends("quantity", "cost_price")
    def _compute_total(self):
        for line in self:
            line.total = line.quantity * line.cost_price

    def create(self, vals_list):
        for vals in vals_list:
            # If cost_price not explicitly passed, pull from item
            if vals.get("item_id") and not vals.get("cost_price"):
                item = self.env["idil.item"].browse(vals["item_id"])
                vals["cost_price"] = item.cost_price
        records = super().create(vals_list)
        return records

    def write(self, vals):
        for line in self:
            if "item_id" in vals and "cost_price" not in vals:
                item = self.env["idil.item"].browse(vals["item_id"])
                vals["cost_price"] = item.cost_price
        return super().write(vals)
