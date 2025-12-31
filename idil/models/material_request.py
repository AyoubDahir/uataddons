import logging
from odoo import models, fields, api, _
from odoo.exceptions import ValidationError, AccessError

_logger = logging.getLogger(__name__)


class MaterialRequest(models.Model):
    _name = "idil.material.request"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _description = "Material Request"
    _order = "id desc"

    _sql_constraints = [
        ("name_uniq", "unique(name)", "Request No must be unique."),
    ]

    name = fields.Char(
        string="Request No",
        copy=False,
        readonly=True,
        default=lambda self: _("New"),
        tracking=True,
    )
    request_date = fields.Date(
        string="Request Date",
        default=fields.Date.context_today,
        required=True,
        tracking=True,
    )
    request_type = fields.Selection(
        [
            ("purchase", "Purchase Request"),
        ],
        string="Request Type",
        required=True,
        default="purchase",
        tracking=True,
    )
    supplier_type = fields.Selection(
        [
            ("local", "Local Supplier"),
            ("international", "International Supplier"),
        ],
        string="Supplier Type",
        tracking=True,
        required=True,
    )
    vendor_id = fields.Many2one(
        "idil.vendor.registration",
        string="Vendor",
        tracking=True,
        required=True,
        help="Vendor is required only for Purchase Request.",
        domain="[('supplier_type', '=', supplier_type), ('active', '=', True)]",
    )
    warehouse_id = fields.Many2one(
        "idil.warehouse",
        required=True,
        string="🏬 Warehouse",
        tracking=True,
    )

    location_id = fields.Many2one(
        "idil.warehouse.location",
        string="📤Location",
        tracking=True,
        required=True,
        domain="[('warehouse_id', '=', warehouse_id), ('active', '=', True)]",
    )

    line_ids = fields.One2many(
        "idil.material.request.line",
        "request_id",
        string="Items",
        copy=True,
        tracking=True,
    )

    purchase_order_id = fields.Many2one(
        "idil.purchase_order",
        string="Generated Purchase Order",
        readonly=True,
        tracking=True,
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

    show_purchase_fields = fields.Boolean(
        compute="_compute_show_fields",
        store=False,
    )
    show_transfer_fields = fields.Boolean(
        compute="_compute_show_fields",
        store=False,
    )

    # ✅ 1) Purchase vs Transfer required fields (MODEL-LEVEL)
    @api.constrains(
        "request_type",
        "supplier_type",
        "vendor_id",
        "warehouse_id",
        "source_location_id",
    )
    def _constrains_required_fields_by_type(self):
        for r in self:
            # Skip empty (during create wizard steps) only if you want:
            # if not r.request_type: continue

            if r.request_type == "purchase":
                if not r.supplier_type:
                    raise ValidationError(
                        _("Supplier Type is required for Purchase Request.")
                    )
                if not r.vendor_id:
                    raise ValidationError(_("Vendor is required for Purchase Request."))

    @api.onchange("supplier_type")
    def _onchange_supplier_type(self):
        """
        Filter vendors based on selected supplier type (if vendor has supplier_type field).
        If your vendor model does NOT have supplier_type yet, this domain will just do nothing.
        """
        if not self.supplier_type:
            return {"domain": {"vendor_id": []}}

        # If your vendor model has field `supplier_type`, domain works.
        # If not, it will not crash; it just won't filter meaningfully.
        return {"domain": {"vendor_id": [("supplier_type", "=", self.supplier_type)]}}

    # -------------------------
    # Core validations
    # -------------------------
    def _validate_before_submit(self):
        for r in self:
            if not r.line_ids:
                raise ValidationError(_("Please add at least one Item line."))

            if r.request_type == "purchase":
                if not r.supplier_type:
                    raise ValidationError(
                        _("Supplier Type is required for Purchase Request.")
                    )
                if not r.vendor_id:
                    raise ValidationError(_("Vendor is required for Purchase Request."))

    def _check_duplicate_open_requests(self):
        """
        Avoid duplicates:
        If there is already an OPEN (draft/pending) MR for same request type and same item,
        block submitting a new one (or block adding duplicates).
        """
        for r in self:
            open_states = ("draft", "pending")
            for line in r.line_ids:
                if not line.item_id:
                    continue

                domain = [
                    ("id", "!=", r.id),
                    ("state", "in", open_states),
                    ("request_type", "=", r.request_type),
                    ("line_ids.item_id", "=", line.item_id.id),
                ]

                # extra narrowing: purchase supplier type/vendor; transfer source/dest
                if r.request_type == "purchase":
                    domain += [
                        ("supplier_type", "=", r.supplier_type),
                        ("vendor_id", "=", r.vendor_id.id),
                    ]

                exists = self.search_count(domain)
                if exists:
                    raise ValidationError(
                        _(
                            "Duplicate request detected.\n"
                            "There is already an open Material Request for item '%s'.\n"
                            "Please review existing Draft/Pending requests to avoid duplicates."
                        )
                        % (line.item_id.display_name,)
                    )

    # -------------------------
    # Workflow actions
    # -------------------------
    def action_submit(self):
        for r in self:
            if r.state != "draft":
                raise ValidationError("Only Draft requests can be submitted.")
            r._validate_before_submit()
            r._check_duplicate_open_requests()
            r.state = "pending"

    def action_reject(self, reason=None):
        for r in self:
            if r.state not in ("pending",):
                raise ValidationError(
                    "Only pending requests can be rejected. if needed, cancel it first."
                )
            if reason:
                r.message_post(body=_("Rejected: %s") % reason)
            r.state = "rejected"

    def action_cancel(self):
        for r in self:
            if r.state == "approved":
                raise ValidationError(
                    _(
                        "You cannot cancel an approved request. reset it to draft first if needed."
                    )
                )
            r.state = "cancel"

    def action_reset_to_draft(self):
        for r in self:
            # ✅ Allowed cases:
            # 1) rejected / cancel
            # 2) approved BUT no PO linked
            if r.state in ("rejected", "cancel"):
                r.state = "draft"
                r.message_post(body=_("Request reset to Draft."))
                continue

            if r.state == "approved":
                if r.purchase_order_id:
                    raise ValidationError(
                        _(
                            "You cannot reset to Draft because this request is Approved "
                            "and linked to a Purchase Order (%s)."
                        )
                        % (r.purchase_order_id.reffno or r.purchase_order_id.id)
                    )

                # Approved but no PO linked -> allow reset
                r.state = "draft"
                r.message_post(
                    body=_(
                        "Request reset to Draft (Approved request had no PO linked)."
                    )
                )
            continue

    def action_approve(self):
        """
        Approve:
        - If purchase -> create PO and link it
        - If transfer -> create internal transfer movements and link ref
        """
        for r in self:
            if r.state != "pending":
                raise ValidationError(
                    "Only pending requests can be approved. Please submit first. Thanks. :)"
                )

            # Prevent self-approval unless maker-checker is enabled
            creator = r.create_uid  # user who created the record
            approver = self.env.user  # user trying to approve now

            # Only check maker-checker if the same user is approving their own record
            if creator == approver:
                # Find the employee linked to this user
                employee = self.env["idil.employee"].search(
                    [("user_id", "=", approver.id)],
                    limit=1,
                )

                # If no employee linked, or maker_checker is False → block self-approval
                if not employee or not employee.maker_checker:
                    raise ValidationError(
                        "You are not allowed to approve your own material request. "
                        "Only employees with 'Maker & Checker' enabled can self-approve. "
                        "Please request approval from another authorized user."
                    )

            if r.request_type == "purchase":
                po = r._create_purchase_order_from_request()
                r.purchase_order_id = po.id
                r.message_post(
                    body=_("Purchase Order created: %s") % (po.reffno or po.id)
                )
            else:
                ref = r._create_internal_transfer_from_request()
                r.transfer_ref = ref
                r.message_post(body=_("Internal Transfer created: %s") % (ref,))

            r.state = "approved"

    # -------------------------
    # Automatic creation logic
    # -------------------------
    def _create_purchase_order_from_request(self):
        """
        Create a Purchase Order in your custom model and link it to MR.
        IMPORTANT:
        Your current PO create() immediately updates stock & bookings.
        For a real receipt-based workflow, later you will move stock update to receipt validation.
        For now, we just generate the PO as requested.
        """
        self.ensure_one()

        if self.purchase_order_id:
            return self.purchase_order_id  # no duplicates

        if not self.vendor_id:
            raise ValidationError(_("Vendor is required to create a Purchase Order."))

        po_vals = {
            "vendor_id": self.vendor_id.id,
            "invoice_number": self.name,  # or empty; depends on your business
            "purchase_date": self.request_date or fields.Date.today(),
            "description": f"Created from Material Request {self.name}",
            "material_request_id": self.id,
            # choose default payment method: A/P is usually default for procurement
        }

        # Create PO first
        po = self.env["idil.purchase_order"].create(po_vals)

        # Create PO lines
        for l in self.line_ids:
            if not l.item_id or l.requested_qty <= 0:
                continue
            self.env["idil.purchase_order.line"].create(
                {
                    "order_id": po.id,
                    "item_id": l.item_id.id,
                    "quantity": int(l.requested_qty),
                    "cost_price": l.suggested_cost_price or l.item_id.cost_price,
                    "expiration_date": l.expiration_date or fields.Date.today(),
                }
            )

        return po

    def _create_internal_transfer_from_request(self):
        """
        Since you do not use Odoo stock module, we implement internal transfer as:
        - creating idil.item.movement records per line
        - movement_type = 'internal'
        - source/destination as text (your current movement uses text)
        """
        self.ensure_one()

        # Safety: do not duplicate transfer generation
        if self.transfer_ref:
            return self.transfer_ref

        # Validate stock again at approval time
        bad_lines = self.line_ids.filtered(lambda l: not l.stock_ok)
        if bad_lines:
            items = ", ".join(bad_lines.mapped("item_id.name"))
            raise ValidationError(
                _(
                    "Cannot approve Transfer Request due to insufficient stock for: %s.\n"
                    "Please use Purchase Request instead."
                )
                % items
            )

        # Generate a simple reference
        ref = f"ITR/{self.name}"

        for l in self.line_ids:
            if not l.item_id or l.requested_qty <= 0:
                continue

            # Reduce stock from item (global stock)
            item = l.item_id
            qty = l.requested_qty

            if item.quantity < qty:
                raise ValidationError(
                    _("Insufficient stock for '%s'. Available: %s, Requested: %s")
                    % (item.name, item.quantity, qty)
                )

            # Update item stock (global)
            item.with_context(update_transaction_booking=False).write(
                {"quantity": item.quantity - qty}
            )

            # Create movement record (internal)
            self.env["idil.item.movement"].create(
                {
                    "item_id": item.id,
                    "date": self.request_date or fields.Date.today(),
                    "quantity": qty,
                    "source": self.source_location_id,
                    "destination": self.destination_location_id,
                    "movement_type": "internal",
                    "related_document": f"idil.material.request,{self.id}",
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
                "idil.material.request.preq"
            ) or _("New")
        self._check_duplicate_open_requests()

        return super().create(vals)

    # -------------------------
    # Lock Approved MR if PO linked
    # -------------------------
    def _lock_message(self):
        self.ensure_one()
        po_ref = (
            self.purchase_order_id.reffno
            or self.purchase_order_id.invoice_number
            or self.purchase_order_id.id
        )
        return (
            _(
                "You cannot modify or delete this Material Request because it is Approved "
                "and already used to create a Purchase Order.\n"
                "Linked Purchase Order: %s"
            )
            % po_ref
        )

    def _is_locked_by_po(self):
        self.ensure_one()
        return self.state == "approved" and bool(self.purchase_order_id)

    def write(self, vals):
        """
        Block updates when MR is approved and linked to PO.
        This blocks RPC/import/write/server actions too.
        """
        # Allow only chatter/system fields (optional)
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
            if r._is_locked_by_po():
                # If user tries to change any business field -> block
                changing_business_fields = set(vals.keys()) - allowed_fields
                if changing_business_fields:
                    raise ValidationError(r._lock_message())

        return super(MaterialRequest, self).write(vals)

    def unlink(self):
        """
        Block deletion when MR is approved and linked to PO.
        """
        for r in self:
            if r._is_locked_by_po():
                raise ValidationError(r._lock_message())
        return super(MaterialRequest, self).unlink()


class MaterialRequestLine(models.Model):
    _name = "idil.material.request.line"
    _description = "Material Request Line"
    _order = "id asc"

    request_id = fields.Many2one(
        "idil.material.request",
        string="Material Request",
        ondelete="cascade",
        required=True,
    )

    item_id = fields.Many2one("idil.item", string="Item", required=True)
    requested_qty = fields.Float(string="Requested Qty", required=True, default=1.0)

    # Optional fields for purchase request
    suggested_cost_price = fields.Float(string="Suggested Cost Price")
    expiration_date = fields.Date(string="Expiration Date")

    # Availability display (based on your idil.item.quantity global stock)
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

    @api.depends("item_id")  # You can add request fields if you want refresh on change
    def _compute_available_qty(self):
        Move = self.env["idil.item.movement"].sudo()
        for l in self:
            l.available_qty = 0.0
            if not l.item_id:
                continue

            # Sum ONLY done movements
            domain_base = [
                ("item_id", "=", l.item_id.id),
                ("state", "=", "done"),
            ]

            total_in = (
                sum(
                    Move.search(domain_base + [("movement_type", "=", "in")]).mapped(
                        "quantity"
                    )
                )
                or 0.0
            )

            total_out = (
                sum(
                    Move.search(domain_base + [("movement_type", "=", "out")]).mapped(
                        "quantity"
                    )
                )
                or 0.0
            )

            # Available = In - Out
            l.available_qty = float(total_in) - float(total_out)

    @api.depends("available_qty")
    def _compute_stock_indicator(self):
        for l in self:
            l.stock_indicator = "green" if (l.available_qty or 0.0) > 0 else "red"

    @api.constrains("requested_qty")
    def _check_requested_qty(self):
        for l in self:
            if l.requested_qty <= 0:
                raise ValidationError(_("Requested quantity must be greater than 0."))

    @api.onchange("item_id")
    def _onchange_item_id(self):
        """
        Auto-fill cost price suggestion from item cost_price (your current pattern).
        """
        for l in self:
            if l.item_id:
                l.suggested_cost_price = l.item_id.cost_price
