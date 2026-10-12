"""配置隔离与客户端接线；使用合成凭据，不读取真实 .env。"""
import os
import unittest
from unittest.mock import patch

from supportpilot.config import admin_usernames, load_chat_config, load_embedding_config


class ConfigTests(unittest.TestCase):
    def test_environment_overrides_file_without_mutating_process(self):
        with patch.dict(os.environ, {"API_KEY": "process-test"}, clear=True), \
             patch("supportpilot.config.dotenv_values", return_value={
                 "API_KEY": "file-test", "SUPPORTPILOT_CHAT_MODEL": "synthetic-model",
                 "SUPPORTPILOT_ADMIN_USERS": "file-admin"}):
            config = load_chat_config()
            self.assertEqual(config.api_key, "process-test")
            self.assertEqual(config.model, "synthetic-model")
            self.assertNotIn("process-test", repr(config))
            self.assertNotIn("SUPPORTPILOT_CHAT_MODEL", os.environ)
            self.assertEqual(admin_usernames(), frozenset())

    def test_embedding_key_fallback_and_independent_key(self):
        with patch.dict(os.environ, {"API_KEY": "fallback-test"}, clear=True), \
             patch("supportpilot.config.dotenv_values", return_value={}):
            self.assertEqual(load_embedding_config().api_key, "fallback-test")
            with patch.dict(os.environ, {"SUPPORTPILOT_EMBEDDING_API_KEY": "embedding-test"}):
                config = load_embedding_config()
                self.assertEqual(config.api_key, "embedding-test")
                self.assertNotIn("embedding-test", repr(config))

    def test_client_defaults_and_explicit_overrides(self):
        from supportpilot.providers.bailian import bailian
        from supportpilot.knowledge.rag_support import make_embedder
        with patch.dict(os.environ, {"API_KEY": "synthetic", "SUPPORTPILOT_EMBEDDING_BASE_URL": "https://example.invalid/v1"}, clear=True), \
             patch("supportpilot.config.dotenv_values", return_value={}), \
             patch("supportpilot.providers.bailian.ChatOpenAI") as chat, \
             patch("openai.OpenAI") as embeddings:
            bailian()
            self.assertEqual(chat.call_args.kwargs["timeout"], 60)
            self.assertEqual(chat.call_args.kwargs["max_retries"], 0)
            bailian(timeout=12, max_retries=2)
            self.assertEqual(chat.call_args.kwargs["timeout"], 12)
            self.assertEqual(chat.call_args.kwargs["max_retries"], 2)
            embedder = make_embedder()
            self.assertEqual(embedder.dimensions, 1024)
            self.assertEqual(embeddings.call_args.kwargs["max_retries"], 1)

    def test_missing_embedding_configuration_fails_before_client_creation(self):
        from supportpilot.knowledge.rag_support import make_embedder
        with patch.dict(os.environ, {}, clear=True), \
             patch("supportpilot.config.dotenv_values", return_value={}), \
             patch("openai.OpenAI") as client:
            with self.assertRaises(ValueError):
                make_embedder()
            client.assert_not_called()

    def test_admin_names_are_normalized(self):
        with patch.dict(os.environ, {"SUPPORTPILOT_ADMIN_USERS": " Admin, ,ADMIN, Other "}, clear=True):
            self.assertEqual(admin_usernames(), frozenset({"admin", "other"}))
