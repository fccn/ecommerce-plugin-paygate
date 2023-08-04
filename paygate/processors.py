"""
PayGate payment processor.
"""

import logging
from decimal import Decimal

from ecommerce.extensions.payment.processors import BasePaymentProcessor, HandledProcessorResponse

logger = logging.getLogger(__name__)


class PayGate(BasePaymentProcessor):
  """
  PayGate payment processor.
  
  For reference, see
  Please add the link documentation here that you use to create the logic of your payment processor.
  
  The payment processor consists of a class with some methods and constants that must be implemented to complete the payment flow.
  the flow of a payment.
  
  The flow of the payment process:

  1. Start a payment with get_transaction_parameters
  2. Redirect the user to the payment page
  3. After payment, the user is redirected to one of the success or failure callback pages
  4. On the successful callback page, we check if the payment was successful with handle_processor_response
  
  
  The following code shows the methods that must be implemented in this class:
  https://github.com/openedx/ecommerce/blob/3b1fcb0ef6658ad123da3cfb1d8ceb55e569708a/ecommerce/extensions/payment/processors/__init__.py#L20-L140
  
  """
  
  # Here should be the required or returned constants that your payment processor needs to implement.
  # It's necessary to add the name of your payment processor.
  NAME = 'paygate'
  CHECKOUTS_ENDPOINT = '/v1/checkouts'
  
  def __init__(self, site):
    """
    Constructs a new instance of the paygate processor, this constructor will be used to fetch the information that it's necessary to apply
    the logic, as minimun this should retrieve the payment page url that it's used to redirect the user to the payment page.

    Raises:
      KeyError: If no settings configured for this payment processor
      AttributeError: If LANGUAGE_CODE setting is not set.
    """
    super().__init__(site)
    configuration = self.configuration
    self.payment_page_url = configuration['payment_page_url']
    self.some_value = configuration['some_value']
  
  def get_transaction_parameters(self, basket, **kwargs):
    """
    This method returns the parameters needed by the payment processor, with these parameters the processor will have the context of the transaction, this function returns these parameters as a dictionary.
    Feel free to add the necessary logic to obtain the data that your payment processor needs, additionally you must send the variable payment_page_url with the url of your payment processor, Hgre you will also send the callback pages, so your payment processor will 
    know where to redirect you when a transaction is executed, to see in which variable you should send them, check the documentation of 
    your payment processor.
    
    Arguments:
      basket (Basket): The basket of products being purchased.
      kwargs: Key arguments.

    Returns:
      dict: Payment-processor-specific parameters required to complete a transaction, including a signature.
    """
    parameters = {
      'payment_page_url': self.payment_page_url,
      'order_number': basket.order_number,
      'some_required_values': self.some_value
    }
    return parameters
  
  def handle_processor_response(self, response, basket=None):
    """
    Verify that the payment was successfully processed -- because Trust but Verify.
    If payment did not succeed, raise GatewayError and log error.
    Keep in mind that your response will come with different information, so you must modify the fields
    which are obtained from the response and checked the logic that it's used to verify if the payment was
    successful.

    Arguments:
        response (dict): Dictionary of parameters received from the payment processor.

    Keyword Arguments:
        basket (Basket): Basket being purchased via the payment processor.

    Raises:
        GatewayError: Indicates a general error on the part of the processor.
        Feel free to implement your own exceptions depended on your payment processor.
    """
    currency = response.get('currency')
    total = Decimal(response.get('total'))
    transaction_id = response.get('transaction_id')
    card_number = response.get('card_number', '')
    card_type = response.get('card_type', '')
    
    return HandledProcessorResponse(
      transaction_id=transaction_id,
      total=total,
      currency=currency,
      card_number=card_number,
      card_type=card_type
    )
  
  def issue_credit(self, order_number, basket, reference_number, amount, currency):
    """
    This is currently not implemented.
    """
    logger.exception(
        'PayGate processor cannot issue credits or refunds from Open edX ecommerce.'
    )
