import yaml
import os
os.chdir('/Users/theo/Desktop/F&P/codes/AeroGreenHouse')

with open('config.yaml', "r") as f:
    config = yaml.safe_load(f)

print(config['gpio_pins'][0]['name'])