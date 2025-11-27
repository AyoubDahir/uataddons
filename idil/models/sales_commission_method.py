
    def _create_sales_commission_record(self):
        """Create deferred commission record for salesperson"""
        for order in self:
            if order.commission_amount > 0:
                self.env['idil.sales.commission'].create({
                    'sale_order_id': order.id,
                    'sales_person_id': order.sales_person_id.id,
                    'date': order.order_date,
                    'currency_id': order.currency_id.id,
                    'commission_amount': order.commission_amount,
                })
