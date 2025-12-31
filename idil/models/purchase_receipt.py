# -*- coding: utf-8 -*-
import logging
from odoo import models, fields, api, _
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)


class PurchaseReceipt(models.Model):
    _name = "idil.purchase.receipt"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _description = "Purchase Receipt"
    _order = "id desc"

    name = fields.Char(
        string="Receipt No",
        copy=False,
        readonly=True,
        default=lambda s: _("New"),
        tracking=True,
    )

    vendor_id = fields.Many2one(
        "idil.vendor.registration",
        string="Vendor",
        required=True,
        tracking=True,
    )

    purchase_order_id = fields.Many2one(
        "idil.purchase_order",
        string="Purchase Order",
        ondelete="cascade",
        tracking=True,
        domain=[],
        required=True,
    )

    material_request_id = fields.Many2one(
        "idil.material.request",
        string="Material Request",
        related="purchase_order_id.material_request_id",
        store=True,
        readonly=True,
    )

    receipt_date = fields.Date(
        string="Receipt Date",
        default=fields.Date.context_today,
        required=True,
        tracking=True,
    )

    supplier_type = fields.Selection(
        related="purchase_order_id.material_request_id.supplier_type",
        store=False,
        readonly=True,
    )

    state = fields.Selection(
        [
            ("none", "Not Received"),
            ("partial", "Partially Received"),
            ("full", "Fully Received"),
            ("closed_short", "Closed (Short)"),
        ],
        string="Receipt Status",
        compute="_compute_state",
        tracking=True,
    )

    line_ids = fields.One2many(
        "idil.purchase.receipt.line", "receipt_id", string="Receipt Lines", copy=True
    )

    total_receive_qty = fields.Float(
        string="Total Received", compute="_compute_totals", store=False
    )

    total_not_coming_qty = fields.Float(
        string="Total Not Coming", compute="_compute_totals", store=False
    )
    total_remaining_qty = fields.Float(
        string="Total Remaining",
        compute="_compute_totals",
        store=False,
    )

    received_history_ids = fields.One2many(
        "idil.received.purchase",
        "receipt_id",
        string="Receive History",
        readonly=True,
    )

    delivery_indicator = fields.Selection(
        [
            ("green", "Fully Delivered"),
            ("yellow", "Partially Delivered"),
            ("orange", "Closed (Short)"),
            ("red", "Not Delivered"),
        ],
        string="Delivery Status",
        compute="_compute_delivery_indicator",
        store=False,
    )

    @api.depends(
        "line_ids.demand_qty",
        "line_ids.already_received",
        "line_ids.not_coming_qty",
        "line_ids.remaining_before",
    )
    def _compute_state(self):
        for r in self:
            if not r.line_ids:
                r.state = "none"
                continue

            total_demand = sum(r.line_ids.mapped("demand_qty")) or 0.0
            total_received = sum(r.line_ids.mapped("already_received")) or 0.0
            total_not_coming = sum(r.line_ids.mapped("not_coming_qty")) or 0.0

            # nothing received and nothing short-closed
            if total_received <= 0 and total_not_coming <= 0:
                r.state = "none"
                continue

            # closed (either full or short-close)
            if (total_received + total_not_coming) >= total_demand and total_demand > 0:
                r.state = "closed_short" if total_not_coming > 0 else "full"
                continue

            # otherwise partial (some activity but still open)
            r.state = "partial"

    @api.depends(
        "line_ids.demand_qty",
        "line_ids.already_received",
        "line_ids.not_coming_qty",
        "line_ids.remaining_before",
    )
    def _compute_delivery_indicator(self):
        for r in self:
            if not r.line_ids:
                r.delivery_indicator = "red"
                continue

            total_demand = sum(r.line_ids.mapped("demand_qty")) or 0.0
            total_received = sum(r.line_ids.mapped("already_received")) or 0.0
            total_not_coming = sum(r.line_ids.mapped("not_coming_qty")) or 0.0
            total_remaining = sum(r.line_ids.mapped("remaining_before")) or 0.0

            # default
            r.delivery_indicator = "red"

            if total_demand <= 0:
                r.delivery_indicator = "red"

            # ✅ fully delivered (all demand received, no short close)
            elif (
                total_remaining <= 0
                and total_received >= total_demand
                and total_not_coming <= 0
            ):
                r.delivery_indicator = "green"

            # ✅ closed short (remaining is 0, but not all received, and there is not coming)
            elif (
                total_remaining <= 0
                and total_not_coming > 0
                and total_received < total_demand
            ):
                r.delivery_indicator = "orange"

            # ✅ partial (some received OR some short close, but still remaining)
            elif total_remaining > 0 and (total_received > 0 or total_not_coming > 0):
                r.delivery_indicator = "yellow"

            # ✅ not delivered (nothing received, nothing short closed)
            else:
                r.delivery_indicator = "red"

    @api.depends("purchase_order_id", "line_ids.purchase_order_line_id")
    def _compute_totals(self):
        History = self.env["idil.received.purchase"]
        for rec in self:
            rec.total_receive_qty = 0.0
            rec.total_not_coming_qty = 0.0
            rec.total_remaining_qty = 0.0

            if not rec.purchase_order_id:
                continue

            # total received + not coming (confirmed history)
            data = History.read_group(
                domain=[
                    ("purchase_order_id", "=", rec.purchase_order_id.id),
                    ("status", "=", "confirmed"),
                ],
                fields=["received_qty:sum", "not_coming_qty:sum"],
                groupby=[],
            )
            total_received = (data[0].get("received_qty", 0.0) if data else 0.0) or 0.0
            total_not_coming = (
                data[0].get("not_coming_qty", 0.0) if data else 0.0
            ) or 0.0

            rec.total_receive_qty = total_received
            rec.total_not_coming_qty = total_not_coming

            # total demand from PO lines
            total_demand = (
                sum(rec.purchase_order_id.order_lines.mapped("quantity")) or 0.0
            )

            rec.total_remaining_qty = max(
                0.0, total_demand - total_received - total_not_coming
            )

    @api.onchange("vendor_id")
    def _onchange_vendor_id_filter_po(self):
        """When vendor changes, show only that vendor's POs that still have remaining qty."""
        self.purchase_order_id = False
        if not self.vendor_id:
            return {"domain": {"purchase_order_id": []}}

        return {
            "domain": {
                "purchase_order_id": [
                    ("vendor_id", "=", self.vendor_id.id),
                    ("state", "=", "confirmed"),
                    (
                        "receipt_state",
                        "in",
                        ["none", "partial"],
                    ),
                    ("order_lines.remaining_qty", ">", 0),
                ]
            }
        }

    @api.onchange("purchase_order_id")
    def _onchange_purchase_order_id_fill_lines(self):
        # clear existing lines
        self.line_ids = [(5, 0, 0)]

        if not self.purchase_order_id:
            return

        lines_cmd = []
        for pol in self.purchase_order_id.order_lines:
            demand = float(pol.quantity or 0.0)
            received = float(pol.received_qty_total or 0.0)  # store=True recommended
            not_coming = float(pol.not_coming_qty or 0.0)  # store=True

            remaining = max(0.0, demand - received - not_coming)
            if remaining <= 0:
                continue

            lines_cmd.append((0, 0, {"purchase_order_line_id": pol.id}))

        self.line_ids = lines_cmd

    def action_open_receive_wizard(self):
        self.ensure_one()
        if not self.purchase_order_id:
            raise ValidationError(_("Please select Purchase Order first."))

        return {
            "type": "ir.actions.act_window",
            "name": _("Receive Qty"),
            "res_model": "idil.purchase.receive.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {
                "default_purchase_receipt_id": self.id,
                "default_purchase_order_id": self.purchase_order_id.id,
                "active_id": self.id,
                "active_model": "idil.purchase.receipt",
            },
        }

    @api.model
    def create(self, vals):
        if vals.get("name", _("New")) == _("New"):
            vals["name"] = self.env["ir.sequence"].next_by_code(
                "idil.purchase.receipt"
            ) or _("New")
        return super(PurchaseReceipt, self).create(vals)

    def unlink(self):
        for rec in self:
            # If there is any received history linked to this receipt, block delete
            history_count = self.env["idil.received.purchase"].search_count(
                [("receipt_id", "=", rec.id)]
            )
            if history_count:
                raise ValidationError(
                    _(
                        "You cannot delete this Receipt because it has Receive History.\n"
                        "Please delete the Receive History lines first, then delete the Receipt."
                    )
                )
        return super().unlink()


class PurchaseReceiptLine(models.Model):
    _name = "idil.purchase.receipt.line"
    _description = "Purchase Receipt Line"

    receipt_id = fields.Many2one(
        "idil.purchase.receipt", required=True, ondelete="cascade"
    )
    purchase_order_line_id = fields.Many2one(
        "idil.purchase_order.line", ondelete="restrict"
    )

    item_id = fields.Many2one(
        related="purchase_order_line_id.item_id", store=True, readonly=True
    )
    demand_qty = fields.Integer(
        related="purchase_order_line_id.quantity",
        store=False,
        readonly=True,
        string="Demand QTY",
    )

    already_received = fields.Float(
        compute="_compute_already_received",
        store=False,
        readonly=True,
    )

    cost_price = fields.Float(
        string="Cost Price",
        compute="_compute_costs_from_history",
        store=True,
        readonly=False,
    )

    landing_cost = fields.Float(
        string="Landing Cost",
        compute="_compute_costs_from_history",
        store=True,
        readonly=False,
    )

    total_cost = fields.Float(
        string="Total Cost",
        compute="_compute_total_cost",
        store=True,
        readonly=True,
    )

    remaining_before = fields.Float(
        string="Remaining Qty",
        compute="_compute_remaining_before",
        store=False,
        readonly=True,
    )

    delivery_indicator = fields.Selection(
        [
            ("green", "Fully Delivered"),
            ("yellow", "Partially Delivered"),
            ("orange", "Closed (Shortly Delivered)"),
            ("red", "Not Delivered"),
        ],
        string="Delivery Status",
        compute="_compute_delivery_indicator",
        store=False,
    )

    not_coming_qty = fields.Float(
        string="Not Coming Qty",
        compute="_compute_not_coming_qty",
        readonly=True,
        tracking=True,
    )

    @api.depends(
        "receipt_id",
        "receipt_id.received_history_ids.status",
        "receipt_id.received_history_ids.receipt_line_id",
        "receipt_id.received_history_ids.received_qty",
        "receipt_id.received_history_ids.cost_price",
        "receipt_id.received_history_ids.landing_cost",
    )
    def _compute_costs_from_history(self):
        History = self.env["idil.received.purchase"]

        for line in self:
            cost = 0.0
            landing = 0.0

            if not line.receipt_id or not line.id:
                line.cost_price = 0.0
                line.landing_cost = 0.0
                continue

            records = History.search(
                [
                    ("receipt_line_id", "=", line.id),
                    ("receipt_id", "=", line.receipt_id.id),
                    ("status", "=", "confirmed"),
                ]
            )

            total_qty = sum(records.mapped("received_qty")) or 0.0

            if total_qty > 0:
                # ✅ cost_price + landing_cost are UNIT prices in history
                cost = (
                    sum(
                        (r.received_qty or 0.0) * (r.cost_price or 0.0) for r in records
                    )
                    / total_qty
                )
                landing = (
                    sum(
                        (r.received_qty or 0.0) * (r.landing_cost or 0.0)
                        for r in records
                    )
                    / total_qty
                )

            # ✅ ONLY history result (no PO fallback)
            line.cost_price = round(cost, 5)
            line.landing_cost = round(landing, 5)

    @api.depends("cost_price", "landing_cost", "already_received")
    def _compute_total_cost(self):
        for line in self:
            unit = (line.cost_price or 0.0) + (line.landing_cost or 0.0)
            qty = float(line.already_received or 0.0)
            line.total_cost = round(unit * qty, 5)

    @api.depends("purchase_order_line_id", "purchase_order_line_id.not_coming_qty")
    def _compute_not_coming_qty(self):
        for line in self:
            line.not_coming_qty = float(
                line.purchase_order_line_id.not_coming_qty or 0.0
            )

    @api.depends("already_received", "remaining_before", "demand_qty", "not_coming_qty")
    def _compute_delivery_indicator(self):
        for line in self:
            received = float(line.already_received or 0.0)
            remaining = float(line.remaining_before or 0.0)
            demand = float(line.demand_qty or 0.0)
            not_coming = float(line.not_coming_qty or 0.0)

            # default
            line.delivery_indicator = "red"

            if demand <= 0:
                line.delivery_indicator = "red"
                continue

            # ✅ all delivered
            if remaining <= 0 and received >= demand and not_coming <= 0:
                line.delivery_indicator = "green"

            # ✅ closed short
            elif remaining <= 0 and received < demand and not_coming > 0:
                line.delivery_indicator = "orange"

            # ✅ partial (some received, no short close)
            elif not_coming <= 0 and 0 < received < demand:
                line.delivery_indicator = "yellow"

            # ✅ not yet delivered (nothing received, no short close)
            elif not_coming <= 0 and received <= 0 and remaining >= demand:
                line.delivery_indicator = "red"

    @api.depends(
        "purchase_order_line_id",
        "purchase_order_line_id.quantity",
        "purchase_order_line_id.not_coming_qty",
        "already_received",
    )
    def _compute_remaining_before(self):
        for line in self:
            pol = line.purchase_order_line_id
            if not pol:
                line.remaining_before = 0.0
                continue

            demand = float(pol.quantity or 0.0)
            not_coming = float(pol.not_coming_qty or 0.0)
            received = float(line.already_received or 0.0)  # from your history model

            line.remaining_before = max(0.0, (demand - received) - not_coming)

    @api.depends("purchase_order_line_id")
    def _compute_already_received(self):
        History = self.env["idil.received.purchase"]
        for line in self:
            if not line.purchase_order_line_id:
                line.already_received = 0.0
                continue

            records = History.search(
                [
                    ("purchase_order_line_id", "=", line.purchase_order_line_id.id),
                    ("receipt_id", "=", line.receipt_id.id),
                    ("status", "=", "confirmed"),
                ]
            )

            line.already_received = sum(records.mapped("received_qty"))

    def action_open_receive_wizard(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Receive Qty"),
            "res_model": "idil.purchase.receive.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {
                "default_receipt_id": self.receipt_id.id,
                "default_receipt_line_id": self.id,
            },
        }
