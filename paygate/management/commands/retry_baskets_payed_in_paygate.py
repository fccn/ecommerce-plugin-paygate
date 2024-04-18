"""
Command that retries to receive the missing server callbacks from PayGate.
"""

import logging
from datetime import datetime, timedelta

from django.contrib.sites.models import Site
from django.core.management.base import BaseCommand
from paygate.processors import PayGate

log = logging.getLogger(__name__)


class Command(BaseCommand):
    """
    Command that retries to receive the missing server callbacks from PayGate.
    """

    help = """retries to receive the missing server callbacks from PayGate."""

    def add_arguments(self, parser):
        """
        Arguments of this command.
        """
        parser.add_argument(
            "--site",
            type=str,
            default=Site.objects.get_current().domain,
            help="The site domain to execute this recover",
        )
        parser.add_argument(
            "--start",
            type=str,
            help="The start date period to retry, incompatible with the --delta_in_minutes",
        )
        parser.add_argument(
            "--end",
            type=str,
            default=None,
            help="The end date period to retry, incompatible with the --delta_in_minutes",
        )
        parser.add_argument(
            "--delta_in_minutes",
            type=str,
            default=1440,  # 1 day
            help="The number of seconds to retry, default to last day",
        )

    def handle(self, *args, **kwargs):
        """
        Synchronize courses to the Richie marketing site, print to console its sync progress.
        """
        start_str = kwargs["start"]
        end_str = kwargs["end"]
        if start_str or end_str:
            start = datetime.strptime(kwargs["start"], "%Y-%m-%d %H:%M:%S")
            end = datetime.strptime(kwargs["end"], "%Y-%m-%d %H:%M:%S")
        else:
            delta_in_minutes = int(kwargs["delta_in_minutes"])
            now = datetime.now()
            end = now
            start = now - timedelta(minutes=delta_in_minutes)

        site_domain = kwargs["site"]
        site = Site.objects.filter(domain=site_domain).first()
        paygate = PayGate(site)
        paygate.retry_baskets_payed_in_paygate(start, end)
