# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import ValidationError


class PurchaseReceiveWizard(models.TransientModel):
    _name = "idil.purchase.receive.wizard"
    _description = "Purchase Receive Wizard"

    company_id = fields.Many2one(
        "res.company", default=lambda s: s.env.company, required=True
    )
    # Context references
    receipt_id = fields.Many2one("idil.purchase.receipt", required=True)
    receipt_line_id = fields.Many2one("idil.purchase.receipt.line", required=True)

    # Auto-derived references
    material_request_id = fields.Many2one(
        related="receipt_id.purchase_order_id.material_request_id",
        readonly=True,
    )
    purchase_order_id = fields.Many2one(
        related="receipt_id.purchase_order_id",
        readonly=True,
    )
    purchase_order_line_id = fields.Many2one(
        related="receipt_line_id.purchase_order_line_id",
        readonly=True,
    )

    # Input fields
    received_qty = fields.Float(string="Received Qty")

    cost_price = fields.Float(string="Cost Price", required=True)
    landing_cost = fields.Float(string="Landing Cost", required=True)
    total_cost = fields.Float(
        string="Total Cost", compute="_compute_total_cost", required=True
    )
    pay_account_id = fields.Many2one(
        "idil.chart.account",
        string="Landing Paid From (Cash/Bank)",
        domain=[
            ("account_type", "in", ["cash", "bank_transfer"])
        ],  # adjust to your field names
        required=False,
    )

    not_coming_qty = fields.Float(string="Not Coming Qty")
    reason_not_coming = fields.Text(string="Reason Not Coming")

    route_step = fields.Selection(
        [
            ("local_1", "Local Receipt"),
            ("int_1", "International Step 1"),
            ("int_2", "International Step 2"),
            ("int_3", "International Step 3"),
        ],
        required=True,
    )

    condition = fields.Selection(
        [
            ("good", "Good"),
            ("damaged", "Damaged"),
            ("expired", "Expired"),
        ],
        required=True,
    )

    date = fields.Date(string="Receipt Date", required=True)

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

    @api.depends("cost_price", "landing_cost", "received_qty")
    def _compute_total_cost(self):
        for w in self:
            w.total_cost = ((w.cost_price or 0.0) + (w.landing_cost or 0.0)) * (
                w.received_qty or 0
            )

    # def action_confirm(self):
    #     self.ensure_one()

    #     if self.received_qty <= 0 and self.not_coming_qty <= 0:
    #         raise ValidationError(_("Received Qty must be greater than zero."))

    #     # Create HISTORY RECORD ONLY
    #     self.env["idil.received.purchase"].create(
    #         {
    #             "material_request_id": self.material_request_id.id,
    #             "purchase_order_id": self.purchase_order_id.id,
    #             "purchase_order_line_id": self.purchase_order_line_id.id,
    #             "rate": self.rate,
    #             "received_date": self.date,
    #             "pay_account_id": self.pay_account_id.id,
    #             "receipt_id": self.receipt_id.id,
    #             "receipt_line_id": self.receipt_line_id.id,
    #             "received_qty": self.received_qty,
    #             "cost_price": self.cost_price,
    #             "landing_cost": self.landing_cost,
    #             "total_cost": self.total_cost,
    #             "reason_not_coming": self.reason_not_coming,
    #             "not_coming_qty": self.not_coming_qty,
    #             "route_step": self.route_step,
    #             "condition": self.condition,
    #             "status": "confirmed",
    #         }
    #     )

    #     return {"type": "ir.actions.act_window_close"}

    def action_confirm(self):
        self.ensure_one()

        if self.received_qty <= 0 and self.not_coming_qty <= 0:
            raise ValidationError(_("Received Qty must be greater than zero."))

        history = self.env["idil.received.purchase"].create(
            {
                "material_request_id": self.material_request_id.id,
                "purchase_order_id": self.purchase_order_id.id,
                "purchase_order_line_id": self.purchase_order_line_id.id,
                "rate": self.rate,
                "received_date": self.date,  # ✅ your doc_date source
                "pay_account_id": self.pay_account_id.id,
                "receipt_id": self.receipt_id.id,
                "receipt_line_id": self.receipt_line_id.id,
                "received_qty": self.received_qty,
                "cost_price": self.cost_price,
                "landing_cost": self.landing_cost,
                "total_cost": self.total_cost,
                "reason_not_coming": self.reason_not_coming,
                "not_coming_qty": self.not_coming_qty,
                "route_step": self.route_step,
                "condition": self.condition,
                "status": "confirmed",
            }
        )

        item = history.receipt_line_id.item_id
        qty = float(history.received_qty or 0.0)
        total = float(history.total_cost or 0.0)
        landing = float(history.landing_cost or 0.0)
        pay_acc = history.pay_account_id.name if history.pay_account_id else "N/A"

        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("✅ Receipt Confirmed"),
                "message": _(
                    "Item: %(item)s\n"
                    "Qty Received: %(qty).5f\n"
                    "Unit Cost: %(unit).5f\n"
                    "Unit Landing: %(landing).5f\n"
                    "Total: %(total).5f\n"
                    "Paid From: %(pay)s"
                )
                % {
                    "item": (item.name if item else "-"),
                    "qty": qty,
                    "unit": float(self.cost_price or 0.0),
                    "landing": landing,
                    "total": total,
                    "pay": pay_acc,
                },
                "type": "success",  # success | warning | danger | info
                "sticky": True,  # keep it visible until auto-close below
                "timeout": 10000,  # ✅ 10 seconds (milliseconds)
                "next": {"type": "ir.actions.act_window_close"},
            },
        }
