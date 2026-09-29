# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 Tim Aidley

"""Human readable formatting of sizes, rates and durations."""


def human_bytes(n):
    n = float(n)
    for unit in ('B', 'KiB', 'MiB', 'GiB', 'TiB'):
        if abs(n) < 1024 or unit == 'TiB':
            return ('%d %s' if unit == 'B' else '%.1f %s') % (n, unit)
        n /= 1024


def human_rate(bytes_per_sec):
    return human_bytes(bytes_per_sec) + '/s'


def human_duration(seconds):
    seconds = max(0, int(seconds))
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, secs = divmod(rem, 60)
    text = '%d:%02d:%02d' % (hours, minutes, secs)
    if days:
        text = '%dd %s' % (days, text)
    return text
