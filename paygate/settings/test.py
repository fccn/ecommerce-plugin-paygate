"""
Settings for paygate
"""
from ecommerce.settings.test import *

PAYMENT_PROCESSORS = ('paygate.processors.PayGate',)

PAYMENT_PROCESSOR_CONFIG={
    "edx": {
        "paygate": {
            "access_token": 'PwdX_XXXX_YYYY',
            "merchant_code": "NAU",
            "api_checkout_url": 'https://test.optimistic.blue/paygateWS/api/CheckOut',
            "api_basic_auth_user": "NAU",
            "api_basic_auth_pass": "APassword",
            "payment_types": ["VISA", "MASTERCARD", "AMEX", "PAYPAL", "MBWAY", "REFMB", "DUC"]
        }
    },
    "other": {
        "paygate": {
            "access_token": 'other_PwdX_XXXX_YYYY',
            "merchant_code": "other_NAU",
            "api_checkout_url": 'https://test_other.optimistic.blue/paygateWS/api/CheckOut',
            "api_basic_auth_user": "other_NAU",
            "api_basic_auth_pass": "other_APassword",
            "payment_types": ["VISA", "MBWAY", "REFMB", "DUC"]
        }
    }
}

EXTRA_PAYMENT_PROCESSOR_URLS = {"paygate": "paygate.urls"}
