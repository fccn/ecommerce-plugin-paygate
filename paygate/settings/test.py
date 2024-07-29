"""
Settings for paygate
"""
from ecommerce.settings.test import *

PAYMENT_PROCESSORS = ('paygate.processors.PayGate',)
PAYMENT_PROCESSOR_CONFIG_DEFAULT = PAYMENT_PROCESSOR_CONFIG
PAYMENT_PROCESSOR_CONFIG={
    "edx": {
        **PAYMENT_PROCESSOR_CONFIG["edx"], 
        **{
            "paygate": {
                "access_token": 'PwdX_XXXX_YYYY',
                "merchant_code": "NAU",
                "api_checkout_url": 'https://test.optimistic.blue/paygateWS/api/CheckOut',
                "api_back_search_transactions": "https://test.optimistic.blue/paygateWS/api/BackOfficeSearchTransactions",
                "mark_test_payment_as_paid_url": "https://test.optimistic.blue/paygateWS/api/MarkTestPaymentAsPaid",
                "api_basic_auth_user": "NAU",
                "api_basic_auth_pass": "APassword",
                "payment_types": ["VISA", "MASTERCARD", "AMEX", "PAYPAL", "MBWAY", "REFMB", "DUC"]
            }
        },
    },
    "other": {
        **PAYMENT_PROCESSOR_CONFIG["other"],
        ** {
            "paygate": {
                "access_token": 'other_PwdX_XXXX_YYYY',
                "merchant_code": "other_NAU",
                "api_checkout_url": 'https://test_other.optimistic.blue/paygateWS/api/CheckOut',
                "api_back_search_transactions": "https://test_other.optimistic.blue/paygateWS/api/BackOfficeSearchTransactions",
                "mark_test_payment_as_paid_url": "https://test_other.optimistic.blue/paygateWS/api/MarkTestPaymentAsPaid",
                "api_basic_auth_user": "other_NAU",
                "api_basic_auth_pass": "other_APassword",
                "payment_types": ["VISA", "MBWAY", "REFMB", "DUC"]
            }
        }
    }
}

EXTRA_PAYMENT_PROCESSOR_URLS = {"paygate": "paygate.urls"}

OSCAR_DEFAULT_CURRENCY = 'EUR'

# Change the default ecommerce/settings/test.py setting so we don't have to collect the static files prior to running the tests.
# And fix different compressable errors like: UncompressableFileError
COMPRESS_ENABLED = False
COMPRESS_OFFLINE = False
COMPRESS_PRECOMPILERS = ()
COMPRESS_CSS_FILTERS = []
