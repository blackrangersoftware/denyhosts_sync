#!/usr/bin/env python

# denyhosts sync server
# Copyright (C) 2015 Jan-Pascal van Best <janpascal@vanbest.org>

# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published
# by the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.

# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.


import datetime
import socket
import time
import logging

from twisted.internet import reactor, threads
from twisted.internet.defer import inlineCallbacks, returnValue

from jinja2 import Template, Environment, PackageLoader

import GeoIP

import pygal
from pygal.style import CleanStyle

import models
import database

def format_datetime(value, format='medium'):
    dt = datetime.datetime.fromtimestamp(value)
    if format == 'full':
        format="EEEE, d. MMMM y 'at' HH:mm:ss"
    elif format == 'medium':
        format="%a %d-%m-%Y %H:%M:%S"
    return dt.strftime(format)

# Functions containing blocking io, call from thread!
def fixup_crackers(hosts):
    gi = GeoIP.new(GeoIP.GEOIP_MEMORY_CACHE)
    for host in hosts:
        try:
            host.country = gi.country_name_by_addr(host.ip_address)
        except Exception, e:
            logging.debug("Exception looking up country for {}: {}".format(host.ip_address, e))
            host.country = ''
        try:
            hostinfo = socket.gethostbyaddr(host.ip_address)
            host.hostname = hostinfo[0]
            #host.hostname = 'disabled'
        except Exception, e:
            logging.debug("Exception looking up reverse DNS for {}: {}".format(host.ip_address, e))
            host.hostname = host.ip_address

@inlineCallbacks
def create_stats_page(stop_reactor = False):
    logging.info("Updating static statistics page...")
    now = time.time()
    stats = {}
    stats["last_updated"] = now
    try:
        #rows = yield database.run_query("SELECT num_hosts,num_reports, num_clients, new_hosts FROM stats ORDER BY time DESC LIMIT 1")
        stats["num_hosts"] = yield models.Cracker.count()
        stats["num_reports"] = yield models.Report.count()

        rows = yield database.run_query("SELECT count(*) FROM reports GROUP BY ip_address") 
        if len(rows)>0:
            stats["num_clients"] = rows[0][0]
        else:
            stats["num_clients"] = 0

        yesterday = now - 24*3600
        stats["daily_reports"] = yield models.Report.count(where=["first_report_time>?", yesterday])
        stats["daily_new_hosts"] = yield models.Cracker.count(where=["first_time>?", yesterday])

        recent_hosts = yield models.Cracker.find(orderby="latest_time DESC", limit=10)
        yield threads.deferToThread(fixup_crackers, recent_hosts)
        stats["recent_hosts"] = recent_hosts

        most_reported_hosts = yield models.Cracker.find(orderby="total_reports DESC", limit=10)
        yield threads.deferToThread(fixup_crackers, most_reported_hosts)
        stats["most_reported_hosts"] = most_reported_hosts

        # Calculate start of daily period: yesterday on the beginning of the
        # current hour
        dt_now = datetime.datetime.fromtimestamp(now)
        start_hour = dt_now.hour
        dt_onthehour = dt_now.replace(minute=0, second=0, microsecond=0)
        dt_start = dt_onthehour - datetime.timedelta(days=1)
        yesterday = int(dt_start.strftime('%s'))

        # FIXME: because of the SQL queries used, hours without any reports will 
        # be omitted from the resulting graph
        rows = yield database.run_query("""
            SELECT CAST((first_report_time-?)/3600 AS UNSIGNED INTEGER), count(*)
            FROM reports
            WHERE first_report_time > ?
            GROUP BY CAST((first_report_time-?)/3600 AS UNSIGNED INTEGER)
            """, yesterday, yesterday, yesterday)
        hourly_chart = pygal.Line(show_legend = False, style=CleanStyle)
        hourly_chart.title = 'Number of reports per hour (until {})'.format( datetime.datetime.fromtimestamp(now).strftime("%d-%m-%Y %H:%M:%S"))
        hourly_chart.x_labels = [ str((start_hour + row[0]) % 24) for row in rows ]
        hourly_chart.add('# of reports', [ row[1] for row in rows ])

        hourly_chart.render_to_file(filename='hourly.svg') 
        hourly_chart.render_to_png(filename='hourly.png') 

        # Calculate start of monthly period: last month on the beginning of the
        # current day
        dt_now = datetime.datetime.fromtimestamp(now)
        start_hour = dt_now.hour
        start_day =  dt_now.day
        dt_ontheday = dt_now.replace(hour=0, minute=0, second=0, microsecond=0)
        dt_start = dt_onthehour - datetime.timedelta(weeks=4)
        yestermonth = int(dt_start.strftime('%s'))

        # FIXME: also days without reports will be omitted
        rows = yield database.run_query("""
            SELECT CAST((first_report_time-?)/24/3600 AS UNSIGNED INTEGER), count(*)
            FROM reports
            WHERE first_report_time > ?
            GROUP BY CAST((first_report_time-?)/24/3600 AS UNSIGNED INTEGER)
            """, yestermonth, yestermonth, yestermonth)
        daily_chart = pygal.Line(show_legend = False, style=CleanStyle)
        daily_chart.title = 'Number of reports per day (until {})'.format( datetime.datetime.fromtimestamp(now).strftime("%d-%m-%Y %H:%M:%S"))
        daily_chart.x_labels = [ str((dt_start +
        datetime.timedelta(days=row[0])).day) for row in rows ]
        daily_chart.add('# of reports', [ row[1] for row in rows ])

        daily_chart.render_to_file(filename='monthly.svg') 
        daily_chart.render_to_png(filename='monthly.png') 

        env = Environment(loader=PackageLoader('dh_syncserver', 'templates'))
        env.filters['datetime'] = format_datetime
        template = env.get_template('stats.html')
        html = template.render(stats)

        with open('stats.html', 'w') as f:
            f.write(html)
    except Exception, e:
        logging.warning("Error creating statistics page: {}".format(e))

    if stop_reactor:
        reactor.stop()
    logging.info("Done updating static statistics page...")

# vim: tabstop=8 expandtab shiftwidth=4 softtabstop=4
