from odoo import models, fields


class MoCostType(models.Model):
    _name = "idil.mo.cost.type"
    _description = "MO Cost Type"
    _order = "name"

    name = fields.Char(string="Cost Name", required=True)

    currency_id = fields.Many2one(
        "res.currency",
        string="Currency",
        required=True,
        default=lambda self: self.env.company.currency_id,
    )

    expense_account_id = fields.Many2one(
        "idil.chart.account",
        string="Expense Account",
        required=True,
        domain="[('header_name', '=', 'Expenses'), ('currency_id', '=', sales_currency_id)]",
    )
