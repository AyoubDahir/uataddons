import re
from datetime import datetime
import logging
from odoo import models, fields, exceptions, api, _
from odoo.exceptions import ValidationError


_logger = logging.getLogger(__name__)


class PurchaseOrderLine(models.Model):
    _name = "idil.purchase_order.line"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _description = "Purchase Order"

    order_id = fields.Many2one(
        "idil.purchase_order", string="Order", ondelete="cascade"
    )
    received_history_ids = fields.One2many(
        "idil.received.purchase",
        "purchase_order_line_id",
        string="Receive History",
        readonly=True,
    )

    item_id = fields.Many2one("idil.item", string="Item", required=True)
    # Show item asset account on the purchase line
    item_asset_account_id = fields.Many2one(
        "idil.chart.account",
        string="Item Asset Account",
        related="item_id.asset_account_id",
        store=True,
        readonly=True,
    )
    # Show item currency on the purchase line
    item_asset_currency_id = fields.Many2one(
        "res.currency",
        string="Asset Account Currency",
        related="item_id.asset_account_id.currency_id",
        store=True,
        readonly=True,
    )

    quantity = fields.Integer(string="Quantity", required=True)
    # Add received quantity
    received_qty_total = fields.Float(
        string="Received Qty",
        compute="_compute_all_fields_from_received_history",
        readonly=True,
        tracking=True,
    )

    remaining_qty = fields.Float(
        string="Remaining Qty",
        compute="_compute_all_fields_from_received_history",
        store=False,
    )

    not_coming_qty = fields.Float(
        string="Not Coming Qty",
        compute="_compute_all_fields_from_received_history",
        store=True,  # ✅ important for domains and reporting
        readonly=True,
        tracking=True,
        help="Qty that will never be received (short close). No stock/accounting will be created for this qty. Computed from Receive History.",
    )

    cost_price = fields.Float(
        string="Cost per Unit", digits=(16, 5), required=True, tracking=True
    )

    amount = fields.Float(
        string="Total Price", compute="_compute_total_price", store=True
    )
    expiration_date = fields.Date(
        string="Expiration Date", required=True
    )  # Add expiration date field

    transaction_ids = fields.One2many(
        "idil.transaction_bookingline", "order_line", string="Transactions"
    )
    item_movement_ids = fields.One2many(
        "idil.item.movement",
        "purchase_order_line_id",
        string="Item Movements",
        auto_join=True,
        ondelete="cascade",
    )
    is_closed = fields.Boolean(
        string="Closed", compute="_compute_is_closed", store=True
    )

    @api.depends(
        "received_history_ids.not_coming_qty",
        "received_history_ids.status",
        "received_history_ids.received_qty",
        "received_history_ids.not_coming_qty",
    )
    def _compute_all_fields_from_received_history(self):
        for line in self:
            confirmed = line.received_history_ids.filtered(
                lambda h: h.status == "confirmed"
            )
            line.not_coming_qty = sum(confirmed.mapped("not_coming_qty")) or 0.0
            line.received_qty_total = sum(confirmed.mapped("received_qty")) or 0.0
            line.remaining_qty = sum(confirmed.mapped("not_coming_qty")) or 0.0

    def name_get(self):
        result = []
        for rec in self:
            # ✅ show real DB ID
            result.append((rec.id, str(rec.id)))
        return result

    @api.depends("remaining_qty")
    def _compute_is_closed(self):
        for l in self:
            l.is_closed = (l.remaining_qty or 0.0) <= 0.0

    @api.constrains("not_coming_qty", "quantity", "received_qty_total")
    def _check_not_coming_qty(self):
        for l in self:
            if l.not_coming_qty < 0:
                raise ValidationError(_("Not Coming Qty cannot be negative."))
            if (l.received_qty_total + l.not_coming_qty) > (l.quantity or 0.0):
                raise ValidationError(
                    _("Received + Not Coming cannot exceed Demand Qty.")
                )

    @api.onchange("item_id")
    def _onchange_item_id(self):
        if self.item_id:
            self.cost_price = self.item_id.cost_price

    @api.model
    def create(self, values):
        # If cost_price is 0 or not provided, get it from the item
        if not values.get("cost_price"):
            item = self.env["idil.item"].browse(values.get("item_id"))
            values["cost_price"] = item.cost_price

        existing_line = self.search(
            [
                ("order_id", "=", values.get("order_id")),
                ("item_id", "=", values.get("item_id")),
            ]
        )
        if existing_line:
            existing_line.write(
                {"quantity": existing_line.quantity + values.get("quantity", 0)}
            )
            return existing_line
        else:

            new_line = super(PurchaseOrderLine, self).create(values)
            # new_line._create_stock_transaction(values)

            return new_line

    def _sum_order_line_amounts(self):
        # Corrected to use the proper field name 'order_lines'
        return sum(line.amount for line in self.order_id.order_lines)

    def _get_next_transaction_number(self):
        max_transaction_number = (
            self.env["idil.transaction_booking"]
            .search([], order="transaction_number desc", limit=1)
            .transaction_number
            or 0
        )
        return max_transaction_number + 1

        # return self.env['idil.transaction_booking'].create(transaction_values)

    @api.depends("item_id", "quantity", "cost_price")
    def _compute_total_price(self):
        for line in self.filtered(lambda l: l.exists()):
            if line.item_id:
                if line.cost_price > 0:
                    line.amount = line.cost_price * line.quantity
                else:
                    line.amount = line.item_id.cost_price * line.quantity
            else:
                line.amount = 0.0

    def add_item(self):
        if self.order_id.vendor_id and self.order_id.vendor_id.stock_supplier:
            new_line = self.env["idil.purchase_order.line"].create(
                {
                    "order_id": self.order_id.id,
                    "expiration_date": fields.Date.today(),
                    # Initialize other fields here (if needed)
                }
            )
            return {
                "type": "ir.actions.act_window",
                "res_model": "idil.purchase_order.line",
                "view_mode": "form",
                "res_id": new_line.id,
                "target": "current",
            }
        else:
            raise exceptions.ValidationError("Vendor stock information not available!")


class PurchaseOrder(models.Model):
    _name = "idil.purchase_order"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _description = "Purchase Order Lines"
    _order = "id desc"

    company_id = fields.Many2one(
        "res.company", default=lambda s: s.env.company, required=True
    )
    reffno = fields.Char(string="Reference Number")  # Consider renaming for clarity
    vendor_id = fields.Many2one(
        "idil.vendor.registration", string="Vendor", required=True
    )
    invoice_number = fields.Char(
        string="Invoice Number",
        required=True,
        tracking=True,
    )
    purchase_date = fields.Date(
        string="Purchase Date", default=fields.Date.today, required=True
    )

    order_lines = fields.One2many(
        "idil.purchase_order.line", "order_id", string="Order Lines"
    )

    description = fields.Text(string="Description")

    amount = fields.Float(
        string="Total Price", compute="_compute_total_amount", store=True, readonly=True
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

    # 🆕 Add exchange rate field
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
    # 👇 Will change immediately when account changes; also searchable/groupable (store=True)
    currency_amount_id = fields.Many2one(
        "res.currency",
        string="Currency",
        compute="_compute_currency_amount",
        store=True,
    )

    # --- Currency refs ---
    currency_usd_id = fields.Many2one(
        "res.currency",
        compute="_compute_currency_refs",
        store=True,
        readonly=True,
    )
    currency_sl_id = fields.Many2one(
        "res.currency",
        compute="_compute_currency_refs",
        store=True,
        readonly=True,
    )

    # --- Totals ---
    amount_usd = fields.Monetary(
        string="💵 USD Total",
        currency_field="currency_usd_id",
        compute="_compute_amount_usd",
        store=True,
        readonly=True,
    )

    amount_sl = fields.Monetary(
        string="💱 SL Total",
        currency_field="currency_sl_id",
        compute="_compute_amount_sl",
        store=True,
        readonly=True,
    )

    amount_total_display = fields.Char(
        string="🧾 Total (Mixed)",
        compute="_compute_amount_total_display",
        store=True,
        readonly=True,
    )

    receipt_ids = fields.One2many(
        "idil.purchase.receipt",
        "purchase_order_id",
        string="Receipts",
    )

    receipt_state = fields.Selection(
        [
            ("none", "Not Received"),
            ("partial", "Partially Received"),
            ("full", "Fully Received"),
            ("closed_short", "Closed (Short)"),
        ],
        string="Receipt Status",
        compute="_compute_receipt_state",
        store=True,  # ✅ MUST be True (otherwise domain fails)
        index=True,  # ✅ recommended
        tracking=True,
        default="none",
    )

    material_request_id = fields.Many2one(
        "idil.material.request",
        string="Material Request",
        readonly=True,
        tracking=True,
        ondelete="restrict",
    )

    @api.depends(
        "order_lines.quantity",
        "order_lines.received_qty_total",
        "order_lines.not_coming_qty",
    )
    def _compute_receipt_state(self):
        for po in self:
            lines = po.order_lines
            if not lines:
                po.receipt_state = "none"
                continue

            total_demand = sum(lines.mapped("quantity")) or 0.0
            total_received = sum(lines.mapped("received_qty_total")) or 0.0
            total_not_coming = sum(lines.mapped("not_coming_qty")) or 0.0

            if total_received <= 0 and total_not_coming <= 0:
                po.receipt_state = "none"
            elif (total_received + total_not_coming) >= total_demand:
                po.receipt_state = "closed_short" if total_not_coming > 0 else "full"
            else:
                po.receipt_state = "partial"

    def action_submit(self):
        for o in self:
            if o.state != "draft":
                continue
            if not o.order_lines:
                raise ValidationError(
                    _("Please add at least one order line before submitting.")
                )
            o.state = "pending"
            o.message_post(body=_("Purchase Order submitted for approval."))

    def action_confirm(self):
        for o in self:
            if o.state != "pending":
                raise ValidationError(_("Only Pending orders can be confirmed."))
            o.state = "confirmed"
            o.message_post(body=_("Purchase Order confirmed."))

    def action_cancel(self):
        for o in self:
            if o.state == "confirmed":
                raise ValidationError(
                    _("You cannot cancel a confirmed purchase order.")
                )
            o.state = "cancel"
            o.message_post(body=_("Purchase Order cancelled."))

    def action_reset_to_draft(self):
        for o in self:
            if o.state != "cancel":
                continue
            o.state = "draft"
            o.message_post(body=_("Purchase Order reset to draft."))

    def action_print_purchase_order_pdf(self):
        self.ensure_one()
        return self.env.ref("idil.report_purchase_order_pdf").report_action(self)

    # ✅ 3) Prevent duplicate item lines inside the SAME MR (MODEL-LEVEL)
    @api.constrains("line_ids", "line_ids.item_id")
    def _constrains_no_duplicate_items_in_lines(self):
        for r in self:
            # only check when there are lines
            if not r.line_ids:
                continue

            seen = set()
            duplicates = set()

            for l in r.line_ids:
                if not l.item_id:
                    continue
                if l.item_id.id in seen:
                    duplicates.add(l.item_id.display_name)
                else:
                    seen.add(l.item_id.id)

            if duplicates:
                raise ValidationError(
                    _(
                        "Duplicate items are not allowed in the same Material Request:\n- %s"
                    )
                    % "\n- ".join(sorted(duplicates))
                )

    def _recompute_receipt_status_from_receipts(self):
        for po in self:
            total_demand = sum(po.order_lines.mapped("quantity")) or 0.0
            total_received = sum(po.order_lines.mapped("received_qty_total")) or 0.0
            total_not_coming = sum(po.order_lines.mapped("not_coming_qty")) or 0.0

            if total_received <= 0 and total_not_coming <= 0:
                po.receipt_state = "none"
            elif (total_received + total_not_coming) >= total_demand:
                # closed either full received or short closed
                po.receipt_state = "full" if total_not_coming <= 0 else "closed_short"
            else:
                po.receipt_state = "partial"

    # -------------------------------
    # Helpers (small + reusable)
    # -------------------------------
    def _is_usd(self, cur):
        return cur and (cur.name or "").upper() == "USD"

    def _is_sl(self, cur):
        return cur and (cur.name or "").upper() in (
            "SL",
            "SOS",
            "SLSH",
            "SOMALI SHILLING",
        )

    def _split_line_totals(self):
        """
        Return tuple: (usd_lines_total, sl_lines_total) based on item asset account currency.
        """
        usd_lines = 0.0
        sl_lines = 0.0

        for l in self.order_lines.exists():
            cur = l.item_asset_currency_id
            amt = l.amount or 0.0
            if not cur or amt <= 0:
                continue

            if self._is_usd(cur):
                usd_lines += amt
            elif self._is_sl(cur):
                sl_lines += amt

        return usd_lines, sl_lines

    # -------------------------------
    # Compute: currencies
    # -------------------------------
    @api.depends("company_id")
    def _compute_currency_refs(self):
        Currency = self.env["res.currency"].sudo()
        usd = Currency.search([("name", "=", "USD")], limit=1)
        sl = Currency.search([("name", "in", ["SL", "SOS"])], limit=1)

        for o in self:
            o.currency_usd_id = usd
            o.currency_sl_id = sl

    # -------------------------------
    # Compute: USD Total
    # -------------------------------
    @api.depends("order_lines.amount", "order_lines.item_asset_currency_id", "rate")
    def _compute_amount_usd(self):
        for o in self:
            rate = o.rate or 0.0
            usd_lines, sl_lines = o._split_line_totals()

            # USD Total = USD lines + (SL -> USD)
            o.amount_usd = usd_lines + (sl_lines / rate if rate > 0 else 0.0)

    # -------------------------------
    # Compute: SL Total
    # -------------------------------
    @api.depends("order_lines.amount", "order_lines.item_asset_currency_id", "rate")
    def _compute_amount_sl(self):
        for o in self:
            rate = o.rate or 0.0
            usd_lines, sl_lines = o._split_line_totals()

            # SL Total = SL lines + (USD -> SL)
            o.amount_sl = sl_lines + (usd_lines * rate if rate > 0 else 0.0)

    # -------------------------------
    # Compute: Mixed Display (original amounts only)
    # -------------------------------
    @api.depends("order_lines.amount", "order_lines.item_asset_currency_id")
    def _compute_amount_total_display(self):
        Currency = self.env["res.currency"].sudo()
        usd = Currency.search([("name", "=", "USD")], limit=1)
        sl = Currency.search([("name", "in", ["SL", "SOS"])], limit=1)

        for o in self:
            usd_lines, sl_lines = o._split_line_totals()

            parts = []
            if usd and usd_lines:
                parts.append(f"{usd.symbol or 'USD'} {usd_lines:,.2f}")
            if sl and sl_lines:
                parts.append(f"{sl.symbol or sl.name} {sl_lines:,.2f}")

            o.amount_total_display = " + ".join(parts) if parts else "0"

    @api.depends("company_id")
    def _compute_currency_refs(self):
        Currency = self.env["res.currency"].sudo()
        usd = Currency.search([("name", "=", "USD")], limit=1)
        sl = Currency.search(
            [("name", "in", ["SL", "SOS"])], limit=1
        )  # adjust to your real name
        for o in self:
            o.currency_usd_id = usd
            o.currency_sl_id = sl

    @api.depends("currency_id", "purchase_date", "company_id")
    def _compute_exchange_rate(self):
        Rate = self.env["res.currency.rate"].sudo()
        for order in self:
            order.rate = 0.0
            if not order.currency_id:
                continue

            doc_date = (
                fields.Date.to_date(order.purchase_date)
                if order.purchase_date
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

    @api.model
    def create(self, vals):
        """
        Override the default create method to customize the reference number.
        """
        # Generate the reference number
        vals["reffno"] = self._generate_purchase_order_reference(vals)
        # Call the super method to create the record with updated values
        order = super(PurchaseOrder, self).create(vals)

        return order

    def _generate_purchase_order_reference(self, values):
        vendor_id = values.get("vendor_id", False)
        if vendor_id:
            vendor_id = self.env["idil.vendor.registration"].browse(vendor_id)
            vendor_name = (
                "PO/" + re.sub("[^A-Za-z0-9]+", "", vendor_id.name[:2]).upper()
                if vendor_id and vendor_id.name
                else "XX"
            )
            date_str = "/" + datetime.now().strftime("%d%m%Y")
            day_night = "/DAY/" if datetime.now().hour < 12 else "/NIGHT/"
            sequence = self.env["ir.sequence"].next_by_code(
                "idil.purchase_order.sequence"
            )
            sequence = sequence[-3:] if sequence else "000"
            return f"{vendor_name}{date_str}{day_night}{sequence}"
        else:
            # Fallback if no BOM is provided
            return self.env["ir.sequence"].next_by_code("idil.purchase_order.sequence")

    @api.depends("order_lines.amount")
    def _compute_total_amount(self):
        for order in self:
            order.amount = sum(line.amount for line in order.order_lines.exists())

    def write(self, vals):
        # ✅ Allow only these fields to change (adjust as needed)
        allowed_fields = {"state", "receipt_state"}

        # ✅ Allow admin/system bypass when needed (optional)
        if self.env.context.get("allow_po_write"):
            return super().write(vals)

        blocked = set(vals.keys()) - allowed_fields
        if blocked:
            raise ValidationError(
                _(
                    "This Purchase Order is auto-generated from Purchase Request and cannot be modified.\n"
                    "Blocked fields: %s"
                )
                % ", ".join(sorted(blocked))
            )

        return super().write(vals)
