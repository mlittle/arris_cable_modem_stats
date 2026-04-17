"""
Modem implementation for Arris T25.
https://github.com/andrewfraley/arris_cable_modem_stats
"""
# pylint: disable=line-too-long
import logging
from typing import Any, Dict, List, Optional
from bs4 import BeautifulSoup
import requests

try:
    from src.modem_interface import ModemInterface
except ImportError:
    from modem_interface import ModemInterface


class T25Modem(ModemInterface):
    """Arris T25 modem implementation."""

    def __init__(self):
        """Initialize the modem with no token."""
        self.token: Optional[str] = None

    def get_config_keys(self) -> List[str]:
        """Return list of required config keys for T25."""
        return ['modem_url', 'modem_username', 'modem_password', 'modem_verify_ssl']

    def _follow_redirect(self, url: str, config: Dict[str, Any], session: requests.Session) -> str:
        """
        Follow HTML meta refresh redirects.

        T25 firmware uses meta refresh instead of HTTP 403 redirects.

        Args:
            url: Starting URL
            config: Configuration dictionary
            session: requests.Session object

        Returns:
            str: Final URL after following all redirects
        """
        res = session.get(url, verify=config['modem_verify_ssl'], timeout=10)
        res.raise_for_status()
        soup = BeautifulSoup(res.content, 'html.parser')
        result = soup.find("meta", attrs={"http-equiv": "refresh"})
        if result:
            # Extract the meta refresh as T25 firmware doesn't use 403 redirects
            next_url = f"{url[:url.rfind('/')]}/{result.attrs['content'].split(';')[1].replace('url=', '')}"
            return self._follow_redirect(next_url, config, session)
        else:
            return res.url

    def authenticate(self, config: Dict[str, Any], session: requests.Session) -> bool:
        """
        Authenticate with the T25 modem using form credentials.

        Args:
            config: Configuration dictionary
            session: requests.Session object

        Returns:
            bool: True if authentication successful, False otherwise
        """
        logging.info('Getting login page for modem model t25')
        try:
            # Follow redirects to get to the login page
            login_url = self._follow_redirect(config['modem_url'], config, session)
            logging.info(f'Login page url: {login_url}')

            # POST credentials to the login form
            login_page = session.post(
                login_url,
                verify=config['modem_verify_ssl'],
                data={
                    'username': config['modem_username'],
                    'password': config['modem_password']
                },
                timeout=10
            )
            login_page.raise_for_status()

            # Dummy return the token as we don't have a token for url auth (Within session)
            # The actual token is stored in session cookies
            self.token = "token_in_session"
            return True

        except Exception as exception:
            logging.error(exception)
            logging.error('Error authenticating with T25 modem')
            return False

    def fetch_data(self, config: Dict[str, Any], session: requests.Session) -> Optional[str]:
        """
        Fetch HTML from the modem status page.

        Args:
            config: Configuration dictionary
            session: requests.Session object (should already be authenticated)

        Returns:
            str: Raw HTML from modem, or None if error
        """
        url = config['modem_url']
        verify_ssl = config['modem_verify_ssl']

        logging.info('Retrieving stats from %s', url)
        logging.debug('Cookies: %s', session.cookies)

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
                    'Authentication error, received login page. Check username / password.'
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
        logging.info('Parsing HTML for modem model t25')

        soup = BeautifulSoup(html, 'html.parser')
        stats = {
            "downstream": [],
            "upstream": []
        }

        # downstream table
        for table_row in soup.find_all("table")[0].find_all("tr"):
            if "power" in str(table_row).lower():
                continue

            if table_row.th:
                continue

            # Replace/remove "Downstream" to normalize with other models
            channel_id = table_row.find_all('td')[0].text.replace("Downstream", "").strip()

            if not channel_id.isdigit():
                continue

            # Other models supply HZ not MHZ * 1000000 to have the same structures as the other ones
            frequency = str(float(table_row.find_all('td')[2].text.replace(" MHz", "").strip()) * 1000000)
            power = table_row.find_all('td')[3].text.replace(" dBmV", "").strip()
            snr = table_row.find_all('td')[4].text.replace(" dB", "").strip()
            corrected = table_row.find_all('td')[7].text.strip()
            uncorrectables = table_row.find_all('td')[8].text.strip()

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
        for table_row in soup.find_all("table")[4].find_all("tr"):
            if table_row.th:
                continue

            # Replace/remove "Upstream" to normalize with other models
            channel_id = table_row.find_all('td')[0].text.replace("Upstream", "").strip()
            if not channel_id.isdigit():
                continue

            symbol_rate = table_row.find_all('td')[5].text.replace(" kSym/s", "").strip()
            frequency = table_row.find_all('td')[2].text.replace(" MHz", "").strip()
            power = table_row.find_all('td')[3].text.replace(" dBmV", "").strip()

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


def follow_redirect(session, config):
    """Legacy function for backward compatibility. Use T25Modem class instead."""
    modem = T25Modem()
    return modem._follow_redirect(config['modem_url'], config, session)


def get_token_t25(config, session):
    """Legacy function for backward compatibility. Use T25Modem class instead."""
    modem = T25Modem()
    if modem.authenticate(config, session):
        return modem.token
    return None


def parse_html_t25(html):
    """Legacy function for backward compatibility. Use T25Modem class instead."""
    modem = T25Modem()
    return modem.parse_data(html)


# Register this modem class with the registry
try:
    from src.modem_registry import register_modem
except ImportError:
    from modem_registry import register_modem
register_modem('t25', T25Modem)
