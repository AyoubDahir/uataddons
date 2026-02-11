from odoo import models, fields, api, exceptions
from datetime import datetime
from datetime import date
import re
from odoo.exceptions import ValidationError, UserError
import logging

from odoo.tools import float_round
from odoo.tools.float_utils import float_compare

_logger = logging.getLogger(__name__)


class ManufacturingOrder(models.Model):
    _name = "idil.manufacturing.order"
    _description = "Manufacturing Order"
    _inherit = ["mail.thread", "mail.activity.mixin"]

    company_id = fields.Many2one(
        "res.company", default=lambda s: s.env.company, required=True
    )

    name = fields.Char(string="Order Reference", tracking=True)

    source_warehouse_id = fields.Many2one(
        "idil.warehouse",
        string="🏬 Warehouse",
        required=True,
        tracking=True,
    )

    source_location_id = fields.Many2one(
        "idil.warehouse.location",
        string="📌 Location",
        required=True,
        tracking=True,
        domain="[('warehouse_id', '=', source_warehouse_id), ('active', '=', True)]",
    )

    bom_id = fields.Many2one(
        "idil.bom",
        string="Bill of Materials",
        required=True,
        help="Select the BOM for this manufacturing order",
        tracking=True,
    )
    product_id = fields.Many2one(
        "my_product.product", string="Product", required=True, readonly=True
    )

    product_qty = fields.Float(
        string="Product Quantity",
        default=1,
        required=True,
        help="Quantity of the final product to be produced",
        tracking=True,
    )
    product_cost = fields.Float(
        string="Product Cost Total",
        compute="_compute_product_cost_total",
        digits=(16, 6),
        store=True,
        readonly=True,
    )
    manufacturing_order_line_ids = fields.One2many(
        "idil.manufacturing.order.line",
        "manufacturing_order_id",
        string="Manufacturing Order Lines",
    )
    status = fields.Selection(
        [
            ("draft", "Draft"),
            ("confirmed", "Confirmed"),
            ("in_progress", "In Progress"),
            ("done", "Done"),
            ("cancelled", "Cancelled"),
        ],
        default="draft",
        string="Status",
        tracking=True,
    )
    scheduled_start_date = fields.Datetime(
        string="Scheduled Start Date", tracking=True, required=True
    )
    bom_grand_total = fields.Float(
        string="BOM Grand Total",
        compute="_compute_grand_total",
        store=True,
        readonly=True,
    )
    tfg_qty = fields.Float(
        string="TFG Quantity", compute="_compute_tfg_qty", store=True, readonly=True
    )

    commission_employee_id = fields.Many2one(
        "idil.employee",
        string="Commission Employee",
        help="Select the employee who will receive the commission for this product",
    )
    commission_id = fields.Many2one(
        "idil.commission",
        string="Linked Commission",
        help="Commission linked to this Manufacturing Order",
        ondelete="set null",  # ✅ safe
    )

    # Commission fields
    commission_amount = fields.Float(
        string="Commission Amount",
        digits=(16, 5),
        compute="_compute_commission_amount",
        store=True,
    )
    transaction_booking_id = fields.Many2one(
        "idil.transaction_booking", string="Transaction Booking", readonly=True
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
    )
    rate = fields.Float(
        string="Exchange Rate",
        compute="_compute_exchange_rate",
        store=True,
        readonly=True,
    )

    booking_id = fields.Many2one(
        "idil.transaction_booking",
        string="Journal Entry",
        compute="_compute_booking_preview",
        store=False,
        readonly=True,
    )

    booking_line_ids = fields.One2many(
        "idil.transaction_bookingline",
        "manufacturing_order_id",
        string="Journal Lines",
        readonly=True,
    )

    journal_total_dr = fields.Float(
        string="Total Debits",
        compute="_compute_booking_preview",
        store=False,
        readonly=True,
        digits=(16, 5),
    )
    journal_total_cr = fields.Float(
        string="Total Credits",
        compute="_compute_booking_preview",
        store=False,
        readonly=True,
        digits=(16, 5),
    )
    journal_is_balanced = fields.Boolean(
        string="Balanced",
        compute="_compute_booking_preview",
        store=False,
        readonly=True,
    )

    journal_summary_html = fields.Html(
        string="Journal Summary",
        compute="_compute_journal_summary_html",
        store=False,
        readonly=True,
    )

    @api.depends("booking_line_ids.dr_amount", "booking_line_ids.cr_amount")
    def _compute_booking_preview(self):
        Booking = self.env["idil.transaction_booking"]
        for o in self:
            b = Booking.search(
                [("manufacturing_order_id", "=", o.id)], order="id desc", limit=1
            )
            o.booking_id = b

            if b:
                dr = float(getattr(b, "debit_total", 0.0) or 0.0)
                cr = float(getattr(b, "credit_total", 0.0) or 0.0)
            else:
                dr = sum(o.booking_line_ids.mapped("dr_amount")) or 0.0
                cr = sum(o.booking_line_ids.mapped("cr_amount")) or 0.0

            o.journal_total_dr = dr
            o.journal_total_cr = cr
            o.journal_is_balanced = abs(dr - cr) < 0.00001

    @api.depends(
        "booking_line_ids.account_number",
        "booking_line_ids.dr_amount",
        "booking_line_ids.cr_amount",
    )
    def _compute_journal_summary_html(self):
        for o in self:
            if not o.booking_line_ids:
                o.journal_summary_html = (
                    "<div class='text-muted'>No journal lines yet.</div>"
                )
                continue

            grouped = {}
            for ln in o.booking_line_ids:
                acc = ln.account_number
                if not acc:
                    continue
                key = acc.id
                if key not in grouped:
                    grouped[key] = {
                        "code": getattr(acc, "code", "") or "",
                        "name": acc.name or "",
                        "currency": acc.currency_id.name or "",
                        "dr": 0.0,
                        "cr": 0.0,
                    }
                grouped[key]["dr"] += float(ln.dr_amount or 0.0)
                grouped[key]["cr"] += float(ln.cr_amount or 0.0)

            total_dr = sum(v["dr"] for v in grouped.values())
            total_cr = sum(v["cr"] for v in grouped.values())
            balanced = abs(total_dr - total_cr) < 0.00001

            rows = []
            for v in sorted(grouped.values(), key=lambda x: (x["code"], x["name"])):
                rows.append(
                    f"""
                    <tr>
                        <td style="white-space:nowrap;">{v["code"]}</td>
                        <td>{v["name"]}</td>
                        <td style="text-align:right;">{v["currency"]}</td>
                        <td style="text-align:right;">{v["dr"]:,.5f}</td>
                        <td style="text-align:right;">{v["cr"]:,.5f}</td>
                    </tr>
                    """
                )

            o.journal_summary_html = f"""
            <div style="border:1px solid #e5e7eb; border-radius:12px; padding:12px; background:#fff;">
            <div style="font-weight:700; margin-bottom:8px;">Accounting Entry Summary</div>

            <table style="width:100%; border-collapse:collapse;">
                <thead>
                <tr style="border-bottom:1px solid #e5e7eb;">
                    <th style="text-align:left; padding:6px;">Code</th>
                    <th style="text-align:left; padding:6px;">Account</th>
                    <th style="text-align:right; padding:6px;">Currency</th>
                    <th style="text-align:right; padding:6px;">Dr</th>
                    <th style="text-align:right; padding:6px;">Cr</th>
                </tr>
                </thead>
                <tbody>
                {''.join(rows)}
                </tbody>
                <tfoot>
                <tr style="border-top:1px solid #e5e7eb;">
                    <td colspan="3" style="padding:6px; font-weight:700;">Totals</td>
                    <td style="padding:6px; text-align:right; font-weight:700;">{total_dr:,.5f}</td>
                    <td style="padding:6px; text-align:right; font-weight:700;">{total_cr:,.5f}</td>
                </tr>
                </tfoot>
            </table>

            <div style="margin-top:10px; font-weight:700; color:{'#16a34a' if balanced else '#dc2626'};">
                {'✔ Balanced' if balanced else '✖ Not Balanced'}
            </div>
            </div>
            """

    @api.onchange("source_warehouse_id")
    def _onchange_source_warehouse_id(self):
        for rec in self:
            rec.source_location_id = False

    @api.constrains("scheduled_start_date")
    def _check_scheduled_start_date_not_future(self):
        for record in self:
            if (
                record.scheduled_start_date
                and record.scheduled_start_date.date() > fields.Date.today()
            ):
                raise ValidationError(
                    "Scheduled Start Date cannot be in the future. Please select today or a previous date."
                )

    @api.depends("currency_id", "scheduled_start_date", "company_id")
    def _compute_exchange_rate(self):
        Rate = self.env["res.currency.rate"].sudo()
        for order in self:
            order.rate = 0.0
            if not order.currency_id:
                continue

            # Use the order's date; fallback to today if missing
            doc_date = (
                fields.Date.to_date(order.scheduled_start_date)
                if order.scheduled_start_date
                else fields.Date.today()
            )

            # Get latest rate on or before the doc_date, preferring the order's company, then global (company_id False)
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

    @api.constrains("currency_id", "scheduled_start_date", "company_id")
    def _check_exchange_rate_exists(self):
        Rate = self.env["res.currency.rate"].sudo()
        for order in self:
            if not order.currency_id:
                continue

            doc_date = (
                fields.Date.to_date(order.scheduled_start_date)
                if order.scheduled_start_date
                else fields.Date.today()
            )

            exists = Rate.search_count(
                [
                    ("currency_id", "=", order.currency_id.id),
                    ("name", "<=", doc_date),
                    ("company_id", "in", [order.company_id.id, False]),
                ]
            )

            if not exists:
                raise exceptions.ValidationError(
                    f"No exchange rate for {order.currency_id.name} on or before {doc_date}. "
                    f"Please create a rate for that date (company: {order.company_id.name})."
                )

    @api.depends(
        "product_id",
        "product_qty",
        "commission_employee_id",
        "manufacturing_order_line_ids.quantity",
    )
    def _compute_commission_amount(self):
        for order in self:
            _logger.info(f"Computing commission for order {order.name}")

            if order.product_id:
                _logger.info(
                    f"Product ID: {order.product_id.id}, Product Name: {order.product_id.name}"
                )

                if order.product_id.account_id:
                    _logger.info(
                        f"Product has commission account: {order.product_id.account_id.name}"
                    )

                    if order.product_id.is_commissionable:
                        _logger.info("Product is commissionable")

                        employee = order.commission_employee_id
                        if employee:
                            _logger.info(
                                f"Commission Employee: {employee.name}, Commission Percentage: {employee.commission}"
                            )

                            commission_percentage = employee.commission
                            commission_amount = 0.0

                            # Loop through each item in the order
                            for line in order.manufacturing_order_line_ids:
                                item = line.item_id
                                if item.is_commission:
                                    _logger.info(
                                        f"Item {item.name} has commission flag set to True"
                                    )
                                    # Calculate commission for the item based on quantity
                                    item_commission = (
                                        commission_percentage * line.quantity
                                    )
                                    commission_amount += item_commission

                            order.commission_amount = commission_amount
                            _logger.info(
                                f"Total Commission Amount: {order.commission_amount}"
                            )
                        else:
                            _logger.info("No commission employee assigned")
                            order.commission_amount = 0.0
                    else:
                        _logger.info("Product is not commissionable")
                        order.commission_amount = 0.0
                else:
                    _logger.info("Product does not have a commission account")
                    order.commission_amount = 0.0
            else:
                _logger.info("No product assigned")
                order.commission_amount = 0.0

    @api.depends("manufacturing_order_line_ids.quantity")
    def _compute_tfg_qty(self):
        for order in self:
            tfg_items_qty = sum(
                line.quantity
                for line in order.manufacturing_order_line_ids
                if line.item_id.is_tfg
            )
            order.tfg_qty = order.product_qty / (tfg_items_qty if tfg_items_qty else 1)

    def check_items_expiration(self):
        """Check if any item in the manufacturing order has expired."""
        # Ensure the check is performed on specific order(s)
        for order in self:
            expired_items = []
            for line in order.manufacturing_order_line_ids:
                item = line.item_id
                if item.expiration_date and item.expiration_date < date.today():
                    expired_items.append(item.name)

            if expired_items:
                # Joining the list of expired items names to include in the error message
                expired_items_str = ", ".join(expired_items)
                raise ValidationError(
                    f"Cannot complete the order as the following items have expired: {expired_items_str}. "
                    f"Please update the BOM or the items before proceeding."
                )

    @api.onchange("bom_id")
    def onchange_bom_id(self):
        if self.bom_id:
            # Assuming 'idil.bom' has a 'product_id' field that references the product
            self.product_id = self.bom_id.product_id

    @api.onchange("product_qty")
    def _onchange_product_qty(self):
        if not self.bom_id or not self.product_qty:
            return

        # Ensure product_id is set from bom_id
        if self.bom_id and not self.product_id:
            self.product_id = self.bom_id.product_id

        # Mapping of BOM item IDs to their quantities for easy lookup
        bom_quantities = {
            line.Item_id.id: line.quantity for line in self.bom_id.bom_line_ids
        }

        for line in self.manufacturing_order_line_ids:
            if line.item_id.id in bom_quantities:
                # Calculate the new quantity for this item based on the product_qty
                new_quantity = bom_quantities[line.item_id.id] * self.product_qty

                # Update the line's quantity directly. Since we're in an onchange method,
                # these changes are temporary and reflected in the UI.
                line.quantity = new_quantity
                line.quantity_bom = new_quantity

        # Recalculate commission
        self._compute_commission_amount()

    @api.onchange("commission_employee_id")
    def _onchange_commission_employee_id(self):
        # Ensure product_id is set from bom_id
        if self.bom_id and not self.product_id:
            self.product_id = self.bom_id.product_id

        # Recalculate commission
        self._compute_commission_amount()

    @api.depends("manufacturing_order_line_ids.row_total")
    def _compute_grand_total(self):
        for order in self:
            order.bom_grand_total = sum(
                line.row_total for line in order.manufacturing_order_line_ids
            )

    @api.depends("manufacturing_order_line_ids.row_total", "product_qty")
    def _compute_product_cost_total(self):
        for order in self:
            order.check_items_expiration()
            order.product_cost = sum(
                line.row_total for line in order.manufacturing_order_line_ids
            )

    @api.onchange("bom_id")
    def onchange_bom_id(self):
        self.check_items_expiration()

        # Clear previous lines, product, and quantity if no BOM selected
        if not self.bom_id:
            self.manufacturing_order_line_ids = [(5, 0, 0)]
            self.product_id = False
            self.product_qty = 0.0  # 🔁 Reset to zero
            return

        # Set product based on BOM
        self.product_id = self.bom_id.product_id
        self.product_qty = 0.0  # 🔁 Reset to zero when BOM is changed

        # Load BOM lines into manufacturing order lines
        commands = [(5, 0, 0)]  # Clear old lines
        for bom_line in self.bom_id.bom_line_ids:
            commands.append(
                (
                    0,
                    0,
                    {
                        "item_id": bom_line.Item_id.id,
                        "quantity": bom_line.quantity,
                        "quantity_bom": bom_line.quantity,
                        "cost_price": bom_line.Item_id.cost_price,
                    },
                )
            )
        self.manufacturing_order_line_ids = commands

    @api.model
    def create(self, vals):
        try:
            with self.env.cr.savepoint():
                _logger.info("Creating Manufacturing Order with values: %s", vals)

                # Check BOM and product setup
                if "bom_id" in vals:
                    bom = self.env["idil.bom"].browse(vals["bom_id"])
                    if bom and bom.product_id:
                        vals["product_id"] = bom.product_id.id
                        product = bom.product_id
                        if (
                            product.account_id
                            and product.is_commissionable
                            and not vals.get("commission_employee_id")
                        ):
                            raise ValidationError(
                                "The product has a commission account but no employee is selected."
                            )

                # Set order reference if not provided
                if "name" not in vals or not vals["name"]:
                    vals["name"] = self._generate_order_reference(vals)

                # Set status to done
                vals["status"] = "done"

                # Create order
                order = super(ManufacturingOrder, self).create(vals)

                # Ensure valid asset accounts
                if not order.product_id.asset_account_id:
                    raise ValidationError(
                        f"The product '{order.product_id.name}' does not have a valid asset account."
                    )
                for line in order.manufacturing_order_line_ids:
                    if not line.item_id.asset_account_id:
                        raise ValidationError(
                            f"The item '{line.item_id.name}' does not have a valid asset account."
                        )

                # Check if asset account balance is sufficient
                for line in order.manufacturing_order_line_ids:
                    item_account_balance = self._get_account_balance(
                        line.item_id.asset_account_id.id
                    )
                    required_balance = line.cost_price * line.quantity
                    if item_account_balance < required_balance:
                        raise ValidationError(
                            f"Insufficient balance in account for item '{line.item_id.name}'. "
                            f"Required: {required_balance}, Available: {item_account_balance}"
                        )

                # Create transaction booking record
                transaction_booking = self.env["idil.transaction_booking"].create(
                    {
                        "transaction_number": self.env["ir.sequence"].next_by_code(
                            "idil.transaction_booking"
                        ),
                        "reffno": order.name,
                        "rate": order.rate,
                        "manufacturing_order_id": order.id,
                        "order_number": order.name,
                        "amount": order.product_cost,
                        "trx_date": order.scheduled_start_date,
                        "payment_status": "paid",
                    }
                )

                # Create transaction booking lines individually
                for line in order.manufacturing_order_line_ids:
                    if order.rate <= 0:
                        raise ValidationError("Rate cannot be zero")

                    cost_amount_usd = line.cost_price * line.quantity
                    cost_amount_sos = cost_amount_usd * order.rate

                    # Get clearing accounts
                    source_clearing_account = self.env["idil.chart.account"].search(
                        [
                            ("name", "=", "Exchange Clearing Account"),
                            (
                                "currency_id",
                                "=",
                                line.item_id.asset_account_id.currency_id.id,
                            ),
                        ],
                        limit=1,
                    )
                    target_clearing_account = self.env["idil.chart.account"].search(
                        [
                            ("name", "=", "Exchange Clearing Account"),
                            (
                                "currency_id",
                                "=",
                                order.product_id.asset_account_id.currency_id.id,
                            ),
                        ],
                        limit=1,
                    )

                    if not source_clearing_account or not target_clearing_account:
                        raise ValidationError(
                            "Exchange Clearing Account are required for currency conversion."
                        )

                # DR Product Asset (SOS)
                self.env["idil.transaction_bookingline"].create(
                    {
                        "transaction_booking_id": booking.id,
                        "manufacturing_order_id": order.id,
                        "manufacturing_order_line_id": line.id,
                        "description": "MO - Product Asset (DR)",
                        "item_id": line.item_id.id,
                        "product_id": order.product_id.id,
                        "account_number": order.product_id.asset_account_id.id,
                        "transaction_type": "dr",
                        "dr_amount": float(cost_amount_sos),
                        "cr_amount": 0.0,
                        "transaction_date": order.scheduled_start_date,
                    }
                )

                # CR Target Clearing (SOS)
                self.env["idil.transaction_bookingline"].create(
                    {
                        "transaction_booking_id": booking.id,
                        "manufacturing_order_id": order.id,
                        "manufacturing_order_line_id": line.id,
                        "description": "MO - Target Clearing (CR)",
                        "item_id": line.item_id.id,
                        "product_id": order.product_id.id,
                        "account_number": target_clearing_account.id,
                        "transaction_type": "cr",
                        "dr_amount": 0.0,
                        "cr_amount": float(cost_amount_sos),
                        "transaction_date": order.scheduled_start_date,
                    }
                )

                # DR Source Clearing (USD)
                self.env["idil.transaction_bookingline"].create(
                    {
                        "transaction_booking_id": booking.id,
                        "manufacturing_order_id": order.id,
                        "manufacturing_order_line_id": line.id,
                        "description": "MO - Source Clearing (DR)",
                        "item_id": line.item_id.id,
                        "product_id": order.product_id.id,
                        "account_number": source_clearing_account.id,
                        "transaction_type": "dr",
                        "dr_amount": float(line.row_total),
                        "cr_amount": 0.0,
                        "transaction_date": order.scheduled_start_date,
                    }
                )

                # CR Item Asset (USD)
                self.env["idil.transaction_bookingline"].create(
                    {
                        "transaction_booking_id": booking.id,
                        "manufacturing_order_id": order.id,
                        "manufacturing_order_line_id": line.id,
                        "description": "MO - Item Asset (CR)",
                        "item_id": line.item_id.id,
                        "product_id": order.product_id.id,
                        "account_number": line.item_id.asset_account_id.id,
                        "transaction_type": "cr",
                        "dr_amount": 0.0,
                        "cr_amount": float(line.row_total),
                        "transaction_date": order.scheduled_start_date,
                    }
                )

            # ✅ commission booking lines + commission record
            if order.commission_amount > 0:
                if not order.product_id.account_id:
                    raise ValidationError(
                        f"Product '{order.product_id.name}' missing commission account."
                    )
                if not order.commission_employee_id.account_id:
                    raise ValidationError(
                        f"Employee '{order.commission_employee_id.name}' missing commission account."
                    )

                self.env["idil.transaction_bookingline"].create(
                    {
                        "transaction_booking_id": booking.id,
                        "manufacturing_order_id": order.id,
                        "manufacturing_order_line_id": line.id,
                        "description": "Commission Expense",
                        "product_id": order.product_id.id,
                        "account_number": order.product_id.account_id.id,
                        "transaction_type": "dr",
                        "dr_amount": float(order.commission_amount),
                        "cr_amount": 0.0,
                        "transaction_date": order.scheduled_start_date,
                    }
                )

                self.env["idil.transaction_bookingline"].create(
                    {
                        "transaction_booking_id": booking.id,
                        "manufacturing_order_id": order.id,
                        "manufacturing_order_line_id": line.id,
                        "description": "Commission Liability",
                        "product_id": order.product_id.id,
                        "account_number": order.commission_employee_id.account_id.id,
                        "transaction_type": "cr",
                        "dr_amount": 0.0,
                        "cr_amount": float(order.commission_amount),
                        "transaction_date": order.scheduled_start_date,
                    }
                )

                precision = order.currency_id.decimal_places or 2
                amt = float_round(
                    order.commission_amount or 0.0, precision_digits=precision
                )
                if abs(amt) < 10 ** (-(precision + 1)):
                    amt = 0.0

                commission = self.env["idil.commission"].create(
                    {
                        "manufacturing_order_id": order.id,
                        "employee_id": order.commission_employee_id.id,
                        "commission_amount": amt,
                        "commission_paid": 0,
                        "payment_status": "pending",
                        "commission_remaining": amt,
                        "date": order.scheduled_start_date,
                        "rate": order.rate,
                    }
                )
                order.write({"commission_id": commission.id})

            # ✅ update product actual_cost (weighted avg)
            if order.bom_id and order.bom_id.product_id:
                product = order.bom_id.product_id
                previous_qty = product.stock_quantity or 0.0
                previous_cost = product.actual_cost or 0.0
                new_qty = order.product_qty or 0.0
                new_total_cost = order.product_cost or 0.0

                total_qty = previous_qty + new_qty
                new_average_cost = (
                    ((previous_qty * previous_cost) + new_total_cost) / total_qty
                    if total_qty
                    else 0.0
                )
                product.write({"actual_cost": new_average_cost})

            # ---------------------------------------------
            # -----------------------------
            # ✅ Update Product COST (moving average) on MO confirm
            # (MO cost currency == Product currency, so NO FX)
            # -----------------------------
            product = order.product_id
            produced_qty = float(order.product_qty or 0.0)

            if product and produced_qty > 0:
                # stock BEFORE adding MO product movement
                prev_qty = float(
                    product.stock_quantity or 0.0
                )  # must be current stock now (before movement)
                prev_cost = float(product.cost or 0.0)

                # MO total cost (same currency as product)
                mo_total_cost = float(order.product_cost or 0.0)
                mo_unit_cost = mo_total_cost / produced_qty if produced_qty else 0.0

                total_qty = prev_qty + produced_qty
                new_avg_cost = (
                    ((prev_qty * prev_cost) + (produced_qty * mo_unit_cost)) / total_qty
                    if total_qty
                    else 0.0
                )

                product.write({"cost": round(new_avg_cost, 5)})

            # ✅ movements
            self.env["idil.product.movement"].create(
                {
                    "product_id": order.product_id.id,
                    "movement_type": "in",
                    "manufacturing_order_id": order.id,
                    "quantity": order.product_qty,
                    "date": order.scheduled_start_date,
                    "source_document": order.name,
                    "source_warehouse_id": order.source_warehouse_id.id,
                    "source_location_id": order.source_location_id.id,
                }
            )

                for line in order.manufacturing_order_line_ids:
                    self.env["idil.item.movement"].create(
                        {
                            "item_id": line.item_id.id,
                            "date": order.scheduled_start_date,
                            "manufacturing_order_line_id": line.id,
                            "manufacturing_order_id": order.id,
                            "quantity": -line.quantity,  # consume from Inventory
                            "source": "Inventory",
                            "destination": "Manufacturing",
                            "movement_type": "out",
                            "related_document": f"idil.manufacturing.order.line,{line.id}",
                            "transaction_number": order.name,
                        }
                    )

                return order
        except Exception as e:
            _logger.error(f"Create transaction failed: {str(e)}")
            raise ValidationError(f"Transaction failed: {str(e)}")

    @api.model
    def write(self, vals):
        try:
            with self.env.cr.savepoint():
                for order in self:
                    # Prevent changing BOM or Product after creation
                    if "bom_id" in vals and vals["bom_id"] != order.bom_id.id:
                        raise ValidationError(
                            "You are not allowed to modify the Bill of Materials (BOM) after the order is created. If you need to change it, please delete and recreate the manufacturing order."
                        )

                    if (
                        "product_id" in vals
                        and vals["product_id"] != order.product_id.id
                    ):
                        raise ValidationError(
                            "You are not allowed to modify the Product after the order is created. If you need to change it, please delete and recreate the manufacturing order."
                        )

                    # ... continue your write logic below as before
                    # Store old values for diff calculation
                    old_product_qty = order.product_qty
                    old_lines = {
                        l.id: l.quantity for l in order.manufacturing_order_line_ids
                    }
                    old_item_ids = {
                        l.id: l.item_id.id for l in order.manufacturing_order_line_ids
                    }

                    # --- 1. Apply changes ---
                    res = super(ManufacturingOrder, order).write(vals)

                    # --- 3. Adjust Item Stock and Movement ---
                    for line in order.manufacturing_order_line_ids:
                        old_qty = old_lines.get(line.id, 0.0)
                        new_qty = line.quantity
                        item = line.item_id
                        qty_diff = new_qty - old_qty

                        # Adjust or create movement
                        movement = self.env["idil.item.movement"].search(
                            [
                                (
                                    "related_document",
                                    "=",
                                    f"idil.manufacturing.order.line,{line.id}",
                                )
                            ],
                            limit=1,
                        )
                        if movement:
                            movement.write(
                                {
                                    "quantity": -new_qty,
                                    "date": order.scheduled_start_date,
                                }
                            )

                    # --- 4. Adjust Product Movement ---
                    product_movement = self.env["idil.product.movement"].search(
                        [("manufacturing_order_id", "=", order.id)], limit=1
                    )
                    if product_movement:
                        product_movement.write(
                            {
                                "quantity": order.product_qty,
                                "date": order.scheduled_start_date,
                                "source_document": order.name,
                            }
                        )

                    # --- 5. Adjust Booking and Booking Lines ---
                    # Find booking
                    booking = self.env["idil.transaction_booking"].search(
                        [("manufacturing_order_id", "=", order.id)], limit=1
                    )
                    if booking:
                        # Update booking amount
                        booking.write(
                            {
                                "amount": float(order.product_cost),
                                "trx_date": order.scheduled_start_date,
                            }
                        )

                        # --- Loop each MO line ---
                        for line in order.manufacturing_order_line_ids:
                            cost_usd = line.cost_price * line.quantity
                            cost_sos = cost_usd * (order.rate or 1.0)

                            # 1. Product asset account (Debit)
                            bl = self.env["idil.transaction_bookingline"].search(
                                [
                                    ("transaction_booking_id", "=", booking.id),
                                    ("item_id", "=", line.item_id.id),
                                    (
                                        "account_number",
                                        "=",
                                        order.product_id.asset_account_id.id,
                                    ),
                                    ("transaction_type", "=", "dr"),
                                ],
                                limit=1,
                            )
                            if bl:
                                bl.write(
                                    {
                                        "dr_amount": float(cost_sos),
                                        "cr_amount": 0.0,
                                        "transaction_date": order.scheduled_start_date,
                                    }
                                )
                            # (Optionally create if missing)

                            # 2. Target clearing account (Credit)
                            target_clearing_account = self.env[
                                "idil.chart.account"
                            ].search(
                                [
                                    ("name", "=", "Exchange Clearing Account"),
                                    (
                                        "currency_id",
                                        "=",
                                        order.product_id.asset_account_id.currency_id.id,
                                    ),
                                ],
                                limit=1,
                            )
                            if target_clearing_account:
                                bl = self.env["idil.transaction_bookingline"].search(
                                    [
                                        ("transaction_booking_id", "=", booking.id),
                                        ("item_id", "=", line.item_id.id),
                                        (
                                            "account_number",
                                            "=",
                                            target_clearing_account.id,
                                        ),
                                        ("transaction_type", "=", "cr"),
                                    ],
                                    limit=1,
                                )
                                if bl:
                                    bl.write(
                                        {
                                            "dr_amount": 0.0,
                                            "cr_amount": float(cost_sos),
                                            "transaction_date": order.scheduled_start_date,
                                        }
                                    )

                            # 3. Source clearing account (Debit)
                            source_clearing_account = self.env[
                                "idil.chart.account"
                            ].search(
                                [
                                    ("name", "=", "Exchange Clearing Account"),
                                    (
                                        "currency_id",
                                        "=",
                                        line.item_id.asset_account_id.currency_id.id,
                                    ),
                                ],
                                limit=1,
                            )
                            if source_clearing_account:
                                bl = self.env["idil.transaction_bookingline"].search(
                                    [
                                        ("transaction_booking_id", "=", booking.id),
                                        ("item_id", "=", line.item_id.id),
                                        (
                                            "account_number",
                                            "=",
                                            source_clearing_account.id,
                                        ),
                                        ("transaction_type", "=", "dr"),
                                    ],
                                    limit=1,
                                )
                                if bl:
                                    bl.write(
                                        {
                                            "dr_amount": float(line.row_total),
                                            "cr_amount": 0.0,
                                            "transaction_date": order.scheduled_start_date,
                                        }
                                    )

                            # 4. Item asset account (Credit)
                            bl = self.env["idil.transaction_bookingline"].search(
                                [
                                    ("transaction_booking_id", "=", booking.id),
                                    ("item_id", "=", line.item_id.id),
                                    (
                                        "account_number",
                                        "=",
                                        line.item_id.asset_account_id.id,
                                    ),
                                    ("transaction_type", "=", "cr"),
                                ],
                                limit=1,
                            )
                            if bl:
                                bl.write(
                                    {
                                        "dr_amount": 0.0,
                                        "cr_amount": float(line.row_total),
                                        "transaction_date": order.scheduled_start_date,
                                    }
                                )

                        # --- Commission (if any) ---
                        if order.commission_amount > 0:
                            # Commission expense (Debit)
                            bl = self.env["idil.transaction_bookingline"].search(
                                [
                                    ("transaction_booking_id", "=", booking.id),
                                    ("product_id", "=", order.product_id.id),
                                    (
                                        "account_number",
                                        "=",
                                        order.product_id.account_id.id,
                                    ),
                                    ("transaction_type", "=", "dr"),
                                ],
                                limit=1,
                            )
                            if bl:
                                bl.write(
                                    {
                                        "dr_amount": float(order.commission_amount),
                                        "cr_amount": 0.0,
                                        "transaction_date": order.scheduled_start_date,
                                    }
                                )

                            # Commission liability (Credit)
                            bl = self.env["idil.transaction_bookingline"].search(
                                [
                                    ("transaction_booking_id", "=", booking.id),
                                    ("product_id", "=", order.product_id.id),
                                    (
                                        "account_number",
                                        "=",
                                        order.commission_employee_id.account_id.id,
                                    ),
                                    ("transaction_type", "=", "cr"),
                                ],
                                limit=1,
                            )
                            if bl:
                                bl.write(
                                    {
                                        "dr_amount": 0.0,
                                        "cr_amount": float(order.commission_amount),
                                        "transaction_date": order.scheduled_start_date,
                                    }
                                )

                        # ... handle exchange/currency booking lines if needed

                    # --- 6. Adjust Commission Record and Lines ---
                    commission_amount = order._calculate_commission_amount(order)
                    commission = self.env["idil.commission"].search(
                        [("manufacturing_order_id", "=", order.id)], limit=1
                    )
                    if commission:
                        commission.write(
                            {
                                "commission_amount": commission_amount,
                                "commission_remaining": commission_amount,  # reset if business logic says so
                                "date": order.scheduled_start_date,
                            }
                        )
                    else:
                        if commission_amount > 0 and order.commission_employee_id:
                            commission = self.env["idil.commission"].create(
                                {
                                    "manufacturing_order_id": order.id,
                                    "employee_id": order.commission_employee_id.id,
                                    "commission_amount": commission_amount,
                                    "commission_paid": 0,
                                    "payment_status": "pending",
                                    "commission_remaining": commission_amount,
                                    "date": order.scheduled_start_date,
                                }
                            )
                            order.write({"commission_id": commission.id})

                    return res
        except Exception as e:
            _logger.error(f"Create transaction failed: {str(e)}")
            raise ValidationError(f"Transaction failed: {str(e)}")

    def _get_account_balance(self, account_id):
        """Calculate the balance for an account."""
        self.env.cr.execute(
            """
                    SELECT COALESCE(SUM(dr_amount) - SUM(cr_amount), 0) as balance
                    FROM idil_transaction_bookingline
                    WHERE account_number = %s
                """,
            (account_id,),
        )
        result = self.env.cr.fetchone()
        return result[0] if result else 0.0

    def _generate_order_reference(self, vals):
        bom_id = vals.get("bom_id", False)
        if bom_id:
            bom = self.env["idil.bom"].browse(bom_id)
            bom_name = (
                re.sub("[^A-Za-z0-9]+", "", bom.name[:2]).upper()
                if bom and bom.name
                else "XX"
            )
            date_str = "/" + datetime.now().strftime("%d%m%Y")
            day_night = "/DAY/" if datetime.now().hour < 12 else "/NIGHT/"
            sequence = self.env["ir.sequence"].next_by_code(
                "idil.manufacturing.order.sequence"
            )
            sequence = sequence[-3:] if sequence else "000"
            return f"{bom_name}{date_str}{day_night}{sequence}"
        else:
            # Fallback if no BOM is provided
            return self.env["ir.sequence"].next_by_code(
                "idil.manufacturing.order.sequence"
            )

    def unlink(self):
        try:
            with self.env.cr.savepoint():
                for order in self:
                    # Step 1: Check if enough product stock exists to allow rollback
                    if order.product_id.stock_quantity < order.product_qty:
                        raise ValidationError(
                            f"Cannot delete: Not enough stock to reverse manufacturing for product '{order.product_id.name}'. "
                            f"Required: {order.product_qty}, Available: {order.product_id.stock_quantity}"
                        )
                    res = super(ManufacturingOrder, self).unlink()
                return res
        except Exception as e:
            _logger.error(f"Create transaction failed: {str(e)}")
            raise ValidationError(f"Transaction failed: {str(e)}")

    def _calculate_commission_amount(self, order, order_lines=None):
        # If order_lines are not provided, fallback to record lines
        order_lines = order_lines or order.manufacturing_order_line_ids
        if not order.product_id or not order.commission_employee_id:
            return 0.0
        if not getattr(order.product_id, "account_id", False):
            return 0.0
        if not getattr(order.product_id, "is_commissionable", False):
            return 0.0
        commission_percentage = order.commission_employee_id.commission or 0.0
        commission_amount = 0.0
        for line in order_lines:
            item = line.item_id
            if getattr(item, "is_commission", False):
                commission_amount += commission_percentage * line.quantity
        return commission_amount


class ManufacturingOrderLine(models.Model):
    _name = "idil.manufacturing.order.line"
    _description = "Manufacturing Order Line"
    _inherit = ["mail.thread", "mail.activity.mixin"]

    manufacturing_order_id = fields.Many2one(
        "idil.manufacturing.order",
        string="Manufacturing Order",
        required=True,
        tracking=True,
        ondelete="cascade",  # Add this to enable automatic deletion
    )
    company_id = fields.Many2one(
        related="manufacturing_order_id.company_id", store=True, index=True
    )

    item_id = fields.Many2one("idil.item", string="Item", required=True, tracking=True)
    quantity_bom = fields.Float(
        string="Demand", digits=(16, 5), required=True, tracking=True
    )

    quantity = fields.Float(
        string="Quantity Used", digits=(16, 5), required=True, tracking=True
    )
    cost_price = fields.Float(
        string="Cost Price at Production",
        digits=(16, 5),
        required=True,
        tracking=True,
        store=True,
    )

    row_total = fields.Float(
        string="USD Total", digits=(16, 5), compute="_compute_row_total", store=True
    )
    cost_amount_sos = fields.Float(
        string="SOS Total",
        digits=(16, 5),
        compute="_compute_cost_amount_sos",
        store=True,
    )

    # New computed field for the difference between Demand and Quantity Used
    quantity_diff = fields.Float(
        string="Quantity Difference",
        digits=(16, 5),
        compute="_compute_quantity_diff",
        store=True,
    )

    @api.depends("row_total", "manufacturing_order_id.rate")
    def _compute_cost_amount_sos(self):
        for line in self:
            if line.manufacturing_order_id:
                line.cost_amount_sos = line.row_total * line.manufacturing_order_id.rate

    @api.model
    def create(self, vals):
        try:
            with self.env.cr.savepoint():
                record = super(ManufacturingOrderLine, self).create(vals)
                record._check_min_order_qty()

                return record
        except Exception as e:
            _logger.error(f"transaction failed: {str(e)}")
            raise ValidationError(f"Transaction failed: {str(e)}")

    def write(self, vals):
        result = super(ManufacturingOrderLine, self).write(vals)
        self._check_min_order_qty()
        return result

    def _check_min_order_qty(self):
        for line in self:
            if line.quantity <= line.item_id.min:
                # This is where you decide how to notify the user. For now, let's log a message.
                # Consider replacing this with a call to a custom notification system if needed.
                _logger.info(
                    f"Attention: The quantity for item '{line.item_id.name}' in manufacturing order '{line.item_id.name}' is near or below the minimum order quantity."
                )

    @api.depends("quantity_bom", "quantity")
    def _compute_quantity_diff(self):
        for record in self:
            record.quantity_diff = record.quantity_bom - record.quantity

    @api.depends("quantity", "cost_price")
    def _compute_row_total(self):
        for line in self:
            line.row_total = line.quantity * line.cost_price
