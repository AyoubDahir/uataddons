# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import ValidationError


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

        trx_source = self.env["idil.transaction.source"].search(
            [("name", "=", "Purchase Receipt")], limit=1
        )
        if not trx_source:
            raise ValidationError(_('Transaction source "Purchase Receipt" not found.'))

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

            # Amount is in ASSET currency (your rule)
            unit_total = float(rec.cost_price or 0.0) + float(rec.landing_cost or 0.0)
            if unit_total < 0:
                raise ValidationError(_("Cost + Landing cannot be negative."))

            amount_asset = qty * unit_total
            doc_date = fields.Date.context_today(rec)

            # Convert to vendor currency if mismatch
            rate = float(rec.rate or getattr(rec.receipt_id, "rate", 0.0) or 0.0)

            if asset_cur.id == vendor_cur.id:
                amount_vendor = amount_asset
            else:
                if rate <= 0:
                    raise ValidationError(
                        _("Exchange rate is required and must be > 0.")
                    )

                # Same convention you described:
                # if 1 USD = rate SL
                if asset_cur.name == "SL" and vendor_cur.name == "USD":
                    amount_vendor = amount_asset / rate
                elif asset_cur.name == "USD" and vendor_cur.name == "SL":
                    amount_vendor = amount_asset * rate
                else:
                    raise ValidationError(
                        _("Unsupported currency pair: %s -> %s")
                        % (asset_cur.name, vendor_cur.name)
                    )

            # Booking header
            booking_vals = {
                "trx_date": doc_date,
                "reffno": rec.receipt_id.name or rec.purchase_order_id.reffno,
                "payment_status": "pending",
                "payment_method": "ap",
                "amount": amount_vendor,  # store liability amount in vendor currency
                "amount_paid": 0.0,
                "remaining_amount": amount_vendor,
                "rate": rate,
                "trx_source_id": trx_source.id,
                "vendor_id": vendor.id,
                "purchase_order_id": rec.purchase_order_id.id,
            }

            # Link back if your booking has this field
            if "received_purchase_id" in Booking._fields:
                booking_vals["received_purchase_id"] = rec.id
            if "purchase_receipt_id" in Booking._fields:
                booking_vals["purchase_receipt_id"] = rec.receipt_id.id

            booking = Booking.create(booking_vals)

            # Booking lines
            if asset_cur.id != vendor_cur.id:
                clearing_asset = self.env["idil.chart.account"].search(
                    [
                        ("name", "=", "Exchange Clearing Account"),
                        ("currency_id", "=", asset_cur.id),
                    ],
                    limit=1,
                )
                clearing_vendor = self.env["idil.chart.account"].search(
                    [
                        ("name", "=", "Exchange Clearing Account"),
                        ("currency_id", "=", vendor_cur.id),
                    ],
                    limit=1,
                )
                if not clearing_asset or not clearing_vendor:
                    raise ValidationError(_("Exchange clearing accounts are required."))

                # CR clearing (asset currency)
                Line.create(
                    {
                        "transaction_booking_id": booking.id,
                        "account_number": clearing_asset.id,
                        "transaction_type": "cr",
                        "dr_amount": 0.0,
                        "cr_amount": amount_asset,
                        "transaction_date": doc_date,
                        "description": f"Receipt FX Clearing ({asset_cur.name}) - {item.name}",
                        "order_line": rec.purchase_order_line_id.id,
                        "item_id": item.id,
                    }
                )

                # DR clearing (vendor currency)
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

                # DR inventory asset (asset currency)
                Line.create(
                    {
                        "transaction_booking_id": booking.id,
                        "account_number": asset_acc.id,
                        "transaction_type": "dr",
                        "dr_amount": amount_asset,
                        "cr_amount": 0.0,
                        "transaction_date": doc_date,
                        "description": f"Inventory Receipt - {item.name}",
                        "order_line": rec.purchase_order_line_id.id,
                        "item_id": item.id,
                    }
                )

                # CR vendor payable (vendor currency)
                Line.create(
                    {
                        "transaction_booking_id": booking.id,
                        "account_number": vendor_acc.id,
                        "transaction_type": "cr",
                        "dr_amount": 0.0,
                        "cr_amount": amount_vendor,
                        "transaction_date": doc_date,
                        "description": f"Vendor Payable - Receipt - {vendor.name}",
                        "order_line": rec.purchase_order_line_id.id,
                        "item_id": item.id,
                    }
                )

            else:
                # Same currency
                Line.create(
                    {
                        "transaction_booking_id": booking.id,
                        "account_number": asset_acc.id,
                        "transaction_type": "dr",
                        "dr_amount": amount_asset,
                        "cr_amount": 0.0,
                        "transaction_date": doc_date,
                        "description": f"Inventory Receipt - {item.name}",
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
                        "cr_amount": amount_asset,
                        "transaction_date": doc_date,
                        "description": f"Vendor Payable - Receipt - {vendor.name}",
                        "order_line": rec.purchase_order_line_id.id,
                        "item_id": item.id,
                    }
                )

            # Vendor Transaction (vendor currency)
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
                "received_purchase_id": rec.id,  # ✅ correct
            }
            vt = VendorTxn.create(vt_vals)

            rec.booking_id = booking.id
            rec.vendor_transaction_id = vt.id

    @api.model
    def create(self, vals):
        rec = super().create(vals)
        # Step 1: create item movement
        rec._create_received_item_movement()
        # Step 2: update cost + expiry
        rec._update_item_cost_and_expiry_on_receive()
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

        return super().unlink()
