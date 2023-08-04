"""
  Paygate payment processing views in these views the callback pages will be implemented
"""
import logging

from django.core.exceptions import ObjectDoesNotExist
from django.db import transaction
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from django.http import HttpResponse
from django.shortcuts import redirect
from django.views.generic import View
from oscar.apps.partner import strategy
from oscar.core.loading import get_class, get_model
from rest_framework import status

from .processors import PayGate

from ecommerce.extensions.checkout.mixins import EdxOrderPlacementMixin
from ecommerce.extensions.checkout.utils import get_receipt_page_url
from ecommerce.extensions.payment.exceptions import InvalidSignatureError


logger = logging.getLogger(__name__)

Applicator = get_class('offer.applicator', 'Applicator')
Basket = get_model('basket', 'Basket')
OrderNumberGenerator = get_class('order.utils', 'OrderNumberGenerator')



class PaygatePaymentResponseView(EdxOrderPlacementMixin, View):
  
  @property
  def payment_processor(self):
    """
      An instance of Paygate payment processor.
    """
    return PayGate(self.request.site)
  
  # Disable atomicity for the view. Otherwise, we'd be unable to commit to the database
  # until the request had concluded; Django will refuse to commit when an atomic() block
  # is active, since that would break atomicity. Without an order present in the database
  # at the time fulfillment is attempted, asynchronous order fulfillment tasks will fail.
  @method_decorator(transaction.non_atomic_requests)
  @method_decorator(csrf_exempt)
  def dispatch(self, request, *args, **kwargs):
      return super().dispatch(request, *args, **kwargs)
  
  def _get_basket(self, basket_id):
    if not basket_id:
        return None
    try:
      basket_id = int(basket_id)
      basket = Basket.objects.get(id=basket_id)
      basket.strategy = strategy.Default()
      Applicator().apply(basket, basket.owner, self.request)
      return basket
    except (ValueError, ObjectDoesNotExist):
        return None
  
  def post(self, request, *args, **kwargs):
    """
    This function will handle the callback request in case it is done via HTTP POST method
    """
    self.process_request(request)
    return HttpResponse()
  
  def get(self, request, *args, **kwargs):
    """
    This function will handle the callback request in case it is done via HTTP GET method
    """
    receipt_url= self.process_request(request)
    return redirect(receipt_url)
  
  
  def process_request(self, request,  *args, **kwargs):
    # pylint: disable=unused-argument
    """
      For this example, we implement a get method that 
      handles an incoming user that is returned to us after processing the payment
      in this case, we assume that the order number of your basket and the transaction ID comes from the request of your payment processor.
    """
    paygate_response = request.POST.dict() if request.method == "POST" else request.GET.dict()
    logger.info(paygate_response)
    order_number = paygate_response.get('order_number')
    transaction_id = paygate_response.get('transaction_id')
    basket_id = OrderNumberGenerator().basket_id(order_number)
    basket = self._get_basket(basket_id)
    ppr = self.payment_processor.record_processor_response(
        paygate_response,
        transaction_id=transaction_id,
        basket=basket,
    )
    # Explicitly delimit operations which will be rolled back if an exception occurs.
    with transaction.atomic():
      # This method have to be invoked in order to handle a payment, this method could raise an PaymentError exception.
      self.handle_payment(paygate_response, basket)
    
    receipt_url = get_receipt_page_url(
      order_number=basket.order_number,
      site_configuration=basket.site.siteconfiguration,
    )
    
    order = self.create_order(request, basket)
    
    return receipt_url
