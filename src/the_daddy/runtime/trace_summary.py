import logging

logger = logging.getLogger(__name__)

class TraceSummary:
    @staticmethod
    def trace_operation(operation_name):
        logger.info(f'Tracing operation: {operation_name}')

    @staticmethod
    def trace_result(result):
        logger.info(f'Operation result: {result}')
