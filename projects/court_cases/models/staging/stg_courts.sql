select
    court_id,
    court_name,
    state,
    court_level,
    utc_offset_minutes
from {{ ref('raw_courts') }}
