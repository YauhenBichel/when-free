"""Settings: the file, then environment variables. Imported as `settings` by the rest of the package."""
from .config import (  # noqa: F401
    TEMPLATE,
    Calendar,
    Config,
    ConfigError,
    add_calendar,
    default_path,
    load,
    now,
    system_timezone,
    write_template,
)
