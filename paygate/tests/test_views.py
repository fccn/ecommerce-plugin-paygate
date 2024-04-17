import json

import mock
from django.test import override_settings
from django.urls import reverse
from oscar.core.loading import get_model
from paygate.processors import PayGate

from ecommerce.courses.tests.factories import CourseFactory
from ecommerce.extensions.checkout.utils import get_receipt_page_url
from ecommerce.extensions.test.factories import create_basket, create_order
from ecommerce.tests.factories import UserFactory
from ecommerce.tests.testcases import TestCase

Basket = get_model('basket', 'Basket')
PaymentProcessorResponse = get_model("payment", "PaymentProcessorResponse")
Order = get_model('order', 'Order')


class PayGateCallbackTests(TestCase):
    """
    Test PayGate Callbacks:
    - server - the server-to-server callback
    - success - the user/client PayGate redirect
    - cancel - when the user/client cancels payment on PayGate
    - failure - when some error is raised inside of PayGate
    """

    def test_cancel_response_view_default(self):
        """
        Test the cancel response view, if the user cancel the payment on the PayGate the user will
        be redirected to this view.
        """
        response = self.client.get(reverse("ecommerce_plugin_paygate:callback_cancel"))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("checkout:cancel-checkout"), response.url)

    @override_settings(
        PAYMENT_PROCESSOR_CONFIG={
            "edx": {
                "paygate": {
                    "access_token": "PwdX_XXXX_YYYY",
                    "merchant_code": "NAU",
                    "api_checkout_url": "https://test.optimistic.blue/paygateWS/api/CheckOut",
                    "api_back_search_transactions":
                        "https://test.optimistic.blue/paygateWS/api/BackOfficeSearchTransactions",
                    "api_basic_auth_user": "NAU",
                    "api_basic_auth_pass": "APassword",
                    "cancel_checkout_path": "/another/path",
                }
            }
        }
    )
    def test_cancel_response_view_custom_path(self):
        """
        Test the cancel response view, if the user cancel the payment on the PayGate the user will
        be redirected to this view.
        This test tests the possibility to customize that page, using the `cancel_checkout_path`
        payment processor configuration.
        """
        response = self.client.get(reverse("ecommerce_plugin_paygate:callback_cancel"))
        self.assertEqual(response.status_code, 302)
        self.assertIn("/another/path", response.url)

    def test_failure_response_view_default(self):
        """
        Test the failure / error response view, used by the PayGate to redirect the client if some
        error has been raised internally or by the upstream payment processor.
        By default it should redirect to the default Django Oscar checkout error page.
        """
        response = self.client.get(reverse("ecommerce_plugin_paygate:callback_failure"))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("checkout:error"), response.url)

    @override_settings(
        PAYMENT_PROCESSOR_CONFIG={
            "edx": {
                "paygate": {
                    "access_token": "PwdX_XXXX_YYYY",
                    "merchant_code": "NAU",
                    "api_checkout_url": "https://test.optimistic.blue/paygateWS/api/CheckOut",
                    "api_back_search_transactions": "https://test.optimistic.blue/paygateWS/api/BackOfficeSearchTransactions",
                    "api_basic_auth_user": "NAU",
                    "api_basic_auth_pass": "APassword",
                    "error_path": "/some/error/custom/path",
                }
            }
        }
    )
    def test_failure_response_view_custom_path(self):
        """
        Test the failure / error response view, used by the PayGate to redirect the client if some
        error has been raised internally or by the upstream payment processor.
        This test tests the possibility of changing the page path that will be used.
        """
        response = self.client.get(reverse("ecommerce_plugin_paygate:callback_failure"))
        self.assertEqual(response.status_code, 302)
        self.assertIn("/some/error/custom/path", response.url)

    def test_server_response_view_get(self):
        """
        Test the server-to-server callback with a HTTP GET method.
        It should return a method not allowed response, because this view is to called only using
        the POST method.
        """
        response = self.client.get(reverse("ecommerce_plugin_paygate:callback_server"))
        self.assertEqual(response.status_code, 405)

    @override_settings(
        PAYMENT_PROCESSOR_CONFIG={
            "edx": {
                "paygate": {
                    "access_token": "PwdX_XXXX_YYYY",
                    "merchant_code": "NAU",
                    "api_checkout_url": "https://test.optimistic.blue/paygateWS/api/CheckOut",
                    "api_back_search_transactions": "https://test.optimistic.blue/paygateWS/api/BackOfficeSearchTransactions",
                    "api_basic_auth_user": "NAU",
                    "api_basic_auth_pass": "APassword",
                    "callback_server_allowed_networks": ["10.0.10.1"],
                }
            }
        }
    )
    def test_server_response_view_allowed_networks(self):
        """
        Test the server-to-server callback with a list of allowed networks / IP addresses that is
        allowed to call this view.
        """
        response = self.client.post(reverse("ecommerce_plugin_paygate:callback_server"))
        self.assertContains(
            response, "Unauthorized invalid allowed ip address", status_code=401
        )

    def test_server_response_view_without_status_and_success(self):
        """
        Test the server-to-server callback without the required parameters of status and success.
        """
        response = self.client.post(reverse("ecommerce_plugin_paygate:callback_server"))
        self.assertContains(
            response, "Incorrect payment_ref", status_code=412
        )

    @mock.patch.object(PayGate, "_make_api_json_request")
    def test_server_response_view_payed(self, mock__make_api_json_request):
        """
        Test the server-to-server callback with a success payed request.
        """
        # create data for test
        course = CourseFactory(id='a/b/c', name='Demo Course', partner=self.partner)
        product = course.create_or_update_seat('test-certificate-type', False, 20)
        basket = create_basket(site=self.site, owner=UserFactory(), empty=True)
        basket.add_product(product)
        basket.save()

        # mock the call to PayGate to double-check if it's being payed
        mock__make_api_json_request.return_value = [{
            "MERCHANT_CODE": "NAU",
            "STATUS_CODE": "C",
            "PAYMENT_REF": basket.order_number,
            "PAYMENT_AMOUNT": "20.00",
            "TRANSACTION_ID": basket.order_number,
            "CARD_MASKED_PAN": "1234",
            "PAYMENT_TYPE_CODE": "REFMB",
        }]

        callback_server_data = {
            "success": True,
            "statusCode": "C",
            'payment_ref': basket.order_number,
            "paymentValue": "20.00",
            "transaction_id": basket.order_number,
            "card_masked_pan": "1234",
            "payment_type_code": "REFMB",
        }
        response = self.client.post(
            reverse("ecommerce_plugin_paygate:callback_server"),
            data=json.dumps(callback_server_data),
            content_type='application/json'
        )
        self.assertContains(response, "Received server callback with success")

        order = Order.objects.all().first()
        self.assertEqual(order.basket.id, basket.id)

    @mock.patch.object(PayGate, "_make_api_json_request")
    def test_server_response_view_already_orderer(self, mock__make_api_json_request):
        """
        Test the server-to-server callback with an already ordered Basket.
        This can happen when we receive a server callback in duplicate or we receive a success
        callback and then a server callback.
        """
        # create data for test
        course = CourseFactory(id='a/b/c', name='Demo Course', partner=self.partner)
        course.save()
        product = course.create_or_update_seat('test-certificate-type', False, 20)
        product.save()
        basket = create_basket(site=self.site, owner=UserFactory(), empty=True)
        basket.add_product(product)
        basket.save()

        # already save an Order for the Basket
        order = create_order(basket=basket)
        order.save()

        # mock the call to PayGate to double-check if it's being payed
        mock__make_api_json_request.return_value = [{
            "MERCHANT_CODE": "NAU",
            "STATUS_CODE": "C",
            "PAYMENT_REF": basket.order_number,
            "PAYMENT_AMOUNT": "20.00",
            "TRANSACTION_ID": basket.order_number,
            "CARD_MASKED_PAN": "1234",
            "PAYMENT_TYPE_CODE": "REFMB",
        }]

        callback_server_data = {
            "success": True,
            "statusCode": "C",
            'payment_ref': basket.order_number,
            "paymentValue": "20.00",
            "transaction_id": basket.order_number,
            "card_masked_pan": "1234",
            "payment_type_code": "REFMB",
        }
        response = self.client.post(
            reverse("ecommerce_plugin_paygate:callback_server"),
            data=json.dumps(callback_server_data),
            content_type='application/json'
        )
        self.assertContains(response, "Received server callback with success")

        order = Order.objects.all().first()
        self.assertEqual(order.basket.id, basket.id)
        self.assertTrue(len(Order.objects.all()) == 1)

    @mock.patch.object(PayGate, "_make_api_json_request")
    def test_success_response_view_payed(self, mock__make_api_json_request):
        """
        Test the success callback with a payed request.
        """
        # create data for test
        course = CourseFactory(id='a/b/c', name='Demo Course', partner=self.partner)
        product = course.create_or_update_seat('test-certificate-type', False, 20)
        basket = create_basket(site=self.site, owner=UserFactory(), empty=True)
        basket.add_product(product)
        basket.save()

        # mock the call to PayGate to double-check if it's being payed
        mock__make_api_json_request.return_value = [{
            "MERCHANT_CODE": "NAU",
            "STATUS_CODE": "C",
            "PAYMENT_REF": basket.order_number,
            "PAYMENT_AMOUNT": "20.00",
            "TRANSACTION_ID": basket.order_number,
            "CARD_MASKED_PAN": "1234",
            "PAYMENT_TYPE_CODE": "REFMB",
        }]

        callback_success_data = {
            "is_paid": True,
            "StatusCode": "C",
            'payment_ref': basket.order_number,
            "paymentValue": "20.00EUR",
            "transaction_id": basket.order_number,
            "card_masked_pan": "1234",
            "payment_type_code": "REFMB",
        }
        response = self.client.get(
            reverse("ecommerce_plugin_paygate:callback_success"),
            callback_success_data,
        )

        receipt_url = get_receipt_page_url(
            self.request.site.siteconfiguration,
            order_number=basket.order_number,
            disable_back_button=True,
        )
        self.assertEqual(receipt_url, response['Location'])

        order = Order.objects.all().first()
        self.assertEqual(order.basket.id, basket.id)

    @mock.patch.object(PayGate, "_make_api_json_request")
    def test_success_response_view_already_received_callback(self, mock__make_api_json_request):
        """
        Test the success callback with an already received callback (success or server).
        """
        # create data for test
        course = CourseFactory(id='a/b/c', name='Demo Course', partner=self.partner)
        product = course.create_or_update_seat('test-certificate-type', False, 20)
        basket = create_basket(site=self.site, owner=UserFactory(), empty=True)
        basket.add_product(product)
        basket.save()

        # Save an Order for the Basket, to mock has we already received callback.
        order = create_order(basket=basket)
        order.save()

        # mock the call to PayGate to double-check if it's being payed
        mock__make_api_json_request.return_value = [{
            "MERCHANT_CODE": "NAU",
            "STATUS_CODE": "C",
            "PAYMENT_REF": basket.order_number,
        }]

        callback_success_data = {
            "is_paid": True,
            "StatusCode": "C",
            'payment_ref': basket.order_number,
            "paymentValue": "20.00EUR",
            "transaction_id": basket.order_number,
            "card_masked_pan": "1234",
            "payment_type_code": "REFMB",
        }
        response = self.client.get(
            reverse("ecommerce_plugin_paygate:callback_success"),
            callback_success_data,
        )

        receipt_url = get_receipt_page_url(
            self.request.site.siteconfiguration,
            order_number=basket.order_number,
            disable_back_button=True,
        )
        self.assertEqual(receipt_url, response['Location'])

        order = Order.objects.all().first()
        self.assertEqual(order.basket.id, basket.id)

    @mock.patch.object(PayGate, "_make_api_json_request")
    def test_server_response_view_small_callback_data(self, mock__make_api_json_request):
        """
        Test the server-to-server callback with minimalistic callback data.
        """
        # create data for test
        course = CourseFactory(id='a/b/c', name='Demo Course', partner=self.partner)
        course.save()
        product = course.create_or_update_seat('test-certificate-type', False, 20)
        product.save()
        basket = create_basket(site=self.site, owner=UserFactory(), empty=True)
        basket.add_product(product)
        basket.save()

        # mock the call to PayGate to double-check if it's being payed
        mock__make_api_json_request.return_value = [{
            "MERCHANT_CODE": "NAU",
            "STATUS_CODE": "C",
            "PAYMENT_REF": basket.order_number,
            "PAYMENT_AMOUNT": "20.00",
            "TRANSACTION_ID": basket.order_number,
            "CARD_MASKED_PAN": "1234",
            "PAYMENT_TYPE_CODE": "REFMB",
        }]

        callback_server_data = {
            'payment_ref': basket.order_number,

        }
        response = self.client.post(
            reverse("ecommerce_plugin_paygate:callback_server"),
            data=json.dumps(callback_server_data),
            content_type='application/json'
        )
        self.assertContains(response, "Received server callback with success")

        order = Order.objects.all().first()
        self.assertEqual(order.basket.id, basket.id)
        self.assertTrue(len(Order.objects.all()) == 1)
