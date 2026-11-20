"""packages/ui/tokens.json is the source of truth for the console's CSS custom properties."""

import json

from tests.conftest import ROOT


def test_css_declares_every_token_with_the_same_value():
    tokens = json.loads((ROOT / "packages" / "ui" / "tokens.json").read_text())
    css = (ROOT / "apps" / "web" / "src" / "app" / "globals.css").read_text()
    expected = {f"--cg-{k}": v for k, v in tokens["color"].items()}
    expected |= {f"--cg-radius-{k}": v for k, v in tokens["radius"].items()}
    expected |= {f"--cg-blur-{k}": v for k, v in tokens["blur"].items()}
    missing = [f"{name}: {value}" for name, value in expected.items() if f"{name}: {value};" not in css]
    assert not missing, f"globals.css drifted from tokens.json: {missing}"


def test_offline_snapshot_is_sample_data_and_verifies():
    snap = json.loads((ROOT / "apps" / "web" / "src" / "data" / "demo-snapshot.json").read_text())
    assert snap["audit"]["verify"]["ok"]
    assert snap["kpis"]["pipeline"]["is_sample_data"] is True
    assert snap["kpis"]["risk"]["external_actions_without_approval"] == 0
    assert "OFFICE_SECRET" not in json.dumps(snap)
