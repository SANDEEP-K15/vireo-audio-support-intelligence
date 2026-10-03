"""Complaint taxonomy (PRD §10) — the single source for the prompt, validation, gold labelling and reports."""
from __future__ import annotations

from enum import Enum


class Theme(str, Enum):
    DELIVERY_DELAY = "DELIVERY_DELAY"
    TRANSIT_DAMAGE_WRONG_ITEM = "TRANSIT_DAMAGE_WRONG_ITEM"
    ADDRESS_CHANGE = "ADDRESS_CHANGE"
    CANCELLATION = "CANCELLATION"
    RETURN_PICKUP = "RETURN_PICKUP"
    REFUND_NOT_RECEIVED = "REFUND_NOT_RECEIVED"
    PAYMENT_FAILED_DUPLICATE = "PAYMENT_FAILED_DUPLICATE"
    DISCOUNT_COUPON = "DISCOUNT_COUPON"
    INVOICE_GST = "INVOICE_GST"
    LOGIN_OTP = "LOGIN_OTP"
    APP_CRASH = "APP_CRASH"
    FIRMWARE_UPDATE = "FIRMWARE_UPDATE"
    PAIRING = "PAIRING"
    BT_DISCONNECT = "BT_DISCONNECT"
    WIFI_SETUP = "WIFI_SETUP"
    BATTERY_DRAIN = "BATTERY_DRAIN"
    CHARGING_FAILURE = "CHARGING_FAILURE"
    DEAD_NO_POWER = "DEAD_NO_POWER"
    AUDIO_DISTORTION = "AUDIO_DISTORTION"
    ONE_SIDE_AUDIO = "ONE_SIDE_AUDIO"
    MIC = "MIC"
    DISPLAY_TOUCH = "DISPLAY_TOUCH"
    STRAP = "STRAP"
    WARRANTY_REPAIR_STATUS = "WARRANTY_REPAIR_STATUS"
    PRESALES = "PRESALES"
    OTHER_UNCLEAR = "OTHER_UNCLEAR"


# theme -> (family, human label, what it covers)
THEMES: dict[Theme, tuple[str, str, str]] = {
    Theme.DELIVERY_DELAY: ("Order & Delivery", "Delivery delay / not received",
                           "not delivered, tracking stuck, out for delivery for days, marked delivered but not received"),
    Theme.TRANSIT_DAMAGE_WRONG_ITEM: ("Order & Delivery", "Transit damage / wrong item",
                                      "arrived damaged, dent or crack out of the box, wrong item, colour or variant"),
    Theme.ADDRESS_CHANGE: ("Order & Delivery", "Address change", "change delivery address, wrong pincode, typo in address"),
    Theme.CANCELLATION: ("Order & Delivery", "Cancellation", "cancel order, ordered by mistake, stop the shipment"),
    Theme.RETURN_PICKUP: ("Returns & Refunds", "Return pickup", "return pickup missed or not done, packed box still waiting"),
    Theme.REFUND_NOT_RECEIVED: ("Returns & Refunds", "Refund not received",
                                "refund promised but not credited, return accepted but no money, refund status chasing"),
    Theme.PAYMENT_FAILED_DUPLICATE: ("Payments", "Payment failed / duplicate",
                                     "money debited but no order, UPI success but no order, charged twice"),
    Theme.DISCOUNT_COUPON: ("Payments", "Discount / coupon", "coupon invalid, discount not applied, offer vanished at payment"),
    Theme.INVOICE_GST: ("Payments", "Invoice / GST", "GST invoice request, invoice not downloading, tax bill"),
    Theme.LOGIN_OTP: ("Account & App", "Login / OTP", "OTP not received, locked out, cannot log in"),
    Theme.APP_CRASH: ("Account & App", "App crash", "Vireo app crashes, will not open, white or loading screen"),
    Theme.FIRMWARE_UPDATE: ("Account & App", "Firmware update",
                            "firmware update stuck or failed, including 'update failed and now it won't turn on'"),
    Theme.PAIRING: ("Connectivity", "Pairing", "will not pair, not discoverable, vanishes from the device list"),
    Theme.BT_DISCONNECT: ("Connectivity", "Bluetooth disconnects", "connection drops, audio stutters or cuts out, call disconnects"),
    Theme.WIFI_SETUP: ("Connectivity", "Wi-Fi setup", "speaker Wi-Fi or network setup failing"),
    Theme.BATTERY_DRAIN: ("Power", "Battery drain", "battery drains fast, poor battery backup"),
    Theme.CHARGING_FAILURE: ("Power", "Charging failure", "earbud or case not charging, no charging LED, charging case dead"),
    Theme.DEAD_NO_POWER: ("Power", "Dead / no power", "device will not power on and no update cause is stated"),
    Theme.AUDIO_DISTORTION: ("Audio", "Audio distortion", "crackling, static, hiss, buzzing, distorted sound"),
    Theme.ONE_SIDE_AUDIO: ("Audio", "One side no audio", "one earbud or one side silent"),
    Theme.MIC: ("Audio", "Microphone", "mic not working, people cannot hear me on calls"),
    Theme.DISPLAY_TOUCH: ("Wearable hardware", "Display / touch", "watch touch unresponsive, display problem, cracked screen on wearable use"),
    Theme.STRAP: ("Wearable hardware", "Strap", "strap torn, peeling, strap pin came off"),
    Theme.WARRANTY_REPAIR_STATUS: ("Warranty", "Warranty / repair status", "warranty claim, RMA or repair status chasing, service centre silence"),
    Theme.PRESALES: ("Pre-sales", "Pre-sales question", "compatibility, water resistance and other pre-purchase questions"),
    Theme.OTHER_UNCLEAR: ("Fallback", "Other / unclear", "no identifiable issue in the customer message and agent note combined"),
}

FAMILIES: list[str] = list(dict.fromkeys(f for f, _, _ in THEMES.values()))

LABELLING_RULES: list[str] = [
    "Label the issue the customer needs resolved, not the action the agent took.",
    "When a stated cause exists, prefer it over the symptom ('update failed, now won't turn on' -> FIRMWARE_UPDATE).",
    "Chasing the status of a refund -> REFUND_NOT_RECEIVED. Chasing the status of a warranty repair -> WARRANTY_REPAIR_STATUS.",
    "With several issues, label the first one the customer states.",
    "Use OTHER_UNCLEAR only when no issue is identifiable from the customer message and agent note combined.",
]

PRIOR_CONTACT_RULE = (
    "customer_claims_prior_contact is true only if the customer says they already contacted Vireo about this "
    "issue before (e.g. 'third time now', 'was told it was resolved', 'still not fixed after your last resolution'). "
    "Having tried fixes themselves, or chasing a promised refund/delivery date, is not by itself prior contact."
)


def family_of(theme: str) -> str:
    return THEMES[Theme(theme)][0]


def label_of(theme: str) -> str:
    return THEMES[Theme(theme)][1]


def taxonomy_text() -> str:
    """Plain-text taxonomy + rules used verbatim in the prompt and the gold-labelling guide."""
    lines = []
    for fam in FAMILIES:
        lines.append(f"{fam}:")
        for th, (f, _, covers) in THEMES.items():
            if f == fam:
                lines.append(f"  - {th.value}: {covers}")
    lines.append("")
    lines.append("Labelling rules:")
    lines.extend(f"  {i}. {r}" for i, r in enumerate(LABELLING_RULES, 1))
    lines.append(f"  {len(LABELLING_RULES) + 1}. {PRIOR_CONTACT_RULE}")
    return "\n".join(lines)
