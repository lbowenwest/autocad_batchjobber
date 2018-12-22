import multiprocessing as mp
import random
import re
import subprocess as sp
import time
from functools import partial
from os import path


class DrawingFilter(object):
    """
    Class to filter drawing files based on certain checks
    to prevent broken drawings being passed to the builder
    """

    def __init__(self, fail_queue=None, logger=None):
        self.logger = logger

        self.pool = mp.Pool()
        self.manager = mp.Manager()

        self.fail_queue = fail_queue or self.manager.Queue()
        self.build_queue = None

        self.num_builders = mp.cpu_count()
        self.builders = []

        self.filter_callback = None
        self.build_callback = None

    def reset_builders(self):
        self.build_queue = self.manager.JoinableQueue()
        self.builders = [
            Builder(self.build_queue, self.logger)
            for _ in range(self.num_builders)
        ]
        for b in self.builders:
            b.start()

    def stop(self):
        self.pool.terminate()
        for b in self.builders:
            b.terminate()

    def set_build_options(self):
        pass

    def process(self, drawings, filter_callback=None, build_callback=None):
        if self.logger:
            self.logger.debug(f"Processing drawings...")

        self.filter_callback = filter_callback
        self.build_callback = build_callback

        self.reset_builders()

        self.pool.map_async(
            partial(
                self.check_drawing,
                pass_queue=self.build_queue,
                fail_queue=self.fail_queue,
                logger=self.logger
            ),
            drawings,
            callback=self.filter_complete
        )

    def filter_complete(self, val):
        self.fail_queue.put(None)
        for _ in range(self.num_builders):
            self.build_queue.put(None)

        if self.filter_callback:
            self.filter_callback()

        self.build_queue.join()
        if self.logger:
            self.logger.info("Build process done!")

        if self.build_callback:
            self.build_callback()

    @staticmethod
    def check_drawing(drawing, pass_queue, fail_queue, logger=None):
        if logger:
            logger.debug(f"Checking {drawing}")
        time.sleep(random.random())
        if re.match(r".?pass", drawing):
            if logger:
                logger.info(f"{drawing} passed drawing check")
            pass_queue.put(drawing)
        else:
            if logger:
                logger.warning(f"{drawing} failed drawing check")
            fail_queue.put(drawing)
        return True


class Builder(mp.Process):
    def __init__(self, queue: mp.JoinableQueue, logger=None):
        super(Builder, self).__init__()
        self.queue = queue
        self.logger = logger

    def run(self):
        while True:
            drawing = self.queue.get()
            if drawing is None:
                self.queue.task_done()
                break
            if self.logger:
                self.logger.debug(f"Building {drawing}...")
            self.build_drawing(drawing)
            self.queue.task_done()
        return

    def build_drawing(self, drawing):
        out = sp.check_output(
            [path.join(path.abspath(path.curdir), "command.sh"), drawing],
            shell=True
        )
        if self.logger:
            self.logger.info(f"Built - {drawing}")