from scripts import design_cap_quality_benchmark as bench


def test_design_pilot_reuses_three_legacy_domains_and_sol():
    assert bench.DOMAINS == ("ui-ux", "graphic-design", "three-d-design")
    assert bench.MODEL == "gpt-5.6-sol"
    assert bench.CAPS == {"cap8_plain": 8, "cap6_plain": 6}


def test_plain_prompt_excludes_legacy_batching_instruction(tmp_path):
    packet = bench.PlainPacket(tmp_path, "ui-ux", 6)
    assert "Hard envelope: 6" in packet.render()
    assert "Batch independent inspection" not in packet.render()
