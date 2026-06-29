"""Platform-coupled paths, tested against REAL FortiSOAR API responses captured
from fsr130 (tests/fixtures/*.json) and replayed via the fsr_api fixture.

Covers the logic that can't run off-box without an appliance: get_users/
get_teams/get_email_templates, Team & people-IRI recipient resolution, and
Email Template body expansion."""
from smtp import operations
from tests.conftest import load_fixture

EMAIL = "@"


def test_get_users_formats_from_real_people(fsr_api):
    people = load_fixture("people.json")["hydra:member"]
    expected = {p["email"] for p in people if p.get("email")}
    out = operations.get_users({}, {})
    assert len(out) == len(people)
    # every returned string ends with the person's email
    assert all(any(s.endswith(e) for e in expected) for s in out)


def test_get_users_uses_fixture(fsr_api):
    out = operations.get_users({}, {})
    assert any("admin@example.com" in s for s in out)


def test_get_teams_returns_names(fsr_api):
    names = operations.get_teams({}, {})
    fixture_names = [t["name"] for t in load_fixture("teams_rel.json")["hydra:member"]]
    assert names == fixture_names
    assert "SOC Team" in names


def test_get_email_templates_returns_names(fsr_api):
    names = operations.get_email_templates({}, {})
    assert names == [t["name"] for t in load_fixture("email_templates.json")["hydra:member"]]


def test_team_recipient_resolution_expands_to_member_emails(fsr_api, smtp_server, smtp_config):
    _, sink = smtp_server
    # actors in teams_rel.json are expanded dicts carrying emails
    members = load_fixture("teams_rel.json")["hydra:member"]
    soc = next(t for t in members if t["name"] == "SOC Team")
    expected = sorted({a["email"] for a in soc["actors"] if isinstance(a, dict) and a.get("email")})

    result = operations.send_email_new(smtp_config, {
        "type": "Team", "to": ["SOC Team"], "subject": "team", "content": "x",
        "body_type": "Plain Text"})

    assert sorted(result["recipients"]["to"]) == expected
    assert expected and EMAIL in expected[0]
    assert sorted(sink.messages[0].rcpt_tos) == expected


def test_manual_people_iri_resolves_to_email(fsr_api, smtp_server, smtp_config):
    person = load_fixture("query_people.json")["hydra:member"][0]
    iri = person["@id"]
    result = operations.send_email_new(smtp_config, {
        "type": "Manual Input", "to": iri, "subject": "iri", "content": "x",
        "body_type": "Plain Text"})
    assert result["recipients"]["to"] == [person["email"]]


def test_email_template_body_is_applied(fsr_api, smtp_server, smtp_config):
    tpl = load_fixture("query_email_templates.json")["hydra:member"][0]
    result = operations.send_email_new(smtp_config, {
        "type": "Manual Input", "to": "x@local.test", "body_type": "Email Template",
        "email_templates": tpl["name"]})
    assert result["status"] == "sent"
    # subject came from the template (off-box expand() is identity)
    assert result["subject"] == tpl["subject"]
