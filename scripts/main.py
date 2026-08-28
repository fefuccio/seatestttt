#!/usr/bin/env python3

import argparse
import logging
import sys

from fishing_bot import FishingBot
from threadsafety import install_main_dispatcher


def parse_args():
    parser = argparse.ArgumentParser(prog="SeaAnglerAssist")
    parser.add_argument("--log-level", choices=["DEBUG", "INFO", "WARNING"],
                        default="INFO", help="Set logging level")
    return parser.parse_args()

def setup_logging(level_name: str):
    level = getattr(logging, level_name, logging.INFO)
    fmt = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"
    logging.basicConfig(level=level, format=fmt)

if __name__ == "__main__":
    args = parse_args()
    setup_logging(args.log_level)
    install_main_dispatcher()
    app = FishingBot()
    sys.exit(app.app.exec())
