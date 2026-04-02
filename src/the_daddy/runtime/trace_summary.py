def log_trace_summary(details):
    """
    Log detailed execution trace summary to enhance runtime observability.

    :param details: Execution details to log.
    """
    # Adding detailed logs for better observability.
    with open('trace_summary.log', 'a') as f:
        f.write(f'{details}\n')
