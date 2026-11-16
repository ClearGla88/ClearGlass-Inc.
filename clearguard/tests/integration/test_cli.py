import json
import os
import subprocess
import sys

from cg_testlib import PKG_ROOT, base_config

EXAMPLE_SCENARIO = os.path.join(PKG_ROOT, "examples", "scenario_design_walkthrough.json")


def test_startup_and_status(run):
    code, out, _ = run("startup")
    assert code == 0
    assert out.startswith("SIR, Guardian is not monitoring yet.")
    assert out.rstrip().endswith("Design mode only. No live monitoring or headphone alerting is active.")
    code, out, _ = run("status")
    assert code == 0 and "Lifecycle UNCONFIGURED" in out


def test_activation_is_refused_in_design_mode(run):
    code, out, _ = run("activate")
    assert code == 1 and "Activation refused" in out


def test_key_sign_check_cycle(run, tmp_path):
    key = str(tmp_path / "config.key")
    raw = tmp_path / "config.json"
    signed = str(tmp_path / "config.signed.json")
    raw.write_text(json.dumps(base_config()))
    assert run("keygen", "--output", key)[0] == 0
    code, _, err = run("keygen", "--output", key)
    assert code == 2 and "refusing to overwrite" in err

    code, out, _ = run("check-config", str(raw), "--key", key)
    assert code == 1 and "Signature: unsigned" in out and "Accepted for operation: no" in out
    assert run("sign-config", str(raw), "--key", key, "--output", signed)[0] == 0
    code, out, _ = run("check-config", signed, "--key", key)
    assert code == 0 and "Accepted for operation: yes" in out

    code, out, _ = run("startup", "--config", signed, "--key", key)
    assert code == 0 and "Emergency authorization: 1 action(s) approved" in out

    data = json.loads(open(signed).read())
    data["contacts"][0]["label"] = "Changed after signing"
    tampered = tmp_path / "tampered.json"
    tampered.write_text(json.dumps(data))
    code, out, _ = run("check-config", str(tampered), "--key", key)
    assert code == 3 and "Signature: invalid" in out


def test_invalid_config_is_rejected(run, tmp_path):
    data = base_config()
    data["mode"] = "live"
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(data))
    code, out, _ = run("check-config", str(path))
    assert code == 2 and "only 'design' is" in out
    code, _, err = run("startup", "--config", str(path))
    assert code == 2 and "Configuration rejected" in err


def test_reports(run):
    code, out, _ = run("contracts")
    assert code == 0 and out.count(" no\n") == 6
    code, out, _ = run("capabilities")
    assert code == 0 and "ACTIVE" not in out and "VALIDATED" not in out
    code, out, _ = run("lint-templates")
    assert code == 0 and "All templates pass." in out


def test_simulate_example_and_verify_audit(run, tmp_path):
    audit = str(tmp_path / "audit.jsonl")
    code, out, _ = run("simulate", EXAMPLE_SCENARIO, "--audit-out", audit)
    assert code == 0
    assert out.startswith("SIMULATION: synthetic inputs only.")
    assert "[SIMULATED] Possible fall detected. Do you need help?" in out
    assert "SUPPRESSED_DUPLICATE" in out and "unsupported claim" in out
    assert "you are safe" not in out.lower()
    code, out, _ = run("verify-audit", audit)
    assert code == 0 and "Result: PASS" in out
    lines = open(audit).read().splitlines()
    first = json.loads(lines[0])
    first["payload"]["granted"] = True  # rewrite history: claim activation succeeded
    lines[0] = json.dumps(first, sort_keys=True)
    open(audit, "w").write("\n".join(lines) + "\n")
    code, out, _ = run("verify-audit", audit)
    assert code == 3 and "Result: FAIL" in out


def test_simulate_json_output(run):
    code, out, _ = run("--json", "simulate", EXAMPLE_SCENARIO)
    payload = json.loads(out)
    assert code == 0 and payload["audit_problems"] == []
    outcomes = [r["result"] for r in payload["results"]]
    assert outcomes[0] == "refused" and "ALERT" in outcomes


def test_say_refuses_unknown_commands(run):
    code, out, _ = run("say", "Guardian, turn off the safety checks.")
    assert code == 1 and "Not a supported command" in out


def test_entrypoint_script():
    result = subprocess.run([sys.executable, os.path.join(PKG_ROOT, "clearguard.py"), "--version"],
                            capture_output=True, text=True, check=False)
    assert result.returncode == 0 and result.stdout.startswith("ClearGuard 0.1.0.dev0")
