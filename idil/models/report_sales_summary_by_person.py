from odoo import models, fields
import base64
import io
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

    def generate_pdf_report(self):
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
            Spacer(1, 20),
            Paragraph(
                f"<b>Date from:</b> {self.start_date.strftime('%d/%m/%Y')}<br/>"
                f"<b>Date to:</b> {self.end_date.strftime('%d/%m/%Y')}",
                left_align_style,
            ),
            Spacer(1, 12),
            Paragraph(
                f"<b>Sales Person Name:</b> {self.salesperson_id.name}",
                left_align_style,
            ),
            Spacer(1, 12),
        ]

        # -------------------------
        # Opening balance (from first opening balance receipt, if any)
        # -------------------------
        self.env.cr.execute(
            """
            SELECT remaining_amount
            FROM idil_sales_receipt
            WHERE salesperson_id = %s
              AND sales_opening_balance_id IS NOT NULL
            ORDER BY id ASC
            LIMIT 1
            """,
            (self.salesperson_id.id,),
        )
        opening_balance_result = self.env.cr.fetchone()
        opening_balance = opening_balance_result[0] if opening_balance_result else 0.0

        # -------------------------
        # Previous balance (before start_date)
        # -------------------------
        self.env.cr.execute(
            """
            SELECT
                SUM( ((COALESCE(sol.quantity, 0) - COALESCE(sol.discount_quantity, 0) - COALESCE(srl.returned_quantity, 0)) * COALESCE(sol.price_unit, 0))
                    -(((COALESCE(sol.quantity, 0) - COALESCE(sol.discount_quantity, 0) - COALESCE(srl.returned_quantity, 0)) * COALESCE(sol.price_unit, 0)) * COALESCE(p.commission, 0))
                ) AS total_sales_minus_commission,
                SUM(COALESCE(src.paid_amount, 0)) AS total_paid_before
            FROM public.idil_sales_sales_personnel sp
            INNER JOIN public.idil_salesperson_place_order spo ON sp.id = spo.salesperson_id
            INNER JOIN idil_sale_order so ON so.sales_person_id = spo.salesperson_id AND so.salesperson_order_id = spo.id
            INNER JOIN idil_sale_order_line sol ON sol.order_id = so.id
            INNER JOIN my_product_product p ON sol.product_id = p.id
            LEFT JOIN public.idil_sale_return sr ON sp.id = sr.salesperson_id AND so.id = sr.sale_order_id
            LEFT JOIN public.idil_sale_return_line srl ON sr.id = srl.return_id AND p.id = srl.product_id
            LEFT JOIN idil_sales_receipt src ON so.id = src.sales_order_id AND sp.id = src.salesperson_id
            WHERE spo.state = 'confirmed'
              AND sp.id = %s
              AND DATE(so.order_date) < %s
            """,
            (self.salesperson_id.id, self.start_date),
        )
        result = self.env.cr.fetchone()
        previous_net = result[0] or 0.0
        previous_paid = result[1] or 0.0
        previous_balance = previous_net - previous_paid

        # -------------------------
        # Main data query (add so.id to identify orders of each day)
        # -------------------------
        self.env.cr.execute(
            """
            SELECT
                DATE(so.order_date) AS order_day,
                so.id               AS order_id,
                p.name,
                sol.quantity,
                (((COALESCE(sol.quantity, 0)) - (COALESCE(srl.returned_quantity, 0))) * (p.discount / 100)) AS celis_tos,
                COALESCE(srl.returned_quantity, 0) AS celis,
                (COALESCE(sol.quantity, 0)
                  - (((COALESCE(sol.quantity, 0)) - (COALESCE(srl.returned_quantity, 0))) * (p.discount / 100))
                  - COALESCE(srl.returned_quantity, 0)) AS net,
                COALESCE(sol.price_unit, 0) AS qiime,
                ((COALESCE(sol.quantity, 0)
                  - (((COALESCE(sol.quantity, 0)) - (COALESCE(srl.returned_quantity, 0))) * (p.discount / 100))
                  - COALESCE(srl.returned_quantity, 0)) * COALESCE(sol.price_unit, 0)) AS lacag,
                (COALESCE(sol.commission, 0) * 100) AS per,
                (((COALESCE(sol.quantity, 0)
                  - (((COALESCE(sol.quantity, 0)) - (COALESCE(srl.returned_quantity, 0))) * (p.discount / 100))
                  - COALESCE(srl.returned_quantity, 0)) * COALESCE(sol.price_unit, 0)) * COALESCE(sol.commission, 0)) AS comm,
                DATE(src.receipt_date) AS receipt_day,
                COALESCE(src.paid_amount, 0) AS paid_amount,
                src.id AS receipt_id
            FROM public.idil_sales_sales_personnel sp
            INNER JOIN public.idil_salesperson_place_order spo
                ON sp.id = spo.salesperson_id
            INNER JOIN idil_sale_order so
                ON so.sales_person_id = spo.salesperson_id
               AND so.salesperson_order_id = spo.id
            INNER JOIN idil_sale_order_line sol ON sol.order_id = so.id
            INNER JOIN my_product_product p ON sol.product_id = p.id
            LEFT JOIN public.idil_sale_return sr
                ON sp.id = sr.salesperson_id
               AND so.id = sr.sale_order_id
            LEFT JOIN public.idil_sale_return_line srl
                ON sr.id = srl.return_id
               AND p.id = srl.product_id
            LEFT JOIN idil_sales_receipt src
                ON so.id = src.sales_order_id
               AND sp.id = src.salesperson_id
            WHERE spo.state = 'confirmed'
              AND sp.id = %s
              AND DATE(so.order_date) BETWEEN %s AND %s
            ORDER BY spo.id, so.id, sol.id;
            """,
            (self.salesperson_id.id, self.start_date, self.end_date),
        )
        rows = self.env.cr.fetchall()

        # Group lines by order_day and collect order_ids per day
        grouped = defaultdict(list)
        orders_by_day = defaultdict(set)
        for r in rows:
            order_day = r[0]
            order_id = r[1]
            grouped[order_day].append(r)
            if order_id:
                orders_by_day[order_day].add(order_id)

        # -------------------------
        # Compute paid_by_day = payments against orders placed that day (any receipt date)
        # -------------------------
        paid_by_day = defaultdict(float)
        for order_day, order_ids in orders_by_day.items():
            if not order_ids:
                continue
            # Use IN %s with a tuple to avoid psycopg2 "list" issues
            self.env.cr.execute(
                """
                SELECT SUM(COALESCE(paid_amount, 0))
                FROM idil_sales_receipt
                WHERE salesperson_id = %s
                  AND sales_order_id IN %s
                """,
                (self.salesperson_id.id, tuple(order_ids)),
            )
            paid_sum = self.env.cr.fetchone()[0] or 0.0
            paid_by_day[order_day] = float(paid_sum)

        # -------------------------
        # Build report table
        # -------------------------
        headers = [
            "Date",  # 0
            "Product",  # 1
            "Cadad",  # 2
            "Celis Tos",  # 3
            "Celis",  # 4
            "Net",  # 5
            "Qiime",  # 6
            "Lacag",  # 7
            "Per %",  # 8
            "Commission",  # 9
            "Balance",  # 10
        ]
        data = [headers]

        total_lacag = 0.0
        total_commission = 0.0
        total_paid = 0.0
        total_balance = 0.0
        highlight_rows = []
        merged_rows = []

        # Iterate by day
        for day in sorted(grouped.keys()):
            daily_rows = grouped[day]
            subtotal_lacag = 0.0
            subtotal_commission = 0.0
            subtotal_balance = 0.0

            for r in daily_rows:
                # Unpack by column index (see SELECT list above)
                # 0: order_day, 1: order_id,
                product = r[2]
                cadad = r[3]
                celis_tos = r[4]
                celis = r[5]
                net = r[6]
                qiime = r[7]
                lacag = r[8]
                per = r[9]
                comm = r[10]
                # r[11] receipt_day, r[12] paid_amount, r[13] receipt_id (not used here)

                balance = lacag - comm

                data.append(
                    [
                        day.strftime("%d/%m/%Y"),
                        product,
                        f"{cadad:.2f}",
                        f"{celis_tos:.2f}",
                        f"{celis:.2f}",
                        f"{net:.2f}",
                        f"{qiime:,.2f}",
                        f"{lacag:,.2f}",
                        f"{per:.2f}%",
                        f"{comm:,.2f}",
                        f"{balance:,.2f}",
                    ]
                )
                subtotal_lacag += lacag
                subtotal_commission += comm
                subtotal_balance += balance

            paid_today = paid_by_day.get(day, 0.0)

            # Summary rows per day
            for label, value in [
                (f"Subtotal {day.strftime('%d/%m/%Y')}", f"{subtotal_balance:,.2f}"),
                (f"Paid {day.strftime('%d/%m/%Y')}", f"{paid_today:,.2f}"),
                (
                    f"Day Total {day.strftime('%d/%m/%Y')}",
                    f"{(subtotal_balance - paid_today):,.2f}",
                ),
            ]:
                row = [""] * 11
                row[0] = label
                row[-1] = value
                data.append(row)
                idx = len(data) - 1
                highlight_rows.append(idx)
                merged_rows.append(idx)

            total_lacag += subtotal_lacag
            total_commission += subtotal_commission
            total_paid += paid_today
            total_balance += subtotal_balance - paid_today

        # GRAND TOTAL row
        data.append(
            [
                "GRAND TOTAL",
                "",
                "",
                "",
                "",
                "",
                "",
                f"{total_lacag:,.2f}",
                "",
                f"{total_commission:,.2f}",
                f"{total_balance:,.2f}",
            ]
        )
        highlight_rows.append(len(data) - 1)
        merged_rows.append(len(data) - 1)

        # Divider
        data.append(["", "", "", "", "", "", "", "", "", "", "--------------------"])
        highlight_rows.append(len(data) - 1)
        merged_rows.append(len(data) - 1)

        # Opening balance row
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
                f"{opening_balance:,.2f}",
            ]
        )
        highlight_rows.append(len(data) - 1)
        merged_rows.append(len(data) - 1)

        # Previous balance row
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
                f"{previous_balance:,.2f}",
            ]
        )
        highlight_rows.append(len(data) - 1)
        merged_rows.append(len(data) - 1)

        # Total paid row
        data.append(
            ["TOTAL PAID:", "", "", "", "", "", "", "", "", "", f"{total_paid:,.2f}"]
        )
        highlight_rows.append(len(data) - 1)
        merged_rows.append(len(data) - 1)

        # Final balance
        final_balance_amount = opening_balance + previous_balance + total_balance
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
                f"{final_balance_amount:,.2f}",
            ]
        )
        final_balance_index = len(data) - 1
        highlight_rows.append(final_balance_index)
        merged_rows.append(final_balance_index)

        # Table styling
        table = Table(
            data,
            colWidths=[70, 140, 50, 60, 50, 40, 60, 80, 50, 70, 100],
        )
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
