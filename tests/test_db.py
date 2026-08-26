from datetime import datetime
from zoneinfo import ZoneInfo

import db

PARIS = ZoneInfo("Europe/Paris")


def _fresh(tmp_path):
    db.reset_for_tests(str(tmp_path / "t.db"))


def test_create_and_get(tmp_path):
    _fresh(tmp_path)
    rid = db.create_raid(
        name="Gigalodon",
        date_iso="2026-06-28",
        poll_duration_seconds=3600,
        created_by=1,
        guild_id=2,
        channel_id=3,
        state="voting_hour",
        hour_poll_closes_at=datetime(2026, 6, 25, 13, 0, tzinfo=PARIS),
    )
    raid = db.get_raid(rid)
    assert raid["name"] == "Gigalodon"
    assert raid["state"] == "voting_hour"
    assert raid["poll_duration_seconds"] == 3600
    assert raid["capacity_removed"] == 0
    assert raid["level_200_only"] == 0


def test_hot_path_indexes_are_created(tmp_path):
    _fresh(tmp_path)
    rows = db._db().execute(
        "SELECT name FROM sqlite_master WHERE type = 'index'"
    ).fetchall()
    index_names = {row["name"] for row in rows}

    for name in (
        "idx_raids_state_id",
        "idx_votes_raid_kind_choice",
        "idx_participants_raid_status_joined",
        "idx_absences_search",
        "idx_market_posts_inactive",
        "idx_metamob_links_guild_user",
        "idx_metamob_trades_thread",
        "idx_metamob_trade_items_trade",
    ):
        assert name in index_names


def test_schema_migrations_are_tracked(tmp_path):
    _fresh(tmp_path)
    migrations = db.list_schema_migrations()

    assert len(migrations) == len(db.MIGRATIONS)
    assert migrations[0]["version"] == "001_raids_fixed_hour"


def test_health_check_reports_db_and_activity(tmp_path):
    _fresh(tmp_path)
    db.create_raid(
        name="Gigalodon",
        date_iso="2026-06-28",
        poll_duration_seconds=3600,
        created_by=1,
        guild_id=2,
        channel_id=3,
        state="scheduled",
    )

    health = db.health_check()

    assert health["quick_check"] == "ok"
    assert health["migration_count"] == len(db.MIGRATIONS)
    assert health["active_raid_count"] == 1


def test_votes_changeable_and_counts(tmp_path):
    _fresh(tmp_path)
    rid = db.create_raid(
        name=None, date_iso="2026-06-28", poll_duration_seconds=3600,
        created_by=1, guild_id=2, channel_id=3, state="choosing_raid",
    )
    db.cast_vote(rid, 100, "raid", "Gigalodon")
    db.cast_vote(rid, 100, "raid", "Jardins Éternels")  # changement
    db.cast_vote(rid, 200, "raid", "Gigalodon")
    counts = db.get_vote_counts(rid, "raid")
    assert counts["Gigalodon"] == 1
    assert counts["Jardins Éternels"] == 1
    assert db.get_voters(rid, "raid", "Gigalodon") == [200]


def test_level_choice_for_hour_votes(tmp_path):
    _fresh(tmp_path)
    rid = db.create_raid(
        name="Gigalodon", date_iso="2026-06-28", poll_duration_seconds=3600,
        created_by=1, guild_id=2, channel_id=3, state="voting_hour",
    )
    db.set_level_choice(rid, 100, "199_minus")
    db.toggle_vote(rid, 100, "hour", "20")
    db.set_level_choice(rid, 200, "199_minus")
    db.set_level_choice(rid, 300, "200_plus")
    db.toggle_vote(rid, 300, "hour", "21")

    assert db.get_level_choice(rid, 100) == "199_minus"
    assert db.get_level_choice(rid, 999) is None
    assert db.count_active_level_choices(rid, "199_minus") == 1
    assert db.count_active_level_choices(rid, "200_plus") == 1


def test_participants(tmp_path):
    _fresh(tmp_path)
    rid = db.create_raid(
        name="Gigalodon", date_iso="2026-06-28", poll_duration_seconds=3600,
        created_by=1, guild_id=2, channel_id=3, state="scheduled",
    )
    db.add_participant(rid, 10)
    db.add_participant(rid, 10)  # doublon ignoré
    db.add_participant(rid, 20)
    assert db.count_participants(rid) == 2
    assert {u for u, _, _ in db.get_participants(rid)} == {10, 20}
    assert db.get_participant_level_group(rid, 10) == "200_plus"


def test_participant_level_group(tmp_path):
    _fresh(tmp_path)
    rid = db.create_raid(
        name="Gigalodon", date_iso="2026-06-28", poll_duration_seconds=3600,
        created_by=1, guild_id=2, channel_id=3, state="scheduled",
    )
    db.add_participant(rid, 10, "confirmed", "199_minus")
    db.add_participant(rid, 20, "waitlist", "200_plus")
    assert db.get_participant_level_group(rid, 10) == "199_minus"
    assert db.count_level_group(rid, "199_minus") == 1
    assert db.count_level_group(rid, "200_plus") == 1
    assert db.get_participants(rid) == [
        (10, "confirmed", "199_minus"),
        (20, "waitlist", "200_plus"),
    ]


def test_is_participant(tmp_path):
    _fresh(tmp_path)
    rid = db.create_raid(
        name="Gigalodon", date_iso="2026-06-28", poll_duration_seconds=3600,
        created_by=1, guild_id=2, channel_id=3, state="scheduled",
    )
    assert db.is_participant(rid, 10) is False
    db.add_participant(rid, 10)
    assert db.is_participant(rid, 10) is True
    assert db.is_participant(rid, 99) is False


def test_raid_ban_is_active_until_expiration(tmp_path):
    _fresh(tmp_path)
    now = datetime(2026, 6, 25, 12, 0, tzinfo=PARIS)
    db.set_raid_ban(
        guild_id=2,
        user_id=10,
        banned_until=datetime(2026, 6, 28, 12, 0, tzinfo=PARIS),
        reason="absence répétée",
        created_by=1,
    )

    active = db.get_active_raid_ban(guild_id=2, user_id=10, now=now)
    assert active is not None
    assert active["reason"] == "absence répétée"
    assert db.get_active_raid_ban(
        guild_id=2,
        user_id=10,
        now=datetime(2026, 6, 29, 12, 0, tzinfo=PARIS),
    ) is None


def test_list_active_raid_bans_filters_and_orders(tmp_path):
    _fresh(tmp_path)
    now = datetime(2026, 6, 25, 12, 0, tzinfo=PARIS)
    db.set_raid_ban(
        guild_id=2,
        user_id=10,
        banned_until=datetime(2026, 6, 28, 12, 0, tzinfo=PARIS),
        reason="trois absences",
        created_by=1,
    )
    db.set_raid_ban(
        guild_id=2,
        user_id=20,
        banned_until=datetime(2026, 6, 27, 12, 0, tzinfo=PARIS),
        reason="deux absences",
        created_by=1,
    )
    db.set_raid_ban(
        guild_id=2,
        user_id=30,
        banned_until=datetime(2026, 6, 24, 12, 0, tzinfo=PARIS),
        reason="expiré",
        created_by=1,
    )
    db.set_raid_ban(
        guild_id=3,
        user_id=40,
        banned_until=datetime(2026, 6, 29, 12, 0, tzinfo=PARIS),
        reason="autre guilde",
        created_by=1,
    )

    assert [row["user_id"] for row in db.list_active_raid_bans(guild_id=2, now=now)] == [20, 10]


def test_deathnote_entry_upsert_list_and_delete(tmp_path):
    _fresh(tmp_path)
    db.upsert_deathnote_entry(
        guild_id=2,
        pseudo="Éni-Bob",
        normalized_pseudo="eni-bob",
        reason="toxique",
        created_by=1,
    )
    db.upsert_deathnote_entry(
        guild_id=2,
        pseudo="Eni-Bob",
        normalized_pseudo="eni-bob",
        reason="reroll suspect",
        created_by=3,
    )

    rows = db.list_deathnote_entries(guild_id=2)

    assert len(rows) == 1
    assert rows[0]["pseudo"] == "Eni-Bob"
    assert rows[0]["reason"] == "reroll suspect"
    assert rows[0]["created_by"] == 3
    assert db.get_deathnote_entry(guild_id=2, normalized_pseudo="eni-bob") is not None
    assert db.delete_deathnote_entry(guild_id=2, normalized_pseudo="eni-bob") is True
    assert db.list_deathnote_entries(guild_id=2) == []


def test_update_and_state_serializes_datetime(tmp_path):
    _fresh(tmp_path)
    rid = db.create_raid(
        name="Gigalodon", date_iso="2026-06-28", poll_duration_seconds=3600,
        created_by=1, guild_id=2, channel_id=3, state="voting_hour",
    )
    db.update_raid(
        rid, state="scheduled",
        scheduled_at=datetime(2026, 6, 28, 21, 0, tzinfo=PARIS),
    )
    raid = db.get_raid(rid)
    assert raid["state"] == "scheduled"
    assert raid["scheduled_at"] == "2026-06-28T21:00:00+02:00"


def test_tickets(tmp_path):
    _fresh(tmp_path)
    db.create_ticket(channel_id=111, guild_id=2, opener_id=5)
    ticket = db.get_ticket_by_channel(111)
    assert ticket["opener_id"] == 5
    assert ticket["closed"] == 0
    db.close_ticket(111)
    assert db.get_ticket_by_channel(111)["closed"] == 1


def test_onboarding_tickets(tmp_path):
    _fresh(tmp_path)
    db.create_ticket(channel_id=111, guild_id=2, opener_id=5)
    db.create_onboarding_ticket(channel_id=111, guild_id=2, user_id=5)

    ticket = db.get_onboarding_ticket_by_channel(111)
    assert ticket["status"] == "pending"
    assert db.get_open_onboarding_ticket_for_user(guild_id=2, user_id=5)["channel_id"] == 111

    close_after = datetime(2026, 6, 28, 21, 0, tzinfo=PARIS)
    db.update_onboarding_ticket(
        111,
        choice="visitor",
        status="visitor_granted",
        application_pseudo="Belette-Royale",
        application_classes="Eniripsa 200",
        application_goals="PvM",
        close_after=close_after,
    )
    pending_close = db.list_onboarding_tickets_with_close_after()
    assert pending_close[0]["choice"] == "visitor"
    assert pending_close[0]["application_pseudo"] == "Belette-Royale"
    assert pending_close[0]["application_classes"] == "Eniripsa 200"
    assert pending_close[0]["application_goals"] == "PvM"
    assert pending_close[0]["close_after"] == "2026-06-28T21:00:00+02:00"

    db.close_onboarding_ticket(111)
    assert db.get_onboarding_ticket_by_channel(111)["status"] == "closed"
    assert db.get_ticket_by_channel(111)["closed"] == 1


def test_role_menus_components_and_options(tmp_path):
    _fresh(tmp_path)
    menu_id = db.create_role_menu(
        guild_id=2,
        channel_id=111,
        title="Choisis tes rôles",
        description="Prends ce qui te correspond.",
        color=0x2ECC71,
        footer="Modifiable à tout moment",
        image_url=None,
        thumbnail_url=None,
        created_by=5,
    )
    db.update_role_menu(menu_id, message_id=999)
    button_id = db.add_role_menu_component(
        menu_id=menu_id,
        component_type="button",
        label="Raid",
        style="primary",
        role_id=123,
    )
    select_id = db.add_role_menu_component(
        menu_id=menu_id,
        component_type="select",
        placeholder="Classes",
        min_values=0,
        max_values=2,
    )
    option_id = db.add_role_menu_option(
        component_id=select_id,
        role_id=456,
        label="Cra",
        description="Dégâts distance",
    )

    menu = db.get_role_menu_by_message(999)
    assert menu["id"] == menu_id
    assert [row["id"] for row in db.list_role_menu_components(menu_id)] == [button_id, select_id]
    assert db.get_role_menu_component(button_id)["role_id"] == 123
    assert db.get_role_menu_option(option_id)["label"] == "Cra"
    assert db.list_role_menu_options(select_id)[0]["role_id"] == 456

    db.update_role_menu_component(button_id, label="PvP", style="danger", exclusive=1)
    db.update_role_menu_option(option_id, label="Iop", description="Dégâts mêlée")
    assert db.get_role_menu_component(button_id)["label"] == "PvP"
    assert db.get_role_menu_component(button_id)["exclusive"] == 1
    assert db.get_role_menu_option(option_id)["description"] == "Dégâts mêlée"

    db.delete_role_menu_component(select_id)
    assert db.list_role_menu_options(select_id) == []


def test_absences_search_and_cleanup(tmp_path):
    _fresh(tmp_path)
    a1 = db.create_absence(
        guild_id=2,
        user_id=10,
        user_display="Alice",
        start_date="2026-07-10",
        end_date="2026-07-12",
        public_channel_id=100,
        public_message_id=1000,
        admin_channel_id=200,
        admin_message_id=2000,
    )
    db.create_absence(
        guild_id=2,
        user_id=20,
        user_display="Bob",
        start_date="2026-07-11",
        end_date="2026-07-13",
        public_channel_id=100,
        public_message_id=1001,
    )
    db.create_absence(
        guild_id=3,
        user_id=10,
        user_display="Alice",
        start_date="2026-07-11",
        end_date="2026-07-13",
        public_channel_id=100,
        public_message_id=1002,
    )

    assert [row["id"] for row in db.search_absences(guild_id=2, today_iso="2026-07-10")] == [a1, a1 + 1]
    assert [row["id"] for row in db.search_absences(guild_id=2, user_id=10, today_iso="2026-07-10")] == [a1]

    db.mark_absence_public_deleted(a1)
    assert [row["id"] for row in db.search_absences(guild_id=2, today_iso="2026-07-10")] == [a1 + 1]
    assert [row["id"] for row in db.list_absences_for_cleanup()] == [a1 + 1, a1 + 2]


def test_list_active_excludes_terminal(tmp_path):
    _fresh(tmp_path)
    db.create_raid(
        name="A", date_iso="2026-06-28", poll_duration_seconds=3600,
        created_by=1, guild_id=2, channel_id=3, state="voting_hour",
    )
    db.create_raid(
        name="B", date_iso="2026-06-28", poll_duration_seconds=3600,
        created_by=1, guild_id=2, channel_id=3, state="done",
    )
    db.create_raid(
        name="C", date_iso="2026-06-28", poll_duration_seconds=3600,
        created_by=1, guild_id=2, channel_id=3, state="breaking_hour_tie",
    )
    assert len(db.list_active_raids()) == 2


def test_create_raid_stores_poll_hours(tmp_path):
    _fresh(tmp_path)
    rid = db.create_raid(
        name="Gigalodon", date_iso="2026-06-28", poll_duration_seconds=3600,
        created_by=1, guild_id=2, channel_id=3, state="voting_hour", poll_hours=[19, 20, 21],
    )
    assert db.get_raid(rid)["poll_hours"] == "19,20,21"


def test_create_raid_stores_poll_close_hour(tmp_path):
    _fresh(tmp_path)
    rid = db.create_raid(
        name="Gigalodon", date_iso="2026-06-28", poll_close_hour=12,
        created_by=1, guild_id=2, channel_id=3, state="voting_hour",
    )
    assert db.get_raid(rid)["poll_close_hour"] == 12


def test_list_raids_with_messages(tmp_path):
    _fresh(tmp_path)
    # Scheduled avec scheduled_message_id -> inclus.
    r1 = db.create_raid(
        name="A", date_iso="2026-06-28", poll_duration_seconds=3600,
        created_by=1, guild_id=2, channel_id=3, state="scheduled",
    )
    db.update_raid(r1, scheduled_at=datetime(2026, 6, 28, 21, 0, tzinfo=PARIS), scheduled_message_id=111)
    # Pas de scheduled_at ni message -> exclu.
    db.create_raid(
        name="B", date_iso="2026-06-28", poll_duration_seconds=3600,
        created_by=1, guild_id=2, channel_id=3, state="voting_hour",
    )
    # Cancelled avec message -> exclu (annulé, message conservé).
    r3 = db.create_raid(
        name="C", date_iso="2026-06-28", poll_duration_seconds=3600,
        created_by=1, guild_id=2, channel_id=3, state="cancelled",
    )
    db.update_raid(r3, scheduled_at=datetime(2026, 6, 28, 21, 0, tzinfo=PARIS), scheduled_message_id=333)
    assert [r["id"] for r in db.list_raids_with_messages()] == [r1]


def test_toggle_vote_multi(tmp_path):
    _fresh(tmp_path)
    rid = db.create_raid(
        name="X", date_iso="2026-06-28", created_by=1, guild_id=2, channel_id=3, state="voting_hour",
    )
    # Multi-vote : un user peut voter plusieurs créneaux qui coexistent.
    assert db.toggle_vote(rid, 100, "hour", "20") is True   # ajout
    assert db.toggle_vote(rid, 100, "hour", "21") is True   # ajout (2e créneau)
    assert db.get_user_votes(rid, 100, "hour") == ["20", "21"]
    # Re-clic sur un créneau déjà voté -> le retire sans toucher aux autres.
    assert db.toggle_vote(rid, 100, "hour", "20") is False
    assert db.get_user_votes(rid, 100, "hour") == ["21"]
    assert db.get_vote_counts(rid, "hour") == {"21": 1}


def test_replace_votes(tmp_path):
    _fresh(tmp_path)
    rid = db.create_raid(
        name="X", date_iso="2026-06-28", created_by=1, guild_id=2, channel_id=3, state="voting_hour",
    )
    db.toggle_vote(rid, 100, "hour", "20")
    db.toggle_vote(rid, 100, "hour", "21")
    db.replace_votes(rid, 100, "hour", ["14", "15", "16"])
    assert db.get_user_votes(rid, 100, "hour") == ["14", "15", "16"]
    assert db.get_vote_counts(rid, "hour") == {"14": 1, "15": 1, "16": 1}
    db.replace_votes(rid, 100, "hour", [])
    assert db.get_user_votes(rid, 100, "hour") == []
    assert db.get_vote_counts(rid, "hour") == {}


def test_waitlist_promotion(tmp_path):
    _fresh(tmp_path)
    rid = db.create_raid(
        name="X", date_iso="2026-06-28", created_by=1, guild_id=2, channel_id=3, state="scheduled",
    )
    db.add_participant(rid, 1, "confirmed")
    db.add_participant(rid, 2, "confirmed")
    db.add_participant(rid, 3, "waitlist")
    db.add_participant(rid, 4, "waitlist")
    assert db.count_confirmed(rid) == 2
    assert db.count_waitlist(rid) == 2
    # Ordre FIFO de la file d'attente.
    assert db.waitlist_position(rid, 3) == 1
    assert db.waitlist_position(rid, 4) == 2
    # Retirer un confirmé -> promeut le 1er de la file (user 3).
    assert db.remove_participant(rid, 1) == 3
    assert db.get_participant_status(rid, 3) == "confirmed"
    assert db.count_confirmed(rid) == 2
    assert db.count_waitlist(rid) == 1
    # Retirer un waitlist -> aucune promotion.
    assert db.remove_participant(rid, 4) is None
    assert db.count_waitlist(rid) == 0
    # get_participants ordonne confirmés puis liste d'attente.
    db.add_participant(rid, 5, "waitlist")
    parts = db.get_participants(rid)
    assert {u for u, _, _ in parts} == {2, 3, 5}
    assert [u for u, s, _ in parts if s == "waitlist"] == [5]


def test_waitlist_promotion_can_skip_ineligible_users(tmp_path):
    _fresh(tmp_path)
    rid = db.create_raid(
        name="X", date_iso="2026-06-28", created_by=1, guild_id=2, channel_id=3, state="scheduled",
    )
    db.add_participant(rid, 1, "confirmed")
    db.add_participant(rid, 2, "waitlist")
    db.add_participant(rid, 3, "waitlist")

    assert db.remove_participant(rid, 1, eligible_waitlist_user_ids={3}) == 3
    assert db.get_participant_status(rid, 2) == "waitlist"
    assert db.get_participant_status(rid, 3) == "confirmed"


def test_metamob_link_upsert_and_delete(tmp_path):
    _fresh(tmp_path)
    db.upsert_metamob_link(
        guild_id=2,
        user_id=10,
        api_key="secret-1",
        quest_slug="abc123",
        username="Garfunk",
        character_name="Perso",
        server_name="Draconiros",
        quest_type_slug="ocre",
    )
    link = db.get_metamob_link(2, 10)
    assert link["api_key"] == "secret-1"
    assert link["quest_slug"] == "abc123"
    assert link["character_name"] == "Perso"
    assert [row["user_id"] for row in db.list_metamob_links_for_guild(2)] == [10]

    db.upsert_metamob_link(
        guild_id=2,
        user_id=10,
        api_key="secret-2",
        quest_slug="def456",
        character_name="Autre",
    )
    updated = db.get_metamob_link(2, 10)
    assert updated["api_key"] == "secret-2"
    assert updated["quest_slug"] == "def456"
    assert updated["character_name"] == "Autre"

    assert db.delete_metamob_link(2, 10) is True
    assert db.get_metamob_link(2, 10) is None
    assert db.delete_metamob_link(2, 10) is False


def test_metamob_trade_items_and_status(tmp_path):
    _fresh(tmp_path)
    trade_id = db.create_metamob_trade(
        guild_id=2,
        thread_id=300,
        forum_channel_id=200,
        starter_id=10,
        target_id=20,
        control_message_id=400,
    )
    trade = db.get_metamob_trade(trade_id)
    assert trade["status"] == "open"
    assert db.get_metamob_trade_by_thread(300)["id"] == trade_id

    db.add_metamob_trade_item(
        trade_id=trade_id,
        monster_id=123,
        monster_name="Arachitik la Souffreteuse",
        giver_id=10,
        receiver_id=20,
    )
    db.add_metamob_trade_item(
        trade_id=trade_id,
        monster_id=123,
        monster_name="Arachitik la Souffreteuse",
        giver_id=10,
        receiver_id=20,
    )
    items = db.list_metamob_trade_items(trade_id)
    assert len(items) == 1
    assert items[0]["quantity"] == 2
    assert db.remove_metamob_trade_item(trade_id=trade_id, monster_id=123, giver_id=10) is True
    assert db.list_metamob_trade_items(trade_id)[0]["quantity"] == 1
    assert db.remove_metamob_trade_item(trade_id=trade_id, monster_id=123, giver_id=10) is True
    assert db.list_metamob_trade_items(trade_id) == []
    assert db.remove_metamob_trade_item(trade_id=trade_id, monster_id=123, giver_id=10) is False

    db.add_metamob_trade_item(
        trade_id=trade_id,
        monster_id=123,
        monster_name="Arachitik la Souffreteuse",
        giver_id=10,
        receiver_id=20,
    )

    db.update_metamob_trade(trade_id, status="pending_confirm", confirmed_by=10)
    assert db.get_metamob_trade(trade_id)["confirmed_by"] == 10
    db.clear_metamob_trade_confirmation(trade_id)
    reopened = db.get_metamob_trade(trade_id)
    assert reopened["status"] == "open"
    assert reopened["confirmed_by"] is None
