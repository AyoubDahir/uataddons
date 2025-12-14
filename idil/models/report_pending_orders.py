from odoo import models, fields, api
from odoo.exceptions import ValidationError
from datetime import timedelta


class PendingOrdersWizard(models.TransientModel):
    _name = "idil.pending.orders.wizard"
    _description = "Pending Orders Report Wizard"

    order_type = fields.Selection(
        [
            ("all", "All Orders"),
            ("sales", "Sales Orders"),
            ("customer", "Customer Orders"),
            ("salesperson", "Salesperson Place Orders"),
        ],
        string="Order Type",
        required=True,
        default="all",
    )
    salesperson_id = fields.Many2one(
        "idil.sales.sales_personnel",
        string="Salesperson",
        help="Leave empty for all salespersons",
    )
    customer_id = fields.Many2one(
        "idil.customer.registration",
        string="Customer",
        help="Leave empty for all customers",
    )
    days_old = fields.Integer(
        string="Older Than (Days)",
        default=0,
        help="Show orders older than this many days (0 = all pending)",
    )

    def action_print_report(self):
        data = {
            "order_type": self.order_type,
            "salesperson_id": self.salesperson_id.id if self.salesperson_id else False,
            "salesperson_name": self.salesperson_id.name if self.salesperson_id else "All",
            "customer_id": self.customer_id.id if self.customer_id else False,
            "customer_name": self.customer_id.name if self.customer_id else "All",
            "days_old": self.days_old,
        }
        return self.env.ref("idil.action_report_pending_orders").report_action(
            self, data=data
        )


class ReportPendingOrders(models.AbstractModel):
    _name = "report.idil.report_pending_orders_template"
    _description = "Pending Orders Report"

    @api.model
    def _get_report_values(self, docids, data=None):
        if not data:
            raise ValidationError("No data provided for report")

        order_type = data.get("order_type", "all")
        salesperson_id = data.get("salesperson_id")
        customer_id = data.get("customer_id")
        days_old = data.get("days_old", 0)

        today = fields.Date.today()
        cutoff_date = today - timedelta(days=days_old) if days_old > 0 else False

        orders_data = []

        # Sales Orders (Draft)
        if order_type in ["all", "sales"]:
            domain = [("state", "=", "draft")]
            if salesperson_id:
                domain.append(("sales_person_id", "=", salesperson_id))
            if cutoff_date:
                domain.append(("order_date", "<=", cutoff_date))

            sales_orders = self.env["idil.sale.order"].search(domain, order="order_date asc")
            for order in sales_orders:
                age = (today - order.order_date.date()).days if order.order_date else 0
                orders_data.append({
                    "type": "Sales Order",
                    "reference": order.name or f"SO-{order.id}",
                    "date": order.order_date.strftime("%Y-%m-%d") if order.order_date else "",
                    "salesperson": order.sales_person_id.name if order.sales_person_id else "",
                    "customer": "",
                    "total": order.order_total,
                    "age_days": age,
                    "status": "Draft",
                })

        # Customer Orders (Draft)
        if order_type in ["all", "customer"]:
            domain = [("state", "=", "draft")]
            if customer_id:
                domain.append(("customer_id", "=", customer_id))
            if cutoff_date:
                domain.append(("order_date", "<=", cutoff_date))

            customer_orders = self.env["idil.customer.sale.order"].search(domain, order="order_date asc")
            for order in customer_orders:
                age = (today - order.order_date.date()).days if order.order_date else 0
                orders_data.append({
                    "type": "Customer Order",
                    "reference": order.name or f"CO-{order.id}",
                    "date": order.order_date.strftime("%Y-%m-%d") if order.order_date else "",
                    "salesperson": "",
                    "customer": order.customer_id.name if order.customer_id else "",
                    "total": order.order_total,
                    "age_days": age,
                    "status": "Draft",
                })

        # Salesperson Place Orders (Draft)
        if order_type in ["all", "salesperson"]:
            domain = [("status", "=", "draft")]
            if salesperson_id:
                domain.append(("sales_person_id", "=", salesperson_id))
            if cutoff_date:
                domain.append(("order_date", "<=", cutoff_date))

            place_orders = self.env["idil.salesperson.place.order"].search(domain, order="order_date asc")
            for order in place_orders:
                age = (today - order.order_date.date()).days if order.order_date else 0
                orders_data.append({
                    "type": "Place Order",
                    "reference": order.name or f"PO-{order.id}",
                    "date": order.order_date.strftime("%Y-%m-%d") if order.order_date else "",
                    "salesperson": order.sales_person_id.name if order.sales_person_id else "",
                    "customer": "",
                    "total": order.order_total if hasattr(order, 'order_total') else 0,
                    "age_days": age,
                    "status": "Draft",
                })

        # Sort by age (oldest first)
        orders_data.sort(key=lambda x: x["age_days"], reverse=True)

        # Calculate summaries
        total_value = sum(o["total"] for o in orders_data)
        avg_age = sum(o["age_days"] for o in orders_data) / len(orders_data) if orders_data else 0
        old_orders = len([o for o in orders_data if o["age_days"] > 7])

        return {
            "doc_ids": docids,
            "doc_model": "idil.pending.orders.wizard",
            "docs": self,
            "data": {
                "order_type": order_type,
                "salesperson_name": data.get("salesperson_name"),
                "customer_name": data.get("customer_name"),
                "days_old": days_old,
                "report_date": today.strftime("%Y-%m-%d"),
                "orders": orders_data,
                "total_orders": len(orders_data),
                "total_value": total_value,
                "avg_age": avg_age,
                "old_orders_count": old_orders,
            },
        }
