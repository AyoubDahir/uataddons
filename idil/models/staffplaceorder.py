from odoo import models, fields, api
from odoo.exceptions import ValidationError, UserError

class StaffPlaceOrder(models.Model):
    _name = "idil.staff.place.order"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _description = "Staff Place Order"
    _order = "id desc"

    name = fields.Char(string="Order Reference", required=True, copy=False, readonly=True, index=True, default="New", tracking=True)
    employee_id = fields.Many2one("idil.employee", string="Staff Member", required=True, tracking=True)
    order_date = fields.Datetime(string="Order Date", default=fields.Datetime.now, tracking=True)
    order_lines = fields.One2many("idil.staff.place.order.line", "order_id", string="Order Lines")
    state = fields.Selection([("draft", "Draft"), ("confirmed", "Confirmed"), ("cancel", "Cancelled")], default="draft", readonly=True, tracking=True)
    total_quantity = fields.Float(string="Total Quantity", compute="_compute_total_quantity", store=True)
    barcode = fields.Char(string="Barcode", compute="_compute_barcode", store=True)
    qr_data = fields.Text(string="QR Data", compute="_compute_qr_data")

    @api.depends('name')
    def _compute_qr_data(self):
        base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url')
        for rec in self:
            rec.qr_data = f"{base_url}/order/info/{rec.name}"

    @api.depends('name')
    def _compute_barcode(self):
        for rec in self:
            rec.barcode = rec.name

    def action_view_barcode(self):
        self.ensure_one()
        return {
            'name': 'Order Barcode Preview',
            'type': 'ir.actions.act_window',
            'res_model': 'idil.order.barcode.preview',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_name': self.name,
                'default_owner_name': self.employee_id.name,
                'default_order_date': self.order_date,
                'default_qr_data': self.qr_data,
            }
        }

    @api.depends("order_lines.quantity")
    def _compute_total_quantity(self):
        for order in self:
            order.total_quantity = sum(line.quantity for line in order.order_lines)

    @api.constrains('employee_id', 'state')
    def _check_unique_draft_order(self):
        for record in self:
            if record.state == 'draft':
                existing_draft = self.search([
                    ('employee_id', '=', record.employee_id.id),
                    ('state', '=', 'draft'),
                    ('id', '!=', record.id)
                ], limit=1)
                if existing_draft:
                    raise ValidationError(f"Staff member {record.employee_id.name} already has an active draft order.")

    @api.model
    def create(self, vals):
        if vals.get('name', 'New') == 'New':
            vals['name'] = self.env['ir.sequence'].next_by_code('idil.staff.place.order.sequence') or 'New'
        
        # Prevent duplicate draft orders for same staff early
        if vals.get('employee_id') and vals.get('state', 'draft') == 'draft':
            existing_draft = self.search([
                ('employee_id', '=', vals.get('employee_id')),
                ('state', '=', 'draft')
            ], limit=1)
            if existing_draft:
                employee_name = self.env['idil.employee'].browse(vals.get('employee_id')).name
                raise UserError(f"Staff member {employee_name} already has an active draft order.")
            
        return super(StaffPlaceOrder, self).create(vals)

    def action_confirm_order(self):
        self.write({"state": "confirmed"})

    def action_cancel_order(self):
        self.write({"state": "cancel"})

class StaffPlaceOrderLine(models.Model):
    _name = "idil.staff.place.order.line"
    _description = "Staff Place Order Line"

    order_id = fields.Many2one("idil.staff.place.order", string="Staff Order", required=True, ondelete='cascade')
    product_id = fields.Many2one("my_product.product", string="Product", required=True)
    quantity = fields.Float(string="Quantity", default=1.0)

    @api.onchange("product_id")
    def _onchange_product_id(self):
        if self.product_id:
            self.quantity = 1.0

    @api.constrains("quantity")
    def _check_quantity(self):
        for line in self:
            if line.quantity <= 0:
                raise ValidationError("Quantity must be greater than zero.")
