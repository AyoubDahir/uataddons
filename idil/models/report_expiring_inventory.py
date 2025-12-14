from odoo import models, fields, api
from odoo.exceptions import ValidationError
from datetime import timedelta


class ExpiringInventoryWizard(models.TransientModel):
    _name = "idil.expiring.inventory.wizard"
    _description = "Expiring Inventory Report Wizard"

    days_ahead = fields.Integer(
        string="Days Ahead",
        required=True,
        default=30,
        help="Show items expiring within this many days",
    )
    category_id = fields.Many2one(
        "idil.item.category",
        string="Category",
        help="Leave empty for all categories",
    )
    include_expired = fields.Boolean(
        string="Include Already Expired",
        default=True,
        help="Include items that have already expired",
    )

    def action_print_report(self):
        data = {
            "days_ahead": self.days_ahead,
            "category_id": self.category_id.id if self.category_id else False,
            "category_name": self.category_id.name if self.category_id else "All Categories",
            "include_expired": self.include_expired,
        }
        return self.env.ref("idil.action_report_expiring_inventory").report_action(
            self, data=data
        )


class ReportExpiringInventory(models.AbstractModel):
    _name = "report.idil.report_expiring_inventory_template"
    _description = "Expiring Inventory Report"

    @api.model
    def _get_report_values(self, docids, data=None):
        if not data:
            raise ValidationError("No data provided for report")

        days_ahead = data.get("days_ahead", 30)
        category_id = data.get("category_id")
        include_expired = data.get("include_expired", True)

        today = fields.Date.today()
        future_date = today + timedelta(days=days_ahead)

        # Get item movements with expiration dates
        domain = [("expiration_date", "<=", future_date)]
        if not include_expired:
            domain.append(("expiration_date", ">=", today))
        
        # Search in purchase order lines which have expiration dates
        po_lines = self.env["idil.purchase_order.line"].search(domain)

        # Group by item and expiration date
        expiry_data = {}
        for line in po_lines:
            if category_id and line.item_id.item_category_id.id != category_id:
                continue
                
            key = (line.item_id.id, line.expiration_date)
            if key not in expiry_data:
                expiry_data[key] = {
                    "item_name": line.item_id.name,
                    "category": line.item_id.item_category_id.name if line.item_id.item_category_id else "Uncategorized",
                    "expiration_date": line.expiration_date,
                    "quantity": 0,
                    "cost_price": line.cost_price,
                    "value_at_risk": 0,
                    "days_until_expiry": (line.expiration_date - today).days,
                }
            
            expiry_data[key]["quantity"] += line.quantity
            expiry_data[key]["value_at_risk"] = expiry_data[key]["quantity"] * expiry_data[key]["cost_price"]

        # Convert to list and sort by expiration date
        item_list = sorted(expiry_data.values(), key=lambda x: x["expiration_date"])

        # Categorize items
        expired_items = [i for i in item_list if i["days_until_expiry"] < 0]
        critical_items = [i for i in item_list if 0 <= i["days_until_expiry"] <= 7]
        warning_items = [i for i in item_list if 7 < i["days_until_expiry"] <= 30]
        upcoming_items = [i for i in item_list if i["days_until_expiry"] > 30]

        # Add status to each item
        for item in item_list:
            if item["days_until_expiry"] < 0:
                item["status"] = "Expired"
                item["status_color"] = "#c62828"
            elif item["days_until_expiry"] <= 7:
                item["status"] = "Critical"
                item["status_color"] = "#ef6c00"
            elif item["days_until_expiry"] <= 30:
                item["status"] = "Warning"
                item["status_color"] = "#f9a825"
            else:
                item["status"] = "Upcoming"
                item["status_color"] = "#2e7d32"

        total_value_at_risk = sum(i["value_at_risk"] for i in item_list)
        expired_value = sum(i["value_at_risk"] for i in expired_items)

        return {
            "doc_ids": docids,
            "doc_model": "idil.expiring.inventory.wizard",
            "docs": self,
            "data": {
                "days_ahead": days_ahead,
                "category_name": data.get("category_name"),
                "report_date": today.strftime("%Y-%m-%d"),
                "items": item_list,
                "total_items": len(item_list),
                "expired_count": len(expired_items),
                "critical_count": len(critical_items),
                "warning_count": len(warning_items),
                "total_value_at_risk": total_value_at_risk,
                "expired_value": expired_value,
            },
        }
