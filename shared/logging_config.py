"""
Logging configuration for PowerFlex Demo services.

Provides consistent logging setup across all components avec MDM, SDS, SDC, MGMT.
"""

import logging
import sys
from pathlib import Path
from typing import Optional

def setup_logging(
    component_name: str,
    level=logging.INFO,
    log_file: Optional[str] = None,
    format_string: Optional[str] = None
):
    """
    Configure logging for a PowerFlex component.
    
    Args:
        component_name: Component identifier (e.g., 'mdm', 'mgmt')
        level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        log_file: Optional file path for log output
        format_string: Custom format string (default provided)
    """
    if format_string is None:
        format_string = f'[%(asctime)s] [{component_name.upper()}] %(levelname)s - %(message)s'
    
    # Configure root logger
    logging.basicConfig(
        level=level,
        format=format_string,
        datefmt='%Y-%m-%d %H:%M:%S',
        handlers=[
            logging.StreamHandler(sys.stdout)
        ]
    )
    
    # Add file handler if specified
    if log_file:
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_file)
        file_handler.setFormatter(logging.Formatter(format_string, datefmt='%Y-%m-%d %H:%M:%S'))
        logging.getLogger().addHandler(file_handler)
    
    logger = logging.getLogger(component_name)
    logger.info(f"{component_name.upper()} logging initialized (level={logging.getLevelName(level)})")
    
    return logger
