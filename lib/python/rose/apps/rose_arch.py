# -*- coding: utf-8 -*-
#-----------------------------------------------------------------------------
# (C) British Crown Copyright 2012-3 Met Office.
#
# This file is part of Rose, a framework for scientific suites.
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
#-----------------------------------------------------------------------------
"""Builtin application: rose_arch: transform and archive suite files."""

import errno
from glob import glob
import os
import re
from rose.app_run import BuiltinApp, ConfigValueError
from rose.checksum import get_checksum
from rose.env import env_var_process, UnboundEnvironmentVariableError
from rose.reporter import Event
from rose.scheme_handler import SchemeHandlersManager
import shlex
import sqlite3
import sys
from tempfile import mkdtemp


class RoseArchEvent(Event):

    """Event raised on an archiving target."""

    def __str__(self):
        target = self.args[0]
        ret = "%s %s (compress=%s)" % (target.status, target.name,
                                       target.compress_scheme)
        if target.status != target.ST_OLD:
            for source in sorted(target.sources.values(),
                                 lambda s1, s2: cmp(s1.name, s2.name)):
                ret += "\n      %s (%s)" % (source.name, source.orig_path)
        return ret


class RoseArchApp(BuiltinApp):

    """Transform and archive files generated by suite tasks."""

    SCHEME = "rose_arch"
    SECTION = "arch"

    def run(self, app_runner, config, *args, **kwargs):
        """Transform and archive suite files.

        This application is designed to work under "rose task-run" in a suite.

        """
        dao = RoseArchDAO()
        suite_name = os.getenv("ROSE_SUITE_NAME")
        if not suite_name:
            return
        suite_dir = app_runner.suite_engine_proc.get_suite_dir(suite_name)
        cwd = os.getcwd()
        app_runner.fs_util.chdir(suite_dir)
        try:
            return self._run(dao, app_runner, config)
        finally:
            app_runner.fs_util.chdir(cwd)
            dao.close()

    def _run(self, dao, app_runner, config):
        """Transform and archive suite files.

        This application is designed to work under "rose task-run" in a suite.

        """
        p = os.path.dirname(os.path.dirname(sys.modules["rose"].__file__))
        compress_manager = SchemeHandlersManager(
                [p], "rose.apps.rose_arch_compressions", ["compress_sources"],
                None, app_runner)
        # Set up the targets
        cycle = os.getenv("ROSE_TASK_CYCLE_TIME")
        targets = []
        for t_key, t_node in sorted(config.value.items()):
            if t_node.is_ignored() or ":" not in t_key:
                continue
            s_key_head, s_key_tail = t_key.split(":", 1)
            if s_key_head != self.SECTION or not s_key_tail:
                continue
            target_prefix = self._get_conf(
                        config, t_node, "target-prefix", default="")
            target_name = target_prefix + s_key_tail
            target = RoseArchTarget(target_name)
            target.command_format = self._get_conf(
                        config, t_node, "command-format", compulsory=True)
            source_str = self._get_conf(
                        config, t_node, "source", compulsory=True)
            source_prefix = self._get_conf(
                        config, t_node, "source-prefix", default="")
            for source_glob in shlex.split(source_str):
                for path in glob(source_prefix + source_glob):
                    # N.B. source_prefix may not be a directory
                    name = path[len(source_prefix):]
                    for p, checksum in get_checksum(path):
                        if checksum is None: # is directory
                            continue
                        if p:
                            target.sources[checksum] = RoseArchSource(
                                            checksum,
                                            os.path.join(name, p),
                                            os,path.join(path, p))
                        else: # path is a file
                            target.sources[checksum] = RoseArchSource(
                                            checksum, name, path)
            if not target.sources:
                e = OSError(errno.ENOENT, os.strerror(errno.ENOENT),
                            source_str)
                raise ConfigValueError([self.SECTION, "source"], source_str, e)
            target.compress_scheme = self._get_conf(config, t_node, "compress")
            if target.compress_scheme:
                if (compress_manager.get_handler(target.compress_scheme) is
                    None):
                    raise ConfigValueError([self.SECTION, "compress"],
                                           target.compress_scheme,
                                           KeyError(target.compress_scheme))
            else:
                target_base = target.name
                if "/" in target.name:
                    target_head, target_base = target.name.rsplit("/", 1)
                if "." in target_base:
                    head, tail = target_base.split(".", 1)
                    if compress_manager.get_handler(tail):
                        target.compress_scheme = tail
            rename_format = self._get_conf(config, t_node, "rename-format")
            if rename_format:
                rename_parser = self._get_conf(config, t_node, "rename-parser")
                if rename_parser:
                    rename_parser = re.compile(rename_parser)
                for source in target.sources.values():
                    d = {"cycle": cycle, "name": source.name}
                    if rename_parser:
                        match = rename_parser.match(source.name)
                        if match:
                            d.update(match.groupdict())
                    source.name = rename_format % d
            old_target = dao.select(target.name)
            if old_target is None or old_target != target:
                dao.delete(target)
            else:
                target.status = target.ST_OLD
            targets.append(target)

        # Delete from database items that are no longer relevant
        dao.delete_all(filter_targets=targets)

        # Update the targets
        for target in targets:
            if target.status == target.ST_OLD:
                app_runner.handle_event(RoseArchEvent(target))
                continue
            target.command_rc = 1
            dao.insert(target)
            work_dir = mkdtemp()
            try:
                # Rename sources
                rename_required = False
                for source in target.sources.values():
                    if source.name != source.orig_name:
                        rename_required = True
                        break
                if rename_required:
                    for source in target.sources.values():
                        source.path = os.path.join(work_dir, source.name)
                        source_path_d = os.path.dirname(source.path)
                        app_runner.fs_util.makedirs(source_path_d)
                        app_runner.fs_util.symlink(source.orig_path,
                                                   source.path)
                # Compress sources
                if target.compress_scheme:
                    c = compress_manager.get_handler(target.compress_scheme)
                    c.compress_sources(target, work_dir)
                # Run archive command
                sources = []
                if target.work_source_path:
                    sources = [target.work_source_path]
                else:
                    for source in target.sources.values():
                        sources.append(source.path)
                sources_str = app_runner.popen.list_to_shell_str(sources)
                target_str = app_runner.popen.list_to_shell_str([target.name])
                command = target.command_format % {"sources": sources_str,
                                                   "target": target_str}
                rc, out, err = app_runner.popen.run(command, shell=True)
                target.command_rc = rc
                dao.update_command_rc(target)
            finally:
                app_runner.fs_util.delete(work_dir)
            if rc:
                app_runner.handle_event(err,
                                        kind=Event.KIND_ERR, level=Event.FAIL)
                app_runner.handle_event(out)
                target.status = target.ST_BAD
            else:
                app_runner.handle_event(err, kind=Event.KIND_ERR)
                app_runner.handle_event(out)
                target.status = target.ST_NEW
            app_runner.handle_event(RoseArchEvent(target))

        return len(targets) - [t.command_rc for t in targets].count(0)

    def _get_conf(self, r_node, t_node, key, compulsory=False, default=None):
        value = t_node.get_value(
                        [key],
                        r_node.get_value([self.SECTION, key], default=default))
        if compulsory and not value:
            raise ConfigValueError([self.SECTION, key], None, KeyError(key))
        if value:
            try:
                value = env_var_process(value)
            except UnboundEnvironmentVariableError as e:
                raise ConfigValueError(keys, value, e)
        return value


class RoseArchTarget(object):

    """An archive target."""

    ST_OLD = "="
    ST_NEW = "+"
    ST_BAD = "!"

    def __init__(self, name):
        self.name = name
        self.compress_scheme = None
        self.command_format = None
        self.command_rc = 0
        self.sources = {} # checksum: RoseArchSource
        self.status = None
        self.work_source_path = None

    def __eq__(self, other):
        if id(self) != id(other):
            for key in ["name", "compress_scheme", "command_format",
                        "command_rc", "sources"]:
                if getattr(self, key) != getattr(other, key, None):
                    return False
        return True

    def __ne__(self, other):
        return not self.__eq__(other)


class RoseArchSource(object):

    """An archive source."""

    def __init__(self, checksum, orig_name, orig_path=None):
        self.checksum = checksum
        self.orig_name = orig_name
        self.orig_path = orig_path
        self.name = self.orig_name
        self.path = self.orig_path

    def __eq__(self, other):
        if id(self) != id(other):
            for key in ["checksum", "name"]:
                if getattr(self, key) != getattr(other, key, None):
                    return False
        return True

    def __ne__(self, other):
        return not self.__eq__(other)


class RoseArchDAO(object):

    """Data access object for incremental mode."""

    FILE_NAME = ".rose-arch.db"
    T_SOURCES = "sources"
    T_TARGETS = "targets"

    def __init__(self):
        self.file_name = os.path.abspath(self.FILE_NAME)
        self.conn = None
        self.create()

    def close(self):
        """Close connection to the SQLite database file."""
        if self.conn is not None:
            self.conn.close()
            self.conn = None

    def get_conn(self):
        """Connect to the SQLite database file."""
        if self.conn is None:
            self.conn = sqlite3.connect(self.file_name)
        return self.conn

    def create(self):
        """Create the database file if it does not exist."""
        if not os.path.exists(self.file_name):
            conn = self.get_conn()
            c = conn.cursor()
            c.execute("""CREATE TABLE """ + self.T_TARGETS + """ (
                          target_name TEXT,
                          compress_scheme TEXT,
                          command_format TEXT,
                          command_rc INT,
                          PRIMARY KEY(target_name))""")
            c.execute("""CREATE TABLE """ + self.T_SOURCES + """ (
                          target_name TEXT,
                          source_name TEXT,
                          checksum TEXT,
                          UNIQUE(target_name, checksum))""")
            conn.commit()

    def delete(self, target):
        """Remove target from the database."""
        conn = self.get_conn()
        c = conn.cursor()
        for t in [self.T_TARGETS, self.T_SOURCES]:
            c.execute("DELETE FROM " + t + " WHERE target_name==?",
                      [target.name])
        conn.commit()

    def delete_all(self, filter_targets):
        """Remove all but those matching filter_targets from the database."""
        conn = self.get_conn()
        c = conn.cursor()
        where = ""
        stmt_args = []
        if filter_targets:
            stmt_fragments = []
            for filter_target in filter_targets:
                stmt_fragments.append("target_name != ?")
                stmt_args.append(filter_target.name)
            where += " WHERE " + " AND ".join(stmt_fragments)
        for t in [self.T_TARGETS, self.T_SOURCES]:
            c.execute("DELETE FROM " + t + where, stmt_args)
        conn.commit()

    def insert(self, target):
        """Insert a target in the database."""
        conn = self.get_conn()
        c = conn.cursor()
        t_stmt = "INSERT INTO " + self.T_TARGETS + " VALUES (?, ?, ?, ?)"
        t_stmt_args = [target.name, target.compress_scheme,
                       target.command_format, target.command_rc]
        c.execute(t_stmt, t_stmt_args)
        sh_stmt = r"INSERT INTO " + self.T_SOURCES + " VALUES (?, ?, ?)"
        sh_stmt_args = [target.name]
        for checksum, source in target.sources.items():
            c.execute(sh_stmt, sh_stmt_args + [source.name, checksum])
        conn.commit()

    def select(self, target_name):
        """Query database for target_name.

        On success, reconstruct the target as an instance of RoseArchTarget
        and return it.

        Return None on failure.

        """
        conn = self.get_conn()
        c = conn.cursor()
        t_stmt = ("SELECT compress_scheme,command_format,command_rc FROM " +
                  self.T_TARGETS +
                  " WHERE target_name==?")
        t_stmt_args = [target_name]
        for row in c.execute(t_stmt, t_stmt_args):
            t = RoseArchTarget(target_name)
            t.compress_scheme, t.command_format, t.command_rc = row
            break
        else:
            return None
        s_stmt = ("SELECT source_name,checksum FROM " + self.T_SOURCES +
                  " WHERE target_name==?")
        s_stmt_args = [target_name]
        for s_row in c.execute(s_stmt, s_stmt_args):
            source_name, checksum = s_row
            t.sources[checksum] = RoseArchSource(checksum, source_name)
        return t

    def update_command_rc(self, target):
        """Update the command return code of a target in the database."""
        conn = self.get_conn()
        c = conn.cursor()
        c.execute("UPDATE " + self.T_TARGETS + " SET command_rc=?" +
                  " WHERE target_name==?", [target.command_rc, target.name])
        conn.commit()
