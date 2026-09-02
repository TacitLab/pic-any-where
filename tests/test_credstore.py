import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

from pawlib import credstore


class FakeBackend(credstore.KeychainBackend):
    name = "fake"
    store = {}

    def available(self):
        return True

    def get(self, profile):
        return self.store.get(profile)

    def set(self, profile, data):
        self.store[profile] = data

    def delete(self, profile):
        self.store.pop(profile, None)


class ResolveTest(unittest.TestCase):
    def setUp(self):
        FakeBackend.store = {}

    def _profile(self, **kw):
        p = {"_name": "main"}
        p.update(kw)
        return p

    def test_env_paw_wins(self):
        env = {"PAW_ACCESS_KEY_ID": "PAWAK", "PAW_SECRET_ACCESS_KEY": "PAWSK",
               "AWS_ACCESS_KEY_ID": "AWSAK", "AWS_SECRET_ACCESS_KEY": "AWSSK"}
        creds = credstore.resolve_credentials(self._profile(), env=env)
        self.assertEqual(creds.access_key, "PAWAK")
        self.assertEqual(creds.source, "环境变量 PAW_*")

    def test_env_aws_fallback_with_token(self):
        env = {"AWS_ACCESS_KEY_ID": "AWSAK", "AWS_SECRET_ACCESS_KEY": "AWSSK",
               "AWS_SESSION_TOKEN": "TOK"}
        creds = credstore.resolve_credentials(self._profile(), env=env)
        self.assertEqual(creds.session_token, "TOK")

    def test_keychain_used_when_no_env(self):
        with mock.patch.object(credstore, "get_backend", return_value=FakeBackend()):
            FakeBackend.store["main"] = {"access_key": "KCAK", "secret_key": "KCSK"}
            creds = credstore.resolve_credentials(self._profile(), env={})
        self.assertEqual(creds.access_key, "KCAK")
        self.assertIn("钥匙串", creds.source)

    def test_env_beats_keychain(self):
        with mock.patch.object(credstore, "get_backend", return_value=FakeBackend()):
            FakeBackend.store["main"] = {"access_key": "KCAK", "secret_key": "KCSK"}
            env = {"PAW_ACCESS_KEY_ID": "ENVAK", "PAW_SECRET_ACCESS_KEY": "ENVSK"}
            creds = credstore.resolve_credentials(self._profile(), env=env)
        self.assertEqual(creds.access_key, "ENVAK")

    def test_no_credentials_raises_with_guidance(self):
        with mock.patch.object(credstore, "get_backend", return_value=None), \
                mock.patch.object(credstore, "_from_aws_credentials_file",
                                  return_value=None):
            with self.assertRaises(credstore.CredentialError) as ctx:
                credstore.resolve_credentials(self._profile(), env={})
        self.assertIn("config set-credential", str(ctx.exception))

    def test_inline_requires_explicit_opt_in(self):
        with mock.patch.object(credstore, "get_backend", return_value=None), \
                mock.patch.object(credstore, "_from_aws_credentials_file",
                                  return_value=None):
            p = self._profile(access_key="AK", secret_key="SK",
                              allow_file_credentials=True)
            creds = credstore.resolve_credentials(p, env={})
            self.assertEqual(creds.access_key, "AK")
            # 未开启 allow_file_credentials 时同样字段不生效
            p2 = self._profile(access_key="AK", secret_key="SK")
            with self.assertRaises(credstore.CredentialError):
                credstore.resolve_credentials(p2, env={})


class AwsFileTest(unittest.TestCase):
    def test_parse_aws_credentials(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake_home = os.path.join(tmp, "home")
            os.makedirs(os.path.join(fake_home, ".aws"))
            with open(os.path.join(fake_home, ".aws", "credentials"), "w") as f:
                f.write("[default]\naws_access_key_id = FILEAK\n"
                        "aws_secret_access_key = FILESK\n")
            with mock.patch.dict(os.environ, {"HOME": fake_home}), \
                    mock.patch("pawlib.credstore.os.path.expanduser",
                               lambda p: p.replace("~", fake_home)):
                creds = credstore._from_aws_credentials_file("default")
            self.assertEqual(creds.access_key, "FILEAK")
            self.assertIsNone(creds.session_token)


class MiscTest(unittest.TestCase):
    def test_redact(self):
        self.assertEqual(credstore.redact("AKIDEXAMPLE"), "AKID****")
        self.assertEqual(credstore.redact(None), "(未配置)")
        self.assertEqual(credstore.redact("abc"), "****")

    def test_store_without_backend_raises(self):
        with mock.patch.object(credstore, "get_backend", return_value=None):
            with self.assertRaises(credstore.CredentialError):
                credstore.store_credentials("p", "ak", "sk")

    def test_store_roundtrip_via_backend(self):
        backend = FakeBackend()
        with mock.patch.object(credstore, "get_backend", return_value=backend):
            name = credstore.store_credentials("p", "ak", "sk", "tok")
            self.assertEqual(name, "fake")
            self.assertEqual(backend.get("p")["session_token"], "tok")


if __name__ == "__main__":
    unittest.main()
