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
        """Compute due commission using SQL for fresh data and payment status."""
        for rec in self:
            if rec.sales_person_id:
                # Use direct SQL to get only truly unpaid commissions
                # This improved query also checks payment_status to make sure we don't show
                # commissions that are already paid but might have stale computed fields
                rec.env.cr.execute(
                    """
                    SELECT 
                        COUNT(*),
                        COALESCE(SUM(sc.commission_amount - COALESCE(paid.total_paid, 0)), 0)
                    FROM idil_sales_commission sc
                    JOIN idil_sales_sales_personnel sp ON sp.id = sc.sales_person_id
                    LEFT JOIN (
                        SELECT commission_id, SUM(amount) as total_paid
                        FROM idil_sales_commission_payment
                        GROUP BY commission_id
                    ) paid ON paid.commission_id = sc.id
                    LEFT JOIN (
                        SELECT id, payment_status 
                        FROM idil_sales_commission
                    ) status ON status.id = sc.id
                    WHERE sc.sales_person_id = %s
                    AND sp.commission_payment_schedule = 'monthly'
                    AND (status.payment_status != 'paid' OR status.payment_status IS NULL)
                    AND (sc.commission_amount - COALESCE(paid.total_paid, 0)) > 0.001
                    """,
                    (rec.sales_person_id.id,)
                )
                
                result = rec.env.cr.fetchone()
                rec.due_commission_count = result[0] or 0
                rec.due_commission_amount = result[1] or 0.0
            else:
                rec.due_commission_amount = 0.0
                rec.due_commission_count = 0

    @api.onchange("sales_person_id", "amount_to_pay")
    def _onchange_sales_person_id(self):
        """Generate commission lines using SQL for fresh data."""
        # Always clear all existing lines first
        self.line_ids = [(5, 0, 0)]
        
        if not self.sales_person_id:
            return

        # Use SQL to get fresh commission data with actual remaining amounts
        # Also check payment_status to avoid including already paid commissions
        # Using dictionaries for robust column handling
        self.env.cr.execute(
            """
            SELECT 
                sc.id as commission_id,
                sc.date as commission_date,
                sc.commission_amount,
                COALESCE(paid.total_paid, 0) as commission_paid,
                (sc.commission_amount - COALESCE(paid.total_paid, 0)) as commission_remaining,
                status.payment_status
            FROM idil_sales_commission sc
            JOIN idil_sales_sales_personnel sp ON sp.id = sc.sales_person_id
            LEFT JOIN (
                SELECT commission_id, SUM(amount) as total_paid
                FROM idil_sales_commission_payment
                GROUP BY commission_id
            ) paid ON paid.commission_id = sc.id
            LEFT JOIN (
                SELECT id, payment_status 
                FROM idil_sales_commission
            ) status ON status.id = sc.id
            WHERE sc.sales_person_id = %s
            AND sp.commission_payment_schedule = 'monthly'
            AND (status.payment_status != 'paid' OR status.payment_status IS NULL)
            AND (sc.commission_amount - COALESCE(paid.total_paid, 0)) > 0.001
            ORDER BY sc.id ASC
            """,
            (self.sales_person_id.id,)
        )
        commission_data = self.env.cr.dictfetchall()
        
        total_remaining = sum(row['commission_remaining'] for row in commission_data)  # commission_remaining
        
        # Auto-fill amount if it's 0
        if self.amount_to_pay == 0:
            self.amount_to_pay = total_remaining

        if self.amount_to_pay > total_remaining + 0.001:
            self.amount_to_pay = 0
            return {
                "warning": {
                    "title": "Amount Too High",
                    "message": f"Total Amount to Pay cannot exceed the sum of all unpaid commissions ({total_remaining:.2f}).",
                }
            }
            
        # Generate lines based on amount_to_pay
        if self.amount_to_pay > 0:
            lines = []
            remaining_payment = self.amount_to_pay
            for row in commission_data:
                if remaining_payment <= 0:
                    break
                    
                # Use dictionary keys instead of positional values - more robust
                # This way it won't break if we add or change columns in the future
                commission_id = row['commission_id']
                commission_date = row['commission_date']
                commission_amount = row['commission_amount']
                commission_paid = row['commission_paid']
                commission_remaining = row['commission_remaining']
                payment_status = row['payment_status']
                
                if commission_remaining <= 0 or payment_status == 'paid':
                    continue  # already paid or marked as paid

                payable = min(remaining_payment, commission_remaining)
                if payable > 0:
                    lines.append(
                        (
                            0,
                            0,
                            {
                                "commission_id": commission_id,
                                "commission_date": commission_date,
                                "commission_amount": commission_amount,
                                "commission_paid": commission_paid,
                                "commission_remaining": commission_remaining,
                            },
                        )
                    )
                    remaining_payment -= payable
            self.line_ids = lines

    @api.constrains("amount_to_pay", "sales_person_id")
    def _check_amount_to_pay(self):
        """Validate amount doesn't exceed total unpaid commission using SQL."""
        for rec in self:
            if rec.sales_person_id and rec.amount_to_pay:
                # Use SQL to get fresh totals (monthly commissions only)
                rec.env.cr.execute(
                    """
                    SELECT COALESCE(SUM(sc.commission_amount - COALESCE(paid.total_paid, 0)), 0)
                    FROM idil_sales_commission sc
                    JOIN idil_sales_sales_personnel sp ON sp.id = sc.sales_person_id
                    LEFT JOIN (
                        SELECT commission_id, SUM(amount) as total_paid
                        FROM idil_sales_commission_payment
                        GROUP BY commission_id
                    ) paid ON paid.commission_id = sc.id
                    WHERE sc.sales_person_id = %s
                    AND sp.commission_payment_schedule = 'monthly'
                    AND (sc.commission_amount - COALESCE(paid.total_paid, 0)) > 0
                    """,
                    (rec.sales_person_id.id,)
                )
                total_remaining = rec.env.cr.fetchone()[0] or 0.0
                
                if rec.amount_to_pay > total_remaining + 0.001:
                    raise ValidationError(
                        f"Total Amount to Pay ({rec.amount_to_pay:.2f}) cannot exceed total unpaid commission ({total_remaining:.2f}) for this salesperson."
                    )

    def action_confirm_payment(self):
        """Confirm bulk payment with proper validation and accounting."""
        if self.state != "draft":
            return

        # Re-validate total amount against fresh DB data (monthly commissions only)
        # Join with sales_personnel to get payment schedule
        self.env.cr.execute(
            """
            SELECT COALESCE(SUM(sc.commission_amount - COALESCE(paid.total_paid, 0)), 0)
            FROM idil_sales_commission sc
            JOIN idil_sales_sales_personnel sp ON sp.id = sc.sales_person_id
            LEFT JOIN (
                SELECT commission_id, SUM(amount) as total_paid
                FROM idil_sales_commission_payment
                GROUP BY commission_id
            ) paid ON paid.commission_id = sc.id
            WHERE sc.sales_person_id = %s
            AND sp.commission_payment_schedule = 'monthly'
            AND (sc.commission_amount - COALESCE(paid.total_paid, 0)) > 0
            """,
            (self.sales_person_id.id,)
        )
        total_remaining = self.env.cr.fetchone()[0] or 0.0
        
        if self.amount_to_pay > total_remaining + 0.001:
            raise ValidationError(
                f"Amount to pay ({self.amount_to_pay:.2f}) exceeds total unpaid commission ({total_remaining:.2f})."
            )

        cash_account_balance = (
            self.cash_account_id and self._get_cash_account_balance() or 0.0
        )
        if self.amount_to_pay > cash_account_balance:
            raise ValidationError(
                f"Insufficient balance in cash account. Balance: {cash_account_balance:.2f}, Required: {self.amount_to_pay:.2f}"
            )

        remaining_payment = self.amount_to_pay

        for line in self.line_ids:
            if remaining_payment <= 0:
                break

            commission = line.commission_id
            
            # Get fresh remaining from DB to avoid stale cache
            self.env.cr.execute(
                """
                SELECT COALESCE(SUM(amount), 0) 
                FROM idil_sales_commission_payment 
                WHERE commission_id = %s
                """,
                (commission.id,)
            )
            total_paid = self.env.cr.fetchone()[0]
            commission_needed = (commission.commission_amount or 0.0) - total_paid

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
                    ("bulk_payment_line_id", "=", False),
                ],
                order="id desc",
                limit=1,
            )
            if payment:
                payment.bulk_payment_line_id = line.id
                payment.flush_recordset()

            # Force recomputation of commission fields
            commission.invalidate_recordset(
                ['commission_paid', 'commission_remaining', 'payment_status']
            )
            commission._compute_commission_paid()
            commission._compute_commission_remaining()
            commission._compute_payment_status()
            commission.flush_recordset(
                ['commission_paid', 'commission_remaining', 'payment_status']
            )

            # Write to this processed line with fresh data from SQL
            self.env.cr.execute(
                """
                SELECT COALESCE(SUM(amount), 0)
                FROM idil_sales_commission_payment
                WHERE commission_id = %s
                """,
                (commission.id,)
            )
            fresh_paid = self.env.cr.fetchone()[0]
            fresh_remaining = commission.commission_amount - fresh_paid
            
            line.write(
                {
                    "paid_amount": payable,
                    "commission_amount": commission.commission_amount,
                    "commission_id": commission.id,
                    "commission_date": commission.date,
                    "commission_paid": fresh_paid,
                    "commission_remaining": fresh_remaining,
                }
            )
            remaining_payment -= payable

        # Update state to confirmed
        self.write({'state': 'confirmed'})
        
        # Commit changes to database to ensure all updates are persisted
        # This is critical to make sure payment status updates are visible in subsequent queries
        self.env.cr.commit()

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
        """Delete bulk payment and reverse all associated commission payments."""
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
                    # Trigger status recalculation with flush
                    commission.invalidate_recordset(
                        ['commission_paid', 'commission_remaining', 'payment_status']
                    )
                    commission._compute_commission_paid()
                    commission._compute_commission_remaining()
                    commission._compute_payment_status()
                    commission.flush_recordset(
                        ['commission_paid', 'commission_remaining', 'payment_status']
                    )

        return super(SalesCommissionBulkPayment, self).unlink()

    def write(self, vals):
        # Allow state change to 'confirmed' even from draft
        if vals.keys() == {'state'} and vals.get('state') == 'confirmed':
            return super().write(vals)
        
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
