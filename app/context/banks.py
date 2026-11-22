"""Bank filter matching against the selected dataset's bank dimension."""
import re


class BankLookupError(ValueError):
    pass


def bank_key(value: str) -> str:
    return re.sub(r'[\s_-]+', ' ', value.casefold()).strip()


def matching_bank_ids(value, banks):
    if value in banks:
        return [value]
    key = bank_key(value)
    return sorted(bank_id for bank_id, name in banks.items()
                  if key and key in (bank_key(bank_id), bank_key(name)))


def resolve_bank_id(value, banks):
    if value is None:
        return None
    matches = matching_bank_ids(value, banks)
    if len(matches) == 1:
        return matches[0]
    if matches:
        examples = ', '.join(matches[:6])
        raise BankLookupError(f'More than one bank matches. Enter the exact bank ID. Matching IDs include {examples}.')
    raise BankLookupError('No bank matches that filter in the selected dataset. Which bank name or ID should I use?')
