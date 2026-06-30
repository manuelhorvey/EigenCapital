import logging

from paper_trading.logging.correlation import CorrelationIdFilter

__version__ = "0.1.0"


def setup_logging(level=logging.INFO, log_file=None):
    fmt = logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] [%(correlation_id)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    root = logging.getLogger("quorrin")
    root.setLevel(level)

    if not any(isinstance(h, logging.StreamHandler) for h in root.handlers):
        sh = logging.StreamHandler()
        sh.setFormatter(fmt)
        root.addHandler(sh)

    if log_file:
        fh = logging.FileHandler(log_file)
        fh.setFormatter(fmt)
        root.addHandler(fh)

    # Add the filter to the handlers, not just the logger. Python's logging
    # propagates records from child loggers (e.g. "quorrin.asset_engine")
    # through to the parent's callHandlers() which bypasses the parent logger's
    # own filter() — meaning a logger-level filter never runs for propagated
    # records.  Adding the filter to the handlers ensures it always fires
    # before formatting, regardless of which logger originated the record.
    filter_ = CorrelationIdFilter()
    for h in root.handlers:
        h.addFilter(filter_)
    root.addFilter(filter_)  # defensive — catches direct emit on the quorrin logger

    return root
