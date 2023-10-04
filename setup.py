"""
Setup file for the ecommerce-plugin-paygate Open edX ecommerce payment processor backend plugin.
"""

from pathlib import Path

from setuptools import setup

README = open(Path(__file__).parent / 'README.rst').read()
CHANGELOG = open(Path(__file__).parent / 'CHANGELOG.rst').read()


setup(
    name='ecommerce-plugin-paygate',
    description='Ecommerce plugin paygate payment processor backend plugin',
    version='0.1.0',
    author='FCCN',
    author_email='info@nau.edu.pt',
    long_description=f'{README}\n\n{CHANGELOG}',
    long_description_content_type='text/x-rst',
    url='https://github.com/fccn/ecommerce-plugin-paygate',
    include_package_data=True,
    zip_safe=False,
    license="AGPL 3.0",
    keywords='Django openedx openedx-plugin ecommerce paygate',
    classifiers=[
        'Development Status :: 3 - Alpha',
        'Framework :: Django',
        'Framework :: Django :: 2.2',
        'Intended Audience :: Developers',
        'License :: OSI Approved :: GNU Affero General Public License v3 or later (AGPLv3+)',
        'Natural Language :: English',
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3.8',
    ],
    install_requires=[
        'Django~=3.2',
    ],
    packages=[
        'paygate',
    ],
    entry_points={
        'ecommerce': [
            'paygate = ecommerce_plugin_paygate.apps:PayGateConfig',
        ],
    },
)
