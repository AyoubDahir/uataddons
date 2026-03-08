from odoo import models, fields, api, _
from odoo.tools.float_utils import float_compare


class UnbalancedTransactionReport(models.TransientModel):
    _name = "idil.unbalanced.transaction.report"
    _description = "Unbalanced Transaction Report"
    _order = "transaction_booking_id desc"

    transaction_booking_id = fields.Many2one(
        "idil.transaction_booking",
        string="Transaction Booking",
        readonly=True,
    )
    transaction_number = fields.Integer(string="Transaction No", readonly=True)
    reffno = fields.Char(string="Reference", readonly=True)
    trx_date = fields.Date(string="Transaction Date", readonly=True)
    company_id = fields.Many2one("res.company", string="Company", readonly=True)

    debit_total = fields.Float(string="Total Debit", digits=(16, 5), readonly=True)
    credit_total = fields.Float(string="Total Credit", digits=(16, 5), readonly=True)
    difference = fields.Float(string="Difference", digits=(16, 5), readonly=True)

    vendor_id = fields.Many2one(
        "idil.vendor.registration", string="Vendor", readonly=True
    )
    customer_id = fields.Many2one(
        "idil.customer.registration", string="Customer", readonly=True
    )
    sales_person_id = fields.Many2one(
        "idil.sales.sales_personnel", string="Sales Person", readonly=True
    )
    purchase_order_id = fields.Many2one(
        "idil.purchase_order", string="Purchase Order", readonly=True
    )
    sale_order_id = fields.Many2one(
        "idil.sale.order", string="Sale Order", readonly=True
    )
    payment_method = fields.Selection(
        [
            ("cash", "Cash"),
            ("ap", "A/P"),
            ("bank_transfer", "Bank Transfer"),
            ("other", "Other"),
            ("internal", "Internal"),
            ("receivable", "A/R"),
            ("opening_balance", "Opening Balance"),
            ("pos", "POS"),
            ("bulk_payment", "Bulk Payment"),
            ("commission_payment", "Commission Payment"),
        ],
        string="Payment Method",
        readonly=True,
    )
    line_count = fields.Integer(string="Lines", readonly=True)

    def action_open_booking(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Transaction Booking"),
            "res_model": "idil.transaction_booking",
            "res_id": self.transaction_booking_id.id,
            "view_mode": "form",
            "target": "current",
        }


class UnbalancedTransactionWizard(models.TransientModel):
    _name = "idil.unbalanced.transaction.wizard"
    _description = "Find Unbalanced Transactions"

    company_id = fields.Many2one(
        "res.company",
        string="Company",
        default=lambda self: self.env.company,
    )
    date_from = fields.Date(string="From Date")
    date_to = fields.Date(string="To Date")

    def action_find_unbalanced_transactions(self):
        self.ensure_one()

        Report = self.env["idil.unbalanced.transaction.report"]
        Report.search([("create_uid", "=", self.env.uid)]).unlink()

        query = """
            SELECT
                tb.id AS booking_id,
                tb.transaction_number,
                tb.reffno,
                tb.trx_date,
                tb.company_id,
                tb.vendor_id,
                tb.customer_id,
                tb.sales_person_id,
                tb.purchase_order_id,
                tb.sale_order_id,
                tb.payment_method,
                COUNT(tbl.id) AS line_count,
                COALESCE(SUM(tbl.dr_amount), 0) AS debit_total,
                COALESCE(SUM(tbl.cr_amount), 0) AS credit_total,
                COALESCE(SUM(tbl.dr_amount), 0) - COALESCE(SUM(tbl.cr_amount), 0) AS difference
            FROM idil_transaction_booking tb
            JOIN idil_transaction_bookingline tbl
                ON tbl.transaction_booking_id = tb.id
            WHERE 1=1
        """
        params = []

        if self.company_id:
            query += " AND tb.company_id = %s"
            params.append(self.company_id.id)

        if self.date_from:
            query += " AND tb.trx_date >= %s"
            params.append(self.date_from)

        if self.date_to:
            query += " AND tb.trx_date <= %s"
            params.append(self.date_to)

        query += """
            GROUP BY
                tb.id,
                tb.transaction_number,
                tb.reffno,
                tb.trx_date,
                tb.company_id,
                tb.vendor_id,
                tb.customer_id,
                tb.sales_person_id,
                tb.purchase_order_id,
                tb.sale_order_id,
                tb.payment_method
            HAVING ROUND(COALESCE(SUM(tbl.dr_amount), 0)::numeric, 5)
                 <> ROUND(COALESCE(SUM(tbl.cr_amount), 0)::numeric, 5)
            ORDER BY tb.id DESC
        """

        self.env.cr.execute(query, tuple(params))
        rows = self.env.cr.dictfetchall()

        created_ids = []
        precision = self.env["decimal.precision"].precision_get("Account")

        for row in rows:
            # extra safety
            if (
                float_compare(
                    row["debit_total"] or 0.0,
                    row["credit_total"] or 0.0,
                    precision_digits=precision,
                )
                != 0
            ):
                rec = Report.create(
                    {
                        "transaction_booking_id": row["booking_id"],
                        "transaction_number": row["transaction_number"],
                        "reffno": row["reffno"],
                        "trx_date": row["trx_date"],
                        "company_id": row["company_id"],
                        "vendor_id": row["vendor_id"],
                        "customer_id": row["customer_id"],
                        "sales_person_id": row["sales_person_id"],
                        "purchase_order_id": row["purchase_order_id"],
                        "sale_order_id": row["sale_order_id"],
                        "payment_method": row["payment_method"],
                        "line_count": row["line_count"],
                        "debit_total": row["debit_total"],
                        "credit_total": row["credit_total"],
                        "difference": row["difference"],
                    }
                )
                created_ids.append(rec.id)

        return {
            "type": "ir.actions.act_window",
            "name": _("Unbalanced Transactions"),
            "res_model": "idil.unbalanced.transaction.report",
            "view_mode": "tree,form",
            "domain": [("id", "in", created_ids)],
            "target": "current",
        }
