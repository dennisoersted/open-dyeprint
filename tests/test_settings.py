from opendyeprint.settings import Settings, load, save


def test_roundtrip_with_devmode(tmp_path):
    p = tmp_path / "s.json"
    s = Settings(printer="X", paper_id=43, profile="C:/p.icc")
    s.set_devmode("X", b"\x00\x01binary")
    save(s, p)
    back = load(p)
    assert back.printer == "X" and back.paper_id == 43
    assert back.devmode_for("X") == b"\x00\x01binary"


def test_missing_or_corrupt_file_gives_defaults(tmp_path):
    assert load(tmp_path / "nope.json") == Settings()
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    assert load(bad) == Settings()


def test_unknown_keys_ignored(tmp_path):
    p = tmp_path / "s.json"
    p.write_text('{"printer": "Y", "from_the_future": 1}')
    assert load(p).printer == "Y"


def test_settings_carried_over_from_old_name(tmp_path, monkeypatch):
    from opendyeprint import settings as s
    monkeypatch.setenv("APPDATA", str(tmp_path))
    old = tmp_path / "Tintype" / "settings.json"
    old.parent.mkdir()
    old.write_text('{"printer": "Canon SELPHY CP1500", "intent": 1}')
    loaded = s.load()
    assert loaded.printer == "Canon SELPHY CP1500" and loaded.intent == 1
    s.save(loaded)
    assert (tmp_path / "Open DyePrint" / "settings.json").exists()
