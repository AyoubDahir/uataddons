from odoo import models, fields, api
from odoo.exceptions import ValidationError
from datetime import datetime

import logging

from odoo.tools import float_compare

_logger = logging.getLogger(__name__)


class item(models.Model):
    _name = "idil.item"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _description = "Idil Purchased Items"

    company_id = fields.Many2one(
        "res.company",
        string="Company",
        required=True,
        default=lambda self: self.env.company,
        index=True,
    )

    ITEM_TYPE_SELECTION = [
        ("service", "Service"),
        ("inventory", "Inventory"),
        ("non_inventory", "Non-Inventory"),
        ("discount", "Discount"),
        ("payment", "Payment"),
        ("tax", "Tax"),
        ("mileage", "Mileage"),
        # Add more QuickBooks item types as needed
    ]
    name = fields.Char(string="Item Name", required=True, tracking=True)
    active = fields.Boolean(string="Archive", default=True, tracking=True)

    description = fields.Text(string="Description", tracking=True)
    item_type = fields.Selection(
        selection=ITEM_TYPE_SELECTION, string="Item Type", required=True, tracking=True
    )

    quantity = fields.Float(
        string="Quantity",
        compute="_compute_stock_quantity",
        digits=(16, 5),
        store=False,  # do NOT store, so it reflects real-time movement
        help="Quantity in stock, computed from movement history (IN - OUT)",
    )

    purchase_date = fields.Date(
        string="Purchase Date", required=True, tracking=True, default=fields.Date.today
    )
    expiration_date = fields.Date(
        string="Expiration Date", required=True, tracking=True
    )
    item_category_id = fields.Many2one(
        comodel_name="idil.item.category",
        string="Item Category",
        required=True,
        help="Select Item Category",
        tracking=True,
    )
    unitmeasure_id = fields.Many2one(
        comodel_name="idil.unit.measure",
        string="Unit of Measure",
        required=True,
        help="Select Unit of Measure",
        tracking=True,
    )
    min = fields.Float(string="Min Order", required=True, tracking=True)

    cost_price = fields.Float(
        string="Price per Unit", digits=(16, 5), required=True, tracking=True
    )

    allergens = fields.Char(string="Allergens/Ingredients", tracking=True)
    image = fields.Binary(string=" Image")
    order_information = fields.Char(string="Order Information", tracking=True)
    bar_code = fields.Char(string="Bar Code", tracking=True)
    # Currency fields
    currency_id = fields.Many2one(
        "res.currency",
        string="Currency",
        required=True,
        default=lambda self: self.env.company.currency_id,
    )

    purchase_account_id = fields.Many2one(
        "idil.chart.account",
        string="Purchase Account",
        help="Account to report purchases of this item",
        required=True,
        tracking=True,
        domain="[('account_type', 'like', 'COGS'), ('currency_id', '=', currency_id), ('header_name', '=', 'Expenses')]",
    )

    landing_account_id = fields.Many2one(
        "idil.chart.account",
        string="Landing/Freight Expense Account",
        domain="[('currency_id', '=', currency_id), ('header_name', '=', 'Expenses')]",
        required=False,
    )

    sales_account_id = fields.Many2one(
        "idil.chart.account",
        string="Sales Account",
        help="Account to report sales of this item",
        tracking=True,
        domain="[('header_name', '=', 'Income'), ('currency_id', '=', currency_id)]",
    )
    asset_account_id = fields.Many2one(
        "idil.chart.account",
        string="Asset Account",
        help="Account to report Asset of this item",
        required=True,
        tracking=True,
        domain="[('header_name', '=', 'Assets'),('currency_id', '=', currency_id)]",
    )

    adjustment_account_id = fields.Many2one(
        "idil.chart.account",
        string="Adjustment Account",
        help="Account to report adjustment of this item",
        required=True,
        tracking=True,
        domain="['|', ('header_name', '=', 'Assets'), ('header_name', '=', 'Expenses'), ('currency_id', '=', currency_id), ('account_type', '=', 'Adjustment' )]",
    )

    days_until_expiration = fields.Integer(
        string="Days Until Expiration",
        compute="_compute_days_until_expiration",
        store=True,
        readonly=True,
    )
    # New computed field
    total_price = fields.Float(
        string="Total Price",
        compute="compute_item_total_value",
        store=False,
        digits=(16, 5),
        tracking=True,
    )

    is_tfg = fields.Boolean(string="Is TFG", default=False, tracking=True)
    is_commission = fields.Boolean(string="Is Commission", default=False, tracking=True)

    # New field to track item movements
    movement_ids = fields.One2many(
        "idil.item.movement", "item_id", string="Item Movements"
    )

    @api.depends("movement_ids.quantity", "movement_ids.movement_type")
    def _compute_stock_quantity(self):
        for product in self:
            qty_in = sum(
                m.quantity for m in product.movement_ids if m.movement_type == "in"
            )
            qty_out = sum(
                m.quantity for m in product.movement_ids if m.movement_type == "out"
            )
            product.quantity = round(qty_in + qty_out, 5)

    # Add a method to update currency_id for existing records
    def update_currency_id(self):
        usd_currency = self.env.ref("base.USD")
        self.search([]).write({"currency_id": usd_currency.id})

    @api.onchange("currency_id")
    def _onchange_currency_id(self):
        """Clear account fields when currency changes to force reselection"""
        if self.currency_id:
            # Keep the accounts if they match the currency, otherwise clear them
            if (
                self.purchase_account_id
                and self.purchase_account_id.currency_id != self.currency_id
            ):
                self.purchase_account_id = False
            if (
                self.sales_account_id
                and self.sales_account_id.currency_id != self.currency_id
            ):
                self.sales_account_id = False
            if (
                self.asset_account_id
                and self.asset_account_id.currency_id != self.currency_id
            ):
                self.asset_account_id = False
            if (
                self.adjustment_account_id
                and self.adjustment_account_id.currency_id != self.currency_id
            ):
                self.adjustment_account_id = False

    @api.onchange("item_type")
    def _onchange_item_type(self):
        """Try to load default accounts based on existing items of same type and currency"""
        if self.item_type and self.currency_id:
            # For new records, the ID might be a NewId (string) which causes SQL errors
            # when comparing with database IDs (integers)
            if not self._origin.id:
                # This is a new record, just search without excluding self
                existing_items = self.search(
                    [
                        ("item_type", "=", self.item_type),
                        ("currency_id", "=", self.currency_id.id),
                    ],
                    limit=1,
                )
            else:
                # This is an existing record, exclude self from search
                existing_items = self.search(
                    [
                        ("item_type", "=", self.item_type),
                        ("currency_id", "=", self.currency_id.id),
                        ("id", "!=", self._origin.id),
                    ],
                    limit=1,
                )

            # If found, copy the accounts
            if existing_items:
                if not self.purchase_account_id and existing_items.purchase_account_id:
                    self.purchase_account_id = existing_items.purchase_account_id
                if not self.sales_account_id and existing_items.sales_account_id:
                    self.sales_account_id = existing_items.sales_account_id
                if not self.asset_account_id and existing_items.asset_account_id:
                    self.asset_account_id = existing_items.asset_account_id
                if (
                    not self.adjustment_account_id
                    and existing_items.adjustment_account_id
                ):
                    self.adjustment_account_id = existing_items.adjustment_account_id

    @api.depends_context("uid")
    def compute_item_total_value(self):
        """Compute total value per item: sum(dr_amount - cr_amount) where account is asset_account_id."""
        for item in self:
            item.total_price = 0.0  # Default value

            if not item.asset_account_id:
                continue

            self.env.cr.execute(
                """
                SELECT 
                    COALESCE(SUM(dr_amount), 0) - COALESCE(SUM(cr_amount), 0) AS balance
                FROM idil_transaction_bookingline
                WHERE item_id = %s AND account_number = %s
            """,
                (item.id, item.asset_account_id.id),
            )

            result = self.env.cr.fetchone()
            item.total_price = round(result[0], 5) if result and result[0] else 0.0

    def get_available_accounts(self):
        """Debug function to check available accounts for the item"""
        if not self.currency_id:
            return {"error": "Currency not set"}

        # Make safe currency_id reference
        currency_id = self.currency_id.id
        if not isinstance(currency_id, int):
            # If we have a problem with the currency ID, try to get it safely
            try:
                currency_id = int(currency_id)
            except (ValueError, TypeError):
                return {"error": "Invalid currency ID format"}

        # Check for available purchase accounts
        purchase_accounts = self.env["idil.chart.account"].search(
            [
                ("account_type", "like", "COGS"),
                ("currency_id", "=", currency_id),
                ("header_name", "=", "Expenses"),
            ]
        )

        # Check for available sales accounts
        sales_accounts = self.env["idil.chart.account"].search(
            [("header_name", "=", "Income"), ("currency_id", "=", currency_id)]
        )

        # Check for available asset accounts
        asset_accounts = self.env["idil.chart.account"].search(
            [("header_name", "=", "Assets"), ("currency_id", "=", currency_id)]
        )

        # Check for available adjustment accounts
        adjustment_accounts = self.env["idil.chart.account"].search(
            [
                "|",
                ("header_name", "=", "Assets"),
                ("header_name", "=", "Expenses"),
                ("currency_id", "=", currency_id),
                ("account_type", "=", "Adjustment"),
            ]
        )

        return {
            "purchase_accounts": purchase_accounts.mapped("name"),
            "sales_accounts": sales_accounts.mapped("name"),
            "asset_accounts": asset_accounts.mapped("name"),
            "adjustment_accounts": adjustment_accounts.mapped("name"),
            "count": {
                "purchase": len(purchase_accounts),
                "sales": len(sales_accounts),
                "asset": len(asset_accounts),
                "adjustment": len(adjustment_accounts),
            },
        }

    @api.constrains("name")
    def _check_unique_name(self):
        for record in self:
            if self.search([("name", "=", record.name), ("id", "!=", record.id)]):
                raise ValidationError(
                    'Item name must be unique. The name "%s" is already in use.'
                    % record.name
                )

    @api.depends("expiration_date")
    def _compute_days_until_expiration(self):
        for record in self:
            if record.expiration_date:
                delta = record.expiration_date - fields.Date.today()
                record.days_until_expiration = delta.days
            else:
                record.days_until_expiration = 0

    @api.constrains("purchase_date", "expiration_date")
    def check_date_not_in_past(self):
        for record in self:
            today = fields.Date.today()
            if record.expiration_date < today:
                raise ValidationError(
                    "Expiration dates must be today or in the future."
                )

    # @api.constrains("quantity", "cost_price")
    # def _check_positive_values(self):
    #     for record in self:
    #         if record.quantity < 0:
    #             raise ValidationError("Quantity must be a positive value.")
    #         if record.cost_price < 0:
    #             raise ValidationError("Cost price must be a positive value.")

    def check_reorder(self):
        """Send notifications for items that need reordering."""
        for record in self:
            if record.quantity < record.min:
                # Logic to send notification or create a reorder
                record.message_post(
                    body=f"Item {record.name} needs reordering. Current stock: {record.quantity}"
                )


class ItemMovement(models.Model):
    _name = "idil.item.movement"
    _description = "Item Movement"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "id desc"

    item_id = fields.Many2one("idil.item", string="Item", required=True, tracking=True)
    date = fields.Date(
        string="Date", required=True, default=fields.Date.today, tracking=True
    )
    quantity = fields.Float(string="Quantity", required=True, tracking=True)
    # ✅ Proper Transfer Traceability (structured)

    source = fields.Char(string="Source", required=True, tracking=True)

    source_warehouse_id = fields.Many2one(
        "idil.warehouse", string="🏬 From Warehouse", tracking=True
    )
    source_location_id = fields.Many2one(
        "idil.warehouse.location",
        string="📤 From Location",
        tracking=True,
        domain="[('warehouse_id', '=', source_warehouse_id), ('active', '=', True)]",
    )

    destination_warehouse_id = fields.Many2one(
        "idil.warehouse", string="🏬 To Warehouse", tracking=True
    )
    destination_location_id = fields.Many2one(
        "idil.warehouse.location",
        string="📥 To Location",
        tracking=True,
        domain="[('warehouse_id', '=', destination_warehouse_id), ('active', '=', True)]",
    )

    state = fields.Selection(
        [("draft", "Draft"), ("done", "Done"), ("cancel", "Cancelled")],
        default="done",
        tracking=True,
    )

    destination = fields.Char(string="Destination", required=True, tracking=True)
    movement_type = fields.Selection(
        [
            ("in", "In"),
            ("out", "Out"),
            ("internal", "Internal Transfer"),
        ],
        string="Movement Type",
        required=True,
        tracking=True,
    )
    related_document = fields.Reference(
        selection=[
            ("idil.purchase_order.line", "Purchase Order Line"),
            ("idil.purchase.receipt", "Purchase Receipt"),
            ("idil.manufacturing.order.line", "Manufacturing Order Line"),
            ("idil.stock.adjustment", "Stock Adjustment"),
            ("idil.purchase_return.line", "Purchase Return Line"),
            ("idil.item.opening.balance.line", "Item Opening Balance Line"),
            ("idil.material.request", "Material Request"),
            ("idil.internal.transfer.line", "Internal Transfer Line"),
            ("idil.internal.transfer", "Internal Transfer"),
        ],
        string="Related Document",
    )

    vendor_id = fields.Many2one(
        "idil.vendor.registration",
        string="Vendor",
        tracking=True,
        help="Vendor associated with this movement if it originated from a purchase order",
    )

    # product_id = fields.Many2one(
    #     "my_product.product",
    #     string="Product",
    #     tracking=True,
    #     help="Product associated with this movement if it relates to a manufacturing order",
    # )

    transaction_number = fields.Char(string="Transaction Number", tracking=True)

    purchase_order_line_id = fields.Many2one(
        "idil.purchase_order.line",
        string="Purchase Order Line",
        ondelete="cascade",  # Enables automatic deletion
        index=True,
    )
    item_opening_balance_id = fields.Many2one(
        "idil.item.opening.balance",
        string="Item Opening Balance",
        ondelete="cascade",  # ✅ auto-delete booking when opening balance is deleted
        index=True,
    )
    purchase_return_id = fields.Many2one(
        "idil.purchase_return",
        string="Purchase Return",
        ondelete="cascade",
    )

    manufacturing_order_line_id = fields.Many2one(
        "idil.manufacturing.order.line",
        string="Manufacturing Order Line",
        ondelete="cascade",  # DB cascades movements when the line is deleted
        index=True,
        tracking=True,
    )

    manufacturing_order_id = fields.Many2one(
        "idil.manufacturing.order",
        string="Manufacturing Order",
        ondelete="cascade",
        index=True,
        tracking=True,
    )
    # ✅ Link movement to received purchase history
    received_purchase_id = fields.Many2one(
        "idil.received.purchase",
        string="Received Purchase History",
        ondelete="cascade",  # ✅ auto delete movements when parent is deleted
        index=True,
        tracking=True,
    )

    @api.constrains(
        "movement_type",
        "source_warehouse_id",
        "destination_warehouse_id",
        "source_location_id",
        "destination_location_id",
    )
    def _check_internal_transfer_fields(self):
        for m in self:
            if m.movement_type != "internal":
                continue

            if not m.source_warehouse_id or not m.destination_warehouse_id:
                raise ValidationError(
                    _("Internal transfer requires From Warehouse and To Warehouse.")
                )

            if not m.source_location_id or not m.destination_location_id:
                raise ValidationError(
                    _("Internal transfer requires From Location and To Location.")
                )

            # prevent same exact place
            if (
                m.source_warehouse_id.id == m.destination_warehouse_id.id
                and m.source_location_id.id == m.destination_location_id.id
            ):
                raise ValidationError(
                    _("From and To cannot be the same warehouse/location.")
                )

    @api.constrains("item_id", "movement_type", "quantity", "date")
    def _check_enough_stock_on_out(self):
        """
        Prevent negative stock for any OUT movement, evaluated as of the movement's date.
        Uses your formula: IN + OUT (where OUT is stored negative).
        """
        precision = 5  # matches digits=(16,5)

        for m in self:
            if not m.item_id or m.movement_type != "out":
                continue

            # Stock balance as of this movement (including it)
            self.env.cr.execute(
                """
                SELECT
                    COALESCE(SUM(CASE WHEN movement_type = 'in'  THEN quantity ELSE 0 END), 0)
                + COALESCE(SUM(CASE WHEN movement_type = 'out' THEN quantity ELSE 0 END), 0)
                FROM idil_item_movement
                WHERE item_id = %s
                AND (date < %s OR (date = %s AND id <= %s))
            """,
                (m.item_id.id, m.date, m.date, m.id),
            )
            (resulting_balance,) = self.env.cr.fetchone()
            resulting_balance = resulting_balance or 0.0

            # Balance BEFORE this record = after - this movement qty
            available_before = resulting_balance - (m.quantity or 0.0)

            if float_compare(resulting_balance, 0.0, precision_digits=precision) < 0:
                raise ValidationError(
                    "Insufficient stock for item '{name}' as of {date}. "
                    "Available: {avail:.5f} | Requested: {req:.5f} | "
                    "Resulting Balance: {res:.5f}".format(
                        name=m.item_id.name,
                        date=m.date,
                        avail=round(available_before, precision),
                        req=round(m.quantity or 0.0, precision),
                        res=round(resulting_balance, precision),
                    )
                )
