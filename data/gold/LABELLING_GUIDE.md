# Gold-set labelling guide (PRD §13)

Label every row of `gold_tickets.csv` **from the text only**. Do not look at model output, the cache, or the
bot category. Fill:

- `gold_theme`: exactly one value from the taxonomy below
- `gold_customer_claims_prior_contact`: `true` or `false`
- `labeller`: your name or initials

Once `python -m vireo evaluate` runs, the file is locked (SHA-256 in `gold_lock.json`) and must not change.

```
Order & Delivery:
  - DELIVERY_DELAY: not delivered, tracking stuck, out for delivery for days, marked delivered but not received
  - TRANSIT_DAMAGE_WRONG_ITEM: arrived damaged, dent or crack out of the box, wrong item, colour or variant
  - ADDRESS_CHANGE: change delivery address, wrong pincode, typo in address
  - CANCELLATION: cancel order, ordered by mistake, stop the shipment
Returns & Refunds:
  - RETURN_PICKUP: return pickup missed or not done, packed box still waiting
  - REFUND_NOT_RECEIVED: refund promised but not credited, return accepted but no money, refund status chasing
Payments:
  - PAYMENT_FAILED_DUPLICATE: money debited but no order, UPI success but no order, charged twice
  - DISCOUNT_COUPON: coupon invalid, discount not applied, offer vanished at payment
  - INVOICE_GST: GST invoice request, invoice not downloading, tax bill
Account & App:
  - LOGIN_OTP: OTP not received, locked out, cannot log in
  - APP_CRASH: Vireo app crashes, will not open, white or loading screen
  - FIRMWARE_UPDATE: firmware update stuck or failed, including 'update failed and now it won't turn on'
Connectivity:
  - PAIRING: will not pair, not discoverable, vanishes from the device list
  - BT_DISCONNECT: connection drops, audio stutters or cuts out, call disconnects
  - WIFI_SETUP: speaker Wi-Fi or network setup failing
Power:
  - BATTERY_DRAIN: battery drains fast, poor battery backup
  - CHARGING_FAILURE: earbud or case not charging, no charging LED, charging case dead
  - DEAD_NO_POWER: device will not power on and no update cause is stated
Audio:
  - AUDIO_DISTORTION: crackling, static, hiss, buzzing, distorted sound
  - ONE_SIDE_AUDIO: one earbud or one side silent
  - MIC: mic not working, people cannot hear me on calls
Wearable hardware:
  - DISPLAY_TOUCH: watch touch unresponsive, display problem, cracked screen on wearable use
  - STRAP: strap torn, peeling, strap pin came off
Warranty:
  - WARRANTY_REPAIR_STATUS: warranty claim, RMA or repair status chasing, service centre silence
Pre-sales:
  - PRESALES: compatibility, water resistance and other pre-purchase questions
Fallback:
  - OTHER_UNCLEAR: no identifiable issue in the customer message and agent note combined

Labelling rules:
  1. Label the issue the customer needs resolved, not the action the agent took.
  2. When a stated cause exists, prefer it over the symptom ('update failed, now won't turn on' -> FIRMWARE_UPDATE).
  3. Chasing the status of a refund -> REFUND_NOT_RECEIVED. Chasing the status of a warranty repair -> WARRANTY_REPAIR_STATUS.
  4. With several issues, label the first one the customer states.
  5. Use OTHER_UNCLEAR only when no issue is identifiable from the customer message and agent note combined.
  6. customer_claims_prior_contact is true only if the customer says they already contacted Vireo about this issue before (e.g. 'third time now', 'was told it was resolved', 'still not fixed after your last resolution'). Having tried fixes themselves, or chasing a promised refund/delivery date, is not by itself prior contact.
```
