# -*- coding: utf-8 -*-

import logging
from odoo import models, fields, api, exceptions, tools, _
from datetime import datetime, timezone, time
from dateutil.parser import parse

_logger = logging.getLogger(__name__)


class OmnaSyncOrders(models.TransientModel):
    _name = 'omna.sync_orders_wizard'
    _inherit = 'omna.api'

    sync_type = fields.Selection([('all', 'All'),
                                  ('by_integration', 'By Integration'),
                                  ('number', 'Number')], 'Import Type', required=True, default='all', help="If you select Number option, you have to provide the Reference value of an Order in Lazada.")
    integration_id = fields.Many2one('omna.integration', 'Integration')
    number = fields.Char("Order Number")


    def sync_orders(self):
        try:
            limit = 10
            offset = 0
            requester = True
            orders = []
            if self.sync_type != 'number':
                while requester:
                    if self.sync_type == 'all':
                        response = self.get('orders', {'limit': limit, 'offset': offset, 'with_details': True})
                    else:
                        response = self.get('integrations/%s/orders' % self.integration_id.integration_id, {'limit': limit, 'offset': offset, 'with_details': True})
                    data = response.get('data')
                    orders.extend(data)
                    if len(data) < limit:
                        requester = False
                    else:
                        offset += limit
            else:
                response = self.get('integrations/%s/orders/%s' % (self.integration_id.integration_id, self.number), {'with_details': True})
                data = response.get('data')
                orders.append(data)

            if orders:
                self.do_import(orders)
                return {
                    'type': 'ir.actions.client',
                    'tag': 'reload'
                }
            else:
                self.env.user.notify_channel('warning', _("Sorry, we don't find results for this criteria. \n Please execute from Settings / Import Mercado Libre -> Omna the option for import Orders, later try to execute this functionality."), _("Information"), True)

        except Exception as e:
            _logger.error(e)
            raise exceptions.AccessError(e)


    def do_import(self, orders):
        try:
            for order in orders:
                # if order['status'] == 'Payment accepted':
                if order['status']:

                    # line_items = [X for X in order.get('original_raw_data').get('associations').get('order_rows')]
                    line_items = order.get('line_items')

                    act_order = self.env['sale.order'].search([('omna_id', '=', order.get('id'))])

                    if not act_order:

                        # partner_invoice = self.env['res.partner'].search([('name', '=', '%s %s' % (
                        #     order.get('original_raw_data').get('customer').get('firstname'),
                        #     order.get('original_raw_data').get('customer').get('lastname'))),
                        #     ('email', '=', order.get('original_raw_data').get('customer').get('email'))], limit=1)

                        # partner_related = self.env['res.partner'].search(['&', '&', ('integration_id', '=', self.integration_id.id),
                        #     ('email', '=', order.get('original_raw_data').get('customer').get('email')),
                        #     ('omna_id', '=', order.get('original_raw_data').get('customer').get('id'))], limit=1)
                        #
                        # if not partner_related:
                        partner_related = self._create_partner(order.get('original_raw_data'))
                        # partner_invoice = self._create_partner(order.get('original_raw_data').get('address_invoice'))
                        # partner_shipping = self._create_partner(order.get('original_raw_data').get('address_delivery'))

                        # partner_shipping = self.env['res.partner'].search([('name', '=', '%s %s' % (
                        #     order.get('ship_address').get('first_name'), order.get('ship_address').get('last_name')))], limit=1)
                        # if not partner_shipping:
                        #     partner_shipping = self._create_partner(order.get('ship_address'))

                        if order.get('integration'):
                            integration = self.env['omna.integration'].search([('integration_id', '=', order.get('integration').get('id'))], limit=1)
                            # warehouse_delivery = self.env['stock.warehouse'].search([('integration_id', '=', integration.id), ('omna_id', '!=', False)], limit=1)
                            warehouse_delivery = self.env['stock.warehouse'].search([('integration_id', '=', integration.id), ('omna_id', '!=', False)], limit=1)
                            # tax_result = self.env['account.tax'].search([('integration_id', '=', integration.id),
                            # ('omna_tax_rule_id', '=', False)], limit=1)

                            if integration:

                                partner_invoice = partner_related.child_ids.filtered(lambda X: X.type == 'invoice')
                                partner_shipping = partner_related.child_ids.filtered(lambda X: X.type == 'delivery')

                                data = {
                                    'omna_id': order.get('id'),
                                    'integration_id': integration.id,
                                    'omna_order_reference': order.get('number'),
                                    'origin': 'OMNA',
                                    'state': 'draft',
                                    'amount_total': round(float(order.get('total_price'))) ,
                                    # 'amount_total': '22.5',
                                    'date_order': fields.Datetime.to_string(parse(order.get('last_import_date').split('T')[0])),
                                    'create_date': fields.Datetime.to_string(datetime.now(timezone.utc)),
                                    'partner_id': partner_related.id,
                                    'partner_invoice_id': partner_invoice.id if partner_invoice else partner_related.id,
                                    'partner_shipping_id': partner_shipping.id if partner_shipping else partner_related.id,
                                    'warehouse_id': warehouse_delivery.id,
                                    'pricelist_id': self.env.ref('product.list0').id,

                                }
                                if order.get('omna_tenant_id'):
                                    data['omna_tenant_id'] = order.get('omna_tenant_id')

                                # omna_order = self.env['sale.order'].create(data)

                                # Creating the orderlines
                                # for line_item in order.get('line_items'):
                                aux = []
                                for line_item in line_items:
                                    # self._create_orderline(omna_order, line_item, order.get('payments')[0].get('currency'))
                                    aux.append((0, 0, self._create_orderline(line_item, order.get('currency'))))

                                # aux.append((0, 0, self._create_carrier_cost(order)))
                                data['order_line'] = aux
                                omna_order = self.env['sale.order'].create(data)

                                amount_untaxed = amount_tax = 0.0
                                for line in omna_order.order_line:
                                    amount_untaxed += line.price_subtotal
                                    amount_tax += line.price_tax
                                omna_order.write({
                                    'amount_untaxed': amount_untaxed,
                                    'amount_tax': amount_tax,
                                    'amount_total': amount_untaxed + amount_tax,
                                })
                                # omna_order._amount_all()

        except Exception as e:
            _logger.error(e)
            raise exceptions.AccessError(e)


    # Agregar a esta funcionalidad las validaciones para relacionar el res.partner con las direcciones de factura y entrega segun la data que llegue en **kwargs
    # Esto seria crear y asociar nuevos records en la pestaña de Contacts and Addresses
    # Ademas de realizar los mapeos para los campos de country_id, state_id, city_id, l10n_pe_district segun la data que llegue de Cenit
    def _create_partner(self, dict_param):
        partner_related = self.env['res.partner'].search(['&', '&', ('integration_id', '=', self.integration_id.id),
                                                          ('email', '=', dict_param.get('buyer').get('email')),
                                                          ('omna_id', '=', dict_param.get('buyer').get('id'))], limit=1)
        if partner_related:
            return partner_related
        else:
            data = {
                'name': '%s %s' % (dict_param.get('buyer').get('first_name'), dict_param.get('buyer').get('last_name')),
                # 'firstname': dict_param.get('buyer').get('first_name'),
                # 'surname': dict_param.get('buyer').get('last_name'),
                # 'mother_name': dict_param.get('customer').get('lastname'),
                'company_type': 'person',
                'l10n_latam_identification_type_id': self.env.ref('l10n_ar.it_dni').id,
                # 'vat': dict_param.get('address_invoice').get('vat_number') or dict_param.get('customer').get('dni'),
                'vat': "1111",
                'type': 'contact',
                # 'street': dict_param.get('address_invoice').get('address1'),
                'street': "AAAAA",
                # 'street2': dict_param.get('address_invoice').get('address2'),
                'street2': "BBBBB",
                # 'city': dict_param.get('address_invoice').get('city'),
                # 'l10n_pe_ubigeo': dict_param.get('address_invoice').get('postcode'),
                'email': dict_param.get('buyer').get('email'),
                'lang': self.env.user.lang,
                'integration_id': self.integration_id.id,
                'omna_id':  str(dict_param.get('buyer').get('id')),
                'prestashop_id': str(dict_param.get('buyer').get('id')),
                # 'child_ids': [(0, 0,  {'type': 'invoice',
                #                        'name': '%s %s' % (dict_param.get('address_invoice').get('firstname'), dict_param.get('address_invoice').get('lastname')),
                #                        'street': dict_param.get('address_invoice').get('address1'),
                #                        'street2': dict_param.get('address_invoice').get('address2'),
                #                        'city': dict_param.get('address_invoice').get('city'),
                #                        'zip': dict_param.get('address_invoice').get('postcode'),
                #                        'email': dict_param.get('customer').get('email'),
                #                        'l10n_latam_identification_type_id': self.env.ref('l10n_pe.it_RUC').id if dict_param.get('address_invoice').get('vat_number') else self.env.ref('l10n_pe.it_DNI').id,
                #                        'vat': dict_param.get('address_invoice').get('vat_number') or dict_param.get('customer').get('dni'),
                #                       }),
                #               (0, 0,  {'type': 'delivery',
                #                        'name': '%s %s' % (dict_param.get('address_delivery').get('firstname'), dict_param.get('address_delivery').get('lastname')),
                #                        'street': dict_param.get('address_delivery').get('address1'),
                #                        'street2': dict_param.get('address_delivery').get('address2'),
                #                        'city': dict_param.get('address_delivery').get('city'),
                #                        'zip': dict_param.get('address_delivery').get('postcode'),
                #                        'email': dict_param.get('customer').get('email'),
                #                        'l10n_latam_identification_type_id': self.env.ref('l10n_pe.it_RUC').id if dict_param.get('address_delivery').get('vat_number') else self.env.ref('l10n_pe.it_DNI').id,
                #                        'vat': dict_param.get('address_delivery').get('vat_number') or dict_param.get('customer').get('dni'),
                #                })]
            }

            # state_manager = self.env['res.country.state']
            # district_manager = self.env['l10n_pe.res.city.district']
            data['country_id'] = self.env.ref('base.ar').id
            # state = state_manager.search([('code', '=', dict_param.get('address_invoice').get('state_iso_code')), ('country_id', '=', country.id)], limit=1)
            # district = district_manager.search([('code', '=', dict_param.get('address_invoice').get('state_iso_code'))])
            # district.city_id.state_id.id
            # state = state_manager.search([('code', '=', dict_param.get('address_invoice').get('state_iso_code'))])
            # if district:
            #     data['state_id'] = district.city_id.state_id.id
            return self.env['res.partner'].create(data)


    # def _create_orderline(self, omna_order, line_item, currency):
    def _create_orderline(self, line_item, currency):
        currency = self.env['res.currency'].search([('name', '=', currency)], limit=1)
        if not currency:
            currency = self.env['res.currency'].search([('name', '=', 'USD')], limit=1)

        product = self.env['product.product'].search([('default_code', '=', line_item.get('product_reference'))], limit=1)

        data = {
            # 'order_id': omna_order.id,
            'omna_id': line_item.get('id'),
            # 'name': product.product_tmpl_id.name if product else line_item.get('name'),
            'name': product.name,
            'price_unit': product.product_tmpl_id.list_price,
            # 'state': omna_order.state,
            'state': "draft",
            'qty_delivered_manual': 0,
            'product_id': product.id if product else False,
            'display_type': False,
            'product_uom': product.product_tmpl_id.uom_id.id if product else self.env.ref('uom.product_uom_unit').id,
            'product_uom_qty': line_item.get('quantity'),
            'customer_lead': 0,  #
            'currency_id': currency.id,
            'product_packaging': False,
            'discount': 0,
            'product_template_id': product.product_tmpl_id.id,
            'route_id': False,
            # 'tax_id': [[6, False, [56]]],
        }

        if not product.id:
            data['display_type'] = 'line_section'

        return data


    def _create_carrier_cost(self, omna_order):
        currency = self.env['res.currency'].search([('name', '=', omna_order.get('currency'))], limit=1)
        if not currency:
            currency = self.env['res.currency'].search([('name', '=', 'USD')], limit=1)

        product = self.env['product.template'].search([('omna_product_id', '=', omna_order.get('original_raw_data').get('id_carrier'))], limit=1)


        data = {
            'omna_id': omna_order.get('original_raw_data').get('id_carrier'),
            'name': product.product_variant_id.name,
            'price_unit': float(omna_order.get('original_raw_data').get('total_shipping')),
            'state': "draft",
            'qty_delivered_manual': 0,
            'product_id': product.product_variant_id.id if product else False,
            'display_type': False,
            'product_uom': product.uom_id.id if product else self.env.ref('uom.product_uom_unit').id,
            'product_uom_qty': 1,
            'customer_lead': 0,  #
            'currency_id': currency.id,
            'product_packaging': False,
            'discount': 0,
            'product_template_id': product.id,
            'route_id': False,
        }

        if not product.id:
            data['display_type'] = 'line_section'

        return data


    def background_import_orders(self):
        try:
            limit = 10
            offset = 0
            requester = True
            orders = []
            integration_result = self.env['omna.integration'].search([], limit=1)

            while requester:
                response = self.get('integrations/%s/orders' % integration_result.integration_id, {'limit': limit, 'offset': offset, 'with_details': True})
                data = response.get('data')
                orders.extend(data)
                if len(data) < limit:
                    requester = False
                else:
                    offset += limit

            if orders:
                self.do_import(orders)
                _logger.info('The task to import orders from Cenit to Odoo have been created, please go to "System\Tasks" to check out the task status.')
            else:
                _logger.info("Sorry, we don't find new order records for import to Odoo.")

        except Exception as e:
            _logger.error(e)
            # raise exceptions.AccessError(e)
        pass


