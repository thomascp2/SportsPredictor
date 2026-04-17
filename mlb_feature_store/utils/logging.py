import sys
from pathlib import Path

from loguru import logger


def setup_logger(log_level: str = "INFO") -> None:
    """
    Configure loguru for the pipeline.

    Writes INFO+ to stderr and DEBUG+ to a rotating daily log file.

    Args:
        log_level: Minimum level for stderr output.
    """
    logger.remove()
    logger.add(
        sys.stderr,
        format="{time:YYYY-MM-DD HH:mm:ss} | {level:<8} | {name}:{function}:{line} - {message}",
        level=log_level,
        colorize=True,
    )
    log_dir = Path(__file__).parent.parent / "logs"
    log_dir.mkdir(exist_ok=True)
    logger.add(
        str(log_dir / "pipeline_{time:YYYY-MM-DD}.log"),
        format="{time:YYYY-MM-DD HH:mm:ss} | {level:<8} | {name}:{function}:{line} - {message}",
        level="DEBUG",
        rotation="1 day",
        retention="30 days",
        compression="gz",
    )


__all__ = ["logger", "setup_logger"]
