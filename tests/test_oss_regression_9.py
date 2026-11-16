import pytest
import yaml

from pypsa_chile.config import load_config


def _share_override(tmp_path, share, remainder):
    path = tmp_path / "shares.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "demand": {
                    "zone_shares": {
                        "norte_grande": share,
                        "norte_chico": 0,
                        "centro": remainder,
                        "sur": 0,
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    return path


@pytest.mark.parametrize(
    ("share", "remainder"),
    [
        pytest.param(-0.25, 1.25, id="negative-with-unit-total"),
        pytest.param(float("nan"), 0.75, id="nan"),
        pytest.param(float("inf"), 0.75, id="positive-infinity"),
        pytest.param(float("-inf"), 0.75, id="negative-infinity"),
        pytest.param("0.25", 0.75, id="numeric-text"),
        pytest.param("invalid", 0.75, id="text"),
        pytest.param(None, 0.75, id="null"),
        pytest.param(True, 0, id="boolean"),
    ],
)
def test_load_config_rejects_invalid_zone_share(tmp_path, share, remainder):
    error = None
    try:
        load_config(_share_override(tmp_path, share, remainder))
    except (TypeError, ValueError) as exc:
        error = exc

    assert isinstance(error, ValueError), (
        f"invalid share {share!r} must raise ValueError, got {error!r}"
    )
    assert "demand.zone_shares" in str(error)
    assert "norte_grande" in str(error)


@pytest.mark.parametrize(
    ("share", "remainder"),
    [(0, 1), (1, 0), (0.25, 0.75), (0.2500005, 0.75)],
)
def test_load_config_keeps_valid_zone_shares(tmp_path, share, remainder):
    cfg = load_config(_share_override(tmp_path, share, remainder))
    assert cfg["demand"]["zone_shares"]["norte_grande"] == share
    assert cfg["demand"]["zone_shares"]["centro"] == remainder
