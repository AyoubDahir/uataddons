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

    # def generate_pdf_report(self):
    #     company = self.env.company
    #     buffer = io.BytesIO()
    #     doc = SimpleDocTemplate(
    #         buffer,
    #         pagesize=landscape(letter),
    #         rightMargin=30,
    #         leftMargin=30,
    #         topMargin=40,
    #         bottomMargin=30,
    #     )
    #     elements = []

    #     styles = getSampleStyleSheet()
    #     header_style = ParagraphStyle(
    #         name="Header",
    #         parent=styles["Title"],
    #         fontSize=18,
    #         textColor=colors.HexColor("#B6862D"),
    #         alignment=1,
    #     )
    #     subtitle_style = ParagraphStyle(
    #         name="Subtitle", parent=styles["Normal"], fontSize=12, alignment=1
    #     )
    #     left_align_style = ParagraphStyle(
    #         name="LeftAlign", parent=styles["Normal"], fontSize=12, alignment=0
    #     )

    #     logo = (
    #         Image(io.BytesIO(base64.b64decode(company.logo)), width=120, height=60)
    #         if company.logo
    #         else Paragraph("<b>No Logo Available</b>", header_style)
    #     )
    #     elements += [
    #         logo,
    #         Spacer(1, 12),
    #         Paragraph(f"<b>{company.name.upper()}</b>", header_style),
    #         Spacer(1, 6),
    #         Paragraph(
    #             f"{company.partner_id.city or ''}, {company.partner_id.country_id.name or ''}<br/>"
    #             f"Phone: {company.partner_id.phone or 'N/A'}<br/>"
    #             f"Email: {company.partner_id.email or 'N/A'}<br/>"
    #             f"Web: {company.website or 'N/A'}",
    #             subtitle_style,
    #         ),
    #         Spacer(1, 20),
    #         Paragraph(
    #             f"<b>Date from:</b> {self.start_date.strftime('%d/%m/%Y')}<br/>"
    #             f"<b>Date to:</b> {self.end_date.strftime('%d/%m/%Y')}",
    #             left_align_style,
    #         ),
    #         Spacer(1, 12),
    #         Paragraph(
    #             f"<b>Sales Person Name:</b> {self.salesperson_id.name}",
    #             left_align_style,
    #         ),
    #         Spacer(1, 12),
    #     ]

    #     # -------------------------
    #     # Opening balance from opening-balance receipt (if any)
    #     # -------------------------
    #     self.env.cr.execute(
    #         """
    #         SELECT remaining_amount
    #         FROM idil_sales_receipt
    #         WHERE salesperson_id = %s
    #           AND sales_opening_balance_id IS NOT NULL
    #         ORDER BY id ASC
    #         LIMIT 1
    #         """,
    #         (self.salesperson_id.id,),
    #     )
    #     opening_balance_result = self.env.cr.fetchone()
    #     opening_balance = opening_balance_result[0] if opening_balance_result else 0.0

    #     # -------------------------
    #     # PREVIOUS BALANCE before start_date
    #     # -------------------------
    #     # previous_sales_before
    #     self.env.cr.execute(
    #         """
    #         SELECT
    #             COALESCE(SUM(
    #                 (
    #                   (COALESCE(sol.quantity,0)
    #                   - COALESCE(sol.discount_quantity,0)
    #                   - COALESCE(srl.returned_quantity,0)) * COALESCE(sol.price_unit,0)
    #                 )
    #                 - (
    #                   (
    #                     (COALESCE(sol.quantity,0)
    #                     - COALESCE(sol.discount_quantity,0)
    #                     - COALESCE(srl.returned_quantity,0)) * COALESCE(sol.price_unit,0)
    #                   ) * COALESCE(p.commission,0)
    #                 )
    #             ), 0) AS sales_minus_commission_before
    #         FROM idil_salesperson_place_order spo
    #         INNER JOIN idil_sale_order so
    #                 ON so.sales_person_id = spo.salesperson_id
    #                AND so.salesperson_order_id = spo.id
    #         INNER JOIN idil_sale_order_line sol ON sol.order_id = so.id
    #         INNER JOIN my_product_product p    ON p.id = sol.product_id
    #         LEFT JOIN  idil_sale_return sr
    #                 ON sr.salesperson_id = spo.salesperson_id
    #                AND sr.sale_order_id  = so.id
    #         LEFT JOIN  idil_sale_return_line srl
    #                 ON srl.return_id = sr.id
    #                AND srl.product_id = p.id
    #         WHERE spo.state = 'confirmed'
    #           AND spo.salesperson_id = %s
    #           AND DATE(so.order_date) < %s
    #         """,
    #         (self.salesperson_id.id, self.start_date),
    #     )
    #     previous_sales_before = self.env.cr.fetchone()[0] or 0.0

    #     # previous_paid_before (by ACTUAL payment_date)
    #     self.env.cr.execute(
    #         """
    #         SELECT COALESCE(SUM(p.paid_amount), 0)
    #         FROM idil_sales_payment p
    #         INNER JOIN idil_sales_receipt r ON r.id = p.sales_receipt_id
    #         WHERE r.salesperson_id = %s
    #           AND DATE(p.payment_date) < %s
    #         """,
    #         (self.salesperson_id.id, self.start_date),
    #     )
    #     previous_paid_before = self.env.cr.fetchone()[0] or 0.0

    #     previous_balance = previous_sales_before - previous_paid_before

    #     # -------------------------
    #     # SALES inside [start_date, end_date]
    #     # -------------------------
    #     self.env.cr.execute(
    #         """
    #         SELECT
    #             DATE(so.order_date) AS order_day,
    #             p.name,
    #             sol.quantity,
    #             (((COALESCE(sol.quantity, 0)) - (COALESCE(srl.returned_quantity, 0))) * (p.discount / 100)) AS celis_tos,
    #             COALESCE(srl.returned_quantity, 0) AS celis,
    #             (COALESCE(sol.quantity, 0)
    #               - (((COALESCE(sol.quantity, 0)) - (COALESCE(srl.returned_quantity, 0))) * (p.discount / 100))
    #               - COALESCE(srl.returned_quantity, 0)) AS net,
    #             COALESCE(sol.price_unit, 0) AS qiime,
    #             ((COALESCE(sol.quantity, 0)
    #               - (((COALESCE(sol.quantity, 0)) - (COALESCE(srl.returned_quantity, 0))) * (p.discount / 100))
    #               - COALESCE(srl.returned_quantity, 0)) * COALESCE(sol.price_unit, 0)) AS lacag,
    #             (COALESCE(sol.commission, 0) * 100) AS per,
    #             (((COALESCE(sol.quantity, 0)
    #               - (((COALESCE(sol.quantity, 0)) - (COALESCE(srl.returned_quantity, 0))) * (p.discount / 100))
    #               - COALESCE(srl.returned_quantity, 0)) * COALESCE(sol.price_unit, 0)) * COALESCE(sol.commission, 0)) AS comm
    #         FROM idil_salesperson_place_order spo
    #         INNER JOIN idil_sale_order so
    #                 ON so.sales_person_id = spo.salesperson_id
    #                AND so.salesperson_order_id = spo.id
    #         INNER JOIN idil_sale_order_line sol ON sol.order_id = so.id
    #         INNER JOIN my_product_product p    ON sol.product_id = p.id
    #         LEFT JOIN  idil_sale_return sr
    #                 ON sr.salesperson_id = spo.salesperson_id
    #                AND sr.sale_order_id  = so.id
    #         LEFT JOIN  idil_sale_return_line srl
    #                 ON srl.return_id = sr.id
    #                AND srl.product_id = p.id
    #         WHERE spo.state = 'confirmed'
    #           AND spo.salesperson_id = %s
    #           AND DATE(so.order_date) BETWEEN %s AND %s
    #         ORDER BY so.id, sol.id
    #         """,
    #         (self.salesperson_id.id, self.start_date, self.end_date),
    #     )
    #     sales_rows = self.env.cr.fetchall()
    #     sales_by_day = defaultdict(list)
    #     for r in sales_rows:
    #         order_day = r[0]
    #         sales_by_day[order_day].append(r)

    #     # -------------------------
    #     # PAYMENTS inside [start_date, end_date] by ACTUAL payment_date
    #     # -------------------------
    #     self.env.cr.execute(
    #         """
    #         SELECT DATE(p.payment_date) AS paid_day, SUM(COALESCE(p.paid_amount,0)) AS total_paid
    #         FROM idil_sales_payment p
    #         INNER JOIN idil_sales_receipt r ON r.id = p.sales_receipt_id
    #         WHERE r.salesperson_id = %s
    #           AND DATE(p.payment_date) BETWEEN %s AND %s
    #         GROUP BY DATE(p.payment_date)
    #         """,
    #         (self.salesperson_id.id, self.start_date, self.end_date),
    #     )
    #     paid_by_day = defaultdict(float)
    #     for d, amt in self.env.cr.fetchall() or []:
    #         paid_by_day[d] = float(amt or 0.0)

    #     # Union of days that have sales or payments
    #     all_days = sorted(set(sales_by_day.keys()) | set(paid_by_day.keys()))

    #     # -------------------------
    #     # Build table with running Outstanding + daily & cumulative Lacag/Commission
    #     # -------------------------
    #     headers = [
    #         "Date",
    #         "Product",
    #         "Cadad",
    #         "Celis Tos",
    #         "Celis",
    #         "Net",
    #         "Qiime",
    #         "Lacag",
    #         "Per %",
    #         "Commission",
    #         "Balance",
    #     ]
    #     data = [headers]

    #     total_lacag = total_commission = total_paid = total_balance = 0.0
    #     highlight_rows, merged_rows = [], []

    #     # Starting outstanding at beginning of the range
    #     cumulative_outstanding = opening_balance + previous_balance

    #     # NEW: running totals to show on the Outstanding line
    #     running_lacag = 0.0
    #     running_commission = 0.0

    #     for day in all_days:
    #         daily_rows = sales_by_day.get(day, [])
    #         subtotal_lacag = subtotal_commission = subtotal_balance = 0.0

    #         for r in daily_rows:
    #             # r: 0 day, 1 product, 2 qty, 3 celis_tos, 4 celis, 5 net, 6 qiime, 7 lacag, 8 per, 9 comm
    #             product, cadad, celis_tos, celis, net, qiime, lacag, per, comm = r[1:10]
    #             balance = lacag - comm
    #             data.append(
    #                 [
    #                     day.strftime("%d/%m/%Y"),
    #                     product,
    #                     f"{cadad:.2f}",
    #                     f"{celis_tos:.2f}",
    #                     f"{celis:.2f}",
    #                     f"{net:.2f}",
    #                     f"{qiime:,.2f}",
    #                     f"{lacag:,.2f}",
    #                     f"{per:.2f}%",
    #                     f"{comm:,.2f}",
    #                     f"{balance:,.2f}",
    #                 ]
    #             )
    #             subtotal_lacag += lacag
    #             subtotal_commission += comm
    #             subtotal_balance += balance

    #         paid_today = paid_by_day.get(day, 0.0)
    #         day_total = subtotal_balance - paid_today

    #         # --- Subtotal row: show today's Lacag & Commission totals too
    #         row = [""] * 11
    #         row[0] = f"Subtotal {day.strftime('%d/%m/%Y')}"
    #         row[7] = f"{subtotal_lacag:,.2f}"  # Lacag (col 8)
    #         row[9] = f"{subtotal_commission:,.2f}"  # Commission (col 10)
    #         row[-1] = f"{subtotal_balance:,.2f}"  # Balance
    #         data.append(row)
    #         idx = len(data) - 1
    #         highlight_rows.append(idx)
    #         merged_rows.append(idx)

    #         # --- Paid row (balance-only)
    #         row = [""] * 11
    #         row[0] = f"Paid {day.strftime('%d/%m/%Y')}"
    #         row[-1] = f"{paid_today:,.2f}"
    #         data.append(row)
    #         idx = len(data) - 1
    #         highlight_rows.append(idx)
    #         merged_rows.append(idx)

    #         # --- Day Total row (balance-only)
    #         row = [""] * 11
    #         row[0] = f"Day Total {day.strftime('%d/%m/%Y')}"
    #         row[-1] = f"{day_total:,.2f}"
    #         data.append(row)
    #         idx = len(data) - 1
    #         highlight_rows.append(idx)
    #         merged_rows.append(idx)

    #         # Running outstanding since beginning up to this day
    #         cumulative_outstanding += day_total

    #         # Update running Lacag/Commission to date for the Outstanding line
    #         running_lacag += subtotal_lacag
    #         running_commission += subtotal_commission

    #         # --- Outstanding (to date) row with cumulative Lacag/Commission
    #         row = [""] * 11
    #         row[0] = f"Outstanding (to date) {day.strftime('%d/%m/%Y')}"
    #         row[7] = f"{running_lacag:,.2f}"  # cumulative Lacag
    #         row[9] = f"{running_commission:,.2f}"  # cumulative Commission
    #         row[-1] = (
    #             f"{cumulative_outstanding:,.2f}"  # cumulative Balance (outstanding)
    #         )
    #         data.append(row)
    #         idx = len(data) - 1
    #         highlight_rows.append(idx)
    #         merged_rows.append(idx)

    #         total_lacag += subtotal_lacag
    #         total_commission += subtotal_commission
    #         total_paid += paid_today
    #         total_balance += day_total

    #     # GRAND TOTAL
    #     data.append(
    #         [
    #             "GRAND TOTAL",
    #             "",
    #             "",
    #             "",
    #             "",
    #             "",
    #             "",
    #             f"{total_lacag:,.2f}",
    #             "",
    #             f"{total_commission:,.2f}",
    #             f"{total_balance:,.2f}",
    #         ]
    #     )
    #     highlight_rows.append(len(data) - 1)
    #     merged_rows.append(len(data) - 1)

    #     # Divider
    #     data.append(["", "", "", "", "", "", "", "", "", "", "--------------------"])
    #     highlight_rows.append(len(data) - 1)
    #     merged_rows.append(len(data) - 1)

    #     # Summary rows after the table
    #     data.append(
    #         [
    #             "OPENING BALANCE",
    #             "",
    #             "",
    #             "",
    #             "",
    #             "",
    #             "",
    #             "",
    #             "",
    #             "",
    #             f"{opening_balance:,.2f}",
    #         ]
    #     )
    #     highlight_rows.append(len(data) - 1)
    #     merged_rows.append(len(data) - 1)

    #     data.append(
    #         [
    #             "PREVIOUS BALANCE",
    #             "",
    #             "",
    #             "",
    #             "",
    #             "",
    #             "",
    #             "",
    #             "",
    #             "",
    #             f"{previous_balance:,.2f}",
    #         ]
    #     )
    #     highlight_rows.append(len(data) - 1)
    #     merged_rows.append(len(data) - 1)

    #     data.append(
    #         ["TOTAL PAID:", "", "", "", "", "", "", "", "", "", f"{total_paid:,.2f}"]
    #     )
    #     highlight_rows.append(len(data) - 1)
    #     merged_rows.append(len(data) - 1)

    #     final_balance_amount = opening_balance + previous_balance + total_balance
    #     data.append(
    #         [
    #             "FINAL BALANCE",
    #             "",
    #             "",
    #             "",
    #             "",
    #             "",
    #             "",
    #             "",
    #             "",
    #             "",
    #             f"{final_balance_amount:,.2f}",
    #         ]
    #     )
    #     final_balance_index = len(data) - 1
    #     highlight_rows.append(final_balance_index)
    #     merged_rows.append(final_balance_index)

    #     table = Table(data, colWidths=[70, 140, 50, 60, 50, 40, 60, 80, 50, 70, 100])
    #     style = TableStyle(
    #         [
    #             ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#B6862D")),
    #             ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
    #             ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
    #             ("ALIGN", (0, 0), (-1, -1), "CENTER"),
    #             ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
    #         ]
    #     )
    #     for row_idx in highlight_rows:
    #         style.add("FONTNAME", (0, row_idx), (-1, row_idx), "Helvetica-Bold")
    #     for row_idx in merged_rows:
    #         style.add("SPAN", (0, row_idx), (2, row_idx))
    #     style.add(
    #         "BACKGROUND",
    #         (0, final_balance_index),
    #         (-1, final_balance_index),
    #         colors.HexColor("#FFD700"),
    #     )
    #     table.setStyle(style)

    #     elements.append(Spacer(1, 20))
    #     elements.append(table)
    #     doc.build(elements)
    #     buffer.seek(0)
    #     pdf_data = buffer.read()

    #     attachment = self.env["ir.attachment"].create(
    #         {
    #             "name": f"Sales Summary Report {self.salesperson_id.name} - {self.start_date} - {self.end_date}.pdf",
    #             "type": "binary",
    #             "datas": base64.b64encode(pdf_data),
    #             "mimetype": "application/pdf",
    #         }
    #     )
    #     return {
    #         "type": "ir.actions.act_url",
    #         "url": f"/web/content/{attachment.id}?download=true",
    #         "target": "new",
    #     }

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

        # ------------------------------------------------------
        # HEADER
        # ------------------------------------------------------
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

        # ------------------------------------------------------
        # OPENING BALANCE from idil.sales.opening.balance.line
        # (static amount – does NOT disappear when paid)
        # ------------------------------------------------------
        self.env.cr.execute(
            """
            SELECT l.amount, ob.date
            FROM idil_sales_opening_balance_line l
            JOIN idil_sales_opening_balance ob
            ON ob.id = l.opening_balance_id
            WHERE ob.state != 'cancel'
            AND l.sales_person_id = %s
            ORDER BY ob.date ASC
            LIMIT 1
            """,
            (self.salesperson_id.id,),
        )
        ob_row = self.env.cr.fetchone()
        opening_balance = float(ob_row[0]) if ob_row else 0.0
        opening_date = ob_row[1] if ob_row else None  # date or None

        # ------------------------------------------------------
        # PREVIOUS BALANCE (sales before start_date)
        # ------------------------------------------------------
        # 1) previous sales – commission (before start_date)
        self.env.cr.execute(
            """
            SELECT
                COALESCE(SUM(
                    (
                    (COALESCE(sol.quantity,0)
                    - COALESCE(sol.discount_quantity,0)
                    - COALESCE(srl.returned_quantity,0)) * COALESCE(sol.price_unit,0)
                    )
                    -
                    (
                    (
                        (COALESCE(sol.quantity,0)
                        - COALESCE(sol.discount_quantity,0)
                        - COALESCE(srl.returned_quantity,0)) * COALESCE(sol.price_unit,0)
                    ) * COALESCE(p.commission,0)
                    )
                ), 0)
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
            """,
            (self.salesperson_id.id, self.start_date),
        )
        previous_sales_before = float(self.env.cr.fetchone()[0] or 0.0)

        # 2) previous payments (ALL receipts, including opening, before start_date)
        self.env.cr.execute(
            """
            SELECT COALESCE(SUM(p.paid_amount), 0)
            FROM idil_sales_payment p
            INNER JOIN idil_sales_receipt r ON r.id = p.sales_receipt_id
            WHERE r.salesperson_id = %s
            AND DATE(p.payment_date) < %s
            """,
            (self.salesperson_id.id, self.start_date),
        )
        previous_paid_before = float(self.env.cr.fetchone()[0] or 0.0)

        previous_balance = previous_sales_before - previous_paid_before

        # ------------------------------------------------------
        # Decide how to use opening balance in calculation:
        # - Always show full opening_balance amount as first row.
        # - If its date is BEFORE start_date, add it into previous_balance
        #   (to avoid double counting in final formula).
        # ------------------------------------------------------
        opening_for_calc = opening_balance
        if opening_date and opening_date < self.start_date:
            previous_balance += opening_balance
            opening_for_calc = 0.0

        # ------------------------------------------------------
        # SALES inside [start_date, end_date]
        # ------------------------------------------------------
        self.env.cr.execute(
            """
            SELECT
                DATE(so.order_date) AS order_day,
                p.name,
                sol.quantity,
                (((COALESCE(sol.quantity, 0))
                - (COALESCE(srl.returned_quantity, 0))) * (p.discount / 100)) AS celis_tos,
                COALESCE(srl.returned_quantity, 0) AS celis,
                (COALESCE(sol.quantity, 0)
                - (((COALESCE(sol.quantity, 0))
                    - (COALESCE(srl.returned_quantity, 0))) * (p.discount / 100))
                - COALESCE(srl.returned_quantity, 0)) AS net,
                COALESCE(sol.price_unit, 0) AS qiime,
                ((COALESCE(sol.quantity, 0)
                - (((COALESCE(sol.quantity, 0))
                    - (COALESCE(srl.returned_quantity, 0))) * (p.discount / 100))
                - COALESCE(srl.returned_quantity, 0)) * COALESCE(sol.price_unit, 0)) AS lacag,
                (COALESCE(sol.commission, 0) * 100) AS per,
                (((COALESCE(sol.quantity, 0)
                - (((COALESCE(sol.quantity, 0))
                    - (COALESCE(srl.returned_quantity, 0))) * (p.discount / 100))
                - COALESCE(srl.returned_quantity, 0))
                * COALESCE(sol.price_unit, 0)) * COALESCE(sol.commission, 0)) AS comm
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
        sales_rows = self.env.cr.fetchall()
        sales_by_day = defaultdict(list)
        for row in sales_rows:
            order_day = row[0]
            sales_by_day[order_day].append(row)

        # ------------------------------------------------------
        # PAYMENTS inside [start_date, end_date]
        # (all receipts, including opening-balance receipts)
        # ------------------------------------------------------
        self.env.cr.execute(
            """
            SELECT DATE(p.payment_date) AS paid_day,
                SUM(COALESCE(p.paid_amount,0)) AS total_paid
            FROM idil_sales_payment p
            INNER JOIN idil_sales_receipt r ON r.id = p.sales_receipt_id
            WHERE r.salesperson_id = %s
            AND DATE(p.payment_date) BETWEEN %s AND %s
            GROUP BY DATE(p.payment_date)
            """,
            (self.salesperson_id.id, self.start_date, self.end_date),
        )
        paid_by_day = defaultdict(float)
        for d, amt in self.env.cr.fetchall() or []:
            paid_by_day[d] = float(amt or 0.0)

        all_days = sorted(set(sales_by_day.keys()) | set(paid_by_day.keys()))

        # ------------------------------------------------------
        # BUILD TABLE
        # ------------------------------------------------------
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
        highlight_rows = []
        merged_rows = []

        # 1) OPENING BALANCE row – always show if not zero
        if opening_balance:
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

        # 2) PREVIOUS BALANCE row – if any
        if previous_balance:
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

        # starting outstanding at beginning of range
        cumulative_outstanding = opening_for_calc + previous_balance

        running_lacag = 0.0
        running_commission = 0.0
        total_period_lacag = 0.0
        total_period_commission = 0.0
        total_period_due = 0.0  # sales due in period (without OB/previous)
        total_paid = 0.0

        for day in all_days:
            daily_sales = sales_by_day.get(day, [])
            subtotal_lacag = 0.0
            subtotal_commission = 0.0
            subtotal_balance = 0.0

            # detail rows
            for s in daily_sales:
                (
                    order_day,
                    product,
                    qty,
                    celis_tos,
                    celis,
                    net,
                    qiime,
                    lacag,
                    per,
                    comm,
                ) = s
                balance = lacag - comm

                data.append(
                    [
                        order_day.strftime("%d/%m/%Y"),
                        product,
                        f"{qty:.2f}",
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

            # Day movement (we don't allow negative day due)
            day_total = max(subtotal_balance - paid_today, 0.0)

            # SUBTOTAL row
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

            # PAID row
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

            # DAY TOTAL row
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

            # update cumulative outstanding (cannot go below zero)
            cumulative_outstanding = max(
                cumulative_outstanding + subtotal_balance - paid_today, 0.0
            )

            running_lacag += subtotal_lacag
            running_commission += subtotal_commission

            # OUTSTANDING TO DATE row
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

            # totals for the period (sales & payments only)
            total_period_lacag += subtotal_lacag
            total_period_commission += subtotal_commission
            total_period_due += subtotal_balance
            grand_total_before_paid = (
                opening_for_calc + previous_balance + total_period_due
            )

            total_paid += paid_today

        # ------------------------------------------------------
        # GRAND TOTAL (period sales only)
        # ------------------------------------------------------
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
                # f"{total_period_due:,.2f}",
                f"{grand_total_before_paid:,.2f}",
            ]
        )
        highlight_rows.append(len(data) - 1)
        merged_rows.append(len(data) - 1)

        # Divider
        data.append(["", "", "", "", "", "", "", "", "", "", "--------------------"])
        highlight_rows.append(len(data) - 1)
        merged_rows.append(len(data) - 1)

        # TOTAL PAID (in period)
        data.append(
            [
                "TOTAL PAID",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                f"{total_paid:,.2f}",
            ]
        )
        highlight_rows.append(len(data) - 1)
        merged_rows.append(len(data) - 1)

        # FINAL BALANCE = Opening (for calc) + Previous + Period Due − Paid
        final_balance = (
            opening_for_calc + previous_balance + total_period_due - total_paid
        )
        if final_balance < 0:
            final_balance = 0.0

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

        # ------------------------------------------------------
        # RENDER TABLE
        # ------------------------------------------------------
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
