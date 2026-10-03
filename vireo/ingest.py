"""C1: read the source CSVs with a real CSV parser, every column as a string."""
from __future__ import annotations

from pathlib import Path

import pandas as pd

EXPECTED_COLUMNS = {
    "tickets": [
        "ticket_id", "created_at", "first_response_at", "resolved_at", "status", "channel",
        "customer_id", "order_id", "product_sku", "category", "priority", "assigned_team",
        "agent_id", "transfers", "csat_score", "refund_amount_inr", "refund_reason_code",
        "replacement_issued", "customer_message", "agent_notes", "source_system",
    ],
    "agents": ["agent_id", "name", "site", "team", "shift", "tier", "from_date", "to_date"],
    "customers": ["customer_id", "name", "city", "state", "signup_date", "care_plus"],
    "orders": ["order_id", "customer_id", "sku", "order_date", "channel", "qty",
               "order_value_inr", "lot_code"],
    "products": ["sku", "product_name", "family", "launch_date", "unit_cost_inr",
                 "retail_price_inr", "warranty_months"],
}


def read_raw(raw_dir: Path) -> dict[str, pd.DataFrame]:
    """Return {table: DataFrame}. Blank cells stay as '' (no implicit NaN conversion)."""
    frames = {}
    for name, cols in EXPECTED_COLUMNS.items():
        df = pd.read_csv(Path(raw_dir) / f"{name}.csv", dtype=str, keep_default_na=False,
                         encoding="utf-8")
        if list(df.columns) != cols:
            raise ValueError(f"{name}.csv columns changed: {list(df.columns)}")
        frames[name] = df
    return frames
