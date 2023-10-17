"""Payment processors urls file."""
from django.urls import path

from .views import (PayGateCallbackCancelResponseView,
                    PayGateCallbackFailureResponseView,
                    PayGateCallbackServerResponseView,
                    PayGateCallbackSuccessResponseView)

# This route will be used for the callback pages.
# The link of these pages are:
# - http://ecommerce_root_url/payment/paygate/callback/server/
# - http://ecommerce_root_url/payment/paygate/callback/success/
# - http://ecommerce_root_url/payment/paygate/callback/cancel/
# - http://ecommerce_root_url/payment/paygate/callback/failure/

app_name = "ecommerce_plugin_paygate"  # pylint: disable=invalid-name
urlpatterns = [
    # server-to-server notification this is the one that fullfills and create the order to
    # fullfill (will enroll the student).
    path(
        r"callback/server/",
        PayGateCallbackServerResponseView.as_view(),
        name="callback_server",
    ),
    # other notifications
    # PayGate redirects the user after he has payed
    path(
        r"callback/success/",
        PayGateCallbackSuccessResponseView.as_view(),
        name="callback_success",
    ),
    # PayGate redirects the user if he has cancel the payment
    path(
        r"callback/cancel/",
        PayGateCallbackCancelResponseView.as_view(),
        name="callback_cancel",
    ),
    # PayGate redirects the user if the payment has finish with some error
    path(
        r"callback/failure/",
        PayGateCallbackFailureResponseView.as_view(),
        name="callback_failure",
    ),
]
