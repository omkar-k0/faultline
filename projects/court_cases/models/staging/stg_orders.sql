select
    order_id,
    case_id,
    hearing_id,
    order_type,
    cast(order_date as date) as order_date,
    order_outcome
from {{ ref('raw_orders') }}
