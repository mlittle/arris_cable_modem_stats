import os
import re
import json
import unittest
import tempfile
import src.arris_stats as arris_stats

# pylint: disable=line-too-long


class TestArrisStats(unittest.TestCase):

    # Required params and their defaults that we need to get from the config file or ENV
    default_config = arris_stats.get_default_config()

    def setUp(self):
        """Clean up ENV vars before each test"""
        for param in self.default_config.keys():
            if param in os.environ:
                del os.environ[param]

    def test_get_config(self):
        """ Test arris_stats.get_config() """
        default_config = self.default_config.copy()

        # Get the config without a config file or any ENV vars set
        config = arris_stats.get_config()
        for param in default_config:
            if param not in ['modem_auth_required', '_auth_required']:
                self.assertEqual(config[param], default_config[param])

        # Test with config file
        config_file = tempfile.NamedTemporaryFile(mode='w', delete=False)
        for param in default_config:
            line = "%s = %s\n" % (param, default_config[param])
            config_file.write(line)
        config_file.close()

        for param in default_config.keys():
            if param in os.environ:
                del os.environ[param]

        config = arris_stats.get_config(config_file.name)
        for param in default_config:
            if param not in ['modem_auth_required', '_auth_required']:
                self.assertEqual(config[param], default_config[param])

    def test_dockerfile(self):
        """ Ensure the docker file has the same hard coded ENV defaults """
        default_config = arris_stats.get_default_config().copy()
        path = 'Dockerfile'
        with open(path, "r") as dockerfile:
            dockerfile_contents = dockerfile.read().splitlines()

        env_lines = []
        first = None
        for line in dockerfile_contents:
            if not first and re.match(r'^ENV \S+ \S+$', line):
                first = line.split('ENV ')[1].split(' \\')[0].strip()
                env_lines.append(first)
            elif first:
                if re.match(r'\s*\S.+=\S.', line):
                    env_lines.append(line.split(' \\')[0].strip())
                elif line.strip() == '' or re.match(r'^#', line.strip()) or re.match(r'^\\', line.strip()):
                    continue
                else:
                    break
        
        for line in env_lines:
            param = line.split('=')[0]
            value = line.split('=')[1]
            self.assertEqual(str(default_config[param]), value)
            del default_config[param]

        self.assertEqual(default_config, {})

    def test_config_file(self):
        """ Ensure the config file as the same hard coded defaults as default_config """
        default_config = self.default_config.copy()
        path = 'src/config.ini.example'
        with open(path, "r") as configfile:
            config_contents = configfile.read().splitlines()
        for line in config_contents:
            linesplit = line.split(' = ')
            if len(linesplit) != 2:
                continue
            param = linesplit[0]
            value = linesplit[1]
            self.assertEqual(str(default_config[param]), value)
            del default_config[param]

        self.assertEqual(default_config, {})

    def test_modem_parse_functions(self):
        """ Test all the modem parse functions """
        modems_supported = arris_stats.modems_supported

        for modem in modems_supported:
            with open('tests/mockups/%s.json' % modem) as f:
                control_values = json.loads(f.read())

            with open('tests/mockups/%s.html' % modem) as f:
                raw_data_string = f.read()

            modem_instance = arris_stats.get_modem_instance(modem)

            if modem == 's33':
                raw_data = json.loads(raw_data_string)
                stats = modem_instance.parse_data(raw_data)
            else:
                stats = modem_instance.parse_data(raw_data_string)

            self.assertIsInstance(stats, dict)
            self.assertIn('downstream', stats)
            self.assertIn('upstream', stats)

            for channel_type in ['downstream', 'upstream']:
                channels = stats[channel_type]
                self.assertIsInstance(channels, list)
                for channel in channels:
                    self.assertIn('channel_id', channel)
                    self.assertIn('power', channel)

            self.assertEqual(stats, control_values)
