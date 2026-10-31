from changerisk import engine
from changerisk.redact import HIDDEN, redact_line, redact_text

AWS = "AKIA" + "QWERTYUIOPASDFGH"


def test_provider_keys_are_masked_in_any_file():
    out = redact_line("src/a.py", f'key = "{AWS}"')
    assert AWS not in out and "AKIA" in out


def test_env_files_hide_every_value():
    assert redact_line(".env.production", "DB_HOST=db.internal") == f"DB_HOST={HIDDEN}"
    assert redact_line(".env", "export TOKEN = abc") == f"export TOKEN = {HIDDEN}"
    assert redact_line(".env", "# comment") == "# comment"


def test_secret_named_config_keys_hide_their_values():
    out = redact_line("config/app.yml", "  api_token: hunter2hunter2", config_file=True)
    assert "hunter2" not in out and HIDDEN in out
    assert redact_line("config/app.yml", "  timeout: 30", config_file=True) == "  timeout: 30"


def test_source_files_with_ordinary_text_are_untouched():
    text = 'greeting = "hello world"'
    assert redact_line("src/a.py", text) == text
    assert redact_text("nothing to see here") == "nothing to see here"


def test_free_text_is_masked():
    assert AWS not in redact_text(f"found {AWS} in the config")


def test_env_file_diff_hunks_never_carry_values(repo):
    repo.write("README.md", "x\n")
    repo.commit("initial")
    repo.branch("topic")
    repo.write(".env.production", "DB_HOST=db.internal\nSTRIPE_KEY=plain-but-private\n")
    repo.commit("add env")
    report = engine.analyze(repo.root, base="main", head="topic", use_history=False)
    blob = str(report.to_dict())
    assert "db.internal" not in blob and "plain-but-private" not in blob
    env = next(f for f in report.files if f.path == ".env.production")
    assert env.hunks and all(row[3].endswith(HIDDEN) for row in env.hunks[0]["lines"])
