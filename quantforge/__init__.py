import logging

from paper_trading.logging.correlation import CorrelationIdFilter

__version__ = "0.1.0"


def setup_logging(level=logging.INFO, log_file=None):
    fmt = logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] [%(correlation_id)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    root = logging.getLogger("quantforge")
    root.setLevel(level)

    if not any(isinstance(h, logging.StreamHandler) for h in root.handlers):
        sh = logging.StreamHandler()
        sh.setFormatter(fmt)
        root.addHandler(sh)

    if log_file:
        fh = logging.FileHandler(log_file)
        fh.setFormatter(fmt)
        root.addHandler(fh)

    root.addFilter(CorrelationIdFilter())

    return root
