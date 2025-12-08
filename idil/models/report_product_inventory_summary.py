# -*- coding: utf-8 -*-
from odoo import models, fields
import base64
import io
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
import logging

_logger = logging.getLogger(__name__)


class ProductInventorySummaryWizard(models.TransientModel):
    _name = "idil.product.inventory.summary.wizard"
    _description = "Product Inventory Summary Report"

    start_date = fields.Date(string="Start Date", required=True)
    end_date = fields.Date(string="End Date", required=True)
    company_id = fields.Many2one(
        "res.company",
        string="Company",
        required=True,
        default=lambda self: self.env.company,
    )
    product_id = fields.Many2one(
        "my_product.product",
        string="Product",
        help="Leave empty for all products",
    )

    def generate_pdf_report(self):
        """Generate Product Inventory Summary PDF Report"""
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
            rightMargin=20,
            leftMargin=20,
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
            name="LeftAlign", parent=styles["Normal"], fontSize=10, alignment=0
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

        # Company Info
        elements += [
            Paragraph(f"<b>{(company.name or '').upper()}</b>", header_style),
            Spacer(1, 4),
        ]

        # Address info
        address_parts = []
        if company.city:
            address_parts.append(company.city)
        if company.country_id:
            address_parts.append(company.country_id.name)
        if address_parts:
            elements.append(Paragraph(", ".join(address_parts), subtitle_style))

        if company.phone:
            elements.append(Paragraph(f"Phone: {company.phone}", subtitle_style))
        if company.email:
            elements.append(Paragraph(f"Email: {company.email}", subtitle_style))
        if company.website:
            elements.append(Paragraph(f"Web: {company.website}", subtitle_style))

        elements += [
            Spacer(1, 16),
            Paragraph(
                f"<b>Report Period:</b> {start_date.strftime('%d/%m/%Y')} - {end_date.strftime('%d/%m/%Y')}",
                left_align_style,
            ),
            Spacer(1, 12),
        ]

        # SQL Query for Product Inventory Summary
        # This query calculates:
        # - Produced Qty (from manufacturing orders)
        # - Total Qty (stock_quantity)
        # - Unit Cost and Total Cost
        # - Disposed (out movements with disposal type)
        # - Ready Qty (current stock)
        # - Sold Qty (from sales)
        # - Sold Cost (cost of goods sold)
        # - Sales Price

        sql = """
        WITH production AS (
            SELECT
                p.id AS product_id,
                COALESCE(SUM(mo.product_qty), 0) AS prod_qty
            FROM my_product_product p
            LEFT JOIN idil_manufacturing_order mo
                ON mo.product_id = p.id
                AND mo.status = 'done'
                AND DATE(mo.scheduled_start_date) BETWEEN %(start)s AND %(end)s
            GROUP BY p.id
        ),
        sales AS (
            SELECT
                sol.product_id,
                COALESCE(SUM(sol.quantity), 0) AS sold_qty,
                COALESCE(SUM(sol.subtotal), 0) AS sold_revenue
            FROM idil_sale_order_line sol
            JOIN idil_sale_order so ON sol.order_id = so.id
            WHERE so.state = 'confirmed'
            AND so.order_date BETWEEN %(start)s AND %(end)s
            AND so.company_id = %(company_id)s
            GROUP BY sol.product_id
        ),
        movements AS (
            SELECT
                pm.product_id,
                COALESCE(SUM(CASE WHEN pm.movement_type = 'in' THEN pm.quantity ELSE 0 END), 0) AS total_in,
                COALESCE(SUM(CASE WHEN pm.movement_type = 'out' THEN ABS(pm.quantity) ELSE 0 END), 0) AS total_out,
                COALESCE(SUM(CASE 
                    WHEN pm.movement_type = 'out' AND pm.destination = 'disposed' 
                    THEN ABS(pm.quantity) ELSE 0 END), 0) AS disposed_qty
            FROM idil_product_movement pm
            WHERE pm.date BETWEEN %(start)s AND %(end)s
            GROUP BY pm.product_id
        )
        SELECT
            p.name AS product_name,
            COALESCE(pr.prod_qty, 0) AS prod_qty,
            COALESCE(mv.total_in, 0) AS total_qty,
            ROUND(COALESCE(p.cost, 0)::numeric, 2) AS unit_cost,
            ROUND((COALESCE(mv.total_in, 0) * COALESCE(p.cost, 0))::numeric, 2) AS total_cost,
            COALESCE(mv.disposed_qty, 0) AS disposed,
            p.stock_quantity AS ready_qty,
            COALESCE(s.sold_qty, 0) AS sold_qty,
            ROUND((COALESCE(s.sold_qty, 0) * COALESCE(p.cost, 0))::numeric, 2) AS sold_cost,
            ROUND(COALESCE(p.sale_price, 0)::numeric, 2) AS sales_price
        FROM my_product_product p
        LEFT JOIN production pr ON pr.product_id = p.id
        LEFT JOIN sales s ON s.product_id = p.id
        LEFT JOIN movements mv ON mv.product_id = p.id
        WHERE (%(product_id)s IS NULL OR p.id = %(product_id)s)
        ORDER BY p.name
        """

        params = {
            "start": start_date,
            "end": end_date,
            "company_id": company.id,
            "product_id": self.product_id.id if self.product_id else None,
        }

        _logger.info(
            f"Generating Product Inventory Summary: Start={start_date}, End={end_date}, Company={company.id}"
        )

        self.env.cr.execute(sql, params)
        rows = self.env.cr.fetchall()

        _logger.info(f"Product Inventory Summary Query returned {len(rows)} rows.")

        # Table Headers (matching the screenshot)
        headers = [
            "Product",
            "Prod Qty",
            "Total Qty",
            "Unit Cost",
            "Total Cost",
            "Disposed",
            "Ready Qty",
            "Sold Qty",
            "Sold Cost",
            "Sales Price",
        ]
        data = [headers]

        # Totals
        total_prod_qty = 0
        total_qty = 0
        total_cost = 0
        total_disposed = 0
        total_ready = 0
        total_sold_qty = 0
        total_sold_cost = 0

        for row in rows:
            # row: name, prod_qty, total_qty, unit_cost, total_cost, disposed, ready_qty, sold_qty, sold_cost, sales_price
            formatted = [
                str(row[0])[:25],  # Product (truncate long names)
                f"{row[1]:,.2f}",  # Prod Qty
                f"{row[2]:,.2f}",  # Total Qty
                f"{row[3]:,.2f}",  # Unit Cost
                f"{row[4]:,.2f}",  # Total Cost
                f"{row[5]:,.2f}",  # Disposed
                f"{row[6]:,.2f}" if row[6] else "0.00",  # Ready Qty
                f"{row[7]:,.2f}",  # Sold Qty
                f"{row[8]:,.2f}",  # Sold Cost
                f"{row[9]:,.2f}",  # Sales Price
            ]
            data.append(formatted)

            # Accumulate totals
            total_prod_qty += float(row[1] or 0)
            total_qty += float(row[2] or 0)
            total_cost += float(row[4] or 0)
            total_disposed += float(row[5] or 0)
            total_ready += float(row[6] or 0)
            total_sold_qty += float(row[7] or 0)
            total_sold_cost += float(row[8] or 0)

        # Add Totals Row
        data.append([
            "TOTALS",
            f"{total_prod_qty:,.2f}",
            f"{total_qty:,.2f}",
            "",
            f"{total_cost:,.2f}",
            f"{total_disposed:,.2f}",
            f"{total_ready:,.2f}",
            f"{total_sold_qty:,.2f}",
            f"{total_sold_cost:,.2f}",
            "",
        ])

        # Column widths adjusted for landscape
        col_widths = [110, 55, 55, 55, 65, 55, 55, 55, 60, 65]
        table = Table(data, colWidths=col_widths)

        # Table Style (matching screenshot golden header)
        style = TableStyle([
            # Header Row
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#B8860B")),  # Dark Gold
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
            ("ALIGN", (0, 0), (0, -1), "LEFT"),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, 0), 9),
            ("BOTTOMPADDING", (0, 0), (-1, 0), 10),
            ("TOPPADDING", (0, 0), (-1, 0), 10),
            # Data Rows
            ("BACKGROUND", (0, 1), (-1, -2), colors.HexColor("#FFFDF5")),
            ("FONTSIZE", (0, 1), (-1, -1), 8),
            ("GRID", (0, 0), (-1, -2), 0.5, colors.HexColor("#D4AF37")),
            # Totals Row
            ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#F5E6C8")),
            ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
            ("TOPPADDING", (0, -1), (-1, -1), 10),
            ("LINEABOVE", (0, -1), (-1, -1), 1, colors.HexColor("#B8860B")),
        ])
        table.setStyle(style)

        elements.append(table)
        doc.build(elements)
        buffer.seek(0)
        pdf_data = buffer.read()

        attachment = self.env["ir.attachment"].create({
            "name": f"product_inventory_summary_{start_date}_{end_date}.pdf",
            "type": "binary",
            "datas": base64.b64encode(pdf_data),
            "mimetype": "application/pdf",
        })

        return {
            "type": "ir.actions.act_url",
            "url": f"/web/content/{attachment.id}?download=true",
            "target": "new",
        }
