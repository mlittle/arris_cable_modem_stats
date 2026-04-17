"""
    Home Assistant MQTT functions

    https://github.com/andrewfraley/arris_cable_modem_stats
"""

import json
import logging

import paho.mqtt.client as mqtt


def send_to_homeassistant(stats, config):
    """Send the stats to Home Assistant via MQTT discovery."""

    client = mqtt.Client(client_id=config['homeassistant_device_id'])

    if config['homeassistant_mqtt_username']:
        client.username_pw_set(
            config['homeassistant_mqtt_username'],
            config['homeassistant_mqtt_password'],
        )

    if config['homeassistant_mqtt_ssl']:
        client.tls_set()

    logging.info(
        'Sending stats to Home Assistant MQTT (%s:%s)',
        config['homeassistant_mqtt_host'],
        config['homeassistant_mqtt_port'],
    )

    try:
        client.connect(
            config['homeassistant_mqtt_host'],
            config['homeassistant_mqtt_port'],
            config['homeassistant_mqtt_keepalive'],
        )
        publish_homeassistant_entities(client, stats, config)
        client.disconnect()
    except Exception as exception:  # pylint: disable=broad-exception-caught
        logging.error('Failed to publish to Home Assistant MQTT')
        logging.error(exception)


def publish_homeassistant_entities(client, stats, config):
    """Publish Home Assistant discovery config and state topics."""

    device = get_device_payload(config)

    publish_summary_sensor(
        client,
        config,
        device,
        'downstream_channel_count',
        'Downstream Channel Count',
        len(stats['downstream']),
        'channels',
        'measurement',
        'mdi:download-network-outline',
    )
    publish_summary_sensor(
        client,
        config,
        device,
        'upstream_channel_count',
        'Upstream Channel Count',
        len(stats['upstream']),
        'channels',
        'measurement',
        'mdi:upload-network-outline',
    )

    for direction, channels in [('downstream', stats['downstream']), ('upstream', stats['upstream'])]:
        for channel in channels:
            publish_channel_entities(client, config, device, direction, channel)


def publish_channel_entities(client, config, device, direction, channel):
    """Publish discovery and state for a single channel."""

    sensor_definitions = get_sensor_definitions(direction)
    channel_id = str(channel['channel_id'])

    for field, definition in sensor_definitions.items():
        if field not in channel:
            continue

        entity_key = f'{direction}_channel_{channel_id}_{field}'
        object_id = f"{config['homeassistant_device_id']}_{entity_key}"
        discovery_topic = get_discovery_topic(config, object_id)
        state_topic = get_state_topic(config, object_id)

        discovery_payload = {
            'name': f"{direction.title()} Channel {channel_id} {definition['name']}",
            'unique_id': object_id,
            'object_id': object_id,
            'state_topic': state_topic,
            'device': device,
            'availability_topic': get_availability_topic(config),
            'payload_available': 'online',
            'payload_not_available': 'offline',
            'icon': definition['icon'],
        }

        if definition['device_class']:
            discovery_payload['device_class'] = definition['device_class']
        if definition['state_class']:
            discovery_payload['state_class'] = definition['state_class']
        if definition['unit_of_measurement']:
            discovery_payload['unit_of_measurement'] = definition['unit_of_measurement']

        client.publish(discovery_topic, json.dumps(discovery_payload), retain=True)
        client.publish(state_topic, serialize_metric_value(channel[field]), retain=False)

    client.publish(get_availability_topic(config), 'online', retain=False)


def publish_summary_sensor(client, config, device, entity_key, name, value, unit, device_class, icon):
    """Publish a summary sensor for device-level totals."""

    object_id = f"{config['homeassistant_device_id']}_{entity_key}"
    discovery_topic = get_discovery_topic(config, object_id)
    state_topic = get_state_topic(config, object_id)

    discovery_payload = {
        'name': f"{config['homeassistant_device_name']} {name}",
        'unique_id': object_id,
        'object_id': object_id,
        'state_topic': state_topic,
        'device': device,
        'availability_topic': get_availability_topic(config),
        'payload_available': 'online',
        'payload_not_available': 'offline',
        'unit_of_measurement': unit,
        'device_class': device_class,
        'state_class': 'measurement',
        'icon': icon,
    }

    client.publish(discovery_topic, json.dumps(discovery_payload), retain=True)
    client.publish(state_topic, serialize_metric_value(value), retain=False)


def get_device_payload(config):
    """Return Home Assistant device metadata."""

    return {
        'identifiers': [config['homeassistant_device_id']],
        'name': config['homeassistant_device_name'],
        'manufacturer': 'Arris',
        'model': config['modem_model'].upper(),
        'configuration_url': config['modem_url'],
    }


def get_sensor_definitions(direction):
    """Return field metadata for channel sensors."""

    common = {
        'frequency': {
            'name': 'Frequency',
            'unit_of_measurement': 'Hz',
            'device_class': 'frequency',
            'state_class': 'measurement',
            'icon': 'mdi:sine-wave',
        },
        'power': {
            'name': 'Power',
            'unit_of_measurement': 'dBmV',
            'device_class': None,
            'state_class': 'measurement',
            'icon': 'mdi:signal',
        },
    }

    if direction == 'downstream':
        common.update({
            'snr': {
                'name': 'SNR',
                'unit_of_measurement': 'dB',
                'device_class': None,
                'state_class': 'measurement',
                'icon': 'mdi:chart-bell-curve-cumulative',
            },
            'corrected': {
                'name': 'Corrected',
                'unit_of_measurement': 'packets',
                'device_class': None,
                'state_class': 'total_increasing',
                'icon': 'mdi:counter',
            },
            'uncorrectables': {
                'name': 'Uncorrectables',
                'unit_of_measurement': 'packets',
                'device_class': None,
                'state_class': 'total_increasing',
                'icon': 'mdi:alert-circle-outline',
            },
        })

    return common


def get_discovery_topic(config, object_id):
    """Return a Home Assistant discovery topic."""

    return f"{config['homeassistant_discovery_prefix']}/sensor/{config['homeassistant_device_id']}/{object_id}/config"


def get_state_topic(config, object_id):
    """Return a Home Assistant state topic."""

    return f"{config['homeassistant_state_topic_prefix']}/{config['homeassistant_device_id']}/{object_id}/state"


def get_availability_topic(config):
    """Return the availability topic for the modem device."""

    return f"{config['homeassistant_state_topic_prefix']}/{config['homeassistant_device_id']}/availability"


def serialize_metric_value(value):
    """Return a value suitable for MQTT state payloads."""

    if isinstance(value, (int, float)):
        return value

    value_string = str(value)
    if '.' in value_string:
        return float(value_string)
    return int(value_string)