import logging.config

import yaml


def setup_logging(config_path="logging.yaml"):
    with open(config_path, "rt") as f:
        config = yaml.safe_load(f.read())
    logging.config.dictConfig(config)
