from odoo import models, fields, api, exceptions
from datetime import datetime
from datetime import date
import re
from odoo.exceptions import ValidationError, UserError
import logging

from odoo import _
from odoo.exceptions import UserError

from odoo.tools import float_round, format_datetime

_logger = logging.getLogger(__name__)


class SaleOrder(models.Model):
    _name = "idil.sale.order"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _description = "Sale Order"

    company_id = fields.Many2one(
        "res.company", default=lambda s: s.env.company, required=True
    )
    name = fields.Char(string="Sales Reference", tracking=True)

    sales_person_id = fields.Many2one(
        "idil.sales.sales_personnel", string="Salesperson", required=True
    )
    salesperson_ar_account_id = fields.Many2one(
        "idil.chart.account",
        string="Salesperson A/R Account",
        related="sales_person_id.account_receivable_id",
        store=True,
        readonly=True,
    )

    # Optional: show the currency of the receivable account itself (more accurate)
    salesperson_ar_currency_id = fields.Many2one(
        "res.currency",
        string="A/R Account Currency",
        related="sales_person_id.account_receivable_id.currency_id",
        store=True,
        readonly=True,
    )

    salesperson_due_amount = fields.Float(
        string="Remaining Balance",
        related="sales_person_id.due_amount",
        store=False,  # real-time
        readonly=True,
        digits=(16, 5),
    )

    # Add a reference to the salesperson's order
    salesperson_order_id = fields.Many2one(
        "idil.salesperson.place.order",
        string="Related Salesperson Order",
        help="This field links to the salesperson order that this actual order is based on.",
    )

    order_date = fields.Datetime(string="Order Date", default=fields.Datetime.now)
    order_lines = fields.One2many(
        "idil.sale.order.line",
        "order_id",
        string="Order Lines",
        tracking=True,
    )
    order_total = fields.Float(
        string="Total (FY)",
        compute="_compute_order_total",
        store=True,
        tracking=True,
    )

    # 1) default state: DRAFT (not confirmed)
    state = fields.Selection(
        [("draft", "Draft"), ("confirmed", "Confirmed"), ("cancel", "Cancelled")],
        default="draft",
        tracking=True,
    )

    commission_amount = fields.Monetary(
        string="Commission Amount (A/R Currency)",
        currency_field="salesperson_ar_currency_id",
        compute="_compute_total_commission",
        store=True,
        tracking=True,
    )

    # Currency fields
    currency_id = fields.Many2one(
        "res.currency",
        string="Currency for Exchange Rate",
        required=True,
        default=lambda self: self.env["res.currency"].search(
            [("name", "=", "SL")], limit=1
        ),
        readonly=True,
        tracking=True,
    )
    USD_currency_id = fields.Many2one(
        "res.currency",
        string="USD Currency",
        required=True,
        default=lambda self: self.env["res.currency"].search(
            [("name", "=", "USD")], limit=1
        ),
        readonly=True,
        tracking=True,
    )
    rate = fields.Float(
        string="Exchange Rate",
        compute="_compute_exchange_rate",
        store=True,
        readonly=True,
        tracking=True,
    )
    total_due_usd = fields.Float(
        string="Total Due (USD)",
        compute="_compute_totals_in_usd",
        currency_field="USD_currency_id",
        store=True,
        tracking=True,
    )
    total_commission_usd = fields.Float(
        string="Commission (USD)",
        compute="_compute_totals_in_usd",
        store=True,
        tracking=True,
    )
    total_discount_usd = fields.Float(
        string="Discount (USD)",
        compute="_compute_totals_in_usd",
        store=True,
        tracking=True,
    )
    total_returned_qty = fields.Float(
        string="Total Returned Quantity",
        compute="_compute_total_returned_qty",
        store=False,
        readonly=True,
    )

    total_cost_price = fields.Float(
        string="Total Cost Price",
        compute="_compute_total_cost_price",
        store=False,
        digits=(16, 6),
        readonly=True,
        tracking=True,
    )

    booking_id = fields.Many2one(
        "idil.transaction_booking",
        string="Journal Entry",
        compute="_compute_booking_preview",
        store=False,
        readonly=True,
    )

    booking_line_ids = fields.One2many(
        "idil.transaction_bookingline",
        "sale_order_id",
        string="Journal Lines",
        readonly=True,
    )

    journal_total_dr = fields.Float(
        string="Total Debits",
        compute="_compute_booking_preview",
        store=False,
        readonly=True,
        digits=(16, 5),
    )
    journal_total_cr = fields.Float(
        string="Total Credits",
        compute="_compute_booking_preview",
        store=False,
        readonly=True,
        digits=(16, 5),
    )
    journal_is_balanced = fields.Boolean(
        string="Balanced",
        compute="_compute_booking_preview",
        store=False,
        readonly=True,
    )

    journal_summary_html = fields.Html(
        string="Journal Summary",
        compute="_compute_journal_summary_html",
        store=False,
        readonly=True,
    )

    @api.depends(
        "booking_line_ids.account_number",
        "booking_line_ids.dr_amount",
        "booking_line_ids.cr_amount",
    )
    def _compute_journal_summary_html(self):
        for o in self:
            if not o.booking_line_ids:
                o.journal_summary_html = (
                    "<div class='text-muted'>No journal lines yet.</div>"
                )
                continue

            # group by account
            grouped = {}
            for ln in o.booking_line_ids:
                acc = ln.account_number
                if not acc:
                    continue
                key = acc.id
                if key not in grouped:
                    grouped[key] = {
                        "code": acc.code or "",
                        "name": acc.name or "",
                        "currency": acc.currency_id.name or "",
                        "dr": 0.0,
                        "cr": 0.0,
                    }
                grouped[key]["dr"] += float(ln.dr_amount or 0.0)
                grouped[key]["cr"] += float(ln.cr_amount or 0.0)

            # totals
            total_dr = sum(v["dr"] for v in grouped.values())
            total_cr = sum(v["cr"] for v in grouped.values())
            balanced = abs(total_dr - total_cr) < 0.00001

            # build HTML table
            rows = []
            for v in sorted(grouped.values(), key=lambda x: (x["code"], x["name"])):
                rows.append(
                    f"""
                    <tr>
                        <td style="white-space:nowrap;">{v["code"]}</td>
                        <td>{v["name"]}</td>
                        <td style="text-align:right;">{v["currency"]}</td>
                        <td style="text-align:right;">{v["dr"]:,.5f}</td>
                        <td style="text-align:right;">{v["cr"]:,.5f}</td>
                    </tr>
                """
                )

            o.journal_summary_html = f"""
            <div style="border:1px solid #e5e7eb; border-radius:12px; padding:12px; background:#fff;">
            <div style="font-weight:700; margin-bottom:8px;">Accounting Entry Summary</div>

            <table style="width:100%; border-collapse:collapse;">
                <thead>
                <tr style="border-bottom:1px solid #e5e7eb;">
                    <th style="text-align:left; padding:6px;">Code</th>
                    <th style="text-align:left; padding:6px;">Account</th>
                    <th style="text-align:right; padding:6px;">Currency</th>
                    <th style="text-align:right; padding:6px;">Dr</th>
                    <th style="text-align:right; padding:6px;">Cr</th>
                </tr>
                </thead>
                <tbody>
                {''.join(rows)}
                </tbody>
                <tfoot>
                <tr style="border-top:1px solid #e5e7eb;">
                    <td colspan="3" style="padding:6px; font-weight:700;">Totals</td>
                    <td style="padding:6px; text-align:right; font-weight:700;">{total_dr:,.5f}</td>
                    <td style="padding:6px; text-align:right; font-weight:700;">{total_cr:,.5f}</td>
                </tr>
                </tfoot>
            </table>

            <div style="margin-top:10px; font-weight:700; color:{'#16a34a' if balanced else '#dc2626'};">
                {'✔ Balanced' if balanced else '✖ Not Balanced'}
            </div>
            </div>
            """

    @api.depends("state", "booking_line_ids.dr_amount", "booking_line_ids.cr_amount")
    def _compute_booking_preview(self):
        Booking = self.env["idil.transaction_booking"]
        for o in self:
            b = Booking.search([("sale_order_id", "=", o.id)], order="id desc", limit=1)
            o.booking_id = b

            # Prefer booking totals if exist, else sum lines
            if b:
                dr = float(b.debit_total or 0.0)
                cr = float(b.credit_total or 0.0)
            else:
                dr = sum(o.booking_line_ids.mapped("dr_amount")) or 0.0
                cr = sum(o.booking_line_ids.mapped("cr_amount")) or 0.0

            o.journal_total_dr = dr
            o.journal_total_cr = cr
            o.journal_is_balanced = abs(dr - cr) < 0.00001

    def action_print_sale_invoice_pdf(self):
        self.ensure_one()
        return self.env.ref("idil.report_sale_invoice_pdf").report_action(self)

    def action_print_sale_invoice_two_copy_pdf(self):
        self.ensure_one()
        return self.env.ref("idil.report_sale_invoice_two_copy_pdf").report_action(self)

    @api.depends("order_lines", "order_lines.product_id", "order_lines.quantity")
    def _compute_total_cost_price(self):
        for order in self:
            total = 0.0
            for line in order.order_lines:
                product = line.product_id
                qty = line.quantity
                if product and qty:
                    if product.bom_id:
                        bom_currency = product.bom_id.currency_id.name
                        if bom_currency == "SL":
                            total += (product.cost * qty) / order.rate
                        else:
                            total += product.cost * qty
                    else:
                        total += (product.cost * qty) / order.rate
            order.total_cost_price = total

    @api.depends("order_lines", "order_lines.product_id")
    def _compute_total_returned_qty(self):
        for order in self:
            return_lines = self.env["idil.sale.return.line"].search(
                [
                    ("return_id.sale_order_id", "=", order.id),
                    ("return_id.state", "=", "confirmed"),
                ]
            )
            order.total_returned_qty = sum(return_lines.mapped("returned_quantity"))

    @api.depends(
        "order_lines.subtotal",
        "order_lines.commission_amount",
        "order_lines.discount_amount",
        "rate",
    )
    def _compute_totals_in_usd(self):
        for order in self:
            subtotal = sum(order.order_lines.mapped("subtotal"))
            commission = sum(order.order_lines.mapped("commission_amount"))
            discount = sum(order.order_lines.mapped("discount_amount"))

            rate = order.rate or 0.0
            order.total_due_usd = sum(order.order_lines.mapped("subtotal_usd"))
            order.total_commission_usd = commission / rate if rate else 0.0
            order.total_discount_usd = discount / rate if rate else 0.0

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

    @api.depends(
        "order_lines.commission_amount",
        "order_lines.currency_id",
        "salesperson_ar_currency_id",
        "rate",
        "order_lines.product_id.is_sales_commissionable",
        "order_lines.product_id.commission",
        "order_lines.product_id.sales_account_id",
    )
    def _compute_total_commission(self):
        for order in self:
            total_commission_ar = 0.0

            ar_cur = order.salesperson_ar_currency_id
            rate = float(order.rate or 0.0)

            # If no salesperson/currency yet, keep 0 (don’t crash compute)
            if not ar_cur:
                order.commission_amount = 0.0
                continue

            # Your conversion convention: 1 USD = rate SL
            def _convert(amount, from_cur, to_cur):
                amount = float(amount or 0.0)
                if not from_cur or not to_cur or from_cur.id == to_cur.id:
                    return amount
                if rate <= 0:
                    raise ValidationError("Exchange rate is required and must be > 0.")

                if from_cur.name == "SL" and to_cur.name == "USD":
                    return amount / rate
                if from_cur.name == "USD" and to_cur.name == "SL":
                    return amount * rate

                raise ValidationError(
                    f"Unsupported currency pair: {from_cur.name} -> {to_cur.name}"
                )

            for line in order.order_lines:
                product = line.product_id
                if not product or not product.is_sales_commissionable:
                    continue

                if not product.sales_account_id:
                    raise ValidationError(
                        _("Product '%s' does not have a Sales Commission Account set.")
                        % product.name
                    )
                if product.commission <= 0:
                    raise ValidationError(
                        _("Product '%s' does not have a valid Commission Rate set.")
                        % product.name
                    )

                line_cur = line.currency_id or product.asset_account_id.currency_id
                total_commission_ar += _convert(
                    line.commission_amount, line_cur, ar_cur
                )

            order.commission_amount = total_commission_ar

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
            return self.env["ir.sequence"].next_by_code("idil.sale.order.sequence")

    @api.depends("order_lines.subtotal_fy")
    def _compute_order_total(self):
        for order in self:
            order.order_total = sum(order.order_lines.mapped("subtotal_fy"))

    @api.onchange("sales_person_id")
    def _onchange_sales_person_id(self):
        if not self.sales_person_id:
            return

        last_order = self.env["idil.salesperson.place.order"].search(
            [("salesperson_id", "=", self.sales_person_id.id), ("state", "=", "draft")],
            order="order_date desc",
            limit=1,
        )

        if last_order:
            order_lines_cmds = [(5, 0, 0)]
            for line in last_order.order_lines:
                discount_quantity = (
                    (line.product_id.discount / 100) * (line.quantity)
                    if line.product_id.is_quantity_discount
                    else 0.0
                )
                order_lines_cmds.append(
                    (
                        0,
                        0,
                        {
                            "product_id": line.product_id.id,
                            "quantity_Demand": line.quantity,
                            "discount_quantity": discount_quantity,
                            "quantity": line.quantity,
                        },
                    )
                )
            self.order_lines = order_lines_cmds
        else:
            raise UserError(
                ("This salesperson does not have any draft orders to reference.")
            )

    # 2) CREATE: link salesperson draft order & set reference — but DO NOT post any side-effects
    @api.model
    def create(self, vals):
        try:
            with self.env.cr.savepoint():
                if "sales_person_id" in vals:
                    salesperson_id = vals["sales_person_id"]
                    sp_order = self.env["idil.salesperson.place.order"].search(
                        [
                            ("salesperson_id", "=", salesperson_id),
                            ("state", "=", "draft"),
                        ],
                        order="order_date desc",
                        limit=1,
                    )
                    if sp_order:
                        vals["salesperson_order_id"] = sp_order.id
                    else:
                        raise UserError(
                            (
                                "No draft Salesperson Order found for the given salesperson."
                            )
                        )

                if not vals.get("name"):
                    vals["name"] = self._generate_order_reference(vals)

                vals["state"] = "draft"

                new_order = super().create(vals)
                return new_order
        except Exception as e:
            _logger.error("Create transaction failed: %s", e)
            raise ValidationError(("Transaction failed: %s") % e)

    # 3) CONFIRM: single place to do validations + posting (receipt, movements, accounting)
    def button_confirm(self):
        for order in self:
            if order.state == "confirmed":
                raise UserError("This Sales Order is already confirmed.")

            if order.state == "cancel":
                raise UserError("This Sales Order is already cancelled.")

            # precheck
            order.precheck_before_confirm()
            order.freeze_exchange_rate()

            try:
                with self.env.cr.savepoint():

                    # ✅ Step 0: capture credit BEFORE creating any order transactions
                    credit_before = order._get_salesperson_credit_before_order()

                    # ✅ Step 1: post normal effects
                    order.post_salesperson_transactions_on_confirm()
                    order._create_sales_commission_record()

                    order.create_movements_on_confirm()
                    order.book_accounting_entry()

                    # ✅ Step 2: apply previous credit AFTER receipt exists
                    order._apply_previous_credit_to_receipt(credit_before)

                    # flip states only after successful postings
                    order.state = "confirmed"
                    if order.salesperson_order_id:
                        order.salesperson_order_id.write({"state": "confirmed"})

                    _logger.info("Confirmed: %s", order.name)

            except Exception as e:
                _logger.error("Confirm failed for %s: %s", order.name, e)
                raise ValidationError("Confirm failed: %s" % e)

    def post_salesperson_transactions_on_confirm(self):
        self.ensure_one()
        if not self.sales_person_id:
            return

        ar_acc = self.sales_person_id.account_receivable_id
        if not ar_acc or not ar_acc.currency_id:
            raise ValidationError(
                "Salesperson A/R account and its currency are required."
            )

        staff_cur = ar_acc.currency_id
        rate = float(self.rate or 0.0)
        if rate <= 0:
            raise ValidationError("Exchange rate is required and must be > 0.")

        schedule = (
            self.sales_person_id.commission_payment_schedule
        )  # 'monthly' | 'daily'

        def _convert(amount, from_cur, to_cur, rate):
            """1 USD = rate SL"""
            amount = float(amount or 0.0)
            if not from_cur or not to_cur or from_cur.id == to_cur.id:
                return amount
            if from_cur.name == "USD" and to_cur.name == "SL":
                return amount * rate
            if from_cur.name == "SL" and to_cur.name == "USD":
                return amount / rate
            raise ValidationError(
                f"Unsupported currency pair {from_cur.name} -> {to_cur.name}"
            )

        Txn = self.env["idil.salesperson.transaction"]

        for line in self.order_lines:
            product = line.product_id
            if (
                not product
                or not product.asset_account_id
                or not product.asset_account_id.currency_id
            ):
                raise ValidationError(
                    f"Product '{product.display_name}' is missing Asset Account currency."
                )

            asset_cur = product.asset_account_id.currency_id
            qty = float(line.quantity or 0.0)
            cur_name = staff_cur.name or ""

            # ------------------------------------------------------------------
            # BASE AMOUNT (same rule as subtotal base, but explicit & stable)
            # base = qty*price - discount_qty*price
            # ------------------------------------------------------------------
            discount_qty = float(line.discount_quantity or 0.0)
            price = float(line.price_unit or 0.0)

            base_asset = qty * price
            discount_asset = float(line.discount_amount or 0.0)
            commission_asset = float(line.commission_amount or 0.0)

            base_staff = _convert(base_asset, asset_cur, staff_cur, rate)
            discount_staff = (
                _convert(discount_asset, asset_cur, staff_cur, rate)
                if discount_asset
                else 0.0
            )
            commission_staff = (
                _convert(commission_asset, asset_cur, staff_cur, rate)
                if commission_asset
                else 0.0
            )

            # ==================================================================
            # CASE 1: MONTHLY COMMISSION
            # ==================================================================
            if schedule == "monthly":

                # 1️⃣ A/R NET (base - discount)
                ar_out = base_staff

                Txn.create(
                    {
                        "sales_person_id": self.sales_person_id.id,
                        "sale_order_id": self.id,
                        "order_id": self.id,
                        "date": self.order_date,
                        "transaction_type": "out",
                        "amount": ar_out - commission_staff,
                        "description": (
                            f"A/R NET (MONTHLY) | {product.name} | Qty:{qty:.2f} | "
                            f"Net:{ar_out:,.2f} {cur_name}"
                        ),
                    }
                )

                # 2️⃣ COMMISSION RECORDED (OUT – affects balance)
                Txn.create(
                    {
                        "sales_person_id": self.sales_person_id.id,
                        "sale_order_id": self.id,
                        "order_id": self.id,
                        "date": self.order_date,
                        "transaction_type": "out",
                        "amount": commission_staff,
                        "description": (
                            f"COMMISSION MONTHLY | {product.name} | Qty:{qty:.2f} | "
                            f"Amt:{commission_staff:,.2f} {cur_name}"
                        ),
                    }
                )

                # 3️⃣ DISCOUNT ON SPOT (IN)
                Txn.create(
                    {
                        "sales_person_id": self.sales_person_id.id,
                        "sale_order_id": self.id,
                        "order_id": self.id,
                        "date": self.order_date,
                        "transaction_type": "in",
                        "amount": discount_staff,
                        "description": (
                            f"DISCOUNT ON SPOT | {product.name} | Qty:{qty:.2f} | "
                            f"Amt:{discount_staff:,.2f} {cur_name}"
                        ),
                    }
                )

            # ==================================================================
            # CASE 2: DAILY COMMISSION
            # ==================================================================
            else:

                # 1️⃣ A/R GROSS (commission included)
                ar_out = base_staff

                Txn.create(
                    {
                        "sales_person_id": self.sales_person_id.id,
                        "sale_order_id": self.id,
                        "order_id": self.id,
                        "date": self.order_date,
                        "transaction_type": "out",
                        "amount": ar_out,
                        "description": (
                            f"A/R GROSS (DAILY) | {product.name} | Qty:{qty:.2f} | "
                            f"Amt:{ar_out:,.2f} {cur_name}"
                        ),
                    }
                )

                # 2️⃣ COMMISSION ON SPOT (IN – reduce A/R)
                Txn.create(
                    {
                        "sales_person_id": self.sales_person_id.id,
                        "sale_order_id": self.id,
                        "order_id": self.id,
                        "date": self.order_date,
                        "transaction_type": "in",
                        "amount": commission_staff,
                        "description": (
                            f"COMMISSION DAILY | {product.name} | Qty:{qty:.2f} | "
                            f"Amt:{commission_staff:,.2f} {cur_name}"
                        ),
                    }
                )

                # 3️⃣ DISCOUNT ON SPOT (IN)
                Txn.create(
                    {
                        "sales_person_id": self.sales_person_id.id,
                        "sale_order_id": self.id,
                        "order_id": self.id,
                        "date": self.order_date,
                        "transaction_type": "in",
                        "amount": discount_staff,
                        "description": (
                            f"DISCOUNT ON SPOT | {product.name} | Qty:{qty:.2f} | "
                            f"Amt:{discount_staff:,.2f} {cur_name}"
                        ),
                    }
                )

        # ======================================================================
        # FINAL SAFETY CHECK: salesperson balance == receipt due
        # ======================================================================
        txns = Txn.search(
            [
                ("sale_order_id", "=", self.id),
                ("sales_person_id", "=", self.sales_person_id.id),
            ]
        )

        total_out = sum(
            txns.filtered(lambda t: t.transaction_type == "out").mapped("amount")
        )
        total_in = sum(
            txns.filtered(lambda t: t.transaction_type == "in").mapped("amount")
        )
        net_due = total_out - total_in

        receipt = self.env["idil.sales.receipt"].search(
            [("sales_order_id", "=", self.id)], limit=1
        )

        if receipt and receipt.currency_id.id == staff_cur.id:
            if abs(float(receipt.due_amount or 0.0) - net_due) > 0.01:
                raise ValidationError(
                    "Salesperson running balance mismatch.\n"
                    f"Txn Net Due: {net_due}\n"
                    f"Receipt Due: {receipt.due_amount}"
                )

    def _create_sales_commission_record(self):
        """Create deferred commission record in salesperson A/R currency (USD staff vs SL staff)."""
        for order in self:
            # ✅ Only monthly creates deferred commission record
            schedule = order.sales_person_id.commission_payment_schedule
            if schedule != "monthly":
                continue

            ar_acc = order.sales_person_id.account_receivable_id
            if not ar_acc or not ar_acc.currency_id:
                raise ValidationError(
                    "Salesperson A/R account and its currency are required."
                )

            staff_cur = ar_acc.currency_id
            rate = float(order.rate or 0.0)
            if rate <= 0:
                raise ValidationError("Exchange rate is required and must be > 0.")

            def _convert(amount, from_cur, to_cur, rate):
                """Convention: 1 USD = rate SL."""
                amount = float(amount or 0.0)
                if not from_cur or not to_cur or from_cur.id == to_cur.id:
                    return amount

                if from_cur.name == "SL" and to_cur.name == "USD":
                    return amount / rate
                if from_cur.name == "USD" and to_cur.name == "SL":
                    return amount * rate

                raise ValidationError(
                    f"Unsupported currency pair: {from_cur.name} -> {to_cur.name}"
                )

            total_comm_staff = 0.0

            # Sum commissions per line converting from product asset currency -> staff currency
            for line in order.order_lines:
                if float(line.commission_amount or 0.0) <= 0:
                    continue

                product = line.product_id
                if (
                    not product
                    or not product.asset_account_id
                    or not product.asset_account_id.currency_id
                ):
                    raise ValidationError(
                        f"Product '{product.display_name}' is missing Asset Account currency."
                    )

                asset_cur = product.asset_account_id.currency_id
                total_comm_staff += _convert(
                    float(line.commission_amount), asset_cur, staff_cur, rate
                )

            if total_comm_staff > 0:
                comm = self.env["idil.sales.commission"].create(
                    {
                        "sale_order_id": order.id,
                        "sales_person_id": order.sales_person_id.id,
                        "date": order.order_date,
                        "currency_id": staff_cur.id,
                        "commission_amount": total_comm_staff,
                        "state": "normal",
                    }
                )

                # ✅ Apply previous paid commission from returned orders (like receipt allocation)

                comm.consume_salesperson_balance()

    def precheck_before_confirm(self):

        self.ensure_one()

        if not self.order_lines:
            raise UserError(("You must add at least one order line."))

        if not self.sales_person_id.account_receivable_id:
            raise ValidationError(
                ("The salesperson does not have a receivable account set.")
            )

        for line in self.order_lines:
            p = line.product_id
            if not p.income_account_id:
                raise ValidationError(
                    ("Income account missing for product: %s") % p.display_name
                )
            if not p.asset_account_id:
                raise ValidationError(
                    ("Asset (inventory) account missing for product: %s")
                    % p.display_name
                )
            if not p.account_cogs_id:
                raise ValidationError(
                    ("COGS account missing for product: %s") % p.display_name
                )

            if p.is_sales_commissionable and p.commission <= 0:
                raise ValidationError(
                    ("Invalid commission for product: %s") % p.display_name
                )

            if line.quantity <= 0:
                raise ValidationError(
                    ("Quantity must be positive for product: %s") % p.display_name
                )

            if p.stock_quantity < line.quantity:
                raise ValidationError(
                    ("Insufficient stock for product: %s") % p.display_name
                )

    def freeze_exchange_rate(self):
        self.ensure_one()
        if not self.currency_id:
            self.rate = 0.0
            return

        on_date = (self.order_date or fields.Datetime.now()).date()
        rate = self.env["res.currency.rate"].search(
            [
                ("currency_id", "=", self.currency_id.id),
                ("name", "=", on_date),
                ("company_id", "=", self.env.company.id),
            ],
            limit=1,
        )
        self.rate = rate.rate if rate else (self.rate or 0.0)

    def create_movements_on_confirm(self):
        self.ensure_one()
        Movement = self.env["idil.product.movement"]
        for line in self.order_lines:
            Movement.create(
                {
                    "product_id": line.product_id.id,
                    "sale_order_id": self.id,
                    "movement_type": "out",
                    "quantity": line.quantity
                    * -1,  # keep positive; direction via movement_type
                    "date": self.order_date,
                    "source_document": self.name,
                    "sales_person_id": self.sales_person_id.id,
                }
            )

    def _validate_before_posting(self):
        """Validate all required setup before creating any booking/lines."""
        for order in self:
            if (
                not order.sales_person_id
                or not order.sales_person_id.account_receivable_id
            ):
                raise ValidationError(
                    "Salesperson or Salesperson A/R account is missing."
                )

            if not order.rate or float(order.rate) <= 0:
                raise ValidationError("Exchange rate is missing or invalid.")

            trx_source = self.env["idil.transaction.source"].search(
                [("name", "=", "Sales Order")], limit=1
            )
            if not trx_source:
                raise ValidationError('Transaction source "Sales Order" not found.')

            if not order.order_lines:
                raise ValidationError(
                    "Order lines are required to post accounting entry."
                )

            for line in order.order_lines:
                product = line.product_id
                if not product:
                    raise ValidationError("Order line is missing product.")

                # Required accounts
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
                        f"Product '{product.name}' does not have a COGS Account set."
                    )

                # Required currencies on accounts
                if not product.asset_account_id.currency_id:
                    raise ValidationError(
                        f"Product '{product.name}' Asset Account has no currency."
                    )
                if not product.income_account_id.currency_id:
                    raise ValidationError(
                        f"Product '{product.name}' Income Account has no currency."
                    )
                if not product.account_cogs_id.currency_id:
                    raise ValidationError(
                        f"Product '{product.name}' COGS Account has no currency."
                    )
                if not order.sales_person_id.account_receivable_id.currency_id:
                    raise ValidationError("Salesperson A/R account has no currency.")

                # Cost currency logic (your current assumption)
                cost_currency = product.asset_account_id.currency_id
                if cost_currency.name not in ("USD", "SL"):
                    raise ValidationError(
                        f"Product '{product.name}' has unsupported cost currency: {cost_currency.name}. Only USD and SL supported."
                    )

                # Commission requirements
                if (
                    product.is_sales_commissionable
                    and float(line.commission_amount or 0.0) > 0
                ):
                    if not product.sales_account_id:
                        raise ValidationError(
                            f"Product '{product.name}' has commission amount but no Sales Commission Account set."
                        )
                    if not product.sales_account_id.currency_id:
                        raise ValidationError(
                            f"Product '{product.name}' Sales Commission Account has no currency."
                        )

                    # monthly schedule requires payable account
                    if order.sales_person_id.commission_payment_schedule == "monthly":
                        if not order.sales_person_id.commission_payable_account_id:
                            raise ValidationError(
                                f"Salesperson '{order.sales_person_id.name}' has monthly schedule but no Commission Payable Account."
                            )
                        if (
                            not order.sales_person_id.commission_payable_account_id.currency_id
                        ):
                            raise ValidationError(
                                f"Salesperson '{order.sales_person_id.name}' Commission Payable Account has no currency."
                            )

                # Discount requirements
                if float(line.discount_amount or 0.0) > 0:
                    if not product.sales_discount_id:
                        raise ValidationError(
                            f"Product '{product.name}' has discount amount but no Sales Discount Account set."
                        )
                    if not product.sales_discount_id.currency_id:
                        raise ValidationError(
                            f"Product '{product.name}' Sales Discount Account has no currency."
                        )

    def _get_salesperson_credit_before_order(self):
        """
        Credit available BEFORE confirming this order.
        Credit exists when total IN > total OUT.
        """
        self.ensure_one()
        Txn = self.env["idil.salesperson.transaction"]

        txns = Txn.search([("sales_person_id", "=", self.sales_person_id.id)])

        total_out = sum(
            txns.filtered(lambda t: t.transaction_type == "out").mapped("amount")
        )
        total_in = sum(
            txns.filtered(lambda t: t.transaction_type == "in").mapped("amount")
        )

        credit = total_in - total_out
        return credit if credit > 0 else 0.0

    def _apply_previous_credit_to_receipt(self, credit_before):
        """
        Apply existing credit WITHOUT duplicating payments:
        - Move (allocate) credit from an older receipt to this receipt
        - Create 2 payment rows:
            * negative on source receipt
            * positive on this receipt
        """
        self.ensure_one()

        Receipt = self.env["idil.sales.receipt"]
        Payment = self.env["idil.sales.payment"]

        target_receipt = Receipt.search([("sales_order_id", "=", self.id)], limit=1)
        if not target_receipt:
            return 0.0

        # How much still needed on this receipt
        target_paid = sum((p.paid_amount or 0.0) for p in target_receipt.payment_ids)
        target_remaining = float(target_receipt.due_amount or 0.0) - float(target_paid)
        if target_remaining <= 0:
            return 0.0

        credit_before = float(credit_before or 0.0)
        if credit_before <= 0:
            return 0.0

        apply_amount = min(credit_before, target_remaining)
        if apply_amount <= 0:
            return 0.0

        # Find a SOURCE receipt that has credit: paid > due
        # (Pick the oldest/any one; you can refine later)
        source_receipts = Receipt.search(
            [
                ("salesperson_id", "=", self.sales_person_id.id),
                ("id", "!=", target_receipt.id),
            ],
            order="id asc",
        )

        allocation_left = apply_amount
        allocation_ref = f"ALLOC-{self.name}"

        for src in source_receipts:
            src_paid = sum((p.paid_amount or 0.0) for p in src.payment_ids)
            src_credit = float(src_paid) - float(src.due_amount or 0.0)
            if src_credit <= 0:
                continue

            take = min(src_credit, allocation_left)
            if take <= 0:
                continue

            # 1) NEGATIVE payment on SOURCE receipt (remove credit from there)
            Payment.create(
                {
                    "sales_receipt_id": src.id,
                    "payment_date": fields.Datetime.now(),
                    "paid_amount": -take,  # ✅ negative reduces src.paid_amount (computed)
                    "is_credit_allocation": True,
                    "allocation_ref": allocation_ref,
                }
            )

            # 2) POSITIVE payment on TARGET receipt (apply credit here)
            Payment.create(
                {
                    "sales_receipt_id": target_receipt.id,
                    "payment_date": fields.Datetime.now(),
                    "paid_amount": take,
                    "is_credit_allocation": True,
                    "allocation_ref": allocation_ref,
                }
            )

            allocation_left -= take
            if allocation_left <= 0:
                break

        applied = apply_amount - allocation_left
        return applied

    def book_accounting_entry(self):
        try:
            with self.env.cr.savepoint():
                # Step 1: validate once
                self._validate_before_posting()

                # Step 2: create booking + lines
                self._create_accounting_booking_and_lines()

        except Exception as e:
            _logger.error("transaction failed: %s", e)
            raise ValidationError(("Transaction failed: %s") % e)

    def _create_accounting_booking_and_lines(self):
        """
        Sales Order accounting posting (MO-style lines, explicit create() calls only)

        FX Rule (same as MO):
        - If DR/CR account currencies are the same => create 2 lines (DR, CR) in that currency
        - If different => create 4 lines using Exchange Clearing Account (2 clearing + 2 real)
        * amount_cr is in CR currency
        * amount_dr is converted to DR currency using order.rate

        Business rules:
        1) COST: DR COGS, CR Inventory (asset)
        2) SALES: DR Salesperson A/R, CR Revenue (GROSS = subtotal + commission + discount)
        3) COMMISSION:
            - monthly: DR commission expense / CR commission payable (A/P)
            - daily:   DR commission expense / CR Salesperson A/R (reduce AR)
        4) DISCOUNT: ALWAYS on-spot => DR discount expense / CR Salesperson A/R (reduce AR)
        5) Receipt due = (DR-CR) on A/R lines in this booking
        """
        try:
            with self.env.cr.savepoint():
                Booking = self.env["idil.transaction_booking"]
                BookingLine = self.env["idil.transaction_bookingline"]
                Chart = self.env["idil.chart.account"]
                Receipt = self.env["idil.sales.receipt"]

                trx_source = self.env["idil.transaction.source"].search(
                    [("name", "=", "Sales Order")], limit=1
                )
                if not trx_source:
                    raise ValidationError('Transaction source "Sales Order" not found.')

                # -------------------------
                # Helpers (small + readable)
                # -------------------------
                def _convert(amount, from_cur, to_cur, rate):
                    """1 USD = rate SL"""
                    amount = float(amount or 0.0)
                    if not from_cur or not to_cur or from_cur.id == to_cur.id:
                        return amount
                    r = float(rate or 0.0)
                    if r <= 0:
                        raise ValidationError(
                            "Exchange rate is required and must be > 0."
                        )
                    if from_cur.name == "SL" and to_cur.name == "USD":
                        return amount / r
                    if from_cur.name == "USD" and to_cur.name == "SL":
                        return amount * r
                    raise ValidationError(
                        f"Unsupported currency pair: {from_cur.name} -> {to_cur.name}"
                    )

                def _require_account_currency(acc, label):
                    if not acc:
                        raise ValidationError(f"Missing account: {label}")
                    if not acc.currency_id:
                        raise ValidationError(
                            f"Account '{acc.name}' must have currency ({label})."
                        )
                    return acc.currency_id

                def _get_clearing(currency_id):
                    acc = Chart.search(
                        [
                            ("name", "=", "Exchange Clearing Account"),
                            ("currency_id", "=", currency_id),
                        ],
                        limit=1,
                    )
                    if not acc:
                        cur = self.env["res.currency"].browse(currency_id)
                        raise ValidationError(
                            f"Exchange Clearing Account is required for currency: {cur.name}"
                        )
                    return acc

                def _post_lines_mo_style(
                    transaction_booking,
                    order,
                    product,
                    dr_acc,
                    cr_acc,
                    dr_amount,
                    cr_amount,
                    description_prefix,
                ):
                    """
                    EXACT MO line style.
                    amount_in_cr_currency is expressed in CR account currency.
                    """
                    amount_cr = float(cr_amount or 0.0)
                    amount_dr = float(dr_amount or 0.0)

                    dr_cur = _require_account_currency(
                        dr_acc, f"DR {description_prefix}"
                    )
                    cr_cur = _require_account_currency(
                        cr_acc, f"CR {description_prefix}"
                    )

                    trx_date = order.order_date
                    rate = float(order.rate or 0.0)

                    # Same currency => 2 lines
                    if dr_cur.id == cr_cur.id:
                        if amount_dr > 0:
                            BookingLine.create(
                                {
                                    "transaction_booking_id": transaction_booking.id,
                                    "description": f"{description_prefix} - Debit",
                                    "product_id": product.id if product else False,
                                    "sale_order_id": order.id,
                                    "account_number": dr_acc.id,
                                    "transaction_type": "dr",
                                    "dr_amount": float(amount_dr),
                                    "cr_amount": 0.0,
                                    "transaction_date": trx_date,
                                    "rate": rate,
                                }
                            )

                        if amount_cr > 0:
                            BookingLine.create(
                                {
                                    "transaction_booking_id": transaction_booking.id,
                                    "description": f"{description_prefix} - Credit",
                                    "product_id": product.id if product else False,
                                    "sale_order_id": order.id,
                                    "account_number": cr_acc.id,
                                    "transaction_type": "cr",
                                    "dr_amount": 0.0,
                                    "cr_amount": float(amount_cr),
                                    "transaction_date": trx_date,
                                    "rate": rate,
                                }
                            )
                        return

                    # Different currency => 4 lines (MO pattern)
                    amount_dr = _convert(amount_cr, cr_cur, dr_cur, rate)

                    source_clearing_account = _get_clearing(
                        cr_cur.id
                    )  # CR currency clearing (source)
                    target_clearing_account = _get_clearing(
                        dr_cur.id
                    )  # DR currency clearing (target)

                    # Debit real DR account (DR currency)
                    BookingLine.create(
                        {
                            "transaction_booking_id": transaction_booking.id,
                            "description": f"{description_prefix} - Debit",
                            "product_id": product.id if product else False,
                            "sale_order_id": order.id,
                            "account_number": dr_acc.id,
                            "transaction_type": "dr",
                            "dr_amount": float(amount_dr),
                            "cr_amount": 0.0,
                            "transaction_date": trx_date,
                            "rate": rate,
                        }
                    )

                    # Credit target clearing (DR currency)
                    BookingLine.create(
                        {
                            "transaction_booking_id": transaction_booking.id,
                            "description": f"{description_prefix} Exchange - Credit",
                            "product_id": product.id if product else False,
                            "sale_order_id": order.id,
                            "account_number": target_clearing_account.id,
                            "transaction_type": "cr",
                            "dr_amount": 0.0,
                            "cr_amount": float(amount_dr),
                            "transaction_date": trx_date,
                            "rate": rate,
                        }
                    )

                    # Debit source clearing (CR currency)
                    BookingLine.create(
                        {
                            "transaction_booking_id": transaction_booking.id,
                            "description": f"{description_prefix} Exchange - Debit",
                            "product_id": product.id if product else False,
                            "sale_order_id": order.id,
                            "account_number": source_clearing_account.id,
                            "transaction_type": "dr",
                            "dr_amount": float(amount_cr),
                            "cr_amount": 0.0,
                            "transaction_date": trx_date,
                            "rate": rate,
                        }
                    )

                    # Credit real CR account (CR currency)
                    BookingLine.create(
                        {
                            "transaction_booking_id": transaction_booking.id,
                            "description": f"{description_prefix} - Credit",
                            "product_id": product.id if product else False,
                            "sale_order_id": order.id,
                            "account_number": cr_acc.id,
                            "transaction_type": "cr",
                            "dr_amount": 0.0,
                            "cr_amount": float(amount_cr),
                            "transaction_date": trx_date,
                            "rate": rate,
                        }
                    )

                # -------------------------
                # Main loop
                # -------------------------
                for order in self:
                    rate = float(order.rate or 0.0)
                    if rate <= 0:
                        raise ValidationError(
                            "Exchange rate is required and must be > 0."
                        )

                    # Salesperson A/R
                    ar_acc = order.sales_person_id.account_receivable_id
                    if not ar_acc:
                        raise ValidationError("Salesperson A/R account is missing.")
                    _require_account_currency(ar_acc, "Salesperson A/R")

                    schedule = order.sales_person_id.commission_payment_schedule
                    ap_comm_acc = False
                    if schedule == "monthly":
                        ap_comm_acc = (
                            order.sales_person_id.commission_payable_account_id
                        )
                        if not ap_comm_acc:
                            raise ValidationError(
                                f"Salesperson '{order.sales_person_id.name}' monthly commission requires Commission Payable A/P account."
                            )
                        _require_account_currency(ap_comm_acc, "Commission Payable A/P")

                    # Booking header
                    booking = Booking.create(
                        {
                            "sales_person_id": order.sales_person_id.id,
                            "sale_order_id": order.id,
                            "trx_source_id": trx_source.id,
                            "Sales_order_number": order.id,
                            "payment_method": "bank_transfer",
                            "payment_status": "pending",
                            "trx_date": order.order_date,
                            "amount": order.order_total,
                            "rate": rate,
                        }
                    )

                    # Optional summary update
                    self.env[
                        "idil.salesperson.order.summary"
                    ].update_summary_from_order(order)

                    for ln in order.order_lines:
                        product = ln.product_id
                        if not product:
                            continue

                        # Accounts
                        asset_acc = product.asset_account_id
                        cogs_acc = product.account_cogs_id
                        income_acc = product.income_account_id

                        if not asset_acc:
                            raise ValidationError(
                                f"Product '{product.display_name}' Asset Account is missing."
                            )
                        if not cogs_acc:
                            raise ValidationError(
                                f"Product '{product.display_name}' COGS Account is missing."
                            )
                        if not income_acc:
                            raise ValidationError(
                                f"Product '{product.display_name}' Income Account is missing."
                            )

                        asset_cur = _require_account_currency(
                            asset_acc, f"Asset account for {product.display_name}"
                        )
                        _require_account_currency(
                            cogs_acc, f"COGS account for {product.display_name}"
                        )
                        income_cur = _require_account_currency(
                            income_acc, f"Income account for {product.display_name}"
                        )

                        # -------------------------
                        # 1) COST: DR COGS, CR Inventory
                        # Amount in CR currency = asset currency
                        # -------------------------
                        bom_cur = (
                            product.bom_id.currency_id
                            if getattr(product, "bom_id", False) and product.bom_id
                            else getattr(product, "currency_id", False)
                        ) or asset_cur

                        qty = float(ln.quantity or 0.0)
                        cost_in_bom = float(product.cost or 0.0) * qty
                        cost_in_asset = _convert(cost_in_bom, bom_cur, asset_cur, rate)

                        _post_lines_mo_style(
                            transaction_booking=booking,
                            order=order,
                            product=product,
                            dr_acc=cogs_acc,
                            cr_acc=asset_acc,
                            cr_amount=cost_in_asset,
                            dr_amount=cost_in_asset,
                            description_prefix=f"COGS/Inventory - {product.name}",
                        )

                        # -------------------------
                        # 2) SALES: DR A/R, CR Revenue (GROSS)
                        # Amount in CR currency = income currency
                        # -------------------------
                        gross_sales_asset = float(ln.subtotal or 0.0)
                        gross_sales_income = _convert(
                            gross_sales_asset, asset_cur, income_cur, rate
                        )

                        disc_amt_asset1 = float(ln.discount_amount or 0.0)
                        disc_in_ar1 = _convert(
                            disc_amt_asset1, asset_cur, ar_acc.currency_id, rate
                        )

                        _post_lines_mo_style(
                            transaction_booking=booking,
                            order=order,
                            product=product,
                            dr_acc=ar_acc,
                            cr_acc=income_acc,
                            cr_amount=gross_sales_income + disc_in_ar1,
                            dr_amount=gross_sales_income,
                            description_prefix=f"Sales - {product.name}",
                        )

                        # -------------------------
                        # 3) COMMISSION
                        # - monthly: DR expense / CR payable
                        # - daily:   DR expense / CR A/R (reduce A/R)
                        # -------------------------
                        comm_amt_asset = float(ln.commission_amount or 0.0)
                        if product.is_sales_commissionable and comm_amt_asset > 0:
                            comm_exp_acc = product.sales_account_id
                            _require_account_currency(
                                comm_exp_acc,
                                f"Commission expense for {product.display_name}",
                            )

                            if schedule == "monthly":
                                comm_pay_amt = _convert(
                                    comm_amt_asset,
                                    asset_cur,
                                    ap_comm_acc.currency_id,
                                    rate,
                                )

                                _post_lines_mo_style(
                                    transaction_booking=booking,
                                    order=order,
                                    product=product,
                                    dr_acc=comm_exp_acc,
                                    cr_acc=ap_comm_acc,
                                    cr_amount=comm_pay_amt,
                                    dr_amount=comm_pay_amt,
                                    description_prefix=f"Commission (Monthly) - {product.name}",
                                )
                            else:
                                comm_in_ar = _convert(
                                    comm_amt_asset, asset_cur, ar_acc.currency_id, rate
                                )

                                _post_lines_mo_style(
                                    transaction_booking=booking,
                                    order=order,
                                    product=product,
                                    dr_acc=comm_exp_acc,
                                    cr_acc=ar_acc,
                                    cr_amount=comm_in_ar,
                                    dr_amount=comm_in_ar,
                                    description_prefix=f"Commission (Daily Reduce AR) - {product.name}",
                                )

                        # -------------------------
                        # 4) DISCOUNT (ALWAYS ON SPOT): DR discount expense / CR A/R (reduce A/R)
                        # -------------------------
                        disc_amt_asset = float(ln.discount_amount or 0.0)
                        if disc_amt_asset > 0:
                            disc_acc = product.sales_discount_id
                            _require_account_currency(
                                disc_acc, f"Discount expense for {product.display_name}"
                            )

                            disc_in_ar = _convert(
                                disc_amt_asset, asset_cur, ar_acc.currency_id, rate
                            )

                            _post_lines_mo_style(
                                transaction_booking=booking,
                                order=order,
                                product=product,
                                dr_acc=disc_acc,
                                cr_acc=ar_acc,
                                cr_amount=0,
                                dr_amount=disc_in_ar,
                                description_prefix=f"Discount (On Spot Reduce AR) - {product.name}",
                            )

                    # ------------------------------
                    # Receipt = A/R due for this booking
                    # ------------------------------
                    if not Receipt.search([("sales_order_id", "=", order.id)], limit=1):
                        ar_lines = booking.booking_lines.filtered(
                            lambda l: l.account_number.id == ar_acc.id
                        )
                        ar_due = sum(ar_lines.mapped("dr_amount")) - sum(
                            ar_lines.mapped("cr_amount")
                        )

                        vals = {
                            "sales_order_id": order.id,
                            "salesperson_id": order.sales_person_id.id,
                            "receipt_date": order.order_date,
                            "due_amount": ar_due,
                            "currency_id": ar_acc.currency_id.id,
                        }
                        if "rate" in Receipt._fields:
                            vals["rate"] = rate

                        Receipt.create(vals)

        except Exception as e:
            _logger.error("transaction failed: %s", e)
            raise ValidationError(("Transaction failed: %s") % e)

    def write(self, vals):
        Receipt = self.env["idil.sales.receipt"]

        for order in self:
            # 🚫 If order is already confirmed, block ALL edits except state change
            if order.state == "confirmed":
                # Allow ONLY state change (e.g. cancel)
                if set(vals.keys()) - {"state"}:
                    # Extra safety: block if any payment exists
                    paid_receipts = Receipt.search(
                        [("sales_order_id", "=", order.id)]
                    ).filtered(lambda r: float(r.paid_amount or 0.0) > 0)

                    if paid_receipts:
                        raise UserError(
                            _("Cannot modify a confirmed Sales Order with payments.")
                        )

                    raise UserError(
                        _("You cannot modify a Sales Order once it is confirmed.")
                    )

        # ✅ Normal write for draft orders or pure state update
        return super(SaleOrder, self).write(vals)

    def unlink(self):
        try:
            with self.env.cr.savepoint():
                order_ids = self.ids
                for order in self:
                    receipts = self.env["idil.sales.receipt"].search(
                        [("sales_order_id", "=", order.id)]
                    )
                    receipts_with_payment = receipts.filtered(
                        lambda r: r.paid_amount > 0
                    )
                    if receipts_with_payment:
                        receipt_details = "\n".join(
                            [
                                f"- Receipt Date: {format_datetime(self.env, r.receipt_date)}, "
                                f"Amount Paid: {r.paid_amount:.2f}, Due: {r.due_amount:.2f}, Remaining: {r.remaining_amount:.2f}"
                                for r in receipts_with_payment
                            ]
                        )
                        raise UserError(
                            (
                                "Cannot Delete this Sales Order because it has Receipts with payment:\n%s"
                            )
                            % receipt_details
                        )

                    returns = self.env["idil.sale.return"].search(
                        [("sale_order_id", "=", order.id)]
                    )
                    if returns:
                        return_details = "\n".join(
                            [
                                f"- Return Date: {format_datetime(self.env, r.return_date)}, State: {r.state}"
                                for r in returns
                            ]
                        )
                        raise UserError(
                            (
                                "Cannot Delete this Sales Order because it has linked Sale Returns:\n%s"
                            )
                            % return_details
                        )
                res = super(SaleOrder, self).unlink()

                return res
        except Exception as e:
            _logger.error("Create transaction failed: %s", e)
            raise ValidationError(("Transaction failed: %s") % e)


class SaleOrderLine(models.Model):
    _name = "idil.sale.order.line"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _description = "Sale Order Line"
    _sql_constraints = [
        ("qty_positive", "CHECK(quantity > 0)", "Quantity must be positive."),
    ]

    company_id = fields.Many2one(related="order_id.company_id", store=True, index=True)
    # 🔧 NEW: give Monetary fields a currency on the line
    currency_id = fields.Many2one(
        "res.currency",
        related="product_id.asset_account_id.currency_id",
        store=True,
        readonly=True,
        string="Currency",
    )
    order_id = fields.Many2one(
        "idil.sale.order", required=True, ondelete="cascade", index=True
    )

    product_id = fields.Many2one("my_product.product", string="Product")
    quantity_Demand = fields.Float(string="Demand", default=1.0)
    quantity = fields.Float(string="QTY Used", required=True, tracking=True)
    quantity_diff = fields.Float(
        string="QTY Diff", compute="_compute_quantity_diff", store=True
    )

    price_unit = fields.Float(
        string="Unit Price",
        default=lambda self: self.product_id.sale_price if self.product_id else 0.0,
    )
    commission = fields.Float(
        string="Commission %",
        store=True,
        default=lambda self: self.product_id.commission if self.product_id else 0.0,
    )
    subtotal = fields.Monetary(
        currency_field="currency_id", compute="_compute_subtotal"
    )
    discount_amount = fields.Monetary(
        currency_field="currency_id", compute="_compute_discount_amount", store=True
    )

    commission_amount = fields.Monetary(
        currency_field="currency_id",
        string="Commission Amount",
        compute="_compute_commission_amount",
        inverse="_set_commission_amount",
        store=True,
    )

    discount_quantity = fields.Float(
        string="Discount Quantity", compute="_compute_discount_quantity", store=True
    )
    returned_quantity = fields.Float(
        string="Returned Quantity",
        compute="_compute_returned_quantity",
        store=False,
        readonly=True,
    )
    # idil.sale.order

    base_currency_id = fields.Many2one(
        "res.currency",
        string="Base Currency",
        default=lambda self: self.env.ref("base.USD"),
        readonly=True,
    )

    fy_currency_id = fields.Many2one(
        "res.currency",
        string="FY Currency",
        default=lambda self: self.env["res.currency"].search(
            [("name", "=", "SL")], limit=1
        ),
        readonly=True,
    )

    subtotal_usd = fields.Monetary(
        string="Subtotal (USD)",
        currency_field="base_currency_id",
        compute="_compute_line_totals_multi_currency",
        store=True,
    )

    subtotal_fy = fields.Monetary(
        string="Subtotal (FY)",
        currency_field="fy_currency_id",
        compute="_compute_line_totals_multi_currency",
        store=True,
    )

    @api.depends("quantity", "price_unit", "currency_id", "order_id.rate")
    def _compute_line_totals_multi_currency(self):
        for line in self:
            quantity = line.quantity or 0.0
            price = line.price_unit or 0.0
            rate = float(line.order_id.rate or 0.0)

            # Base subtotal
            subtotal = quantity * price
            line.subtotal = subtotal

            currency = line.currency_id.name if line.currency_id else "SL"

            if currency == "USD":
                # Subtotal is USD
                line.subtotal_usd = subtotal
                line.subtotal_fy = subtotal * rate if rate else 0.0

            else:
                # Treat everything else as SL
                line.subtotal_fy = subtotal
                line.subtotal_usd = subtotal / rate if rate else 0.0

    @api.depends("order_id", "product_id")
    def _compute_returned_quantity(self):
        for line in self:
            if line.order_id and line.product_id:
                return_lines = self.env["idil.sale.return.line"].search(
                    [
                        ("return_id.sale_order_id", "=", line.order_id.id),
                        ("product_id", "=", line.product_id.id),
                        ("return_id.state", "=", "confirmed"),
                    ]
                )
                line.returned_quantity = sum(return_lines.mapped("returned_quantity"))
            else:
                line.returned_quantity = 0.0

    @api.depends("quantity", "product_id.commission", "price_unit", "commission")
    def _compute_commission_amount(self):
        for line in self:
            product = line.product_id
            if product.is_sales_commissionable:
                if not product.sales_account_id:
                    raise ValidationError(
                        ("Product '%s' does not have a Sales Commission Account set.")
                        % product.name
                    )
                if product.commission <= 0:
                    raise ValidationError(
                        ("Product '%s' does not have a valid Commission Rate set.")
                        % product.name
                    )

                line.commission_amount = (
                    (line.quantity - line.discount_quantity)
                    * line.commission
                    * line.price_unit
                )
            else:
                line.commission_amount = 0.0

    def _set_commission_amount(self):
        for line in self:
            pass

    @api.depends(
        "quantity",
        "price_unit",
        "commission_amount",
        "order_id.sales_person_id.commission_payment_schedule",
    )
    def _compute_subtotal(self):
        for line in self:
            # Base amount before commission
            base_amount = (line.quantity * line.price_unit) - (
                line.discount_quantity * line.price_unit
            )

            # Only subtract commission if it's paid immediately (daily schedule)
            # For monthly/deferred commissions, salesperson must remit the full amount
            if line.order_id and line.order_id.sales_person_id:
                schedule = line.order_id.sales_person_id.commission_payment_schedule
                if schedule == "daily":
                    # Immediate payment: salesperson keeps commission from the sale
                    line.subtotal = base_amount
                else:
                    # Deferred payment: salesperson must remit full amount
                    line.subtotal = base_amount

    @api.depends("quantity")
    def _compute_discount_quantity(self):
        for line in self:
            line.discount_quantity = (
                (line.product_id.discount / 100) * (line.quantity)
                if line.product_id.is_quantity_discount
                else 0.0
            )

    @api.depends("discount_quantity", "price_unit")
    def _compute_discount_amount(self):
        for line in self:
            line.discount_amount = line.discount_quantity * line.price_unit

    @api.depends("quantity_Demand", "quantity")
    def _compute_quantity_diff(self):
        for record in self:
            record.quantity_diff = record.quantity_Demand - record.quantity

    @api.model
    def create(self, vals):
        try:
            with self.env.cr.savepoint():
                return super(SaleOrderLine, self).create(vals)
        except Exception as e:
            _logger.error("Create transaction failed: %s", e)
            raise ValidationError(("Transaction failed: %s") % e)

    def write(self, vals):
        try:
            with self.env.cr.savepoint():
                for line in self:
                    order = line.order_id
                    product = line.product_id
                    old_qty = line.quantity
                    new_qty = vals.get("quantity", old_qty)

                    if new_qty < old_qty:
                        confirmed_returns = self.env["idil.sale.return.line"].search(
                            [
                                ("return_id.sale_order_id", "=", order.id),
                                ("product_id", "=", product.id),
                                ("return_id.state", "=", "confirmed"),
                            ]
                        )
                        total_returned = sum(
                            confirmed_returns.mapped("returned_quantity")
                        )

                        if new_qty < total_returned:
                            raise ValidationError(
                                (
                                    "You cannot reduce quantity of '%(p)s' to %(n).2f because %(r).2f has already been returned."
                                )
                                % {"p": product.name, "n": new_qty, "r": total_returned}
                            )

                    if "quantity" in vals:
                        quantity_diff = vals["quantity"] - line.quantity
                        self.update_product_stock(line.product_id, quantity_diff)

                res = super(SaleOrderLine, self).write(vals)

                for line in self:
                    order = line.order_id

                    self.env["idil.salesperson.transaction"].search(
                        [("order_id", "=", order.id), ("sale_return_id", "=", False)]
                    ).unlink()

                    for updated_line in order.order_lines:
                        self.env["idil.salesperson.transaction"].create(
                            {
                                "sales_person_id": order.sales_person_id.id,
                                "date": fields.Date.today(),
                                "order_id": order.id,
                                "transaction_type": "out",
                                "amount": updated_line.subtotal
                                + updated_line.discount_amount
                                + updated_line.commission_amount,
                                "description": f"Sales Amount of - Order Line for {updated_line.product_id.name} (Qty: {updated_line.quantity})",
                            }
                        )

                        # Commission and Discount are now deferred and handled by idil.sales.commission and idil.sales.discount
                        # We do NOT post them to transactions here anymore.
                        # However, we might need to update the deferred records if the amount changes.
                        # For now, we just stop the immediate posting to fix the bug.
                        pass

                return res
        except Exception as e:
            _logger.error("Create transaction failed: %s", e)
            raise ValidationError(("Transaction failed: %s") % e)

    @staticmethod
    def update_product_stock(product, quantity_diff):
        new_stock_quantity = product.stock_quantity - quantity_diff
        if new_stock_quantity < 0:
            raise ValidationError(
                (
                    "Insufficient stock for product '%(p)s'. The available stock quantity is %(a).2f, "
                    "but the required quantity is %(r).2f."
                )
                % {
                    "p": product.name,
                    "a": product.stock_quantity,
                    "r": abs(quantity_diff),
                }
            )
        # product.stock_quantity = new_stock_quantity
