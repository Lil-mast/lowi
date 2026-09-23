"""Create tables and the default local user."""

from app.config import get_settings
from app.db.session import configure_engine, init_db


def main() -> None:
    settings = get_settings()
    configure_engine(settings.database_url)
    init_db(settings)


if __name__ == "__main__":
    main()
