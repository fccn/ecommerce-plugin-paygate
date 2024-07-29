# Makefile for ecommerce-plugin-paygate

# ==============================================================================
# VARIABLES

# current directory relative to the Makefile file
ROOT_DIR:=$(shell dirname $(realpath $(firstword $(MAKEFILE_LIST))))

# By default use the devstack ecommerce folder
# but you can use other folder, you just have to change this environment variable like:
#   ECOMMERCE_SOURCE_PATH=/nau make test
#   make ECOMMERCE_SOURCE_PATH=/nau test
ECOMMERCE_SOURCE_PATH ?= /edx/app/ecommerce/ecommerce

# ==============================================================================
# RULES

default: help

help:
	@echo "Please use \`make <target>' where <target> is one of"
	@grep -E '^[a-zA-Z0-9_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-30s\033[0m %s\n", $$1, $$2}'
.PHONY: help

_prerequire:
	@if [ ! -d "${ECOMMERCE_SOURCE_PATH}" ]; then { echo "Ecommerce directory doesn't exist.\n  ECOMMERCE_SOURCE_PATH=${ECOMMERCE_SOURCE_PATH}\nPlease check if that directory exist or change the default value using:\n  ECOMMERCE_SOURCE_PATH=~/<different path>/ecommerce make <target>" ; exit 1; } fi
.PHONY: _prerequire

test: | _prerequire ## Run all the tests, to run a specific test run: make test `pwd`/paygate/tests/test_XPTO.py
	@args="$(filter-out $@,$(MAKECMDGOALS))" && \
	arg_2="$${args:-${1}}" && \
	arg_3="$${arg_2:=$(ROOT_DIR)/paygate}" && \
	cd ${ECOMMERCE_SOURCE_PATH} && \
	DJANGO_SETTINGS_MODULE=paygate.settings.test coverage run --source="$(ROOT_DIR)" -m pytest $${arg_3}
.PHONY: test

clean: ## remove all the unneeded artifacts
	-rm -rf .tox
	-rm -rf *.egg-info
	-find . -name '__pycache__' -prune -exec rm -rf "{}" \;
	-find . -name '*.pyc' -delete
	-rm -f MANIFEST
	-rm -rf .coverage .coverage.* htmlcov
.PHONY: clean

# It will use the `.isort.cfg` from ecommerce
lint-isort: _prerequire
	@cd ${ECOMMERCE_SOURCE_PATH} && \
	isort --check-only --diff $(ROOT_DIR)/paygate
.PHONY: lint-isort

# It will use the `.isort.cfg` from ecommerce
run-isort: _prerequire
	@cd ${ECOMMERCE_SOURCE_PATH} && \
	isort $(ROOT_DIR)/paygate
.PHONY: run_isort

# It will use the `setup.cfg` from ecommerce
lint-pycodestyle: _prerequire
	@cd ${ECOMMERCE_SOURCE_PATH} && \
	pycodestyle --config=setup.cfg $(ROOT_DIR)/paygate
.PHONY: lint-pycodestyle

# It will use the `pylintrc` from ecommerce
lint-pylint: _prerequire
	@cd ${ECOMMERCE_SOURCE_PATH} && \
	pylint -j 0 --rcfile=pylintrc --verbose --init-hook='import sys; sys.path.append("${ECOMMERCE_SOURCE_PATH}")' $(ROOT_DIR)/paygate
.PHONY: lint-pylint

# Disabled because of the error:
#   Django was not configured. For more information run pylint --load-plugins=pylint_django --help-msg=django-not-configured (django-not-configured)
lint: | lint-isort lint-pycodestyle # lint-pylint ## Run Python linting
.PHONY: lint
