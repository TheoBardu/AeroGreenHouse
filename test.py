import yaml
import os

with open('config.yaml', "r") as f:
    config = yaml.safe_load(f)

print(config['gpio_pins'][0]['name'])

print(config.get("config_reload_interval", 5))