"""AudioRecorder stream recovery (#44), with a fake sounddevice, no hardware."""

import unittest
from unittest import mock

import numpy as np

from claude_stt import recorder
from claude_stt.recorder import AudioRecorder, RecorderConfig


class FakeStream:
    def __init__(self, sd, **kwargs):
        self.sd = sd
        self.kwargs = kwargs
        self.callback = kwargs["callback"]
        self.closed = False

    def start(self):
        if self.sd.fail_start:
            raise RuntimeError("AUHAL err -50")

    def stop(self):
        pass

    def close(self):
        self.closed = True

    def feed(self, value=0.1, frames=1024):
        self.callback(np.full((frames, 1), value, dtype="float32"), frames, None, None)


class FakeSoundDevice:
    """Stands in for the sounddevice module and records PortAudio re-inits."""

    def __init__(self):
        self.streams = []
        self.calls = []
        self.fail_start = False
        self.default_name = "AirPods"

    def InputStream(self, **kwargs):
        stream = FakeStream(self, **kwargs)
        self.streams.append(stream)
        return stream

    def query_devices(self, device=None, kind=None):
        if device is None and kind is None:
            return [{"name": self.default_name, "max_input_channels": 1}]
        if device is not None:
            return {"name": f"Device {device}"}
        return {"name": self.default_name}

    def _terminate(self):
        self.calls.append("terminate")

    def _initialize(self):
        self.calls.append("initialize")


class Clock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now


class RecorderRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.sd = FakeSoundDevice()
        patcher = mock.patch.object(recorder, "sd", self.sd)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.clock = Clock()
        self.sleeps = []

    def _recorder(self, device=None):
        rec = AudioRecorder(RecorderConfig(device=device))
        rec._clock = self.clock
        rec._sleep = self.sleeps.append
        self.assertTrue(rec.prewarm())
        self.sleeps.clear()
        return rec

    @property
    def stream(self):
        return self.sd.streams[-1]

    def test_ac1_given_a_silent_warm_stream_when_recording_starts_then_portaudio_reinits_and_a_new_stream_opens(self):
        rec = self._recorder()
        self.clock.now += 1.5
        with self.assertLogs("claude_stt.recorder", "INFO") as logs:
            self.assertTrue(rec.start())
        self.assertEqual(self.sd.calls, ["terminate", "initialize"])
        self.assertEqual(len(self.sd.streams), 2)
        self.assertTrue(self.sd.streams[0].closed)
        self.assertIsNone(self.stream.kwargs["device"])
        self.assertIn("Audio stream reopened on AirPods", "\n".join(logs.output))
        self.stream.feed()
        self.assertEqual(len(rec.stop()), 1024)

    def test_ac1_given_a_configured_device_when_reopened_then_exactly_that_device_opens(self):
        # AC-8 as well: a set audio_device survives the reopen.
        rec = self._recorder(device=3)
        self.clock.now += 1.5
        self.assertTrue(rec.start())
        self.assertEqual([s.kwargs["device"] for s in self.sd.streams], [3, 3])

    def test_ac7_given_a_healthy_warm_stream_when_recording_starts_then_no_reopen_and_no_delay(self):
        rec = self._recorder()
        self.clock.now += 0.5
        self.stream.feed()
        self.clock.now += 0.06
        self.assertTrue(rec.start())
        self.assertEqual(len(self.sd.streams), 1)
        self.assertEqual(self.sd.calls, [])
        self.assertEqual(self.sleeps, [])

    def test_ac2_given_a_callback_gap_while_recording_when_watchdog_runs_then_reopens_once_and_keeps_audio(self):
        rec = self._recorder()
        self.stream.feed()
        self.assertTrue(rec.start())
        self.stream.feed(0.2)
        self.clock.now += 1.1
        self.assertTrue(rec.ensure_alive())
        self.assertEqual(len(self.sd.streams), 2)
        self.assertTrue(rec.is_recording)
        self.stream.feed(0.3)
        audio = rec.stop()
        self.assertEqual(len(audio), 2048)
        self.assertAlmostEqual(float(audio[0]), 0.2, places=5)
        self.assertAlmostEqual(float(audio[-1]), 0.3, places=5)

    def test_ac2_given_callbacks_keep_arriving_when_watchdog_runs_then_nothing_reopens(self):
        rec = self._recorder()
        self.assertTrue(rec.start())
        for _ in range(20):
            self.clock.now += 0.064
            self.stream.feed()
            self.assertTrue(rec.ensure_alive())
        self.assertEqual(len(self.sd.streams), 1)

    def test_ac3_given_the_reopened_stream_stays_silent_when_watchdog_runs_again_then_it_reports_no_input(self):
        rec = self._recorder()
        self.assertTrue(rec.start())
        self.clock.now += 1.1
        self.assertTrue(rec.ensure_alive())
        self.clock.now += 1.1
        self.assertFalse(rec.ensure_alive())
        self.assertEqual(len(self.sd.streams), 2)

    def test_ac3_given_a_start_reopen_when_new_stream_stays_silent_then_watchdog_does_not_reopen_again(self):
        rec = self._recorder()
        self.clock.now += 1.5
        self.assertTrue(rec.start())
        self.clock.now += 1.1
        self.assertFalse(rec.ensure_alive())
        self.assertEqual(len(self.sd.streams), 2)

    def test_ac3_given_the_reopen_fails_when_recording_starts_then_start_fails(self):
        rec = self._recorder()
        self.clock.now += 1.5
        self.sd.fail_start = True
        with self.assertLogs("claude_stt.recorder", "ERROR"):
            self.assertFalse(rec.start())
        self.assertFalse(rec.is_recording)

    def test_ac3_given_the_reopen_fails_while_recording_when_watchdog_runs_then_it_reports_no_input(self):
        rec = self._recorder()
        self.assertTrue(rec.start())
        self.clock.now += 1.1
        self.sd.fail_start = True
        with self.assertLogs("claude_stt.recorder", "ERROR"):
            self.assertFalse(rec.ensure_alive())

    def test_given_a_new_recording_when_it_stalls_then_it_gets_its_own_reopen(self):
        rec = self._recorder()
        self.assertTrue(rec.start())
        self.clock.now += 1.1
        self.assertTrue(rec.ensure_alive())
        rec.stop()
        self.stream.feed()
        self.assertTrue(rec.start())
        self.clock.now += 1.1
        self.assertTrue(rec.ensure_alive())
        self.assertEqual(len(self.sd.streams), 3)

    def test_ac3_given_portaudio_terminate_raises_when_reopened_then_reopen_fails(self):
        rec = self._recorder()
        self.sd._terminate = mock.Mock(side_effect=RuntimeError("busy"))
        with self.assertLogs("claude_stt.recorder", "WARNING"):
            self.assertFalse(rec.reopen())
        self.assertEqual(len(self.sd.streams), 1)

    def test_ac3_given_portaudio_initialize_raises_when_recording_starts_then_start_fails(self):
        rec = self._recorder()
        self.clock.now += 1.5
        self.sd._initialize = mock.Mock(side_effect=RuntimeError("no devices"))
        with self.assertLogs("claude_stt.recorder", "WARNING"):
            self.assertFalse(rec.start())
        self.assertFalse(rec.is_recording)

    def test_ac3_given_portaudio_initialize_failed_once_when_reopened_again_then_it_initializes_without_terminate(self):
        rec = self._recorder()
        self.sd._initialize = mock.Mock(side_effect=[RuntimeError("no devices"), None])
        with self.assertLogs("claude_stt.recorder", "WARNING"):
            self.assertFalse(rec.reopen())
        # Terminating an uninitialized PortAudio raises paNotInitialized.
        self.sd._terminate = mock.Mock(side_effect=RuntimeError("paNotInitialized"))
        self.assertTrue(rec.reopen())
        self.sd._terminate.assert_not_called()
        self.assertEqual(self.sd._initialize.call_count, 2)

    def test_given_no_sounddevice_when_reopened_then_it_fails_quietly(self):
        rec = self._recorder()
        with mock.patch.object(recorder, "sd", None):
            self.assertFalse(rec.reopen())

    def test_device_name_names_the_configured_device_or_the_default(self):
        self.assertEqual(self._recorder().device_name(), "AirPods")
        self.assertEqual(self._recorder(device=3).device_name(), "Device 3")
        self.sd.query_devices = mock.Mock(side_effect=RuntimeError("gone"))
        self.assertEqual(self._recorder_without_prewarm(device=None).device_name(), "system default input")

    def _recorder_without_prewarm(self, device):
        return AudioRecorder(RecorderConfig(device=device))


if __name__ == "__main__":
    unittest.main()
