def test_import_main_module():
    import main  # noqa: F401


def test_import_cogs():
    import cogs.core  # noqa: F401
    import cogs.admin  # noqa: F401
    import cogs.settings  # noqa: F401
    import cogs.raid  # noqa: F401
    import cogs.ticket  # noqa: F401
    import cogs.verification  # noqa: F401
    import cogs.absence  # noqa: F401
    import cogs.rolemenu  # noqa: F401
    import cogs.stuff  # noqa: F401
    import cogs.market  # noqa: F401
    import cogs.metamob  # noqa: F401
    import cogs.deathnote  # noqa: F401


def test_import_modules():
    import db  # noqa: F401
    import utils.dates  # noqa: F401
    import utils.poll  # noqa: F401
    import utils.embeds  # noqa: F401
    import utils.perms  # noqa: F401
    import utils.verification  # noqa: F401
    import utils.stuff_card  # noqa: F401
    import utils.stuff_capture  # noqa: F401
