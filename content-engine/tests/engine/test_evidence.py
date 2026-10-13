from engine.evidence import build_evidence_pack


def test_build_evidence_pack_keeps_source_link_and_angles():
    candidate = {
        "dedupe_key": "github:owner/repo",
        "source": "github",
        "title": "AI Screenshot Agent",
        "url": "https://github.com/owner/repo",
        "summary": "An AI agent that takes screenshots and writes content drafts.",
        "raw": {"stars": 300, "forks": 20},
        "total": 82.0,
        "reason": "high clarity and usefulness",
    }

    pack = build_evidence_pack(candidate)

    assert pack.url == "https://github.com/owner/repo"
    assert "一手来源" in pack.facts[0]
    assert any("普通读者" in angle for angle in pack.writing_angles)
    assert pack.risks
