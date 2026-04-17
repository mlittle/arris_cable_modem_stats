"""
Modem implementation for Arris SB6183.
https://github.com/andrewfraley/arris_cable_modem_stats

This function written by https://github.com/mphuff
"""
# pylint: disable=line-too-long
import logging
from typing import Any, Dict, List
from bs4 import BeautifulSoup
import requests

try:
    from src.modem_interface import ModemInterface
except ImportError:
    from modem_interface import ModemInterface


class SB6183Modem(ModemInterface):
    """Arris SB6183 modem implementation."""

    def get_config_keys(self) -> List[str]:
        """Return list of required config keys for SB6183."""
        return ['modem_url', 'modem_verify_ssl']

    def authenticate(self, config: Dict[str, Any], session: requests.Session) -> bool:
        """
        SB6183 does not require authentication.
        This is a no-op method.
        """
        logging.debug('SB6183 does not require authentication')
        return True

    def fetch_data(self, config: Dict[str, Any], session: requests.Session) -> str:
        """
        Fetch HTML from the modem status page.

        Args:
            config: Configuration dictionary
            session: requests.Session object

        Returns:
            str: Raw HTML from modem
        """
        url = config['modem_url']
        verify_ssl = config['modem_verify_ssl']

        logging.info('Fetching HTML from %s', url)

        try:
            response = session.get(url, verify=verify_ssl, timeout=10)
            response.raise_for_status()
            html = response.text
            return html
        except Exception as exception:
            logging.error('Error fetching HTML from %s', url)
            logging.error(exception)
            return None

    def parse_data(self, html: str) -> Dict[str, List[Dict[str, Any]]]:
        """
        Parse the HTML into the modem stats dict.

        Args:
            html: Raw HTML from modem

        Returns:
            dict: Parsed stats with 'downstream' and 'upstream' keys
        """
        logging.info('Parsing HTML for modem model sb6183')

        soup = BeautifulSoup(html, 'html.parser')
        stats = {
            'downstream': [],
            'upstream': []
        }

        # downstream table
        logging.debug("Found %s tables", len(soup.find_all("table")))
        for table_row in soup.find_all("table")[2].find_all("tr"):
            if table_row.th:
                continue

            channel_id = table_row.find_all('td')[0].text.strip()
            logging.debug("Processing downstream channel %s", channel_id)
            # Some firmwares have a header row not already skipped by "if table_row.th",
            # skip it if channel_id isn't an integer
            if not channel_id.isdigit():
                continue

            frequency = int(table_row.find_all('td')[4].text.replace(" Hz", "").strip())
            power = float(table_row.find_all('td')[5].text.replace(" dBmV", "").strip())
            snr = float(table_row.find_all('td')[6].text.replace(" dB", "").strip())
            corrected = int(table_row.find_all('td')[7].text.strip())
            uncorrectables = int(table_row.find_all('td')[8].text.strip())

            stats['downstream'].append({
                'channel_id': channel_id,
                'frequency': frequency,
                'power': power,
                'snr': snr,
                'corrected': corrected,
                'uncorrectables': uncorrectables
            })

        logging.debug('downstream stats: %s', stats['downstream'])
        if len(stats['downstream']) == 0:
            logging.error(
                'Failed to get any downstream stats! If you have selected the correct modem, '
                'then this could be a parsing issue in %s', __file__)

        # upstream table
        for table_row in soup.find_all("table")[3].find_all("tr"):
            if table_row.th:
                continue

            # Some firmwares have a header row not already skipped by "if table_row.th",
            # skip it if channel_id isn't an integer
            channel_id = table_row.find_all('td')[0].text.strip()
            if not channel_id.isdigit():
                continue

            symbol_rate = int(table_row.find_all('td')[4].text.replace(" Ksym/sec", "").strip())
            frequency = int(table_row.find_all('td')[5].text.replace(" Hz", "").strip())
            power = float(table_row.find_all('td')[6].text.replace(" dBmV", "").strip())

            stats['upstream'].append({
                'channel_id': channel_id,
                'symbol_rate': symbol_rate,
                'frequency': frequency,
                'power': power,
            })

        logging.debug('upstream stats: %s', stats['upstream'])
        if len(stats['upstream']) == 0:
            logging.error(
                'Failed to get any upstream stats! If you have selected the correct modem, '
                'then this could be a parsing issue in %s', __file__)

        return stats


# Keep legacy function for backward compatibility with tests
def parse_html_sb6183(html):
    """Legacy function for backward compatibility. Use SB6183Modem class instead."""
    modem = SB6183Modem()
    return modem.parse_data(html)


# Register this modem class with the registry
try:
    from src.modem_registry import register_modem
except ImportError:
    from modem_registry import register_modem
register_modem('sb6183', SB6183Modem)
