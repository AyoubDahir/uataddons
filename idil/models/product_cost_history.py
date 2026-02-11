# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import ValidationError


class ProductCostHistory(models.Model):
    _name = "idil.product.cost.history"
    _description = "Product Cost History (Manufacturing)"
    _order = "id desc"

    company_id = fields.Many2one(
        "res.company", default=lambda s: s.env.company, required=True
    )

    manufacturing_order_id = fields.Many2one(
        "idil.manufacturing.order",
        string="Manufacturing Order",
        required=True,
        ondelete="cascade",
        index=True,
    )

    product_id = fields.Many2one(
        "my_product.product",
        string="Product",
        required=True,
        ondelete="restrict",
        index=True,
    )

    scheduled_date = fields.Datetime(
        string="Scheduled Date",
        required=True,
        index=True,
    )

    produced_qty = fields.Float(string="Produced Qty", digits=(16, 5), required=True)

    unit_cost = fields.Float(
        string="Unit Cost",
        digits=(16, 5),
        required=True,
        help="Unit cost calculated from MO total cost / produced qty.",
    )

    total_cost = fields.Float(
        string="Total Cost",
        digits=(16, 5),
        required=True,
        help="Total cost used in this MO for cost averaging.",
    )

    prev_qty = fields.Float(
        string="Previous Qty",
        digits=(16, 5),
        help="Product stock qty before this MO production.",
    )

    prev_cost = fields.Float(
        string="Previous Cost",
        digits=(16, 5),
        help="Product cost before this MO production.",
    )

    new_avg_cost = fields.Float(
        string="New Avg Cost",
        digits=(16, 5),
        help="Final moving average cost after this MO.",
    )

    note = fields.Char(string="Note")
