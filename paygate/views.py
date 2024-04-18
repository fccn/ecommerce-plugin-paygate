"""
PayGate payment processing views in these views the callback pages will be implemented
"""

import abc
import json
import logging
import traceback
from json.decoder import JSONDecodeError

from django.db import transaction
from django.http import (HttpResponse, HttpResponseNotAllowed,
                         HttpResponseServerError)
from django.shortcuts import redirect
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from django.views.generic import View
from oscar.apps.payment.exceptions import PaymentError
from oscar.core.loading import get_class, get_model

from ecommerce.extensions.checkout.mixins import EdxOrderPlacementMixin
from ecommerce.extensions.checkout.utils import get_receipt_page_url

from .ip import allowed_client_ip, get_client_ip
from .processors import PayGate
from .utils import get_basket_from_payment_ref, order_exist

logger = logging.getLogger(__name__)

Applicator = get_class("offer.applicator", "Applicator")
Basket = get_model("basket", "Basket")
OrderNumberGenerator = get_class("order.utils", "OrderNumberGenerator")
PaymentProcessorResponse = get_model("payment", "PaymentProcessorResponse")


class PayGateCallbackBaseResponseView(
    EdxOrderPlacementMixin, View, metaclass=abc.ABCMeta
):
    """
    Base class for all response views of PayGate callback's
    """

    @method_decorator(transaction.non_atomic_requests)
    @method_decorator(csrf_exempt)
    def dispatch(self, request, *args, **kwargs):
        """
        Disable atomicity for the view. Otherwise, we'd be unable to commit to the database
        until the request had concluded; Django will refuse to commit when an atomic() block
        is active, since that would break atomicity. Without an order present in the database
        at the time fulfillment is attempted, asynchronous order fulfillment tasks will fail.
        """
        return super().dispatch(request, *args, **kwargs)

    @property
    def payment_processor(self):
        """
        An instance of PayGate payment processor.
        """
        return PayGate(self.request.site)

    def get_basket_and_record_response(self, request):
        """
        Get the basket object and save the processor response.

        Returns:
            Basket: the basket object that this callback references.
            PaymentProcessorResponse: The auditing model used to store the PayGate processor
                response.
        """
        if request.method == "POST":
            # if HTTP method POST then the payload is a JSON
            try:
                paygate_response = json.loads(request.body)
            except JSONDecodeError:
                logger.warning("Error decoding request body as JSON")
                paygate_response = {}
        else:
            paygate_response = request.GET.dict()
        # logger.info("paygate_response: %s", paygate_response)

        # ppr = get_object_or_404(PaymentProcessorResponse, id=ppr_id)

        # Get Basket from sent from Checkout PayGate API has the call back server params.
        basket = None
        ppr = None

        payment_ref = paygate_response.get("payment_ref")
        if payment_ref:
            basket = get_basket_from_payment_ref(payment_ref)

            ppr = self.payment_processor.record_processor_response(
                paygate_response,
                transaction_id=payment_ref,
                basket=basket,
            )
        else:
            logger.warning("Missing 'payment_ref' parameter from request")
        return basket, ppr


class PayGateCallbackServerResponseView(PayGateCallbackBaseResponseView):
    """
    A server-to-server notification that informs the Ecommerce if the payment on the PayGate
    has been with success or not.
    The decision is based on the payload of this call.
    """

    def get(self, request, *args, **kwargs):  # pylint: disable=unused-argument
        """
        Handle the callback request if it is done via HTTP GET method.

        It will send an HTTP 405 response indicating that the GET is not allowed and the client
        should send it using a POST HTTP method.
        """
        return HttpResponseNotAllowed(["POST"])

    def post(self, request, *args, **kwargs):  # pylint: disable=unused-argument
        """
        This function will handle the callback request in case it is done via HTTP POST method

        Implementation of the server-to-server callback from PayGate to Ecommerce.

        To view the payload of this POST, please see the `ServerCallbackExample` Schema input of
        the PayGate Swagger.

        In case of some exception/error this method will send only the HTTP response status code
        without an user interface, because this method should be called from the PayGate server.

        Internally this method will call the BackOfficeSearchTransactions to double check that the
        transaction is really payed. With this design decision we don't need to protect the
        callbacks URLs by IP.
        """

        allowed_networks = self.payment_processor.callback_server_allowed_networks
        if not allowed_networks:
            logger.warning(
                "PayGate possible security risk missing 'callback_server_allowed_networks' configuration!"
            )
        if allowed_networks and not allowed_client_ip(
            get_client_ip(request),
            allowed_networks,
        ):
            return HttpResponse("Unauthorized invalid allowed ip address", status=401)
        # else: the client ip is allowed

        (basket, payment_processor_response) = self.get_basket_and_record_response(
            request
        )

        if not basket:
            logger.warning(
                "PayGate server callback without payment_ref"
            )
            return HttpResponse(
                "Incorrect payment_ref", status=412
            )

        try:
            # Explicitly delimit operations which will be rolled back if an exception occurs.
            with transaction.atomic():
                # This method have to be invoked in order to handle a payment,
                # this method could raise an PaymentError exception.
                self.handle_payment(payment_processor_response.response, basket)
        except PaymentError:
            logger.exception(
                "PayGate server callback error while handling payment with a payment error for basket [%d]",
                basket.id,
            )
            return HttpResponseServerError(
                "Error while handling payment - payment error"
            )
        except Exception:  # pylint: disable=broad-except
            logger.exception(
                "PayGate server callback error while handling payment with another error for basket [%d]",
                basket.id,
            )
            logger.error(traceback.format_exc())
            return HttpResponseServerError("Error while handling payment - other error")

        # if the basket hasn't already contain an order, create one
        if order_exist(basket):
            # the basket already contains an order.
            # we could receive duplicated server callbacks.
            logger.warning(
                "PayGate server callback the basket already has an order for basket [%d]",
                basket.id,
            )
        else:
            # create an order for the basket
            try:
                order = self.create_order(request, basket)
            except Exception:  # pylint: disable=broad-except
                logger.exception(
                    "PayGate server callback error while creating order for basket [%d]",
                    basket.id,
                )
                return HttpResponseServerError("Error while creating order")

            try:
                self.handle_post_order(order)
            except Exception:  # pylint: disable=broad-except
                self.log_order_placement_exception(basket.order_number, basket.id)

        return HttpResponse("Received server callback with success")


class PayGateCallbackSuccessResponseView(PayGateCallbackBaseResponseView):
    """
    This view is used by the PayGate frontend to redirect the user after he has payed with
    success.
    This callback should NOT be used to fullfill the order.

    Internally this method will call the BackOfficeSearchTransactions to double check that the
    transaction is really payed. With this design decision we don't need to protect the
    callbacks URLs by IP.
    """

    def get(
        self, request, *args, **kwargs
    ):  # pylint: disable=unused-argument,too-many-return-statements
        """
        This function will handle the callback request in case it is done via HTTP GET method
        """
        (basket, payment_processor_response) = self.get_basket_and_record_response(
            request
        )
        if not basket:
            logger.warning("PayGate no basket found on the callback success")
            return redirect(self.payment_processor.failure_url)

        receipt_url = get_receipt_page_url(
            self.request.site.siteconfiguration,
            order_number=basket.order_number,
            disable_back_button=True,
        )

        if not order_exist(basket):
            # Received the frontend success callback before received the server-to-server callback

            try:
                # Explicitly delimit operations which will be rolled back if an exception occurs.
                with transaction.atomic():
                    # This method have to be invoked in order to handle a payment,
                    # this method could raise an PaymentError exception.
                    self.handle_payment(payment_processor_response.response, basket)
            except PaymentError:
                return redirect(self.payment_processor.error_url)
            except Exception:  # pylint: disable=broad-except
                logger.exception(
                    "Attempts to handle payment for basket [%d] failed.", basket.id
                )
                logger.error(traceback.format_exc())
                return redirect(receipt_url)

            try:
                order = self.create_order(request, basket)
            except Exception:  # pylint: disable=broad-except
                return redirect(receipt_url)

            try:
                self.handle_post_order(order)
            except Exception:  # pylint: disable=broad-except
                self.log_order_placement_exception(basket.order_number, basket.id)

            return redirect(receipt_url)
        # else
        #   basked already has an order, ok the PayGate already has successfully called the server
        #      callback.

        return redirect(receipt_url)


class PayGateCallbackRedirectResponseView(PayGateCallbackBaseResponseView):
    """
    This is base view for callbacks that just redirect the user
    """

    def get(self, request, *args, **kwargs):  # pylint: disable=unused-argument
        """
        This function will handle the callback request in case it is done via HTTP GET method
        """
        self.get_basket_and_record_response(request)
        return redirect(self.url_to_redirect())

    @abc.abstractmethod
    def url_to_redirect(self):
        """
        The URL that this view should redirect when it is called by the PayGate.
        """
        raise NotImplementedError


class PayGateCallbackCancelResponseView(PayGateCallbackRedirectResponseView):
    """
    This view is used by PayGate frontend to redirect the user after he has cancel the payment on
    the PayGate user interface.
    """

    def url_to_redirect(self):
        return self.payment_processor.cancel_url


class PayGateCallbackFailureResponseView(PayGateCallbackRedirectResponseView):
    """
    This view is used by PayGate frontend to redirect the user when some error has been raised
    inside the PayGate.
    """

    def url_to_redirect(self):
        return self.payment_processor.failure_url
