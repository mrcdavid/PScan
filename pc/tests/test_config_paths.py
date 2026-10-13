"""Installed-mode (per-user) paths vs. source-mode (repo) paths."""

from pscan_server import config
from pscan_server.config import PC_DIR, Config, load_config


def test_source_mode_uses_repo_folders(monkeypatch):
    monkeypatch.delenv("PSCAN_HOME", raising=False)
    monkeypatch.setattr(config.sys, "frozen", False, raising=False)
    cfg = load_config()
    assert cfg.config_path == PC_DIR / "config.toml"
    assert cfg.data_dir == PC_DIR / "data"
    # Default Scans folder is the repo's, never %USERPROFILE%.
    assert cfg.output_dir == (PC_DIR / "config.toml").parent.joinpath("../Scans").resolve()


def test_installed_mode_uses_home_and_profile(monkeypatch, tmp_path):
    home = tmp_path / "home"
    monkeypatch.setenv("PSCAN_HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "profile"))
    cfg = load_config()
    assert cfg.config_path == home / "config.toml"
    assert cfg.data_dir == home / "data"
    assert cfg.output_dir == tmp_path / "profile" / "PScan Scans"


def test_installed_first_run_seeds_config_from_template(monkeypatch, tmp_path):
    template = tmp_path / "bundle" / "config.toml"
    template.parent.mkdir(parents=True)
    template.write_text('port = 8765\npaper = "Letter"\n', encoding="utf-8")
    monkeypatch.setenv("PSCAN_HOME", str(tmp_path / "home"))
    monkeypatch.setattr(config, "_bundled_config_template", lambda: template)

    cfg = load_config()
    assert cfg.config_path.exists()  # copied into the user's home
    assert cfg.paper == "Letter"


def test_shipped_template_does_not_force_output_dir(monkeypatch, tmp_path):
    """First run of the installed app must default to %USERPROFILE%\\PScan Scans."""
    template = PC_DIR / "packaging" / "config.template.toml"
    assert template.exists(), "the packaged config template is missing"
    monkeypatch.setenv("PSCAN_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "profile"))
    monkeypatch.setattr(config, "_bundled_config_template", lambda: template)

    cfg = load_config()
    assert cfg.output_dir == tmp_path / "profile" / "PScan Scans"
    assert cfg.ocr is True and cfg.paper == "A4"


def test_save_output_dir_round_trips(tmp_path):
    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text('port = 8765\noutput_dir = "../Scans"\n', encoding="utf-8")
    cfg = load_config(path=cfg_path, data_dir=tmp_path / "data")

    target = tmp_path / "My Scans"
    cfg.save_output_dir(target)
    assert cfg.output_dir == target and target.is_dir()
    # Persisted and read back, even with a Windows-style path (backslashes escaped as TOML).
    assert load_config(path=cfg_path, data_dir=tmp_path / "data").output_dir == target


def test_save_output_dir_appends_when_absent(tmp_path):
    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text("port = 8765\n", encoding="utf-8")
    cfg = load_config(path=cfg_path, data_dir=tmp_path / "data")
    cfg.save_output_dir(tmp_path / "out")
    assert "output_dir = " in cfg_path.read_text(encoding="utf-8")


def test_find_tesseract_prefers_bundled(monkeypatch, tmp_path):
    bundled_dir = tmp_path / "app" / "tesseract"
    bundled_dir.mkdir(parents=True)
    exe = bundled_dir / "tesseract.exe"
    exe.write_text("", encoding="utf-8")
    monkeypatch.setattr(config, "app_dir", lambda: tmp_path / "app")
    cfg = Config(
        server_name="x",
        port=1,
        discovery_port=2,
        output_dir=tmp_path,
        default_mode="color",
        ocr=True,
        ocr_lang="eng",
        tesseract_path="",
        max_long_edge=3000,
        jpeg_quality=85,
        data_dir=tmp_path / "data",
    )
    assert cfg.find_tesseract() == str(exe)
