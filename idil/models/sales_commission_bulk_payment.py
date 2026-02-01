from odoo import models, fields, api, _
from odoo.exceptions import ValidationError
import logging

_logger = logging.getLogger(__name__)

MODULE_VERSION = "2.0-ORM"


class SalesCommissionBulkPayment(models.Model):
    _name = "idil.sales.commission.bulk.payment"
    _description = "Sales Commission Bulk Payment"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "id desc"

    name = fields.Char(string="Reference", default="New", readonly=True, copy=False)

    company_id = fields.Many2one(
        "res.company", default=lambda s: s.env.company, required=True
    )
    sales_person_id = fields.Many2one(
        "idil.sales.sales_personnel",
        string="Salesperson",
        required=True,
        domain=[("commission_payment_schedule", "=", "monthly")],
    )

    amount_to_pay = fields.Float(
        string="Total Amount to Pay", required=True, store=True
    )

    payment_method_ids = fields.One2many(
        "idil.sales.commission.bulk.payment.method",
        "bulk_payment_id",
        string="Payment Methods",
    )

    total_methods_amount = fields.Float(
        string="Total Payment Breakdown",
        compute="_compute_total_methods_amount",
        store=False,
    )

    # cash_account_id = fields.Many2one(
    #     "idil.chart.account",
    #     string="Cash/Bank Account",
    #     required=True,
    #     domain=[("account_type", "in", ["cash", "bank_transfer"])],
    # )

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
        tracking=True,
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

    booking_ids = fields.Many2many(
        "idil.transaction_booking",
        compute="_compute_booking_ids",
        string="Accounting Entries",
        readonly=True,
    )
    booking_count = fields.Integer(
        compute="_compute_booking_ids",
        string="Accounting Entries",
        readonly=True,
    )

    journal_summary_html = fields.Html(
        string="Accounting Entry Summary",
        compute="_compute_journal_summary_html",
        store=False,
        readonly=True,
    )

    @api.depends("line_ids")
    def _compute_booking_ids(self):
        Payment = self.env["idil.sales.commission.payment"]
        for rec in self:
            payments = Payment.search(
                [
                    ("bulk_payment_line_id", "in", rec.line_ids.ids),
                    ("transaction_booking_id", "!=", False),
                ]
            )
            bookings = payments.mapped("transaction_booking_id")
            rec.booking_ids = bookings
            rec.booking_count = len(bookings)

    def action_open_bookings(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Accounting Entries"),
            "res_model": "idil.transaction_booking",
            "view_mode": "tree,form",
            "domain": [("id", "in", self.booking_ids.ids)],
            "target": "current",
        }

    @api.depends(
        "booking_ids",
        "booking_ids.booking_lines",
        "booking_ids.booking_lines.dr_amount",
        "booking_ids.booking_lines.cr_amount",
        "booking_ids.booking_lines.account_number",
    )
    def _compute_journal_summary_html(self):
        for rec in self:
            # collect all booking lines from all related bookings
            lines = rec.booking_ids.mapped("booking_lines")
            if not lines:
                rec.journal_summary_html = (
                    "<div class='text-muted'>No accounting entries yet.</div>"
                )
                continue

            grouped = {}
            for ln in lines:
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

            rec.journal_summary_html = f"""
            <div style="border:1px solid #e5e7eb; border-radius:12px; padding:12px; background:#fff;">
              <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:8px;">
                <div style="font-weight:700;">Accounting Entry Summary</div>
                <div style="font-weight:700; color:{'#16a34a' if balanced else '#dc2626'};">
                  {'✔ Balanced' if balanced else '✖ Not Balanced'}
                </div>
              </div>

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
            </div>
            """

    @api.depends("payment_method_ids.amount")
    def _compute_total_methods_amount(self):
        for rec in self:
            rec.total_methods_amount = (
                sum(rec.payment_method_ids.mapped("amount")) or 0.0
            )

    @api.constrains("amount_to_pay", "payment_method_ids", "payment_method_ids.amount")
    def _check_methods_total(self):
        for rec in self:
            if rec.amount_to_pay and rec.payment_method_ids:
                total = sum(rec.payment_method_ids.mapped("amount")) or 0.0
                if abs(total - rec.amount_to_pay) > 0.001:
                    raise ValidationError(
                        _(
                            "Payment breakdown total (%.2f) must equal Amount To Pay (%.2f)."
                        )
                        % (total, rec.amount_to_pay)
                    )

    # ---------------------------------------------------------
    # ORM helpers (replace SQL)
    # ---------------------------------------------------------
    def _get_commissions_domain(self):
        """Keep your exact business rule: monthly commissions only for this salesperson."""
        self.ensure_one()
        return [
            ("sales_person_id", "=", self.sales_person_id.id),
            # salesperson domain already forces monthly schedule; but keep safe:
            ("sales_person_id.commission_payment_schedule", "=", "monthly"),
        ]

    def _get_payments_for_commissions(self, commissions):
        """All payments for given commission set."""
        Payment = self.env["idil.sales.commission.payment"]
        return Payment.search([("commission_id", "in", commissions.ids)])

    def _get_paid_map(self, commissions):
        payments = self._get_payments_for_commissions(commissions).filtered(
            lambda p: not p.is_allocation
        )
        paid_map = {cid: 0.0 for cid in commissions.ids}
        for p in payments:
            paid_map[p.commission_id.id] = paid_map.get(
                p.commission_id.id, 0.0
            ) + float(p.amount or 0.0)
        return paid_map

    def _get_commission_remaining_lines(self):
        """
        Standard ORM version of your SQL that returns rows with:
        - commission_id, commission_date, commission_amount, paid, remaining
        Only for remaining > 0.001, ordered ASC.
        """
        self.ensure_one()
        if not self.sales_person_id:
            return []

        Commission = self.env["idil.sales.commission"]

        domain = self._get_commissions_domain() + [
            ("state", "=", "normal"),  # ✅ exclude returned commissions
            (
                "payment_status",
                "not in",
                ["reallocated", "partial_reallocated", "cancelled"],
            ),
        ]
        commissions = Commission.search(domain, order="id asc")

        if not commissions:
            return []

        paid_map = self._get_paid_map(commissions)

        rows = []
        for sc in commissions:
            paid = float(sc.commission_paid or 0.0)
            remaining = float(sc.commission_remaining or 0.0)

            if remaining > 0.001:
                rows.append(
                    {
                        "commission": sc,
                        "commission_id": sc.id,
                        "commission_date": sc.date,
                        "commission_amount": float(sc.commission_amount or 0.0),
                        "commission_paid": paid,
                        "commission_remaining": remaining,
                    }
                )
        return rows

    # ---------------------------------------------------------
    # Compute due commission (replace SQL)
    # ---------------------------------------------------------
    @api.depends("sales_person_id")
    def _compute_due_commission(self):
        for rec in self:
            if not rec.sales_person_id:
                rec.due_commission_count = 0
                rec.due_commission_amount = 0.0
                continue

            rows = rec._get_commission_remaining_lines()
            rec.due_commission_count = len(rows)
            rec.due_commission_amount = (
                sum(r["commission_remaining"] for r in rows) if rows else 0.0
            )

    # ---------------------------------------------------------
    # Onchange generate lines (replace SQL)
    # ---------------------------------------------------------
    @api.onchange("sales_person_id", "amount_to_pay")
    def _onchange_sales_person_id(self):
        self.line_ids = [(5, 0, 0)]
        if not self.sales_person_id:
            return

        rows = self._get_commission_remaining_lines()
        total_remaining = sum(r["commission_remaining"] for r in rows) if rows else 0.0

        if self.amount_to_pay == 0:
            self.amount_to_pay = total_remaining

        if self.amount_to_pay > total_remaining + 0.001:
            self.amount_to_pay = 0
            return {
                "warning": {
                    "title": _("Amount Too High"),
                    "message": _(
                        "Total Amount to Pay cannot exceed the sum of all unpaid commissions (%.2f)."
                    )
                    % total_remaining,
                }
            }

        if self.amount_to_pay > 0 and rows:
            lines = []
            remaining_payment = self.amount_to_pay

            for r in rows:
                if remaining_payment <= 0:
                    break

                commission_remaining = r["commission_remaining"]
                if commission_remaining <= 0:
                    continue

                payable = min(remaining_payment, commission_remaining)
                if payable > 0:
                    lines.append(
                        (
                            0,
                            0,
                            {
                                "commission_id": r["commission_id"],
                                "commission_date": r["commission_date"],
                                "commission_amount": r["commission_amount"],
                                "commission_paid": r["commission_paid"],
                                "commission_remaining": r["commission_remaining"],
                                "paid_amount": payable,  # keep this field accurate on UI
                            },
                        )
                    )
                    remaining_payment -= payable

            self.line_ids = lines

    # ---------------------------------------------------------
    # Fallback line generator (replace SQL)
    # ---------------------------------------------------------
    def _generate_commission_lines(self):
        """Generate lines using ORM - used when onchange lines don't persist."""
        for rec in self:
            if not rec.sales_person_id or not rec.amount_to_pay:
                return

            _logger.info(
                "Generating lines for %s: salesperson=%s, amount=%s",
                rec.name,
                rec.sales_person_id.id,
                rec.amount_to_pay,
            )

            rows = rec._get_commission_remaining_lines()
            _logger.info("Found %s unpaid commissions", len(rows))

            if not rows:
                return

            Line = rec.env["idil.sales.commission.bulk.payment.line"]

            remaining_payment = rec.amount_to_pay
            created = 0

            for r in rows:
                if remaining_payment <= 0:
                    break

                commission_remaining = r["commission_remaining"]
                if commission_remaining <= 0:
                    continue

                payable = min(remaining_payment, commission_remaining)
                if payable <= 0:
                    continue

                Line.create(
                    {
                        "bulk_payment_id": rec.id,
                        "commission_id": r["commission_id"],
                        "commission_date": r["commission_date"],
                        "commission_amount": r["commission_amount"],
                        "commission_paid": r["commission_paid"],
                        "commission_remaining": r["commission_remaining"],
                        "paid_amount": payable,
                    }
                )
                created += 1
                remaining_payment -= payable

            _logger.info("Created %s commission lines for %s", created, rec.name)

    # ---------------------------------------------------------
    # Constrains (replace SQL)
    # ---------------------------------------------------------
    @api.constrains("amount_to_pay", "sales_person_id")
    def _check_amount_to_pay(self):
        for rec in self:
            if rec.sales_person_id and rec.amount_to_pay:
                rows = rec._get_commission_remaining_lines()
                total_remaining = (
                    sum(r["commission_remaining"] for r in rows) if rows else 0.0
                )
                if rec.amount_to_pay > total_remaining + 0.001:
                    raise ValidationError(
                        _(
                            "Total Amount to Pay (%.2f) cannot exceed total unpaid commission (%.2f) for this salesperson."
                        )
                        % (rec.amount_to_pay, total_remaining)
                    )

    def action_confirm_payment(self):
        for rec in self:
            if rec.state != "draft":
                return

            # 1) must have methods
            if not rec.payment_method_ids:
                raise ValidationError(
                    _("Please add at least one payment method (cash/bank/etc).")
                )

            # 2) validate breakdown total already handled by constraint
            # 3) validate balances per account
            rec._validate_payment_method_balances()

            # 4) ensure lines exist
            if not rec.line_ids:
                rec._generate_commission_lines()
            if not rec.line_ids:
                raise ValidationError(_("No commission lines to pay."))

            # build pool: list of dicts with remaining per account
            pool = []
            for m in rec.payment_method_ids:
                if float(m.amount or 0.0) > 0:
                    pool.append({"account": m.account_id, "remaining": float(m.amount)})

            def _take_from_pool(need):
                chunks = []
                remaining = float(need)
                for p in pool:
                    if remaining <= 0:
                        break
                    if p["remaining"] <= 0:
                        continue
                    use = min(remaining, p["remaining"])
                    chunks.append({"account": p["account"], "amount": use})
                    p["remaining"] -= use
                    remaining -= use

                if remaining > 0.001:
                    raise ValidationError(
                        _("Payment breakdown is not enough to cover Amount To Pay.")
                    )
                return chunks

            remaining_payment = rec.amount_to_pay
            payments_created = 0

            for line in rec.line_ids.sorted(key=lambda l: l.commission_id.id):
                if remaining_payment <= 0:
                    break

                commission = line.commission_id
                if not commission:
                    continue

                # fresh remaining (your logic)
                payments = self.env["idil.sales.commission.payment"].search(
                    [("commission_id", "=", commission.id)]
                )
                total_paid = sum(payments.mapped("amount")) or 0.0
                commission_needed = float(commission.commission_amount or 0.0) - float(
                    total_paid or 0.0
                )

                if commission_needed <= 0:
                    continue

                payable = min(remaining_payment, commission_needed)
                if payable <= 0:
                    break

                # split payable across accounts
                chunks = _take_from_pool(payable)

                # IMPORTANT: create payments per chunk and link them to bulk line
                for ch in chunks:
                    # call pay_commission using this account + amount
                    commission.cash_account_id = ch["account"]
                    commission.amount_to_pay = ch["amount"]

                    # ✅ make pay_commission return created payment (see fix below)
                    payment = commission.with_context(
                        return_payment_record=True
                    ).pay_commission()

                    if payment:
                        payment.bulk_payment_line_id = line.id
                        payments_created += 1

                # refresh snapshot for the bulk line after all chunks
                payments2 = self.env["idil.sales.commission.payment"].search(
                    [("commission_id", "=", commission.id)]
                )
                fresh_paid = sum(payments2.mapped("amount")) or 0.0
                fresh_remaining = float(commission.commission_amount or 0.0) - float(
                    fresh_paid or 0.0
                )

                line.write(
                    {
                        "paid_amount": payable,
                        "commission_paid": fresh_paid,
                        "commission_remaining": fresh_remaining,
                    }
                )

                remaining_payment -= payable

            if payments_created == 0:
                raise ValidationError(_("No payments were created."))

            rec.write({"state": "confirmed"})

    @api.constrains("amount_to_pay", "payment_method_ids")
    def _check_methods_required(self):
        for rec in self:
            if rec.amount_to_pay > 0 and not rec.payment_method_ids:
                raise ValidationError(
                    _("Please add payment methods before confirming.")
                )

    # ---------------------------------------------------------
    # Cash balance (replace SQL)
    # ---------------------------------------------------------
    def _get_account_balance(self, account):
        lines = self.env["idil.transaction_bookingline"].search(
            [("account_number", "=", account.id)]
        )
        dr = sum(lines.mapped("dr_amount")) or 0.0
        cr = sum(lines.mapped("cr_amount")) or 0.0
        return dr - cr

    def _validate_payment_method_balances(self):
        self.ensure_one()
        for m in self.payment_method_ids:
            bal = self._get_account_balance(m.account_id)
            if m.amount > bal + 0.001:
                raise ValidationError(
                    _("Insufficient balance in %s. Balance: %.2f, Required: %.2f")
                    % (m.account_id.display_name, bal, m.amount)
                )

    # ---------------------------------------------------------
    # Create / unlink / write (unchanged logic)
    # ---------------------------------------------------------
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
            for line in bulk.line_ids:
                commission_payments = self.env["idil.sales.commission.payment"].search(
                    [("bulk_payment_line_id", "=", line.id)]
                )

                for payment in commission_payments:
                    commission = payment.commission_id
                    payment.unlink()

                    # same recalculation logic you had (kept)
                    commission.invalidate_recordset(
                        ["commission_paid", "commission_remaining", "payment_status"]
                    )
                    if hasattr(commission, "_compute_commission_paid"):
                        commission._compute_commission_paid()
                    if hasattr(commission, "_compute_commission_remaining"):
                        commission._compute_commission_remaining()
                    if hasattr(commission, "_compute_payment_status"):
                        commission._compute_payment_status()

        return super(SalesCommissionBulkPayment, self).unlink()

    def write(self, vals):
        # Allow state change to 'confirmed' even from draft
        if vals.keys() == {"state"} and vals.get("state") == "confirmed":
            return super().write(vals)

        for rec in self:
            if rec.state == "confirmed":
                raise ValidationError(
                    _(
                        "This record is confirmed and cannot be modified.\n"
                        "If changes are required, please delete and create a new bulk payment."
                    )
                )
        return super().write(vals)


class SalesCommissionBulkPaymentLine(models.Model):
    _name = "idil.sales.commission.bulk.payment.line"
    _description = "Sales Commission Bulk Payment Line"
    _order = "id desc"

    bulk_payment_id = fields.Many2one(
        "idil.sales.commission.bulk.payment",
        string="Bulk Payment",
        ondelete="cascade",
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


class SalesCommissionBulkPaymentMethod(models.Model):
    _name = "idil.sales.commission.bulk.payment.method"
    _description = "Bulk Commission Payment Method Line"
    _order = "id asc"

    bulk_payment_id = fields.Many2one(
        "idil.sales.commission.bulk.payment",
        required=True,
        ondelete="cascade",
    )

    payment_method = fields.Selection(
        [
            ("cash", "Cash"),
            ("bank_transfer", "Bank Transfer"),
            ("cheque", "Cheque"),
            ("other", "Other"),
        ],
        required=True,
        default="cash",
    )

    account_id = fields.Many2one(
        "idil.chart.account",
        string="Cash/Bank Account",
        required=True,
        domain=[("account_type", "in", ["cash", "bank_transfer"])],
    )

    amount = fields.Float(string="Amount", required=True, digits=(16, 5))
