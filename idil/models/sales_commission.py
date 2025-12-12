from odoo import models, fields, api
from odoo.exceptions import ValidationError
from datetime import date
from dateutil.relativedelta import relativedelta
import logging

_logger = logging.getLogger(__name__)


class SalesCommission(models.Model):
    _name = "idil.sales.commission"
    _description = "Sales Commission"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "id desc"

    company_id = fields.Many2one(
        "res.company", default=lambda s: s.env.company, required=True
    )
    name = fields.Char(
        string="Commission Reference",
        required=True,
        tracking=True,
        default="New",
        readonly=True,
    )

    # Links
    sale_order_id = fields.Many2one(
        "idil.sale.order",
        string="Sale Order",
        required=True,
        ondelete="cascade",
        index=True,
        tracking=True,
    )
    sales_person_id = fields.Many2one(
        "idil.sales.sales_personnel",
        string="Salesperson",
        required=True,
        readonly=True,
        tracking=True,
    )

    # Currency
    currency_id = fields.Many2one(
        "res.currency",
        string="Currency",
        required=True,
        readonly=True,
    )

    # Amounts
    commission_amount = fields.Float(
        string="Commission Amount",
        digits=(16, 5),
        required=True,
        readonly=True,
        tracking=True,
    )
    commission_paid = fields.Float(
        string="Commission Paid",
        compute="_compute_commission_paid",
        store=True,
        readonly=True,
    )
    commission_remaining = fields.Float(
        string="Commission Remaining",
        compute="_compute_commission_remaining",
        store=True,
        readonly=True,
    )

    # Dates
    date = fields.Date(
        string="Date",
        default=fields.Date.context_today,
        required=True,
        readonly=True,
        tracking=True,
    )

    # Payment Schedule Fields
    payment_schedule = fields.Selection(
        related="sales_person_id.commission_payment_schedule",
        store=False,
        string="Payment Schedule",
        readonly=True,
    )

    due_date = fields.Date(
        string="Due Date",
        compute="_compute_due_date",
        store=True,
        help="Date when commission becomes payable based on salesperson's payment schedule",
    )

    is_payable = fields.Boolean(
        string="Is Payable",
        compute="_compute_is_payable",
        search="_search_is_payable",
        help="True if commission is due for payment today or earlier",
    )

    # Payment Status
    payment_status = fields.Selection(
        [("pending", "Pending"), ("partial_paid", "Partial Paid"), ("paid", "Paid")],
        string="Payment Status",
        compute="_compute_payment_status",
        store=True,
        tracking=True,
    )

    # Payment tracking
    payment_ids = fields.One2many(
        "idil.sales.commission.payment",
        "commission_id",
        string="Commission Payments",
        readonly=True,
    )

    # Payment fields (for payment form)
    cash_account_id = fields.Many2one(
        "idil.chart.account",
        string="Cash/Bank Account",
        domain="[('account_type', 'in', ['cash', 'bank_transfer'])]",
        help="Select the cash or bank account for payment.",
    )
    amount_to_pay = fields.Float(
        string="Amount to Pay", digits=(16, 5), default=0.0
    )

    @api.depends("payment_ids", "payment_ids.amount")
    def _compute_commission_paid(self):
        """Compute total paid amount from all payments."""
        for commission in self:
            # Use SQL to get fresh totals, bypassing ORM cache
            self.env.cr.execute(
                """
                SELECT COALESCE(SUM(amount), 0)
                FROM idil_sales_commission_payment
                WHERE commission_id = %s
                """,
                (commission.id,)
            )
            commission.commission_paid = self.env.cr.fetchone()[0]

    @api.depends("commission_amount", "commission_paid")
    def _compute_commission_remaining(self):
        """Compute remaining commission amount."""
        for commission in self:
            commission.commission_remaining = (
                commission.commission_amount - commission.commission_paid
            )

    @api.depends("date", "sales_person_id.commission_payment_schedule",
                 "sales_person_id.commission_payment_day")
    def _compute_due_date(self):
        """Calculate due date based on salesperson's payment schedule"""
        for commission in self:
            if not commission.sales_person_id or not commission.date:
                commission.due_date = commission.date
                continue

            if commission.sales_person_id.commission_payment_schedule == "daily":
                # Due same day as transaction
                commission.due_date = commission.date
            else:  # monthly
                # Due on specified day of next applicable month
                transaction_date = fields.Date.from_string(commission.date)
                payment_day = commission.sales_person_id.commission_payment_day or 1

                # Ensure payment day is valid (1-31)
                payment_day = max(1, min(31, payment_day))

                # Calculate next payment date
                if transaction_date.day < payment_day:
                    # Payment is in the same month
                    try:
                        due_date = transaction_date.replace(day=payment_day)
                    except ValueError:
                        # Handle months with fewer days (e.g., Feb 30)
                        due_date = transaction_date.replace(day=1) + relativedelta(
                            months=1, days=-1
                        )
                else:
                    # Payment is in the next month
                    try:
                        next_month = transaction_date + relativedelta(months=1)
                        due_date = next_month.replace(day=payment_day)
                    except ValueError:
                        # Handle months with fewer days
                        next_month = transaction_date + relativedelta(months=1)
                        due_date = next_month.replace(day=1) + relativedelta(
                            months=1, days=-1
                        )

                commission.due_date = due_date

    @api.depends("due_date", "payment_status")
    def _compute_is_payable(self):
        """Check if commission is due for payment"""
        today = fields.Date.today()
        for commission in self:
            commission.is_payable = (
                commission.payment_status in ["pending", "partial_paid"]
                and commission.due_date
                and commission.due_date <= today
            )

    def _search_is_payable(self, operator, value):
        """Allow searching for payable commissions"""
        today = fields.Date.today()
        if operator == "=" and value:
            return [
                ("payment_status", "in", ["pending", "partial_paid"]),
                ("due_date", "<=", today),
            ]
        else:
            return [
                "|",
                ("payment_status", "=", "paid"),
                ("due_date", ">", today),
            ]

    @api.depends("commission_amount", "commission_paid")
    def _compute_payment_status(self):
        """Compute payment status using SQL for fresh data."""
        for record in self:
            # Use SQL to get fresh totals directly from DB
            self.env.cr.execute(
                """
                SELECT COALESCE(SUM(amount), 0)
                FROM idil_sales_commission_payment
                WHERE commission_id = %s
                """,
                (record.id,)
            )
            paid_amount = self.env.cr.fetchone()[0] or 0.0
            
            # Update payment status based on fresh data
            if paid_amount >= record.commission_amount:
                record.payment_status = "paid"
            elif paid_amount > 0:
                record.payment_status = "partial_paid"
            else:
                record.payment_status = "pending"
                
            # Log for debugging
            _logger.info(
                f"Commission {record.id}: Amount={record.commission_amount}, Paid={paid_amount}, Status={record.payment_status}"
            )

    @api.model
    def create(self, vals):
        if vals.get("name", "New") == "New":
            vals["name"] = self.env["ir.sequence"].next_by_code(
                "idil.sales.commission"
            ) or "New"
        return super(SalesCommission, self).create(vals)

    def pay_commission(self):
        """Pay commission to salesperson"""
        self.ensure_one()

        # CRITICAL: Daily schedule commissions are NOT payable
        # For daily schedule, commission is netted from receivables at sale time
        # The salesperson already keeps their commission - no payment needed
        if self.payment_schedule == 'daily':
            raise ValidationError(
                "Daily schedule commissions are not payable. "
                "The salesperson already received their commission at the time of sale "
                "(netted from receivables)."
            )

        # Use SQL-level locking to prevent race conditions (SELECT FOR UPDATE)
        self.env.cr.execute(
            """
            SELECT id FROM idil_sales_commission 
            WHERE id = %s FOR UPDATE NOWAIT
            """,
            (self.id,)
        )

        # Guard with fresh DB state (avoid cache/UI staleness)
        self.env.cr.execute(
            """
            SELECT COALESCE(SUM(amount), 0) 
            FROM idil_sales_commission_payment 
            WHERE commission_id = %s
            """,
            (self.id,)
        )
        total_paid = self.env.cr.fetchone()[0]
        remaining = (self.commission_amount or 0.0) - total_paid
        
        if remaining <= 0:
            raise ValidationError("This commission is already fully paid.")

        if not self.cash_account_id:
            raise ValidationError(
                "Please select a cash account before paying the commission."
            )

        if self.amount_to_pay <= 0:
            raise ValidationError("Amount to pay must be greater than 0.")

        # Validate against fresh remaining to prevent overpay from stale cache/UI
        if self.amount_to_pay > remaining + 0.001:  # Small tolerance for float precision
            raise ValidationError(
                f"The amount to pay ({self.amount_to_pay:.2f}) exceeds the remaining "
                f"commission amount ({remaining:.2f})."
            )
        
        # Cap amount to remaining if within tolerance
        actual_amount = min(self.amount_to_pay, remaining)

        # Validate commission payable account exists for monthly schedule
        if not self.sales_person_id.commission_payable_account_id:
            raise ValidationError(
                f"Salesperson '{self.sales_person_id.name}' has monthly commission schedule "
                "but no Commission Payable Account configured."
            )

        # Create payment record
        payment_vals = {
            "commission_id": self.id,
            "sales_person_id": self.sales_person_id.id,
            "amount": self.amount_to_pay,
            "date": fields.Date.context_today(self),
            "cash_account_id": self.cash_account_id.id,
        }
        payment = self.env["idil.sales.commission.payment"].create(payment_vals)

        # Book accounting entry for commission payment (monthly schedule only)
        # Daily schedule doesn't use Commission Payable, so no clearing entry needed
        if self.payment_schedule == 'monthly':
            trx_source = self.env["idil.transaction.source"].search(
                [("name", "=", "Commission Payment")], limit=1
            )
            if not trx_source:
                # Fallback to Receipt source if Commission Payment doesn't exist
                trx_source = self.env["idil.transaction.source"].search(
                    [("name", "=", "Receipt")], limit=1
                )
            
            # Get exchange rate - use the rate from the sale order or default to 1.0
            rate = self.sale_order_id.rate if self.sale_order_id and self.sale_order_id.rate else 1.0
            
            # Create transaction booking with all required fields
            # Add more comprehensive error handling
            try:
                booking_vals = {
                    "sales_person_id": self.sales_person_id.id,
                    "trx_source_id": trx_source.id if trx_source else False,
                    "trx_date": fields.Date.context_today(self),
                    "amount": self.amount_to_pay,
                    "payment_method": "commission_payment",
                    "payment_status": "paid",
                    "reffno": f"Commission Payment - {self.name}",
                    "rate": rate,
                    "sale_order_id": self.sale_order_id.id if self.sale_order_id else False,
                    "company_id": self.company_id.id,
                    "currency_id": self.currency_id.id,
                }
                _logger.info(f"Creating transaction booking with values: {booking_vals}")
                booking = self.env["idil.transaction_booking"].create(booking_vals)
                _logger.info(f"Successfully created transaction booking ID: {booking.id}")
            except Exception as e:
                _logger.error(f"Failed to create transaction booking: {str(e)}")
                raise ValidationError(f"Failed to create accounting entry: {str(e)}")
            
            try:
                # DR Commission Payable (clear the liability)
                dr_line = self.env["idil.transaction_bookingline"].create(
                    {
                        "transaction_booking_id": booking.id,
                        "description": f"Commission Payment - {self.sale_order_id.name if self.sale_order_id else self.name}",
                        "account_number": self.sales_person_id.commission_payable_account_id.id,
                        "transaction_type": "dr",
                        "dr_amount": self.amount_to_pay,
                        "cr_amount": 0,
                        "transaction_date": fields.Date.context_today(self),
                        "company_id": self.company_id.id,
                        "currency_id": self.currency_id.id,
                    }
                )
                _logger.info(f"Created DR booking line ID: {dr_line.id}")
                
                # CR Cash/Bank (record cash outflow)
                cr_line = self.env["idil.transaction_bookingline"].create(
                    {
                        "transaction_booking_id": booking.id,
                        "description": f"Commission Payment - {self.sale_order_id.name if self.sale_order_id else self.name}",
                        "account_number": self.cash_account_id.id,
                        "transaction_type": "cr",
                        "dr_amount": 0,
                        "cr_amount": self.amount_to_pay,
                        "transaction_date": fields.Date.context_today(self),
                        "company_id": self.company_id.id,
                        "currency_id": self.currency_id.id,
                    }
                )
                _logger.info(f"Created CR booking line ID: {cr_line.id}")
                
                # Flush to ensure database consistency
                self.env.cr.execute("COMMIT")
                
            except Exception as e:
                _logger.error(f"Failed to create transaction booking lines: {str(e)}")
                raise ValidationError(f"Failed to create accounting entries: {str(e)}")
            
            # Link booking to payment record for trial balance tracking
            payment.write({"transaction_booking_id": booking.id})

        # Reset amount_to_pay and reload the view to reflect updated status
        self.amount_to_pay = 0.0

        return {"type": "ir.actions.client", "tag": "reload"}
        
    def action_sync_payments(self):
        """Action to manually sync payment records and create missing transaction bookings.
        This helps fix inconsistencies between commission payments and accounting entries."""
        self.ensure_one()
        
        # Check if any payment exists without transaction booking
        missing_bookings = self.env['idil.sales.commission.payment'].search([
            ('commission_id', '=', self.id),
            ('transaction_booking_id', '=', False),
        ])
        
        if not missing_bookings:
            raise ValidationError("All payments already have transaction bookings. Nothing to sync.")
            
        created_bookings = 0
        for payment in missing_bookings:
            try:
                # Create missing transaction booking
                trx_source = self.env["idil.transaction.source"].search(
                    [("name", "=", "Commission Payment")], limit=1
                ) or self.env["idil.transaction.source"].search([("name", "=", "Receipt")], limit=1)
                
                rate = self.sale_order_id.rate if self.sale_order_id and self.sale_order_id.rate else 1.0
                
                # Create booking for this payment
                booking = self.env["idil.transaction_booking"].create({
                    "sales_person_id": self.sales_person_id.id,
                    "trx_source_id": trx_source.id if trx_source else False,
                    "trx_date": payment.date,
                    "amount": payment.amount,
                    "payment_method": "commission_payment",
                    "payment_status": "paid",
                    "reffno": f"Commission Payment - {self.name} (Sync)",
                    "rate": rate,
                    "sale_order_id": self.sale_order_id.id if self.sale_order_id else False,
                    "company_id": self.company_id.id,
                    "currency_id": self.currency_id.id,
                })
                
                # Create DR/CR lines
                self.env["idil.transaction_bookingline"].create({
                    "transaction_booking_id": booking.id,
                    "description": f"Commission Payment - {self.name} (Sync)",
                    "account_number": self.sales_person_id.commission_payable_account_id.id,
                    "transaction_type": "dr",
                    "dr_amount": payment.amount,
                    "cr_amount": 0,
                    "transaction_date": payment.date,
                    "company_id": self.company_id.id,
                    "currency_id": self.currency_id.id,
                })
                
                self.env["idil.transaction_bookingline"].create({
                    "transaction_booking_id": booking.id,
                    "description": f"Commission Payment - {self.name} (Sync)",
                    "account_number": payment.cash_account_id.id,
                    "transaction_type": "cr",
                    "dr_amount": 0,
                    "cr_amount": payment.amount,
                    "transaction_date": payment.date,
                    "company_id": self.company_id.id,
                    "currency_id": self.currency_id.id,
                })
                
                # Link booking to payment
                payment.write({"transaction_booking_id": booking.id})
                created_bookings += 1
                
                # Commit after each successful booking creation
                self.env.cr.commit()
                
            except Exception as e:
                _logger.error(f"Failed to sync payment {payment.id}: {str(e)}")
        
        # Recompute payment status
        self.invalidate_recordset(['commission_paid', 'commission_remaining', 'payment_status'])
        self._compute_commission_paid()
        self._compute_commission_remaining()
        self._compute_payment_status()
        self.flush_recordset(['commission_paid', 'commission_remaining', 'payment_status'])
        
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Sync Complete',
                'message': f"Created {created_bookings} transaction bookings for previously missing payments",
                'type': 'success',
                'sticky': False,
            }
        }


class SalesCommissionPayment(models.Model):
    _name = "idil.sales.commission.payment"
    _description = "Sales Commission Payment"
    _order = "id desc"

    bulk_payment_line_id = fields.Many2one(
        "idil.sales.commission.bulk.payment.line",
        string="Bulk Payment Line",
        readonly=True,
    )

    company_id = fields.Many2one(
        "res.company", default=lambda s: s.env.company, required=True
    )
    commission_id = fields.Many2one(
        "idil.sales.commission", string="Commission", required=True, ondelete="cascade"
    )
    sales_person_id = fields.Many2one(
        "idil.sales.sales_personnel", string="Salesperson", required=True
    )
    currency_id = fields.Many2one(
        "res.currency",
        string="Currency",
        required=True,
        default=lambda self: self.env["res.currency"].search(
            [("name", "=", "SL")], limit=1
        ),
        readonly=True,
    )
    amount = fields.Float(string="Amount", digits=(16, 5), required=True)
    date = fields.Date(string="Date", default=fields.Date.context_today, required=True)
    cash_account_id = fields.Many2one(
        "idil.chart.account", string="Cash/Bank Account", required=True
    )
    transaction_booking_id = fields.Many2one(
        "idil.transaction_booking",
        string="Transaction Booking",
        readonly=True,
        help="Link to the accounting entry for this payment",
    )

    @api.model
    def create(self, vals):
        """Create payment with SQL-level validation to prevent overpayment."""
        commission = None
        if vals.get("commission_id"):
            commission_id = vals["commission_id"]
            commission = self.env["idil.sales.commission"].browse(commission_id)
            
            # CRITICAL: Block daily schedule commission payments
            if commission.payment_schedule == 'daily':
                raise ValidationError(
                    "Daily schedule commissions are not payable. "
                    "The salesperson already received their commission at the time of sale."
                )
            
            # Use SQL-level locking to prevent race conditions
            self.env.cr.execute(
                """
                SELECT id FROM idil_sales_commission 
                WHERE id = %s FOR UPDATE NOWAIT
                """,
                (commission_id,)
            )
            
            # Get fresh totals directly from DB
            self.env.cr.execute(
                """
                SELECT COALESCE(SUM(amount), 0) 
                FROM idil_sales_commission_payment 
                WHERE commission_id = %s
                """,
                (commission_id,)
            )
            total_paid = self.env.cr.fetchone()[0]
            remaining = (commission.commission_amount or 0.0) - total_paid
            amount = (vals.get("amount") or 0.0)
            
            if remaining <= 0:
                raise ValidationError("This commission is already fully paid.")
            if amount > remaining + 0.001:  # Small tolerance for float precision
                raise ValidationError(
                    f"The amount to pay ({amount:.2f}) exceeds the remaining commission amount ({remaining:.2f})."
                )
            # Cap amount to remaining if within tolerance
            if amount > remaining:
                vals["amount"] = remaining

        payment = super(SalesCommissionPayment, self).create(vals)
        # Create salesperson transaction (In - reduces what they owe)
        payment._create_salesperson_transaction()
        
        # Explicitly update commission fields to ensure persistence
        payment._update_commission_balance()
        
        return payment

    def _create_salesperson_transaction(self):
        """Post commission payment to salesperson account"""
        self.env["idil.salesperson.transaction"].create(
            {
                "sales_person_id": self.sales_person_id.id,
                "date": self.date,
                "transaction_type": "in",
                "amount": self.amount,
                "description": f"Commission Payment - {self.commission_id.sale_order_id.name}",
            }
        )

    def unlink(self):
        """Delete associated salesperson transaction when payment is deleted"""
        # Store commissions to update before deletion
        commissions = self.mapped('commission_id')
        
        for payment in self:
            # Find and delete the transaction
            transaction = self.env["idil.salesperson.transaction"].search(
                [
                    ("sales_person_id", "=", payment.sales_person_id.id),
                    ("date", "=", payment.date),
                    ("amount", "=", payment.amount),
                    ("transaction_type", "=", "in"),
                    (
                        "description",
                        "=",
                        f"Commission Payment - {payment.commission_id.sale_order_id.name}",
                    ),
                ],
                limit=1,
            )
            if transaction:
                transaction.unlink()

        res = super(SalesCommissionPayment, self).unlink()
        
        # Force recomputation after deletion
        for commission in commissions:
            # Invalidate cache and trigger recomputation
            commission.invalidate_recordset(
                ['commission_paid', 'commission_remaining', 'payment_status']
            )
            commission._compute_commission_paid()
            commission._compute_commission_remaining()
            commission._compute_payment_status()
            commission.flush_recordset(
                ['commission_paid', 'commission_remaining', 'payment_status']
            )
            
        return res

    def _update_commission_balance(self):
        """Trigger recomputation of commission balance fields."""
        for payment in self:
            commission = payment.commission_id
            # Invalidate cache to force recomputation
            commission.invalidate_recordset(
                ['commission_paid', 'commission_remaining', 'payment_status']
            )
            # Force recomputation by accessing the fields
            commission._compute_commission_paid()
            commission._compute_commission_remaining()
            commission._compute_payment_status()
            # Flush to database
            commission.flush_recordset(
                ['commission_paid', 'commission_remaining', 'payment_status']
            )

    @api.constrains("amount", "commission_id")
    def _check_amount_not_exceed_remaining(self):
        """Safety net to prevent overpayment using SQL-level check."""
        for rec in self:
            if not rec.commission_id:
                continue
            
            # Block daily schedule payments at constraint level too
            if rec.commission_id.payment_schedule == 'daily':
                raise ValidationError(
                    "Daily schedule commissions are not payable. "
                    "The salesperson already received their commission at the time of sale."
                )
            
            # Use SQL to get fresh totals excluding current record
            self.env.cr.execute(
                """
                SELECT COALESCE(SUM(amount), 0) 
                FROM idil_sales_commission_payment 
                WHERE commission_id = %s AND id != %s
                """,
                (rec.commission_id.id, rec.id or 0)
            )
            already_paid = self.env.cr.fetchone()[0]
            remaining = (rec.commission_id.commission_amount or 0.0) - already_paid
            
            if rec.amount > remaining + 0.001:  # Small tolerance for float precision
                raise ValidationError(
                    f"Payment amount ({rec.amount:.2f}) exceeds remaining commission ({remaining:.2f})."
                )
