import pytest

from backend.database import DATA, DOCUMENTS


def test_list_sections(client):
    manual = client.get("/api/documents/claims_manual/sections").json()
    assert [s["section"] for s in manual] == list(range(1, 15))
    assert manual[8] == {"section": 9, "title": "Repeat claims"}
    wording = client.get("/api/documents/policy_wording/sections").json()
    assert len(wording) == 12
    assert wording[9]["title"] == "How we work out your payment"


def test_read_section(client):
    section = client.get("/api/documents/claims_manual/sections/10").json()
    assert section["document"] == "claims_manual"
    assert section["title"] == "Meals without receipts"
    assert "$35 per traveler" in section["text"]


@pytest.mark.parametrize("document", DOCUMENTS)
def test_sections_match_the_documents(client, document):
    text = (DATA / DOCUMENTS[document]).read_text(encoding="utf-8")
    for entry in client.get(f"/api/documents/{document}/sections").json():
        number = entry["section"]
        section = client.get(f"/api/documents/{document}/sections/{number}").json()
        start = text.index(f"## {number}. {section['title']}\n")
        end = text.find("\n## ", start)
        body = text[start:] if end == -1 else text[start:end]
        assert body.partition("\n")[2].strip() == section["text"]


@pytest.mark.parametrize(
    "path",
    [
        "/api/documents/handbook/sections",
        "/api/documents/handbook/sections/1",
        "/api/documents/claims_manual/sections/99",
    ],
)
def test_unknown_documents_and_sections(client, path):
    assert client.get(path).status_code == 404


def test_instructions_for_the_queue_and_a_claim(client):
    instructions = client.get("/api/instructions").json()
    assert instructions["queue"].startswith("# UnderCover Agent: running the queue")
    assert instructions["claim"].startswith("# UnderCover Agent: working a claim")
    assert "read_section" in instructions["claim"]
    for text in instructions.values():
        assert "# UnderCover Travel Insurance: Policy Wording" not in text
