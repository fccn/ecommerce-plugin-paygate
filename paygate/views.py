"""
Paygate payment processing views in these views the callback pages will be implemented
"""
import abc
import json
import logging
import traceback

from django.core.exceptions import ObjectDoesNotExist
from django.db import transaction
from django.http import (HttpResponse, HttpResponseNotAllowed,
                         HttpResponseServerError)
from django.shortcuts import redirect
from django.utils.decorators import method_decorator
from django.utils.translation import ugettext_lazy as _
from django.views.decorators.csrf import csrf_exempt
from django.views.generic import View
from ecommerce.extensions.checkout.mixins import \
    EdxOrderPlacementMixin  # pylint: disable=import-error
from ecommerce.extensions.checkout.utils import \
    get_receipt_page_url  # pylint: disable=import-error
from ecommerce.extensions.partner import \
    strategy  # pylint: disable=import-error
from oscar.apps.payment.exceptions import \
    PaymentError  # pylint: disable=import-error
from oscar.core.loading import get_class  # pylint: disable=import-error
from oscar.core.loading import get_model  # pylint: disable=import-error

from .ip import allowed_client_ip, get_client_ip
from .processors import PayGate

logger = logging.getLogger(__name__)

Applicator = get_class("offer.applicator", "Applicator")
Basket = get_model("basket", "Basket")
OrderNumberGenerator = get_class("order.utils", "OrderNumberGenerator")
PaymentProcessorResponse = get_model("payment", "PaymentProcessorResponse")


class PaygateCallbackBaseResponseView(
    EdxOrderPlacementMixin, View, metaclass=abc.ABCMeta
):
    """
    Base class for all response views of Paygate callback's
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
        An instance of Paygate payment processor.
        """
        return PayGate(self.request.site)

    def _get_basket(self, basket_id):
        """
        Get the Django Oscar Basket class from its id.
        """
        if not basket_id:
            return None
        try:
            basket_id = int(basket_id)
            basket = Basket.objects.get(id=basket_id)
            basket.strategy = strategy.Selector().strategy()
            Applicator().apply(basket, basket.owner, self.request)
            return basket
        except (ValueError, ObjectDoesNotExist):
            return None

    def get_basket_and_record_response(self, request):
        """
        Get the basket object and save the processor response.

        Returns:
            Basket: the basket object that this callback references.
            PaymentProcessorResponse: The auditing model used to store the Paygate processor
                response.
        """
        paygate_response = (
            # if HTTP method POST then the payload is a JSON
            json.loads(request.body)
            if request.method == "POST"
            else request.GET.dict()
        )
        logger.info(paygate_response)

        # ppr = get_object_or_404(PaymentProcessorResponse, id=ppr_id)

        # Get Basket from sent from Checkout Paygate API has the call back server params.
        basket = None
        ppr = None

        transaction_id = paygate_response.get("payment_ref")
        if transaction_id:
            basket_id = OrderNumberGenerator().basket_id(transaction_id)
            basket = self._get_basket(basket_id)

            ppr = self.payment_processor.record_processor_response(
                paygate_response,
                transaction_id=transaction_id,
                basket=basket,
            )
        else:
            logger.error("Missing 'payment_ref' parameter from request")
        return basket, ppr


class PaygateCallbackServerResponseView(PaygateCallbackBaseResponseView):
    """
    A server-to-server notification that informs the ecommerce if the payment on the paygate
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

        Implementation of the server-to-server callback from Paygate to Ecommerce.
        This method should be protected with an `callback_server_allowed_networks` paygate
        configuration with a list of allowed networks to send this POST.

        To view the payload of this POST, please see the `ServerCallbackExample` Schema input of
        the Paygate Swagger.

        In case of some exception/error this method will send only the HTTP response status code
        without an user interface, because this method should be called from the Paygate.
        """

        allowed_networks = self.payment_processor.callback_server_allowed_networks
        if not allowed_networks:
            logger.warning(
                "Paygate possible security risk missing 'callback_server_allowed_networks' configuration!"
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

        payed_with_success = (
            bool(payment_processor_response.response.get("success", False))
            and payment_processor_response.response.get("statusCode", "") == "C"
        )
        if not payed_with_success:
            logger.warning(
                "Paygate server callback without success and correct statusCode of 'C'"
            )
            return HttpResponse("Incorrect success and status code", status=412)

        try:
            # Explicitly delimit operations which will be rolled back if an exception occurs.
            with transaction.atomic():
                # This method have to be invoked in order to handle a payment,
                # this method could raise an PaymentError exception.
                self.handle_payment(payment_processor_response.response, basket)
        except PaymentError:
            logger.exception(
                "Paygate server callback error while handling payment with a payment error for basket [{}]",
                basket.id,
            )
            return HttpResponseServerError(
                "Error while handling payment - payment error"
            )
        except Exception:
            logger.exception(
                "Paygate server callback error while handling payment with another error for basket [{}]",
                basket.id,
            )
            logger.error(traceback.format_exc())
            return HttpResponseServerError("Error while handling payment - other error")

        # if the basket hasn't already contain an order, create one
        if not hasattr(basket, "order"):
            # the basket already contains an order.
            # we could receive duplicated server callbacks.
            logger.warning(
                "Paygate server callback the basket already has an order for basket [{}]",
                basket.id,
            )
        else:
            # create an order for the basket
            try:
                order = self.create_order(request, basket)
            except Exception:  # pylint: disable=broad-except
                logger.exception(
                    "Paygate server callback error while creating order for basket [{}]",
                    basket.id,
                )
                return HttpResponseServerError("Error while creating order")

            try:
                self.handle_post_order(order)
            except Exception:  # pylint: disable=broad-except
                self.log_order_placement_exception(basket.order_number, basket.id)

        return HttpResponse("Received server callback with success")


class PaygateCallbackSuccessResponseView(PaygateCallbackBaseResponseView):
    """
    This view is used by the Paygate frontend to redirect the user after he has payed with
    success.
    This callback should NOT be used to fullfill the order.

    We should just check if we have received the callback server-to-server request. If yes we
    should just inform the student that he will be enrolled to the course in a couple of moments.
    If not we should inform the student that we are still waiting to receive the payment
    notification.
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
            logger.warning("Paygate no basket found on the callback success")
            return redirect(self.payment_processor.failure_url)

        receipt_url = get_receipt_page_url(
            self.request.site.siteconfiguration,
            order_number=basket.order_number,
            disable_back_button=True,
        )

        if not hasattr(basket, "order"):
            # Received the frontend success callback before received the server-to-server callback

            payed_with_success = (
                bool(payment_processor_response.response.get("is_paid", False))
                and payment_processor_response.response.get("StatusCode", "") == "C"
            )
            if not payed_with_success:
                logger.warning(
                    "Paygate server callback without success and correct statusCode of 'C'"
                )
                return HttpResponse("Incorrect success and status code", status=412)

            try:
                # Explicitly delimit operations which will be rolled back if an exception occurs.
                with transaction.atomic():
                    # This method have to be invoked in order to handle a payment,
                    # this method could raise an PaymentError exception.
                    self.handle_payment(payment_processor_response.response, basket)
            except PaymentError:
                return redirect(self.payment_processor.error_url)
            except (
                Exception
            ) as exp:  # pylint: disable=broad-exception-caught,unused-variable
                logger.exception(
                    "Attempts to handle payment for basket [{}] failed.", basket.id
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
        #   basked already has an order, ok the Paygate already has successfully called the server
        #      callback.

        return redirect(receipt_url)


class PaygateCallbackRedirectResponseView(PaygateCallbackBaseResponseView):
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
        The URL that this view should redirect when it is called by the Paygate.
        """
        raise NotImplementedError


class PaygateCallbackCancelResponseView(PaygateCallbackRedirectResponseView):
    """
    This view is used by Paygate frontend to redirect the user after he has cancel the payment on
    the Paygate user interface.
    """

    def url_to_redirect(self):
        return self.payment_processor.cancel_url


class PaygateCallbackFailureResponseView(PaygateCallbackRedirectResponseView):
    """
    This view is used by Paygate frontend to redirect the user when some error has been raised
    inside the Paygate.
    """

    def url_to_redirect(self):
        return self.payment_processor.failure_url
