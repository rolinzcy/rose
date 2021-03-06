# -*- coding: utf-8 -*-
# -----------------------------------------------------------------------------
# Copyright (C) 2012-2019 British Crown (Met Office) & Contributors.
#
# This file is part of Rose, a framework for meteorological suites.
#
# Rose is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# Rose is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with Rose. If not, see <http://www.gnu.org/licenses/>.
# -----------------------------------------------------------------------------
"""Rose Bush: data access to cylc suite runtime databases."""

from fnmatch import fnmatch
from glob import glob
import os
import re
import tarfile

from metomi.rose.suite_engine_procs.cylc import CylcProcessor, CylcSuiteDAO


class RoseBushDAO(object):

    """Rose Bush: data access to cylc suite runtime databases."""

    CYCLE_ORDERS = {"time_desc": " DESC", "time_asc": " ASC"}
    JOB_ORDERS = {
        "time_desc": "time DESC, submit_num DESC, name DESC, cycle DESC",
        "time_asc": "time ASC, submit_num ASC, name ASC, cycle ASC",
        "cycle_desc_name_asc": "cycle DESC, name ASC, submit_num DESC",
        "cycle_desc_name_desc": "cycle DESC, name DESC, submit_num DESC",
        "cycle_asc_name_asc": "cycle ASC, name ASC, submit_num DESC",
        "cycle_asc_name_desc": "cycle ASC, name DESC, submit_num DESC",
        "name_asc_cycle_asc": "name ASC, cycle ASC, submit_num DESC",
        "name_desc_cycle_asc": "name DESC, cycle ASC, submit_num DESC",
        "name_asc_cycle_desc": "name ASC, cycle DESC, submit_num DESC",
        "name_desc_cycle_desc": "name DESC, cycle DESC, submit_num DESC",
        "time_submit_desc": (
            "time_submit DESC, submit_num DESC, name DESC, cycle DESC"),
        "time_submit_asc": (
            "time_submit ASC, submit_num DESC, name DESC, cycle DESC"),
        "time_run_desc": (
            "time_run DESC, submit_num DESC, name DESC, cycle DESC"),
        "time_run_asc": (
            "time_run ASC, submit_num DESC, name DESC, cycle DESC"),
        "time_run_exit_desc": (
            "time_run_exit DESC, submit_num DESC, name DESC, cycle DESC"),
        "time_run_exit_asc": (
            "time_run_exit ASC, submit_num DESC, name DESC, cycle DESC"),
        "duration_queue_desc": (
            "(CAST(strftime('%s', time_run) AS NUMERIC) -" +
            " CAST(strftime('%s', time_submit) AS NUMERIC)) DESC, " +
            "submit_num DESC, name DESC, cycle DESC"),
        "duration_queue_asc": (
            "(CAST(strftime('%s', time_run) AS NUMERIC) -" +
            " CAST(strftime('%s', time_submit) AS NUMERIC)) ASC, " +
            "submit_num DESC, name DESC, cycle DESC"),
        "duration_run_desc": (
            "(CAST(strftime('%s', time_run_exit) AS NUMERIC) -" +
            " CAST(strftime('%s', time_run) AS NUMERIC)) DESC, " +
            "submit_num DESC, name DESC, cycle DESC"),
        "duration_run_asc": (
            "(CAST(strftime('%s', time_run_exit) AS NUMERIC) -" +
            " CAST(strftime('%s', time_run) AS NUMERIC)) ASC, " +
            "submit_num DESC, name DESC, cycle DESC"),
        "duration_queue_run_desc": (
            "(CAST(strftime('%s', time_run_exit) AS NUMERIC) -" +
            " CAST(strftime('%s', time_submit) AS NUMERIC)) DESC, " +
            "submit_num DESC, name DESC, cycle DESC"),
        "duration_queue_run_asc": (
            "(CAST(strftime('%s', time_run_exit) AS NUMERIC) -" +
            " CAST(strftime('%s', time_submit) AS NUMERIC)) ASC, " +
            "submit_num DESC, name DESC, cycle DESC"),
    }
    JOB_STATUS_COMBOS = {
        "all": "",
        "submitted": "submit_status == 0 AND time_run IS NULL",
        "submitted,running": "submit_status == 0 AND run_status IS NULL",
        "submission-failed": "submit_status == 1",
        "submission-failed,failed": "submit_status == 1 OR run_status == 1",
        "running": "time_run IS NOT NULL AND run_status IS NULL",
        "running,succeeded,failed": "time_run IS NOT NULL",
        "succeeded": "run_status == 0",
        "succeeded,failed": "run_status IS NOT NULL",
        "failed": "run_status == 1",
    }
    REC_CYCLE_QUERY_OP = re.compile(r"\A(before |after |[<>]=?)(.+)\Z")
    REC_SEQ_LOG = re.compile(r"\A(.+\.)([^\.]+)(\.[^\.]+)\Z")
    SUITE_CONF = CylcProcessor.SUITE_CONF
    SUITE_DIR_REL_ROOT = CylcProcessor.SUITE_DIR_REL_ROOT
    TASK_STATUS_GROUPS = {
        "active": [
            "ready", "queued", "submitting", "submitted", "submit-retrying",
            "running", "retrying"],
        "fail": ["submission failed", "failed"],
        "success": ["expired", "succeeded"]}
    TASK_STATUSES = (
        "runahead", "waiting", "held", "queued", "ready", "expired",
        "submitted", "submit-failed", "submit-retrying", "running",
        "succeeded", "failed", "retrying")

    def __init__(self):
        self.daos = {}

    def get_suite_broadcast_states(self, user_name, suite_name):
        """Return broadcast states of a suite.

        [[point, name, key, value], ...]

        """
        # Check if "broadcast_states" table is available or not
        if not self._db_has_table(user_name, suite_name, "broadcast_states"):
            return

        broadcast_states = []
        for row in self._db_exec(
                user_name, suite_name,
                "SELECT point,namespace,key,value FROM broadcast_states" +
                " ORDER BY point ASC, namespace ASC, key ASC"):
            point, namespace, key, value = row
            broadcast_states.append([point, namespace, key, value])
        return broadcast_states

    def get_suite_broadcast_events(self, user_name, suite_name):
        """Return broadcast events of a suite.

        [[time, change, point, name, key, value], ...]

        """
        # Check if "broadcast_events" table is available or not
        if not self._db_has_table(user_name, suite_name, "broadcast_events"):
            return {}

        broadcast_events = []
        for row in self._db_exec(
                user_name, suite_name,
                "SELECT time,change,point,namespace,key,value" +
                " FROM broadcast_events" +
                " ORDER BY time DESC, point DESC, namespace DESC, key DESC"):
            time_, change, point, namespace, key, value = row
            broadcast_events.append(
                (time_, change, point, namespace, key, value))
        return broadcast_events

    @staticmethod
    def get_suite_dir_rel(suite_name, *paths):
        """Return the relative path to the suite running directory.

        paths -- if specified, are added to the end of the path.
        """
        return CylcProcessor.get_suite_dir_rel(suite_name, *paths)

    def get_suite_job_entries(
            self, user_name, suite_name, cycles, tasks, task_status,
            job_status, order, limit, offset):
        """Query suite runtime database to return a listing of task jobs.

        user -- A string containing a valid user ID
        suite -- A string containing a valid suite ID
        cycles -- If specified, display only task jobs matching these cycles.
                  A value in the list can be a cycle, the string "before|after
                  CYCLE", or a glob to match cycles.
        tasks -- If specified, display only jobs with task names matching
                 these names. Values can be a valid task name or a glob like
                 pattern for matching valid task names.
        task_status -- If specified, it should be a list of task statuses.
                       Display only jobs in the specified list. If not
                       specified, display all jobs.
        job_status -- If specified, must be a string matching a key in
                      RoseBushDAO.JOB_STATUS_COMBOS. Select jobs by their
                      statuses.
        order -- Order search in a predetermined way. A valid value is one of
                 the keys in RoseBushDAO.ORDERS.
        limit -- Limit number of returned entries
        offset -- Offset entry number

        Return (entries, of_n_entries) where:
        entries -- A list of matching entries
        of_n_entries -- Total number of entries matching query

        Each entry is a dict:
            {"cycle": cycle, "name": name, "submit_num": submit_num,
             "events": [time_submit, time_init, time_exit],
             "task_status": task_status,
             "logs": {"script": {"path": path, "path_in_tar", path_in_tar,
                                 "size": size, "mtime": mtime},
                      "out": {...},
                      "err": {...},
                      ...}}
        """
        where_expr, where_args = self._get_suite_job_entries_where(
            cycles, tasks, task_status, job_status)

        # Get number of entries
        of_n_entries = 0
        stmt = ("SELECT COUNT(*)" +
                " FROM task_jobs JOIN task_states USING (name, cycle)" +
                where_expr)
        for row in self._db_exec(user_name, suite_name, stmt, where_args):
            of_n_entries = row[0]
            break
        else:
            self._db_close(user_name, suite_name)
            return ([], 0)

        # Get entries
        entries = []
        entry_of = {}
        stmt = ("SELECT" +
                " task_states.time_updated AS time," +
                " cycle, name," +
                " task_jobs.submit_num AS submit_num," +
                " task_states.submit_num AS submit_num_max," +
                " task_states.status AS task_status," +
                " time_submit, submit_status," +
                " time_run, time_run_exit, run_signal, run_status," +
                " user_at_host, batch_sys_name, batch_sys_job_id" +
                " FROM task_jobs JOIN task_states USING (cycle, name)" +
                where_expr +
                " ORDER BY " +
                self.JOB_ORDERS.get(order, self.JOB_ORDERS["time_desc"]))
        limit_args = []
        if limit:
            stmt += " LIMIT ? OFFSET ?"
            limit_args = [limit, offset]
        for row in self._db_exec(
                user_name, suite_name, stmt, where_args + limit_args):
            (
                cycle, name, submit_num, submit_num_max, task_status,
                time_submit, submit_status,
                time_run, time_run_exit, run_signal, run_status,
                user_at_host, batch_sys_name, batch_sys_job_id
            ) = row[1:]
            entry = {
                "cycle": cycle,
                "name": name,
                "submit_num": submit_num,
                "submit_num_max": submit_num_max,
                "events": [time_submit, time_run, time_run_exit],
                "task_status": task_status,
                "submit_status": submit_status,
                "run_signal": run_signal,
                "run_status": run_status,
                "host": user_at_host,
                "submit_method": batch_sys_name,
                "submit_method_id": batch_sys_job_id,
                "logs": {},
                "seq_logs_indexes": {}}
            entries.append(entry)
            entry_of[(cycle, name, submit_num)] = entry
        self._db_close(user_name, suite_name)
        if entries:
            self._get_job_logs(user_name, suite_name, entries, entry_of)
        return (entries, of_n_entries)

    def _get_suite_job_entries_where(
            self, cycles, tasks, task_status, job_status):
        """Helper for get_suite_job_entries.

        Get query's "WHERE" expression and its arguments.
        """
        where_exprs = []
        where_args = []
        if cycles:
            cycle_where_exprs = []
            for cycle in cycles:
                match = self.REC_CYCLE_QUERY_OP.match(cycle)
                if match:
                    operator, operand = match.groups()
                    where_args.append(operand)
                    if operator == "before ":
                        cycle_where_exprs.append("cycle <= ?")
                    elif operator == "after ":
                        cycle_where_exprs.append("cycle >= ?")
                    else:
                        cycle_where_exprs.append("cycle %s ?" % operator)
                else:
                    where_args.append(cycle)
                    cycle_where_exprs.append("cycle GLOB ?")
            where_exprs.append(" OR ".join(cycle_where_exprs))
        if tasks:
            where_exprs.append(" OR ".join(["name GLOB ?"] * len(tasks)))
            where_args += tasks
        if task_status:
            task_status_where_exprs = []
            for item in task_status:
                task_status_where_exprs.append("task_states.status == ?")
                where_args.append(item)
            where_exprs.append(" OR ".join(task_status_where_exprs))
        try:
            job_status_where = self.JOB_STATUS_COMBOS[job_status]
        except KeyError:
            pass
        else:
            if job_status_where:
                where_exprs.append(job_status_where)
        if where_exprs:
            return (" WHERE (" + ") AND (".join(where_exprs) + ")", where_args)
        else:
            return ("", where_args)

    def _get_job_logs(self, user_name, suite_name, entries, entry_of):
        """Helper for "get_suite_job_entries". Get job logs.

        Recent job logs are likely to be in the file system, so we can get a
        listing of the relevant "log/job/CYCLE/NAME/SUBMI_NUM/" directory.
        Older job logs may be archived in "log/job-CYCLE.tar.gz", we should
        only open each relevant TAR file once to obtain a listing for all
        relevant entries of that cycle.

        Modify each entry in entries.
        """
        prefix = "~"
        if user_name:
            prefix += user_name
        user_suite_dir = os.path.expanduser(os.path.join(
            prefix, self.get_suite_dir_rel(suite_name)))
        try:
            fs_log_cycles = os.listdir(
                os.path.join(user_suite_dir, "log", "job"))
        except OSError:
            fs_log_cycles = []
        targzip_log_cycles = []
        for name in glob(os.path.join(user_suite_dir, "log", "job-*.tar.gz")):
            targzip_log_cycles.append(os.path.basename(name)[4:-7])

        relevant_targzip_log_cycles = []
        for entry in entries:
            if entry["cycle"] in fs_log_cycles:
                pathd = "log/job/%(cycle)s/%(name)s/%(submit_num)02d" % entry
                try:
                    filenames = os.listdir(os.path.join(user_suite_dir, pathd))
                except OSError:
                    continue
                for filename in filenames:
                    try:
                        stat = os.stat(
                            os.path.join(user_suite_dir, pathd, filename))
                    except OSError:
                        pass
                    else:
                        entry["logs"][filename] = {
                            "path": "/".join([pathd, filename]),
                            "path_in_tar": None,
                            "mtime": int(stat.st_mtime),  # int precise enough
                            "size": stat.st_size,
                            "exists": True,
                            "seq_key": None}
                        continue
            if entry["cycle"] in targzip_log_cycles:
                if entry["cycle"] not in relevant_targzip_log_cycles:
                    relevant_targzip_log_cycles.append(entry["cycle"])

        for cycle in relevant_targzip_log_cycles:
            path = os.path.join("log", "job-%s.tar.gz" % cycle)
            tar = tarfile.open(os.path.join(user_suite_dir, path), "r:gz")
            for member in tar.getmembers():
                # member.name expected to be "job/cycle/task/submit_num/*"
                if not member.isfile():
                    continue
                try:
                    cycle_str, name, submit_num_str = (
                        member.name.split("/", 4)[1:4])
                    entry = entry_of[(cycle_str, name, int(submit_num_str))]
                except (KeyError, ValueError):
                    continue
                entry["logs"][os.path.basename(member.name)] = {
                    "path": path,
                    "path_in_tar": member.name,
                    "mtime": int(member.mtime),  # too precise otherwise
                    "size": member.size,
                    "exists": True,
                    "seq_key": None}

        # Sequential logs
        for entry in entries:
            for filename, filename_items in entry["logs"].items():
                seq_log_match = self.REC_SEQ_LOG.match(filename)
                if not seq_log_match:
                    continue
                head, index_str, tail = seq_log_match.groups()
                seq_key = head + "*" + tail
                filename_items["seq_key"] = seq_key
                if seq_key not in entry["seq_logs_indexes"]:
                    entry["seq_logs_indexes"][seq_key] = {}
                entry["seq_logs_indexes"][seq_key][index_str] = filename
            for seq_key, indexes in entry["seq_logs_indexes"].items():
                # Only one item, not a sequence
                if len(indexes) <= 1:
                    entry["seq_logs_indexes"].pop(seq_key)
                # All index_str are numbers, convert key to integer so
                # the template can sort them as numbers
                try:
                    int_indexes = {}
                    for index_str, filename in indexes.items():
                        int_indexes[int(index_str)] = filename
                    entry["seq_logs_indexes"][seq_key] = int_indexes
                except ValueError:
                    pass
            for filename, log_dict in entry["logs"].items():
                # Unset seq_key for singular items
                if log_dict["seq_key"] not in entry["seq_logs_indexes"]:
                    log_dict["seq_key"] = None

    def get_suite_logs_info(self, user_name, suite_name):
        """Return the information of the suite logs.

        Return a tuple that looks like:
            ("cylc-run",
             {"err": {"path": "log/suite/err", "mtime": mtime, "size": size},
              "log": {"path": "log/suite/log", "mtime": mtime, "size": size},
              "out": {"path": "log/suite/out", "mtime": mtime, "size": size}})

        """
        logs_info = {}
        prefix = "~"
        if user_name:
            prefix += user_name
        d_rel = self.get_suite_dir_rel(suite_name)
        dir_ = os.path.expanduser(os.path.join(prefix, d_rel))
        # Get cylc files.
        cylc_files = ["cylc-suite-env", "suite.rc", "suite.rc.processed"]
        for key in cylc_files:
            f_name = os.path.join(dir_, key)
            if os.path.isfile(f_name):
                f_stat = os.stat(f_name)
                logs_info[key] = {"path": key,
                                  "mtime": f_stat.st_mtime,
                                  "size": f_stat.st_size}
        # Get cylc suite log files.
        log_files = ["log/suite/err", "log/suite/log", "log/suite/out"]
        for key in log_files:
            f_name = os.path.join(dir_, key)
            if os.path.isfile(f_name):
                try:
                    link_path = os.readlink(f_name)
                except OSError:
                    link_path = f_name
                old_logs = []  # Old log naming system.
                new_logs = []  # New log naming system.
                # TODO: Post migration to cylc this logic can be replaced by:
                # `from cylc.suite_logging import get_logs` (superior)
                for log in glob(f_name + '.*'):
                    log_name = os.path.basename(log)
                    if log_name == link_path:
                        continue
                    if len(log_name.split('.')[1]) > 3:
                        new_logs.append(os.path.join("log", "suite", log_name))
                    else:
                        old_logs.append(os.path.join("log", "suite", log_name))
                new_logs.sort(reverse=True)
                old_logs.sort()
                f_stat = os.stat(f_name)
                logs_info[key] = {"path": key,
                                  "paths": [key] + new_logs + old_logs,
                                  "mtime": f_stat.st_mtime,
                                  "size": f_stat.st_size}
        return ("cylc", logs_info)

    def get_suite_cycles_summary(
            self, user_name, suite_name, order, limit, offset):
        """Return a the state summary (of each cycle) of a user's suite.

        user -- A string containing a valid user ID
        suite -- A string containing a valid suite ID
        limit -- Limit number of returned entries
        offset -- Offset entry number

        Return (entries, of_n_entries), where entries is a data structure that
        looks like:
            [   {   "cycle": cycle,
                    "n_states": {
                        "active": N, "success": M, "fail": L, "job_fails": K,
                    },
                    "max_time_updated": T2,
                },
                # ...
            ]
        where:
        * cycle is a date-time cycle label
        * N, M, L, K are the numbers of tasks in given states
        * T2 is the time when last update time of (a task in) the cycle

        and of_n_entries is the total number of entries.

        """
        of_n_entries = 0
        stmt = ("SELECT COUNT(DISTINCT cycle) FROM task_states WHERE " +
                "submit_num > 0")
        for row in self._db_exec(user_name, suite_name, stmt):
            of_n_entries = row[0]
            break
        if not of_n_entries:
            return ([], 0)

        # Not strictly correct, if cycle is in basic date-only format,
        # but should not matter for most cases
        integer_mode = False
        stmt = "SELECT cycle FROM task_states LIMIT 1"
        for row in self._db_exec(user_name, suite_name, stmt):
            integer_mode = row[0].isdigit()
            break

        prefix = "~"
        if user_name:
            prefix += user_name
        user_suite_dir = os.path.expanduser(os.path.join(
            prefix, self.get_suite_dir_rel(suite_name)))
        targzip_log_cycles = []
        try:
            for item in os.listdir(os.path.join(user_suite_dir, "log")):
                if item.startswith("job-") and item.endswith(".tar.gz"):
                    targzip_log_cycles.append(item[4:-7])
        except OSError:
            pass

        states_stmt = {}
        for key, names in self.TASK_STATUS_GROUPS.items():
            states_stmt[key] = " OR ".join(
                ["status=='%s'" % (name) for name in names])
        stmt = (
            "SELECT" +
            " cycle," +
            " max(time_updated)," +
            " sum(" + states_stmt["active"] + ") AS n_active," +
            " sum(" + states_stmt["success"] + ") AS n_success,"
            " sum(" + states_stmt["fail"] + ") AS n_fail"
            " FROM task_states" +
            " GROUP BY cycle")
        if integer_mode:
            stmt += " ORDER BY cast(cycle as number)"
        else:
            stmt += " ORDER BY cycle"
        stmt += self.CYCLE_ORDERS.get(order, self.CYCLE_ORDERS["time_desc"])
        stmt_args = []
        if limit:
            stmt += " LIMIT ? OFFSET ?"
            stmt_args += [limit, offset]
        entry_of = {}
        entries = []
        for row in self._db_exec(user_name, suite_name, stmt, stmt_args):
            cycle, max_time_updated, n_active, n_success, n_fail = row
            if n_active or n_success or n_fail:
                entry_of[cycle] = {
                    "cycle": cycle,
                    "has_log_job_tar_gz": cycle in targzip_log_cycles,
                    "max_time_updated": max_time_updated,
                    "n_states": {
                        "active": n_active,
                        "success": n_success,
                        "fail": n_fail,
                        "job_active": 0,
                        "job_success": 0,
                        "job_fail": 0,
                    },
                }
                entries.append(entry_of[cycle])

        # Check if "task_jobs" table is available or not.
        # Note: A single query with a JOIN is probably a more elegant solution.
        # However, timing tests suggest that it is cheaper with 2 queries.
        # This 2nd query may return more results than is necessary, but should
        # be a very cheap query as it does not have to do a lot of work.
        if self._db_has_table(user_name, suite_name, "task_jobs"):
            stmt = (
                "SELECT cycle," +
                " sum(" + self.JOB_STATUS_COMBOS["submitted,running"] +
                ") AS n_job_active," +
                " sum(" + self.JOB_STATUS_COMBOS["succeeded"] +
                ") AS n_job_success," +
                " sum(" + self.JOB_STATUS_COMBOS["submission-failed,failed"] +
                ") AS n_job_fail" +
                " FROM task_jobs GROUP BY cycle")
        else:
            fail_events_stmt = " OR ".join(
                ["event=='%s'" % (name)
                 for name in self.TASK_STATUS_GROUPS["fail"]])
            stmt = (
                "SELECT cycle," +
                " sum(" + fail_events_stmt + ") AS n_job_fail" +
                " FROM task_events GROUP BY cycle")
        for cycle, n_job_active, n_job_success, n_job_fail in self._db_exec(
                user_name, suite_name, stmt):
            try:
                entry_of[cycle]["n_states"]["job_active"] = n_job_active
                entry_of[cycle]["n_states"]["job_success"] = n_job_success
                entry_of[cycle]["n_states"]["job_fail"] = n_job_fail
            except KeyError:
                pass
            else:
                del entry_of[cycle]
                if not entry_of:
                    break
        self._db_close(user_name, suite_name)

        return entries, of_n_entries

    def get_suite_state_summary(self, user_name, suite_name):
        """Return a the state summary of a user's suite.

        Return {"is_running": b, "is_failed": b, "server": s}
        where:
        * is_running is a boolean to indicate if the suite is running
        * is_failed: a boolean to indicate if any tasks (submit) failed
        * server: host:port of server, if available

        """
        ret = {
            "is_running": False,
            "is_failed": False,
            "server": None}
        dao = self._db_init(user_name, suite_name)
        if not os.access(dao.db_f_name, os.F_OK | os.R_OK):
            return ret

        port_file_path = os.path.expanduser(
            os.path.join(
                "~" + user_name, "cylc-run", suite_name, ".service",
                "contact"))
        try:
            host = None
            port_str = None
            for line in open(port_file_path):
                key, value = [item.strip() for item in line.split("=", 1)]
                if key == "CYLC_SUITE_HOST":
                    host = value
                elif key == "CYLC_SUITE_PORT":
                    port_str = value
        except (IOError, ValueError):
            pass
        else:
            if host and port_str:
                ret["is_running"] = True
                ret["server"] = host.split(".", 1)[0] + ":" + port_str

        stmt = "SELECT status FROM task_states WHERE status GLOB ? LIMIT 1"
        stmt_args = ["*failed"]
        for _ in self._db_exec(user_name, suite_name, stmt, stmt_args):
            ret["is_failed"] = True
            break
        self._db_close(user_name, suite_name)

        return ret

    @staticmethod
    def is_conf(path):
        """Return "cylc-suite-rc" if path is a Cylc suite.rc file."""
        if fnmatch(os.path.basename(path), "suite*.rc*"):
            return "cylc-suite-rc"

    @classmethod
    def parse_job_log_rel_path(cls, f_name):
        """Return (cycle, task, submit_num, ext)."""
        return CylcProcessor.parse_job_log_rel_path(f_name)

    def _db_close(self, user_name, suite_name):
        """Close a named database connection."""
        key = (user_name, suite_name)
        if self.daos.get(key) is not None:
            self.daos[key].close()

    def _db_exec(self, user_name, suite_name, stmt, stmt_args=None):
        """Execute a query on a named database connection."""
        daos = self._db_init(user_name, suite_name)
        return daos.execute(stmt, stmt_args)

    def _db_has_table(self, user_name, suite_name, table_name):
        """Return True if table_name exists in the suite database."""
        cursor = self._db_exec(
            user_name, suite_name,
            "SELECT name FROM sqlite_master WHERE name==?", [table_name])
        return cursor.fetchone() is not None

    def _db_init(self, user_name, suite_name):
        """Initialise a named database connection."""
        key = (user_name, suite_name)
        if key not in self.daos:
            prefix = "~"
            if user_name:
                prefix += user_name
            for name in [os.path.join("log", "db"), "cylc-suite.db"]:
                db_f_name = os.path.expanduser(os.path.join(
                    prefix, self.get_suite_dir_rel(suite_name, name)))
                self.daos[key] = CylcSuiteDAO(db_f_name)
                if os.path.exists(db_f_name):
                    break
        return self.daos[key]
