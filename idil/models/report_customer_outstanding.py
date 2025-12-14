from odoo import models, fields, api
from odoo.exceptions import ValidationError
from datetime import timedelta


class CustomerOutstandingWizard(models.TransientModel):
    _name = "idil.customer.outstanding.wizard"
    _description = "Customer Outstanding Balance Report Wizard"

    as_of_date = fields.Date(
        string="As of Date",
        required=True,
        default=fields.Date.context_today,
    )
    customer_id = fields.Many2one(
        "idil.customer.registration",
        string="Customer",
        help="Leave empty for all customers",
    )
    salesperson_id = fields.Many2one(
        "idil.sales.sales_personnel",
        string="Salesperson",
        help="Leave empty for all salespersons",
    )
    min_balance = fields.Float(
        string="Minimum Balance",
        default=0,
        help="Only show balances greater than this amount",
    )
    include_salesperson_ar = fields.Boolean(
        string="Include Salesperson AR",
        default=True,
        help="Include salesperson accounts receivable",
    )

    def action_print_report(self):
        data = {
            "as_of_date": self.as_of_date.strftime("%Y-%m-%d"),
            "customer_id": self.customer_id.id if self.customer_id else False,
            "customer_name": self.customer_id.name if self.customer_id else "All Customers",
            "salesperson_id": self.salesperson_id.id if self.salesperson_id else False,
            "salesperson_name": self.salesperson_id.name if self.salesperson_id else "All Salespersons",
            "min_balance": self.min_balance,
            "include_salesperson_ar": self.include_salesperson_ar,
        }
        return self.env.ref("idil.action_report_customer_outstanding").report_action(
            self, data=data
        )


class ReportCustomerOutstanding(models.AbstractModel):
    _name = "report.idil.report_customer_outstanding_template"
    _description = "Customer Outstanding Balance Report"

    @api.model
    def _get_report_values(self, docids, data=None):
        if not data:
            raise ValidationError("No data provided for report")

        as_of_date = data.get("as_of_date")
        customer_id = data.get("customer_id")
        salesperson_id = data.get("salesperson_id")
        min_balance = data.get("min_balance", 0)
        include_salesperson_ar = data.get("include_salesperson_ar", True)

        today = fields.Date.today()
        outstanding_data = []

        # Customer Outstanding from Sales Receipts
        receipt_domain = [("payment_status", "=", "pending")]
        if customer_id:
            receipt_domain.append(("customer_id", "=", customer_id))
        if salesperson_id:
            receipt_domain.append(("salesperson_id", "=", salesperson_id))

        receipts = self.env["idil.sales.receipt"].search(receipt_domain)

        # Group by customer
        customer_balances = {}
        for receipt in receipts:
            balance = receipt.due_amount - receipt.paid_amount
            if balance <= min_balance:
                continue

            # Determine the key (customer or salesperson)
            if receipt.customer_id:
                key = ("customer", receipt.customer_id.id)
                name = receipt.customer_id.name
                contact = receipt.customer_id.phone if hasattr(receipt.customer_id, 'phone') else ""
            elif receipt.salesperson_id and include_salesperson_ar:
                key = ("salesperson", receipt.salesperson_id.id)
                name = receipt.salesperson_id.name
                contact = receipt.salesperson_id.phone if hasattr(receipt.salesperson_id, 'phone') else ""
            else:
                continue

            if key not in customer_balances:
                customer_balances[key] = {
                    "type": key[0].title(),
                    "name": name,
                    "contact": contact,
                    "total_due": 0,
                    "total_paid": 0,
                    "outstanding": 0,
                    "receipt_count": 0,
                    "oldest_date": None,
                    "receipts": [],
                }

            customer_balances[key]["total_due"] += receipt.due_amount
            customer_balances[key]["total_paid"] += receipt.paid_amount
            customer_balances[key]["outstanding"] += balance
            customer_balances[key]["receipt_count"] += 1

            receipt_date = receipt.receipt_date.date() if receipt.receipt_date else today
            if customer_balances[key]["oldest_date"] is None or receipt_date < customer_balances[key]["oldest_date"]:
                customer_balances[key]["oldest_date"] = receipt_date

            customer_balances[key]["receipts"].append({
                "reference": receipt.name or f"REC-{receipt.id}",
                "date": receipt_date.strftime("%Y-%m-%d"),
                "due_amount": receipt.due_amount,
                "paid_amount": receipt.paid_amount,
                "balance": balance,
                "age_days": (today - receipt_date).days,
            })

        # Calculate aging buckets and prepare final data
        for key, data_item in customer_balances.items():
            if data_item["oldest_date"]:
                data_item["days_outstanding"] = (today - data_item["oldest_date"]).days
                data_item["oldest_date"] = data_item["oldest_date"].strftime("%Y-%m-%d")
            else:
                data_item["days_outstanding"] = 0
                data_item["oldest_date"] = ""

            # Aging buckets
            data_item["bucket_0_30"] = sum(r["balance"] for r in data_item["receipts"] if r["age_days"] <= 30)
            data_item["bucket_31_60"] = sum(r["balance"] for r in data_item["receipts"] if 31 <= r["age_days"] <= 60)
            data_item["bucket_61_90"] = sum(r["balance"] for r in data_item["receipts"] if 61 <= r["age_days"] <= 90)
            data_item["bucket_90_plus"] = sum(r["balance"] for r in data_item["receipts"] if r["age_days"] > 90)

            outstanding_data.append(data_item)

        # Sort by outstanding amount descending
        outstanding_data.sort(key=lambda x: x["outstanding"], reverse=True)

        # Calculate totals
        total_outstanding = sum(d["outstanding"] for d in outstanding_data)
        total_0_30 = sum(d["bucket_0_30"] for d in outstanding_data)
        total_31_60 = sum(d["bucket_31_60"] for d in outstanding_data)
        total_61_90 = sum(d["bucket_61_90"] for d in outstanding_data)
        total_90_plus = sum(d["bucket_90_plus"] for d in outstanding_data)

        return {
            "doc_ids": docids,
            "doc_model": "idil.customer.outstanding.wizard",
            "docs": self,
            "data": {
                "as_of_date": as_of_date,
                "customer_name": data.get("customer_name"),
                "salesperson_name": data.get("salesperson_name"),
                "min_balance": min_balance,
                "customers": outstanding_data,
                "total_customers": len(outstanding_data),
                "total_outstanding": total_outstanding,
                "total_0_30": total_0_30,
                "total_31_60": total_31_60,
                "total_61_90": total_61_90,
                "total_90_plus": total_90_plus,
            },
        }
