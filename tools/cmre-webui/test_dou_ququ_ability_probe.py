from pathlib import Path

from dou_ququ_ability_probe import PROBE_MARKER, _inject_probe_setup


def test_inject_probe_setup_only_changes_staged_map(tmp_path: Path):
    source = tmp_path / "source.galaxy"
    source.write_text(
        'void lllzbD(bool a, bool b) {}\n'
        'unit lllkDt; int lllbOS;\n'
        'void lllNAn() {}\n'
        'void lllnIs() {}\n'
        'void InitMap(){lllAtg();lllNAn();lllnIs();}\n',
        encoding="utf-8",
    )
    original = source.read_text(encoding="utf-8")
    _inject_probe_setup(source)
    patched = source.read_text(encoding="utf-8")
    assert original != patched
    assert PROBE_MARKER in patched
    assert "douQuquAbilityProbeSetup();" in patched
    assert 'SetDialogItemEditorValue(lllbOS, \"Marine\"' in patched
