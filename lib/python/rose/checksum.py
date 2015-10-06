# -*- coding: utf-8 -*-
#-----------------------------------------------------------------------------
# (C) British Crown Copyright 2012-5 Met Office.
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
#-----------------------------------------------------------------------------
"""Calculates the MD5 checksum for a file or files in a directory."""


import errno
import hashlib
import os

from rose.resource import ResourceLocator


_DEFAULT_DEFAULT_KEY = "md5"
_DEFAULT_KEY = None


def get_checksum(name, checksum_func=None):
    """
    Calculate "checksum" of content in a file or directory called "name".

    By default, the "checksum" is MD5 checksum. This can modified by "impl",
    which should be a function with the interface:

        checksum_str = checksum_func(source_str)

    Return a list of 3-element tuples. Each tuple represents a path in "name",
    the checksum, and the access mode. If the path is a directory, the checksum
    and the access mode will both be set to None.

    If "name" is a file, it returns a one-element list with a
    ("", checksum, mode) tuple.

    If "name" does not exist, raise OSError.

    """
    if not os.path.exists(name):
        raise OSError(errno.ENOENT, os.strerror(errno.ENOENT), name)

    if checksum_func is None:
        checksum_func = get_checksum_func()
    path_and_checksum_list = []
    if os.path.isfile(name):
        checksum = checksum_func(name, "")
        path_and_checksum_list.append(
            ("", checksum, os.stat(os.path.realpath(name)).st_mode))
    else:  # if os.path.isdir(path):
        name = os.path.normpath(name)
        path_and_checksum_list = []
        for dirpath, _, filenames in os.walk(name):
            path = dirpath[len(name) + 1:]
            path_and_checksum_list.append((path, None, None))
            for filename in filenames:
                filepath = os.path.join(path, filename)
                source = os.path.join(name, filepath)
                checksum = checksum_func(source, name)
                mode = os.stat(os.path.realpath(source)).st_mode
                path_and_checksum_list.append((filepath, checksum, mode))
    return path_and_checksum_list


def get_checksum_func(key=None):
    """Return a checksum function suitable for get_checksum.

    "key" can be "mtime+size" or the name of a hash object from hashlib.
    If "key" is not specified, return function to do MD5 checksum.

    Raise KeyError(key) if "key" is not a recognised hash object.

    """
    if key is None:
        if _DEFAULT_KEY is None:
            _DEFAULT_KEY = ResourceLocator.default().get_conf().get_value(
                ["checksum-method"], _DEFAULT_DEFAULT_KEY)
        key = _DEFAULT_KEY
    if key == "mtime+size":
        return _mtime_and_size
    if not hasattr(hashlib, key.replace("sum", "")):
        raise KeyError(key)
    return lambda source, *_: _get_hexdigest(key, source)


def _get_hexdigest(key, source):
    """Load content of source into an hash object, and return its hexdigest."""
    hashobj = getattr(hashlib, key)()
    if hasattr(source, "read"):
        handle = source
    else:
        handle = open(source)
    try:
        f_bsize = os.statvfs(handle.name).f_bsize
    except (AttributeError, OSError):
        f_bsize = 4096
    while True:
        bytes_ = handle.read(f_bsize)
        if not bytes_:
            break
        hashobj.update(bytes_)
    handle.close()
    return hashobj.hexdigest()


def _mtime_and_size(source, root):
    """Return a string containing the name, its modified time and its size."""
    stat = os.stat(os.path.realpath(source))
    if root:
        source = os.path.relpath(source, root)
    return os.pathsep.join(["source=" + source,
                            "mtime=" + str(stat.st_mtime),
                            "size=" + str(stat.st_size)])
