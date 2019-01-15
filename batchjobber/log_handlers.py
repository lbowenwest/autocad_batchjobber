import logging
import logging.handlers
import logging.config
import multiprocessing as mp
from typing import Dict


class LogDispatcher:
    """
    Logging process wrapper class which handles starting and stopping the dispatcher
    """
    def __init__(self, log_queue: mp.Queue, window_queue: mp.Queue, start: bool = True):
        self.stop_event = mp.Event()
        self.log_queue = log_queue
        self.window_queue = window_queue
        self.log_process = mp.Process(
            target=log_listener,
            args=(self.log_queue, self.stop_event, generate_listener_config(self.window_queue))
        )
        if start:
            self.start()

    def start(self):
        logging.debug("Starting logging process...")
        self.log_process.start()

    def stop(self):
        logging.debug("Stopping logging process...")
        self.stop_event.set()
        self.log_process.join()


def log_listener(q, stop_event, config):
    """
    Process which listens to the log queue and handles records.
    Waits for main process to signal completion via the event. 
    The listener is then stopped and the process exits.
    """
    logging.config.dictConfig(config)
    listener = logging.handlers.QueueListener(q, SimpleLogHandler())
    listener.start()
    stop_event.wait()
    listener.stop()


class SimpleLogHandler:
    """
    A simple handler for logging events. It runs in the listener process 
    and dispatches events to loggers based on the name in the received record
    """
    def handle(self, record):
        logger = logging.getLogger(record.name)
        logger.handle(record)


class LogWindowHandler(logging.Handler):
    """
    Logging handler for the log window class. On receiving a record, 
    formats the record and adds the string msg to the queue for the window 
    to handle
    """
    def __init__(self, queue):
        super(LogWindowHandler, self).__init__()
        self.queue = queue

    def emit(self, record):
        msg = self.format(record)
        self.queue.put(msg)


def generate_worker_config(q: mp.Queue, level: str = 'DEBUG') -> Dict:
    """
    Generates logging config for worker processes (builder and processor)

    :param q: queue to use for logging
    :param level: logging level (default DEBUG)
    :return: config to be passed to logging.config.dictConfig
    """
    log_config = {
        'version': 1,
        'handlers': {
            'queue': {
                'class': 'logging.handlers.QueueHandler',
                'queue': q,
            },
        },
        'root': {
            'level': level,
            'handlers': ['queue'],
        },
    }
    return log_config


def generate_listener_config(q: mp.Queue) -> Dict:
    """
    Generates logging config for the dispatcher process

    :param q: console window queue
    :return: config dict
    """
    log_config = {
        'version': 1,
        'formatters': {
            'simple': {
                'class': 'logging.Formatter',
                'format': '%(levelname)-8s %(message)s'
            },
            'window': {
                'class': 'logging.Formatter',
                'format': '%(levelname)-8s %(message)s\n'
            },
        },
        'handlers': {
            'console': {
                'class': 'logging.StreamHandler',
                'level': 'DEBUG',
                'formatter': 'simple',
            },
            'window': {
                'class': 'batchjobber.log_handlers.LogWindowHandler',
                'level': 'INFO',
                'queue': q,
                'formatter': 'window'
            }
        },
        'root': {
            'level': 'DEBUG',
            'handlers': ['console', 'window']
        }
    }
    return log_config
