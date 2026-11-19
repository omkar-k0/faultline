select
    payment_id,
    filing_id,
    paid_at_local,
    cast(paid_at_local as date) as paid_on,
    amount_inr,
    payment_method
from {{ ref('raw_fee_payments') }}
