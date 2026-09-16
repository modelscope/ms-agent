# Copyright (c) Alibaba, Inc. and its affiliates.
"""Content-driven outbound secret redaction tests (BUG-0909-01).

The framework ``sanitize_outbound_file`` hooks select files by PATH, so a key
left in ``skills/*``, a persona document or a memory file used to be uploaded
verbatim. These tests pin the replacement layer: what it must catch, what it
must leave alone (documentation is full of secret-shaped placeholders), and the
byte-identity / idempotency contract the sync paths depend on.
"""
import base64
import json
import unittest

from ms_agent.agent_hub._secrets import (Finding, name_strength,
                                         redact_outbound, redact_text)

SK_KEY = "sk-S26ProseLeak0001"
GH_PAT = "ghp_S25bPatLeak7x9Qm2Rt4Vw"
JWT = ("eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0."
       "dOJvBm9vS2VyXzEyMzQ1Njc")
B64_KEY = base64.b64encode(b"sk-S28B64Leak0001").decode()


class TestVendorTokenPatterns(unittest.TestCase):
    """Decisive vendor prefixes are redacted wherever they appear."""

    def _assert_redacted(self, text, kind="api_key"):
        out, hits = redact_text(text)
        self.assertNotIn(SK_KEY, out)
        self.assertIn("[REDACTED:", out)
        self.assertTrue(hits)
        self.assertEqual(hits[0][0], kind)
        return out

    def test_sk_key_in_prose(self):
        self._assert_redacted(f"调用 API 时使用 {SK_KEY} 作为密钥。")

    def test_sk_key_in_python_assignment(self):
        out = self._assert_redacted(f'API_KEY = "{SK_KEY}"')
        self.assertIn('API_KEY = "[REDACTED:api_key]"', out)

    def test_sk_key_in_shell_export(self):
        self._assert_redacted(f"export DASHSCOPE_API_KEY={SK_KEY}")

    def test_every_vendor_prefix_is_redacted(self):
        """One case per branch of the vendor alternation."""
        samples = (
            ("openai", "sk-Pr0jK3yAbCdEfGhIjKlMn"),
            ("anthropic", "sk-ant-api03-AbCdEfGhIjKlMnOpQr"),
            ("github_pat", "ghp_S25bPatLeak7x9Qm2Rt4Vw"),
            ("github_fine", "github_pat_11ABCDEFGH0XyZ9QwErTyUiOpAsDf"),
            ("gitlab", "glpat-Xy7Zk2Mn9Pq4Rt6W"),
            # Split literal: push protection rejects a contiguous Slack-token
            # shape in source even when the fixture is fake.
            ("slack", "xox" + "b-987654321098-AbCdEfGhIjKl"),
            ("aws", "AKIAI3F0DNN7EXA1B2C4"),
            ("google", "AIzaSyA1b2C3d4E5f6G7h8I9j0K"),
            ("huggingface", "hf_XyZ1a2B3c4D5e6F7g8H9"),
            ("npm", "npm_XyZ1a2B3c4D5e6F7g8H9"),
            ("shopify", "shpat_XyZ1a2B3c4D5e6F7g8H9"),
        )
        for label, token in samples:
            with self.subTest(vendor=label):
                out, hits = redact_text(f"credential = {token}")
                self.assertNotIn(token, out)
                self.assertIn("[REDACTED:api_key]", out)
                self.assertTrue(hits)

    def test_jwt(self):
        out, hits = redact_text(f"token: {JWT}")
        self.assertNotIn(JWT, out)
        self.assertIn("[REDACTED:jwt]", out)
        self.assertEqual(hits[0][0], "jwt")

    def test_bearer_header_in_curl(self):
        out, hits = redact_text(
            f'curl -H "Authorization: Bearer {SK_KEY}" https://api.example.com')
        self.assertNotIn(SK_KEY, out)
        self.assertTrue(hits)

    def test_sk_prefix_needs_a_left_boundary(self):
        """``sk-`` inside an ordinary word is not a credential."""
        for text in ("task-tracking pipeline", "<task-notification>ping",
                     "risk-assessment model"):
            out, hits = redact_text(text)
            self.assertEqual(out, text, text)
            self.assertEqual(hits, ())

    def test_bearer_is_case_sensitive(self):
        """Lowercase "bearer" is prose, not an Authorization header."""
        text = ("HTTP headers are bearer credentials in disguise; "
                "see the bearer endpoint docs.")
        out, hits = redact_text(text)
        self.assertEqual(out, text)
        self.assertEqual(hits, ())


class TestBase64Payload(unittest.TestCase):
    """A persona instruction to decode a credential at runtime."""

    def test_blob_decoding_to_a_key_is_redacted(self):
        text = f'    echo "{B64_KEY}" | base64 -d'
        out, hits = redact_text(text)
        self.assertNotIn(B64_KEY, out)
        self.assertIn("[REDACTED:base64]", out)
        self.assertEqual(hits[0][0], "base64")

    def test_non_secret_blobs_are_kept(self):
        """Benign text, a hex digest (decodes to binary) and a data URI."""
        benign = base64.b64encode(b"hello world, this is fine").decode()
        digest = ("d4735e3a265e16eee03f59718b9b5d03"
                  "019c07d8b6c51f90da3a666eec13ab35")
        png = base64.b64encode(b"PNGDATA" * 12).decode()
        cases = (
            f"echo {benign} | base64 -d",
            f"commit {digest} is the release",
            f"![img](data:image/png;base64,{png})",
        )
        for text in cases:
            with self.subTest(text=text[:40]):
                out, hits = redact_text(text)
                self.assertEqual(out, text)
                self.assertEqual(hits, ())


class TestDocumentedPlaceholdersSurvive(unittest.TestCase):
    """The false-positive gate: docs are full of secret-shaped non-secrets.

    Every case here is real content taken from this repo's docs, the framework
    default templates and converted third-party agent packages.
    """

    CLEAN = (
        # variable references / template placeholders
        'Use `os.environ["DASHSCOPE_API_KEY"]` to read the key.',
        "Pass `--api-key <YOUR_KEY>` on the command line.",
        "curl -H \"Authorization: Bearer $TOKEN\" https://api.example.com/v1",
        'export API_KEY="<your-key-here>"',
        "api_key = ${DASHSCOPE_API_KEY}",
        "headers = {'Authorization': f'Bearer {api_key}'}",
        "url: https://gateway.example.com/v1?access_token=${token}",
        "password = keyvaultref:$SECRET_URI",
        "DB_PASSWORD = secretref:db-password",
        # identifier-shaped values, not credentials
        "apiKey = SendGridApiKey",
        "api_key = MySecretValue123",
        "page_token = options?.pageToken",
        "credential = Invoke-MgGraphRequest",
        "session_id = self.runtime.session_id",
        "SECTION_KEY = personalization",
        # documentation URLs and examples
        "postgresql+asyncpg://user:pass@localhost/db",
        "base_url: https://dashscope.aliyuncs.com/compatible-mode/v1",
        "See https://example.com/docs?api_key=&model=qwen3-max",
        # placeholder spellings
        "OPENAI_API_KEY=sk-xxxxxxxxxxxxxxxxxxxx",
        "api_key: sk-your-key-here",
        'token = "changeme123456"',
        # data fields that are NOT credentials
        '{"usage": {"tokens": 1234, "keys": ["a"]}}',
        "max_tokens: 4096",
        "page_token: CaESBgoGEgQiBw",
        '{"key": "user_profile_2"}',
        # prose
        "You are a helpful weather assistant. Query the forecast API.",
    )

    def test_clean_content_is_untouched(self):
        for text in self.CLEAN:
            with self.subTest(text=text):
                out, hits = redact_text(text)
                self.assertEqual(out, text)
                self.assertEqual(hits, ())


class TestNameStrength(unittest.TestCase):
    """Which key names may drive a redaction, and how hard they push."""

    def test_qualified_credential_names_are_strong(self):
        for name in ("api_key", "apiKey", "model.api_key", "--auth-token",
                     "GITHUB_TOKEN", "db_password", "smtp_passwd",
                     "client_secret", "access_token", "OPENWEATHER_KEY"):
            with self.subTest(name=name):
                self.assertEqual(name_strength(name), 2)

    def test_bare_singular_names_are_weak(self):
        for name in ("key", "token", "secret", "password", "credential"):
            with self.subTest(name=name):
                self.assertEqual(name_strength(name), 1)

    def test_data_and_metadata_names_never_trigger(self):
        for name in ("max_tokens", "min_tokens", "total_tokens", "page_token",
                     "next_token", "continuation_token", "session_id",
                     "request_id", "trace_id", "tokens", "keys", "key_id",
                     "key_name", "token_type", "secret_name", "options.pageToken",
                     "id", "name", "description", "model", "base_url"):
            with self.subTest(name=name):
                self.assertEqual(name_strength(name), 0)


class TestWeakNameValueGate(unittest.TestCase):
    """A bare ``key``/``token`` only fires on a credential-shaped value."""

    def test_memory_note_credential_is_redacted(self):
        out, hits = redact_text("- gateway token: S42bMemTokenLeak01")
        self.assertNotIn("S42bMemTokenLeak01", out)
        self.assertEqual(hits[0][0], "credential")
        self.assertEqual(hits[0][2], "token")

    def test_documented_flag_value_is_redacted(self):
        out, hits = redact_text(
            "python leak_point.py --token S25dFlagValLeak01")
        self.assertNotIn("S25dFlagValLeak01", out)
        self.assertEqual(hits[0][0], "flag")

    def test_data_mapping_value_survives(self):
        for text in ('{"key": "user_profile_2"}', '{"token": "session_a1b2"}',
                     "key: lowercase_snake_value_9"):
            with self.subTest(text=text):
                out, hits = redact_text(text)
                self.assertEqual(out, text)
                self.assertEqual(hits, ())


class TestUrlCredentials(unittest.TestCase):
    """URL credentials in free text, with the lenient value gate."""

    def test_secret_query_parameter_is_blanked_name_kept(self):
        out, hits = redact_text(
            "url: https://api.example.com/v1?api_key=S34bDocUrlLeak01&m=1")
        self.assertNotIn("S34bDocUrlLeak01", out)
        self.assertIn("api_key=[REDACTED:api_key]", out)
        self.assertIn("&m=1", out)
        self.assertEqual(hits[0][2], "api_key")

    def test_userinfo_password_is_redacted(self):
        out, _ = redact_text("git clone https://user:Sup3rS3cretPass99@h/r")
        self.assertNotIn("Sup3rS3cretPass99", out)
        self.assertIn("user:[REDACTED:password]@h/r", out)

    def test_bare_userinfo_token_is_redacted(self):
        out, _ = redact_text("git clone https://ghp_AbCdEfG7h9IjK2LmNo@h/r")
        self.assertNotIn("ghp_AbCdEfG7h9IjK2LmNo", out)

    def test_documented_urls_survive(self):
        """A doc example password and a variable-reference query value."""
        for text in ("postgresql+asyncpg://user:pass@localhost/db",
                     "https://gateway.example.com/v1?access_token=${token}"):
            with self.subTest(text=text):
                out, hits = redact_text(text)
                self.assertEqual(out, text)
                self.assertEqual(hits, ())

    def test_trailing_punctuation_is_not_swallowed(self):
        out, _ = redact_text(
            f"See https://h/v1?api_key=S34bDocUrlLeak01.")
        self.assertTrue(out.endswith("."))
        self.assertNotIn("S34bDocUrlLeak01", out)


class TestTierAConfigShapedFiles(unittest.TestCase):
    """Structural cleaning by name or shape, at ANY path."""

    def _out(self, rel, text):
        raw = text.encode("utf-8")
        cleaned, hits = redact_outbound(rel, raw)
        return cleaned.decode("utf-8"), hits

    def test_skill_local_mcp_json_is_scrubbed(self):
        payload = json.dumps({
            "mcpServers": {
                "weather": {
                    "command": "uvx",
                    "args": ["-y", "srv", "--api-key", "S32bArgValLeak001"],
                    "env": {
                        "OPENWEATHER_KEY": "S32EnvKeyLeak0001"
                    },
                    "url": "https://api.example.com/v1?api_key=S33UrlKeyLeak01",
                }
            }
        })
        out, hits = self._out("skills/weather/mcp.json", payload)
        data = json.loads(out)
        server = data["mcpServers"]["weather"]
        self.assertEqual(server["env"], {"OPENWEATHER_KEY": ""})
        self.assertIn("api_key=", server["url"])
        self.assertNotIn("S33UrlKeyLeak01", server["url"])
        self.assertNotIn("S32bArgValLeak001", out)
        self.assertEqual(hits[0].kind, "config")

    def test_mcp_shape_triggers_scrub_under_any_filename(self):
        """The scrubber 'knows' this format, so the filename must not matter."""
        payload = json.dumps({
            "name": "weather",
            "mcpServers": {
                "w": {
                    "env": {
                        "KEY": "S34DocEnvLeak0001"
                    }
                }
            },
        })
        out, hits = self._out("skills/weather/tools.json", payload)
        self.assertNotIn("S34DocEnvLeak0001", out)
        self.assertTrue(hits)

    def test_skill_config_yaml_is_scrubbed(self):
        text = ("name: weather\n"
                "mcp_servers:\n"
                "  weather:\n"
                "    env:\n"
                "      OPENWEATHER_KEY: S35YamlEnvLeak01\n"
                "    url: https://api.example.com/v1?api_key=S35bYamlUrl01\n")
        out, hits = self._out("skills/weather/config.yaml", text)
        self.assertNotIn("S35YamlEnvLeak01", out)
        self.assertNotIn("S35bYamlUrl01", out)
        self.assertIn("OPENWEATHER_KEY: ''", out)
        self.assertEqual(hits[0].kind, "config")

    def test_skill_config_toml_is_scrubbed(self):
        text = ('[mcp_servers.weather]\ncommand = "uvx"\n'
                '[mcp_servers.weather.env]\nOPENWEATHER_KEY = "S36TomlEnv01"\n')
        out, hits = self._out("skills/weather/config.toml", text)
        self.assertNotIn("S36TomlEnv01", out)
        self.assertTrue(hits)

    def test_arbitrary_json_data_file_is_not_structurally_scrubbed(self):
        """``tokens`` / ``keys`` are data fields; only the MCP subtree is
        eligible for the bag rules."""
        payload = json.dumps({
            "usage": {
                "tokens": 12345,
                "keys": ["alpha", "beta"]
            },
            "key": "user_profile_2",
        })
        raw = payload.encode("utf-8")
        cleaned, hits = redact_outbound("skills/x/data/usage.json", raw)
        self.assertIs(cleaned, raw)
        self.assertEqual(hits, ())

    def test_mcp_subtree_scrub_leaves_the_rest_of_the_document(self):
        payload = json.dumps({
            "usage": {
                "tokens": 12345
            },
            "mcpServers": {
                "w": {
                    "env": {
                        "K": "S37MixedLeak00001"
                    }
                }
            },
        })
        out, _ = self._out("skills/x/tools.json", payload)
        data = json.loads(out)
        self.assertEqual(data["usage"], {"tokens": 12345})
        self.assertEqual(data["mcpServers"]["w"]["env"], {"K": ""})

    def test_malformed_non_config_json_does_not_raise(self):
        """A broken data fixture falls through to the text pass instead of
        blocking the upload (the framework hook already fails closed for the
        ROOT config files it owns)."""
        raw = b'{"sources": [,,,'
        cleaned, hits = redact_outbound("skills/x/broken.json", raw)
        self.assertIs(cleaned, raw)
        self.assertEqual(hits, ())

    def test_secret_in_malformed_config_json_is_still_redacted(self):
        raw = ('{"mcpServers": {"w": {"env": {"K": "%s"}},,,' % SK_KEY).encode()
        cleaned, hits = redact_outbound("skills/x/broken.json", raw)
        self.assertNotIn(SK_KEY, cleaned.decode("utf-8"))
        self.assertTrue(hits)


class TestRedactOutboundContract(unittest.TestCase):
    """The invariants the sync paths rely on."""

    def test_clean_content_returns_the_original_bytes_object(self):
        """``drop_unchanged_defaults`` compares bytes and ``push_mirror`` skips
        by sha256, so an untouched file must not be re-serialized."""
        raw = b"# Persona\n\nYou are a helpful assistant.\n"
        cleaned, hits = redact_outbound("SOUL.md", raw)
        self.assertIs(cleaned, raw)
        self.assertEqual(hits, ())

    def test_non_utf8_binary_passes_through(self):
        raw = b"\x89PNG\r\n\x1a\n" + bytes(range(256))
        cleaned, hits = redact_outbound("skills/x/assets/logo.png", raw)
        self.assertIs(cleaned, raw)
        self.assertEqual(hits, ())

    def test_redaction_is_idempotent(self):
        text = (f"key = {SK_KEY}\n"
                f"curl -H 'Authorization: Bearer {SK_KEY}'\n"
                f"url: https://h/v1?api_key=S34bDocUrlLeak01\n"
                f"export GITHUB_TOKEN={GH_PAT}\n")
        once, hits1 = redact_text(text)
        twice, hits2 = redact_text(once)
        self.assertEqual(twice, once)
        self.assertTrue(hits1)
        self.assertEqual(hits2, ())

    def test_outbound_redaction_is_idempotent(self):
        raw = f"API_KEY = '{SK_KEY}'".encode("utf-8")
        first, hits1 = redact_outbound("skills/x/run.py", raw)
        second, hits2 = redact_outbound("skills/x/run.py", first)
        self.assertEqual(second, first)
        self.assertTrue(hits1)
        self.assertEqual(hits2, ())

    def test_findings_never_carry_the_secret(self):
        raw = f"api_key = {SK_KEY}".encode("utf-8")
        _cleaned, hits = redact_outbound("skills/x/env.sh", raw)
        for finding in hits:
            self.assertIsInstance(finding, Finding)
            self.assertEqual(finding.rel, "skills/x/env.sh")
            for field in finding:
                self.assertNotIn(SK_KEY, str(field))

    def test_jsonl_history_keeps_cursors_and_drops_keys(self):
        """nanobot ``memory/history.jsonl`` mixes pagination cursors with
        credentials; only the credential may go."""
        line1 = json.dumps({"page_token": "CaESBgoGEgQiBw", "text": "hi"})
        line2 = json.dumps({"api_key": SK_KEY, "text": "bye"})
        raw = f"{line1}\n{line2}\n".encode("utf-8")
        cleaned, hits = redact_outbound("memory/history.jsonl", raw)
        text = cleaned.decode("utf-8")
        self.assertIn("CaESBgoGEgQiBw", text)
        self.assertNotIn(SK_KEY, text)
        self.assertTrue(hits)

    def test_never_raises_on_hostile_input(self):
        """The watch daemon swallows exceptions and keeps polling, so a raise
        here would silently stop all syncing."""
        hostile = (
            b"\xff\xfe\x00binary",
            b"",
            b"=" * 5000,
            b"[]" * 2000,
            b"sk-" * 500,
            json.dumps({"a": ["b" * 300]}).encode(),
            ("key = " + "A1" * 400).encode(),
        )
        for raw in hostile:
            with self.subTest(raw=raw[:24]):
                cleaned, _hits = redact_outbound("skills/x/any.md", raw)
                self.assertIsInstance(cleaned, bytes)

    def test_memo_returns_the_callers_object_for_clean_content(self):
        """Two frameworks ship a byte-identical SOUL.md template, so the memo
        is hit with equal content but a different bytes object."""
        text = "# Persona\n\nNothing secret here.\n".encode("utf-8")
        first, _ = redact_outbound("SOUL.md", text)
        second, _ = redact_outbound("SOUL.md", bytes(text))
        self.assertIs(second, text)
        self.assertEqual(first, text)


if __name__ == "__main__":
    unittest.main()
