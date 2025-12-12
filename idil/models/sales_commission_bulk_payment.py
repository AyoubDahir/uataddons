from odoo import models, fields, api
from odoo.exceptions import ValidationError
import logging

_logger = logging.getLogger(__name__)

# VERSION MARKER: v2.0 - Added duplicate payment prevention
# If you see this in logs, the new code is running
MODULE_VERSION = "2.0"


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
                # SIMPLIFIED QUERY: Only check actual remaining amounts from payments
                # This is the most reliable way to determine what's still owed
                rec.env.cr.execute(
                    """
                    SELECT 
                        COUNT(*),
                        COALESCE(SUM(remaining), 0)
                    FROM (
                        SELECT 
                            sc.id,
                            sc.commission_amount - COALESCE((
                                SELECT SUM(amount) 
                                FROM idil_sales_commission_payment 
                                WHERE commission_id = sc.id
                            ), 0) as remaining
                        FROM idil_sales_commission sc
                        JOIN idil_sales_sales_personnel sp ON sp.id = sc.sales_person_id
                        WHERE sc.sales_person_id = %s
                        AND sp.commission_payment_schedule = 'monthly'
                    ) sub
                    WHERE remaining > 0.001
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

        # SIMPLIFIED QUERY: Only check actual remaining amounts from payments
        # Use subquery for each commission to get its actual paid amount
        self.env.cr.execute(
            """
            SELECT 
                sc.id as commission_id,
                sc.date as commission_date,
                sc.commission_amount,
                COALESCE((
                    SELECT SUM(amount) 
                    FROM idil_sales_commission_payment 
                    WHERE commission_id = sc.id
                ), 0) as commission_paid,
                sc.commission_amount - COALESCE((
                    SELECT SUM(amount) 
                    FROM idil_sales_commission_payment 
                    WHERE commission_id = sc.id
                ), 0) as commission_remaining
            FROM idil_sales_commission sc
            JOIN idil_sales_sales_personnel sp ON sp.id = sc.sales_person_id
            WHERE sc.sales_person_id = %s
            AND sp.commission_payment_schedule = 'monthly'
            AND sc.commission_amount - COALESCE((
                SELECT SUM(amount) 
                FROM idil_sales_commission_payment 
                WHERE commission_id = sc.id
            ), 0) > 0.001
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
                    
                # Use dictionary keys - query already filters out fully paid commissions
                commission_id = row['commission_id']
                commission_date = row['commission_date']
                commission_amount = row['commission_amount']
                commission_paid = row['commission_paid']
                commission_remaining = row['commission_remaining']
                
                # Double-check remaining (query already filters, but be safe)
                if commission_remaining <= 0:
                    continue

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

    def _generate_commission_lines(self):
        """Generate commission lines from fresh DB data - used as fallback when onchange lines don't persist."""
        if not self.sales_person_id or not self.amount_to_pay:
            return
        
        _logger.info(f"Generating lines for {self.name}: salesperson={self.sales_person_id.id}, amount={self.amount_to_pay}")
        
        # Query fresh commission data
        self.env.cr.execute(
            """
            SELECT 
                sc.id as commission_id,
                sc.date as commission_date,
                sc.commission_amount,
                COALESCE((
                    SELECT SUM(amount) 
                    FROM idil_sales_commission_payment 
                    WHERE commission_id = sc.id
                ), 0) as commission_paid,
                sc.commission_amount - COALESCE((
                    SELECT SUM(amount) 
                    FROM idil_sales_commission_payment 
                    WHERE commission_id = sc.id
                ), 0) as commission_remaining
            FROM idil_sales_commission sc
            JOIN idil_sales_sales_personnel sp ON sp.id = sc.sales_person_id
            WHERE sc.sales_person_id = %s
            AND sp.commission_payment_schedule = 'monthly'
            AND sc.commission_amount - COALESCE((
                SELECT SUM(amount) 
                FROM idil_sales_commission_payment 
                WHERE commission_id = sc.id
            ), 0) > 0.001
            ORDER BY sc.id ASC
            """,
            (self.sales_person_id.id,)
        )
        commission_data = self.env.cr.dictfetchall()
        
        _logger.info(f"Found {len(commission_data)} unpaid commissions")
        
        if not commission_data:
            return
        
        # Create lines
        lines_to_create = []
        remaining_payment = self.amount_to_pay
        
        for row in commission_data:
            if remaining_payment <= 0:
                break
            
            commission_remaining = row['commission_remaining']
            if commission_remaining <= 0:
                continue
            
            payable = min(remaining_payment, commission_remaining)
            if payable > 0:
                lines_to_create.append({
                    "bulk_payment_id": self.id,
                    "commission_id": row['commission_id'],
                    "commission_date": row['commission_date'],
                    "commission_amount": row['commission_amount'],
                    "commission_paid": row['commission_paid'],
                    "commission_remaining": commission_remaining,
                })
                remaining_payment -= payable
        
        # Create lines directly in DB
        if lines_to_create:
            line_model = self.env["idil.sales.commission.bulk.payment.line"]
            for line_vals in lines_to_create:
                line_model.create(line_vals)
            _logger.info(f"Created {len(lines_to_create)} commission lines for {self.name}")
            # Refresh to get the new lines
            self.invalidate_recordset(['line_ids'])

    @api.constrains("amount_to_pay", "sales_person_id")
    def _check_amount_to_pay(self):
        """Validate amount doesn't exceed total unpaid commission using SQL."""
        for rec in self:
            if rec.sales_person_id and rec.amount_to_pay:
                # SIMPLIFIED QUERY: Calculate remaining directly from payments
                rec.env.cr.execute(
                    """
                    SELECT COALESCE(SUM(remaining), 0)
                    FROM (
                        SELECT 
                            sc.commission_amount - COALESCE((
                                SELECT SUM(amount) 
                                FROM idil_sales_commission_payment 
                                WHERE commission_id = sc.id
                            ), 0) as remaining
                        FROM idil_sales_commission sc
                        JOIN idil_sales_sales_personnel sp ON sp.id = sc.sales_person_id
                        WHERE sc.sales_person_id = %s
                        AND sp.commission_payment_schedule = 'monthly'
                    ) sub
                    WHERE remaining > 0.001
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

        _logger.info(f"=== BULK PAYMENT v{MODULE_VERSION} === Confirming {self.name}")
        
        # If lines are empty, try to regenerate them from fresh DB data
        if not self.line_ids:
            _logger.info(f"No lines found, regenerating from DB for {self.name}")
            self._generate_commission_lines()
        
        # After regeneration attempt, check again
        if not self.line_ids:
            raise ValidationError(
                "No commission lines to pay. Please select a salesperson and ensure "
                "there are unpaid commissions before confirming."
            )
        
        _logger.info(f"Bulk payment {self.name} has {len(self.line_ids)} lines to process")

        # Re-validate total amount against fresh DB data (monthly commissions only)
        # SIMPLIFIED QUERY: Calculate remaining directly from payments
        self.env.cr.execute(
            """
            SELECT COALESCE(SUM(remaining), 0)
            FROM (
                SELECT 
                    sc.commission_amount - COALESCE((
                        SELECT SUM(amount) 
                        FROM idil_sales_commission_payment 
                        WHERE commission_id = sc.id
                    ), 0) as remaining
                FROM idil_sales_commission sc
                JOIN idil_sales_sales_personnel sp ON sp.id = sc.sales_person_id
                WHERE sc.sales_person_id = %s
                AND sp.commission_payment_schedule = 'monthly'
            ) sub
            WHERE remaining > 0.001
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
        payments_created = 0
        total_paid_amount = 0.0

        for line in self.line_ids:
            if remaining_payment <= 0:
                break

            commission = line.commission_id
            
            _logger.info(f"Processing commission {commission.id} (amount: {commission.commission_amount})")
            
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
            
            _logger.info(f"Commission {commission.id}: total_paid={total_paid}, needed={commission_needed}")

            if commission_needed <= 0:
                _logger.info(f"Commission {commission.id} already fully paid, skipping")
                continue

            # Amount to pay for this commission (full or partial)
            payable = min(remaining_payment, commission_needed)
            if payable <= 0:
                break

            _logger.info(f"Paying {payable} for commission {commission.id}")

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
                payments_created += 1
                total_paid_amount += payable
                _logger.info(f"Created payment {payment.id} for commission {commission.id}")

            # pay_commission() now handles the status update directly via SQL
            # Just update the line with fresh data from SQL
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

        # CRITICAL: Ensure at least one payment was made
        if payments_created == 0:
            raise ValidationError(
                "No payments were created. All commissions may already be fully paid. "
                "Please refresh the page and try again."
            )

        _logger.info(f"Bulk payment {self.name}: Created {payments_created} payments totaling {total_paid_amount}")

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
