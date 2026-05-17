import copy
import json
from decimal import Decimal
from urllib.parse import parse_qsl, urlparse

import mock
from django.conf import settings
from django.db import IntegrityError
from django.test import override_settings
from django.urls import reverse
from oscar.apps.payment.exceptions import GatewayError
from oscar.core.loading import get_model
from paygate.pending_orders import (confirm_pending_order,
                                    mark_order_as_payment_error,
                                    place_pending_order)
from paygate.processors import PayGate
from paygate.utils import get_receipt_page_url

from ecommerce.courses.tests.factories import CourseFactory
from ecommerce.extensions.fulfillment.status import ORDER
from ecommerce.extensions.payment.processors import HandledProcessorResponse
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
                **settings.PAYMENT_PROCESSOR_CONFIG["edx"],
                **{
                    "paygate": {
                        "access_token": "PwdX_XXXX_YYYY",
                        "merchant_code": "NAU",
                        "api_checkout_url": "https://test.optimistic.blue/paygateWS/api/CheckOut",
                        "api_back_search_transactions": "https://test.optimistic.blue/paygateWS/api/BackOfficeSearchTransactions",
                        "api_basic_auth_user": "NAU",
                        "api_basic_auth_pass": "APassword",
                        "cancel_checkout_path": "/another/path",
                    }
                },
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
                **settings.PAYMENT_PROCESSOR_CONFIG["edx"],
                **{
                    "paygate": {
                        "access_token": "PwdX_XXXX_YYYY",
                        "merchant_code": "NAU",
                        "api_checkout_url": "https://test.optimistic.blue/paygateWS/api/CheckOut",
                        "api_back_search_transactions": "https://test.optimistic.blue/paygateWS/api/BackOfficeSearchTransactions",
                        "api_basic_auth_user": "NAU",
                        "api_basic_auth_pass": "APassword",
                        "error_path": "/some/error/custom/path",
                    }
                },
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
                **settings.PAYMENT_PROCESSOR_CONFIG["edx"],
                **{
                    "paygate": {
                        "access_token": "PwdX_XXXX_YYYY",
                        "merchant_code": "NAU",
                        "api_checkout_url": "https://test.optimistic.blue/paygateWS/api/CheckOut",
                        "api_back_search_transactions": "https://test.optimistic.blue/paygateWS/api/BackOfficeSearchTransactions",
                        "api_basic_auth_user": "NAU",
                        "api_basic_auth_pass": "APassword",
                        "callback_server_allowed_networks": ["10.0.10.1"],
                    }
                },
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
            self.request,
            order_number=basket.order_number,
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
            self.request,
            order_number=basket.order_number,
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

    @mock.patch.object(PayGate, "_make_api_json_request")
    def test_callback_server_duc(self, mock__make_api_json_request):
        """
        Test the server-to-server callback with a DUC payment.
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
            "TRANSACTION_ID": "123415432432432",
            "CARD_MASKED_PAN": None,
            "PAYMENT_TYPE_CODE": "DUC",
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


PAYGATE_CONFIG_WITH_THANK_YOU = {
    "edx": {
        **settings.PAYMENT_PROCESSOR_CONFIG["edx"],
        **{
            "paygate": {
                "access_token": "PwdX_XXXX_YYYY",
                "merchant_code": "NAU",
                "api_checkout_url": "https://test.optimistic.blue/paygateWS/api/CheckOut",
                "api_back_search_transactions": (
                    "https://test.optimistic.blue/paygateWS/api/BackOfficeSearchTransactions"
                ),
                "api_basic_auth_user": "NAU",
                "api_basic_auth_pass": "APassword",
                "thank_you_url": "https://orders.example.com/thank-you",
            }
        },
    }
}


def _thank_you_config(thank_you_url):
    """
    A copy of `PAYGATE_CONFIG_WITH_THANK_YOU` with a different `thank_you_url`.
    """
    config = copy.deepcopy(PAYGATE_CONFIG_WITH_THANK_YOU)
    config["edx"]["paygate"]["thank_you_url"] = thank_you_url
    return config


class PayGateAsynchronousPaymentTests(TestCase):
    """
    Tests for the asynchronous payment flow.

    An asynchronous payment method -- on NAU the Multibanco reference (`REFMB`) --
    is not confirmed while the user is still in the browser. The success callback
    must therefore never take payment: it places a `Pending` order so the user can
    see the in-flight payment, and the payment is confirmed later, either by the
    server-to-server callback or lazily from the Order History page.
    """

    def create_basket_with_seat(self):
        course = CourseFactory(id='a/b/c', name='Demo Course', partner=self.partner)
        product = course.create_or_update_seat('test-certificate-type', False, 20)
        basket = create_basket(site=self.site, owner=UserFactory(), empty=True)
        basket.add_product(product)
        basket.save()
        return basket

    @staticmethod
    def callback_data(basket):
        return {
            "is_paid": False,
            "StatusCode": "P",
            'payment_ref': basket.order_number,
            "paymentValue": "20.00EUR",
            "payment_type_code": "REFMB",
        }

    @override_settings(PAYMENT_PROCESSOR_CONFIG=PAYGATE_CONFIG_WITH_THANK_YOU)
    @mock.patch.object(PayGate, "_make_api_json_request")
    def test_success_callback_places_a_pending_order_and_redirects_to_thank_you(
        self, mock__make_api_json_request,
    ):
        """
        With `thank_you_url` configured the success callback must:
          * NOT call the PayGate BackOfficeSearchTransactions API, because an
            asynchronous payment is not confirmed yet and asking would raise a
            GatewayError and show the user a bogus payment error.
          * create the order in the `Pending` status, so the user can see it.
          * NOT record any payment against it.
          * redirect the user to the configured Thank-You URL with the order number.
        """
        basket = self.create_basket_with_seat()

        response = self.client.get(
            reverse("ecommerce_plugin_paygate:callback_success"),
            self.callback_data(basket),
        )

        self.assertEqual(response.status_code, 302)
        self.assertIn("https://orders.example.com/thank-you", response['Location'])
        self.assertIn(f"order_number={basket.order_number}", response['Location'])

        order = Order.objects.get(number=basket.order_number)
        self.assertEqual(order.status, ORDER.PENDING)
        # A pending order must never be fulfilled: no enrolment, no invoice.
        self.assertFalse(order.is_fulfillable)
        self.assertEqual(order.sources.count(), 0)
        self.assertEqual(order.payment_events.count(), 0)

        mock__make_api_json_request.assert_not_called()

    @override_settings(PAYMENT_PROCESSOR_CONFIG=PAYGATE_CONFIG_WITH_THANK_YOU)
    @mock.patch.object(PayGate, "_make_api_json_request")
    def test_success_callback_is_idempotent(self, mock__make_api_json_request):
        """
        The user may reload the success callback. That must not create a second
        order nor change the status of the one already placed.
        """
        basket = self.create_basket_with_seat()

        self.client.get(
            reverse("ecommerce_plugin_paygate:callback_success"),
            self.callback_data(basket),
        )
        self.client.get(
            reverse("ecommerce_plugin_paygate:callback_success"),
            self.callback_data(basket),
        )

        self.assertEqual(Order.objects.filter(number=basket.order_number).count(), 1)
        self.assertEqual(
            Order.objects.get(number=basket.order_number).status, ORDER.PENDING
        )
        mock__make_api_json_request.assert_not_called()

    @override_settings(PAYMENT_PROCESSOR_CONFIG=PAYGATE_CONFIG_WITH_THANK_YOU)
    @mock.patch.object(PayGate, "handle_processor_response")
    def test_server_callback_confirms_a_pending_order(self, mock_handle_processor_response):
        """
        When the learner finally pays the Multibanco reference, PayGate calls the
        server-to-server callback. That must confirm the existing `Pending` order
        rather than bail out because "the basket already has an order", and it must
        record the payment and fulfil the order.
        """
        mock_handle_processor_response.return_value = HandledProcessorResponse(
            transaction_id="MB-TXN-1",
            total=Decimal("20.00"),
            currency="EUR",
            card_number="REFMB",
            card_type="REFMB",
        )
        basket = self.create_basket_with_seat()

        # The user came back from PayGate first: a pending order exists.
        self.client.get(
            reverse("ecommerce_plugin_paygate:callback_success"),
            self.callback_data(basket),
        )
        self.assertEqual(
            Order.objects.get(number=basket.order_number).status, ORDER.PENDING
        )

        # PayGate now notifies that the reference has been paid.
        response = self.client.post(
            reverse("ecommerce_plugin_paygate:callback_server"),
            json.dumps(self.callback_data(basket)),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        order = Order.objects.get(number=basket.order_number)
        self.assertNotEqual(order.status, ORDER.PENDING)
        self.assertEqual(order.sources.count(), 1)
        self.assertEqual(order.payment_events.count(), 1)
        self.assertEqual(order.sources.first().reference, "MB-TXN-1")

    @override_settings(PAYMENT_PROCESSOR_CONFIG=PAYGATE_CONFIG_WITH_THANK_YOU)
    @mock.patch.object(PayGate, "handle_processor_response")
    def test_server_callback_ignores_an_already_paid_order(self, mock_handle_processor_response):
        """
        Duplicated server callbacks for an order that is already paid must be
        ignored, and must not record the payment twice.
        """
        mock_handle_processor_response.return_value = HandledProcessorResponse(
            transaction_id="MB-TXN-1",
            total=Decimal("20.00"),
            currency="EUR",
            card_number="REFMB",
            card_type="REFMB",
        )
        basket = self.create_basket_with_seat()
        self.client.get(
            reverse("ecommerce_plugin_paygate:callback_success"),
            self.callback_data(basket),
        )

        for __ in range(2):
            self.client.post(
                reverse("ecommerce_plugin_paygate:callback_server"),
                json.dumps(self.callback_data(basket)),
                content_type="application/json",
            )

        order = Order.objects.get(number=basket.order_number)
        self.assertEqual(order.sources.count(), 1)
        self.assertEqual(order.payment_events.count(), 1)

    @override_settings(PAYMENT_PROCESSOR_CONFIG=PAYGATE_CONFIG_WITH_THANK_YOU)
    @mock.patch.object(PayGate, "handle_processor_response")
    def test_success_callback_uses_thank_you_for_an_already_fulfilled_order(
        self, mock_handle_processor_response,
    ):
        """
        For a synchronous method the server-to-server callback normally fulfils the
        order before the browser redirect arrives. The user must still reach the
        Thank-You page, carrying the number of the order that already exists -- no
        second order, no receipt page and no extra payment recorded.
        """
        mock_handle_processor_response.return_value = HandledProcessorResponse(
            transaction_id="CARD-TXN-4",
            total=Decimal("20.00"),
            currency="EUR",
            card_number="xxxx-1111",
            card_type="VISA",
        )
        basket = self.create_basket_with_seat()

        # The server callback lands first and fulfils the order.
        self.client.post(
            reverse("ecommerce_plugin_paygate:callback_server"),
            json.dumps(self.callback_data(basket)),
            content_type="application/json",
        )
        order = Order.objects.get(number=basket.order_number)
        self.assertNotEqual(order.status, ORDER.PENDING)

        # The user is only now redirected back from PayGate.
        response = self.client.get(
            reverse("ecommerce_plugin_paygate:callback_success"),
            self.callback_data(basket),
        )

        self.assertEqual(response.status_code, 302)
        self.assertIn("https://orders.example.com/thank-you", response['Location'])
        self.assertIn(f"order_number={basket.order_number}", response['Location'])
        self.assertEqual(Order.objects.filter(number=basket.order_number).count(), 1)
        order.refresh_from_db()
        self.assertEqual(order.sources.count(), 1)
        self.assertEqual(order.payment_events.count(), 1)

    @mock.patch.object(PayGate, "handle_processor_response")
    def test_success_callback_without_thank_you_url_keeps_the_synchronous_flow(
        self, mock_handle_processor_response,
    ):
        """
        `thank_you_url` gates the whole asynchronous flow, not just the redirect
        destination. Until a deployment configures it the previous behaviour is kept
        untouched: the payment is handled synchronously, the order is created and
        fulfilled, and the user is sent to the receipt page. No `Pending` order is
        placed and nothing relies on the server-to-server callback landing later.
        """
        mock_handle_processor_response.return_value = HandledProcessorResponse(
            transaction_id="CARD-TXN-3",
            total=Decimal("20.00"),
            currency="EUR",
            card_number="xxxx-1111",
            card_type="VISA",
        )
        basket = self.create_basket_with_seat()

        response = self.client.get(
            reverse("ecommerce_plugin_paygate:callback_success"),
            self.callback_data(basket),
        )

        self.assertEqual(response.status_code, 302)
        self.assertIn("receipt", response['Location'])
        mock_handle_processor_response.assert_called_once()
        order = Order.objects.get(number=basket.order_number)
        self.assertNotEqual(order.status, ORDER.PENDING)
        self.assertEqual(order.sources.count(), 1)
        self.assertEqual(order.payment_events.count(), 1)

    @mock.patch.object(PayGate, "handle_processor_response")
    def test_success_callback_without_thank_you_url_still_shows_the_error_page(
        self, mock_handle_processor_response,
    ):
        """
        The other half of the preserved behaviour: when PayGate cannot confirm the
        payment the user reaches the error page, exactly as before. This is the known
        bad outcome for an asynchronous payment method, and it is what configuring
        `thank_you_url` fixes.
        """
        mock_handle_processor_response.side_effect = GatewayError(
            "PayGate couldn't double check if basket has been payed"
        )
        basket = self.create_basket_with_seat()

        response = self.client.get(
            reverse("ecommerce_plugin_paygate:callback_success"),
            self.callback_data(basket),
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(Order.objects.filter(number=basket.order_number).count(), 0)

    @override_settings(PAYMENT_PROCESSOR_CONFIG=PAYGATE_CONFIG_WITH_THANK_YOU)
    @mock.patch("paygate.views.place_pending_order")
    @mock.patch.object(PayGate, "handle_processor_response")
    def test_success_callback_survives_losing_the_race_to_the_server_callback(
        self, mock_handle_processor_response, mock_place_pending_order,
    ):
        """
        For a card payment the server-to-server callback lands at almost the same
        instant as the browser redirect. If it creates the order first, the unique
        constraint on `Order.number` makes our insert fail -- and the user, who has
        just paid successfully, must NOT be sent to the payment error page.
        """
        mock_handle_processor_response.return_value = HandledProcessorResponse(
            transaction_id="CARD-TXN-1",
            total=Decimal("20.00"),
            currency="EUR",
            card_number="xxxx-1111",
            card_type="VISA",
        )
        basket = self.create_basket_with_seat()

        # The server callback wins the race and fulfils the order.
        self.client.post(
            reverse("ecommerce_plugin_paygate:callback_server"),
            json.dumps(self.callback_data(basket)),
            content_type="application/json",
        )
        # Our insert then loses on the unique constraint.
        mock_place_pending_order.side_effect = IntegrityError("duplicate order number")

        response = self.client.get(
            reverse("ecommerce_plugin_paygate:callback_success"),
            self.callback_data(basket),
        )

        # The user reaches the Thank-You page, not the error page.
        self.assertEqual(response.status_code, 302)
        self.assertIn("https://orders.example.com/thank-you", response['Location'])
        self.assertIn(f"order_number={basket.order_number}", response['Location'])
        # And there is exactly one order, the paid one.
        self.assertEqual(Order.objects.filter(number=basket.order_number).count(), 1)
        self.assertEqual(Order.objects.get(number=basket.order_number).sources.count(), 1)

    @override_settings(PAYMENT_PROCESSOR_CONFIG=PAYGATE_CONFIG_WITH_THANK_YOU)
    @mock.patch("paygate.views.place_pending_order")
    @mock.patch.object(PayGate, "handle_processor_response")
    def test_success_callback_survives_a_non_integrity_placement_error(
        self, mock_handle_processor_response, mock_place_pending_order,
    ):
        """
        The losing side of the race does not always fail on the `Order.number`
        unique constraint: `basket.submit()` rejects an already submitted basket
        with a different exception. The user has still paid, so he must reach the
        Thank-You page and not the error page.
        """
        mock_handle_processor_response.return_value = HandledProcessorResponse(
            transaction_id="CARD-TXN-2",
            total=Decimal("20.00"),
            currency="EUR",
            card_number="xxxx-1111",
            card_type="VISA",
        )
        basket = self.create_basket_with_seat()

        # The server callback wins the race and fulfils the order.
        self.client.post(
            reverse("ecommerce_plugin_paygate:callback_server"),
            json.dumps(self.callback_data(basket)),
            content_type="application/json",
        )
        mock_place_pending_order.side_effect = ValueError("basket already submitted")

        response = self.client.get(
            reverse("ecommerce_plugin_paygate:callback_success"),
            self.callback_data(basket),
        )

        self.assertEqual(response.status_code, 302)
        self.assertIn("https://orders.example.com/thank-you", response['Location'])
        self.assertIn(f"order_number={basket.order_number}", response['Location'])
        self.assertEqual(Order.objects.filter(number=basket.order_number).count(), 1)
        self.assertEqual(Order.objects.get(number=basket.order_number).sources.count(), 1)

    @override_settings(
        PAYMENT_PROCESSOR_CONFIG=_thank_you_config(
            "https://orders.example.com/thank-you?locale=pt&"
        )
    )
    @mock.patch.object(PayGate, "_make_api_json_request")
    def test_success_callback_builds_a_valid_thank_you_url(
        self, mock__make_api_json_request,  # pylint: disable=unused-argument
    ):
        """
        A `thank_you_url` that already carries a query string, and even a stray
        trailing separator, must still produce a well formed redirect.
        """
        basket = self.create_basket_with_seat()

        response = self.client.get(
            reverse("ecommerce_plugin_paygate:callback_success"),
            self.callback_data(basket),
        )

        self.assertEqual(response.status_code, 302)
        parsed = urlparse(response['Location'])
        self.assertEqual(parsed.path, "/thank-you")
        self.assertEqual(
            dict(parse_qsl(parsed.query)),
            {"locale": "pt", "order_number": basket.order_number},
        )


class PayGatePendingOrderTests(TestCase):
    """
    Tests for `paygate.pending_orders`, the module that places and confirms the
    orders of asynchronous payments.
    """

    def setUp(self):
        super().setUp()
        course = CourseFactory(id='a/b/c', name='Demo Course', partner=self.partner)
        product = course.create_or_update_seat('test-certificate-type', False, 20)
        self.basket = create_basket(site=self.site, owner=UserFactory(), empty=True)
        self.basket.add_product(product)
        self.basket.save()
        # `self.request` comes from SiteMixin, already bound to the test site and
        # registered with crum, which the order placement machinery relies on.
        self.request.user = self.basket.owner

    def test_place_pending_order_does_not_fulfil(self):
        order = place_pending_order(self.request, self.basket)

        self.assertEqual(order.status, ORDER.PENDING)
        self.assertFalse(order.is_fulfillable)
        self.assertEqual(order.sources.count(), 0)
        self.assertEqual(order.payment_events.count(), 0)
        self.basket.refresh_from_db()
        self.assertEqual(self.basket.status, Basket.SUBMITTED)

    @mock.patch.object(PayGate, "handle_processor_response")
    def test_confirm_pending_order_records_payment_and_fulfils(
        self, mock_handle_processor_response,
    ):
        mock_handle_processor_response.return_value = HandledProcessorResponse(
            transaction_id="MB-TXN-2",
            total=Decimal("20.00"),
            currency="EUR",
            card_number="REFMB",
            card_type="REFMB",
        )
        order = place_pending_order(self.request, self.basket)

        order = confirm_pending_order(self.request, self.basket, order, {})

        # The order left the Pending status and carries the payment.
        self.assertNotEqual(order.status, ORDER.PENDING)
        self.assertEqual(order.sources.count(), 1)
        self.assertEqual(order.payment_events.count(), 1)
        source = order.sources.first()
        self.assertEqual(source.reference, "MB-TXN-2")
        self.assertEqual(source.amount_debited, Decimal("20.00"))

    @mock.patch.object(PayGate, "handle_processor_response")
    def test_confirm_pending_order_leaves_it_pending_when_not_payed_yet(
        self, mock_handle_processor_response,
    ):
        """
        An unpaid Multibanco reference makes PayGate raise a GatewayError. That is
        the normal, expected outcome and must leave the order untouched so it can be
        retried on the next visit to the Order History page.
        """
        mock_handle_processor_response.side_effect = GatewayError(
            "PayGate couldn't double check if basket has been payed"
        )
        order = place_pending_order(self.request, self.basket)

        with self.assertRaises(GatewayError):
            confirm_pending_order(self.request, self.basket, order, {})

        order.refresh_from_db()
        self.assertEqual(order.status, ORDER.PENDING)
        self.assertEqual(order.sources.count(), 0)
        self.assertEqual(order.payment_events.count(), 0)

    @mock.patch.object(PayGate, "handle_processor_response")
    def test_confirm_pending_order_is_idempotent(
        self, mock_handle_processor_response,
    ):
        """
        The lazy resolution from the Order History page and the server-to-server
        callback can both confirm the same order. The second confirmation must be
        a no-op instead of recording a second payment source and event.
        """
        mock_handle_processor_response.return_value = HandledProcessorResponse(
            transaction_id="MB-TXN-4",
            total=Decimal("20.00"),
            currency="EUR",
            card_number="REFMB",
            card_type="REFMB",
        )
        order = place_pending_order(self.request, self.basket)
        order = confirm_pending_order(self.request, self.basket, order, {})
        status_after_first = order.status

        order = confirm_pending_order(self.request, self.basket, order, {})

        self.assertEqual(order.status, status_after_first)
        self.assertEqual(order.sources.count(), 1)
        self.assertEqual(order.payment_events.count(), 1)
        mock_handle_processor_response.assert_called_once()

    def test_mark_order_as_payment_error(self):
        order = place_pending_order(self.request, self.basket)

        mark_order_as_payment_error(order)

        order.refresh_from_db()
        self.assertEqual(order.status, ORDER.PAYMENT_ERROR)

    @mock.patch.object(PayGate, "handle_processor_response")
    def test_mark_order_as_payment_error_leaves_a_paid_order_alone(
        self, mock_handle_processor_response,
    ):
        mock_handle_processor_response.return_value = HandledProcessorResponse(
            transaction_id="MB-TXN-3",
            total=Decimal("20.00"),
            currency="EUR",
            card_number="REFMB",
            card_type="REFMB",
        )
        order = place_pending_order(self.request, self.basket)
        order = confirm_pending_order(self.request, self.basket, order, {})
        status_before = order.status

        mark_order_as_payment_error(order)

        order.refresh_from_db()
        self.assertEqual(order.status, status_before)
