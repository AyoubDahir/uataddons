from odoo import models, fields, api
from odoo.exceptions import ValidationError


# BOM Model
class BOM(models.Model):
    _name = "idil.bom"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _description = "Bill of Materials"

    name = fields.Char(string="BOM Name", required=True)
    type_id = fields.Many2one(
        comodel_name="idil.bom.type",
        string="BOM Types",
        required=True,
        help="Select type of BOM",
        tracking=True,
    )
    product_id = fields.Many2one(
        "my_product.product", string="Component", required=True, tracking=True
    )

    bom_line_ids = fields.One2many(
        "idil.bom.line", "bom_id", string="BOM Lines", tracking=True
    )

    # Computed field to calculate total cost based on BOM lines
    total_cost = fields.Float(
        string="Total Cost",
        digits=(16, 5),
        compute="_compute_total_cost",
        store=True,
        tracking=True,
    )
    currency_id = fields.Many2one(
        "res.currency",
        string="Currency",
        compute="_compute_currency_id",
        store=True,
        readonly=True,
        tracking=True,
    )

    is_mixed_currency = fields.Boolean(
        string="Mixed Currency BOM",
        compute="_compute_is_mixed_currency",
        store=True,
        help="Indicates if BOM contains items with different currencies",
    )

    @api.depends("bom_line_ids", "bom_line_ids.Item_id")
    def _compute_currency_id(self):
        for bom in self:
            currency = None
            all_same = True
            for line in bom.bom_line_ids:
                line_currency = line.Item_id.currency_id
                if not currency:
                    currency = line_currency
                elif line_currency != currency:
                    all_same = False
                    break
            # For mixed currency BOMs, set to False (will be handled per-line)
            bom.currency_id = currency if all_same else False

    @api.depends("bom_line_ids", "bom_line_ids.currency_id")
    def _compute_is_mixed_currency(self):
        for bom in self:
            currencies = set()
            for line in bom.bom_line_ids:
                if line.Item_id and line.Item_id.currency_id:
                    currencies.add(line.Item_id.currency_id.id)
            bom.is_mixed_currency = len(currencies) > 1

    @api.depends("bom_line_ids.total", "bom_line_ids.currency_id", "product_id.cost_value_currency_id")
    def _compute_total_cost(self):
        for bom in self:
            if not bom.product_id:
                bom.total_cost = round(sum(line.total for line in bom.bom_line_ids), 5)
                continue
            
            # Use product.cost_value_currency_id for consistency
            product_currency = bom.product_id.cost_value_currency_id
            if not product_currency:
                bom.total_cost = round(sum(line.total for line in bom.bom_line_ids), 5)
                continue
            
            total = 0.0
            for line in bom.bom_line_ids:
                line_currency = line.currency_id
                line_total = line.total or 0.0
                
                if not line_currency or line_currency.id == product_currency.id:
                    # Same currency - no conversion needed
                    total += line_total
                else:
                    # Need currency conversion
                    rate = self._get_current_exchange_rate()
                    if rate and rate > 0:
                        if line_currency.name == "USD" and product_currency.name == "SL":
                            # USD to SL: multiply by rate
                            total += line_total * rate
                        elif line_currency.name == "SL" and product_currency.name == "USD":
                            # SL to USD: divide by rate
                            total += line_total / rate
                        else:
                            # Unknown conversion - add as-is (fallback)
                            total += line_total
                    else:
                        # No rate available - add as-is
                        total += line_total
            
            bom.total_cost = round(total, 5)
    
    def _get_current_exchange_rate(self):
        """Get current exchange rate (SL per 1 USD)"""
        rate_record = self.env["res.currency.rate"].search(
            [("currency_id.name", "=", "SL")],
            order="name desc",
            limit=1,
        )
        return rate_record.rate if rate_record else 0.0


# BOM Line Model
class BOMLine(models.Model):
    _name = "idil.bom.line"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _description = "BOM Line"

    Item_id = fields.Many2one(
        "idil.item", string="Component", required=True, tracking=True
    )
    quantity = fields.Float(string="Quantity", digits=(16, 5), required=True)
    # 🔹 Directly show the item's cost_price (not computed)
    cost_price = fields.Float(
        string="Cost Price",
        digits=(16, 5),
        related="Item_id.cost_price",
        store=True,
        readonly=True,
        tracking=True,
    )
    bom_id = fields.Many2one(
        "idil.bom", string="BOM", ondelete="cascade", tracking=True
    )
    currency_id = fields.Many2one(
        "res.currency",
        string="Currency",
        related="Item_id.currency_id",
        store=True,
        readonly=True,
        tracking=True,
    )
    # 🔹 Optional: Show total for this line (cost_price × quantity)
    total = fields.Float(
        string="Line Total",
        compute="_compute_line_total",
        digits=(16, 5),
        store=False,
        readonly=True,
        tracking=True,
    )

    # Ensure that a BOM line is not duplicated for the same item
    _sql_constraints = [
        (
            "unique_bom_line_item",
            "unique(bom_id, Item_id)",
            "Item already exists in BOM lines!",
        ),
    ]

    @api.depends("cost_price", "quantity")
    def _compute_line_total(self):
        for line in self:
            line.total = round(line.cost_price * line.quantity, 5)

    @api.model
    def create(self, values):
        # Check if the item already exists in BOM lines for this BOM
        existing_line = self.search(
            [
                ("bom_id", "=", values.get("bom_id")),
                ("Item_id", "=", values.get("Item_id")),
            ],
            limit=1,
        )

        if existing_line:
            # If the item exists, update the quantity instead of creating a new line
            existing_line.write(
                {"quantity": existing_line.quantity + values.get("quantity", 0)}
            )
            return existing_line
        else:
            # If the item doesn't exist, proceed with normal creation
            return super(BOMLine, self).create(values)
