from odoo import models, fields, api
from odoo.exceptions import ValidationError
from dateutil.relativedelta import relativedelta
import logging

_logger = logging.getLogger(__name__)


class SalesDiscount(models.Model):
    _name = "idil.sales.discount"
    _description = "Sales Discount"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "id desc"

    company_id = fields.Many2one(
        "res.company", default=lambda s: s.env.company, required=True
    )
    name = fields.Char(
        string="Discount Reference",
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
    discount_amount = fields.Float(
        string="Discount Amount",
        digits=(16, 5),
        required=True,
        readonly=True,
        tracking=True,
    )
    discount_processed = fields.Float(
        string="Discount Processed",
        compute="_compute_discount_processed",
        store=True,
        readonly=True,
    )
    discount_remaining = fields.Float(
        string="Discount Remaining",
        compute="_compute_discount_remaining",
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
        related="sales_person_id.discount_payment_schedule",
        store=True,
        string="Payment Schedule",
        readonly=True,
    )

    due_date = fields.Date(
        string="Due Date",
        compute="_compute_due_date",
        store=True,
        help="Date when discount becomes processable based on salesperson's schedule",
    )

    is_payable = fields.Boolean(
        string="Is Processable",
        compute="_compute_is_payable",
        search="_search_is_payable",
        help="True if discount is due for processing today or earlier",
    )

    # Status
    state = fields.Selection(
        [("pending", "Pending"), ("partial", "Partial"), ("processed", "Processed")],
        string="Status",
        compute="_compute_state",
        store=True,
        tracking=True,
    )

    # Processing tracking
    process_ids = fields.One2many(
        "idil.sales.discount.process",
        "discount_id",
        string="Discount Processing",
        readonly=True,
    )

    # Processing fields (for form)
    amount_to_process = fields.Float(
        string="Amount to Process", digits=(16, 5), default=0.0
    )

    @api.depends("date", "sales_person_id.discount_payment_schedule",
                 "sales_person_id.discount_payment_day")
    def _compute_due_date(self):
        """Calculate due date based on salesperson's discount payment schedule"""
        for record in self:
            if not record.sales_person_id or not record.date:
                record.due_date = record.date
                continue

            if record.sales_person_id.discount_payment_schedule == "daily":
                # Due same day as transaction
                record.due_date = record.date
            else:  # monthly
                # Due on specified day of next applicable month
                transaction_date = fields.Date.from_string(record.date)
                payment_day = record.sales_person_id.discount_payment_day or 1

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

                record.due_date = due_date

    @api.depends("due_date", "state")
    def _compute_is_payable(self):
        """Check if discount is due for processing"""
        today = fields.Date.today()
        for record in self:
            record.is_payable = (
                record.state in ["pending", "partial"]
                and record.due_date
                and record.due_date <= today
            )

    def _search_is_payable(self, operator, value):
        """Allow searching for processable discounts"""
        today = fields.Date.today()
        if operator == "=" and value:
            return [
                ("state", "in", ["pending", "partial"]),
                ("due_date", "<=", today),
            ]
        else:
            return [
                "|",
                ("state", "=", "processed"),
                ("due_date", ">", today),
            ]

    @api.depends("process_ids.amount")
    def _compute_discount_processed(self):
        for record in self:
            record.discount_processed = sum(
                process.amount for process in record.process_ids
            )

    @api.depends("discount_amount", "discount_processed")
    def _compute_discount_remaining(self):
        for record in self:
            record.discount_remaining = record.discount_amount - record.discount_processed

    @api.depends("discount_amount", "discount_processed")
    def _compute_state(self):
        for record in self:
            if record.discount_processed >= record.discount_amount:
                record.state = "processed"
            elif record.discount_processed > 0:
                record.state = "partial"
            else:
                record.state = "pending"

    @api.model
    def create(self, vals):
        if vals.get("name", "New") == "New":
            vals["name"] = self.env["ir.sequence"].next_by_code(
                "idil.sales.discount"
            ) or "New"
        return super(SalesDiscount, self).create(vals)

    def process_discount(self):
        """Process discount (post transaction to salesperson)"""
        self.ensure_one()

        if self.amount_to_process <= 0:
            raise ValidationError("Amount to process must be greater than 0.")

        if self.amount_to_process > self.discount_remaining:
            raise ValidationError(
                f"The amount to process ({self.amount_to_process}) exceeds the remaining "
                f"discount amount ({self.discount_remaining})."
            )

        # Create processing record
        process_vals = {
            "discount_id": self.id,
            "sales_person_id": self.sales_person_id.id,
            "amount": self.amount_to_process,
            "date": fields.Date.context_today(self),
        }
        self.env["idil.sales.discount.process"].create(process_vals)

        # Reset amount_to_process
        self.amount_to_process = 0.0

        return {"type": "ir.actions.client", "tag": "reload"}


class SalesDiscountProcess(models.Model):
    _name = "idil.sales.discount.process"
    _description = "Sales Discount Processing"
    _order = "id desc"

    company_id = fields.Many2one(
        "res.company", default=lambda s: s.env.company, required=True
    )
    discount_id = fields.Many2one(
        "idil.sales.discount", string="Discount", required=True, ondelete="cascade"
    )
    sales_person_id = fields.Many2one(
        "idil.sales.sales_personnel", string="Salesperson", required=True
    )
    amount = fields.Float(string="Amount", digits=(16, 5), required=True)
    date = fields.Date(string="Date", default=fields.Date.context_today, required=True)

    def create(self, vals):
        process = super(SalesDiscountProcess, self).create(vals)
        # Create salesperson transaction (Out - negative amount as per original logic)
        process._create_salesperson_transaction()
        return process

    def _create_salesperson_transaction(self):
        """Post discount transaction to salesperson account"""
        self.env["idil.salesperson.transaction"].create(
            {
                "sales_person_id": self.sales_person_id.id,
                "date": self.date,
                "transaction_type": "out",
                "amount": self.amount * -1, # Negative amount for discount as per original logic
                "description": f"Sales Discount - {self.discount_id.sale_order_id.name}",
            }
        )

    def unlink(self):
        """Delete associated salesperson transaction when process is deleted"""
        for process in self:
            # Find and delete the transaction
            transaction = self.env["idil.salesperson.transaction"].search(
                [
                    ("sales_person_id", "=", process.sales_person_id.id),
                    ("date", "=", process.date),
                    ("amount", "=", process.amount * -1),
                    ("transaction_type", "=", "out"),
                    (
                        "description",
                        "=",
                        f"Sales Discount - {process.discount_id.sale_order_id.name}",
                    ),
                ],
                limit=1,
            )
            if transaction:
                transaction.unlink()

        return super(SalesDiscountProcess, self).unlink()
