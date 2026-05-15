import logging
import sys

from pythonjsonlogger import jsonlogger

from bot.config import Settings


def setup_logging(settings: Settings) -> None:
    root = logging.getLogger()
    for handler in list(root.handlers):
        root.removeHandler(handler)

    handler = logging.StreamHandler(sys.stdout)
    if settings.log_json:
        formatter: logging.Formatter = jsonlogger.JsonFormatter(
            "%(asctime)s %(levelname)s %(name)s %(message)s",
            rename_fields={"levelname": "level", "asctime": "ts", "name": "logger"},
        )
    else:
        formatter = logging.Formatter(
            "%(asctime)s %(levelname)s %(name)s %(message)s"
        )
    handler.setFormatter(formatter)
    root.addHandler(handler)
    root.setLevel(settings.log_level.upper())

    logging.getLogger("aiogram.event").setLevel(logging.WARNING)
