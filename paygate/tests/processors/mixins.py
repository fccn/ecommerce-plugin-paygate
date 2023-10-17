from __future__ import absolute_import, unicode_literals

import responses
from django.conf import settings
from oscar.core.loading import get_class, get_model
from six.moves.urllib.parse import urljoin

CURRENCY = 'USD'
Basket = get_model('basket', 'Basket')
Order = get_model('order', 'Order')
PaymentEventType = get_model('order', 'PaymentEventType')
PaymentProcessorResponse = get_model('payment', 'PaymentProcessorResponse')
SourceType = get_model('payment', 'SourceType')

post_checkout = get_class('checkout.signals', 'post_checkout')


class PayGateMixin:
    """
    Mixin with helper methods for mocking PayGate API responses.
    """

    def mock_api_response(self, path, body, method=responses.POST, resp=responses):
        url = self._create_api_url(path=path)
        resp.add(method, url, json=body)

    def mock_checkout_api_response(self, code='000.200.100', resp=responses):
        api_response = {
            'result': {
                'code': code
            },
            'id': '123456789',
        }
        url = settings.PAYMENT_PROCESSOR_CONFIG['edx']['paygate']['api_checkout_url']
        self.mock_api_response(url, api_response, resp=resp)

    # def mock_submit_response(self, code='000.000.000', resp=responses):
    #     api_response = {
    #         'result': {
    #             'code': code,
    #             'description': 'FooBarBaz'
    #         },
    #         'merchantTransactionId': 'EDX-100001',
    #         'amount': '149.00',
    #         'cart': {
    #             'items': [
    #                 {
    #                     'currency': 'EUR',
    #                     'name': 'Demo course',
    #                     'quantity': '1',
    #                     'sku': 'A123B456',
    #                     'totalAmount': '149.00',
    #                     'type': 'DIGITAL',
    #                 }
    #             ]
    #         },
    #         'currency': 'EUR',
    #         'id': '8ac7a4a1787d377701787d9bf9b6046d',
    #         'paymentType': 'DB',
    #         'paymentBrand': 'VISA',
    #         'card': {
    #             'bin': '411111',
    #             'binCountry': 'SA',
    #             'expiryMonth': '01',
    #             'expiryYear': '2099',
    #             'holder': 'John Smith',
    #             'last4Digits': '1111'
    #         }
    #     }
    #     self.mock_api_response('/v1/checkouts/123456789/payment', api_response, resp=resp)

    def _create_api_url(self, path):
        """
        Returns the API URL
        """
        base_url = settings.PAYMENT_PROCESSOR_CONFIG['edx']['paygate']['paygate_base_api_url']
        return urljoin(base_url, path)
