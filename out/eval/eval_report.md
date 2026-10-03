# Classifier evaluation report

Gold set: 120 human-labelled tickets (locked by SHA-256). Prompt `v1`.
Thresholds: accuracy >= 85%, every family >= 70%.
Provider: `gemini`. Selected model: **gemini-3.5-flash-lite** (cheapest-first ladder).

## gemini-3.5-flash-lite — PASS

- accuracy 98.3%, macro-F1 0.984, AI errors 0
- cost per ticket $0.00036; evaluation cost $0.0429
- prior-contact flag: precision 0.917, recall 1.0 (gold positives 11)

| Family | n | Accuracy |
|---|---|---|
| Order & Delivery | 22 | 100.0% |
| Returns & Refunds | 10 | 100.0% |
| Payments | 16 | 100.0% |
| Account & App | 14 | 100.0% |
| Connectivity | 14 | 100.0% |
| Power | 15 | 93.3% |
| Audio | 14 | 92.9% |
| Wearable hardware | 7 | 100.0% |
| Warranty | 4 | 100.0% |
| Pre-sales | 4 | 100.0% |

| Theme | F1 |
|---|---|
| ADDRESS_CHANGE | 1.000 |
| APP_CRASH | 1.000 |
| AUDIO_DISTORTION | 1.000 |
| BATTERY_DRAIN | 1.000 |
| BT_DISCONNECT | 1.000 |
| CANCELLATION | 1.000 |
| CHARGING_FAILURE | 0.923 |
| DEAD_NO_POWER | 1.000 |
| DELIVERY_DELAY | 1.000 |
| DISCOUNT_COUPON | 1.000 |
| DISPLAY_TOUCH | 1.000 |
| FIRMWARE_UPDATE | 1.000 |
| INVOICE_GST | 1.000 |
| LOGIN_OTP | 1.000 |
| MIC | 1.000 |
| ONE_SIDE_AUDIO | 0.800 |
| PAIRING | 1.000 |
| PAYMENT_FAILED_DUPLICATE | 1.000 |
| PRESALES | 1.000 |
| REFUND_NOT_RECEIVED | 1.000 |
| RETURN_PICKUP | 1.000 |
| STRAP | 1.000 |
| TRANSIT_DAMAGE_WRONG_ITEM | 1.000 |
| WARRANTY_REPAIR_STATUS | 0.889 |
| WIFI_SETUP | 1.000 |

Most frequent confusions (gold → predicted):

- ONE_SIDE_AUDIO → WARRANTY_REPAIR_STATUS: 1
- CHARGING_FAILURE → ONE_SIDE_AUDIO: 1
