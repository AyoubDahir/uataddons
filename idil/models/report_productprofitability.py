from odoo import models, fields
import base64
import io
from decimal import Decimal
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


class ManufacturingReportWizard(models.TransientModel):
    _name = "idil.manufacturing.report"
    _description = "Manufacturing Summary Report"

    start_date = fields.Date(string="Start Date", required=True)
    end_date = fields.Date(string="End Date", required=True)
    company_id = fields.Many2one(
        "res.company",
        string="Company",
        required=True,
        default=lambda self: self.env.company,
    )

    def generate_pdf_report(self):
        company = self.company_id
        start_date = self.start_date
        end_date = self.end_date

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

        # Logo
        if company.logo:
            try:
                elements.append(
                    Image(
                        io.BytesIO(base64.b64decode(company.logo)), width=80, height=80
                    )
                )
            except Exception:
                elements.append(Paragraph("<b>No Logo Available</b>", header_style))
        else:
            elements.append(Paragraph("<b>No Logo Available</b>", header_style))

        elements += [
            Paragraph(f"<b>{(company.name or '').upper()}</b>", header_style),
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
                f"<b>Report Period:</b> {start_date.strftime('%d/%m/%Y')} - {end_date.strftime('%d/%m/%Y')}",
                left_align_style,
            ),
            Spacer(1, 12),
        ]

        # ========================= SQL =========================
        sql = """
        WITH mo AS (
            SELECT
                mo.product_id,
                SUM(CASE WHEN mo.scheduled_start_date < %(start)s THEN mo.product_qty ELSE 0 END)::numeric AS produced_before,
                SUM(CASE WHEN mo.scheduled_start_date BETWEEN %(start)s AND %(end)s THEN mo.product_qty ELSE 0 END)::numeric AS prod_qty,
                SUM(CASE WHEN mo.scheduled_start_date <= %(end)s THEN mo.product_qty ELSE 0 END)::numeric AS produced_to_end,
                SUM(CASE WHEN mo.scheduled_start_date <= %(end)s THEN mo.product_cost ELSE 0 END)::numeric AS total_cost
            FROM idil_manufacturing_order mo
            WHERE mo.status = 'done'
            AND mo.company_id = %(company_id)s
            AND mo.scheduled_start_date <= %(end)s
            GROUP BY mo.product_id
        ),
        pa AS (
            SELECT
                pa.product_id,
                SUM(CASE WHEN pa.adjustment_date < %(start)s THEN pa.new_quantity ELSE 0 END)::numeric AS disposed_before,
                SUM(CASE WHEN pa.adjustment_date BETWEEN %(start)s AND %(end)s THEN pa.new_quantity ELSE 0 END)::numeric AS disposed_in_period,
                SUM(CASE WHEN pa.adjustment_date <= %(end)s THEN pa.new_quantity ELSE 0 END)::numeric AS disposed_to_end
            FROM idil_product_adjustment pa
            GROUP BY pa.product_id
        ),
        sales AS (
            SELECT
                sol.product_id,
                SUM(CASE WHEN so.order_date < %(start)s THEN sol.quantity ELSE 0 END)::numeric AS sold_before,
                SUM(CASE WHEN so.order_date BETWEEN %(start)s AND %(end)s THEN sol.quantity ELSE 0 END)::numeric AS sold_qty,
                AVG(sol.price_unit)::numeric AS sales_price,
                SUM(CASE WHEN so.order_date BETWEEN %(start)s AND %(end)s
                        THEN (sol.quantity::numeric * sol.price_unit::numeric)
                        ELSE 0::numeric END)::numeric AS total_sales
            FROM idil_sale_order_line sol
            JOIN idil_sale_order so ON sol.order_id = so.id
            GROUP BY sol.product_id
        )
        SELECT
            p.name AS product,

            -- Prev Qty = produced_before - disposed_before - sold_before
            (COALESCE(mo.produced_before, 0::numeric)
            - COALESCE(pa.disposed_before, 0::numeric)
            - COALESCE(sales.sold_before, 0::numeric)) AS prev_qty,

            COALESCE(mo.prod_qty, 0::numeric) AS prod_qty,

            -- Total Qty = Prev + Prod (up to now)
            ((COALESCE(mo.produced_before, 0::numeric)
            - COALESCE(pa.disposed_before, 0::numeric)
            - COALESCE(sales.sold_before, 0::numeric))
            + COALESCE(mo.prod_qty, 0::numeric)) AS total_qty,

            CASE
            WHEN NULLIF(COALESCE(mo.produced_to_end, 0::numeric), 0::numeric) IS NOT NULL
            THEN ROUND((COALESCE(mo.total_cost, 0::numeric) / NULLIF(mo.produced_to_end, 0::numeric)), 3)
            ELSE 0::numeric
            END AS unit_cost,

            COALESCE(mo.total_cost, 0::numeric) AS total_cost,

            COALESCE(pa.disposed_in_period, 0::numeric) AS disposed_in_period,

            (COALESCE(mo.produced_to_end, 0::numeric) - COALESCE(pa.disposed_to_end, 0::numeric)) AS ready_qty,

            COALESCE(sales.sold_qty, 0::numeric) AS sold_qty,

            CASE
            WHEN NULLIF(COALESCE(mo.produced_to_end, 0::numeric), 0::numeric) IS NOT NULL
            THEN ROUND(
                (COALESCE(mo.total_cost, 0::numeric) / NULLIF(mo.produced_to_end, 0::numeric))
                * COALESCE(sales.sold_qty, 0::numeric)
                , 2)
            ELSE 0::numeric
            END AS sold_cost,

            COALESCE(sales.sales_price, 0::numeric) AS sales_price,
            COALESCE(sales.total_sales, 0::numeric) AS total_sales,

            (COALESCE(sales.total_sales, 0::numeric)
            - CASE
                WHEN NULLIF(COALESCE(mo.produced_to_end, 0::numeric), 0::numeric) IS NOT NULL
                THEN ROUND(
                    (COALESCE(mo.total_cost, 0::numeric) / NULLIF(mo.produced_to_end, 0::numeric))
                    * COALESCE(sales.sold_qty, 0::numeric)
                    , 2)
                ELSE 0::numeric
                END
            ) AS net_profit

        FROM my_product_product p
        LEFT JOIN mo ON mo.product_id = p.id
        LEFT JOIN pa ON pa.product_id = p.id
        LEFT JOIN sales ON sales.product_id = p.id
        ORDER BY p.name;
                """

        params = {
            "start": start_date,
            "end": end_date,
            "company_id": company.id,
        }

        self.env.cr.execute(sql, params)
        rows = self.env.cr.fetchall()

        # ===================== TABLE OUTPUT =====================
        headers = [
            "Product",
            "Prev Qty",
            "Prod Qty",
            "Total Qty",
            "Unit Cost",
            "Total Cost",
            "Disposed",
            "Ready Qty",
            "Sold Qty",
            "Sold Cost",
            "Sales Price",
            "Total Sales",
            "Net Profit",
        ]
        data = [headers]

        for row in rows:
            formatted = []
            for col in row:
                if isinstance(col, (int, float, Decimal)):
                    formatted.append(f"{col:,.2f}")
                else:
                    formatted.append(col or "")
            data.append(formatted)

        col_widths = [140, 80, 80, 90, 80, 90, 80, 90, 80, 90, 80, 90, 90]
        table = Table(data, colWidths=col_widths)
        table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#B6862D")),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                    ("ALIGN", (1, 1), (-1, -1), "RIGHT"),
                    ("ALIGN", (0, 0), (0, -1), "LEFT"),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ]
            )
        )

        elements.append(Spacer(1, 20))
        elements.append(table)
        doc.build(elements)
        buffer.seek(0)
        pdf_data = buffer.read()

        attachment = self.env["ir.attachment"].create(
            {
                "name": f"manufacturing_report_{start_date}_{end_date}.pdf",
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
