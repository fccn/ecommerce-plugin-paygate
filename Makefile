# Makefile for ecommerce-plugin-paygate

ifdef TOXENV
TOX := tox -- #to isolate each tox environment if TOXENV is defined
endif
PYTHON_ENV=py38
DJANGO_ENV_VAR=$(if $(DJANGO_ENV),$(DJANGO_ENV),django32)

help: ## display this help message
	@echo "Please use \`make <target>' where <target> is one of"
	@grep '^[a-zA-Z]' $(MAKEFILE_LIST) | sort | awk -F ':.*?## ' 'NF==2 {printf "\033[36m  %-25s\033[0m %s\n", $$1, $$2}'

test: ## run all the tests
	$(TOX) DJANGO_SETTINGS_MODULE=settings.test coverage run --source="." -m pytest ./paygate
.PHONY: test

lint: ## check our own code with pylint
	tox -e quality
.PHONY: lint

clean: ## remove all the unneeded artifacts
	-rm -rf .tox
	-rm -rf *.egg-info
	-find . -name '__pycache__' -prune -exec rm -rf "{}" \;
	-find . -name '*.pyc' -delete
	-rm -f MANIFEST
	-rm -rf .coverage .coverage.* htmlcov
.PHONY: clean

requirements: ## install the developer requirements
	$(TOX) pip install -qr requirements/pip.txt
	$(TOX) pip install -e .
	$(TOX) pip install -r requirements/dev.txt
.PHONY: requirements

test-requirements: ## install test requirements
	$(TOX) pip install -qr requirements/test.txt
.PHONY: test-requirements

compile-requirements: export CUSTOM_COMPILE_COMMAND=make upgrade
compile-requirements: ## compile the requirements/*.txt files with the latest packages satisfying requirements/*.in
	# Make sure to compile files after any other files they include!
	pip-compile -v ${COMPILE_OPTS} --allow-unsafe --rebuild -o requirements/pip.txt requirements/pip.in
	pip-compile -v ${COMPILE_OPTS} -o requirements/pip-tools.txt requirements/pip-tools.in
	pip install -qr requirements/pip.txt
	pip install -qr requirements/pip-tools.txt
	pip-compile -v ${COMPILE_OPTS} -o requirements/base.txt requirements/base.in
	pip-compile -v ${COMPILE_OPTS} -o requirements/dev.txt requirements/dev.in
	pip-compile -v ${COMPILE_OPTS} -o requirements/test.txt requirements/test.in
	pip-compile -v ${COMPILE_OPTS} -o requirements/ci.txt requirements/ci.in
.PHONY: compile-requirements

upgrade: ## update the requirements/*.txt files with the latest packages satisfying requirements/*.in
	pip install -qr requirements/pip-tools.txt
	$(MAKE) compile-requirements COMPILE_OPTS="--upgrade"
.PHONY: upgrade

run_check_isort: requirements
	tox -e $(PYTHON_ENV)-check_isort

run_isort: requirements
	tox -e $(PYTHON_ENV)-${DJANGO_ENV_VAR}-run_isort

run_pycodestyle: requirements
	tox -e $(PYTHON_ENV)-${DJANGO_ENV_VAR}-pycodestyle

run_pep8: run_pycodestyle

run_pylint: requirements
	tox -e $(PYTHON_ENV)-${DJANGO_ENV_VAR}-pylint

quality: run_check_isort run_pycodestyle run_pylint ## run isort pycodestyle and Pylint

validate_python: clean requirements ## run Python unit tests and quality checks
	tox -e $(PYTHON_ENV)-${DJANGO_ENV_VAR}-tests

validate: validate_python quality ## Run Python unit tests and linting

# DJANGO_SETTINGS_MODULE='paygate.settings.test' pytest /edx/src/ecommerce-plugin-paygate/
