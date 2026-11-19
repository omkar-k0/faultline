select
    judge_id,
    court_id,
    judge_name,
    cast(appointed_on as date) as appointed_on
from {{ ref('raw_judges') }}
