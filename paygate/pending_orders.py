"""
Support for asynchronous PayGate payment methods.

Some PayGate payment types are not confirmed while the user is still in front of
the browser. The most relevant one on NAU is the Multibanco reference (`REFMB`):
PayGate hands the user an entity/reference pair that can be paid at an ATM or on
a home-banking site at any point during the following days.

For those payment types the previous design was wrong: the "success" callback
(the URL PayGate redirects the user to after he presses "Continuar") ran
`handle_payment` immediately, which asks PayGate whether the transaction is
completed. For a Multibanco reference the answer is "not yet", so a `GatewayError`
was raised and the user was shown a payment error page even though nothing had
gone wrong.

This module implements the two halves of the asynchronous flow:

* :func:`place_pending_order` creates the `Order` in the `Pending` status as soon
  as the user comes back from PayGate. The order is *not* paid and *not*
  fulfilled -- `Order.is_fulfillable` is False for `Pending`, no `PaymentSource`
  or `PaymentEvent` is attached and the `post_checkout` signal is not sent, so
  the learner is not enrolled and nothing is sent to the financial manager.
  Its only purpose is to make the in-flight payment visible to the user on the
  Order History page.

* :func:`confirm_pending_order` asks PayGate whether the payment has landed. When
  it has, the payment is recorded against the existing order, the order moves to
  `Open` and the regular Open edX fulfilment path runs, exactly as it does for a
  synchronous card payment.

Known limitation, accepted deliberately: nothing expires a `Pending` order. An
unpaid Multibanco reference leaves a submitted basket and a `Pending` order in
place indefinitely, and the learner has no self-service way to retry -- support
has to intervene. This is considered acceptable at NAU's REFMB volume. Closing
it would mean sending `REFMB_START_DATE`/`REFMB_END_DATE` to PayGate (see
`PayGate.get_transaction_parameters`, where they are currently commented out) so
both sides agree on a deadline, plus a management command that moves expired
`Pending` orders to `Payment Error` and reopens their basket.

The `Pending` and `Payment Error` statuses used here are not an invention of this
plugin: upstream ecommerce already declares them in
`ecommerce.extensions.fulfillment.status.ORDER` and already allows the
`Pending -> (Open, Payment Error)` transitions in `OSCAR_ORDER_STATUS_PIPELINE`.
Nothing in the shipped code ever set them, because `OSCAR_INITIAL_ORDER_STATUS`
is `Open`. We are filling in a slot that upstream left open, which is what lets
NAU support asynchronous payments without patching ecommerce itself.
"""

import logging

from django.db import transaction
from oscar.core.loading import get_class, get_model

from ecommerce.extensions.checkout.mixins import EdxOrderPlacementMixin
from ecommerce.extensions.fulfillment.status import ORDER

from .processors import PayGate

logger = logging.getLogger(__name__)

Order = get_model("order", "Order")
NoShippingRequired = get_class("shipping.methods", "NoShippingRequired")
OrderTotalCalculator = get_class("checkout.calculators", "OrderTotalCalculator")


class PayGateOrderPlacement(EdxOrderPlacementMixin):
    """
    Exposes the `EdxOrderPlacementMixin` order placement machinery outside of a
    view.

    `EdxOrderPlacementMixin` is normally mixed into a Django view, which is where
    it picks up `self.request` and `self.payment_processor` from. The lazy
    resolution done from the Order History page has a request but is not a
    checkout view, so this small adapter supplies both.
    """

    def __init__(self, request):
        self.request = request

    @property
    def payment_processor(self):
        """
        An instance of the PayGate payment processor bound to the current site.
        """
        return PayGate(self.request.site)


def place_pending_order(request, basket):
    """
    Place an `Order` for `basket` in the `Pending` status, without taking payment
    and without fulfilling it.

    This deliberately calls `place_order` instead of the more usual
    `EdxOrderPlacementMixin.create_order`. `create_order` goes through
    `handle_order_placement`, which ends in `handle_successful_order` and
    therefore sends `post_checkout` -- that would enrol the learner and invoice
    the purchase before a single cent has been paid.

    Arguments:
        request (HttpRequest): the current request, used for the site and for the
            order placement audit trail.
        basket (Basket): the basket to place the order for. It must have a
            strategy assigned.

    Returns:
        Order: the newly created order, in the `Pending` status.
    """
    placement = PayGateOrderPlacement(request)

    shipping_method = NoShippingRequired()
    shipping_charge = shipping_method.calculate(basket)
    order_total = OrderTotalCalculator().calculate(basket, shipping_charge)

    order = placement.place_order(
        order_number=basket.order_number,
        user=basket.owner,
        basket=basket,
        shipping_address=None,
        shipping_method=shipping_method,
        shipping_charge=shipping_charge,
        billing_address=None,
        order_total=order_total,
        status=ORDER.PENDING,
        request=request,
    )
    basket.submit()

    logger.info(
        "PayGate placed pending order [%s] for basket [%d]",
        order.number,
        basket.id,
    )
    return order


def confirm_pending_order(request, basket, order, response=None):
    """
    Ask PayGate whether `basket` has actually been paid and, if it has, record the
    payment against `order` and fulfil it.

    This runs exactly the same `handle_payment` call the synchronous flow runs, so
    a payment confirmed lazily from the Order History page is recorded in the same
    way as one confirmed by the server-to-server callback.

    Arguments:
        request (HttpRequest): the current request.
        basket (Basket): the basket being paid. It must have a strategy assigned.
        order (Order): the existing `Pending` order to confirm.
        response (dict): the raw PayGate response to hand to the processor.
            PayGate's `handle_processor_response` ignores it and re-queries the
            gateway by order number, but it is passed through for the audit trail.

    Returns:
        Order: the refreshed order.

    Raises:
        GatewayError: PayGate has not confirmed the payment yet. The order is left
            in `Pending` so it can be retried later. This is the expected outcome
            for an unpaid Multibanco reference and is not an error.
        PaymentError: the payment failed in a way that will not resolve itself.
    """
    placement = PayGateOrderPlacement(request)

    # The lazy resolution done from the Order History page and the
    # server-to-server callback can both reach this point for the same order at
    # the same time. Without a lock both would pass the "still Pending" check and
    # both would record a `PaymentSource`/`PaymentEvent`, so take a row lock on
    # the order and re-check its status while holding it. The loser of the race
    # returns the already confirmed order untouched.
    with transaction.atomic():
        order = Order.objects.select_for_update().get(pk=order.pk)
        if order.status != ORDER.PENDING:
            logger.info(
                "PayGate order [%s] is already in status [%s], nothing to confirm",
                order.number,
                order.status,
            )
            return order

        # Raises GatewayError when PayGate has not confirmed the payment yet, which
        # the caller is expected to treat as "still pending".
        placement.handle_payment(response or {}, basket)

        # `handle_payment` only caches the payment source and event, because in the
        # normal flow the order does not exist yet. Here it does, so attach them.
        placement.save_payment_details(order)

        order.set_status(ORDER.OPEN)

    logger.info(
        "PayGate confirmed payment for order [%s], moved to [%s]",
        order.number,
        order.status,
    )

    # Runs the regular post-placement path: audit log, offer assignments and the
    # `post_checkout` signal that enrols the learner and sends the transaction to
    # the financial manager.
    placement.handle_successful_order(order, request)

    try:
        placement.handle_post_order(order)
    except Exception:  # pylint: disable=broad-except
        placement.log_order_placement_exception(order.number, basket.id)

    order.refresh_from_db()
    return order


def mark_order_as_payment_error(order):
    """
    Move `order` to the `Payment Error` status, if the pipeline allows it.

    Only `Pending` orders can reach `Payment Error`, so this is a no-op for an
    order that has already been paid or fulfilled.
    """
    if order.status != ORDER.PENDING:
        return order

    order.set_status(ORDER.PAYMENT_ERROR)
    logger.warning(
        "PayGate marked order [%s] as [%s]", order.number, order.status
    )
    return order
