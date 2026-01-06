# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import ValidationError
from odoo.tools import float_compare


class IdilReceivedPurchase(models.Model):
    _name = "idil.received.purchase"
    _description = "Received Purchase History"
    _order = "id desc"

    # --- References (ALL IDS you asked for) ---
    material_request_id = fields.Many2one(
        "idil.material.request",
        string="Material Request",
        required=True,
        ondelete="restrict",
    )

    purchase_order_id = fields.Many2one(
        "idil.purchase_order",
        string="Purchase Order",
        required=True,
        ondelete="restrict",
    )

    purchase_order_line_id = fields.Many2one(
        "idil.purchase_order.line",
        string="PO Line",
        required=True,
        ondelete="restrict",
    )

    receipt_id = fields.Many2one(
        "idil.purchase.receipt",
        string="Receipt",
        required=True,
        ondelete="cascade",
    )

    receipt_line_id = fields.Many2one(
        "idil.purchase.receipt.line",
        string="Receipt Line",
        required=True,
        ondelete="cascade",
    )

    booking_id = fields.Many2one(
        "idil.transaction_booking",
        string="Transaction Booking",
        readonly=True,
        ondelete="set null",
    )

    user_id = fields.Many2one(
        "res.users",
        string="Recorded By",
        default=lambda self: self.env.user,
        readonly=True,
    )
    vendor_transaction_id = fields.Many2one(
        "idil.vendor_transaction",
        string="Vendor Transaction",
        readonly=True,
        ondelete="cascade",
    )

    pay_account_id = fields.Many2one(
        "idil.chart.account",
        string="Landing Paid From (Cash/Bank)",
        domain=[
            ("account_type", "in", ["cash", "bank_transfer"])
        ],  # adjust to your field names
        required=False,
    )

    # --- Business fields ---
    received_qty = fields.Float(string="Received Qty")

    cost_price = fields.Float(string="Cost Price")
    landing_cost = fields.Float(string="Landing Cost")
    total_cost = fields.Float(string="Total Cost")

    not_coming_qty = fields.Float(string="Total Not Coming")
    reason_not_coming = fields.Text(string="Reason")

    received_date = fields.Datetime(
        string="Received Date",
        default=fields.Datetime.now,
        required=True,
    )

    route_step = fields.Selection(
        [
            ("local_1", "Local Receipt"),
            ("int_1", "International Step 1"),
            ("int_2", "International Step 2"),
            ("int_3", "International Step 3"),
        ],
        string="Step",
        required=True,
    )

    condition = fields.Selection(
        [
            ("good", "Good"),
            ("damaged", "Damaged"),
            ("expired", "Expired"),
        ],
        string="Condition",
        required=True,
    )

    status = fields.Selection(
        [
            ("draft", "Draft"),
            ("confirmed", "Confirmed"),
        ],
        default="confirmed",
        string="Status",
        required=True,
    )
    rate = fields.Float(
        string="Exchange Rate",
        store=True,
        readonly=True,
    )

    def _create_received_item_movement(self):
        for rec in self:
            qty = float(rec.received_qty or 0.0)
            if qty <= 0:
                continue

            item = rec.receipt_line_id.item_id
            if not item:
                raise ValidationError(_("Receipt Line has no Item linked."))

            rec.env["idil.item.movement"].create(
                {
                    "received_purchase_id": rec.id,  # ✅ THIS IS THE KEY
                    "item_id": item.id,
                    "date": fields.Date.context_today(rec),
                    "quantity": qty,
                    "movement_type": "in",
                    "source": "Purchase Receipt",
                    "destination": "Stock",
                    "destination_warehouse_id": rec.receipt_id.material_request_id.warehouse_id.id,
                    "destination_location_id": rec.receipt_id.material_request_id.location_id.id,
                    "purchase_order_line_id": rec.purchase_order_line_id.id,
                    "related_document": "idil.purchase.receipt,%s" % rec.receipt_id.id,
                }
            )

    @api.constrains(
        "received_qty", "not_coming_qty", "purchase_order_line_id", "status"
    )
    def _check_qtys_not_exceed_remaining(self):
        """
        remaining = demand - (already_confirmed_received + already_confirmed_not_coming)
        This record (received_qty + not_coming_qty) must be <= remaining.
        Allow received_qty = 0 when not_coming_qty > 0 (full short close case).
        """
        for rec in self:
            if not rec.purchase_order_line_id:
                continue

            recv = float(rec.received_qty or 0.0)
            nc = float(rec.not_coming_qty or 0.0)

            if recv < 0 or nc < 0:
                raise ValidationError(
                    _("Received Qty and Not Coming Qty cannot be negative.")
                )

            # at least one must be entered
            if recv == 0 and nc == 0:
                raise ValidationError(
                    _("You must enter either Received Qty or Not Coming Qty.")
                )

            pol = rec.purchase_order_line_id
            demand = float(pol.quantity or 0.0)

            # sums from OTHER confirmed history lines (exclude current)
            domain = [
                ("purchase_order_line_id", "=", pol.id),
                ("status", "=", "confirmed"),
                ("id", "!=", rec.id),
            ]
            others = self.search(domain)

            already_recv = sum(others.mapped("received_qty")) or 0.0
            already_nc = sum(others.mapped("not_coming_qty")) or 0.0

            remaining = max(0.0, demand - already_recv - already_nc)

            if (recv + nc) > remaining:
                raise ValidationError(
                    _(
                        "Received + Not Coming (%(x)s) cannot be greater than Remaining (%(rem)s).\n"
                        "Remaining = Demand (%(d)s) - Already Received (%(ar)s) - Already Not Coming (%(anc)s)."
                    )
                    % {
                        "x": (recv + nc),
                        "rem": remaining,
                        "d": demand,
                        "ar": already_recv,
                        "anc": already_nc,
                    }
                )

        # optional: force reason when not coming is used
        if nc > 0 and not rec.reason_not_coming:
            raise ValidationError(
                _("Please provide a Reason when Not Coming Qty is entered.")
            )

    def _update_item_cost_and_expiry_on_receive(self):
        """
        Step 2:
        - Update item.expiration_date from receipt line (preferred) else PO line
        - Update item.cost_price using weighted average UNIT LANDED COST:
            incoming_unit_landed = (cost_price + landing_cost)
            new_avg = (current_qty*current_cost + received_qty*incoming_unit_landed) / (current_qty + received_qty)
        Notes:
        - item.quantity is computed from movements => do NOT write it directly
        """
        precision = 5  # match your digits=(16,5)

        for rec in self:
            qty = float(rec.received_qty or 0.0)
            if qty <= 0:
                continue

            item = rec.receipt_line_id.item_id
            if not item:
                raise ValidationError(_("Receipt Line has no Item linked."))

            # -----------------------
            # Expiry date (receipt line preferred)
            # -----------------------
            expiry = getattr(rec.receipt_line_id, "expiration_date", False) or getattr(
                rec.purchase_order_line_id, "expiration_date", False
            )

            # -----------------------
            # Incoming unit cost
            # -----------------------
            # Prefer receive record cost_price if user enters it,
            # otherwise fallback to receipt line, then PO line, then item.
            base_cost = (
                float(rec.cost_price or 0.0)
                or float(getattr(rec.receipt_line_id, "cost_price", 0.0) or 0.0)
                or float(getattr(rec.purchase_order_line_id, "cost_price", 0.0) or 0.0)
                or float(item.cost_price or 0.0)
            )

            landing = float(rec.landing_cost or 0.0)

            # Incoming landed unit cost (per unit)
            incoming_unit_landed = base_cost + landing
            if incoming_unit_landed < 0:
                raise ValidationError(
                    _("Total unit cost (Cost + Landing) cannot be negative.")
                )

            # -----------------------
            # Current stock & cost (computed stock from movements)
            # -----------------------
            current_qty = float(item.quantity or 0.0)
            current_cost = float(item.cost_price or 0.0)

            # -----------------------
            # Weighted average
            # -----------------------
            new_qty = current_qty + qty
            # If new_qty is 0, fallback to incoming (but qty>0 so normally not)
            if new_qty > 0:
                new_avg_cost = (
                    (current_qty * current_cost) + (qty * incoming_unit_landed)
                ) / new_qty
            else:
                new_avg_cost = incoming_unit_landed

            # -----------------------
            # Update item master
            # -----------------------
            vals = {
                "cost_price": round(new_avg_cost, precision),
            }
            if expiry:
                vals["expiration_date"] = expiry

            item.with_context(update_transaction_booking=False).write(vals)

            # Optional: store total cost on this receive record for reporting
            rec.total_cost = round(qty * incoming_unit_landed, precision)

    # -------------------------------------------------------------------------
    # Step 3 + Step 4: Booking + Booking Lines + Vendor Transaction (WORKING)
    # RULE: amount entered is in ASSET currency (item asset account currency)
    # -------------------------------------------------------------------------

    def _post_receive_booking_and_vendor_txn(self):
        Booking = self.env["idil.transaction_booking"]
        Line = self.env["idil.transaction_bookingline"]
        VendorTxn = self.env["idil.vendor_transaction"]
        Chart = self.env["idil.chart.account"]

        trx_source = self.env["idil.transaction.source"].search(
            [("name", "=", "Purchase Receipt")], limit=1
        )
        if not trx_source:
            raise ValidationError(_('Transaction source "Purchase Receipt" not found.'))

        def _convert(amount, from_cur, to_cur, rate):
            """Convert using your convention: if 1 USD = rate SL."""
            amount = float(amount or 0.0)
            if from_cur.id == to_cur.id:
                return amount

            r = float(rate or 0.0)
            if r <= 0:
                raise ValidationError(_("Exchange rate is required and must be > 0."))

            if from_cur.name == "SL" and to_cur.name == "USD":
                return amount / r
            if from_cur.name == "USD" and to_cur.name == "SL":
                return amount * r

            raise ValidationError(
                _("Unsupported currency pair: %s -> %s") % (from_cur.name, to_cur.name)
            )

        def _get_clearing(cur):
            acc = Chart.search(
                [
                    ("name", "=", "Exchange Clearing Account"),
                    ("currency_id", "=", cur.id),
                ],
                limit=1,
            )
            if not acc:
                raise ValidationError(
                    _("Exchange clearing account is required for currency: %s")
                    % cur.name
                )
            return acc

        def _get_account_balance(account):
            """Balance = SUM(DR) - SUM(CR) for this account."""
            self.env.cr.execute(
                """
                SELECT COALESCE(SUM(dr_amount), 0) - COALESCE(SUM(cr_amount), 0)
                FROM idil_transaction_bookingline
                WHERE account_number = %s
                """,
                (account.id,),
            )
            bal = self.env.cr.fetchone()[0] or 0.0
            return float(bal)

        def _check_pay_balance(pay_account, amount_to_pay, precision=5):
            """Raise if cash/bank does not have enough balance."""
            bal = _get_account_balance(pay_account)
            if (
                float_compare(
                    bal, float(amount_to_pay or 0.0), precision_digits=precision
                )
                < 0
            ):
                raise ValidationError(
                    _(
                        "Insufficient balance in Paying Account '%(acc)s'.\n"
                        "Available: %(bal).5f | Required: %(req).5f"
                    )
                    % {
                        "acc": pay_account.name,
                        "bal": bal,
                        "req": float(amount_to_pay or 0.0),
                    }
                )

        for rec in self:
            if rec.booking_id:
                continue

            qty = float(rec.received_qty or 0.0)
            if qty <= 0:
                raise ValidationError(_("Received Qty must be greater than 0."))

            item = rec.receipt_line_id.item_id
            if not item or not item.asset_account_id:
                raise ValidationError(_("Item or Item Asset Account is missing."))

            vendor = rec.purchase_order_id.vendor_id
            if not vendor or not vendor.account_payable_id:
                raise ValidationError(_("Vendor or Vendor A/P account is missing."))

            asset_acc = item.asset_account_id
            vendor_acc = vendor.account_payable_id

            asset_cur = asset_acc.currency_id
            vendor_cur = vendor_acc.currency_id
            if not asset_cur or not vendor_cur:
                raise ValidationError(
                    _("Both Asset and Vendor A/P accounts must have currency.")
                )

            doc_date = fields.Date.context_today(rec)
            rate = float(rec.rate or getattr(rec.receipt_id, "rate", 0.0) or 0.0)

            # --------------------------
            # Amount split
            # --------------------------
            base_unit = float(rec.cost_price or 0.0)
            landing_unit = float(rec.landing_cost or 0.0)

            if base_unit < 0:
                raise ValidationError(_("Cost Price cannot be negative."))
            if landing_unit < 0:
                raise ValidationError(_("Landing Cost cannot be negative."))

            amount_base_asset = qty * base_unit
            landing_total_asset = qty * landing_unit  # if landing is total, change this

            amount_vendor = _convert(amount_base_asset, asset_cur, vendor_cur, rate)

            # --------------------------
            # Booking header (vendor direct only)
            # --------------------------
            booking_vals = {
                "trx_date": doc_date,
                "reffno": rec.receipt_id.name or rec.purchase_order_id.reffno,
                "payment_status": "pending",
                "payment_method": "ap",
                "amount": amount_vendor,
                "amount_paid": 0.0,
                "remaining_amount": amount_vendor,
                "rate": rate,
                "trx_source_id": trx_source.id,
                "vendor_id": vendor.id,
                "purchase_order_id": rec.purchase_order_id.id,
            }
            if "received_purchase_id" in Booking._fields:
                booking_vals["received_purchase_id"] = rec.id
            if "purchase_receipt_id" in Booking._fields:
                booking_vals["purchase_receipt_id"] = rec.receipt_id.id

            booking = Booking.create(booking_vals)

            # --------------------------
            # 1) Direct cost: Inventory + Vendor A/P
            # --------------------------
            if amount_base_asset > 0:
                if asset_cur.id != vendor_cur.id:
                    clearing_asset = _get_clearing(asset_cur)
                    clearing_vendor = _get_clearing(vendor_cur)

                    Line.create(
                        {
                            "transaction_booking_id": booking.id,
                            "account_number": clearing_asset.id,
                            "transaction_type": "cr",
                            "dr_amount": 0.0,
                            "cr_amount": amount_base_asset,
                            "transaction_date": doc_date,
                            "description": f"Receipt FX Clearing ({asset_cur.name}) - {item.name}",
                            "order_line": rec.purchase_order_line_id.id,
                            "item_id": item.id,
                        }
                    )

                    Line.create(
                        {
                            "transaction_booking_id": booking.id,
                            "account_number": clearing_vendor.id,
                            "transaction_type": "dr",
                            "dr_amount": amount_vendor,
                            "cr_amount": 0.0,
                            "transaction_date": doc_date,
                            "description": f"Receipt FX Clearing ({vendor_cur.name}) - {item.name}",
                            "order_line": rec.purchase_order_line_id.id,
                            "item_id": item.id,
                        }
                    )

                    Line.create(
                        {
                            "transaction_booking_id": booking.id,
                            "account_number": asset_acc.id,
                            "transaction_type": "dr",
                            "dr_amount": amount_base_asset,
                            "cr_amount": 0.0,
                            "transaction_date": doc_date,
                            "description": f"Inventory Receipt (Direct) - {item.name}",
                            "order_line": rec.purchase_order_line_id.id,
                            "item_id": item.id,
                        }
                    )

                    Line.create(
                        {
                            "transaction_booking_id": booking.id,
                            "account_number": vendor_acc.id,
                            "transaction_type": "cr",
                            "dr_amount": 0.0,
                            "cr_amount": amount_vendor,
                            "transaction_date": doc_date,
                            "description": f"Vendor Payable (Direct) - {vendor.name}",
                            "order_line": rec.purchase_order_line_id.id,
                            "item_id": item.id,
                        }
                    )
                else:
                    Line.create(
                        {
                            "transaction_booking_id": booking.id,
                            "account_number": asset_acc.id,
                            "transaction_type": "dr",
                            "dr_amount": amount_base_asset,
                            "cr_amount": 0.0,
                            "transaction_date": doc_date,
                            "description": f"Inventory Receipt (Direct) - {item.name}",
                            "order_line": rec.purchase_order_line_id.id,
                            "item_id": item.id,
                        }
                    )
                    Line.create(
                        {
                            "transaction_booking_id": booking.id,
                            "account_number": vendor_acc.id,
                            "transaction_type": "cr",
                            "dr_amount": 0.0,
                            "cr_amount": amount_base_asset,
                            "transaction_date": doc_date,
                            "description": f"Vendor Payable (Direct) - {vendor.name}",
                            "order_line": rec.purchase_order_line_id.id,
                            "item_id": item.id,
                        }
                    )

            # --------------------------
            # 2) Landing: Expense + Cash/Bank (with balance check)
            # --------------------------
            if landing_total_asset > 0:
                pay_acc = rec.pay_account_id
                if not pay_acc:
                    raise ValidationError(
                        _("Please select Paying Account (Cash/Bank) for Landing Cost.")
                    )

                landing_exp_acc = item.landing_account_id
                if not landing_exp_acc:
                    raise ValidationError(
                        _(
                            "Item is missing Landing Expense Account (landing_account_id)."
                        )
                    )

                pay_cur = pay_acc.currency_id
                exp_cur = landing_exp_acc.currency_id
                if not pay_cur or not exp_cur:
                    raise ValidationError(
                        _(
                            "Paying account and Landing expense account must have currency."
                        )
                    )

                landing_amount_pay = _convert(
                    landing_total_asset, asset_cur, pay_cur, rate
                )
                landing_amount_exp = _convert(
                    landing_total_asset, asset_cur, exp_cur, rate
                )

                # ✅ validate pay account has enough balance (in pay account currency)
                _check_pay_balance(pay_acc, landing_amount_pay, precision=5)

                if pay_cur.id == exp_cur.id:
                    Line.create(
                        {
                            "transaction_booking_id": booking.id,
                            "account_number": landing_exp_acc.id,
                            "transaction_type": "dr",
                            "dr_amount": landing_amount_exp,
                            "cr_amount": 0.0,
                            "transaction_date": doc_date,
                            "description": f"Landing/Freight Expense - {item.name}",
                            "order_line": rec.purchase_order_line_id.id,
                            "item_id": item.id,
                        }
                    )
                    Line.create(
                        {
                            "transaction_booking_id": booking.id,
                            "account_number": pay_acc.id,
                            "transaction_type": "cr",
                            "dr_amount": 0.0,
                            "cr_amount": landing_amount_pay,
                            "transaction_date": doc_date,
                            "description": f"Landing Paid (Cash/Bank) - {item.name}",
                            "order_line": rec.purchase_order_line_id.id,
                            "item_id": item.id,
                        }
                    )
                else:
                    clearing_pay = _get_clearing(pay_cur)
                    clearing_exp = _get_clearing(exp_cur)

                    Line.create(
                        {
                            "transaction_booking_id": booking.id,
                            "account_number": landing_exp_acc.id,
                            "transaction_type": "dr",
                            "dr_amount": landing_amount_exp,
                            "cr_amount": 0.0,
                            "transaction_date": doc_date,
                            "description": f"Landing/Freight Expense - {item.name}",
                            "order_line": rec.purchase_order_line_id.id,
                            "item_id": item.id,
                        }
                    )
                    Line.create(
                        {
                            "transaction_booking_id": booking.id,
                            "account_number": pay_acc.id,
                            "transaction_type": "cr",
                            "dr_amount": 0.0,
                            "cr_amount": landing_amount_pay,
                            "transaction_date": doc_date,
                            "description": f"Landing Paid (Cash/Bank) - {item.name}",
                            "order_line": rec.purchase_order_line_id.id,
                            "item_id": item.id,
                        }
                    )
                    Line.create(
                        {
                            "transaction_booking_id": booking.id,
                            "account_number": clearing_pay.id,
                            "transaction_type": "cr",
                            "dr_amount": 0.0,
                            "cr_amount": landing_amount_pay,
                            "transaction_date": doc_date,
                            "description": f"Landing FX Clearing ({pay_cur.name}) - {item.name}",
                            "order_line": rec.purchase_order_line_id.id,
                            "item_id": item.id,
                        }
                    )
                    Line.create(
                        {
                            "transaction_booking_id": booking.id,
                            "account_number": clearing_exp.id,
                            "transaction_type": "dr",
                            "dr_amount": landing_amount_exp,
                            "cr_amount": 0.0,
                            "transaction_date": doc_date,
                            "description": f"Landing FX Clearing ({exp_cur.name}) - {item.name}",
                            "order_line": rec.purchase_order_line_id.id,
                            "item_id": item.id,
                        }
                    )

            # --------------------------
            # Vendor transaction (direct only)
            # --------------------------
            vt_vals = {
                "transaction_number": booking.transaction_number,
                "transaction_date": doc_date,
                "vendor_id": vendor.id,
                "amount": amount_vendor,
                "remaining_amount": amount_vendor,
                "paid_amount": 0.0,
                "payment_method": "ap",
                "reffno": booking.reffno,
                "transaction_booking_id": booking.id,
                "payment_status": "pending",
                "received_purchase_id": rec.id,
            }
            vt = VendorTxn.create(vt_vals)

            rec.booking_id = booking.id
            rec.vendor_transaction_id = vt.id

    @api.model
    def create(self, vals):
        rec = super().create(vals)
        # Step 1:  update cost + expiry
        rec._update_item_cost_and_expiry_on_receive()
        # Step 2: create item movement
        rec._create_received_item_movement()
        # Step 3: create booking
        rec._post_receive_booking_and_vendor_txn()

        return rec

    def action_delete_history(self):
        """Delete one history line from the tree button."""
        for rec in self:
            # Optional safety rules (adjust)
            # Example: don't allow delete if confirmed unless manager
            # if rec.status == "confirmed" and not self.env.user.has_group("base.group_system"):
            #     raise ValidationError(_("You are not allowed to delete confirmed receive history."))

            rec.unlink()
        return True

    def unlink(self):
        """
        Delete permission is ONLY based on idil.employee linked to current user.
        - If no employee is linked -> block
        - If linked but allow_delete_receipt is False -> block
        - If linked and allow_delete_receipt is True -> allow
        (NO system admin bypass)
        """
        emp = self.env["idil.employee"].search(
            [("user_id", "=", self.env.user.id)], limit=1
        )

        if not emp:
            raise ValidationError(
                _("Access Denied: Your user is not linked to an Employee record.")
            )

        if not emp.allow_delete_receipt:
            raise ValidationError(
                _(
                    "Access Denied: You are not allowed to delete purchase receipt/receive history."
                )
            )

        items = self.mapped("receipt_line_id.item_id").filtered(lambda x: x)

        res = super().unlink()

        for item in items:
            self._recompute_item_cost_from_receipts(item)

        return res

    def _recompute_item_cost_from_receipts(self, item):
        """
        Recompute item.cost_price after deleting a received purchase record.

        Baseline:
        - 0 qty, 0 cost (since you don't store opening qty/cost on item)

        Replay:
        - remaining CONFIRMED idil.received.purchase lines for this item
        - ordered by received_date asc, id asc
        - incoming_unit = cost_price + landing_cost (UNIT prices)
        - moving average:
            avg = (prev_qty*prev_cost + in_qty*in_unit) / (prev_qty + in_qty)
        """
        precision = 5

        qty_on_hand = 0.0
        avg_cost = 0.0

        receipts = self.search(
            [
                ("status", "=", "confirmed"),
                ("receipt_line_id.item_id", "=", item.id),
                ("received_qty", ">", 0),
            ],
            order="received_date asc, id asc",
        )

        for r in receipts:
            in_qty = float(r.received_qty or 0.0)
            if in_qty <= 0:
                continue

            unit_cost = float(r.cost_price or 0.0) + float(r.landing_cost or 0.0)
            if unit_cost < 0:
                raise ValidationError(_("Incoming unit cost cannot be negative."))

            new_qty = qty_on_hand + in_qty
            avg_cost = ((qty_on_hand * avg_cost) + (in_qty * unit_cost)) / new_qty
            qty_on_hand = new_qty

        # If no receipts left, decide what to set:
        # Option A: set to 0
        # Option B: keep current item.cost_price
        # Your example expects: after deleting landing record, cost should become 1.9
        # That will happen because one receipt remains.
        final_cost = round(avg_cost, precision) if qty_on_hand > 0 else 0.0

        item.with_context(update_transaction_booking=False).write(
            {"cost_price": final_cost}
        )
