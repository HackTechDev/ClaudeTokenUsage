"""Tests du chargement de la configuration."""
import contextlib, io, sys, tempfile, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from claude_usage import DEFAULT_CONFIG, load_config


class LoadConfigTest(unittest.TestCase):
    def load(self, content):
        with tempfile.NamedTemporaryFile("w", suffix=".toml", delete=False) as f:
            f.write(content)
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            config = load_config(f.name)
        Path(f.name).unlink()
        return config, stderr.getvalue()

    def test_missing_file_gives_defaults(self):
        self.assertEqual(load_config("/inexistant/config.toml"), DEFAULT_CONFIG)

    def test_values_override_defaults(self):
        config, err = self.load("refresh_interval = 120\nwarn_threshold = 60\n")
        self.assertEqual((config["refresh_interval"], config["warn_threshold"], config["crit_threshold"]),
                         (120, 60, 90))
        self.assertEqual(err, "")

    def test_invalid_entries_are_ignored_with_warning(self):
        config, err = self.load('warn_threshold = "beaucoup"\ncouleur = "bleu"\n')
        self.assertEqual(config, DEFAULT_CONFIG)
        self.assertIn("warn_threshold", err)
        self.assertIn("couleur", err)

    def test_broken_toml_gives_defaults(self):
        config, err = self.load("refresh_interval = \n")
        self.assertEqual(config, DEFAULT_CONFIG)
        self.assertIn("Configuration ignorée", err)

    def test_interval_minimum(self):
        self.assertEqual(self.load("refresh_interval = 1\n")[0]["refresh_interval"], 10)


if __name__ == "__main__":
    unittest.main()
