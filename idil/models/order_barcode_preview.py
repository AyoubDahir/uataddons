from odoo import models, fields, api

class OrderBarcodePreview(models.TransientModel):
    _name = "idil.order.barcode.preview"
    _description = "Order Barcode Preview"

    name = fields.Char(string="Reference", readonly=True)
    owner_name = fields.Char(string="Owner", readonly=True)
    order_date = fields.Datetime(string="Order Date", readonly=True)
    qr_data = fields.Text(string="QR Data", readonly=True)
    
    # This field will be used to render the HTML preview on screen
    preview_html = fields.Html(string="Preview", compute="_compute_preview_html")

    @api.depends('name', 'owner_name', 'order_date', 'qr_data')
    def _compute_preview_html(self):
        for rec in self:
            # Generate the preview HTML similar to the report but for screen
            # Note: We use Odoo's internal barcode controller for the images
            barcode_url = f"/report/barcode/?barcode_type=Code128&value={rec.name}&width=600&height=150"
            qr_url = f"/report/barcode/?barcode_type=QR&value={rec.qr_data}&width=200&height=200"
            
            rec.preview_html = f"""
                <div style="background-color: #f8f9fa; padding: 20px; border-radius: 10px; border: 2px solid #000080; font-family: Arial, sans-serif;">
                    <div style="background-color: #000080; color: white; padding: 10px 20px; border-radius: 8px 8px 0 0; display: flex; justify-content: space-between; align-items: center;">
                        <h2 style="margin: 0; font-size: 24px;">{rec.name}</h2>
                        <span style="font-size: 12px; opacity: 0.8;">{rec.order_date}</span>
                    </div>
                    
                    <div style="padding: 20px; background: white; border: 1px solid #dee2e6; border-top: none; border-radius: 0 0 8px 8px;">
                        <div style="margin-bottom: 20px;">
                            <label style="font-size: 10px; color: #666; font-weight: bold; text-transform: uppercase;">Owner / Responsible</label>
                            <div style="font-size: 22px; font-weight: bold; color: #000080;">{rec.owner_name}</div>
                        </div>
                        
                        <div style="display: flex; gap: 20px; align-items: flex-end; padding-top: 20px; border-top: 1px dashed #dee2e6;">
                            <div style="flex: 1; text-align: center;">
                                <div style="font-size: 9px; color: #999; margin-bottom: 5px; font-weight: bold;">BARCODE (FOR ODOO SEARCH)</div>
                                <img src="{barcode_url}" style="width: 100%; height: 60px; object-fit: contain;"/>
                                <div style="font-weight: bold; margin-top: 5px;">{rec.name}</div>
                            </div>
                            
                            <div style="width: 120px; text-align: center;">
                                <div style="font-size: 9px; color: #999; margin-bottom: 5px; font-weight: bold;">QR (FULL DETAILS)</div>
                                <img src="{qr_url}" style="width: 100px; height: 100px;"/>
                            </div>
                        </div>
                    </div>
                </div>
            """
