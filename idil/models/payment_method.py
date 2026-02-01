from odoo import models, fields, api
from odoo.exceptions import ValidationError


class IdilPaymentMethod(models.Model):
    _name = "idil.payment.method"
    _description = "Payment Method Setup"
    _inherit = ["mail.thread", "mail.activity.mixin"]

    company_id = fields.Many2one(
        "res.company", default=lambda s: s.env.company, required=True
    )

    name = fields.Char(required=True, tracking=True)
    code = fields.Selection(
        [
            ("cash", "Cash"),
            ("bank", "Bank"),
            ("evc", "EVC"),
            ("wallet", "Wallet"),
            ("other", "Other"),
        ],
        required=True,
        tracking=True,
    )

    # Default account linked to this method
    account_id = fields.Many2one(
        "idil.chart.account",
        string="Default Account",
        required=True,
        tracking=True,
    )

    active = fields.Boolean(default=True)

    _sql_constraints = [
        (
            "uniq_method_company",
            "unique(company_id, name)",
            "Payment method name must be unique per company.",
        ),
    ]
