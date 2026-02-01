from odoo import http
from odoo.http import request

class OrderInfoController(http.Controller):
    @http.route('/order/info/<string:order_ref>', type='http', auth='public', website=True)
    def order_info(self, order_ref, **kwargs):
        # Search for the order in all possible models
        order = request.env['idil.salesperson.place.order'].sudo().search([('name', '=', order_ref)], limit=1)
        if not order:
            order = request.env['idil.customer.place.order'].sudo().search([('name', '=', order_ref)], limit=1)
        if not order:
            order = request.env['idil.staff.place.order'].sudo().search([('name', '=', order_ref)], limit=1)
            
        if not order:
            return "Order not found"

        # Determine owner name
        owner_name = ""
        if 'salesperson_id' in order._fields:
            owner_name = order.salesperson_id.name
        elif 'customer_id' in order._fields:
            owner_name = order.customer_id.name
        elif 'employee_id' in order._fields:
            owner_name = order.employee_id.name

        values = {
            'order': order,
            'owner_name': owner_name,
        }
        return request.render('idil.order_info_mobile_template', values)
