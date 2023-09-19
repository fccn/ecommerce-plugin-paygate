==================================================================================
Paygate payment processor for Open edX
==================================================================================


This is a placeholder payment processor for the `Ecommerce <https://edx-ecommerce.readthedocs.io/en/latest/>`__ application from `Open edX <https://open.edx.org/>`__.

This plugin was created by `eduNEXT <https://www.edunext.co/>`__ to work specifically with the `Tutor <https://docs.tutor.overhang.io/>`__ Open edX distribution. The following installation instructions should work wit the `tutor-ecommerce plugin <https://github.com/overhangio/tutor-ecommerce>`__, but there is no reason to believe that it shouldn't also work with the Open edX native installation.

This guide is based in the `openedx-saferpay <https://github.com/epfl-cede/openedx-saferpay/tree/master>`__ README.

Install the following version of tutor-ecommerce as it contains special code to avoid the usage of discovery service for development purposes:

    pip install git+https://github.com/eduNEXT/tutor-ecommerce@nau/v14.0.1#egg=tutor-ecommerce==v14.0.1


Make sure that the ecommerce plugin is enabled::

    tutor plugins enable ecommerce

Make sure that the discovery and mfe plugins are disabled::

    tutor plugins disable mfe
    tutor plugins disable discovery

Add the Paygate payment processor to the Docker image::

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
        payment_page_url: your-payment-page-url
        some_value: some-extra-value
    $ tutor config save --set "ECOMMERCE_PAYMENT_PROCESSORS=$(cat paygate.yml)"

Run initialization scripts::

    tutor local quickstart

Enable the Saferpay payment backend::

    tutor local run ecommerce ./manage.py waffle_switch --create payment_processor_active_paygate on

All payments will then proceed through the Paygate payment processor.

License
=======

This work is licensed under the terms of the `GNU Affero General Public License (AGPL) <https://github.com/fccn/ecommerce-plugin-paygate/blob/master/LICENSE.txt>`_.
