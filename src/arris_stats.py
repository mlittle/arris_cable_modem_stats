"""
    Pull stats from Arris Cable modem's web interface and send stats to InfluxDB

    https://github.com/andrewfraley/arris_cable_modem_stats
"""
# pylint: disable=line-too-long

import os
import sys
import time
import base64
import logging
import argparse
import configparser
import urllib3
import requests
import json
import importlib

# Import modem implementations and registry
from src.modem_interface import ModemInterface
from src.modem_registry import get_modem_instance, get_supported_models
# Import all modem modules to trigger their registration
from src.arris_stats_sb6183 import SB6183Modem  # noqa: F401
from src.arris_stats_sb8200 import SB8200Modem  # noqa: F401
from src.arris_stats_t25 import T25Modem  # noqa: F401
from src.arris_stats_s33 import S33Modem  # noqa: F401

# Legacy: modems_supported is now dynamically populated from registry
modems_supported = get_supported_models()


def load_destination_module(module_name):
    """Load an output module whether running as a package or a script."""

    if __package__:
        return importlib.import_module(f'{__package__}.{module_name}')
    return importlib.import_module(module_name)


def main():
    """ MAIN """

    args = get_args()
    config_path = args.config
    config = get_config(config_path)

    init_logger(args.log_level or config.get('log_level'))

    sleep_interval = int(config['sleep_interval'])
    destination = config['destination']

    # Disable the SSL warnings if we're not verifying SSL
    if not config['modem_verify_ssl']:
        urllib3.disable_warnings()

    # Get the modem instance
    try:
        modem = get_modem_instance(config['modem_model'])
    except RuntimeError as error:
        error_exit(str(error), config, sleep=False)

    # Create a session for the modem to use (handles cookies, etc.)
    session = requests.Session()

    first = True
    while True:
        if not first:
            logging.info('Sleeping for %s seconds', sleep_interval)
            sys.stdout.flush()
            time.sleep(sleep_interval)
        first = False

        # Authenticate if required (some modems require authentication for each poll)
        if config.get('modem_auth_required', config.get('_auth_required', False)):
            authenticated = False
            while not authenticated:
                authenticated = modem.authenticate(config, session)
                if not authenticated and config['exit_on_auth_error']:
                    error_exit('Unable to authenticate with modem. Exiting since exit_on_auth_error is True', config)
                if not authenticated:
                    logging.info('Unable to obtain valid login session, sleeping for: %ss', sleep_interval)
                    time.sleep(sleep_interval)

        # Get the raw data from the modem
        raw_data = modem.fetch_data(config, session)
        if not raw_data:
            if config['exit_on_html_error']:
                error_exit('No data obtained from modem. Exiting since exit_on_html_error is True', config)
            logging.error('No data to parse, giving up until next interval')
            if config['clear_auth_token_on_html_error']:
                logging.info('clear_auth_token_on_html_error is true, creating new session')
                session = requests.Session()
            continue

        # Parse the data
        stats = modem.parse_data(raw_data)

        if not stats or (not stats['upstream'] and not stats['downstream']):
            logging.error('Failed to get any stats, giving up until next interval')
            continue

        # Where should we send the results?
        if destination == 'influxdb' and config['influx_major_version'] == 1:
            destination_module = load_destination_module('arris_stats_influx1')
            destination_module.send_to_influx(stats, config)
        elif destination == 'influxdb' and config['influx_major_version'] == 2:
            destination_module = load_destination_module('arris_stats_influx2')
            destination_module.send_to_influx(stats, config)
        elif destination == 'timestream':
            destination_module = load_destination_module('arris_stats_aws_timestream')
            destination_module.send_to_aws_time_stream(stats, config)
        elif destination == 'splunk':
            destination_module = load_destination_module('arris_stats_splunk')
            destination_module.send_to_splunk(stats, config)
        elif destination == 'homeassistant':
            destination_module = load_destination_module('arris_stats_homeassistant')
            destination_module.send_to_homeassistant(stats, config)
        elif destination == 'stdout_json':
            print(json.dumps(stats))
        else:
            error_exit('Destination %s not supported!  Aborting.' % destination, sleep=False)


def get_args():
    """ Get argparser args """
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', metavar='config_file_path', help='Path to config file', required=False)
    parser.add_argument('--debug', help='Enable debug logging', action='store_true', required=False, default=False)
    parser.add_argument('--log-level', help='Set log_level', action='store', type=str.lower, required=False, choices=["debug", "info", "warning", "error"])
    args = parser.parse_args()
    if args.debug:
        args.log_level = "debug"
    return args


def get_default_config():
    return {

        # Main
        'log_level': "info",
        'destination': 'influxdb',
        'sleep_interval': 300,
        'modem_url': 'https://192.168.100.1/cmconnectionstatus.html',
        'modem_ip': None,  # For S33 modem
        'modem_verify_ssl': False,
        'modem_auth_required': False,
        'modem_username': 'admin',
        'modem_password': None,
        'modem_model': 'sb8200',
        'request_timeout': 10,  # For S33 and other modems
        'exit_on_auth_error': True,
        'exit_on_html_error': True,
        'clear_auth_token_on_html_error': True,
        'sleep_before_exit': True,

        # Influx
        'influx_major_version': 1,
        'influx_host': 'localhost',
        'influx_port': 8086,
        'influx_database': 'cable_modem_stats',
        'influx_username': None,
        'influx_password': None,
        'influx_use_ssl': False,
        'influx_verify_ssl': True,
        'influx_org': None,
        'influx_url': 'http://localhost:8086',
        'influx_bucket': 'cable_modem_stats',
        'influx_token': None,

        # AWS Timestream
        'timestream_aws_access_key_id': None,
        'timestream_aws_secret_access_key': None,
        'timestream_database': 'cable_modem_stats',
        'timestream_table': 'cable_modem_stats',
        'timestream_aws_region': 'us-east-1',

        # Splunk
        'splunk_token': None,
        'splunk_host': None,
        'splunk_port': 8088,
        'splunk_ssl': False,
        'splunk_verify_ssl': True,
        'splunk_source': 'arris_cable_modem_stats',

        # Home Assistant MQTT
        'homeassistant_mqtt_host': 'localhost',
        'homeassistant_mqtt_port': 1883,
        'homeassistant_mqtt_username': None,
        'homeassistant_mqtt_password': None,
        'homeassistant_mqtt_ssl': False,
        'homeassistant_mqtt_keepalive': 60,
        'homeassistant_discovery_prefix': 'homeassistant',
        'homeassistant_state_topic_prefix': 'arris_cable_modem_stats',
        'homeassistant_device_name': 'Arris_Cable_Modem',
        'homeassistant_device_id': 'arris_cable_modem'
    }


def get_config(config_path=None):
    """ Grab config from the ini config file,
        then grab the same variables from ENV to override
    """

    default_config = get_default_config()
    config = default_config.copy()

    # Get config from config.ini if specified
    if config_path:
        logging.info('Getting config from: %s', config_path)
        # Some hacky action to get the config without using section headings in the file
        # https://stackoverflow.com/a/10746467/866057
        parser = configparser.RawConfigParser()
        section = 'MAIN'
        with open(config_path) as fileh:
            file_content = '[%s]\n' % section + fileh.read()
        parser.read_string(file_content)

        for param in default_config:
            config[param] = parser[section].get(param, default_config[param])
    else:  # Get it from ENV
        logging.info('Getting config from ENV')
        for param in config:
            if os.environ.get(param):
                config[param] = os.environ.get(param)

    # Special handling depending on type
    for param in config:

        # If the default value is a boolean, but we have a string, convert it
        if isinstance(default_config[param], bool) and isinstance(config[param], str):
            config[param] = str_to_bool(string=config[param], name=param)

        # If the default value is an int, but we have a string, convert it
        if isinstance(default_config[param], int) and isinstance(config[param], str):
            config[param] = int(config[param])

        # Finally any 'None' string should just be None
        if default_config[param] is None and config[param] == 'None':
            config[param] = None

        # Ensure model is supported
        if config['modem_model'] not in get_supported_models():
            supported = ', '.join(get_supported_models())
            raise RuntimeError(
                f"Modem model '{config['modem_model']}' not supported! "
                f"Supported models: {supported}"
            )

    # Handle backward compatibility: S33 modems might use modem_ip instead of modem_url
    if config['modem_model'] == 's33' and not config.get('modem_ip'):
        # If modem_url looks like an IP address or contains 'modem_ip' context,
        # extract the IP from it for S33
        modem_url = config.get('modem_url', '')
        if modem_url.startswith('https://'):
            # Extract IP from URL like 'https://192.168.100.1/...'
            ip_part = modem_url.replace('https://', '').replace('http://', '').split('/')[0]
            config['modem_ip'] = ip_part
            logging.info('Normalized modem_url to modem_ip for S33: %s', ip_part)

    # Determine if authentication is required based on modem model
    auth_required_models = {'sb8200', 't25', 's33'}
    if config['modem_model'] in auth_required_models:
        config['modem_auth_required'] = True
        config['_auth_required'] = True
    else:
        config['_auth_required'] = config.get('modem_auth_required', False)

    logging.debug('Config loaded: %s', {k: v for k, v in config.items() if 'password' not in k.lower() and 'token' not in k.lower()})

    return config


def get_token(config, session):
    """ Get the auth token by sending the
        username and password pair for basic auth. They
        also want the pair as a base64 encoded get req param
    """
    logging.info('Obtaining login session from modem')

    url = config['modem_url']
    username = config['modem_username']
    password = config['modem_password']
    verify_ssl = config['modem_verify_ssl']

    # We have to send a request with the username and password
    # encoded as a url param.  Look at the Javascript from the
    # login page for more info on the following.
    token = username + ":" + password
    auth_hash = base64.b64encode(token.encode('ascii')).decode()
    auth_url = url + '?login_' + auth_hash
    # logging.debug('auth_url: %s', auth_url)

    # This is going to respond with a token, which is a hash that we
    # have to send as a get parameter with subsequent requests
    # Requests will automatically handle the session cookies
    try:
        resp = session.get(auth_url, headers={'Authorization': 'Basic ' + auth_hash}, verify=verify_ssl)
        if resp.status_code != 200:
            logging.error('Error authenticating with %s', url)
            logging.error('Status code: %s', resp.status_code)
            logging.error('Reason: %s', resp.reason)
            return None
        resp.close()
    except Exception as exception:
        logging.error(exception)
        logging.error('Error authenticating with %s', url)
        return None

    if 'Password:' in resp.text:
        logging.error('Authentication error, received login page.  Check username / password.  SB8200 has some kind of bug that can cause this after too many authentications, the only known fix is to reboot the modem.')
        return None

    token = resp.text
    return token


def get_html(config, token, session):
    """ Get the status page from the modem
        return the raw html
    """

    if config['modem_auth_required']:
        url = config['modem_url'] + '?ct_' + token
    else:
        url = config['modem_url']

    verify_ssl = config['modem_verify_ssl']

    logging.info('Retreiving stats from %s', config['modem_url'])
    logging.debug('Cookies: %s', session.cookies)
    logging.debug('Full url: %s', url)

    try:
        resp = session.get(url, verify=verify_ssl)
        if resp.status_code != 200:
            logging.error('Error retreiving html from %s', url)
            logging.error('Status code: %s', resp.status_code)
            logging.error('Reason: %s', resp.reason)
            return None
        status_html = resp.content.decode("utf-8")
        resp.close()
    except Exception as exception:
        logging.error(exception)
        logging.error('Error retreiving html from %s', url)
        return None

    if 'Password:' in status_html:
        logging.error('Authentication error, received login page.  This can happen once when a new session is established and you should let it retry, but if it persists then check username / password.')
        if not config['modem_auth_required']:
            logging.warning('You have modem_auth_required to False, but a login page was detected!')
        return None

    return status_html


def error_exit(message, config=None, sleep=True):
    """ Log error, sleep if needed, then exit 1 """
    logging.error(message)
    if sleep and config and config['sleep_before_exit']:
        logging.info('Sleeping for %s seconds before exiting since sleep_before_exit is True', config['sleep_interval'])
        time.sleep(config['sleep_interval'])
    sys.exit(1)


def write_html(html):
    """ write html to file """
    with open("/tmp/html", "wb") as text_file:
        text_file.write(html)


def read_html():
    """ read html from file """
    with open("/tmp/html", "rb") as text_file:
        html = text_file.read()
    return html


def str_to_bool(string, name):
    """ Return True is string ~= 'true' """
    if string.lower() == 'true':
        return True
    if string.lower() == 'false':
        return False

    raise ValueError('Config parameter % s should be boolean "true" or "false", but value is neither of those.' % name)


def init_logger(log_level="info"):
    """ Start the python logger """
    log_format = '%(asctime)s %(levelname)-8s %(message)s'

    level = logging.INFO

    if log_level == "debug":
        level = logging.DEBUG
    elif log_level == "info":
        level = logging.INFO
    elif log_level == "warning":
        level = logging.WARNING
    elif log_level == "error":
        level = logging.ERROR

    # https://stackoverflow.com/a/61516733/866057
    try:
        root_logger = logging.getLogger()
        root_logger.setLevel(level)
        root_handler = root_logger.handlers[0]
        root_handler.setFormatter(logging.Formatter(log_format))
    except IndexError:
        logging.basicConfig(level=level, format=log_format)


if __name__ == '__main__':
    main()
