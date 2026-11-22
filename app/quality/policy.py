def blocked(records):
    return any(record.status == 'BLOCK' for record in records)
