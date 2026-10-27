#!/usr/bin/env python3
"""Entry point of review-cycle-state.

Kept free of syntax newer than Python 3.6 so the version guard can run on old interpreters.
"""

import os
import sys

if sys.version_info < (3, 10):
    sys.stderr.write(
        "review-cycle needs Python >= 3.10, found {}.{}\n".format(
            sys.version_info[0], sys.version_info[1]
        )
    )
    sys.exit(3)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import review_cycle.cli  # noqa: E402

sys.exit(review_cycle.cli.main(sys.argv[1:]))
