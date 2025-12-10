from odoo import models, fields, api
from odoo.exceptions import ValidationError


class SalesCommissionBulkPayment(models.Model):
    _name = "idil.sales.commission.bulk.payment"
    _description = "Sales Commission Bulk Payment"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "id desc"

    name = fields.Char(string="Reference", default="New", readonly=True, copy=False)
    sales_person_id = fields.Many2one(
        "idil.sales.sales_personnel",
        string="Salesperson",
        required=True,
        domain=[("commission_payment_schedule", "=", "monthly")],
    )
    amount_to_pay = fields.Float(
        string="Total Amount to Pay", required=True, store=True
    )
    cash_account_id = fields.Many2one(
        "idil.chart.account",
        string="Cash/Bank Account",
        required=True,
        domain=[("account_type", "in", ["cash", "bank_transfer"])],
    )
    date = fields.Date(default=fields.Date.context_today, string="Date")
    line_ids = fields.One2many(
        "idil.sales.commission.bulk.payment.line",
        "bulk_payment_id",
        string="Commission Lines",
    )
    state = fields.Selection(
        [("draft", "Draft"), ("confirmed", "Confirmed")],
        default="draft",
        string="Status",
    )
    due_commission_amount = fields.Float(
        string="Total Due Commission Amount",
        compute="_compute_due_commission",
        store=False,
    )
    due_commission_count = fields.Integer(
        string="Number of Due Commissions",
        compute="_compute_due_commission",
        store=False,
    )

    @api.depends("sales_person_id")
    def _compute_due_commission(self):
        for rec in self:
            if rec.sales_person_id:
                unpaid_commissions = rec.env["idil.sales.commission"].search(
                    [
                        ("sales_person_id", "=", rec.sales_person_id.id),
                        ("payment_status", "!=", "paid"),
                        ("payment_schedule", "=", "monthly"),
                    ]
                )
                rec.due_commission_amount = sum(
                    c.commission_remaining for c in unpaid_commissions
                )
                rec.due_commission_count = len(unpaid_commissions)
            else:
                rec.due_commission_amount = 0.0
                rec.due_commission_count = 0

    @api.onchange("sales_person_id", "amount_to_pay")
    def _onchange_sales_person_id(self):
        # Always clear all existing lines first
        self.line_ids = [(5, 0, 0)]
        
        if not self.sales_person_id:
            return

        unpaid_commissions = self.env["idil.sales.commission"].search(
            [
                ("sales_person_id", "=", self.sales_person_id.id),
                ("payment_status", "!=", "paid"),
                ("payment_schedule", "=", "monthly"),
            ],
            order="id asc",
        )
        total_remaining = sum(c.commission_remaining for c in unpaid_commissions)
        
        # Auto-fill amount if it's 0
        if self.amount_to_pay == 0:
            self.amount_to_pay = total_remaining

        if self.amount_to_pay > total_remaining:
            self.amount_to_pay = 0
            return {
                "warning": {
                    "title": "Amount Too High",
                    "message": f"Total Amount to Pay cannot exceed the sum of all unpaid commissions ({total_remaining}).",
                }
            }
            
        # Generate lines based on amount_to_pay
        if self.amount_to_pay > 0:
            lines = []
            remaining_payment = self.amount_to_pay
            for commission in unpaid_commissions:
                if remaining_payment <= 0:
                    break
                commission_needed = commission.commission_remaining
                if commission_needed <= 0:
                    continue  # already paid

                payable = min(remaining_payment, commission_needed)
                if payable > 0:
                    lines.append(
                        (
                            0,
                            0,
                            {
                                "commission_id": commission.id,
                                "commission_date": commission.date,
                                "commission_amount": commission.commission_amount,
                                "commission_paid": commission.commission_paid,
                                "commission_remaining": commission.commission_remaining,
                            },
                        )
                    )
                    remaining_payment -= payable
            self.line_ids = lines

    @api.constrains("amount_to_pay", "sales_person_id")
    def _check_amount_to_pay(self):
        for rec in self:
            if rec.sales_person_id and rec.amount_to_pay:
                unpaid_commissions = rec.env["idil.sales.commission"].search(
                    [
                        ("sales_person_id", "=", rec.sales_person_id.id),
                        ("payment_status", "!=", "paid"),
                        ("payment_schedule", "=", "monthly"),
                    ]
                )
                total_remaining = sum(
                    c.commission_remaining for c in unpaid_commissions
                )
                if rec.amount_to_pay > total_remaining:
                    raise ValidationError(
                        f"Total Amount to Pay ({rec.amount_to_pay}) cannot exceed total unpaid commission ({total_remaining}) for this salesperson."
                    )

    def action_confirm_payment(self):
        if self.state != "draft":
            return

        cash_account_balance = (
            self.cash_account_id and self._get_cash_account_balance() or 0.0
        )
        if self.amount_to_pay > cash_account_balance:
            raise ValidationError(
                f"Insufficient balance in cash account. Balance: {cash_account_balance}, Required: {self.amount_to_pay}"
            )

        remaining_payment = self.amount_to_pay

        for line in self.line_ids:
            if remaining_payment <= 0:
                break

            commission = line.commission_id
            commission_needed = commission.commission_remaining

            if commission_needed <= 0:
                continue

            # Amount to pay for this commission (full or partial)
            payable = min(remaining_payment, commission_needed)
            if payable <= 0:
                break

            # Set the payment fields on the commission and trigger payment
            commission.cash_account_id = self.cash_account_id
            commission.amount_to_pay = payable
            commission.pay_commission()

            # Find the latest commission payment just created
            payment = self.env["idil.sales.commission.payment"].search(
                [
                    ("commission_id", "=", commission.id),
                    ("sales_person_id", "=", commission.sales_person_id.id),
                    ("amount", "=", payable),
                    ("bulk_payment_line_id", "=", False),
                ],
                order="id desc",
                limit=1,
            )
            if payment:
                payment.bulk_payment_line_id = line.id

            # Write only to this processed line
            line.write(
                {
                    "paid_amount": payable,
                    "commission_amount": commission.commission_amount,
                    "commission_id": commission.id,
                    "commission_date": commission.date,
                    "commission_paid": commission.commission_paid,
                    "commission_remaining": commission.commission_remaining,
                }
            )
            remaining_payment -= payable

        self.state = "confirmed"

    def _get_cash_account_balance(self):
        self.env.cr.execute(
            """
            SELECT COALESCE(SUM(dr_amount), 0) - COALESCE(SUM(cr_amount), 0)
            FROM idil_transaction_bookingline
            WHERE account_number = %s
            """,
            (self.cash_account_id.id,),
        )
        return self.env.cr.fetchone()[0]

    @api.model
    def create(self, vals):
        if vals.get("name", "New") == "New":
            vals["name"] = (
                self.env["ir.sequence"].next_by_code(
                    "idil.sales.commission.bulk.payment.seq"
                )
                or "SCBP/0001"
            )
        return super().create(vals)

    def unlink(self):
        for bulk in self:
            # For each line in the bulk payment
            for line in bulk.line_ids:
                # Find commission payments linked to this bulk payment line
                commission_payments = self.env["idil.sales.commission.payment"].search(
                    [("bulk_payment_line_id", "=", line.id)]
                )
                
                for payment in commission_payments:
                    commission = payment.commission_id
                    # Delete the payment (this will delete associated transactions via unlink)
                    payment.unlink()
                    # Trigger status recalculation
                    commission._compute_commission_paid()
                    commission._compute_commission_remaining()
                    commission._compute_payment_status()

        return super(SalesCommissionBulkPayment, self).unlink()

    def write(self, vals):
        for rec in self:
            if rec.state == "confirmed":
                raise ValidationError(
                    "This record is confirmed and cannot be modified.\n"
                    "If changes are required, please delete and create a new bulk payment."
                )
        return super().write(vals)


class SalesCommissionBulkPaymentLine(models.Model):
    _name = "idil.sales.commission.bulk.payment.line"
    _description = "Sales Commission Bulk Payment Line"
    _order = "id desc"

    bulk_payment_id = fields.Many2one(
        "idil.sales.commission.bulk.payment", string="Bulk Payment"
    )
    commission_id = fields.Many2one(
        "idil.sales.commission", string="Commission", required=True
    )
    commission_date = fields.Date(string="Commission Date", readonly=True, store=True)

    commission_amount = fields.Float(
        string="Commission Amount", readonly=True, store=True
    )
    commission_paid = fields.Float(string="Already Paid", readonly=True, store=True)
    commission_remaining = fields.Float(string="Remaining", readonly=True, store=True)
    paid_amount = fields.Float(string="Paid Now", readonly=True, store=True)
    
    # Related Fields
    sale_order_id = fields.Many2one(
        related="commission_id.sale_order_id",
        string="Sale Order",
        readonly=True,
        store=True,
    )
    commission_status = fields.Selection(
        related="commission_id.payment_status",
        string="Status",
        readonly=True,
        store=True,
    )
