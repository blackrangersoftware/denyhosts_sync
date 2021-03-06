import logging
import inspect
import os
import os.path

from denyhosts_server import config
from denyhosts_server import models
from denyhosts_server import main
from denyhosts_server import database

from twisted.trial import unittest
from twisted.enterprise import adbapi
from twisted.internet.defer import inlineCallbacks, returnValue

from twistar.registry import Registry

class TestBase(unittest.TestCase):
    @inlineCallbacks
    def setUp(self, config_basename="test.conf"):
        configfile = os.path.join(
            os.path.dirname(inspect.getsourcefile(TestBase)),
            config_basename
        )

        config.read_config(configfile)

        Registry.DBPOOL = adbapi.ConnectionPool(config.dbtype, **config.dbparams)
        Registry.register(models.Cracker, models.Report, models.Legacy)

        yield database.clean_database(quiet=True)
        main.configure_logging()
