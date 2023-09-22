"""Payment processors urls file."""
from django.conf.urls import url
from django.urls import path

from .views import *

# This route will be used for the callback pages.
# The link of these pages are:
# - http://ecommerce_root_url/payment/paygate/callback/server/
# - http://ecommerce_root_url/payment/paygate/callback/success/
# - http://ecommerce_root_url/payment/paygate/callback/cancel/
# - http://ecommerce_root_url/payment/paygate/callback/failure/

app_name = "ecommerce_plugin_paygate"
urlpatterns = [
    # server-to-server notification this is the one that fullfills and create the order to
    # fullfill (will enroll the student).
    path(
        r"callback/server/",
        PaygateCallbackServerResponseView.as_view(),
        name="callback_server",
    ),
    # other notifications
    # Paygate redirects the user after he has payed
    path(
        r"callback/success/",
        PaygateCallbackSuccessResponseView.as_view(),
        name="callback_success",
    ),
    # Paygate redirects the user if he has cancel the payment
    path(
        r"callback/cancel/",
        PaygateCallbackCancelResponseView.as_view(),
        name="callback_cancel",
    ),
    # Paygate redirects the user if the payment has finish with some error
    path(
        r"callback/failure/",
        PaygateCallbackFailureResponseView.as_view(),
        name="callback_failure",
    ),
]
