select
    party_id,
    party_type,
    party_name,
    state as party_state
from {{ ref('raw_parties') }}
