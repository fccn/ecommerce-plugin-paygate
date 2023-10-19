from oscar.core.loading import get_model

Order = get_model('order', 'Order')
Basket = get_model("basket", "Basket")


def order_exist(basket: Basket) -> bool:
    """
    Utility method that check if there is an Order for the Basket
    """
    return Order.objects.filter(number=basket.order_number).exists()
