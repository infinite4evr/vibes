import sys

if "--search-provider" in sys.argv[1:]:  # GNOME Activities search, started by D-Bus; no window, no GTK
    from .search_provider import main as provider_main
    sys.exit(provider_main())

from .main import main  # noqa: E402

sys.exit(main())
