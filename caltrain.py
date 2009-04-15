#!/usr/bin/env python2.5
__usage = """
    --from <stop>   the stop you're traveling from
    --to   <stop>   the stop you're traveling to
"""
__doc__ = __usage

from lxml import html
from collections import defaultdict
import re
import sqlite3
import datetime
from datetime import time
from optparse import OptionParser
import sys

WEEKDAY = 'weekday'
WEEKEND = 'weekend'
NORTHBOUND = 'northbound'
SOUTHBOUND = 'southbound'

TABLES_TO_PARSE = [
  (WEEKDAY, NORTHBOUND, 'Weekday Northbound service'),
  (WEEKDAY, SOUTHBOUND, 'Weekday Southbound service'),
  (WEEKEND, NORTHBOUND, 'Weekend and Holiday Northbound service'),
  (WEEKEND, SOUTHBOUND, 'Weekend and Holiday Southbound service')]

def pull_schedule(url="http://www.caltrain.com/timetable.html"):
  root = html.parse(url).getroot()
  
  # dom looks like <h2>table name</h2><table>...</table>
  headings_and_tables = root.cssselect('h2,table')
  tables_by_name = {}
  for e in headings_and_tables:
    if e.tag == 'h2':
      cur_heading = e.text_content()
    else:
      tables_by_name[cur_heading] = e

  results = {}
  for (day_type, direction, t_name) in TABLES_TO_PARSE:
    table = tables_by_name[t_name]
    results[(day_type, direction)] = parse_schedule_table(table)
  return results

def parse_schedule_table(table):
  # make sure we don't have any cells that span columns, since that would
  # be trickier

  assert len(table.cssselect('td[colspan],th[colspan]')) == 0
  trs = table.cssselect('tr')
  header = trs[0]
  del trs[0]
  col_headers = [e.text_content() for e in header.cssselect('td,th')]
  del col_headers[0] # not a train number

  data = []
  
  for tr in trs:
    stop_name = tr.cssselect('th')[0].text_content()
    
    tds = [e.text_content() for e in tr.cssselect('td')]

    prev_hour = 0
    
    for (train_num, time) in zip(col_headers, tds):
      time = time.strip()
      match = re.match(r'(\d+):(\d+)', time)
      if match:
        (hour, minute) = match.groups()
        hour = int(hour) ; minute = int(minute)
        if hour < prev_hour and hour != 12:
          hour += 12
        prev_hour = hour
        data.append( (train_num, stop_name, hour, minute) )
  return data

def save_schedule_to_sql(conn, schedule, table_name="caltrain"):
  c = conn.cursor()
  c.execute("""
  CREATE TABLE %s (
    day_type text,
    direction text,
    train_num text,
    stop text,
    hour integer,
    minute integer
  )""" % table_name)
  
  for ( (day_type, direction), points ) in schedule.iteritems():
    for (train, stop, hour, minute) in points:
      c.execute("""INSERT INTO %s VALUES (?, ?, ?, ?, ?, ?)""" % table_name,
                (day_type, direction, train, stop, hour, minute))

  conn.commit()

def is_weekday(date):
  return date.weekday() < 5

def is_holiday(date):
  return (date.month, date.day) in [
    (1, 1),
    (7, 4),
    (12, 25)]
# TODO add memorial day and thanksgiving

def get_schedule_between(conn, from_stop, to_stop):
  today = datetime.date.today()
  if is_weekday(today) and not is_holiday(today):
    schedule = WEEKDAY
  else:
    schedule = WEEKEND
    
  c = conn.cursor()
  c.execute("""
SELECT c1.hour, c1.minute, c2.hour, c2.minute FROM caltrain AS c1, caltrain AS c2
WHERE c1.day_type=? AND c1.stop=?
   AND c1.train_num = c2.train_num
  AND c2.day_type=c1.day_type
  AND c2.stop=?
  AND ((c2.hour > c1.hour) OR
       (c2.hour = c1.hour AND c2.minute > c1.minute))
  """, (schedule, from_stop, to_stop))


  res = []
  for (leave_h, leave_m, arrive_h, arrive_m) in c:
    res.append((time(leave_h, leave_m),
                time(arrive_h, arrive_m)))
  return res

def get_stops(conn):
  c = conn.cursor()
  c.execute("""
  SELECT DISTINCT(stop) FROM caltrain ORDER BY stop
  """)
  return [s for (s,) in c]

def print_table(rows):
  col_lens = [len(x) for x in rows[0]]
  for row in rows:
    for (idx, col) in enumerate(row):
      if col_lens[idx] < len(col):
        col_lens[idx] = len(col)

  for row in rows:
    for col_len, col in zip(col_lens, row):
      print col.ljust(col_len),
    print
    

def print_schedule(conn, from_stop, to_stop):
  sched = get_schedule_between(conn, from_stop, to_stop)

  table = [("", "Leave %s" % from_stop, "Arrive %s" % to_stop)]
  now = datetime.datetime.now().time()
  
  for (leave, arrive) in sched:
    if leave > now:
      marker = '***'
    else:
      marker = ''
    table.append( (marker, str(leave), str(arrive)) )
  print_table(table)

def print_stops(conn):
  stops = get_stops(conn)
  for stop in stops:
    print stop

def _get_table_list(conn):
  return [name for (name,) in conn.execute("select name from sqlite_master where type='table'")]

def parse_args():
  global __usage
  op = OptionParser(usage = __usage)
  op.add_option("-l", "--list-stops", dest="list_stops", action="store_true")
  op.add_option("-f", "--from", dest='frm', action='store', type='string')
  op.add_option("-t", "--to", dest='to', action='store', type='string')
  opts, args = op.parse_args()
  if len(args):
    op.print_usage()
    raise Exception("Unhandled args: %s" % repr(args))
  if not opts.list_stops and (not opts.frm or not opts.to):
    op.print_usage()
    sys.exit(1)
  return opts

def main():
  args = parse_args()
  conn = sqlite3.connect('/tmp/caltrain_schedule.db')
  if 'caltrain' not in _get_table_list(conn):
    sched = pull_schedule()
    save_schedule_to_sql(conn, sched)
  if args.list_stops:
    print_stops(conn)
  else:
    print_schedule(conn, args.frm, args.to)

if __name__ == "__main__":
  main()

