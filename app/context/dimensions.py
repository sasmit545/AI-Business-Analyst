"""Bind application filters to members of the authorized payment dataset."""
from app.context.banks import resolve_bank_id


class DimensionLookupError(ValueError):
    pass


def resolve_member(value, directory, dimension):
    if value in directory:
        return value
    key = value.strip().casefold()
    matches = sorted(code for code, name in directory.items()
                     if key and key in (code.casefold(), name.casefold()))
    if len(matches) == 1:
        return matches[0]
    if matches:
        raise DimensionLookupError(f'More than one {dimension} matches. Enter an exact ID. '
                                   f'Matching IDs include {", ".join(matches[:6])}.')
    raise DimensionLookupError(f'No {dimension} matches that filter in the selected dataset. '
                               f'Which {dimension} name or ID should I use?')


def bind_filters(filters, authorization):
    """Leave malformed fields to the ordinary request validator."""
    bound = dict(filters)
    for field in ('payer_bank_id', 'payment_method', 'merchant_id'):
        value = filters.get(field)
        if not isinstance(value, str) or len(value) > 64:
            continue
        if field == 'payer_bank_id':
            bound[field] = resolve_bank_id(value, authorization.banks)
        elif field == 'payment_method':
            bound[field] = resolve_member(value, authorization.methods, 'payment method')
        else:
            bound[field] = authorization.resolve_merchant(value)
    return bound
