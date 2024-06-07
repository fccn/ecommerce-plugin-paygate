from decimal import Decimal

import factory
import mock
from paygate.processors import PayGate

from ecommerce.extensions.payment.processors import HandledProcessorResponse
from ecommerce.extensions.payment.tests.processors.mixins import \
    PaymentProcessorTestCaseMixin
from ecommerce.tests.factories import UserFactory
from ecommerce.tests.testcases import TestCase


class PayGateMultipleSeatsTests(PaymentProcessorTestCaseMixin, TestCase):
    """
    The PayGate payment processor tests using the Ecommerce approach of using the
    `PaymentProcessorTestCaseMixin` class.
    """

    # Used by the upstream `PaymentProcessorTestCaseMixin` to know what payment processor we are
    # testing.
    processor_name = "paygate"
    processor_class = PayGate

    # full diff on failing
    maxDiff = None

    def setUp(self):
        """
        Create data for the tests.
        Define an user and make it as the owner of the basket.
        So we can get the user data and verify it during the tests.
        """
        super(PayGateMultipleSeatsTests, self).setUp()

        self.user = UserFactory(full_name=factory.Faker("name"))
        self.basket.owner = self.user

        # add 2 more times the same product, with a total of 3.
        self.basket.add_product(self.product)
        self.basket.add_product(self.product)

    def test_get_transaction_parameters(self):
        """
        Test the PayGate `get_transaction_parameters` method. This method calls the PayGate
        `checkout` API method, so on this test we need to mock that call, and verify the call has
        the expected input and verify if the method returns the expected output.
        """
        payment_page_url = "https://frontend-test.optimistic.blue/pay"
        session_token = "A_TOKEN_THAT_WILL_BE_USED"

        # mock the PayGate checkout call
        with mock.patch.object(
            PayGate,
            "_make_api_json_request",
            return_value={
                "URL": payment_page_url,
                "Success": True,
                "ReturnCode": "XPTO",
                "ShortReturnMessage": "A short return message",
                "LongReturnMessage": "A very long return message",
                "SessionToken": session_token,
                "PaymentID": 1234,
            },
        ) as mock__make_api_json_request:
            self.request.LANGUAGE_CODE = "en"
            self.assertEqual(
                self.processor.get_transaction_parameters(
                    self.basket, request=self.request
                ),
                {
                    "payment_page_url": payment_page_url,
                    "payment_form_data": {
                        "SessionToken": session_token,
                    },
                },
            )

        mock__make_api_json_request.assert_called_with(
            "https://test.optimistic.blue/paygateWS/api/CheckOut",
            method="POST",
            data={
                "ACCESS_TOKEN": "PwdX_XXXX_YYYY",
                "MERCHANT_CODE": "NAU",
                "IS_RECURRENT": False,
                "CLIENT_NAME": self.user.full_name,
                "EMAIL": self.user.email,
                "LANGUAGE": "en",
                "PAYMENT_REF": "EDX-100001",
                "TRANSACTION_DESC": "Seat in Demo Course with test-certificate-type certificate",
                "CURRENCY": "EUR",
                "TOTAL_AMOUNT": round(Decimal(60.00), 2),
                "PAYMENT_TYPES": [
                    "VISA",
                    "MASTERCARD",
                    "AMEX",
                    "PAYPAL",
                    "MBWAY",
                    "REFMB",
                    "DUC",
                ],
                "CALLBACK_SUCCESS_URL": "http://testserver.fake/payment/paygate/callback/success/",
                "CALLBACK_CANCEL_URL": "http://testserver.fake/payment/paygate/callback/cancel/",
                "CALLBACK_FAILURE_URL": "http://testserver.fake/payment/paygate/callback/failure/",
                "CALLBACK_SERVER_URL": "http://testserver.fake/payment/paygate/callback/server/",
                "CALLBACK_SERVER_PARMS": [
                    {
                        "key": "course_id",
                        "value": "a/b/c",
                    }
                ],
            },
            basket=self.basket,
            timeout=20,
            basic_auth_user="NAU",
            basic_auth_pass="APassword",
        )

    def test_get_transaction_parameters_payment_id_none(self):
        """
        Test the PayGate `get_transaction_parameters` method, with a `PaymentID` with a `None`
        value.
        This method calls the PayGate
        `checkout` API method, so on this test we need to mock that call, and verify the call has
        the expected input and verify if the method returns the expected output.
        """
        payment_page_url = "https://frontend-test.optimistic.blue/pay"
        session_token = "A_TOKEN_THAT_WILL_BE_USED"

        # mock the PayGate checkout call
        with mock.patch.object(
            PayGate,
            "_make_api_json_request",
            return_value={
                "URL": payment_page_url,
                "Success": True,
                "ReturnCode": "XPTO",
                "ShortReturnMessage": "A short return message",
                "LongReturnMessage": "A very long return message",
                "SessionToken": session_token,
                "PaymentID": None,
            },
        ) as mock__make_api_json_request:
            self.request.LANGUAGE_CODE = "en"
            self.assertEqual(
                self.processor.get_transaction_parameters(
                    self.basket, request=self.request
                ),
                {
                    "payment_page_url": payment_page_url,
                    "payment_form_data": {
                        "SessionToken": session_token,
                    },
                },
            )

        mock__make_api_json_request.assert_called_with(
            "https://test.optimistic.blue/paygateWS/api/CheckOut",
            method="POST",
            data={
                "ACCESS_TOKEN": "PwdX_XXXX_YYYY",
                "MERCHANT_CODE": "NAU",
                "IS_RECURRENT": False,
                "CLIENT_NAME": self.user.full_name,
                "EMAIL": self.user.email,
                "LANGUAGE": "en",
                "PAYMENT_REF": "EDX-100001",
                "TRANSACTION_DESC": "Seat in Demo Course with test-certificate-type certificate",
                "CURRENCY": "EUR",
                "TOTAL_AMOUNT": round(Decimal(60.00), 2),
                "PAYMENT_TYPES": [
                    "VISA",
                    "MASTERCARD",
                    "AMEX",
                    "PAYPAL",
                    "MBWAY",
                    "REFMB",
                    "DUC",
                ],
                "CALLBACK_SUCCESS_URL": "http://testserver.fake/payment/paygate/callback/success/",
                "CALLBACK_CANCEL_URL": "http://testserver.fake/payment/paygate/callback/cancel/",
                "CALLBACK_FAILURE_URL": "http://testserver.fake/payment/paygate/callback/failure/",
                "CALLBACK_SERVER_URL": "http://testserver.fake/payment/paygate/callback/server/",
                "CALLBACK_SERVER_PARMS": [
                    {
                        "key": "course_id",
                        "value": "a/b/c",
                    }
                ],
            },
            basket=self.basket,
            timeout=20,
            basic_auth_user="NAU",
            basic_auth_pass="APassword",
        )

    def test_handle_processor_response(self):
        """
        Test the PayGate `handle_processor_response` method.
        The method verifies that the payment has been processed correctly and successfully by the
        PayGate, this means that the `handle_processor_response` method will again call the PayGate
        to check if the basket has been payed by calling the `BackOfficeSearchTransactions` API.
        """
        # mock the PayGate checkout call
        with mock.patch.object(
            PayGate,
            "_make_api_json_request",
            return_value=[
                {
                    "MERCHANT_CODE": "NAU",
                    "STATUS_CODE": "C",
                    "PAYMENT_REF": self.basket.order_number,
                    "PAYMENT_AMOUNT": "60.00",
                    "TRANSACTION_ID": "ALONGTRANSACTIONIDENTIFICATION",
                    "CARD_MASKED_PAN": "1234",
                    "PAYMENT_TYPE_CODE": "REFMB",
                }
            ],
        ) as mock__make_api_json_request:
            self.request.LANGUAGE_CODE = "en"
            self.assertEqual(
                self.processor.handle_processor_response(
                    # response data is ignored
                    {},
                    basket=self.basket,
                ),
                # expected
                HandledProcessorResponse(
                    transaction_id="ALONGTRANSACTIONIDENTIFICATION",
                    total=round(Decimal(60.00), 2),
                    currency="EUR",
                    card_number="1234",
                    card_type="REFMB",
                ),
            )

        mock__make_api_json_request.assert_called_with(
            "https://test.optimistic.blue/paygateWS/api/BackOfficeSearchTransactions",
            method="POST",
            data={
                "ACCESS_TOKEN": "PwdX_XXXX_YYYY",
                "MERCHANT_CODE": "NAU",
                "PAYMENT_REF": self.basket.order_number,
                "STATUS_CODE": "C",
                "SORT_DIRECTION": "ASC",
                "SORT_COLUMN": "PAYMENT_REF",
                "NEXT_ROWS": 2,
                "OFFSET_ROWS": 0,
            },
            basket=self.basket,
            timeout=20,
            basic_auth_user="NAU",
            basic_auth_pass="APassword",
        )

    def test_issue_credit(self):
        pass

    def test_issue_credit_error(self):
        pass
