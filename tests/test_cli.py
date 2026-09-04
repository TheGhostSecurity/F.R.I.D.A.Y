import sys

from friday_gateway import cli


def test_ask_dispatches_to_agent(monkeypatch, capsys) -> None:
    class FakeAgent:
        def ask(self, query: str) -> str:
            assert query == "what am I working on?"
            return "You are working on F.R.I.D.A.Y."

    import friday_gateway.agent

    monkeypatch.setattr(friday_gateway.agent, "OllamaAgent", FakeAgent)
    monkeypatch.setattr(sys, "argv", ["friday", "ask", "what am I working on?"])
    cli.main()
    assert capsys.readouterr().out == "You are working on F.R.I.D.A.Y.\n"


def test_pending_dispatches_to_gateway(monkeypatch, capsys) -> None:
    monkeypatch.setattr(cli, "_request", lambda path, method="GET": {"pending": [], "path": path, "method": method})
    monkeypatch.setattr(sys, "argv", ["friday", "pending"])
    cli.main()
    output = capsys.readouterr().out
    assert '"path": "/confirmations"' in output
    assert '"method": "GET"' in output
