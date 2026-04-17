"""
Modem implementation for Arris SB8200.
https://github.com/andrewfraley/arris_cable_modem_stats
"""
# pylint: disable=line-too-long
import logging
import base64
from typing import Any, Dict, List, Optional
from bs4 import BeautifulSoup
import requests

try:
    from src.modem_interface import ModemInterface
except ImportError:
    from modem_interface import ModemInterface


class SB8200Modem(ModemInterface):
    """Arris SB8200 modem implementation."""

    def __init__(self):
        """Initialize the modem with no token."""
        self.token: Optional[str] = None

    def get_config_keys(self) -> List[str]:
        """Return list of required config keys for SB8200."""
        return ['modem_url', 'modem_username', 'modem_password', 'modem_verify_ssl']

    def authenticate(self, config: Dict[str, Any], session: requests.Session) -> bool:
        """
        Authenticate with the SB8200 modem and store the token.

        Args:
            config: Configuration dictionary
            session: requests.Session object

        Returns:
            bool: True if authentication successful, False otherwise
        """
        logging.info('Obtaining login session from modem')

        url = config['modem_url']
        username = config['modem_username']
        password = config['modem_password']
        verify_ssl = config['modem_verify_ssl']

        # We have to send a request with the username and password
        # encoded as a url param. Look at the Javascript from the
        # login page for more info on the following.
        token = username + ":" + password
        auth_hash = base64.b64encode(token.encode('ascii')).decode()
        auth_url = url + '?login_' + auth_hash

        # This is going to respond with a token, which is a hash that we
        # have to send as a get parameter with subsequent requests
        # Requests will automatically handle the session cookies
        try:
            resp = session.get(
                auth_url,
                headers={'Authorization': 'Basic ' + auth_hash},
                verify=verify_ssl,
                timeout=10
            )
            if resp.status_code != 200:
                logging.error('Error authenticating with %s', url)
                logging.error('Status code: %s', resp.status_code)
                logging.error('Reason: %s', resp.reason)
                return False

            if 'Password:' in resp.text:
                logging.error(
                    'Authentication error, received login page. Check username / password. '
                    'SB8200 has some kind of bug that can cause this after too many authentications, '
                    'the only known fix is to reboot the modem.'
                )
                return False

            self.token = resp.text
            resp.close()
            return True

        except Exception as exception:
            logging.error(exception)
            logging.error('Error authenticating with %s', url)
            return False

    def fetch_data(self, config: Dict[str, Any], session: requests.Session) -> Optional[str]:
        """
        Fetch HTML from the modem status page using stored token.

        Args:
            config: Configuration dictionary
            session: requests.Session object

        Returns:
            str: Raw HTML from modem, or None if error
        """
        if not self.token:
            logging.error('Not authenticated. Call authenticate() first.')
            return None

        url = config['modem_url'] + '?ct_' + self.token
        verify_ssl = config['modem_verify_ssl']

        logging.info('Retrieving stats from %s', config['modem_url'])
        logging.debug('Cookies: %s', session.cookies)
        logging.debug('Full url: %s', url)

        try:
            resp = session.get(url, verify=verify_ssl, timeout=10)
            if resp.status_code != 200:
                logging.error('Error retrieving html from %s', url)
                logging.error('Status code: %s', resp.status_code)
                logging.error('Reason: %s', resp.reason)
                return None

            status_html = resp.content.decode("utf-8")
            resp.close()

            if 'Password:' in status_html:
                logging.error(
                    'Authentication error, received login page. This can happen once when a new '
                    'session is established and you should let it retry, but if it persists then '
                    'check username / password.'
                )
                # Clear token to force re-authentication
                self.token = None
                return None

            return status_html

        except Exception as exception:
            logging.error(exception)
            logging.error('Error retrieving html from %s', url)
            return None

    def parse_data(self, html: str) -> Dict[str, List[Dict[str, Any]]]:
        """
        Parse the HTML into the modem stats dict.

        Args:
            html: Raw HTML from modem

        Returns:
            dict: Parsed stats with 'downstream' and 'upstream' keys
        """
        logging.info('Parsing HTML for modem model sb8200')

        # As of Aug 2019 the SB8200 has a bug in its HTML
        # The tables have an extra </tr> in the table headers, we have to remove it so
        # that Beautiful Soup can parse it
        # Before: <tr><th colspan=7><strong>Upstream Bonded Channels</strong></th></tr>
        # After: <tr><th colspan=7><strong>Upstream Bonded Channels</strong></th>
        html = html.replace('Bonded Channels</strong></th></tr>', 'Bonded Channels</strong></th>', 2)

        soup = BeautifulSoup(html, 'html.parser')
        stats = {}

        # downstream table
        stats['downstream'] = []
        for table_row in soup.find_all("table")[1].find_all("tr"):
            if table_row.th:
                continue

            channel_id = table_row.find_all('td')[0].text.strip()

            # Some firmwares have a header row not already skipped by "if table_row.th",
            # skip it if channel_id isn't an integer
            if not channel_id.isdigit():
                continue

            frequency = table_row.find_all('td')[3].text.replace(" Hz", "").strip()
            power = table_row.find_all('td')[4].text.replace(" dBmV", "").strip()
            snr = table_row.find_all('td')[5].text.replace(" dB", "").strip()
            corrected = table_row.find_all('td')[6].text.strip()
            uncorrectables = table_row.find_all('td')[7].text.strip()

            stats['downstream'].append({
                'channel_id': channel_id,
                'frequency': frequency,
                'power': power,
                'snr': snr,
                'corrected': corrected,
                'uncorrectables': uncorrectables
            })

        logging.debug('downstream stats: %s', stats['downstream'])
        if not stats['downstream']:
            logging.error(
                'Failed to get any downstream stats! If you have selected the correct modem, '
                'then this could be a parsing issue in %s', __file__)

        # upstream table
        stats['upstream'] = []
        for table_row in soup.find_all("table")[2].find_all("tr"):
            if table_row.th:
                continue

            channel_id = table_row.find_all('td')[1].text.strip()

            # Some firmwares have a header row not already skipped by "if table_row.th",
            # skip it if channel_id isn't an integer
            if not channel_id.isdigit():
                continue

            frequency = table_row.find_all('td')[4].text.replace(" Hz", "").strip()
            power = table_row.find_all('td')[6].text.replace(" dBmV", "").strip()

            stats['upstream'].append({
                'channel_id': channel_id,
                'frequency': frequency,
                'power': power,
            })

        logging.debug('upstream stats: %s', stats['upstream'])
        if not stats['upstream']:
            logging.error(
                'Failed to get any upstream stats! If you have selected the correct modem, '
                'then this could be a parsing issue in %s', __file__)

        return stats


def get_token_sb8200(config, session):
    """Legacy function for backward compatibility. Use SB8200Modem class instead."""
    modem = SB8200Modem()
    if modem.authenticate(config, session):
        return modem.token
    return None


def parse_html_sb8200(html):
    """Legacy function for backward compatibility. Use SB8200Modem class instead."""
    modem = SB8200Modem()
    return modem.parse_data(html)


# Register this modem class with the registry
try:
    from src.modem_registry import register_modem
except ImportError:
    from modem_registry import register_modem
register_modem('sb8200', SB8200Modem)
