# -*- coding: utf-8 -*-
import logging
from odoo import models, fields, api, _
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)


class IdilWarehouse(models.Model):
    _name = "idil.warehouse"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _description = "Warehouse"
    _order = "name asc"

    name = fields.Char(string="🏬 Warehouse Name", required=True, tracking=True)
    code = fields.Char(string="🏷️ Code", tracking=True)
    active = fields.Boolean(string="✅ Active", default=True, tracking=True)

    manager_id = fields.Many2one(
        "res.users",
        string="👤 Warehouse Manager",
        tracking=True,
        help="User responsible for this warehouse.",
    )

    address = fields.Char(string="📍 Address", tracking=True)
    notes = fields.Text(string="📝 Notes")

    location_ids = fields.One2many(
        "idil.warehouse.location",
        "warehouse_id",
        string="📌 Locations",
        copy=False,
    )

    location_count = fields.Integer(
        string="📌 Locations",
        compute="_compute_location_count",
        store=False,
    )

    @api.depends("location_ids")
    def _compute_location_count(self):
        for w in self:
            w.location_count = len(w.location_ids)

    _sql_constraints = [
        ("warehouse_code_uniq", "unique(code)", "Warehouse code must be unique."),
    ]

    @api.constrains("code")
    def _check_code(self):
        for w in self:
            if w.code and len(w.code.strip()) < 2:
                raise ValidationError(
                    _("Warehouse code must be at least 2 characters.")
                )


class IdilWarehouseLocation(models.Model):
    _name = "idil.warehouse.location"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _description = "Warehouse Location"
    _order = "warehouse_id asc, name asc"

    name = fields.Char(string="📌 Location Name", required=True, tracking=True)
    code = fields.Char(string="🏷️ Code", tracking=True)
    active = fields.Boolean(string="✅ Active", default=True, tracking=True)

    warehouse_id = fields.Many2one(
        "idil.warehouse",
        string="🏬 Warehouse",
        required=True,
        ondelete="cascade",
        tracking=True,
    )

    usage = fields.Selection(
        [
            ("receiving", "📥 Receiving Area"),
            ("storage", "📦 Storage"),
            ("cold", "❄️ Cold Storage"),
            ("staging", "🧺 Staging"),
            ("dispatch", "🚚 Dispatch"),
            ("transit", "🛳️ Transit"),
            ("supplier", "🏭 Supplier Drop Zone"),
            ("custom", "🧩 Custom"),
        ],
        string="🧭 Location Type",
        default="storage",
        tracking=True,
    )

    is_default_receiving = fields.Boolean(
        string="⭐ Default Receiving Location",
        default=False,
        tracking=True,
        help="Used as default receiving location for this warehouse.",
    )

    notes = fields.Text(string="📝 Notes")

    _sql_constraints = [
        (
            "loc_code_per_wh_uniq",
            "unique(warehouse_id, code)",
            "Location code must be unique per warehouse.",
        ),
        (
            "loc_name_per_wh_uniq",
            "unique(warehouse_id, name)",
            "Location name must be unique per warehouse.",
        ),
    ]

    @api.constrains("is_default_receiving", "warehouse_id")
    def _check_one_default_receiving(self):
        for loc in self:
            if not loc.is_default_receiving:
                continue
            others = self.search_count(
                [
                    ("id", "!=", loc.id),
                    ("warehouse_id", "=", loc.warehouse_id.id),
                    ("is_default_receiving", "=", True),
                ]
            )
            if others:
                raise ValidationError(
                    _("Only one Default Receiving Location is allowed per warehouse.")
                )
