import logging
import sys


def setup_logger(name: str = "bugvault", level: int = logging.INFO) -> logging.Logger:
    """Return a logger that writes to stderr only — never stdout.

    MCP communicates over stdout. ANY stdout output from application
    code will corrupt the JSON-RPC protocol. This logger redirects
    everything to stderr where it is invisible to the MCP transport.
    """
    logger = logging.getLogger(name)
    logger.setLevel(level)

    if not logger.handlers:
        handler = logging.StreamHandler(stream=sys.stderr)
        handler.setFormatter(logging.Formatter(
            "[%(asctime)s] %(name)s %(levelname)s: %(message)s",
            datefmt="%H:%M:%S",
        ))
        logger.addHandler(handler)

    # Prevent log propagation to the root logger, which may have
    # handlers attached to stdout by third-party libraries.
    logger.propagate = False

    return logger


logger = setup_logger()
