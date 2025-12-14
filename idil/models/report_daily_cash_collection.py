from odoo import models, fields, api
from odoo.exceptions import ValidationError


class DailyCashCollectionWizard(models.TransientModel):
    _name = "idil.daily.cash.collection.wizard"
    _description = "Daily Cash Collection Report Wizard"

    date = fields.Date(
        string="Date",
        required=True,
        default=fields.Date.context_today,
    )
    salesperson_id = fields.Many2one(
        "idil.sales.sales_personnel",
        string="Salesperson",
        help="Leave empty for all salespersons",
    )
    payment_method_id = fields.Many2one(
        "idil.chart.account",
        string="Payment Account",
        domain=[("account_type", "in", ["cash", "bank_transfer"])],
        help="Leave empty for all payment methods",
    )

    def action_print_report(self):
        data = {
            "date": self.date.strftime("%Y-%m-%d"),
            "salesperson_id": self.salesperson_id.id if self.salesperson_id else False,
            "salesperson_name": self.salesperson_id.name if self.salesperson_id else "All Salespersons",
            "payment_method_id": self.payment_method_id.id if self.payment_method_id else False,
            "payment_method_name": self.payment_method_id.name if self.payment_method_id else "All Methods",
        }
        return self.env.ref("idil.action_report_daily_cash_collection").report_action(
            self, data=data
        )


class ReportDailyCashCollection(models.AbstractModel):
    _name = "report.idil.report_daily_cash_collection_template"
    _description = "Daily Cash Collection Report"

    @api.model
    def _get_report_values(self, docids, data=None):
        if not data:
            raise ValidationError("No data provided for report")

        date = data.get("date")
        salesperson_id = data.get("salesperson_id")
        payment_method_id = data.get("payment_method_id")

        # Build domain for sales payments
        domain = [("payment_date", ">=", f"{date} 00:00:00"), ("payment_date", "<=", f"{date} 23:59:59")]

        # Get sales receipts for the date
        receipt_domain = [
            ("receipt_date", ">=", f"{date} 00:00:00"),
            ("receipt_date", "<=", f"{date} 23:59:59"),
        ]
        if salesperson_id:
            receipt_domain.append(("salesperson_id", "=", salesperson_id))

        receipts = self.env["idil.sales.receipt"].search(receipt_domain)

        # Get payments for the date
        payment_domain = [
            ("payment_date", ">=", f"{date} 00:00:00"),
            ("payment_date", "<=", f"{date} 23:59:59"),
        ]
        payments = self.env["idil.sales.payment"].search(payment_domain)

        # Group by salesperson
        salesperson_data = {}
        for receipt in receipts:
            sp_name = receipt.salesperson_id.name if receipt.salesperson_id else "Direct/Customer"
            sp_id = receipt.salesperson_id.id if receipt.salesperson_id else 0
            
            if sp_id not in salesperson_data:
                salesperson_data[sp_id] = {
                    "name": sp_name,
                    "total_sales": 0,
                    "total_collected": 0,
                    "receipt_count": 0,
                }
            
            salesperson_data[sp_id]["total_sales"] += receipt.due_amount
            salesperson_data[sp_id]["total_collected"] += receipt.paid_amount
            salesperson_data[sp_id]["receipt_count"] += 1

        # Group by payment method
        payment_method_data = {}
        for payment in payments:
            if payment_method_id and payment.payment_account.id != payment_method_id:
                continue
                
            pm_name = payment.payment_account.name if payment.payment_account else "Unknown"
            pm_id = payment.payment_account.id if payment.payment_account else 0
            
            if pm_id not in payment_method_data:
                payment_method_data[pm_id] = {
                    "name": pm_name,
                    "amount": 0,
                    "count": 0,
                }
            
            payment_method_data[pm_id]["amount"] += payment.paid_amount
            payment_method_data[pm_id]["count"] += 1

        # Calculate totals
        total_sales = sum(sp["total_sales"] for sp in salesperson_data.values())
        total_collected = sum(sp["total_collected"] for sp in salesperson_data.values())
        total_by_method = sum(pm["amount"] for pm in payment_method_data.values())

        return {
            "doc_ids": docids,
            "doc_model": "idil.daily.cash.collection.wizard",
            "docs": self,
            "data": {
                "date": date,
                "salesperson_name": data.get("salesperson_name"),
                "payment_method_name": data.get("payment_method_name"),
                "salesperson_summary": list(salesperson_data.values()),
                "payment_method_summary": list(payment_method_data.values()),
                "total_sales": total_sales,
                "total_collected": total_collected,
                "total_by_method": total_by_method,
                "collection_rate": (total_collected / total_sales * 100) if total_sales > 0 else 0,
            },
        }
