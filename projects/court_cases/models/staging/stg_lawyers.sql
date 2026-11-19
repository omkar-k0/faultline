select
    lawyer_id,
    bar_number,
    lawyer_name,
    nullif(firm, '') as firm,
    cast(enrolled_on as date) as enrolled_on
from {{ ref('raw_lawyers') }}
