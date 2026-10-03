"""Shared fixtures. No test touches the network: the Anthropic client is always a fake."""
from __future__ import annotations

import json
from types import SimpleNamespace

import pandas as pd
import pytest

from vireo import load_config
from vireo.metrics import add_derived


REAL_DATA = (load_config()["paths"]["raw_dir"] / "tickets.csv").exists()


def pytest_configure(config):
    config.addinivalue_line("markers", "real_data: needs the (unpublished) assignment files in data/raw/")


def pytest_collection_modifyitems(config, items):
    """The assignment dataset is not in the public repository; tests that read it skip when it is absent."""
    if REAL_DATA:
        return
    skip = pytest.mark.skip(reason="assignment data not present in data/raw/ (not published; see README 'Data')")
    for item in items:
        if "real_data" in item.keywords:
            item.add_marker(skip)


@pytest.fixture(scope="session")
def cfg():
    return load_config()


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """Any attempt to open a network connection fails the test (A12: suite passes without network)."""
    import socket

    def guard(*args, **kwargs):
        raise RuntimeError("network access attempted during tests")
    monkeypatch.setattr(socket.socket, "connect", guard)
    monkeypatch.setattr(socket, "create_connection", guard)


def make_tickets(rows: list[dict], policy: dict) -> pd.DataFrame:
    """Clean-form tickets (as produced by clean.run_clean) from minimal dicts."""
    base = {"status": "resolved", "channel": "chat", "customer_id": "C1", "product_sku": "SKU1",
            "first_response_at": None, "resolved_at": None, "source_system": "helpdesk", "transfers": 0,
            "csat": None, "agent_id": "A1", "agent_team": "Chat Frontline", "assigned_team": "Chat Frontline",
            "category": "Connectivity", "customer_message": "msg", "agent_notes": "note"}
    df = pd.DataFrame([{**base, **r} for r in rows])
    for c in ("created_at", "first_response_at", "resolved_at"):
        df[c] = pd.to_datetime(df[c])
    df["first_response_at"] = df.first_response_at.fillna(df.created_at + pd.Timedelta(minutes=1))
    df["attended"] = df.status.isin(["resolved", "closed"])
    df["is_legacy"] = df.source_system == "legacy_fd"
    df["transfers"] = df.transfers.astype("Int64")
    df["csat"] = pd.to_numeric(df.csat).astype("Float64")
    return add_derived(df, policy)


class FakeClient:
    """Mimics client.messages.create. `replies` is a list of JSON strings (or callables) returned in order."""

    def __init__(self, replies=None, default=None, in_tokens=500, out_tokens=20):
        self.replies = list(replies or [])
        self.default = default or json.dumps({"theme": "PAIRING", "customer_claims_prior_contact": False})
        self.calls = []
        self.in_tokens, self.out_tokens = in_tokens, out_tokens
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        text = self.replies.pop(0) if self.replies else self.default
        if callable(text):
            text = text(kwargs)
        return SimpleNamespace(content=[SimpleNamespace(type="text", text=text)], stop_reason="end_turn",
                               usage=SimpleNamespace(input_tokens=self.in_tokens, output_tokens=self.out_tokens))
