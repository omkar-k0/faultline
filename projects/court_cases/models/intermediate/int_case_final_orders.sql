select
    case_id,
    order_id as final_order_id,
    order_date as final_order_date,
    order_outcome as final_outcome
from {{ ref('stg_orders') }}
where order_type = 'final'
