from odoo import models, fields, api
from odoo.exceptions import ValidationError


class ManufacturingOrderCostLine(models.Model):
    _name = "idil.manufacturing.order.cost.line"
    _description = "MO Extra Cost Line"
    _order = "id desc"

    manufacturing_order_id = fields.Many2one(
        "idil.manufacturing.order",
        required=True,
        ondelete="cascade",
        index=True,
    )

    cost_type_id = fields.Many2one(
        "idil.mo.cost.type",
        string="Cost Type",
        required=True,
    )

    employee_id = fields.Many2one("idil.employee", string="Employee")

    currency_id = fields.Many2one(
        related="cost_type_id.currency_id",
        store=True,
        readonly=True,
    )

    expense_account_id = fields.Many2one(
        related="cost_type_id.expense_account_id",
        store=True,
        readonly=True,
    )

    description = fields.Char(string="Description")
    amount = fields.Float(string="Amount", digits=(16, 5), required=True, default=0.0)

    @api.constrains("amount")
    def _check_amount(self):
        for r in self:
            if (r.amount or 0.0) < 0:
                raise ValidationError("Amount cannot be negative.")
