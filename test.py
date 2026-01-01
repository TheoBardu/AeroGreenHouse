import yaml
import os
from helper_aeroGreenHouse import aeroHelper
from numpy import arange

ah = aeroHelper()
print(ah.configs['gpio_pins'])
# tsep = 40

# T = arange(-5,18)
# for i,t in enumerate(T):
#     f = ah.T_modifier(t)
#     print(T[i], tsep - f*tsep)


# with open('config.yaml', "r") as f:
#     config = yaml.safe_load(f)

# print(config)
# print(config['gpio_pins'][0]['name'])
# print(config.get("config_reload_interval", 5))
