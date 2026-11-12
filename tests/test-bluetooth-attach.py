import os
from pathlib import Path
import subprocess
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'overlay/mnt/vendor/ctrl/setBluetooth.sh'
class BluetoothAttach(unittest.TestCase):
    def test_stale_lock_retries_after_unblocking_radio(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); bindir=root/'bin'; bindir.mkdir()
            hci=root/'hci0'; lock=root/'init_bt'; lock.touch()
            log=root/'calls'
            for name, body in {
                'rfkill': 'echo "rfkill $*" >> "$CALLS"',
                'insmod': 'exit 0',
                'pidof': 'exit 1',
                'rtk_hciattach': 'echo attach >> "$CALLS"; mkdir "$HCI"; sleep 1',
                'hciconfig': 'echo hci0',
            }.items():
                p=bindir/name; p.write_text('#!/bin/sh\n'+body+'\n');p.chmod(0o755)
            env=dict(os.environ, PATH=str(bindir)+':'+os.environ['PATH'], BASEOS_BT_LOCK=str(lock), BASEOS_BT_HCI=str(hci), BASEOS_BT_ATTACH_LOG=str(root/'attach.log'), CALLS=str(log), HCI=str(hci))
            result=subprocess.run(['sh',str(SCRIPT),'all'],env=env,text=True,capture_output=True,timeout=8)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertTrue(hci.is_dir())
            self.assertEqual(log.read_text().splitlines(),['rfkill unblock bluetooth','attach'])
if __name__=='__main__':unittest.main()
