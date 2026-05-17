"""
PayGate payment processing views in these views the callback pages will be implemented
"""

import abc
import json
import logging
import traceback
from json.decoder import JSONDecodeError
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from django.db import IntegrityError, transaction
from django.http import (HttpResponse, HttpResponseNotAllowed,
                         HttpResponseServerError)
from django.shortcuts import redirect
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from django.views.generic import View
from oscar.apps.payment.exceptions import PaymentError
from oscar.core.loading import get_class, get_model
from paygate.utils import get_receipt_page_url

from ecommerce.extensions.checkout.mixins import EdxOrderPlacementMixin
from ecommerce.extensions.fulfillment.status import ORDER

from .ip import allowed_client_ip, get_client_ip
from .pending_orders import confirm_pending_order, place_pending_order
from .processors import PayGate
from .utils import get_basket_from_payment_ref, get_order

logger = logging.getLogger(__name__)

Applicator = get_class("offer.applicator", "Applicator")
Basket = get_model("basket", "Basket")
OrderNumberGenerator = get_class("order.utils", "OrderNumberGenerator")
PaymentProcessorResponse = get_model("payment", "PaymentProcessorResponse")


class PayGateCallbackException(Exception):
    pass


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

    def handle_payment_and_create_order(self, basket, payment_processor_response):
        """
        Handle payment and, if needed, create the order.

        Three cases are handled:

        * There is already a `Pending` order for the basket, because the user came
          back from PayGate through the success callback before the payment was
          confirmed. The payment is recorded against that existing order and the
          order is fulfilled.
        * There is already an order in any other status. This is a duplicated
          server callback and is ignored.
        * There is no order yet, which is the classic synchronous flow: handle the
          payment, create the order and fulfil it.
        """
        existing_order = get_order(basket)

        if existing_order and existing_order.status != ORDER.PENDING:
            # the basket already contains a fulfilled order.
            # we could receive duplicated server callbacks.
            logger.warning(
                "PayGate callback the basket already has an order for basket [%d]",
                basket.id,
            )
            return False

        try:
            if existing_order:
                # An asynchronous payment (e.g. a Multibanco reference) that has
                # now been paid. Confirm the pending order that was placed when
                # the user returned from PayGate.
                confirm_pending_order(
                    self.request,
                    basket,
                    existing_order,
                    payment_processor_response.response,
                )
                return True

            # This method have to be invoked in order to handle a payment,
            # this method could raise an PaymentError exception.
            self.handle_payment(payment_processor_response.response, basket)

            order = self.create_new_order(self.request, basket)
            self.run_post_order(basket, order)
        except PaymentError as exc:
            logger.exception(
                "PayGate server callback error while handling payment with a payment error for basket [%d]",
                basket.id,
            )
            raise PayGateCallbackException(
                "Error while handling payment - payment error"
            ) from exc
        except PayGateCallbackException:
            # Already logged and already the right exception type; let it through
            # untouched instead of wrapping it in itself.
            raise
        except Exception as exc:  # pylint: disable=broad-except
            logger.exception(
                "PayGate server callback error while handling payment with another error for basket [%d]",
                basket.id,
            )
            logger.error(traceback.format_exc())
            raise PayGateCallbackException("Error while handling payment - other error") from exc

        return True

    def create_new_order(self, request, basket):
        """
        Create an order for the basket.
        """
        try:
            return self.create_order(request, basket)
        except Exception as exc:  # pylint: disable=broad-except
            logger.exception(
                "PayGate server callback error while creating order for basket [%d]",
                basket.id,
            )
            raise PayGateCallbackException("Error while creating order") from exc

    def run_post_order(self, basket, order):
        """
        Run the post-order actions, swallowing any error.

        Note that this is deliberately *not* called `handle_post_order`: that name
        belongs to `EdxOrderPlacementMixin` and overriding it here would shadow the
        implementation this method calls.
        """
        try:
            self.handle_post_order(order)
        except Exception:  # pylint: disable=broad-except
            self.log_order_placement_exception(basket.order_number, basket.id)

        return True


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
            self.handle_payment_and_create_order(basket, payment_processor_response)
        except PayGateCallbackException as exp:
            return HttpResponseServerError(str(exp))

        return HttpResponse("Received server callback with success")


class PayGateCallbackSuccessResponseView(PayGateCallbackBaseResponseView):
    """
    This view is used by the PayGate frontend to redirect the user after he has payed with
    success.

    ``thank_you_url`` is an on/off switch for the whole asynchronous flow, not merely a
    choice of redirect destination. It exists so the flow is only enabled on a deployment
    that has already rolled out the Thank-You page, and it changes the behaviour of this
    view for *every* payment method at once, cards included:

    * **Without** ``thank_you_url``: the previous behaviour, unchanged. The payment is
      handled synchronously, the order is created and fulfilled, and the user is sent to
      the receipt page. This calls ``handle_processor_response``, so for an asynchronous
      payment method it still raises a ``GatewayError`` and shows the payment error page.
      That is the bug the flag fixes, kept as-is while the flag is off.

    * **With** ``thank_you_url``: this view never takes payment, for any payment type.
      It records the callback response, makes sure an order exists for the basket --
      placing a ``Pending`` one when the server-to-server callback has not already
      created a fulfilled order -- and redirects to the Thank-You page. No deployment
      gets synchronous fulfilment here once the flag is set.

    Treating every payment method the same is deliberate. The destination after a payment
    provider does not depend on how the learner paid; only the speed of the confirmation
    does, and a card is simply confirmed sooner than a Multibanco reference. Branching on
    the payment type would also misclassify MBWAY, which is asynchronous in practice
    because the payer has to approve it on a phone.

    A ``Pending`` order is not fulfilled and carries no payment record. It is resolved
    against PayGate by whichever of these happens first: the server-to-server callback,
    the ``retry_baskets_payed_in_paygate`` management command (which re-fires that
    callback for completed transactions we have not recorded, and deliberately does not
    skip ``Pending`` orders), or the learner opening the Order History page, which hits
    ``nau_extensions.OrderPaymentStatusView``. Fulfilment therefore never depends on a
    single one of those landing.
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

        thank_you_url = self.payment_processor.thank_you_url
        if not thank_you_url:
            return self.fulfil_synchronously(basket, payment_processor_response)

        order = self.get_or_place_pending_order(basket, payment_processor_response)
        if order is None:
            return redirect(self.payment_processor.error_url)

        parsed = urlparse(thank_you_url)
        query = dict(parse_qsl(parsed.query))
        query["order_number"] = order.number
        return redirect(urlunparse(parsed._replace(query=urlencode(query))))

    def fulfil_synchronously(self, basket, payment_processor_response):
        """
        The behaviour of this view before the asynchronous flow existed, kept for the
        deployments that have not configured a `thank_you_url` yet: handle the payment,
        create and fulfil the order, and send the user to the receipt page.
        """
        try:
            self.handle_payment_and_create_order(basket, payment_processor_response)
        except PayGateCallbackException:
            return redirect(self.payment_processor.error_url)

        return redirect(
            get_receipt_page_url(self.request, order_number=basket.order_number)
        )

    @staticmethod
    def get_payment_type_code(payment_processor_response):
        """
        The PayGate payment type (`VISA`, `REFMB`, `MBWAY`, ...) of a recorded callback,
        or None when it is missing. Only used for logging, so it never raises.
        """
        response = getattr(payment_processor_response, "response", None) or {}
        return response.get("payment_type_code")

    def get_or_place_pending_order(self, basket, payment_processor_response=None):
        """
        Return the `Order` of `basket`, placing a `Pending` one if it does not exist yet.

        Arguments:
            basket (Basket): the basket the user has just paid for.
            payment_processor_response (PaymentProcessorResponse): the recorded PayGate
                callback, used only to enrich the logs of a failed placement.

        Returns:
            Order: the existing or newly placed order, or None when it could not be
                placed and the caller should send the user to the error page.
        """
        order = get_order(basket)
        if order:
            logger.info(
                "PayGate success callback for basket [%d]: order [%s] already exists with status [%s]",
                basket.id,
                order.number,
                order.status,
            )
            return order

        try:
            return place_pending_order(self.request, basket)
        except IntegrityError:
            logger.info(
                "PayGate success callback for basket [%d]: the order was created "
                "concurrently by the server callback",
                basket.id,
            )
        except Exception:  # pylint: disable=broad-except
            logger.exception(
                "PayGate success callback could not place a pending order for basket [%d], "
                "payment type [%s], total [%s]",
                basket.id,
                self.get_payment_type_code(payment_processor_response),
                basket.total_incl_tax,
            )

        order = get_order(basket)
        if order is None:
            logger.error(
                "PayGate success callback has no order for basket [%d]", basket.id
            )
            return None

        logger.info(
            "PayGate success callback for basket [%d]: continuing with order [%s] "
            "in status [%s]",
            basket.id,
            order.number,
            order.status,
        )
        return order


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
