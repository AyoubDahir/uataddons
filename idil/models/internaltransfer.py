# -*- coding: utf-8 -*-
import logging
from odoo import models, fields, api, _
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)


class InternalTransfer(models.Model):
    _name = "idil.internal.transfer"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _description = "Internal Transfer"
    _order = "id desc"

    _sql_constraints = [
        ("name_uniq", "unique(name)", "Transfer No must be unique."),
    ]

    name = fields.Char(
        string="Transfer No",
        copy=False,
        readonly=True,
        default=lambda self: _("New"),
        tracking=True,
    )

    transfer_date = fields.Date(
        string="Transfer Date",
        default=fields.Date.context_today,
        required=True,
        tracking=True,
    )

    source_warehouse_id = fields.Many2one(
        "idil.warehouse", string="🏬 From Warehouse", required=True, tracking=True
    )
    destination_warehouse_id = fields.Many2one(
        "idil.warehouse", string="🏬 To Warehouse", required=True, tracking=True
    )

    source_location_id = fields.Many2one(
        "idil.warehouse.location",
        string="📤 From Location",
        required=True,
        tracking=True,
        domain="[('warehouse_id', '=', source_warehouse_id), ('active', '=', True)]",
    )
    destination_location_id = fields.Many2one(
        "idil.warehouse.location",
        string="📥 To Location",
        required=True,
        tracking=True,
        domain="[('warehouse_id', '=', destination_warehouse_id), ('active', '=', True)]",
    )

    line_ids = fields.One2many(
        "idil.internal.transfer.line",
        "transfer_id",
        string="Products",
        copy=True,
        tracking=True,
    )

    move_ref = fields.Char(
        string="Movement Ref",
        readonly=True,
        tracking=True,
        help="Reference for created movements.",
    )

    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("pending", "Pending Approval"),
            ("approved", "Approved"),
            ("rejected", "Rejected"),
            ("cancel", "Cancelled"),
        ],
        string="Status",
        default="draft",
        tracking=True,
        copy=False,
    )

    notes = fields.Text(string="Notes")

    # -------------------------
    # Constraints
    # -------------------------
    @api.constrains("source_location_id", "destination_location_id")
    def _constrains_source_destination_not_same(self):
        for r in self:
            if (
                r.source_location_id
                and r.destination_location_id
                and r.source_location_id.id == r.destination_location_id.id
            ):
                raise ValidationError(
                    _("Source Location and Destination Location cannot be the same.")
                )

    # -------------------------
    # Validation helpers
    # -------------------------
    def _validate_before_submit(self):
        for r in self:
            if not r.line_ids:
                raise ValidationError(_("Please add at least one product line."))

            bad_lines = r.line_ids.filtered(lambda l: not l.stock_ok)
            if bad_lines:
                items = ", ".join(bad_lines.mapped("item_id.name"))
                raise ValidationError(
                    _(
                        "Insufficient stock for Transfer on: %s.\n"
                        "Please reduce quantity or use Purchase Request."
                    )
                    % items
                )

    def _check_duplicate_open_transfers(self):
        """
        Prevent duplicates:
        if there is already an OPEN (draft/pending) internal transfer
        for same source/dest locations and same item.
        """
        open_states = ("draft", "pending")
        for r in self:
            for line in r.line_ids:
                if not line.item_id:
                    continue
                domain = [
                    ("id", "!=", r.id),
                    ("state", "in", open_states),
                    ("source_location_id", "=", r.source_location_id.id),
                    ("destination_location_id", "=", r.destination_location_id.id),
                    ("line_ids.item_id", "=", line.item_id.id),
                ]
                if self.search_count(domain):
                    raise ValidationError(
                        _(
                            "Duplicate Internal Transfer detected.\n"
                            "There is already an open transfer for item '%s' with same source/destination.\n"
                            "Please review Draft/Pending transfers."
                        )
                        % line.item_id.display_name
                    )

    # -------------------------
    # Workflow
    # -------------------------
    def action_submit(self):
        for r in self:
            if r.state != "draft":
                continue
            r._validate_before_submit()
            r._check_duplicate_open_transfers()
            r.state = "pending"

    def action_reject(self, reason=None):
        for r in self:
            if r.state != "pending":
                raise ValidationError(_("Only pending transfers can be rejected."))
            if reason:
                r.message_post(body=_("Rejected: %s") % reason)
            r.state = "rejected"

    def action_cancel(self):
        for r in self:
            if r.state == "approved":
                raise ValidationError(_("You cannot cancel an approved transfer."))
            r.state = "cancel"

    def action_reset_to_draft(self):
        for r in self:
            if r.state in ("rejected", "cancel"):
                r.state = "draft"

    def action_approve(self):
        for r in self:
            if r.state != "pending":
                raise ValidationError(_("Only pending transfers can be approved."))

            # Maker-checker rule
            creator = r.create_uid
            approver = self.env.user
            if creator == approver:
                employee = self.env["idil.employee"].search(
                    [("user_id", "=", approver.id)], limit=1
                )
                if not employee or not employee.maker_checker:
                    raise ValidationError(
                        _(
                            "You are not allowed to approve your own Internal Transfer. "
                            "Please request approval from another authorized user."
                        )
                    )

            ref = r._create_internal_movements()
            r.move_ref = ref
            r.message_post(body=_("Internal Transfer executed: %s") % ref)
            r.state = "approved"

    # -------------------------
    # Movement + Stock update
    # -------------------------
    def _create_internal_movements(self):
        """
        Current logic uses GLOBAL item.quantity (not per location).
        This means it reduces stock globally and ONLY logs destination.
        If you want true warehouse stock, later we will implement location stock model.
        """
        self.ensure_one()

        if self.move_ref:
            return self.move_ref

        # Validate again at approval time
        bad_lines = self.line_ids.filtered(lambda l: not l.stock_ok)
        if bad_lines:
            items = ", ".join(bad_lines.mapped("item_id.name"))
            raise ValidationError(_("Insufficient stock for: %s") % items)

        ref = f"IT/{self.name}"

        for l in self.line_ids:
            if not l.item_id or l.qty <= 0:
                continue

            item = l.item_id
            qty = l.qty

            if (item.quantity or 0.0) < qty:
                raise ValidationError(
                    _("Insufficient stock for '%s'. Available: %s, Requested: %s")
                    % (item.name, item.quantity, qty)
                )

            # Update GLOBAL stock (your current approach)
            item.with_context(update_transaction_booking=False).write(
                {"quantity": (item.quantity or 0.0) - qty}
            )

            # Create internal movement log
            self.env["idil.item.movement"].create(
                {
                    "item_id": item.id,
                    "date": self.transfer_date or fields.Date.today(),
                    "quantity": qty,
                    # If your movement model expects IDs, keep IDs.
                    # If it expects text, change to .display_name
                    "source": self.source_location_id.id,
                    "destination": self.destination_location_id.id,
                    "movement_type": "internal",
                    "related_document": f"idil.internal.transfer,{self.id}",
                    "reference": ref,  # if you have this field
                }
            )

        return ref

    # -------------------------
    # Sequence
    # -------------------------
    @api.model
    def create(self, vals):
        if vals.get("name", _("New")) == _("New"):
            vals["name"] = self.env["ir.sequence"].next_by_code(
                "idil.internal.transfer"
            ) or _("New")
        return super().create(vals)

    # -------------------------
    # Lock after approved
    # -------------------------
    def _is_locked(self):
        self.ensure_one()
        return self.state == "approved"

    def write(self, vals):
        allowed_fields = {
            "message_follower_ids",
            "message_ids",
            "activity_ids",
            "activity_state",
            "activity_type_id",
            "activity_user_id",
            "activity_date_deadline",
            "activity_summary",
            "activity_exception_decoration",
            "activity_exception_icon",
        }
        for r in self:
            if r._is_locked():
                if set(vals.keys()) - allowed_fields:
                    raise ValidationError(
                        _(
                            "You cannot modify this Internal Transfer because it is Approved."
                        )
                    )
        return super().write(vals)

    def unlink(self):
        for r in self:
            if r._is_locked():
                raise ValidationError(
                    _(
                        "You cannot delete this Internal Transfer because it is Approved."
                    )
                )
        return super().unlink()


class InternalTransferLine(models.Model):
    _name = "idil.internal.transfer.line"
    _description = "Internal Transfer Line"
    _order = "id asc"

    transfer_id = fields.Many2one(
        "idil.internal.transfer",
        string="Internal Transfer",
        ondelete="cascade",
        required=True,
    )

    item_id = fields.Many2one("idil.item", string="Item", required=True)
    qty = fields.Float(string="Qty", required=True, default=1.0)

    available_qty = fields.Float(
        string="Available Qty", compute="_compute_available_qty", store=False
    )
    stock_ok = fields.Boolean(
        string="Stock OK", compute="_compute_stock_ok", store=False
    )

    stock_indicator = fields.Selection(
        [("green", "Available"), ("red", "Insufficient")],
        compute="_compute_stock_indicator",
        store=False,
    )

    @api.depends("item_id")
    def _compute_available_qty(self):
        for l in self:
            l.available_qty = float(l.item_id.quantity or 0.0) if l.item_id else 0.0

    @api.depends("available_qty", "qty")
    def _compute_stock_ok(self):
        for l in self:
            l.stock_ok = l.available_qty >= (l.qty or 0.0)

    @api.depends("stock_ok")
    def _compute_stock_indicator(self):
        for l in self:
            l.stock_indicator = "green" if l.stock_ok else "red"

    @api.constrains("qty")
    def _check_qty(self):
        for l in self:
            if l.qty <= 0:
                raise ValidationError(_("Quantity must be greater than 0."))
