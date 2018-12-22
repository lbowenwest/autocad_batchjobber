import multiprocessing as mp
import random
import re
import subprocess as sp
import time
from functools import partial
from os import path

from .utility import autocad_console
from .log_handlers import install_mp_handler


class DrawingFilter(object):
    """
    Class to filter drawing files based on certain checks
    to prevent broken drawings being passed to the builder
    """

    def __init__(self, fail_queue=None, logger=None):
        self.logger = logger

        install_mp_handler(self.logger)
        self.pool = mp.Pool()
        self.manager = mp.Manager()

        self.fail_queue = fail_queue or self.manager.Queue()
        self.build_queue = None

        self.num_builders = mp.cpu_count()
        self.builders = []

        self.drawing_dir = ""
        self.filter_callback = None
        self.build_callback = None

    def reset_builders(self, drawing_dir):
        self.build_queue = self.manager.JoinableQueue()
        self.builders = [
            Builder(self.build_queue, drawing_dir, logger=self.logger)
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

    def process(self, drawings, drawing_dir, filter_callback=None, build_callback=None):
        if self.logger:
            self.logger.debug(f"Processing drawings...")

        self.drawing_dir = drawing_dir
        self.filter_callback = filter_callback
        self.build_callback = build_callback

        self.reset_builders(drawing_dir)

        self.pool.map_async(
            partial(
                self.check_drawing,
                drawing_dir=drawing_dir,
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
    def check_drawing(drawing, drawing_dir, pass_queue, fail_queue, logger=None):
        if logger:
            logger.debug(f"Checking {drawing}")
        # time.sleep(random.random())
        script_dir = path.abspath(path.join(path.abspath(path.curdir), "..", "scripts"))
        cmd = [
            autocad_console(),
            "/i", path.join(path.abspath(drawing_dir), drawing),
            "/s", path.join(script_dir, "test_xrefs.scr")
        ]
        out = sp.check_output(cmd, shell=Trues, stderr=sp.DEVNULL)
        result = out.replace(b'\x00', b'').replace(b'\x08', b'').decode('ascii')
        match = re.match(r".+Total Xref\(s\): (\d+)", re.sub(r"[\r\n]", "", result))
        if not match:
            return False
        if int(match.group(1)) == 0:
            if logger:
                logger.info(f"{drawing} passed drawing check")
            pass_queue.put(drawing)
        else:
            if logger:
                logger.warning(f"{drawing} failed drawing check")
            fail_queue.put(drawing)
        return True


class Builder(mp.Process):
    def __init__(self, queue: mp.JoinableQueue, drawing_dir, logger=None):
        super(Builder, self).__init__()
        self.queue = queue
        self.logger = logger
        self.drawing_dir = path.abspath(drawing_dir)
        self.autocad_cmd = autocad_console(log=False)
        self.script_dir = path.abspath(path.join(path.abspath(path.curdir), "..", "scripts"))
        self.script = path.join(self.script_dir, "zipship.scr")

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
        cmd = [self.autocad_cmd, "/i", path.join(self.drawing_dir, drawing), "/s", self.script]
        self.logger.debug(f"Command: {' '.join(cmd)}")
        # print(f"Command: {' '.join(cmd)}")
        sp.check_call(cmd, shell=True, stdout=sp.DEVNULL, stderr=sp.DEVNULL)
        if self.logger:
            self.logger.info(f"Built - {drawing}")
