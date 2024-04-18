from django.core.exceptions import ObjectDoesNotExist
from oscar.core.loading import get_class, get_model

from ecommerce.extensions.partner import strategy

Order = get_model("order", "Order")
Basket = get_model("basket", "Basket")
Applicator = get_class("offer.applicator", "Applicator")
OrderNumberGenerator = get_class("order.utils", "OrderNumberGenerator")


def order_exist(basket: Basket) -> bool:
    """
    Utility method that check if there is an Order for the Basket
    """
    return Order.objects.filter(number=basket.order_number).exists()


def get_basket(basket_id, request=None):
    """
    Get the Django Oscar Basket class from its id.
    """
    if not basket_id:
        return None
    try:
        basket_id = int(basket_id)
        basket = Basket.objects.get(id=basket_id)
        basket.strategy = strategy.Selector().strategy()
        if request:
            Applicator().apply(basket, basket.owner, request=request)
        return basket
    except (ValueError, ObjectDoesNotExist):
        return None


def get_basket_from_payment_ref(payment_ref):
    """
    Get the Django Oscar Basket from payment_ref used by PayGate.
    """
    basket_id = OrderNumberGenerator().basket_id(payment_ref)
    return get_basket(basket_id)
