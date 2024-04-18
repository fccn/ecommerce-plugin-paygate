from django.conf import settings
from django.contrib import admin, messages
from django.utils.translation import gettext_lazy as _
from oscar.core.loading import get_model
from paygate.processors import PayGate

from ecommerce.extensions.basket.admin import BasketAdminExtended

Basket = get_model("basket", "basket")

admin.site.unregister((Basket,))


@admin.register(Basket)
class BasketAdminExtendedPaygate(BasketAdminExtended):
    """
    Extended PayGate Basket Django Administration screen with custom actions.
    """

    @admin.action(description=_("Check if is payed on PayGate"))
    def check_if_is_payed(self, request, queryset):
        """
        Django admin action that permit to check/retry if the basket has been payed on PayGate.
        """
        for basket in queryset:
            site = basket.site
            paygate = PayGate(site)
            success = paygate.send_callback_to_itself_to_retry(basket)
            if success:
                self.message_user(
                    request,
                    _(
                        "Check if is payed on PayGate with success.",
                    ),
                    messages.SUCCESS,
                )
            else:
                self.message_user(
                    request,
                    _(
                        "Check if is payed on PayGate with an error.",
                    ),
                    messages.ERROR,
                )

    @admin.action(description=_("Mark test payment as payed on PayGate"))
    def mark_test_payment_as_paid(self, request, queryset):
        """
        Django admin action that permit to edit Paygate telling the payment has been payed.
        This method is only available on not production Paygate instances.
        """
        for basket in queryset:
            site = basket.site
            paygate = PayGate(site)
            success = paygate.mark_test_payment_as_paid(basket=basket)
            if success:
                self.message_user(
                    request,
                    _(
                        "Mark test payment as payed on PayGate with success.",
                    ),
                    messages.SUCCESS,
                )
            else:
                self.message_user(
                    request,
                    _(
                        "Mark test payment as payed on PayGate with an error.",
                    ),
                    messages.ERROR,
                )

    actions = [check_if_is_payed] + (
        [mark_test_payment_as_paid]
        if getattr(settings, "MARK_TEST_PAYMENT_AS_PAID_ACTION_AVAILABLE", True)
        else []
    )
