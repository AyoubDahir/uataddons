from odoo import models, fields, api
from odoo.exceptions import ValidationError


class LowStockAlertWizard(models.TransientModel):
    _name = "idil.low.stock.alert.wizard"
    _description = "Low Stock Alert Report Wizard"

    threshold = fields.Integer(
        string="Stock Threshold",
        required=True,
        default=10,
        help="Show items with quantity below this threshold",
    )
    category_id = fields.Many2one(
        "idil.item.category",
        string="Category",
        help="Leave empty for all categories",
    )
    include_zero_stock = fields.Boolean(
        string="Include Zero Stock",
        default=True,
        help="Include items with zero quantity",
    )

    def action_print_report(self):
        data = {
            "threshold": self.threshold,
            "category_id": self.category_id.id if self.category_id else False,
            "category_name": self.category_id.name if self.category_id else "All Categories",
            "include_zero_stock": self.include_zero_stock,
        }
        return self.env.ref("idil.action_report_low_stock_alert").report_action(
            self, data=data
        )


class ReportLowStockAlert(models.AbstractModel):
    _name = "report.idil.report_low_stock_alert_template"
    _description = "Low Stock Alert Report"

    @api.model
    def _get_report_values(self, docids, data=None):
        if not data:
            raise ValidationError("No data provided for report")

        threshold = data.get("threshold", 10)
        category_id = data.get("category_id")
        include_zero_stock = data.get("include_zero_stock", True)

        # Build domain
        domain = [("quantity", "<", threshold)]
        if not include_zero_stock:
            domain.append(("quantity", ">", 0))
        if category_id:
            domain.append(("item_category_id", "=", category_id))

        items = self.env["idil.item"].search(domain, order="quantity asc")

        # Prepare item data
        item_list = []
        total_value_at_risk = 0
        for item in items:
            shortage = threshold - item.quantity
            value_needed = shortage * item.cost_price if shortage > 0 else 0
            
            item_list.append({
                "name": item.name,
                "category": item.item_category_id.name if item.item_category_id else "Uncategorized",
                "quantity": item.quantity,
                "unit": item.unitmeasure_id.name if item.unitmeasure_id else "",
                "cost_price": item.cost_price,
                "current_value": item.quantity * item.cost_price,
                "shortage": shortage,
                "value_needed": value_needed,
                "status": "Critical" if item.quantity == 0 else "Low",
            })
            total_value_at_risk += value_needed

        # Summary stats
        critical_count = len([i for i in item_list if i["status"] == "Critical"])
        low_count = len([i for i in item_list if i["status"] == "Low"])

        return {
            "doc_ids": docids,
            "doc_model": "idil.low.stock.alert.wizard",
            "docs": self,
            "data": {
                "threshold": threshold,
                "category_name": data.get("category_name"),
                "items": item_list,
                "total_items": len(item_list),
                "critical_count": critical_count,
                "low_count": low_count,
                "total_value_at_risk": total_value_at_risk,
                "report_date": fields.Date.today().strftime("%Y-%m-%d"),
            },
        }
