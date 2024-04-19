"""
PayGate payment processor.
"""

import base64
import datetime
import json
import logging
from decimal import Decimal

import requests
import simplejson.errors
from django.conf import settings
from django.urls import reverse
from oscar.apps.payment.exceptions import GatewayError
from oscar.core.loading import get_class, get_model
from paygate.utils import get_basket_from_payment_ref, order_exist

from ecommerce.core.url_utils import get_ecommerce_url
from ecommerce.extensions.payment.processors import (BasePaymentProcessor,
                                                     HandledProcessorResponse)

logger = logging.getLogger(__name__)
ProductClass = get_model("catalogue", "ProductClass")
OrderNumberGenerator = get_class("order.utils", "OrderNumberGenerator")


class PayGate(BasePaymentProcessor):
    """
    PayGate payment processor.

    For reference, see the Swagger sent by AMA of the PPAP service:
    Link to documentation:
    - https://cloud.ama.gov.pt/index.php/s/5jKnbXuV3ajYQQ5

    Or alternatively see the test environment swagger of the Optimistic Blue (the software house).
    - https://lab.optimistic.blue/paygateWS/swagger/index.html

    The payment processor consists of a class with some methods and constants that must be
    implemented to complete the payment flow.
    the flow of a payment.

    The flow of the payment process:

    1. Start a payment with get_transaction_parameters
    2. Redirect the user to the payment page
    3. After payment, the user is redirected to one of the success or failure callback pages
    4. When the user has payed with success, the PayGate calls the server callback, and we mark
    the payment has successful by placing an order or the basket
    5. PayGate redirects the user to the successful callback page, we check if the basket already
    as an order

    The payment processor is supposed to be configured as follows:
    ```
      paygate:
        access_token: PwdX_XXXX_YYYY
        merchant_code: NAU
        api_checkout_url: https://lab.optimistic.blue/paygateWS/api/CheckOut
        api_checkout_req_timeout_sec: 10 # optional
        api_back_search_transactions: https://lab.optimistic.blue/paygateWS/api/BackOfficeSearchTransactions
        mark_test_payment_as_paid_url: https://lab.optimistic.blue/paygateWS/api/MarkTestPaymentAsPaid
        api_back_search_transactions_timeout_seconds: 10 # optional
        api_basic_auth_user: username
        api_basic_auth_pass: password
        cancel_checkout_path: /checkout/cancel-checkout/ # optional
        error_path: /checkout/error/ # optional
        title: PayGate # optional
        payment_types: ["VISA", "MASTERCARD", "AMEX", "PAYPAL", "MBWAY", "REFMB", "DUC"]

    ```

    The `cancel_checkout_path`  and `error_path` can be optional and default to
    `PAYMENT_PROCESSOR_CANCEL_PATH` and `PAYMENT_PROCESSOR_ERROR_PATH`.


    The following code shows the methods that must be implemented in this class:
    https://github.com/openedx/ecommerce/blob/3b1fcb0ef6658ad123da3cfb1d8ceb55e569708a/ecommerce/extensions/payment/processors/__init__.py#L20-L140

    """

    # Here should be the required or returned constants that your payment processor needs to implement.
    # It's necessary to add the name of your payment processor.
    NAME = "paygate"

    # By default if there is only a payment gateway configured, we don't show
    # "Checkout with PayGate".
    # If you want to override the default `TITLE` you can add the `title` configuration.
    # TITLE = "PayGate"

    CHECKOUTS_ENDPOINT = "/v1/checkouts"

    # By default the calls to PayGate Checkout API has a time of 10 seconds
    API_REQUEST_TIMEOUT_SECONDS = 10

    DEFAULT_API_CHECKOUT_URL = "https://lab.optimistic.blue/paygateWS/api/CheckOut"
    # the default timeout that we wait to have a response of the PayGate Checkout API method
    DEFAULT_API_CHECKOUT_REQUEST_TIMEOUT_SECONDS = 10

    DEFAULT_API_BACK_SEARCH_TRANSACTIONS = (
        "https://lab.optimistic.blue/paygateWS/api/BackOfficeSearchTransactions"
    )
    DEFAULT_API_BACK_SEARCH_TRANSACTIONS_TIMEOUT_SECONDS = 10
    DEFAULT_RETRY_CALLBACK_SUCCESS_TIMEOUT_SECONDS = 10

    DEFAULT_MARK_TEST_PAYMENT_AS_PAID_URL = "https://lab.optimistic.blue/paygateWS/api/MarkTestPaymentAsPaid"
    DEFAULT_MARK_TEST_PAYMENT_AS_PAID_REQUEST_TIMEOUT_SECONDS = 10

    def __init__(self, site):
        """
        Constructs a new instance of the paygate processor, this constructor will be used to fetch
        the information that it's necessary to apply
        the logic, as minimun this should retrieve the payment page url that it's used to redirect
        the user to the payment page.

        Raises:
          KeyError: If no settings configured for this payment processor
          AttributeError: If LANGUAGE_CODE setting is not set.
        """
        super().__init__(site)
        self.access_token = self.configuration["access_token"]
        self.merchant_code = self.configuration["merchant_code"]
        self.api_basic_auth_user = self.configuration["api_basic_auth_user"]
        self.api_basic_auth_pass = self.configuration["api_basic_auth_pass"]
        self.api_checkout_url = self.configuration.get(
            "api_checkout_url", self.DEFAULT_API_CHECKOUT_URL
        )
        self.api_checkout_req_timeout_sec = self.configuration.get(
            "api_checkout_req_timeout_sec",
            self.DEFAULT_API_CHECKOUT_REQUEST_TIMEOUT_SECONDS,
        )
        self.api_back_search_transactions = self.configuration.get(
            "api_back_search_transactions",
            self.DEFAULT_API_BACK_SEARCH_TRANSACTIONS,
        )
        self.api_back_search_transactions_timeout_seconds = self.configuration.get(
            "api_back_search_transactions_timeout_seconds",
            self.DEFAULT_API_BACK_SEARCH_TRANSACTIONS_TIMEOUT_SECONDS,
        )
        self.retry_callback_success_timeout_seconds = self.configuration.get(
            "retry_callback_success_timeout_seconds",
            self.DEFAULT_RETRY_CALLBACK_SUCCESS_TIMEOUT_SECONDS,
        )
        self.payment_types = self.configuration.get(
            "payment_types",
            ["VISA", "MASTERCARD", "AMEX", "PAYPAL", "MBWAY", "REFMB", "DUC"],  # etc...
        )

        # By default if there is only a payment gateway configured, we don't show
        # "Checkout with PayGate".
        # If you want to override the default `TITLE` you can add the `title` to this payment
        # processor configuration.
        partner_short_code = self.site.siteconfiguration.partner.short_code
        payment_processors_config_count = len(
            settings.PAYMENT_PROCESSOR_CONFIG[partner_short_code.lower()]
        )
        show_title_default = payment_processors_config_count > 1
        self.TITLE = self.configuration.get(
            "title", "PayGate" if show_title_default else None
        )

        self.mark_test_payment_as_paid_url = self.configuration.get(
            "mark_test_payment_as_paid_url", self.DEFAULT_MARK_TEST_PAYMENT_AS_PAID_URL
        )
        self.mark_test_payment_as_paid_req_timeout_sec = self.configuration.get(
            "mark_test_payment_as_paid_req_timeout_sec",
            self.DEFAULT_MARK_TEST_PAYMENT_AS_PAID_REQUEST_TIMEOUT_SECONDS,
        )

    @property
    def callback_server_allowed_networks(self):
        """
        The internet protocol networks that are allowed to execute the server callback.
        """
        return self.configuration.get("callback_server_allowed_networks", None)

    @property
    def error_url(self):
        """
        The destination error URL.

        If some error is being raised by the PayGate software the user will be redirected to the
        failure callback.

        The failure callback should then redirect the user to this url.
        By default it will redirect the user to the upstream Open edX ecommerce checkout error
        page.
        """
        return get_ecommerce_url(
            self.configuration.get("error_path", reverse("checkout:error"))
        )

    @property
    def failure_url(self):
        """
        Same as the error_url property
        """
        return self.error_url

    @property
    def cancel_url(self):
        """
        The destination cancel URL.

        If the user decides to cancel the payment inside the PayGate software, he will be
        redirected to the "callback cancel" that will be redirected inside this plugin to the
        Open edX Ecommerce "cancel-checkout" view.
        """
        return get_ecommerce_url(
            self.configuration.get(
                "cancel_checkout_path", reverse("checkout:cancel-checkout")
            )
        )

    def get_transaction_parameters(
        self, basket, request=None, use_client_side_checkout=False, **kwargs
    ):  # pylint: disable=unused-argument, too-many-locals
        """
        Generate a dictionary of signed parameters required for this processor to complete a
        transaction.
        This method returns the parameters needed by the payment processor, with these parameters
        the processor will have the context of the transaction, this function returns these
        parameters as a dictionary.
        Feel free to add the necessary logic to obtain the data that your payment processor needs,
        additionally you must send the variable payment_page_url with the url of your payment
        processor, here you will also send the callback pages, so your payment processor will
        know where to redirect you when a transaction is executed, to see in which variable you
        should send them, check the documentation of
        your payment processor.

        Arguments:
          basket (Basket): The basket of products being purchased.
            request (Request, optional): A Request object which can be used to construct an
            absolute.
          URL in
            cases where one is required.
          use_client_side_checkout (bool, optional): Determines if client-side checkout should be
            used.
          **kwargs: Additional parameters.

        Returns:
          dict: Payment-processor-specific parameters required to complete a transaction,
            including a signature. At a minimum, this dict must include a `payment_page_url`
            indicating the location of the processor's hosted payment page.
        """
        logger.info("PayGate: started payment for basket %d", basket.id)

        # Create PPR early to obtain an ID that can be passed to the return urls
        success_payment_processor_response = self.record_processor_response(
            {}, transaction_id=None, basket=basket
        )

        callback_server_parms = []

        single_seat = self.get_single_seat(basket)
        if single_seat:
            course_id = single_seat.course_id

        # include course_id on the callback server params
        if course_id:
            callback_server_parms.append(
                {
                    "key": "course_id",
                    "value": course_id,
                }
            )

        paygate_checkout_request_data = {
            "ACCESS_TOKEN": self.access_token,
            "MERCHANT_CODE": self.merchant_code,
            "IS_RECURRENT": False,
            "CLIENT_NAME": basket.owner.full_name,
            # "ADDRESS_LINE_1": basket.order.billing_address.line1,
            # "ADDRESS_LINE_2": basket.order.billing_address.line2,
            # "CITY": basket.order.billing_address.city,
            # "POSTAL_CODE": basket.order.billing_address.postcode,
            # "STATE": basket.order.billing_address.state,
            # "COUNTRY_CODE": basket.order.billing_address.country,
            "EMAIL": basket.owner.email,
            "LANGUAGE": request.LANGUAGE_CODE.split("-")[0],
            # "WIDGET_MESSAGE": "string", # old field no longer in use.
            "PAYMENT_REF": basket.order_number,  # Identification of transaction
            "TRANSACTION_DESC": "\n".join(
                [line.product.title for line in basket.lines.all()]
            ),
            "CURRENCY": basket.currency,  # should be EUR
            # Transaction amount to debit the client. Decimal format: XXXXX.XX
            "TOTAL_AMOUNT": round(basket.total_incl_tax, 2),
            "PAYMENT_TYPES": self.payment_types,
            # 'REFMB_START_DATE': '2023-09-20T16:27:34.518Z',
            # 'REFMB_END_DATE': '2023-09-20T16:27:34.518Z',
            # 'REFMB_MIN_AMOUNT': 0,
            # 'REFMB_MAX_AMOUNT': 0,
            "CALLBACK_SUCCESS_URL": get_ecommerce_url(
                reverse("ecommerce_plugin_paygate:callback_success")
            ),
            "CALLBACK_CANCEL_URL": get_ecommerce_url(
                reverse("ecommerce_plugin_paygate:callback_cancel")
            ),
            "CALLBACK_FAILURE_URL": get_ecommerce_url(
                reverse("ecommerce_plugin_paygate:callback_failure")
            ),
            "CALLBACK_SERVER_URL": get_ecommerce_url(
                reverse("ecommerce_plugin_paygate:callback_server")
            ),
            "CALLBACK_SERVER_PARMS": callback_server_parms,
        }
        response_data = self._make_api_json_request(
            self.api_checkout_url,
            method="POST",
            data=paygate_checkout_request_data,
            basket=basket,
            timeout=self.api_checkout_req_timeout_sec,
            basic_auth_user=self.api_basic_auth_user,
            basic_auth_pass=self.api_basic_auth_pass,
        )

        # the URL to redirect the user
        payment_page_url = self._parse_checkout_response(response_data, "URL", basket)

        # boolean reporting transaction success/failure
        success = bool(self._parse_checkout_response(response_data, "Success", basket))

        # transaction status code
        return_code = self._parse_checkout_response(response_data, "ReturnCode", basket)

        # client friendly error message, if applicable
        short_return_message = self._parse_checkout_response(
            response_data, "ShortReturnMessage", basket
        )

        # Technical error message
        long_return_message = self._parse_checkout_response(
            response_data, "LongReturnMessage", basket
        )

        # SessionToken for use in subsequent operations within the same payment session
        session_token = self._parse_checkout_response(
            response_data, "SessionToken", basket
        )

        payment_id = self._parse_checkout_response(response_data, "PaymentID", basket)

        if not success:
            logger.warning(
                (
                    "PayGate checkout: not succeed! "
                    "for basket=%d "
                    "payment_id=%s "
                    "return code=%s "
                    "shor error message=%s "
                    "long error message=%s"
                ),
                basket.id,
                str(payment_id),
                return_code,
                short_return_message,
                long_return_message,
            )

            self._raise_api_error(
                "Not success", response_data=response_data, basket=basket
            )

        # Save payment processor response
        success_payment_processor_response.transaction_id = basket.order_number
        success_payment_processor_response.response = response_data
        success_payment_processor_response.save()

        logger.info(
            "PayGate payment: basket=%d obtained paygate payment id=%s",
            basket.id,
            str(payment_id),
        )

        parameters = {
            "payment_page_url": payment_page_url,
            "payment_form_data": {
                "SessionToken": session_token,
            },
        }
        return parameters

    def _parse_checkout_response(self, response_data, field, basket=None):
        """
        Parse a single `field` from the response received from the PayGate Checkout API.
        """
        try:
            value = response_data[field]
        except KeyError:
            dump = json.dumps(response_data)
            message = f"Could not parse '{field}' field from response: content={dump}"
            self._raise_api_error(message, response_data=response_data, basket=basket)
        return value

    @staticmethod
    def get_single_seat(basket):
        """
        Return the first product encountered in the basket with the product
        class of 'seat'.  Return None if no such products were found.
        """
        try:
            seat_class = ProductClass.objects.get(slug="seat")
        except ProductClass.DoesNotExist:
            # this occurs in test configurations where the seat product class is not in use
            return None

        for line in basket.lines.all():
            product = line.product
            if product.get_product_class() == seat_class:
                return product

        return None

    def handle_processor_response(self, response, basket=None):
        """
        Verify that the payment was successfully processed -- because "Trust, but verify".
        If payment did not succeed, raise GatewayError and log error.
        Keep in mind that your response will come with different information, so you must modify
        the fields which are obtained from the response and checked the logic that it's used to
        verify if the payment was successful.

        On PayGate we aren't using any response field.
        We use the Basket passed by argument to find on PayGate if it has been payed, with this
        decision we are using the premise "Trust, but verify".

        So we internally on this method we are calling again the PayGate.
        Search PayGate transactions for the basket that has been completed, it should be a single
        transaction on that state. If true we have double checked that the transaction has been completed
        with success and the user as payed the basket.
        It is very important to double check if it has been payed, because with this feature we
        don't need th protect by IP address the callback success URL and we can just call the
        success notification callback on the check_if_is_payed action on admin.

        Arguments:
          response (dict): Dictionary of parameters received from the payment processor.

        Keyword Arguments:
          basket (Basket): Basket being purchased via the payment processor.

        Returns:
          HandledProcessorResponse

        Raises:
          GatewayError: Indicates a general error on the part of the processor.
          Feel free to implement your own exceptions depended on your payment processor.
        """
        paygate_back_search_transactions_data = {
            "ACCESS_TOKEN": self.access_token,
            "MERCHANT_CODE": self.merchant_code,
            # since we are searching by order_number we should receive a single response
            "PAYMENT_REF": basket.order_number,
            # search only completed transactions
            "STATUS_CODE": "C",
            # Sorting parameter. Sort results ('ASC'ending or 'DESC'ending)
            # For this call we just need to know if there is a single one.
            "SORT_DIRECTION": "ASC",
            # Sorting parameter. Sort results by the specified column name.
            "SORT_COLUMN": "PAYMENT_REF",
            # Paging parameter. How many rows to retrieve from the result set.
            "NEXT_ROWS": 2,
            # Paging parameter. How many rows to skip from the result set
            "OFFSET_ROWS": 0,
        }
        search_response_data = self._make_api_json_request(
            self.api_back_search_transactions,
            method="POST",
            data=paygate_back_search_transactions_data,
            basket=basket,
            timeout=self.api_back_search_transactions_timeout_seconds,
            basic_auth_user=self.api_basic_auth_user,
            basic_auth_pass=self.api_basic_auth_pass,
        )
        logger.info(
            "Search Transactions on PayGate received the response data: %s",
            search_response_data,
        )
        confirmed_payed_on_paygate = False
        # it should be a single item that have been payed
        if len(search_response_data) == 1:
            paygate_transaction = search_response_data[0]
            confirmed_payed_on_paygate = (
                (paygate_transaction.get("MERCHANT_CODE") == self.merchant_code) and
                (paygate_transaction.get("STATUS_CODE") == "C") and
                (paygate_transaction.get("PAYMENT_REF") == basket.order_number)
            )
        if not confirmed_payed_on_paygate:
            raise GatewayError("PayGate couldn't double check if basket has been payed")

        # Example: 1.00
        total = Decimal(paygate_transaction.get("PAYMENT_AMOUNT"))

        # The currency isn't available on Search PayGate transactions
        # /api/BackOfficeSearchTransactions
        currency = basket.currency

        # Save the transaction ID returned by the payment processor.
        # It isn't the Internal PayGate Payment ID, but the upstream id depending of the payment
        # type chosen by the user inside the PayGate.
        transaction_id = paygate_transaction.get("TRANSACTION_ID")

        # Payment type (VISA, MASTERCARD, PAYPAL, MBWAY, REFMB, DUC, ...)
        # We use the `card_type` to save the payment type used.
        card_type = paygate_transaction.get("PAYMENT_TYPE_CODE")

        # Save only a mask of the card
        card_number = paygate_transaction.get("CARD_MASKED_PAN")
        if not card_number:
            card_number = card_type

        hpr = HandledProcessorResponse(
            transaction_id=transaction_id,
            total=total,
            currency=currency,
            card_number=card_number,
            card_type=card_type,
        )
        logger.info("HandledProcessorResponse is %s", hpr)
        return hpr

    def issue_credit(
        self, order_number, basket, reference_number, amount, currency
    ):  # pylint disable:too-many-arguments,unused-argument
        """
        This is currently not implemented.
        """
        logger.exception(
            "PayGate processor cannot issue credits or refunds from Open edX ecommerce."
        )

    def _make_api_json_request(
        self,
        url,
        method="GET",
        data=None,
        basket=None,
        timeout=10,
        basic_auth_user=None,
        basic_auth_pass=None,
    ):  # pylint disable=too-many-arguments
        """
        Execute an API call to the PayGate using an HTTP `method` with some `data` as payload to an
        ecommerce `basket`.
        """
        if basket:
            self.record_processor_response(
                {'url': url, 'timeout': timeout, 'data': data},
                transaction_id=basket.order_number,
                basket=basket,
            )
        requests_func = getattr(requests, method.lower())

        # All calls to PayGate require basic authentication has the 1st layer of security.
        headers = {}
        if basic_auth_pass and basic_auth_pass:
            encoded_auth = base64.b64encode(
                f"{basic_auth_user}:{basic_auth_pass}".encode()
            ).decode()
            headers = {"Authorization": f"Basic {encoded_auth}"}

        # Add standard request data
        request_data = {}
        request_data.update(data)

        logger.info("PayGate calling '%s' with payload %s", url, request_data)
        try:
            # pylint: disable=not-callable
            response = requests_func(
                url,
                json=request_data,
                headers=headers,
                timeout=timeout,
            )
        except requests.exceptions.Timeout:
            self._raise_api_error("API timeout", None, {}, basket)

        try:
            response_data = response.json()
        except (json.JSONDecodeError, simplejson.errors.JSONDecodeError):
            self._raise_api_error(
                "Could not parse JSON content from response", response, {}, basket
            )
        if response.status_code != 200:
            self._raise_api_error(
                "Invalid API response", response, response_data, basket
            )
        return response_data

    def _raise_api_error(self, message, response=None, response_data=None, basket=None):
        """
        Raise an error while integrating with PayGate, so we have a normalized way of log when
        something wasn't ok.
        """
        error_response = None
        if response is not None:
            error_response = {
                "status_code": response.status_code,
                "content": response.content.decode(),
                "data": response_data,
            }
        error = {"message": message, "response": error_response}
        entry = self.record_processor_response(
            error, transaction_id=basket.order_number if basket else None, basket=basket
        )
        logger.error(
            "Failed request to PayGate API for basket [%d], response stored in entry [%d].",
            basket.id if basket else None,
            entry.id,
            exc_info=True,
        )
        raise GatewayError(error)

    def retry_baskets_payed_in_paygate(
        self,
        from_datetime: datetime.datetime,
        to_datetime: datetime.datetime,
        offset_rows=0,
        next_rows=100,
    ):
        """
        Recover PayGate transactions that we haven't received the server call back.
        Search PayGate transactions that has been completed on a time range and
        that haven't been marked as payed inside the ecommerce.
        """
        paygate_back_search_transactions_data = {
            "ACCESS_TOKEN": self.access_token,
            "MERCHANT_CODE": self.merchant_code,
            # search only completed transactions
            "STATUS_CODE": "C",
            # Sorting parameter. Sort results ('ASC'ending or 'DESC'ending)
            # For this call we just need to know if there is a single one.
            "SORT_DIRECTION": "ASC",
            # Sorting parameter. Sort results by the specified column name.
            "SORT_COLUMN": "PAYMENT_REF",
            # Paging parameter. How many rows to retrieve from the result set.
            "NEXT_ROWS": next_rows,
            # Paging parameter. How many rows to skip from the result set
            "OFFSET_ROWS": offset_rows,
            # Filter by posted transaction datetime. If not null, only transactions
            # with posted date greater or equal to the value supplied will be returned.
            "FROM_DATETIME": from_datetime.isoformat(),
            # Filter by posted transaction datetime. If not null, only transactions
            # with posted date less or equal to the value supplied will be returned.
            "TO_DATETIME": to_datetime.isoformat(),
        }
        response_data = self._make_api_json_request(
            self.api_back_search_transactions,
            method="POST",
            data=paygate_back_search_transactions_data,
            timeout=self.api_back_search_transactions_timeout_seconds,
            basic_auth_user=self.api_basic_auth_user,
            basic_auth_pass=self.api_basic_auth_pass,
        )
        # it should be a single item that have been payed
        for paygate_transaction in response_data:
            payment_ref = paygate_transaction.get("PAYMENT_REF")
            basket = get_basket_from_payment_ref(payment_ref)
            if not basket:
                logger.warning("Can't find Basket for payment_ref=%s", payment_ref)
                continue

            if order_exist(basket):
                logger.info("Order already exists for payment_ref=%s", payment_ref)
                continue

            logger.info("Retrying callback server for payment_ref=%s", payment_ref)

            # call the callback server to retry
            self.send_callback_to_itself_to_retry(basket)

        if len(response_data) == next_rows:
            self.retry_baskets_payed_in_paygate(
                from_datetime=from_datetime,
                to_datetime=to_datetime,
                offset_rows=offset_rows + next_rows,
                next_rows=next_rows,
            )

    def send_callback_to_itself_to_retry(self, basket) -> bool:
        """
        Send the success callback to itself.
        The callback will also call the PayGate to double check.
        """
        if basket:
            payment_ref = basket.order_number

        logger.info("Sending callback to check if payment_ref=%s has been payed", payment_ref)
        # call the callback server to retry
        ecommerce_callback_server = basket.site.siteconfiguration.build_ecommerce_url(
            reverse("ecommerce_plugin_paygate:callback_server")
        )
        request_data = {
            "payment_ref": payment_ref,
            "statusCode": "C",
            "success": True,
            # so we can differentiate on the PaymentProcessorResponse object
            "retry_baskets_payed_in_paygate": "true",
        }
        response = requests.post(
            ecommerce_callback_server,
            json=request_data,
            timeout=self.retry_callback_success_timeout_seconds,
        )
        success = response.status_code == 200
        if success:
            logger.info("Successfully retried for payment_ref=%s", payment_ref)
        else:
            logger.info("Unsuccess on retried for payment_ref=%s", payment_ref)
        return success

    def mark_test_payment_as_paid(self, basket=None) -> bool:
        """
        Make a PayGate payment as paid on PayGate.
        This action is only available on testing instances of PayGate.
        """
        payment_ref = basket.order_number
        request_data = {
            "ACCESS_TOKEN": self.access_token,
            "MERCHANT_CODE": self.merchant_code,
            "PAYMENT_REF": payment_ref,
        }
        try:
            # if not 200 throws GatewayError
            self._make_api_json_request(
                self.mark_test_payment_as_paid_url,
                method="POST",
                data=request_data,
                basket=basket,
                timeout=self.mark_test_payment_as_paid_req_timeout_sec,
                basic_auth_user=self.api_basic_auth_user,
                basic_auth_pass=self.api_basic_auth_pass,
            )
            return True
        except GatewayError as ge:
            logger.warning("GatewayError error when mark_test_payment_as_paid [%s]", ge)
            return False
