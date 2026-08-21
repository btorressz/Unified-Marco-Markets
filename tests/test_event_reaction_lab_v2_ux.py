from pathlib import Path


def test_reaction_lab_v2_sections_and_safety_copy():
    ui=Path("frontend/assets/ui.js").read_text()
    for label in ("PRICE REACTIONS","FUNDING REACTIONS","BASIS REACTIONS","REGIME PATH","EVENT-LINKED DECISIONS","COVERAGE &amp; PROVENANCE"):
        assert label in ui
    assert "NOT MATURED" in ui and "UNAVAILABLE" in ui and "BLOCK outcomes are counterfactual" in ui
    assert "Annualized Basis" not in ui


def test_stale_basis_feasibility_client_removed():
    assert "getBasisFeasibility" not in Path("frontend/assets/api.js").read_text()
