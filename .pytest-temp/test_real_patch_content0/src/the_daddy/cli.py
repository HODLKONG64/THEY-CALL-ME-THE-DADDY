def _safe(value):
    try:
        json.dumps(value)
        return value
    except Exception:
        return str(value)
