"""macOS headless idle-sleep guard: process-scoped, no global power changes."""
import os
from pathlib import Path
import sys
import subprocess
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import power_guard


class PowerGuardTests(unittest.TestCase):
    def test_caffeinate_is_process_scoped_and_does_not_change_pmset(self):
        with patch.object(power_guard.subprocess, 'Popen') as create, \
             patch.object(power_guard.os, 'getpid', return_value=9211):
            power_guard.begin()
        command = create.call_args.args[0]
        self.assertEqual(command, ['/usr/bin/caffeinate', '-i', '-s', '-w', '9211'])
        self.assertNotIn('-d', command)
        self.assertNotIn('pmset', str(create.call_args))

    def test_guard_ends_when_supervisor_stops(self):
        process = Mock()
        process.poll.return_value = None
        power_guard.finish(process)
        process.terminate.assert_called_once()
        process.kill.assert_not_called()

    def test_stuck_guard_is_killed_and_reaped(self):
        process = Mock()
        process.poll.return_value = None
        process.wait.side_effect = [subprocess.TimeoutExpired('caffeinate', 5), 0]
        power_guard.finish(process)
        process.kill.assert_called_once()
        self.assertEqual(process.wait.call_count, 2)

    def test_finished_guard_is_not_signalled(self):
        process = Mock()
        process.poll.return_value = 0
        power_guard.finish(process)
        process.terminate.assert_not_called()


if __name__ == '__main__':
    unittest.main()
