==================================================================================
PayGate payment processor for Open edX
==================================================================================


This is a placeholder payment processor for the `Ecommerce <https://edx-ecommerce.readthedocs.io/en/latest/>`__ 
application from `Open edX <https://open.edx.org/>`__.

This plugin was bootstraped by `eduNEXT <https://www.edunext.co/>`__ and 
implemented by the `NAU FCCN team <https://www.fccn.pt>`__ to work specifically with 
the `Tutor <https://docs.tutor.overhang.io/>`__ Open edX distribution. 
The following installation instructions should work wit the 
`tutor-ecommerce plugin <https://github.com/overhangio/tutor-ecommerce>`__, 
but there is no reason to believe that it shouldn't also work with the Open edX native installation.

This guide is based in the `openedx-saferpay <https://github.com/epfl-cede/openedx-saferpay/tree/master>`__ README.

Other projects that this project receive inspiration:
- https://github.com/epfl-cede/openedx-saferpay
- https://github.com/nelc/ecommerce-hyperpay
- https://github.com/eduNEXT/ecommerce-extensions/tree/ee25624582c8e42b7eb998fda54358a7025c2dce/ecommerce_extensions/payment/processors
- https://github.com/open-craft/ecommerce-paytabs

Tutor
===============

Install the following version of tutor-ecommerce as it contains special code to avoid the usage of discovery service for development purposes:

    pip install git+https://github.com/eduNEXT/tutor-ecommerce@nau/v14.0.1#egg=tutor-ecommerce==v14.0.1

Make sure that the ecommerce plugin is enabled::

    tutor plugins enable ecommerce

Make sure that the discovery and mfe plugins are disabled::

    tutor plugins disable mfe
    tutor plugins disable discovery

Add the PayGate payment processor to the Docker image::

    tutor config save \
        --set 'ECOMMERCE_EXTRA_PIP_REQUIREMENTS=["https://github.com/fccn/ecommerce-plugin-paygate"]'
    tutor images build ecommerce

Then configure your Ecommerce instance to use the PayGate payment processor::

    tutor config save --set 'ECOMMERCE_ENABLED_PAYMENT_PROCESSORS=["paygate"]'
    tutor config save --set 'ECOMMERCE_EXTRA_PAYMENT_PROCESSOR_CLASSES=["paygate.processor.PayGate"]'
    tutor config save --set 'ECOMMERCE_EXTRA_PAYMENT_PROCESSOR_URLS={"paygate": "paygate.urls"}'

Save your PayGate credentials to paygate.yml::

    $ cat paygate.yml
    paygate:
        access_token: PwdX_XXXX_YYYY
        merchant_code: NAU
        api_checkout_url: https://lab.optimistic.blue/paygateWS/api/CheckOut
        api_checkout_req_timeout_sec: 10 # optional
        api_back_search_transactions: https://lab.optimistic.blue/paygateWS/api/BackOfficeSearchTransactions
        api_back_search_transactions_timeout_seconds: 10 # optional
        api_basic_auth_user: username
        api_basic_auth_pass: password
        cancel_checkout_path: /checkout/cancel-checkout/ # optional
        error_path: /checkout/error/ # optional
        title: PayGate # optional
        payment_types: ["VISA", "MASTERCARD", "AMEX", "PAYPAL", "MBWAY", "REFMB", "DUC"]
    $ tutor config save --set "ECOMMERCE_PAYMENT_PROCESSORS=$(cat paygate.yml)"

    The `cancel_checkout_path` and `error_path` are optional.

Run initialization scripts::

    tutor local quickstart

Enable the PayGate payment backend::

    tutor local run ecommerce ./manage.py waffle_switch --create payment_processor_active_paygate on

All payments will then proceed through the PayGate payment processor.


Devstack
===============

Next, it is described the instructions to run the development environmen using the Open edX `Devstack <https://github.com/openedx/devstack>`__.

If you are using some internal FCCN IaaS VM, please use FCCN forked `Devstack <https://github.com/fccn/devstack>`__ for that Open edX release.


Troubleshooting
-----------------

If the service `frontend-app-payment` didn't start and has this on the docker logs::

    sh: 1: fedx-scripts: not found

The reason was because the `npm install` were raising some error::

    Invalid tag name ">=^16.0.0" of package "react@>=^16.0.0": Tags may not have any characters that encodeURIComponent encodes.

To fix run this inside the container::

    npm install --legacy-peer-deps

Configuration
===============

To develop using the devstack edit the `ecommerce/settings/private.py` file add change to::

    PAYMENT_PROCESSOR_CONFIG = {
        "edx": {
            "paygate": {
                "access_token": 'PwdX_XXXX_YYYY',
                "merchant_code": "NAU",
                "api_checkout_url": 'https://lab.optimistic.blue/paygateWS/api/CheckOut',
                "api_basic_auth_user": "NAU",
                "api_basic_auth_pass": "APassword",
                "payment_types": ["VISA", "MASTERCARD", "AMEX", "PAYPAL", "MBWAY", "REFMB", "DUC"]
            }
        }
    }
    PAYMENT_PROCESSORS = ("paygate.processors.PayGate",)
    EXTRA_PAYMENT_PROCESSOR_URLS = {"paygate": "paygate.urls"}
    OSCAR_DEFAULT_CURRENCY = 'EUR'
    
    LANGUAGE_CODE = "pt"
    from django.utils.translation import ugettext_lazy as _
    LANGUAGES = (
        ('pt-pt', _('Português')),
        ('en', _('English')),
    )
    LOGO_URL = "https://lms.nau.edu.pt/static/nau-basic/images/nau_azul.svg"

    # Use custom tax strategy
    NAU_EXTENSION_OSCAR_STRATEGY_CLASS = "ecommerce_plugin_paygate.strategy.DefaultStrategy"

    # Configure tax as 23% used in Portugal
    NAU_EXTENSION_TAX_RATE = "0.298701299" # = 0.23/0.77


Clone the repository https://github.com/fccn/ecommerce-plugin-paygate to the `src` folder of the devstack (the parent `src` folder of the devstack folder)

Install this plugin inside the ecommerce container::

    make dev.shell.ecommerce
    pip install -e /edx/src/ecommerce-plugin-paygate

Restart ecommerce application::

    make dev.restart-container.ecommerce

On the Open edX Ecommerce user interface it is need to activate the PayGate payment processor.
To activate the `paygate` add switch with the name `payment_processor_active_paygate` on
http://localhost:18130/admin/waffle/switch/.

On ecommerce Django admin site configuration,
http://localhost:18130/admin/core/siteconfiguration/1/change/
- disable Microfrontend for Basket Page
- replace payment processors from `cybersource,paypal` to `paygate`

To run the tests and linting inside the Ecommerce container using Devstack run::
    make -C /edx/src/ecommerce-plugin-paygate/ test lint

Callbacks
===============

There are different callbacks that the PayGate uses.
The success, cancel and failure callbacks are used to redirect the user after he has payed with success,
has cancel the payment inside the PayGate user interface or some error has been raised.

Additionally, there is also a server-to-server callback, the PayGate calls the Ecommerce informing
that some payment reference has been payed.

Example of the server callback, change the `payment_ref` with your basked identification::

    curl -d '{"statusCode":"C", "success":"true", "MerchantCode":"NAUFCCN", "returnCode":"ABCDEFGHI", "shortMsg":"Opera%C3%A7%C3%A3o%20bem%20sucedida", "name": "edx", "is_paid": "true", "paymentValue": "1.00", "payment_ref": "EDX-100019"}' -H "Content-Type: application/json" -X POST http://localhost:18130/payment/paygate/callback/server/

VSCode
======

To make the isort work properly inside the Visual Studio Code, you should add this to your Workspace settings JSON::

    "isort.args":["--settings-file", "<path to ecommerce project on host>/.isort.cfg"],

License
=======

This work is licensed under the terms of the `GNU Affero General Public License (AGPL) <https://github.com/fccn/ecommerce-plugin-paygate/blob/master/LICENSE.txt>`_.
