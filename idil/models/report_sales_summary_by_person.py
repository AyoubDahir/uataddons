from odoo import models, fields
import base64, io
from collections import defaultdict
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
    Image,
)
from reportlab.lib.pagesizes import landscape, letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors


class SalesSummaryPersonReportWizard(models.TransientModel):
    _name = "idil.sales.summary.with.person"
    _description = "Sales Summary Report with Sales Person"

    start_date = fields.Date(string="Start Date", required=True)
    end_date = fields.Date(string="End Date", required=True)
    salesperson_id = fields.Many2one(
        "idil.sales.sales_personnel", string="Sales Person", required=True
    )

    def _should_convert_to_usd(self):
        # Your exact rule: salesperson linked A/R currency is USD => show report in USD
        ar_currency = self.salesperson_id.account_receivable_id.currency_id
        return bool(ar_currency and ar_currency.name == "USD")

    def _prepare_report_data(self):
        self.ensure_one()
        if not self.salesperson_id:
            return {}
        company = self.env.company
        company_currency = company.currency_id
        usd_currency = self.env.ref("base.USD")

        convert_to_usd = self._should_convert_to_usd()
        report_currency = usd_currency if convert_to_usd else company_currency
        salesperson_currency = (
            self.salesperson_id.account_receivable_id.currency_id
            if self.salesperson_id.account_receivable_id
            and self.salesperson_id.account_receivable_id.currency_id
            else company_currency
        )

        def money(amount, from_currency, date):
            amount = float(amount or 0.0)
            if not convert_to_usd:
                return amount
            if not from_currency or from_currency == report_currency:
                return amount
            return from_currency._convert(amount, report_currency, company, date)

        # 1. Opening Balance
        self.env.cr.execute(
            """
            SELECT l.amount, ob.date
            FROM idil_sales_opening_balance_line l
            JOIN idil_sales_opening_balance ob ON ob.id = l.opening_balance_id
            WHERE ob.state != 'cancel'
              AND l.sales_person_id = %s
            ORDER BY ob.date ASC
            LIMIT 1
            """,
            (self.salesperson_id.id,),
        )
        ob_row = self.env.cr.fetchone()
        opening_balance = float(ob_row[0]) if ob_row else 0.0
        opening_date = ob_row[1] if ob_row else self.start_date
        opening_balance_rep = money(opening_balance, company_currency, opening_date)

        # 2. Previous Balance
        self.env.cr.execute(
            """
                 SELECT
                    DATE(so.order_date) AS day,
                    so.currency_id AS so_currency_id,

                    /* Lacag: qty (after discount & return depending on flag) * price */
                    COALESCE(SUM(
                        (
                            (
                                COALESCE(sol.quantity, 0)
                                - (CASE
                                        WHEN COALESCE(p.is_quantity_discount, TRUE)
                                        THEN COALESCE(sol.discount_quantity, 0)
                                        ELSE 0
                                END)
                                - COALESCE(srl.returned_quantity, 0)
                            ) * COALESCE(sol.price_unit, 0)
                        )
                    ), 0) AS lacag_sum,

                    /* Commission: only if product is commissionable */
                    COALESCE(SUM(
                        (
                            (
                                COALESCE(sol.quantity, 0)
                                - (CASE
                                        WHEN COALESCE(p.is_quantity_discount, TRUE)
                                        THEN COALESCE(sol.discount_quantity, 0)
                                        ELSE 0
                                END)
                                - COALESCE(srl.returned_quantity, 0)
                            )  * COALESCE(sol.price_unit, 0)
                        ) * (CASE
                                WHEN COALESCE(p.is_sales_commissionable, TRUE)
                                THEN COALESCE(p.commission, 0)
                                ELSE 0
                        END)
                    ), 0) AS comm_sum

                FROM idil_salesperson_place_order spo
                INNER JOIN idil_sale_order so
                        ON so.sales_person_id = spo.salesperson_id
                    AND so.salesperson_order_id = spo.id
                INNER JOIN idil_sale_order_line sol ON sol.order_id = so.id
                INNER JOIN my_product_product p    ON p.id = sol.product_id
                LEFT JOIN  idil_sale_return sr
                        ON sr.salesperson_id = spo.salesperson_id
                    AND sr.sale_order_id  = so.id
                LEFT JOIN  idil_sale_return_line srl
                        ON srl.return_id = sr.id
                    AND srl.product_id = p.id

                WHERE spo.state = 'confirmed'
                AND spo.salesperson_id = %s
                AND DATE(so.order_date) < %s

                GROUP BY DATE(so.order_date), so.currency_id
            """,
            (self.salesperson_id.id, self.start_date),
        )
        previous_sales_net_rep = 0.0
        for day, so_currency_id, lacag_sum, comm_sum in self.env.cr.fetchall() or []:
            so_cur = (
                self.env["res.currency"].browse(int(so_currency_id))
                if so_currency_id
                else company_currency
            )
            net = float(lacag_sum or 0.0) - float(comm_sum or 0.0)
            previous_sales_net_rep += money(net, so_cur, day)

        self.env.cr.execute(
            """
            SELECT
                DATE(p.payment_date) AS day,
                COALESCE(r.currency_id, 0) AS receipt_currency_id,
                COALESCE(SUM(COALESCE(p.paid_amount,0)),0) AS paid_sum
            FROM idil_sales_payment p
            INNER JOIN idil_sales_receipt r ON r.id = p.sales_receipt_id
            WHERE r.salesperson_id = %s
              AND DATE(p.payment_date) < %s
            GROUP BY DATE(p.payment_date), COALESCE(r.currency_id, 0)
            """,
            (self.salesperson_id.id, self.start_date),
        )
        previous_paid_rep = 0.0
        for day, rcid, paid_sum in self.env.cr.fetchall() or []:
            pay_cur = (
                self.env["res.currency"].browse(int(rcid)) if rcid else company_currency
            )
            previous_paid_rep += money(float(paid_sum or 0.0), pay_cur, day)

        previous_balance_rep = previous_sales_net_rep - previous_paid_rep

        # 3. Current Period Sales
        self.env.cr.execute(
            """
           SELECT
                    DATE(so.order_date) AS order_day,
                    so.currency_id AS so_currency_id,
                    p.name,
                    sol.quantity,

                    /* Celis Tos (discount qty) only if Discountible */
                    (
                    CASE
                        WHEN COALESCE(p.is_quantity_discount, TRUE)
                        THEN (((COALESCE(sol.quantity, 0)) - COALESCE(srl.returned_quantity, 0)) * (COALESCE(p.discount,0) / 100))
                        ELSE 0
                    END
                    ) AS celis_tos,

                    COALESCE(srl.returned_quantity, 0) AS celis,

                    /* Net qty: discount applied only if Discountible */
                    (
                    COALESCE(sol.quantity, 0)
                    - (
                        CASE
                            WHEN COALESCE(p.is_quantity_discount, TRUE)
                            THEN (((COALESCE(sol.quantity, 0)) - COALESCE(srl.returned_quantity, 0)) * (COALESCE(p.discount,0) / 100))
                            ELSE 0
                        END
                        )
                    - COALESCE(srl.returned_quantity, 0)
                    ) AS net,

                    COALESCE(sol.price_unit, 0) AS qiime,

                    /* Lacag = net * price (net already respects Discountible flag) */
                    (
                    (
                        COALESCE(sol.quantity, 0)
                        - (
                            CASE
                            WHEN COALESCE(p.is_quantity_discount, TRUE)
                            THEN (((COALESCE(sol.quantity, 0)) - COALESCE(srl.returned_quantity, 0)) * (COALESCE(p.discount,0) / 100))
                            ELSE 0
                            END
                        )
                        - COALESCE(srl.returned_quantity, 0)
                    ) * COALESCE(sol.price_unit, 0)
                    ) AS lacag,

                    /* Per is still returned as stored (no change) */
                    COALESCE(sol.commission, 0) AS per,

                    /* Commission only if Commissionable */
                    (
                    CASE
                        WHEN COALESCE(p.is_sales_commissionable, TRUE)
                        THEN
                        (
                            (
                            COALESCE(sol.quantity, 0)
                            - (
                                CASE
                                    WHEN COALESCE(p.is_quantity_discount, TRUE)
                                    THEN (((COALESCE(sol.quantity, 0)) - COALESCE(srl.returned_quantity, 0)) * (COALESCE(p.discount,0) / 100))
                                    ELSE 0
                                END
                                )
                            - COALESCE(srl.returned_quantity, 0)
                            ) * COALESCE(sol.price_unit, 0)
                        ) * COALESCE(sol.commission, 0)
                        ELSE 0
                    END
                    ) AS comm

                FROM idil_salesperson_place_order spo
                INNER JOIN idil_sale_order so
                        ON so.sales_person_id = spo.salesperson_id
                    AND so.salesperson_order_id = spo.id
                INNER JOIN idil_sale_order_line sol ON sol.order_id = so.id
                INNER JOIN my_product_product p    ON sol.product_id = p.id
                LEFT JOIN  idil_sale_return sr
                        ON sr.salesperson_id = spo.salesperson_id
                    AND sr.sale_order_id  = so.id
                LEFT JOIN  idil_sale_return_line srl
                        ON srl.return_id = sr.id
                    AND srl.product_id = p.id

                WHERE spo.state = 'confirmed'
                AND spo.salesperson_id = %s
                AND DATE(so.order_date) BETWEEN %s AND %s

                ORDER BY so.order_date, sol.id
            """,
            (self.salesperson_id.id, self.start_date, self.end_date),
        )
        sales_by_day = defaultdict(list)
        for row in self.env.cr.fetchall() or []:
            sales_by_day[row[0]].append(row)

        # 4. Current Period Payments
        self.env.cr.execute(
            """
            SELECT
                DATE(p.payment_date) AS paid_day,
                COALESCE(r.currency_id, 0) AS receipt_currency_id,
                COALESCE(SUM(COALESCE(p.paid_amount,0)),0) AS total_paid
            FROM idil_sales_payment p
            INNER JOIN idil_sales_receipt r ON r.id = p.sales_receipt_id
            WHERE r.salesperson_id = %s
              AND DATE(p.payment_date) BETWEEN %s AND %s
            GROUP BY DATE(p.payment_date), COALESCE(r.currency_id, 0)
            """,
            (self.salesperson_id.id, self.start_date, self.end_date),
        )
        paid_by_day = defaultdict(float)
        for d, rcid, amt in self.env.cr.fetchall() or []:
            pay_cur = (
                self.env["res.currency"].browse(int(rcid)) if rcid else company_currency
            )
            paid_by_day[d] += money(float(amt or 0.0), pay_cur, d)

        all_days = sorted(set(sales_by_day.keys()) | set(paid_by_day.keys()))

        return {
            "report_currency": report_currency,
            "salesperson_currency": salesperson_currency,  # ✅ ADD THIS
            "opening_balance_rep": opening_balance_rep,
            "previous_balance_rep": previous_balance_rep,
            "sales_by_day": sales_by_day,
            "paid_by_day": paid_by_day,
            "all_days": all_days,
            "money_func": money,
            "company_currency": company_currency,
        }

    def get_report_data(self, wizard_id=None):
        wizard = self.browse(wizard_id) if wizard_id else self
        data = wizard._prepare_report_data()

        report_data = {
            "salesperson_name": wizard.salesperson_id.name,
            "start_date": wizard.start_date.strftime("%d %b %Y"),
            "end_date": wizard.end_date.strftime("%d %b %Y"),
            "currency": data["report_currency"].name,
            "salesperson_currency": (
                data.get("salesperson_currency") and data["salesperson_currency"].name
            )
            or "",
            "opening_sum": data["opening_balance_rep"] + data["previous_balance_rep"],
            "total_paid": 0.0,
            "period_sales_net": 0.0,
            "final_balance": 0.0,
            "days": {},
        }

        cumulative_outstanding = report_data["opening_sum"]
        total_paid_period = 0.0
        total_sales_net_period = 0.0

        for day in data["all_days"]:
            daily_sales_raw = data["sales_by_day"].get(day, [])
            day_subtotal_lacag = 0.0
            day_subtotal_comm = 0.0
            day_subtotal_balance = 0.0

            sales_list = []
            for s in daily_sales_raw:
                (
                    order_day,
                    so_cur_id,
                    product,
                    qty,
                    celis_tos,
                    celis,
                    net_qty,
                    qiime,
                    lacag,
                    per,
                    comm,
                ) = s
                so_cur = (
                    self.env["res.currency"].browse(int(so_cur_id))
                    if so_cur_id
                    else data["company_currency"]
                )

                lacag_rep = data["money_func"](lacag, so_cur, order_day)
                comm_rep = data["money_func"](comm, so_cur, order_day)
                qiime_rep = data["money_func"](qiime, so_cur, order_day)
                balance_rep = lacag_rep - comm_rep

                sales_list.append(
                    {
                        "product": product,
                        "qty": qty,
                        "celis": celis,
                        "celis_tos": celis_tos,
                        "net_qty": net_qty,
                        "qiime": qiime_rep,
                        "per": per,
                        "lacag": lacag_rep,
                        "comm": comm_rep,
                        "balance": balance_rep,
                    }
                )
                day_subtotal_lacag += lacag_rep
                day_subtotal_comm += comm_rep
                day_subtotal_balance += balance_rep

            paid_today = float(data["paid_by_day"].get(day, 0.0))
            cumulative_outstanding += day_subtotal_balance - paid_today
            total_paid_period += paid_today
            total_sales_net_period += day_subtotal_balance

            report_data["days"][day] = {
                "sales": sales_list,
                "subtotal_lacag": day_subtotal_lacag,
                "subtotal_comm": day_subtotal_comm,
                "subtotal_balance": day_subtotal_balance,
                "paid": paid_today,
                "running_outstanding": cumulative_outstanding,
            }

        report_data["total_paid"] = total_paid_period
        report_data["period_sales_net"] = total_sales_net_period
        report_data["final_balance"] = cumulative_outstanding

        return report_data

    def action_view_html_report(self):
        return self.env.ref(
            "idil.action_report_sales_summary_person_html"
        ).report_action(self)

    def generate_pdf_report(self):
        data_prep = self._prepare_report_data()
        report_currency = data_prep["report_currency"]
        money = data_prep["money_func"]
        company_currency = data_prep["company_currency"]
        opening_balance_rep = data_prep["opening_balance_rep"]
        previous_balance_rep = data_prep["previous_balance_rep"]
        sales_by_day = data_prep["sales_by_day"]
        paid_by_day = data_prep["paid_by_day"]
        all_days = data_prep["all_days"]

        company = self.env.company
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(
            buffer,
            pagesize=landscape(letter),
            rightMargin=30,
            leftMargin=30,
            topMargin=40,
            bottomMargin=30,
        )
        elements = []

        styles = getSampleStyleSheet()
        header_style = ParagraphStyle(
            name="Header",
            parent=styles["Title"],
            fontSize=18,
            textColor=colors.HexColor("#B6862D"),
            alignment=1,
        )
        subtitle_style = ParagraphStyle(
            name="Subtitle", parent=styles["Normal"], fontSize=12, alignment=1
        )
        left_align_style = ParagraphStyle(
            name="LeftAlign", parent=styles["Normal"], fontSize=12, alignment=0
        )

        logo = (
            Image(io.BytesIO(base64.b64decode(company.logo)), width=120, height=60)
            if company.logo
            else Paragraph("<b>No Logo Available</b>", header_style)
        )
        elements += [
            logo,
            Spacer(1, 12),
            Paragraph(f"<b>{company.name.upper()}</b>", header_style),
            Spacer(1, 6),
            Paragraph(
                f"{company.partner_id.city or ''}, {company.partner_id.country_id.name or ''}<br/>"
                f"Phone: {company.partner_id.phone or 'N/A'}<br/>"
                f"Email: {company.partner_id.email or 'N/A'}<br/>"
                f"Web: {company.website or 'N/A'}",
                subtitle_style,
            ),
            Spacer(1, 12),
            Paragraph(
                f"<b>Date from:</b> {self.start_date.strftime('%d/%m/%Y')}<br/>"
                f"<b>Date to:</b> {self.end_date.strftime('%d/%m/%Y')}<br/>"
                f"<b>Currency:</b> {report_currency.name}",
                left_align_style,
            ),
            Spacer(1, 8),
            Paragraph(
                f"<b>Sales Person Name:</b> {self.salesperson_id.name}",
                left_align_style,
            ),
            Spacer(1, 12),
        ]

        headers = [
            "Date",
            "Product",
            "Cadad",
            "Celis Tos",
            "Celis",
            "Net",
            "Qiime",
            "Lacag",
            "Per %",
            "Commission",
            "Balance",
        ]
        data = [headers]
        highlight_rows, merged_rows = [], []

        if opening_balance_rep:
            data.append(
                [
                    "OPENING BALANCE",
                    "",
                    "",
                    "",
                    "",
                    "",
                    "",
                    "",
                    "",
                    "",
                    f"{opening_balance_rep:,.2f}",
                ]
            )
            highlight_rows.append(len(data) - 1)
            merged_rows.append(len(data) - 1)

        if previous_balance_rep:
            data.append(
                [
                    "PREVIOUS BALANCE",
                    "",
                    "",
                    "",
                    "",
                    "",
                    "",
                    "",
                    "",
                    "",
                    f"{previous_balance_rep:,.2f}",
                ]
            )
            highlight_rows.append(len(data) - 1)
            merged_rows.append(len(data) - 1)

        running_lacag = 0.0
        running_commission = 0.0
        total_period_lacag = 0.0
        total_period_commission = 0.0
        total_period_balance = 0.0
        total_paid = 0.0
        cumulative_outstanding = previous_balance_rep + opening_balance_rep

        for day in all_days:
            daily_sales = sales_by_day.get(day, [])
            subtotal_lacag = subtotal_commission = subtotal_balance = 0.0

            for s in daily_sales:
                (
                    order_day,
                    so_currency_id,
                    product,
                    qty,
                    celis_tos,
                    celis,
                    net_qty,
                    qiime,
                    lacag,
                    per,
                    comm,
                ) = s
                so_cur = (
                    self.env["res.currency"].browse(int(so_currency_id))
                    if so_currency_id
                    else company_currency
                )
                qiime_rep = money(qiime, so_cur, order_day)
                lacag_rep = money(lacag, so_cur, order_day)
                comm_rep = money(comm, so_cur, order_day)
                balance_rep = lacag_rep - comm_rep

                data.append(
                    [
                        order_day.strftime("%d/%m/%Y"),
                        product,
                        f"{float(qty or 0.0):.2f}",
                        f"{float(celis_tos or 0.0):.2f}",
                        f"{float(celis or 0.0):.2f}",
                        f"{float(net_qty or 0.0):.2f}",
                        f"{qiime_rep:,.2f}",
                        f"{lacag_rep:,.2f}",
                        f"{float(per or 0.0):.2f}%",
                        f"{comm_rep:,.2f}",
                        f"{balance_rep:,.2f}",
                    ]
                )
                subtotal_lacag += lacag_rep
                subtotal_commission += comm_rep
                subtotal_balance += balance_rep

            paid_today = float(paid_by_day.get(day, 0.0))
            day_total = subtotal_balance - paid_today

            data.append(
                [
                    f"Subtotal {day.strftime('%d/%m/%Y')}",
                    "",
                    "",
                    "",
                    "",
                    "",
                    "",
                    f"{subtotal_lacag:,.2f}",
                    "",
                    f"{subtotal_commission:,.2f}",
                    f"{subtotal_balance:,.2f}",
                ]
            )
            highlight_rows.append(len(data) - 1)
            merged_rows.append(len(data) - 1)

            data.append(
                [
                    f"Paid {day.strftime('%d/%m/%Y')}",
                    "",
                    "",
                    "",
                    "",
                    "",
                    "",
                    "",
                    "",
                    "",
                    f"{paid_today:,.2f}",
                ]
            )
            highlight_rows.append(len(data) - 1)
            merged_rows.append(len(data) - 1)

            data.append(
                [
                    f"Day Total {day.strftime('%d/%m/%Y')}",
                    "",
                    "",
                    "",
                    "",
                    "",
                    "",
                    "",
                    "",
                    "",
                    f"{day_total:,.2f}",
                ]
            )
            highlight_rows.append(len(data) - 1)
            merged_rows.append(len(data) - 1)

            cumulative_outstanding += day_total
            running_lacag += subtotal_lacag
            running_commission += subtotal_commission

            data.append(
                [
                    f"Outstanding (to date) {day.strftime('%d/%m/%Y')}",
                    "",
                    "",
                    "",
                    "",
                    "",
                    "",
                    f"{running_lacag:,.2f}",
                    "",
                    f"{running_commission:,.2f}",
                    f"{cumulative_outstanding:,.2f}",
                ]
            )
            highlight_rows.append(len(data) - 1)
            merged_rows.append(len(data) - 1)

            total_period_lacag += subtotal_lacag
            total_period_commission += subtotal_commission
            total_period_balance += subtotal_balance
            total_paid += paid_today

        grand_total_before_paid = (
            opening_balance_rep + previous_balance_rep + total_period_balance
        )
        data.append(
            [
                "GRAND TOTAL",
                "",
                "",
                "",
                "",
                "",
                "",
                f"{total_period_lacag:,.2f}",
                "",
                f"{total_period_commission:,.2f}",
                f"{grand_total_before_paid:,.2f}",
            ]
        )
        highlight_rows.append(len(data) - 1)
        merged_rows.append(len(data) - 1)

        data.append(["", "", "", "", "", "", "", "", "", "", "--------------------"])
        data.append(
            ["TOTAL PAID", "", "", "", "", "", "", "", "", "", f"{total_paid:,.2f}"]
        )
        highlight_rows.append(len(data) - 1)
        merged_rows.append(len(data) - 1)

        final_balance = grand_total_before_paid - total_paid
        data.append(
            [
                "FINAL BALANCE",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                f"{final_balance:,.2f}",
            ]
        )
        final_balance_index = len(data) - 1
        highlight_rows.append(final_balance_index)
        merged_rows.append(final_balance_index)

        table = Table(data, colWidths=[70, 140, 50, 60, 50, 40, 60, 80, 50, 70, 100])
        style = TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#B6862D")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ]
        )
        for row_idx in highlight_rows:
            style.add("FONTNAME", (0, row_idx), (-1, row_idx), "Helvetica-Bold")
        for row_idx in merged_rows:
            style.add("SPAN", (0, row_idx), (2, row_idx))
        style.add(
            "BACKGROUND",
            (0, final_balance_index),
            (-1, final_balance_index),
            colors.HexColor("#FFD700"),
        )
        table.setStyle(style)

        elements.append(Spacer(1, 20))
        elements.append(table)
        doc.build(elements)

        buffer.seek(0)
        pdf_data = buffer.read()
        attachment = self.env["ir.attachment"].create(
            {
                "name": f"Sales Summary Report {self.salesperson_id.name} - {self.start_date} - {self.end_date}.pdf",
                "type": "binary",
                "datas": base64.b64encode(pdf_data),
                "mimetype": "application/pdf",
            }
        )

        return {
            "type": "ir.actions.act_url",
            "url": f"/web/content/{attachment.id}?download=true",
            "target": "new",
        }
