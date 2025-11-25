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


class ProductProfitabilityReportWizard(models.TransientModel):
    _name = "idil.manufacturing.report"  # Keeping technical name to avoid migration issues, but logic is new
    _description = "Product Profitability Analysis Report"

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

        # Fix: Swap dates if start > end
        if start_date > end_date:
            start_date, end_date = end_date, start_date


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
            textColor=colors.HexColor("#2C3E50"),
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
                pass

        elements += [
            Paragraph(f"<b>{(company.name or '').upper()}</b>", header_style),
            Spacer(1, 6),
            Paragraph("<b>Product Profitability Analysis (USD)</b>", subtitle_style),
            Spacer(1, 20),
            Paragraph(
                f"<b>Report Period:</b> {start_date.strftime('%d/%m/%Y')} - {end_date.strftime('%d/%m/%Y')}",
                left_align_style,
            ),
            Spacer(1, 12),
        ]

        # ========================= SQL =========================
        # Logic:
        # 1. Get all confirmed sales in the period.
        # 2. Convert Revenue to USD using transaction exchange rate.
        # 3. Calculate Cost in USD (already in USD).
        # 4. Profit = Revenue (USD) - Cost (USD).
        sql = """
        SELECT
            p.name AS product_name,
            SUM(sol.quantity) AS sold_qty,
            AVG(sol.price_unit / NULLIF(so.rate, 0)) AS avg_price,
            SUM(sol.quantity * sol.price_unit / NULLIF(so.rate, 0)) AS total_revenue,
            p.cost AS unit_cost,
            SUM(sol.quantity * p.cost) AS total_cost,
            (SUM(sol.quantity * sol.price_unit / NULLIF(so.rate, 0)) - SUM(sol.quantity * p.cost)) AS net_profit,
            CASE 
                WHEN SUM(sol.quantity * sol.price_unit / NULLIF(so.rate, 0)) > 0 
                THEN ((SUM(sol.quantity * sol.price_unit / NULLIF(so.rate, 0)) - SUM(sol.quantity * p.cost)) / SUM(sol.quantity * sol.price_unit / NULLIF(so.rate, 0))) * 100 
                ELSE 0 
            END AS margin_percentage
        FROM idil_sale_order_line sol
        JOIN idil_sale_order so ON sol.order_id = so.id
        JOIN my_product_product p ON sol.product_id = p.id
        WHERE so.state = 'confirmed'
        AND so.order_date BETWEEN %(start)s AND %(end)s
        AND so.company_id = %(company_id)s
        GROUP BY p.name, p.cost
        ORDER BY net_profit DESC;
        """

        params = {
            "start": start_date,
            "end": end_date,
            "company_id": company.id,
        }

        import logging
        _logger = logging.getLogger(__name__)
        
        _logger.info(f"Generating Profitability Report: Start={start_date}, End={end_date}, Company={company.id}")

        self.env.cr.execute(sql, params)
        rows = self.env.cr.fetchall()
        
        _logger.info(f"Profitability Report Query returned {len(rows)} rows.")


        # ===================== TABLE OUTPUT =====================
        headers = [
            "Product",
            "Sold Qty",
            "Avg Price (USD)",
            "Revenue (USD)",
            "Unit Cost (USD)",
            "Total Cost (USD)",
            "Net Profit (USD)",
            "Margin %",
        ]
        data = [headers]

        total_revenue = 0
        total_cost = 0
        total_profit = 0

        for row in rows:
            # row: name, qty, avg_price, revenue, unit_cost, total_cost, profit, margin
            formatted = [
                row[0],  # Product
                f"{row[1]:,.2f}",  # Qty
                f"{row[2]:,.2f}",  # Avg Price
                f"{row[3]:,.2f}",  # Revenue
                f"{row[4]:,.2f}",  # Unit Cost
                f"{row[5]:,.2f}",  # Total Cost
                f"{row[6]:,.2f}",  # Profit
                f"{row[7]:,.1f}%",  # Margin
            ]
            data.append(formatted)
            
            total_revenue += row[3] or 0
            total_cost += row[5] or 0
            total_profit += row[6] or 0

        # Add Totals Row
        data.append([
            "TOTALS",
            "",
            "",
            f"{total_revenue:,.2f}",
            "",
            f"{total_cost:,.2f}",
            f"{total_profit:,.2f}",
            f"{(total_profit / total_revenue * 100) if total_revenue else 0:,.1f}%"
        ])

        col_widths = [160, 55, 75, 85, 75, 85, 85, 60]
        table = Table(data, colWidths=col_widths)
        
        # Style
        style = TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2C3E50")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
                ("ALIGN", (0, 0), (0, -1), "LEFT"),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, 0), 10),
                ("BOTTOMPADDING", (0, 0), (-1, 0), 12),
                ("BACKGROUND", (0, 1), (-1, -2), colors.HexColor("#F8F9F9")),
                ("GRID", (0, 0), (-1, -2), 0.5, colors.grey),
                # Totals Row Style
                ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#EAEDED")),
                ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
                ("TOPPADDING", (0, -1), (-1, -1), 12),
            ]
        )
        table.setStyle(style)

        elements.append(table)
        doc.build(elements)
        buffer.seek(0)
        pdf_data = buffer.read()

        attachment = self.env["ir.attachment"].create(
            {
                "name": f"profitability_report_{start_date}_{end_date}.pdf",
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
