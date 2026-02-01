from odoo import models, fields, api
from odoo.exceptions import UserError, ValidationError
import logging


import logging

_logger = logging.getLogger(__name__)


class SaleReturn(models.Model):
    _name = "idil.sale.return"
    _description = "Sale Return"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "id desc"

    company_id = fields.Many2one(
        "res.company", default=lambda s: s.env.company, required=True
    )

    name = fields.Char(
        string="Reference", default="New", readonly=True, copy=False, tracking=True
    )
    salesperson_id = fields.Many2one(
        "idil.sales.sales_personnel", string="Salesperson", required=True, tracking=True
    )
    sale_order_id = fields.Many2one(
        "idil.sale.order",
        string="Sale Order",
        required=True,
        domain="[('sales_person_id', '=', salesperson_id)]",
        help="Select a sales order related to the chosen salesperson.",
        tracking=True,
    )
    return_date = fields.Datetime(
        string="Return Date", default=fields.Datetime.now, required=True, tracking=True
    )
    return_lines = fields.One2many(
        "idil.sale.return.line", "return_id", string="Return Lines", required=True
    )
    state = fields.Selection(
        [("draft", "Draft"), ("confirmed", "Confirmed"), ("cancelled", "Cancelled")],
        default="draft",
        string="Status",
        track_visibility="onchange",
        tracking=True,
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
        tracking=True,
    )
    rate = fields.Float(
        string="Exchange Rate",
        compute="_compute_exchange_rate",
        store=True,
        readonly=True,
        tracking=True,
    )
    total_returned_qty = fields.Float(
        string="Total Returned Quantity",
        compute="_compute_totals",
        store=False,
        tracking=True,
    )

    total_subtotal = fields.Float(
        string="Total Amount",
        compute="_compute_totals",
        store=False,
        tracking=True,
    )
    total_discount_amount = fields.Float(
        string="Total Discount Amount",
        compute="_compute_totals",
        store=False,
        tracking=True,
    )

    total_commission_amount = fields.Float(
        string="Total Commission Amount",
        compute="_compute_totals",
        store=False,
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
        "sale_return_id",
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

            total_dr = sum(v["dr"] for v in grouped.values())
            total_cr = sum(v["cr"] for v in grouped.values())
            balanced = abs(total_dr - total_cr) < 0.00001

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
            # ✅ booking linked by sale_return_id
            b = Booking.search(
                [("sale_return_id", "=", o.id)], order="id desc", limit=1
            )
            o.booking_id = b

            if b:
                dr = float(getattr(b, "debit_total", 0.0) or 0.0)
                cr = float(getattr(b, "credit_total", 0.0) or 0.0)
            else:
                dr = sum(o.booking_line_ids.mapped("dr_amount")) or 0.0
                cr = sum(o.booking_line_ids.mapped("cr_amount")) or 0.0

            o.journal_total_dr = dr
            o.journal_total_cr = cr
            o.journal_is_balanced = abs(dr - cr) < 0.00001

    @api.depends("currency_id", "return_date", "company_id")
    def _compute_exchange_rate(self):
        Rate = self.env["res.currency.rate"].sudo()
        for order in self:
            order.rate = 0.0
            if not order.currency_id:
                continue

            doc_date = (
                fields.Date.to_date(order.return_date)
                if order.return_date
                else fields.Date.today()
            )

            # Get latest rate on or before the doc_date, preferring the order's company, then global (company_id False)

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
        "return_lines.returned_quantity",
        "return_lines.price_unit",
        "return_lines.product_id.discount",
        "return_lines.product_id.commission",
        "return_lines.product_id.is_quantity_discount",
    )
    def _compute_totals(self):
        for rec in self:
            total_qty = 0.0
            total_subtotal = 0.0
            total_discount = 0.0
            total_commission = 0.0

            _logger.debug(
                "Computing totals for return %s with %s lines",
                rec.name,
                len(rec.return_lines),
            )

            for line in rec.return_lines:
                qty = line.returned_quantity
                price = line.price_unit
                product = line.product_id

                _logger.debug(
                    "Line product: %s | qty: %s | price: %s",
                    product.name if product else None,
                    qty,
                    price,
                )

                if not product or qty <= 0:
                    continue

                discount_qty = (
                    (product.discount / 100.0) * qty
                    if product.is_quantity_discount
                    else 0.0
                )
                discount_amount = discount_qty * price

                commission_base_qty = qty - discount_qty
                commission_amount = commission_base_qty * product.commission * price

                subtotal = qty * price

                total_qty += qty
                total_subtotal += subtotal
                total_discount += discount_amount
                total_commission += commission_amount

            rec.total_returned_qty = total_qty
            rec.total_subtotal = total_subtotal
            rec.total_discount_amount = total_discount
            rec.total_commission_amount = total_commission

    @api.onchange("sale_order_id")
    def _onchange_sale_order_id(self):
        if not self.sale_order_id:
            return
        sale_order = self.sale_order_id
        return_lines = [(5, 0, 0)]  # Clear existing lines

        for line in sale_order.order_lines:
            return_lines.append(
                (
                    0,
                    0,
                    {
                        "product_id": line.product_id.id,
                        "quantity": line.quantity,  # Ensure this is being set
                        "returned_quantity": 0.0,
                        "price_unit": line.price_unit,
                        "subtotal": line.subtotal,
                    },
                )
            )

        self.return_lines = return_lines

    def action_confirm(self):
        try:
            with self.env.cr.savepoint():
                for return_order in self:
                    if return_order.state != "draft":
                        raise UserError("Only draft return orders can be confirmed.")

                    # Step A: validate quantities (your existing logic)
                    return_order._validate_return_quantities()

                    # Step B: post all return effects
                    return_order.book_sales_return_entry()

                    # Step C: chatter + state
                    returned_lines = return_order.return_lines.filtered(
                        lambda l: l.returned_quantity > 0
                    )
                    total = sum(returned_lines.mapped("subtotal"))
                    return_order.message_post(
                        body=f"✅ Sales Return confirmed with {len(returned_lines)} returned items. "
                        f"Total: {return_order.currency_id.symbol or ''}{total:,.2f}"
                    )
                    return_order.write({"state": "confirmed"})
            return True
        except Exception as e:
            _logger.error("transaction failed: %s", e)
            raise ValidationError(f"Transaction failed: {str(e)}")

    def _validate_return_quantities(self):
        self.ensure_one()

        for return_line in self.return_lines:
            corresponding_sale_line = self.env["idil.sale.order.line"].search(
                [
                    ("order_id", "=", self.sale_order_id.id),
                    ("product_id", "=", return_line.product_id.id),
                ],
                limit=1,
            )
            if not corresponding_sale_line:
                raise ValidationError(
                    f"Sale line not found for product {return_line.product_id.name}."
                )

            previous_returns = self.env["idil.sale.return.line"].search(
                [
                    ("return_id.sale_order_id", "=", self.sale_order_id.id),
                    ("product_id", "=", return_line.product_id.id),
                    ("return_id", "!=", self.id),
                    ("return_id.state", "=", "confirmed"),
                ]
            )
            total_prev_returned = sum(r.returned_quantity for r in previous_returns)
            new_total = total_prev_returned + return_line.returned_quantity

            if new_total > corresponding_sale_line.quantity:
                available_to_return = (
                    corresponding_sale_line.quantity - total_prev_returned
                )
                raise ValidationError(
                    f"Cannot return {return_line.returned_quantity:.2f} of {return_line.product_id.name}.\n\n"
                    f"✅ Already Returned: {total_prev_returned:.2f}\n"
                    f"✅ Available for Return: {available_to_return:.2f}\n"
                    f"🧾 Original Sold Quantity: {corresponding_sale_line.quantity:.2f}"
                )

    def book_sales_return_entry(self):
        for return_order in self:
            ctx = return_order._sr_build_ctx()
            ctx["booking"] = return_order._sr_create_booking(ctx)

            for rl in return_order.return_lines:
                if rl.returned_quantity <= 0:
                    continue
                return_order._sr_post_line_accounting(ctx, rl)
                return_order._sr_post_line_salesperson_txn(ctx, rl)
                return_order._sr_post_line_movement(ctx, rl)

            return_order._sr_update_receipt(ctx)
            # ✅ ADD THIS:
            return_order._sr_update_commission_record(ctx)

    def _sr_build_ctx(self):
        self.ensure_one()

        salesperson = self.salesperson_id
        if not salesperson or not salesperson.account_receivable_id:
            raise ValidationError(
                "The salesperson does not have a receivable account set."
            )

        ar_acc = salesperson.account_receivable_id
        if not ar_acc.currency_id:
            raise ValidationError("Salesperson A/R account must have currency.")

        schedule = salesperson.commission_payment_schedule  # 'monthly' or 'daily'
        rate = float(self.rate or 0.0)
        if rate <= 0:
            raise ValidationError("Exchange rate is required and must be > 0.")

        trx_source = self.env["idil.transaction.source"].search(
            [("name", "=", "Sales Return")], limit=1
        )
        if not trx_source:
            raise UserError("Transaction source 'Sales Return' not found.")

        return {
            "order": self,
            "salesperson": salesperson,
            "ar_acc": ar_acc,
            "schedule": schedule,
            "rate": rate,
            "trx_source": trx_source,
            "Chart": self.env["idil.chart.account"],
            "Booking": self.env["idil.transaction_booking"],
            "BookingLine": self.env["idil.transaction_bookingline"],
            "SpTxn": self.env["idil.salesperson.transaction"],
            "Receipt": self.env["idil.sales.receipt"],
        }

    def _sr_convert(self, amount, from_cur, to_cur, rate):
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

    def _sr_require_currency(self, acc, label):
        if not acc:
            raise ValidationError(f"Missing account: {label}")
        if not acc.currency_id:
            raise ValidationError(f"Account '{acc.name}' must have currency ({label}).")
        return acc.currency_id

    def _sr_get_clearing(self, Chart, currency_id):
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

    def _sr_post_mo_pair(
        self, ctx, dr_acc, cr_acc, amount_in_cr_cur, desc, product=False
    ):
        BookingLine = ctx["BookingLine"]
        Chart = ctx["Chart"]
        rate = ctx["rate"]
        order = ctx["order"]
        booking = ctx["booking"]

        amount_cr = float(amount_in_cr_cur or 0.0)
        if amount_cr == 0.0:
            return

        dr_cur = self._sr_require_currency(dr_acc, f"DR {desc}")
        cr_cur = self._sr_require_currency(cr_acc, f"CR {desc}")
        trx_date = order.return_date or fields.Datetime.now()

        if dr_cur.id == cr_cur.id:
            BookingLine.create(
                {
                    "transaction_booking_id": booking.id,
                    "sale_return_id": order.id,
                    "sale_order_id": order.sale_order_id.id,
                    "description": f"{desc} - Debit",
                    "product_id": product.id if product else False,
                    "account_number": dr_acc.id,
                    "transaction_type": "dr",
                    "dr_amount": amount_cr,
                    "cr_amount": 0.0,
                    "transaction_date": trx_date,
                }
            )
            BookingLine.create(
                {
                    "transaction_booking_id": booking.id,
                    "sale_return_id": order.id,
                    "sale_order_id": order.sale_order_id.id,
                    "description": f"{desc} - Credit",
                    "product_id": product.id if product else False,
                    "account_number": cr_acc.id,
                    "transaction_type": "cr",
                    "dr_amount": 0.0,
                    "cr_amount": amount_cr,
                    "transaction_date": trx_date,
                }
            )
            return

        amount_dr = self._sr_convert(amount_cr, cr_cur, dr_cur, rate)
        source_clearing = self._sr_get_clearing(Chart, cr_cur.id)
        target_clearing = self._sr_get_clearing(Chart, dr_cur.id)

        BookingLine.create(
            {
                "transaction_booking_id": booking.id,
                "sale_return_id": order.id,
                "sale_order_id": order.sale_order_id.id,
                "description": f"{desc} - Debit",
                "product_id": product.id if product else False,
                "account_number": dr_acc.id,
                "transaction_type": "dr",
                "dr_amount": amount_dr,
                "cr_amount": 0.0,
                "transaction_date": trx_date,
            }
        )
        BookingLine.create(
            {
                "transaction_booking_id": booking.id,
                "sale_return_id": order.id,
                "sale_order_id": order.sale_order_id.id,
                "description": f"{desc} Exchange - Credit",
                "product_id": product.id if product else False,
                "account_number": target_clearing.id,
                "transaction_type": "cr",
                "dr_amount": 0.0,
                "cr_amount": amount_dr,
                "transaction_date": trx_date,
            }
        )
        BookingLine.create(
            {
                "transaction_booking_id": booking.id,
                "sale_return_id": order.id,
                "sale_order_id": order.sale_order_id.id,
                "description": f"{desc} Exchange - Debit",
                "product_id": product.id if product else False,
                "account_number": source_clearing.id,
                "transaction_type": "dr",
                "dr_amount": amount_cr,
                "cr_amount": 0.0,
                "transaction_date": trx_date,
            }
        )
        BookingLine.create(
            {
                "transaction_booking_id": booking.id,
                "sale_return_id": order.id,
                "sale_order_id": order.sale_order_id.id,
                "description": f"{desc} - Credit",
                "product_id": product.id if product else False,
                "account_number": cr_acc.id,
                "transaction_type": "cr",
                "dr_amount": 0.0,
                "cr_amount": amount_cr,
                "transaction_date": trx_date,
            }
        )

    def _sr_create_booking(self, ctx):
        Booking = ctx["Booking"]
        order = ctx["order"]
        salesperson = ctx["salesperson"]
        trx_source = ctx["trx_source"]

        booking_amount = sum(
            (ln.subtotal or 0.0)
            for ln in order.return_lines
            if ln.returned_quantity > 0
        )

        return Booking.create(
            {
                "sales_person_id": salesperson.id,
                "sale_return_id": order.id,
                "sale_order_id": order.sale_order_id.id,
                "trx_source_id": trx_source.id,
                "Sales_order_number": order.sale_order_id.id,
                "rate": ctx["rate"],
                "payment_method": "bank_transfer",
                "payment_status": "pending",
                "trx_date": fields.Date.context_today(self),
                "amount": booking_amount,
            }
        )

    def _sr_post_line_accounting(self, ctx, rl):
        order = ctx["order"]
        ar_acc = ctx["ar_acc"]
        schedule = ctx["schedule"]
        rate = ctx["rate"]

        product = rl.product_id
        asset_acc = product.asset_account_id
        cogs_acc = product.account_cogs_id
        income_acc = product.income_account_id

        asset_cur = self._sr_require_currency(
            asset_acc, f"Asset for {product.display_name}"
        )
        self._sr_require_currency(cogs_acc, f"COGS for {product.display_name}")
        income_cur = self._sr_require_currency(
            income_acc, f"Income for {product.display_name}"
        )

        qty = float(rl.returned_quantity or 0.0)
        price = float(rl.price_unit or 0.0)

        discount_qty = (
            (product.discount / 100.0) * qty if product.is_quantity_discount else 0.0
        )
        discount_amt_asset = float(discount_qty * price)

        commission_amt_asset = 0.0
        if product.is_sales_commissionable and float(product.commission or 0.0) > 0:
            commission_amt_asset = float(
                (qty - discount_qty) * product.commission * price
            )

        gross_asset = float(qty * price)

        # monthly sales accounting included commission in AR/Revenue posting
        gross_for_ar_asset = gross_asset

        # cost reverse
        bom_cur = (
            product.bom_id.currency_id
            if product.bom_id
            else getattr(product, "currency_id", False)
        ) or asset_cur
        cost_in_asset = self._sr_convert(
            float(product.cost or 0.0) * qty, bom_cur, asset_cur, rate
        )

        # A) Inventory/COGS reverse
        self._sr_post_mo_pair(
            ctx,
            asset_acc,
            cogs_acc,
            cost_in_asset,
            f"Return Inventory/COGS - {product.name}",
            product,
        )

        # B) Revenue/AR reverse
        gross_for_ar_income = self._sr_convert(
            gross_for_ar_asset, asset_cur, income_cur, rate
        )
        gross_for_ar_in_arcur = (
            self._sr_convert(gross_for_ar_income, income_cur, ar_acc.currency_id, rate)
            if income_cur.id != ar_acc.currency_id.id
            else gross_for_ar_income
        )

        self._sr_post_mo_pair(
            ctx,
            income_acc,
            ar_acc,
            gross_for_ar_in_arcur,
            f"Return Sales (Revenue/AR) - {product.name}",
            product,
        )

        # C) Discount reversal
        if discount_amt_asset > 0:
            disc_acc = product.sales_discount_id
            self._sr_require_currency(disc_acc, f"Discount for {product.display_name}")

            disc_in_ar = self._sr_convert(
                discount_amt_asset, asset_cur, ar_acc.currency_id, rate
            )
            disc_in_disc = (
                self._sr_convert(
                    disc_in_ar, ar_acc.currency_id, disc_acc.currency_id, rate
                )
                if ar_acc.currency_id.id != disc_acc.currency_id.id
                else disc_in_ar
            )

            self._sr_post_mo_pair(
                ctx,
                ar_acc,
                disc_acc,
                disc_in_disc,
                f"Return Discount (reverse) - {product.name}",
                product,
            )

        # D) Commission reversal
        if commission_amt_asset > 0:
            comm_exp_acc = product.sales_account_id
            self._sr_require_currency(
                comm_exp_acc, f"Commission expense for {product.display_name}"
            )

            if schedule == "monthly":
                ap_comm_acc = ctx["salesperson"].commission_payable_account_id
                self._sr_require_currency(
                    ap_comm_acc, f"Commission payable for {ctx['salesperson'].name}"
                )

                comm_in_ap = self._sr_convert(
                    commission_amt_asset, asset_cur, ap_comm_acc.currency_id, rate
                )
                comm_in_exp = (
                    self._sr_convert(
                        comm_in_ap,
                        ap_comm_acc.currency_id,
                        comm_exp_acc.currency_id,
                        rate,
                    )
                    if ap_comm_acc.currency_id.id != comm_exp_acc.currency_id.id
                    else comm_in_ap
                )

                self._sr_post_mo_pair(
                    ctx,
                    ap_comm_acc,
                    comm_exp_acc,
                    comm_in_exp,
                    f"Return Commission (Monthly reverse) - {product.name}",
                    product,
                )
            else:
                comm_in_ar = self._sr_convert(
                    commission_amt_asset, asset_cur, ar_acc.currency_id, rate
                )
                comm_in_exp = (
                    self._sr_convert(
                        comm_in_ar, ar_acc.currency_id, comm_exp_acc.currency_id, rate
                    )
                    if ar_acc.currency_id.id != comm_exp_acc.currency_id.id
                    else comm_in_ar
                )

                self._sr_post_mo_pair(
                    ctx,
                    ar_acc,
                    comm_exp_acc,
                    comm_in_exp,
                    f"Return Commission (Daily reverse) - {product.name}",
                    product,
                )

    def _sr_post_line_salesperson_txn(self, ctx, rl):
        order = ctx["order"]
        salesperson = ctx["salesperson"]
        ar_acc = ctx["ar_acc"]
        schedule = ctx["schedule"]
        rate = ctx["rate"]
        SpTxn = ctx["SpTxn"]

        product = rl.product_id
        asset_cur = product.asset_account_id.currency_id

        qty = float(rl.returned_quantity or 0.0)
        price = float(rl.price_unit or 0.0)

        discount_qty = (
            (product.discount / 100.0) * qty if product.is_quantity_discount else 0.0
        )
        discount_amt_asset = float(discount_qty * price)

        commission_amt_asset = 0.0
        if product.is_sales_commissionable and float(product.commission or 0.0) > 0:
            commission_amt_asset = float(
                (qty - discount_qty) * product.commission * price
            )

        gross_asset = float(qty * price)

        staff_cur = ar_acc.currency_id
        gross_staff = self._sr_convert(gross_asset, asset_cur, staff_cur, rate)
        disc_staff = (
            self._sr_convert(discount_amt_asset, asset_cur, staff_cur, rate)
            if discount_amt_asset
            else 0.0
        )
        comm_staff = (
            self._sr_convert(commission_amt_asset, asset_cur, staff_cur, rate)
            if commission_amt_asset
            else 0.0
        )

        if schedule == "monthly":
            # IN (AR NET), IN (comm), OUT (disc)
            net_staff = gross_staff - comm_staff
            SpTxn.create(
                {
                    "sales_person_id": salesperson.id,
                    "date": fields.Date.today(),
                    "sale_return_id": order.id,
                    "order_id": order.sale_order_id.id,
                    "transaction_type": "in",
                    "amount": float(net_staff),
                    "description": f"Sales Return - A/R NET for {product.name} (Qty: {qty})",
                }
            )
            SpTxn.create(
                {
                    "sales_person_id": salesperson.id,
                    "date": fields.Date.today(),
                    "sale_return_id": order.id,
                    "order_id": order.sale_order_id.id,
                    "transaction_type": "in",
                    "amount": float(comm_staff),
                    "description": f"Sales Return - Commission reversal (monthly) for {product.name}",
                }
            )
            SpTxn.create(
                {
                    "sales_person_id": salesperson.id,
                    "date": fields.Date.today(),
                    "sale_return_id": order.id,
                    "order_id": order.sale_order_id.id,
                    "transaction_type": "out",
                    "amount": float(disc_staff),
                    "description": f"Sales Return - Discount reversal for {product.name}",
                }
            )
        else:
            # IN (gross), OUT (comm), OUT (disc)
            SpTxn.create(
                {
                    "sales_person_id": salesperson.id,
                    "date": fields.Date.today(),
                    "sale_return_id": order.id,
                    "order_id": order.sale_order_id.id,
                    "transaction_type": "in",
                    "amount": float(gross_staff),
                    "description": f"Sales Return - Gross for {product.name} (Qty: {qty})",
                }
            )
            SpTxn.create(
                {
                    "sales_person_id": salesperson.id,
                    "date": fields.Date.today(),
                    "sale_return_id": order.id,
                    "order_id": order.sale_order_id.id,
                    "transaction_type": "out",
                    "amount": float(comm_staff),
                    "description": f"Sales Return - Commission reversal (daily) for {product.name}",
                }
            )
            SpTxn.create(
                {
                    "sales_person_id": salesperson.id,
                    "date": fields.Date.today(),
                    "sale_return_id": order.id,
                    "order_id": order.sale_order_id.id,
                    "transaction_type": "out",
                    "amount": float(disc_staff),
                    "description": f"Sales Return - Discount reversal for {product.name}",
                }
            )

    def _sr_post_line_movement(self, ctx, rl):
        order = ctx["order"]
        qty = float(rl.returned_quantity or 0.0)
        self.env["idil.product.movement"].create(
            {
                "product_id": rl.product_id.id,
                "movement_type": "in",
                "quantity": qty,
                "date": order.return_date,
                "source_document": order.name,
                "sales_person_id": order.salesperson_id.id,
            }
        )

    def _sr_update_receipt(self, ctx):
        order = ctx["order"]
        Receipt = ctx["Receipt"]
        ar_acc = ctx["ar_acc"]
        schedule = ctx["schedule"]
        rate = ctx["rate"]

        sales_receipt = Receipt.search(
            [("sales_order_id", "=", order.sale_order_id.id)], limit=1
        )
        if not sales_receipt:
            return

        total_return_ar = 0.0

        for rl in order.return_lines:
            if rl.returned_quantity <= 0:
                continue
            p = rl.product_id
            if not p or not p.asset_account_id or not p.asset_account_id.currency_id:
                continue

            asset_cur = p.asset_account_id.currency_id
            qty = float(rl.returned_quantity or 0.0)
            price = float(rl.price_unit or 0.0)

            gross_asset = qty * price
            discount_qty = (p.discount / 100.0) * qty if p.is_quantity_discount else 0.0
            discount_asset = discount_qty * price

            commission_asset = 0.0
            if p.is_sales_commissionable and float(p.commission or 0.0) > 0:
                commission_asset = (qty - discount_qty) * p.commission * price

            # monthly: base - discount + commission
            # daily:   base - discount - commission

            if schedule == "monthly":
                net_asset = gross_asset - discount_asset

            else:
                net_asset = gross_asset - discount_asset - commission_asset

            total_return_ar += self._sr_convert(
                net_asset, asset_cur, ar_acc.currency_id, rate
            )

        sales_receipt.due_amount -= float(total_return_ar)
        sales_receipt.paid_amount = min(
            sales_receipt.paid_amount, sales_receipt.due_amount
        )
        sales_receipt.remaining_amount = (
            sales_receipt.due_amount - sales_receipt.paid_amount
        )
        sales_receipt.payment_status = (
            "paid" if sales_receipt.due_amount <= 0 else "pending"
        )

    def _sr_update_commission_record(self, ctx):
        """
        Sale Return → Commission handling (MONTHLY only)

        Goals:
        1) Reduce the original commission_amount based on returned qty
        2) If the commission was already settled (either by CASH payment OR by BALANCE allocation),
        and now the valid commission becomes smaller, move the OVERPAID portion into
        salesperson.commission_balance.
        3) Create an OUT allocation payment row on the commission as an audit trail.
        4) Prevent duplicates across multiple returns using comm_rec.balance_shifted.
        """

        order = ctx["order"]  # SaleReturn
        salesperson = ctx["salesperson"]
        schedule = ctx["schedule"]
        rate = ctx["rate"]
        ar_cur = ctx["ar_acc"].currency_id  # staff currency

        # Only monthly uses deferred commissions
        if schedule != "monthly":
            return

        Comm = self.env["idil.sales.commission"]
        Pay = self.env["idil.sales.commission.payment"]

        # Commission record related to the original Sales Order
        comm_rec = Comm.search(
            [
                ("sale_order_id", "=", order.sale_order_id.id),
                ("sales_person_id", "=", salesperson.id),
            ],
            order="id desc",
            limit=1,
        )
        if not comm_rec:
            return

        # ---------------------------------------------------------
        # A) Compute commission reversed by THIS return (staff currency)
        # ---------------------------------------------------------
        total_comm_staff = 0.0
        for rl in order.return_lines:
            if float(rl.returned_quantity or 0.0) <= 0:
                continue

            p = rl.product_id
            if (
                not p
                or not p.is_sales_commissionable
                or float(p.commission or 0.0) <= 0
            ):
                continue

            asset_cur = p.asset_account_id.currency_id
            qty = float(rl.returned_quantity or 0.0)
            price = float(rl.price_unit or 0.0)

            discount_qty = (p.discount / 100.0) * qty if p.is_quantity_discount else 0.0
            comm_asset = (qty - discount_qty) * p.commission * price

            total_comm_staff += order._sr_convert(comm_asset, asset_cur, ar_cur, rate)

        if total_comm_staff <= 0:
            return

        # ---------------------------------------------------------
        # B) Reduce commission_amount (valid commission left)
        # ---------------------------------------------------------
        old_amt = float(comm_rec.commission_amount or 0.0)
        new_amt = max(old_amt - total_comm_staff, 0.0)
        comm_rec.commission_amount = new_amt

        # mark returned fully if now zero
        if new_amt <= 0.00001:
            comm_rec.state = "cancelled_return"

        # ---------------------------------------------------------
        # C) Determine how much was already settled BEFORE this return
        #    - CASH payments: not is_allocation
        #    - BALANCE payments: is_allocation + allocation_ref startswith "BAL-IN-"
        # ---------------------------------------------------------
        cash_paid = (
            sum(
                comm_rec.payment_ids.filtered(lambda p: not p.is_allocation).mapped(
                    "amount"
                )
            )
            or 0.0
        )

        balance_paid = (
            sum(
                comm_rec.payment_ids.filtered(
                    lambda p: p.is_allocation
                    and (p.allocation_ref or "").startswith("BAL-IN-")
                ).mapped("amount")
            )
            or 0.0
        )

        total_paid_effect = float(cash_paid) + float(balance_paid)

        # If nothing settled, nothing to shift
        if total_paid_effect <= 0.00001:
            return

        # ---------------------------------------------------------
        # D) How much SHOULD be sitting in salesperson balance after this return?
        #    Overpaid = settled - new valid amount
        # ---------------------------------------------------------
        should_shift_total = max(total_paid_effect - new_amt, 0.0)

        # already shifted (avoid duplicates across multiple returns)
        already_shifted = float(comm_rec.balance_shifted or 0.0)

        delta_shift = should_shift_total - already_shifted
        if delta_shift <= 0.00001:
            return

        # ---------------------------------------------------------
        # E) Create OUT allocation on this commission (audit trail)
        # ---------------------------------------------------------
        Pay.create(
            {
                "commission_id": comm_rec.id,
                "sales_person_id": comm_rec.sales_person_id.id,
                "currency_id": comm_rec.currency_id.id,
                "amount": -delta_shift,  # OUT (credit moved out)
                "is_allocation": True,
                "allocation_ref": f"RET-OUT-{order.sale_order_id.name}-{order.name}",
                "date": fields.Date.context_today(self),
            }
        )

        # ---------------------------------------------------------
        # F) Add to salesperson balance wallet
        # ---------------------------------------------------------
        salesperson.commission_balance = (
            float(salesperson.commission_balance or 0.0) + delta_shift
        )

        # track shifted amount to prevent duplicates
        comm_rec.balance_shifted = already_shifted + delta_shift

        # Optional chatter message
        comm_rec.message_post(
            body=(
                f"🔁 Sales Return {order.name}: shifted {delta_shift:,.2f} {comm_rec.currency_id.name} "
                f"to salesperson balance. New balance: {salesperson.commission_balance:,.2f}. "
                f"(Cash paid: {cash_paid:,.2f}, Balance paid: {balance_paid:,.2f}, New valid: {new_amt:,.2f})"
            )
        )

    def write(self, vals):
        for rec in self:
            if rec.state == "confirmed":
                raise UserError(
                    "🛑 Editing is not allowed for this sales return at the moment."
                )
        return super(SaleReturn, self).write(vals)

    def unlink(self):
        """
        Delete Sales Return SAFELY and restore everything as if return never happened.

        Rules:
        1) If related sales receipt has paid_amount > 0  -> BLOCK deletion
        2) If allowed:
        - Restore sales receipt amounts back (undo _sr_update_receipt effect)
        - Delete booking lines + booking created by this return
        - Delete salesperson transactions created by this return
        - Delete product movements created by this return
        - Then delete the return itself (lines will cascade)
        """
        try:
            with self.env.cr.savepoint():
                Receipt = self.env["idil.sales.receipt"]
                Booking = self.env["idil.transaction_booking"]
                BookingLine = self.env["idil.transaction_bookingline"]
                SpTxn = self.env["idil.salesperson.transaction"]
                Move = self.env["idil.product.movement"]

                for record in self:
                    # If you want to allow deleting draft freely:
                    if record.state != "confirmed":
                        continue

                    # --- 1) Block deletion if receipt has payment ---
                    receipt = Receipt.search(
                        [("sales_order_id", "=", record.sale_order_id.id)],
                        limit=1,
                    )
                    if receipt and float(receipt.paid_amount or 0.0) > 0:
                        raise ValidationError(
                            f"⚠️ You cannot delete Sales Return '{record.name}' because a payment of "
                            f"{receipt.paid_amount:.2f} has already been received on the related sales order."
                        )

                    # --- 2) Restore receipt (UNDO what _sr_update_receipt() did) ---
                    # _sr_update_receipt subtracts total_return_ar from due_amount
                    # so on delete we ADD it back.
                    if receipt:
                        salesperson = record.salesperson_id
                        if not salesperson or not salesperson.account_receivable_id:
                            raise ValidationError(
                                "Salesperson receivable account is missing; cannot restore receipt."
                            )

                        ar_acc = salesperson.account_receivable_id
                        schedule = (
                            salesperson.commission_payment_schedule
                        )  # monthly/daily
                        rate = float(record.rate or 0.0)
                        if rate <= 0:
                            raise ValidationError(
                                "Exchange rate must be > 0 to restore receipt."
                            )

                        total_return_ar = 0.0
                        for rl in record.return_lines:
                            if float(rl.returned_quantity or 0.0) <= 0:
                                continue

                            p = rl.product_id
                            if (
                                not p
                                or not p.asset_account_id
                                or not p.asset_account_id.currency_id
                            ):
                                continue

                            asset_cur = p.asset_account_id.currency_id
                            qty = float(rl.returned_quantity or 0.0)
                            price = float(rl.price_unit or 0.0)

                            gross_asset = qty * price
                            discount_qty = (
                                (p.discount / 100.0) * qty
                                if p.is_quantity_discount
                                else 0.0
                            )
                            discount_asset = discount_qty * price

                            commission_asset = 0.0
                            if (
                                p.is_sales_commissionable
                                and float(p.commission or 0.0) > 0
                            ):
                                commission_asset = (
                                    (qty - discount_qty) * p.commission * price
                                )

                            # MUST mirror your _sr_update_receipt() exactly:
                            # monthly: net = gross - discount
                            # daily:   net = gross - discount - commission
                            if schedule == "monthly":
                                net_asset = gross_asset - discount_asset
                            else:
                                net_asset = (
                                    gross_asset - discount_asset - commission_asset
                                )

                            total_return_ar += record._sr_convert(
                                net_asset, asset_cur, ar_acc.currency_id, rate
                            )

                        # Restore back
                        receipt.due_amount += float(total_return_ar)
                        receipt.paid_amount = min(
                            receipt.paid_amount, receipt.due_amount
                        )
                        receipt.remaining_amount = (
                            receipt.due_amount - receipt.paid_amount
                        )
                        receipt.payment_status = (
                            "paid" if receipt.due_amount <= 0 else "pending"
                        )

                    # --- 3) Delete created accounting + other effects ---
                    # Booking lines + booking
                    BookingLine.search([("sale_return_id", "=", record.id)]).unlink()
                    Booking.search([("sale_return_id", "=", record.id)]).unlink()

                    # Salesperson transactions
                    SpTxn.search([("sale_return_id", "=", record.id)]).unlink()

                    # Product movements created by return (you used source_document = order.name)
                    Move.search(
                        [
                            ("source_document", "=", record.name),
                            ("movement_type", "=", "in"),
                        ]
                    ).unlink()

                # Finally delete return records (lines cascade)
                return super(SaleReturn, self).unlink()

        except Exception as e:
            _logger.exception("Sales Return unlink failed: %s", e)
            raise ValidationError(f"Transaction failed: {str(e)}")

    @api.model
    def create(self, vals):
        if vals.get("name", "New") == "New":
            vals["name"] = (
                self.env["ir.sequence"].next_by_code("idil.sale.return") or "New"
            )
        return super(SaleReturn, self).create(vals)


class SaleReturnLine(models.Model):
    _name = "idil.sale.return.line"
    _description = "Sale Return Line"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "id desc"

    return_id = fields.Many2one(
        "idil.sale.return",
        string="Sale Return",
        required=True,
        ondelete="cascade",
        tracking=True,
    )
    product_id = fields.Many2one(
        "my_product.product", string="Product", required=True, tracking=True
    )
    # ✅ Currency shown on line (from product inventory/asset account currency)
    currency_id = fields.Many2one(
        "res.currency",
        string="Prod CY",
        related="product_id.asset_account_id.currency_id",
        store=True,
        readonly=True,
    )

    quantity = fields.Float(string="Sales QTY", required=True)
    returned_quantity = fields.Float(
        string="Returned QTY", required=True, tracking=True
    )
    price_unit = fields.Float(string="Unit Price", required=True, tracking=True)
    subtotal = fields.Float(
        string="Subtotal", compute="_compute_subtotal", store=True, tracking=True
    )
    previously_returned_qty = fields.Float(
        string="Prev Return QTY",
        compute="_compute_previously_returned_qty",
        store=False,
        readonly=True,
        tracking=True,
    )
    available_return_qty = fields.Float(
        string="Availabl to Return",
        compute="_compute_available_return_qty",
        store=False,
        readonly=True,
        tracking=True,
    )

    discount_amount = fields.Monetary(
        string="Discount Amount",
        currency_field="currency_id",
        compute="_compute_amounts",
        store=True,
        tracking=True,
    )
    commission_amount = fields.Monetary(
        string="Commission Amount",
        currency_field="currency_id",
        compute="_compute_amounts",
        store=True,
        tracking=True,
    )
    net_amount = fields.Monetary(
        string="Net Amount",
        currency_field="currency_id",
        compute="_compute_amounts",
        store=True,
        tracking=True,
        help="Net = (qty*price) - discount - commission",
    )

    USD_currency_id = fields.Many2one(
        "res.currency",
        string="USD CY",
        required=True,
        default=lambda self: self.env["res.currency"].search(
            [("name", "=", "USD")], limit=1
        ),
        readonly=True,
    )

    SL_currency_id = fields.Many2one(
        "res.currency",
        string="FY CY",
        required=True,
        default=lambda self: self.env["res.currency"].search(
            [("name", "=", "SL")], limit=1
        ),
        readonly=True,
    )

    total_net_usd = fields.Monetary(
        string="Net (USD)",
        currency_field="USD_currency_id",
        compute="_compute_totals_currency",
        store=False,
        tracking=True,
    )
    total_net_sl = fields.Monetary(
        string="Net (FY)",
        currency_field="SL_currency_id",
        compute="_compute_totals_currency",
        store=False,
        tracking=True,
    )

    @api.depends("net_amount", "currency_id", "return_id.rate")
    def _compute_totals_currency(self):
        """
        Compute THIS LINE net in USD and SL.
        Uses:
        - net_amount (already computed as gross - discount - commission) in product currency
        - currency_id = product currency
        - return_id.rate (1 USD = rate SL)
        """
        for line in self:
            rate = float(line.return_id.rate or 0.0)
            amt = float(line.net_amount or 0.0)
            cur = line.currency_id

            if not cur or amt == 0.0:
                line.total_net_usd = 0.0
                line.total_net_sl = 0.0
                continue

            cur_name = cur.name

            if cur_name == "USD":
                line.total_net_usd = amt
                line.total_net_sl = (amt * rate) if rate else 0.0

            elif cur_name == "SL":
                line.total_net_sl = amt
                line.total_net_usd = (amt / rate) if rate else 0.0

            else:
                raise ValidationError(
                    f"Unsupported currency '{cur_name}' on product '{line.product_id.display_name}'. "
                    "Only USD and SL are supported."
                )

    @api.depends(
        "returned_quantity",
        "price_unit",
        "product_id.discount",
        "product_id.commission",
        "product_id.is_quantity_discount",
        "product_id.is_sales_commissionable",
    )
    def _compute_amounts(self):
        for line in self:
            qty = float(line.returned_quantity or 0.0)
            price = float(line.price_unit or 0.0)
            p = line.product_id

            if not p or qty <= 0:
                line.discount_amount = 0.0
                line.commission_amount = 0.0
                line.net_amount = 0.0
                continue

            # discount
            discount_qty = (p.discount / 100.0) * qty if p.is_quantity_discount else 0.0
            discount_amt = discount_qty * price

            # commission
            commission_amt = 0.0
            if p.is_sales_commissionable:
                commission_base_qty = qty - discount_qty
                commission_amt = commission_base_qty * p.commission * price

            gross = qty * price
            net = gross - discount_amt

            line.discount_amount = discount_amt
            line.commission_amount = commission_amt
            line.net_amount = net

    @api.depends("product_id", "return_id.sale_order_id")
    def _compute_previously_returned_qty(self):
        for line in self:
            if (
                not line.product_id
                or not line.return_id
                or not line.return_id.sale_order_id
            ):
                line.previously_returned_qty = 0.0
                continue

            domain = [
                ("product_id", "=", line.product_id.id),
                ("return_id.sale_order_id", "=", line.return_id.sale_order_id.id),
                ("return_id.state", "=", "confirmed"),
            ]

            # Avoid filtering by ID if the line is not saved (has no numeric ID)
            if isinstance(line.id, int):
                domain.append(("id", "!=", line.id))

            previous_lines = self.env["idil.sale.return.line"].search(domain)
            line.previously_returned_qty = sum(
                r.returned_quantity for r in previous_lines
            )

    @api.depends("returned_quantity", "price_unit")
    def _compute_subtotal(self):
        for line in self:
            line.subtotal = line.returned_quantity * line.price_unit

    @api.depends("product_id", "return_id.sale_order_id")
    def _compute_available_return_qty(self):
        for line in self:
            line.available_return_qty = 0.0
            if (
                not line.product_id
                or not line.return_id
                or not line.return_id.sale_order_id
            ):
                continue

            sale_line = self.env["idil.sale.order.line"].search(
                [
                    ("order_id", "=", line.return_id.sale_order_id.id),
                    ("product_id", "=", line.product_id.id),
                ],
                limit=1,
            )

            if not sale_line:
                continue

            domain = [
                ("product_id", "=", line.product_id.id),
                ("return_id.sale_order_id", "=", line.return_id.sale_order_id.id),
                ("return_id.state", "=", "confirmed"),
            ]
            if isinstance(line.id, int):
                domain.append(("id", "!=", line.id))

            previous_lines = self.env["idil.sale.return.line"].search(domain)
            total_prev_returned = sum(r.returned_quantity for r in previous_lines)
            line.available_return_qty = max(
                sale_line.quantity - total_prev_returned, 0.0
            )
