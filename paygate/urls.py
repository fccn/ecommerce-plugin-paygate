"""Payment processors urls file."""
from django.urls import path
from .views import PaygatePaymentResponseView

# This route will be used for the callback pages.
# The link of these pages is https://ecommerce_root_url/payment/paygate/notify/ or
# http://ecommerce_root_url/payment/paygate/notify/

urlpatterns = [
    path(r'^payment/paygate/notify/$', PaygatePaymentResponseView.as_view(), name="notify"),
]
