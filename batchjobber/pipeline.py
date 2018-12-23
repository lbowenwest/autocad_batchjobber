import multiprocessing as mp
import re
import subprocess as sp
import logging
import logging.handlers
from functools import partial
from os import path

from .utility import autocad_console


class DrawingProcessor(object):
    """
    Class to filter drawing files based on certain checks
    to prevent broken drawings being passed to the builder
    """

    def __init__(self, fail_queue=None, log_queue=None):
        self.logger = logging.getLogger()
        self.log_queue = log_queue

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
            Builder(self.build_queue, drawing_dir, log_queue=self.log_queue)
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
        self.logger.debug(f"Starting checks...")

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
                log_queue=self.log_queue
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
        self.logger.info("Build process done!")

        if self.build_callback:
            self.build_callback()

    @staticmethod
    def check_drawing(drawing, drawing_dir, pass_queue, fail_queue, log_queue):
        qh = logging.handlers.QueueHandler(log_queue)
        logger = logging.getLogger('filter')
        logger.setLevel(logging.DEBUG)
        logger.addHandler(qh)
        logger.debug(f"Checking {drawing}")
        script_dir = path.join(path.abspath(path.curdir), "scripts")
        cmd = [
            autocad_console(log=False),
            "/i", path.join(path.abspath(drawing_dir), drawing),
            "/s", path.join(script_dir, "test_xrefs.scr")
        ]
        out = sp.check_output(cmd, shell=True, stderr=sp.DEVNULL)
        result = out.replace(b'\x00', b'').replace(b'\x08', b'').decode('ascii')
        match = re.match(r".+Total Xref\(s\): (\d+)", re.sub(r"[\r\n]", "", result))
        if not match:
            return False
        if int(match.group(1)) == 0:
            logger.info(f"{drawing} passed drawing check")
            pass_queue.put(drawing)
        else:
            logger.warning(f"{drawing} failed drawing check")
            fail_queue.put(drawing)
        return True


class Builder(mp.Process):
    def __init__(self, queue: mp.JoinableQueue, drawing_dir, publish=True, log_queue=None):
        super(Builder, self).__init__()
        self.queue = queue
        self.log_queue = log_queue
        self.drawing_dir = path.abspath(drawing_dir)
        self.autocad_cmd = autocad_console(log=False)
        self.script_dir = path.join(path.abspath(path.curdir), "scripts")
        if publish:
            self.script = path.join(self.script_dir, "zipship_publish.scr")
        else:
            self.script = path.join(self.script_dir, "zipship.scr")

    def run(self):
        logger = logging.getLogger('builder')
        logger.setLevel(logging.DEBUG)
        qh = logging.handlers.QueueHandler(self.log_queue)
        logger.addHandler(qh)
        while True:
            drawing = self.queue.get()
            if drawing is None:
                self.queue.task_done()
                break
            logger.debug(f"Building {drawing}...")
            self.build_drawing(drawing)
            logger.info(f"Built - {drawing}")
            self.queue.task_done()
        return

    def build_drawing(self, drawing):
        cmd = [
            self.autocad_cmd,
            "/i", path.join(self.drawing_dir, drawing),
            "/s", path.join(self.script_dir, self.script)]
        out_code = sp.check_call(cmd, shell=True, stdout=sp.DEVNULL, stderr=sp.DEVNULL)
        return out_code
