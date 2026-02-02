import re

from odoo import models, fields, api
from odoo.exceptions import UserError, ValidationError
from odoo.tools import float_compare
from odoo.tools.safe_eval import datetime
import logging

_logger = logging.getLogger(__name__)


class CustomerSaleOrder(models.Model):
    _name = "idil.customer.sale.order"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _description = "CustomerSale Order"

    company_id = fields.Many2one(
        "res.company", default=lambda s: s.env.company, required=True
    )
    name = fields.Char(string="Sales Reference", tracking=True)
    customer_id = fields.Many2one(
        "idil.customer.registration", string="Customer", required=True
    )
    # Add the field to link to the Customer Place Order

    customer_place_order_id = fields.Many2one(
        "idil.customer.place.order",
        string="Customer Place Order",
        domain="[('customer_id', '=', customer_id), ('state', 'in', ('draft','sent','approved'))]",
        required=False,
    )

    order_date = fields.Datetime(string="Order Date", default=fields.Datetime.now)
    order_lines = fields.One2many(
        "idil.customer.sale.order.line", "order_id", string="Order Lines"
    )
    order_total = fields.Float(
        string="Order Total", compute="_compute_order_total", store=True
    )
    state = fields.Selection(
        [("draft", "Draft"), ("confirmed", "Confirmed"), ("cancel", "Cancelled")],
        default="confirmed",
    )
    # Currency fields
    currency_id = fields.Many2one(
        "res.currency",
        string="Currency",
        required=True,
        default=lambda self: self.env.company.currency_id,
        readonly=True,
    )

    rate = fields.Float(
        string="Exchange Rate",
        compute="_compute_exchange_rate",
        store=True,
        readonly=True,
    )

    payment_method_ids = fields.Many2one(
        "idil.payment.method",
        string="Payment Method",
        tracking=True,
    )

    # One2many field for multiple payment methods
    payment_lines = fields.One2many(
        "idil.customer.sale.payment",
        "order_id",
        string="Payments",
    )

    total_paid = fields.Float(
        string="Total Paid", compute="_compute_total_paid", store=False
    )

    balance_due = fields.Float(
        string="Balance Due", compute="_compute_balance_due", store=False
    )
    customer_opening_balance_id = fields.Many2one(
        "idil.customer.opening.balance.line",
        string="Opening Balance",
        ondelete="cascade",
    )
    total_return_amount = fields.Float(
        string="Total Returned",
        compute="_compute_total_return_amount",
        store=False,
    )
    net_balance = fields.Float(
        string="Net Balance",
        compute="_compute_net_balance",
        store=False,
    )
    total_cost_price = fields.Float(
        string="Total Cost Price",
        compute="_compute_total_cost_price",
        store=False,
        digits=(16, 6),
        readonly=True,
        tracking=True,
    )

    @api.constrains("order_lines", "customer_opening_balance_id")
    def _check_has_lines(self):
        for order in self:
            if order.customer_opening_balance_id:
                continue
            if not order.order_lines:
                raise ValidationError(_("You must add at least one order line."))

    # Automatically populate order lines from the place order when customer_place_order_id is selected
    @api.onchange("customer_place_order_id")
    def _onchange_customer_place_order(self):
        if not self.customer_place_order_id:
            return

        # If user already typed manual lines, prevent accidental overwrite
        if self.order_lines:
            return {
                "warning": {
                    "title": _("Warning"),
                    "message": _(
                        "Order lines already exist. Clear them first if you want to load from Place Order."
                    ),
                }
            }

        order_line_vals = []
        for line in self.customer_place_order_id.order_lines:
            order_line_vals.append(
                (
                    0,
                    0,
                    {
                        "product_id": line.product_id.id,
                        "quantity": line.quantity,
                        "price_unit": line.product_id.sale_price,
                    },
                )
            )

        self.order_lines = order_line_vals

    @api.depends("order_lines", "order_lines.product_id", "order_lines.quantity")
    def _compute_total_cost_price(self):
        for order in self:
            total = 0.0
            for line in order.order_lines:
                product = line.product_id
                qty = line.quantity
                if product and qty:
                    # 1. If product has a BOM
                    if product.bom_id:
                        bom_currency = product.bom_id.currency_id.name
                        if bom_currency == "SL":
                            total += (product.cost * qty) / order.rate
                        else:
                            total += product.cost * qty
                    else:
                        # 2. If no BOM, assume cost is SL and convert
                        total += (product.cost * qty) / order.rate
            order.total_cost_price = total

    @api.depends("order_total", "total_paid", "total_return_amount")
    def _compute_net_balance(self):
        for order in self:
            # Net balance after returns (simple + stable)
            order.net_balance = (
                order.order_total - order.total_paid
            ) - order.total_return_amount

    @api.depends("order_lines", "order_lines.product_id")  # triggers on change
    def _compute_total_return_amount(self):
        for order in self:
            return_lines = self.env["idil.customer.sale.return.line"].search(
                [
                    ("sale_order_line_id.order_id", "=", order.id),
                    ("return_id.state", "=", "confirmed"),
                ]
            )
            order.total_return_amount = sum(return_lines.mapped("total_amount"))

    @api.depends("payment_lines.amount")
    def _compute_total_paid(self):
        for order in self:
            order.total_paid = sum(order.payment_lines.mapped("amount"))

    @api.depends("order_total", "payment_lines.amount")
    def _compute_balance_due(self):
        for order in self:
            total_paid = sum(order.payment_lines.mapped("amount")) or 0.0
            order.balance_due = max(order.order_total - total_paid, 0.0)

    @api.constrains("payment_lines", "order_total")
    def _check_payment_balance(self):
        for order in self:
            total_paid = sum(order.payment_lines.mapped("amount")) or 0.0
            if float_compare(total_paid, order.order_total, precision_digits=5) > 0:
                raise ValidationError(
                    "The total paid amount cannot exceed the order total."
                )

    @api.depends("currency_id", "order_date", "company_id")
    def _compute_exchange_rate(self):
        Rate = self.env["res.currency.rate"].sudo()
        for order in self:
            order.rate = 0.0
            if not order.currency_id:
                continue

            doc_date = (
                fields.Date.to_date(order.order_date)
                if order.order_date
                else fields.Date.today()
            )

            rate_rec = Rate.search(
                [
                    ("currency_id", "=", order.currency_id.id),
                    ("name", "<=", doc_date),
                    ("company_id", "in", [order.company_id.id, False]),
                ],
                order="company_id desc, name desc",
                limit=1,
            )

            order.rate = rate_rec.rate or 0.0

    @api.model
    def create(self, vals):
        try:
            with self.env.cr.savepoint():
                # Step 1: Check if customer_id is provided in vals
                if "customer_id" in vals:

                    # Set order reference if not provided
                    if "name" not in vals or not vals["name"]:
                        vals["name"] = self._generate_order_reference(vals)

                # Proceed with creating the SaleOrder with the updated vals
                new_order = super(CustomerSaleOrder, self).create(vals)
                # ✅ confirm the linked place order, if any

                # Step 3: Create product movements for each order line
                for line in new_order.order_lines:
                    self.env["idil.product.movement"].create(
                        {
                            "product_id": line.product_id.id,
                            "movement_type": "out",
                            "quantity": line.quantity * -1,
                            "date": new_order.order_date,
                            "source_document": new_order.name,
                            "customer_id": new_order.customer_id.id,
                        }
                    )

                # Step 4: Book accounting entries for the new order
                new_order.sync_sale_financials()

                # ✅ If this sale order came from a Customer Place Order, confirm it and link back
                if new_order.customer_place_order_id:
                    new_order.customer_place_order_id.write(
                        {
                            "state": "confirmed",  # or "converted" if you later rename
                            "sale_order_id": new_order.id,
                        }
                    )

                return new_order
        except Exception as e:
            _logger.error(f"Create transaction failed: {str(e)}")
            raise ValidationError(f"Transaction failed: {str(e)}")

    # inside class CustomerSaleOrder(models.Model):

    def _generate_order_reference(self, vals):
        bom_id = vals.get("bom_id", False)
        if bom_id:
            bom = self.env["idil.bom"].browse(bom_id)
            bom_name = (
                re.sub("[^A-Za-z0-9]+", "", bom.name[:2]).upper()
                if bom and bom.name
                else "XX"
            )
            date_str = "/" + datetime.now().strftime("%d%m%Y")
            day_night = "/DAY/" if datetime.now().hour < 12 else "/NIGHT/"
            sequence = self.env["ir.sequence"].next_by_code("idil.sale.order.sequence")
            sequence = sequence[-3:] if sequence else "000"
            return f"{bom_name}{date_str}{day_night}{sequence}"
        else:
            # Fallback if no BOM is provided
            return self.env["ir.sequence"].next_by_code("idil.sale.order.sequence")

    @api.depends("order_lines.subtotal")
    def _compute_order_total(self):
        for order in self:
            order.order_total = sum(order.order_lines.mapped("subtotal"))

    def sync_sale_financials(self):
        """
        Flow (ordered as you requested):
        1) If you want default payment leg AND no payment lines:
            - get PayMethod
            - create Payment leg
        2) Create/Update Booking (header) then rebuild BookingLines
        3) Create/Update Receipt
        4) Link payment legs to receipt (sales_receipt_id)
        """

        PayMethod = self.env["idil.payment.method"]
        Payment = self.env["idil.customer.sale.payment"]
        Booking = self.env["idil.transaction_booking"]
        BookingLine = self.env["idil.transaction_bookingline"]
        Receipt = self.env["idil.sales.receipt"]

        for order in self:
            if order.customer_opening_balance_id:
                continue

            # -----------------------------
            # Validations
            # -----------------------------
            if not order.customer_id.account_receivable_id:
                raise ValidationError(
                    "The Customer does not have a receivable account."
                )
            if order.rate <= 0:
                raise ValidationError(
                    "Please insert a valid exchange rate greater than 0."
                )
            if not order.order_lines:
                raise ValidationError(
                    "You must insert at least one product to proceed with the sale."
                )

            expected_currency = order.customer_id.account_receivable_id.currency_id

            # ---------------------------------------------------------
            # 1) OPTIONAL: Auto-create ONE default payment leg if none exist
            # IMPORTANT: This will make every order paid automatically if you leave it enabled.
            # If you want A/R by default, set AUTO_CREATE_DEFAULT_PAYMENT = False.
            # ---------------------------------------------------------
            AUTO_CREATE_DEFAULT_PAYMENT = (
                False  # <<< set True only if you really want auto full cash/bank
            )

            if AUTO_CREATE_DEFAULT_PAYMENT and not order.payment_lines:
                # DO NOT domain-search on account_id.account_type (it fails in your env)
                methods = PayMethod.search(
                    [("company_id", "=", order.company_id.id), ("active", "=", True)]
                )

                # choose cash first then bank using python filtering
                default_method = False
                for m in methods:
                    acc = m.account_id
                    if acc and acc.account_type == "cash":
                        default_method = m
                        break
                if not default_method:
                    for m in methods:
                        acc = m.account_id
                        if acc and acc.account_type == "bank_transfer":
                            default_method = m
                            break

                if default_method:
                    Payment.create(
                        {
                            "order_id": order.id,
                            "sales_receipt_id": order.id,
                            "payment_method_ids": default_method.id,
                            "amount": order.order_total,
                            "date": (
                                fields.Date.to_date(order.order_date)
                                if order.order_date
                                else fields.Date.context_today(self)
                            ),
                        }
                    )

            # -----------------------------
            # Totals & Overpayment
            # -----------------------------
            total_paid = sum(order.payment_lines.mapped("amount")) or 0.0
            remaining = max(order.order_total - total_paid, 0.0)

            if float_compare(total_paid, order.order_total, precision_digits=5) > 0:
                raise ValidationError(
                    "The total paid amount cannot exceed the order total."
                )

            # status
            if float_compare(total_paid, 0.0, precision_digits=5) <= 0:
                receipt_status = "pending"
            elif float_compare(remaining, 0.0, precision_digits=5) <= 0:
                receipt_status = "paid"
            else:
                receipt_status = "partial"

            # Validate payment accounts currency ONLY if payment lines exist
            for p in order.payment_lines:
                if not p.account_id:
                    raise ValidationError("Payment line is missing an account.")
                if (
                    p.account_id.currency_id
                    and p.account_id.currency_id != expected_currency
                ):
                    raise ValidationError(
                        f"Currency mismatch in payment method '{p.payment_method_ids.name}'.\n"
                        f"Payment account currency is '{p.account_id.currency_id.name}', "
                        f"but Customer A/R currency is '{expected_currency.name}'."
                    )

            # -----------------------------
            # 2) Create/Update Booking FIRST (as you requested)
            # -----------------------------
            trx_source = self.env["idil.transaction.source"].search(
                [("name", "=", "Customer Sales Order")], limit=1
            )
            if not trx_source:
                raise UserError("Transaction source 'Customer Sales Order' not found.")

            # header payment method label using safe python loop
            header_payment_method = "receivable"
            found_bank = False
            found_cash = False
            for p in order.payment_lines:
                if p.account_id and p.account_id.account_type == "bank_transfer":
                    found_bank = True
                elif p.account_id and p.account_id.account_type == "cash":
                    found_cash = True
            if found_bank:
                header_payment_method = "bank_transfer"
            elif found_cash:
                header_payment_method = "cash"

            booking = Booking.search(
                [("cusotmer_sale_order_id", "=", order.id)], limit=1
            )
            if booking:
                booking.write(
                    {
                        "customer_id": order.customer_id.id,
                        "trx_source_id": trx_source.id,
                        "reffno": order.name,
                        "Sales_order_number": order.id,
                        "payment_method": header_payment_method,
                        "payment_status": receipt_status,
                        "rate": order.rate,
                        "trx_date": order.order_date,
                        "amount": order.order_total,
                    }
                )
                # rebuild lines
                BookingLine.search(
                    [("transaction_booking_id", "=", booking.id)]
                ).unlink()
            else:
                booking = Booking.create(
                    {
                        "customer_id": order.customer_id.id,
                        "cusotmer_sale_order_id": order.id,
                        "trx_source_id": trx_source.id,
                        "reffno": order.name,
                        "Sales_order_number": order.id,
                        "payment_method": header_payment_method,
                        "payment_status": receipt_status,
                        "rate": order.rate,
                        "trx_date": order.order_date,
                        "amount": order.order_total,
                    }
                )

            # ---- Booking line A: DR Customer A/R (full)
            BookingLine.create(
                {
                    "transaction_booking_id": booking.id,
                    "description": f"Customer Sales Order A/R - {order.name}",
                    "product_id": False,
                    "account_number": order.customer_id.account_receivable_id.id,
                    "transaction_type": "dr",
                    "dr_amount": order.order_total,
                    "cr_amount": 0.0,
                    "transaction_date": fields.Date.context_today(self),
                }
            )

            # ---- Product lines: DR COGS, CR Inventory, CR Income
            for line in order.order_lines:
                product = line.product_id

                bom_currency = (
                    product.bom_id.currency_id
                    if product.bom_id
                    else product.currency_id
                )
                amount_in_bom_currency = product.cost * line.quantity
                product_cost_amount = (
                    amount_in_bom_currency * order.rate
                    if (bom_currency and bom_currency.name == "USD")
                    else amount_in_bom_currency
                )

                if not product.asset_account_id:
                    raise ValidationError(
                        f"Product '{product.name}' does not have an Asset Account set."
                    )
                if not product.income_account_id:
                    raise ValidationError(
                        f"Product '{product.name}' does not have an Income Account set."
                    )
                if not product.account_cogs_id:
                    raise ValidationError(
                        f"No COGS account assigned for the product '{product.name}'.\n"
                        f"Please configure 'COGS Account' in the product settings before continuing."
                    )

                for acc_name, acc in {
                    "Asset": product.asset_account_id,
                    "Income": product.income_account_id,
                    "COGS": product.account_cogs_id,
                }.items():
                    if acc.currency_id and acc.currency_id != expected_currency:
                        raise ValidationError(
                            f"{acc_name} account currency mismatch for product '{product.name}'.\n"
                            f"Expected: {expected_currency.name} | Actual: {acc.currency_id.name}"
                        )

                # DR COGS
                BookingLine.create(
                    {
                        "transaction_booking_id": booking.id,
                        "description": f"Sales Order - COGS for {product.name}",
                        "product_id": product.id,
                        "account_number": product.account_cogs_id.id,
                        "transaction_type": "dr",
                        "dr_amount": product_cost_amount,
                        "cr_amount": 0.0,
                        "transaction_date": fields.Date.context_today(self),
                    }
                )

                # CR Inventory
                BookingLine.create(
                    {
                        "transaction_booking_id": booking.id,
                        "description": f"Sales Order - Inventory out for {product.name}",
                        "product_id": product.id,
                        "account_number": product.asset_account_id.id,
                        "transaction_type": "cr",
                        "dr_amount": 0.0,
                        "cr_amount": product_cost_amount,
                        "transaction_date": fields.Date.context_today(self),
                    }
                )

                # CR Income
                BookingLine.create(
                    {
                        "transaction_booking_id": booking.id,
                        "description": f"Sales Revenue - {product.name}",
                        "product_id": product.id,
                        "account_number": product.income_account_id.id,
                        "transaction_type": "cr",
                        "dr_amount": 0.0,
                        "cr_amount": line.subtotal,
                        "transaction_date": fields.Date.context_today(self),
                    }
                )

            # ---- Payment legs: DR payment account / CR A/R (only if payment lines exist)
            for p in order.payment_lines:
                if float_compare(p.amount, 0.0, precision_digits=5) <= 0:
                    continue

                acc_type = p.account_id.account_type if p.account_id else "N/A"

                BookingLine.create(
                    {
                        "transaction_booking_id": booking.id,
                        "description": f"Payment - {p.payment_method_ids.name} ({acc_type})",
                        "product_id": False,
                        "account_number": p.account_id.id,
                        "transaction_type": "dr",
                        "dr_amount": p.amount,
                        "cr_amount": 0.0,
                        "transaction_date": fields.Date.context_today(self),
                    }
                )
                BookingLine.create(
                    {
                        "transaction_booking_id": booking.id,
                        "description": f"Payment applied to A/R - {p.payment_method_ids.name}",
                        "product_id": False,
                        "account_number": order.customer_id.account_receivable_id.id,
                        "transaction_type": "cr",
                        "dr_amount": 0.0,
                        "cr_amount": p.amount,
                        "transaction_date": fields.Date.context_today(self),
                    }
                )

            # -----------------------------
            # 3) Create/Update Receipt LAST (as you requested)
            # -----------------------------
            receipt = Receipt.search(
                [("cusotmer_sale_order_id", "=", order.id)], limit=1
            )

            receipt_vals = {
                "cusotmer_sale_order_id": order.id,
                "receipt_date": order.order_date,
                "due_amount": order.order_total,
                "paid_amount": total_paid,
                "remaining_amount": remaining,
                "customer_id": order.customer_id.id,
            }
            if "payment_status" in Receipt._fields:
                receipt_vals["payment_status"] = receipt_status
            elif "state" in Receipt._fields:
                receipt_vals["state"] = receipt_status

            if receipt:
                receipt.write(receipt_vals)
            else:
                receipt = Receipt.create(receipt_vals)

            # -----------------------------
            # 4) Link payment legs to receipt (customer sales payment management)
            # -----------------------------
            for p in order.payment_lines:
                if p.sales_receipt_id != receipt:
                    p.write({"sales_receipt_id": receipt.id})

            # Optional log
            try:
                order.message_post(
                    body=(
                        "✅ <b>Sale Financials Synced</b><br/>"
                        f"• Order Total: <b>{order.order_total}</b><br/>"
                        f"• Total Paid: <b>{total_paid}</b><br/>"
                        f"• Remaining: <b>{remaining}</b><br/>"
                        f"• Receipt Status: <b>{receipt_status}</b><br/>"
                        f"• Payment Legs: <b>{len(order.payment_lines)}</b>"
                    )
                )
            except Exception:
                pass

    def write(self, vals):
        try:
            # Start transaction
            with self.env.cr.savepoint():
                for order in self:

                    # 1.  Prevent changing payment_method from receivable → cash
                    # # ------------------------------------------------------------------
                    # if "payment_method" in vals and vals["payment_method"] in [
                    #     "cash",
                    #     "bank_transfer",
                    # ]:
                    #     for order in self:
                    #         if order.payment_method == "receivable":
                    #             raise ValidationError(
                    #                 "You cannot switch the payment method from "
                    #                 "'Account Receivable' to 'Cash or bank'.\n"
                    #                 "Receivable booking lines already exist for this order."
                    #             )
                    # if (
                    #     "payment_method" in vals
                    #     and vals["payment_method"] == "receivable"
                    # ):
                    #     for order in self:
                    #         if order.payment_method in ["cash", "bank_transfer"]:
                    #             raise ValidationError(
                    #                 "You cannot switch the payment method from "
                    #                 "'Cash or bank' to 'Account Receivable'.\n"
                    #                 "Cash booking lines already exist for this order."
                    #             )

                    # Loop through the lines in the database before they are updated
                    for line in order.order_lines:
                        if not line.product_id:
                            continue

                        # Fetch original (pre-update) record from DB
                        original_line = self.env[
                            "idil.customer.sale.order.line"
                        ].browse(line.id)
                        old_qty = original_line.quantity

                        # Get new quantity from vals if being changed, else use current
                        new_qty = line.quantity
                        if "order_lines" in vals:
                            for command in vals["order_lines"]:
                                if command[0] == 1 and command[1] == line.id:
                                    if "quantity" in command[2]:
                                        new_qty = command[2]["quantity"]

                        product = line.product_id

                        # Check if increase
                        if new_qty > old_qty:
                            diff = new_qty - old_qty
                            if product.stock_quantity < diff:
                                raise ValidationError(
                                    f"Not enough stock for product '{product.name}'.\n"
                                    f"Available: {product.stock_quantity}, Required additional: {diff}"
                                )
                            # product.stock_quantity -= diff

                        # If decrease
                        elif new_qty < old_qty:
                            diff = old_qty - new_qty
                            # product.stock_quantity += diff

                # === Perform the write ===
                res = super(CustomerSaleOrder, self).write(vals)

                # === Update related records ===
                for order in self:
                    # -- Update Product Movements --
                    movements = self.env["idil.product.movement"].search(
                        [("source_document", "=", order.name)]
                    )
                    for movement in movements:
                        matching_line = order.order_lines.filtered(
                            lambda l: l.product_id.id == movement.product_id.id
                        )
                        if matching_line:
                            movement.write(
                                {
                                    "quantity": matching_line[0].quantity * -1,
                                    "date": order.order_date,
                                    "customer_id": order.customer_id.id,
                                }
                            )

                    # -- Update Sales Receipt --
                    receipt = self.env["idil.sales.receipt"].search(
                        [("cusotmer_sale_order_id", "=", order.id)], limit=1
                    )
                    if receipt:
                        receipt.write(
                            {
                                "due_amount": order.order_total,
                                "paid_amount": order.total_paid,
                                "remaining_amount": order.balance_due,
                                "customer_id": order.customer_id.id,
                            }
                        )

                    # -- Update Transaction Booking & Booking Lines --
                    booking = self.env["idil.transaction_booking"].search(
                        [("cusotmer_sale_order_id", "=", order.id)], limit=1
                    )
                    if booking:
                        booking.write(
                            {
                                "trx_date": fields.Date.context_today(self),
                                "amount": order.order_total,
                                "customer_id": order.customer_id.id,
                                "payment_method": "bank_transfer",
                                "payment_status": "pending",
                            }
                        )

                        lines = self.env["idil.transaction_bookingline"].search(
                            [("transaction_booking_id", "=", booking.id)]
                        )
                        for line in lines:
                            matching_order_line = order.order_lines.filtered(
                                lambda l: l.product_id.id == line.product_id.id
                            )
                            if not matching_order_line:
                                continue

                            order_line = matching_order_line[0]
                            product = order_line.product_id

                            bom_currency = (
                                product.bom_id.currency_id
                                if product.bom_id
                                else product.currency_id
                            )

                            amount_in_bom_currency = product.cost * order_line.quantity

                            if bom_currency.name == "USD":
                                product_cost_amount = amount_in_bom_currency * self.rate
                            else:
                                product_cost_amount = amount_in_bom_currency

                            _logger.info(
                                f"Product Cost Amount: {product_cost_amount} for product {product.name}"
                            )
                            updated_values = {}

                            # COGS (DR)
                            if (
                                line.transaction_type == "dr"
                                and line.account_number.id == product.account_cogs_id.id
                            ):
                                updated_values["dr_amount"] = product_cost_amount
                                updated_values["cr_amount"] = 0

                            # Asset Inventory (CR)
                            elif (
                                line.transaction_type == "cr"
                                and line.account_number.id
                                == product.asset_account_id.id
                            ):
                                updated_values["cr_amount"] = product_cost_amount
                                updated_values["dr_amount"] = 0

                            # Receivable or Cash (DR)
                            elif (
                                line.transaction_type == "dr"
                                and line.account_number.id
                                == (
                                    order.customer_id.account_receivable_id.id
                                    if order.payment_method
                                    not in ["cash", "bank_transfer"]
                                    else order.account_number.id
                                )
                            ):
                                updated_values["dr_amount"] = order_line.subtotal
                                updated_values["cr_amount"] = 0

                            # Income (CR)
                            elif (
                                line.transaction_type == "cr"
                                and line.account_number.id
                                == product.income_account_id.id
                            ):
                                updated_values["cr_amount"] = order_line.subtotal
                                updated_values["dr_amount"] = 0

                            line.write(updated_values)

                return res
        except Exception as e:
            _logger.error("Error in create: %s", e)
            raise ValidationError(models._("Creation failed: %s") % str(e))

    def unlink(self):
        try:
            with self.env.cr.savepoint():
                for order in self:
                    for line in order.order_lines:
                        # 🔒 Prevent delete if any payment has been made
                        receipt = self.env["idil.sales.receipt"].search(
                            [("cusotmer_sale_order_id", "=", order.id)], limit=1
                        )
                        if receipt and receipt.paid_amount > 0:
                            raise ValidationError(
                                f"❌ Cannot delete order '{order.name}' because it has a paid amount of {receipt.paid_amount:.2f}."
                            )
                        product = line.product_id
                        if product:
                            # 1. Restore the stock
                            # product.stock_quantity += line.quantity

                            # 2. Delete related product movement
                            self.env["idil.product.movement"].search(
                                [
                                    ("product_id", "=", product.id),
                                    ("source_document", "=", order.name),
                                ]
                            ).unlink()

                            # 3. Delete related booking lines
                            booking_lines = self.env[
                                "idil.transaction_bookingline"
                            ].search(
                                [
                                    ("product_id", "=", product.id),
                                    (
                                        "transaction_booking_id.cusotmer_sale_order_id",
                                        "=",
                                        order.id,
                                    ),
                                ]
                            )
                            booking_lines.unlink()

                    # 5. Delete transaction booking if it exists
                    booking = self.env["idil.transaction_booking"].search(
                        [("cusotmer_sale_order_id", "=", order.id)], limit=1
                    )
                    if booking:
                        booking.unlink()

                    # Release linked place orders BEFORE deleting the SOs
                    place_orders = self.env["idil.customer.place.order"]
                    for so in self:
                        po = so.customer_place_order_id
                        if not po:
                            # fallback in case only the reverse link exists
                            po = self.env["idil.customer.place.order"].search(
                                [("sale_order_id", "=", so.id)], limit=1
                            )
                        if po:
                            place_orders |= po

                    if place_orders:
                        place_orders.write({"state": "draft", "sale_order_id": False})

                    res = super(CustomerSaleOrder, self).unlink()

                    # 4. Delete sales receipt
                    self.env["idil.sales.receipt"].search(
                        [("cusotmer_sale_order_id", "=", order.id)]
                    ).unlink()

                    return res
        except Exception as e:
            _logger.error("Error in create: %s", e)
            raise ValidationError(models._("Creation failed: %s") % str(e))


class CustomerSaleOrderLine(models.Model):
    _name = "idil.customer.sale.order.line"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _description = "CustomerSale Order Line"

    order_id = fields.Many2one("idil.customer.sale.order", string="Sale Order")
    product_id = fields.Many2one("my_product.product", string="Product")
    quantity_Demand = fields.Float(string="Demand", default=1.0)
    available_stock = fields.Float(
        string="Available Stock",
        related="product_id.stock_quantity",
        readonly=True,
        store=False,
    )

    quantity = fields.Float(string="Quantity Used", required=True, tracking=True)
    cost_price = fields.Float(
        string="Cost Price", store=True, tracking=True
    )  # Save cost to DB

    # Editable price unit with dynamic default
    price_unit = fields.Float(
        string="Unit Price",
        default=lambda self: self.product_id.sale_price if self.product_id else 0.0,
    )
    cogs = fields.Float(string="COGS", compute="_compute_cogs")

    subtotal = fields.Float(string="Due Amount", compute="_compute_subtotal")
    profit = fields.Float(string="Profit Amount", compute="_compute_profit")
    customer_opening_balance_line_id = fields.Many2one(
        "idil.customer.opening.balance.line",
        string="Customer Opening Balance Line",
        ondelete="cascade",
    )

    @api.constrains("product_id", "price_unit")
    def _check_min_sales_price(self):
        for line in self:
            if not line.product_id or not line.price_unit:
                continue

            min_price = line.product_id.min_sales_price or 0.0
            if min_price <= 0:
                continue

            # safe float compare
            if float_compare(line.price_unit, min_price, precision_digits=5) < 0:
                raise ValidationError(
                    models._(
                        "Unit Price for '%(product)s' cannot be less than Min Sales Price.\n"
                        "Min: %(min)s | Entered: %(entered)s"
                    )
                    % {
                        "product": line.product_id.name,
                        "min": min_price,
                        "entered": line.price_unit,
                    }
                )

    @api.onchange("product_id", "price_unit")
    def _onchange_max_sales_price_warning(self):
        for line in self:
            if not line.product_id or not line.price_unit:
                continue

            max_price = line.product_id.max_sales_price or 0.0
            if max_price <= 0:
                continue

            # If entered price is higher than max => WARNING (allow proceed)
            if float_compare(line.price_unit, max_price, precision_digits=5) > 0:
                return {
                    "warning": {
                        "title": models._("High Price Warning"),
                        "message": models._(
                            "The Unit Price for '%(product)s' is higher than the Max Sales Price.\n"
                            "Max: %(max)s | Entered: %(entered)s\n\n"
                            "You can proceed, but please confirm this price is correct."
                        )
                        % {
                            "product": line.product_id.name,
                            "max": max_price,
                            "entered": line.price_unit,
                        },
                    }
                }

    @api.depends("quantity", "price_unit")
    def _compute_subtotal(self):
        for line in self:
            line.subtotal = line.quantity * line.price_unit

    @api.depends("cogs", "subtotal")
    def _compute_profit(self):
        for line in self:
            line.profit = line.subtotal - line.cogs

    @api.depends("quantity", "cost_price", "order_id.rate")
    def _compute_cogs(self):
        """Computes the Cost of Goods Sold (COGS) considering the exchange rate"""
        for line in self:
            if line.order_id:
                line.cogs = line.quantity * line.cost_price
            else:
                line.cogs = (
                    line.quantity * line.cost_price
                )  # Fallback if no rate is found

    @api.model
    def create(self, vals):
        try:
            with self.env.cr.savepoint():
                # If linked to opening balance, skip product_id and stock check!
                if vals.get("customer_opening_balance_line_id"):
                    vals["product_id"] = False  # Explicitly make sure it's empty
                    return super(CustomerSaleOrderLine, self).create(vals)
                # Else: normal process, require product and update stock
                if not vals.get("product_id"):
                    raise ValidationError(
                        "You must select a product for this order line (unless it's for opening balance)."
                    )
                record = super(CustomerSaleOrderLine, self).create(vals)
                self.update_product_stock(record.product_id, record.quantity)
                return record
        except Exception as e:
            _logger.error(f"Create transaction failed: {str(e)}")
            raise ValidationError(f"Transaction failed: {str(e)}")

    @staticmethod
    def update_product_stock(product, quantity):
        """Static Method: Update product stock quantity based on the sale order line quantity change."""
        # If this order is for opening balance, skip accounting booking: opening balance does its own accounting

        new_stock_quantity = product.stock_quantity - quantity
        if new_stock_quantity < 0:
            raise ValidationError(
                "Insufficient stock for product '{}'. The available stock quantity is {:.2f}, "
                "but the required quantity is {:.2f}.".format(
                    product.name, product.stock_quantity, abs(quantity)
                )
            )
        # product.stock_quantity = new_stock_quantity

    @api.constrains("quantity", "price_unit")
    def _check_quantity_and_price(self):
        """Ensure that quantity and unit price are greater than zero."""
        for line in self:

            # If this order is for opening balance, skip accounting booking: opening balance does its own accounting
            if line.customer_opening_balance_line_id:
                return

            if line.quantity <= 0:
                raise ValidationError(
                    f"Product '{line.product_id.name}' must have a quantity greater than zero."
                )
            if line.price_unit <= 0:
                raise ValidationError(
                    f"Product '{line.product_id.name}' must have a unit price greater than zero."
                )

    @api.onchange("product_id", "order_id.rate")
    def _onchange_product_id(self):
        """When product_id changes, update the cost price"""
        if self.product_id:
            self.cost_price = (
                self.product_id.cost * self.order_id.rate
            )  # Fetch cost price from product
            self.price_unit = (
                self.product_id.sale_price
            )  # Set sale price as default unit price
        else:
            self.cost_price = 0.0
            self.price_unit = 0.0


class CustomerSalePayment(models.Model):
    _name = "idil.customer.sale.payment"
    _description = "Sale Order Payment"

    order_id = fields.Many2one("idil.customer.sale.order", string="Customer Sale Order")
    sales_payment_id = fields.Many2one(
        "idil.sales.payment", string="Sales Payment", ondelete="cascade"
    )
    sales_receipt_id = fields.Many2one("idil.sales.receipt", string="Sales Receipt")

    customer_id = fields.Many2one(
        "idil.customer.registration",
        string="Customer",
        related="order_id.customer_id",
        store=True,
        readonly=True,
    )

    # Currency fields
    currency_id = fields.Many2one(
        "res.currency",
        string="Currency",
        required=True,
        default=lambda self: self.env["res.currency"].search(
            [("name", "=", "SL")], limit=1
        ),
        readonly=True,
    )

    company_id = fields.Many2one(
        related="order_id.company_id", store=True, readonly=True
    )

    payment_method_ids = fields.Many2one(
        "idil.payment.method",
        string="Payment Method",
        required=True,
        domain="[('company_id','=',company_id), ('active','=',True)]",
    )

    account_id = fields.Many2one(
        "idil.chart.account",
        string="Account",
        related="payment_method_ids.account_id",
        store=True,
        readonly=True,
    )

    amount = fields.Float(string="Amount", required=True)
    date = fields.Date(string="Date", required=True)
    bulk_receipt_payment_id = fields.Many2one(
        "idil.receipt.bulk.payment", index=True, ondelete="cascade"
    )

    @api.onchange("payment_method_ids")
    def _onchange_payment_method_id(self):
        for rec in self:
            if rec.payment_method_ids:
                rec.account_id = rec.payment_method_ids.account_id

    @api.constrains("amount")
    def _check_amount(self):
        for rec in self:
            if rec.amount <= 0:
                raise ValidationError("Payment amount must be greater than zero.")
