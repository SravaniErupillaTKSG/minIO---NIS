import sys
from loguru import logger
from app.core.config import get_settings


def setup_logging() -> None:
    settings = get_settings()

    logger.remove()  # Remove default handler

    fmt = (
        "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
        "<level>{level: <8}</level> | "
        "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | "
        "<level>{message}</level>"
    )

    # Console handler
    logger.add(
        sys.stdout,
        format=fmt,
        level=settings.log_level,
        colorize=True,
        backtrace=True,
        diagnose=settings.debug,
    )

    # File handler — rotates at 50 MB, keeps 7 days of compressed logs
    logger.add(
        settings.log_file,
        format=fmt,
        level=settings.log_level,
        rotation="50 MB",
        retention="7 days",
        compression="zip",
        backtrace=True,
        diagnose=False,
    )

    logger.info(f"Logging initialized | level={settings.log_level} | file={settings.log_file}")
