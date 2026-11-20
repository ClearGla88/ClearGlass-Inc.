import json
import os

from guardian_core.cli import main
from gs_testlib import config_dict


def run(capsys, *argv):
    code = main(list(argv))
    out = capsys.readouterr()
    return code, out.out, out.err


def test_startup_in_design_mode(capsys):
    code, out, _ = run(capsys, "startup")
    assert code == 0 and "Design mode only." in out


def test_keygen_sign_check_and_startup_with_config(tmp_path, capsys):
    key, plain, signed = tmp_path / "k.hex", tmp_path / "plain.json", tmp_path / "signed.json"
    assert run(capsys, "keygen", str(key))[0] == 0
    assert oct(os.stat(key).st_mode & 0o777) == "0o600"
    cfg = config_dict(consent_expires_at="2099-01-01T00:00:00Z")
    plain.write_text(json.dumps(cfg))
    assert run(capsys, "sign-config", str(plain), str(signed), "--key", str(key))[0] == 0
    code, out, _ = run(capsys, "check-config", str(signed), "--key", str(key))
    assert code == 0 and "consent valid" in out
    code, out, _ = run(capsys, "startup", "--config", str(signed), "--key", str(key))
    assert code == 0 and "3 approved action(s); dispatcher unavailable" in out


def test_errors_exit_2_without_tracebacks(tmp_path, capsys):
    code, _, err = run(capsys, "check-config", str(tmp_path / "missing.json"), "--key", str(tmp_path / "nokey"))
    assert code == 2 and err.startswith("error:")
    code, _, err = run(capsys, "startup", "--config", "x.json")
    assert code == 2


def test_expired_consent_exits_1(tmp_path, capsys):
    key, plain, signed = tmp_path / "k.hex", tmp_path / "plain.json", tmp_path / "signed.json"
    run(capsys, "keygen", str(key))
    plain.write_text(json.dumps(config_dict(consent_expires_at="2026-11-02T00:00:00Z")))
    run(capsys, "sign-config", str(plain), str(signed), "--key", str(key))
    code, out, _ = run(capsys, "check-config", str(signed), "--key", str(key))
    assert code == 1 and "EXPIRED" in out


def test_lint_templates_passes(capsys):
    code, out, _ = run(capsys, "lint-templates")
    assert code == 0 and "0 with problems" in out
