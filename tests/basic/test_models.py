import os
import time
import unittest
from unittest.mock import ANY, MagicMock, patch

from aider.models import (
    ANTHROPIC_BETA_HEADER,
    Model,
    ModelInfoManager,
    register_models,
    sanity_check_model,
    sanity_check_models,
)


class TestModels(unittest.TestCase):
    def setUp(self):
        """Reset MODEL_SETTINGS before each test"""
        from aider.models import MODEL_SETTINGS

        self._original_settings = MODEL_SETTINGS.copy()

    def tearDown(self):
        """Restore original MODEL_SETTINGS after each test"""
        from aider.models import MODEL_SETTINGS

        MODEL_SETTINGS.clear()
        MODEL_SETTINGS.extend(self._original_settings)

    def test_get_model_info_nonexistent(self):
        manager = ModelInfoManager()
        info = manager.get_model_info("non-existent-model")
        self.assertEqual(info, {})

    def test_max_context_tokens(self):
        model = Model("gpt-3.5-turbo")
        self.assertEqual(model.info["max_input_tokens"], 16385)

        model = Model("gpt-3.5-turbo-16k")
        self.assertEqual(model.info["max_input_tokens"], 16385)

        model = Model("gpt-3.5-turbo-1106")
        self.assertEqual(model.info["max_input_tokens"], 16385)

        model = Model("gpt-4")
        self.assertEqual(model.info["max_input_tokens"], 8 * 1024)

        model = Model("gpt-4-0613")
        self.assertEqual(model.info["max_input_tokens"], 8 * 1024)

    @patch("os.environ")
    def test_sanity_check_model_all_set(self, mock_environ):
        mock_environ.get.return_value = "dummy_value"
        mock_io = MagicMock()
        model = MagicMock()
        model.name = "test-model"
        model.missing_keys = ["API_KEY1", "API_KEY2"]
        model.keys_in_environment = True
        model.info = {"some": "info"}

        sanity_check_model(mock_io, model)

        mock_io.tool_output.assert_called()
        calls = mock_io.tool_output.call_args_list
        self.assertIn("- API_KEY1: Set", str(calls))
        self.assertIn("- API_KEY2: Set", str(calls))

    @patch("os.environ")
    def test_sanity_check_model_not_set(self, mock_environ):
        mock_environ.get.return_value = ""
        mock_io = MagicMock()
        model = MagicMock()
        model.name = "test-model"
        model.missing_keys = ["API_KEY1", "API_KEY2"]
        model.keys_in_environment = True
        model.info = {"some": "info"}

        sanity_check_model(mock_io, model)

        mock_io.tool_output.assert_called()
        calls = mock_io.tool_output.call_args_list
        self.assertIn("- API_KEY1: Not set", str(calls))
        self.assertIn("- API_KEY2: Not set", str(calls))

    def test_sanity_check_models_bogus_editor(self):
        mock_io = MagicMock()
        main_model = Model("gpt-4")
        main_model.editor_model = Model("bogus-model")

        result = sanity_check_models(mock_io, main_model)

        self.assertTrue(
            result
        )  # Should return True because there's a problem with the editor model
        mock_io.tool_warning.assert_called_with(ANY)  # Ensure a warning was issued

        warning_messages = [
            warning_call.args[0] for warning_call in mock_io.tool_warning.call_args_list
        ]
        print("Warning messages:", warning_messages)  # Add this line

        self.assertGreaterEqual(mock_io.tool_warning.call_count, 1)  # Expect two warnings
        self.assertTrue(
            any("bogus-model" in msg for msg in warning_messages)
        )  # Check that one of the warnings mentions the bogus model

    @patch("aider.models.check_for_dependencies")
    def test_sanity_check_model_calls_check_dependencies(self, mock_check_deps):
        """Test that sanity_check_model calls check_for_dependencies"""
        mock_io = MagicMock()
        model = MagicMock()
        model.name = "test-model"
        model.missing_keys = []
        model.keys_in_environment = True
        model.info = {"some": "info"}

        sanity_check_model(mock_io, model)

        # Verify check_for_dependencies was called with the model name
        mock_check_deps.assert_called_once_with(mock_io, "test-model")

    def test_model_aliases(self):
        # Test common aliases
        model = Model("4")
        self.assertEqual(model.name, "gpt-4-0613")

        model = Model("4o")
        self.assertEqual(model.name, "gpt-4o")

        model = Model("35turbo")
        self.assertEqual(model.name, "gpt-3.5-turbo")

        model = Model("35-turbo")
        self.assertEqual(model.name, "gpt-3.5-turbo")

        model = Model("3")
        self.assertEqual(model.name, "gpt-3.5-turbo")

        model = Model("sonnet")
        self.assertEqual(model.name, "claude-sonnet-4-6")

        model = Model("haiku")
        self.assertEqual(model.name, "claude-haiku-4-5")

        model = Model("opus")
        self.assertEqual(model.name, "claude-opus-4-7")

        # Test non-alias passes through unchanged
        model = Model("gpt-4")
        self.assertEqual(model.name, "gpt-4")

    def test_o1_use_temp_false(self):
        # Test GitHub Copilot models
        model = Model("github/o1-mini")
        self.assertEqual(model.name, "github/o1-mini")
        self.assertEqual(model.use_temperature, False)

        model = Model("github/o1-preview")
        self.assertEqual(model.name, "github/o1-preview")
        self.assertEqual(model.use_temperature, False)

    def test_parse_token_value(self):
        # Create a model instance to test the parse_token_value method
        model = Model("gpt-4")

        # Test integer inputs
        self.assertEqual(model.parse_token_value(8096), 8096)
        self.assertEqual(model.parse_token_value(1000), 1000)

        # Test string inputs
        self.assertEqual(model.parse_token_value("8096"), 8096)

        # Test k/K suffix (kilobytes)
        self.assertEqual(model.parse_token_value("8k"), 8 * 1024)
        self.assertEqual(model.parse_token_value("8K"), 8 * 1024)
        self.assertEqual(model.parse_token_value("10.5k"), 10.5 * 1024)
        self.assertEqual(model.parse_token_value("0.5K"), 0.5 * 1024)

        # Test m/M suffix (megabytes)
        self.assertEqual(model.parse_token_value("1m"), 1 * 1024 * 1024)
        self.assertEqual(model.parse_token_value("1M"), 1 * 1024 * 1024)
        self.assertEqual(model.parse_token_value("0.5M"), 0.5 * 1024 * 1024)

        # Test with spaces
        self.assertEqual(model.parse_token_value(" 8k "), 8 * 1024)

        # Test conversion from other types
        self.assertEqual(model.parse_token_value(8.0), 8)

    def test_set_thinking_tokens(self):
        # Test that set_thinking_tokens correctly sets the tokens with different formats
        model = Model("gpt-4")

        # Test with integer
        model.set_thinking_tokens(8096)
        self.assertEqual(model.extra_params["thinking"]["budget_tokens"], 8096)
        self.assertFalse(model.use_temperature)

        # Test with string
        model.set_thinking_tokens("10k")
        self.assertEqual(model.extra_params["thinking"]["budget_tokens"], 10 * 1024)

        # Test with decimal value
        model.set_thinking_tokens("0.5M")
        self.assertEqual(model.extra_params["thinking"]["budget_tokens"], 0.5 * 1024 * 1024)

    @patch("aider.models.check_pip_install_extra")
    def test_check_for_dependencies_bedrock(self, mock_check_pip):
        """Test that check_for_dependencies calls check_pip_install_extra for Bedrock models"""
        from aider.io import InputOutput

        io = InputOutput()

        # Test with a Bedrock model
        from aider.models import check_for_dependencies

        check_for_dependencies(io, "bedrock/anthropic.claude-3-sonnet-20240229-v1:0")

        # Verify check_pip_install_extra was called with correct arguments
        mock_check_pip.assert_called_once_with(
            io, "boto3", "AWS Bedrock models require the boto3 package.", ["boto3"]
        )

    @patch("aider.models.check_pip_install_extra")
    def test_check_for_dependencies_vertex_ai(self, mock_check_pip):
        """Test that check_for_dependencies calls check_pip_install_extra for Vertex AI models"""
        from aider.io import InputOutput

        io = InputOutput()

        # Test with a Vertex AI model
        from aider.models import check_for_dependencies

        check_for_dependencies(io, "vertex_ai/gemini-1.5-pro")

        # Verify check_pip_install_extra was called with correct arguments
        mock_check_pip.assert_called_once_with(
            io,
            "google.cloud.aiplatform",
            "Google Vertex AI models require the google-cloud-aiplatform package.",
            ["google-cloud-aiplatform"],
        )

    @patch("aider.models.check_pip_install_extra")
    def test_check_for_dependencies_other_model(self, mock_check_pip):
        """Test that check_for_dependencies doesn't call check_pip_install_extra for other models"""
        from aider.io import InputOutput

        io = InputOutput()

        # Test with a non-Bedrock, non-Vertex AI model
        from aider.models import check_for_dependencies

        check_for_dependencies(io, "gpt-4")

        # Verify check_pip_install_extra was not called
        mock_check_pip.assert_not_called()

    def test_get_repo_map_tokens(self):
        # Test default case (no max_input_tokens in info)
        model = Model("gpt-4")
        model.info = {}
        self.assertEqual(model.get_repo_map_tokens(), 1024)

        # Test minimum boundary (max_input_tokens < 8192)
        model.info = {"max_input_tokens": 4096}
        self.assertEqual(model.get_repo_map_tokens(), 1024)

        # Test middle range (max_input_tokens = 16384)
        model.info = {"max_input_tokens": 16384}
        self.assertEqual(model.get_repo_map_tokens(), 2048)

        # Test maximum boundary (max_input_tokens > 32768)
        model.info = {"max_input_tokens": 65536}
        self.assertEqual(model.get_repo_map_tokens(), 4096)

        # Test exact boundary values
        model.info = {"max_input_tokens": 8192}
        self.assertEqual(model.get_repo_map_tokens(), 1024)

        model.info = {"max_input_tokens": 32768}
        self.assertEqual(model.get_repo_map_tokens(), 4096)

    def test_configure_model_settings(self):
        # Test o3-mini case
        model = Model("something/o3-mini")
        self.assertEqual(model.edit_format, "diff")
        self.assertTrue(model.use_repo_map)
        self.assertFalse(model.use_temperature)

        # Test o1-mini case
        model = Model("something/o1-mini")
        self.assertTrue(model.use_repo_map)
        self.assertFalse(model.use_temperature)
        self.assertFalse(model.use_system_prompt)

        # Test o1-preview case
        model = Model("something/o1-preview")
        self.assertEqual(model.edit_format, "diff")
        self.assertTrue(model.use_repo_map)
        self.assertFalse(model.use_temperature)
        self.assertFalse(model.use_system_prompt)

        # Test o1 case
        model = Model("something/o1")
        self.assertEqual(model.edit_format, "diff")
        self.assertTrue(model.use_repo_map)
        self.assertFalse(model.use_temperature)
        self.assertFalse(model.streaming)

        # Test deepseek v3 case
        model = Model("deepseek-v3")
        self.assertEqual(model.edit_format, "diff")
        self.assertTrue(model.use_repo_map)
        self.assertEqual(model.reminder, "sys")
        self.assertTrue(model.examples_as_sys_msg)

        # Test deepseek reasoner case
        model = Model("deepseek-r1")
        self.assertEqual(model.edit_format, "diff")
        self.assertTrue(model.use_repo_map)
        self.assertTrue(model.examples_as_sys_msg)
        self.assertFalse(model.use_temperature)
        self.assertEqual(model.reasoning_tag, "think")

        # Test provider/deepseek-r1 case
        model = Model("someprovider/deepseek-r1")
        self.assertEqual(model.edit_format, "diff")
        self.assertTrue(model.use_repo_map)
        self.assertTrue(model.examples_as_sys_msg)
        self.assertFalse(model.use_temperature)
        self.assertEqual(model.reasoning_tag, "think")

        # Test provider/deepseek-v3 case
        model = Model("anotherprovider/deepseek-v3")
        self.assertEqual(model.edit_format, "diff")
        self.assertTrue(model.use_repo_map)
        self.assertEqual(model.reminder, "sys")
        self.assertTrue(model.examples_as_sys_msg)

        # Test llama3 70b case
        model = Model("llama3-70b")
        self.assertEqual(model.edit_format, "diff")
        self.assertTrue(model.use_repo_map)
        self.assertTrue(model.send_undo_reply)
        self.assertTrue(model.examples_as_sys_msg)

        # Test gpt-4 case
        model = Model("gpt-4")
        self.assertEqual(model.edit_format, "diff")
        self.assertTrue(model.use_repo_map)
        self.assertTrue(model.send_undo_reply)

        # Test gpt-3.5 case
        model = Model("gpt-3.5")
        self.assertEqual(model.reminder, "sys")

        # Test 3.5-sonnet case
        model = Model("claude-3.5-sonnet")
        self.assertEqual(model.edit_format, "diff")
        self.assertTrue(model.use_repo_map)
        self.assertTrue(model.examples_as_sys_msg)
        self.assertEqual(model.reminder, "user")

        # Test o1- prefix case
        model = Model("o1-something")
        self.assertFalse(model.use_system_prompt)
        self.assertFalse(model.use_temperature)

        # Test qwen case
        model = Model("qwen-coder-2.5-32b")
        self.assertEqual(model.edit_format, "diff")
        self.assertEqual(model.editor_edit_format, "editor-diff")
        self.assertTrue(model.use_repo_map)

    def test_aider_extra_model_settings(self):
        import tempfile

        import yaml

        # Create temporary YAML file with test settings
        test_settings = [
            {
                "name": "aider/extra_params",
                "extra_params": {
                    "extra_headers": {"Foo": "bar"},
                    "some_param": "some value",
                },
            },
        ]

        # Write to a regular file instead of NamedTemporaryFile
        # for better cross-platform compatibility
        tmp = tempfile.mktemp(suffix=".yml")
        try:
            with open(tmp, "w") as f:
                yaml.dump(test_settings, f)

            # Register the test settings
            register_models([tmp])

            # Test that defaults are applied when no exact match
            model = Model("claude-3-5-sonnet-20240620")
            # Test that both the override and existing headers are present
            model = Model("claude-3-5-sonnet-20240620")
            self.assertEqual(model.extra_params["extra_headers"]["Foo"], "bar")
            self.assertEqual(
                model.extra_params["extra_headers"]["anthropic-beta"],
                ANTHROPIC_BETA_HEADER,
            )
            self.assertEqual(model.extra_params["some_param"], "some value")
            self.assertEqual(model.extra_params["max_tokens"], 8192)

            # Test that exact match overrides defaults but not overrides
            model = Model("gpt-4")
            self.assertEqual(model.extra_params["extra_headers"]["Foo"], "bar")
            self.assertEqual(model.extra_params["some_param"], "some value")
        finally:
            # Clean up the temporary file
            import os

            try:
                os.unlink(tmp)
            except OSError:
                pass

    @patch("aider.models.litellm.completion")
    @patch.object(Model, "token_count")
    def test_ollama_num_ctx_set_when_missing(self, mock_token_count, mock_completion):
        mock_token_count.return_value = 1000

        model = Model("ollama/llama3")
        messages = [{"role": "user", "content": "Hello"}]

        model.send_completion(messages, functions=None, stream=False)

        # Verify num_ctx was calculated and added to call
        expected_ctx = int(1000 * 1.25) + 8192  # 9442
        mock_completion.assert_called_once_with(
            model=model.name,
            messages=messages,
            stream=False,
            temperature=0,
            num_ctx=expected_ctx,
            timeout=600,
        )

    @patch("aider.models.litellm.completion")
    def test_ollama_uses_existing_num_ctx(self, mock_completion):
        model = Model("ollama/llama3")
        model.extra_params = {"num_ctx": 4096}

        messages = [{"role": "user", "content": "Hello"}]
        model.send_completion(messages, functions=None, stream=False)

        # Should use provided num_ctx from extra_params
        mock_completion.assert_called_once_with(
            model=model.name,
            messages=messages,
            stream=False,
            temperature=0,
            num_ctx=4096,
            timeout=600,
        )

    @patch("aider.models.litellm.completion")
    def test_non_ollama_no_num_ctx(self, mock_completion):
        model = Model("gpt-4")
        messages = [{"role": "user", "content": "Hello"}]

        model.send_completion(messages, functions=None, stream=False)

        # Regular models shouldn't get num_ctx
        mock_completion.assert_called_once_with(
            model=model.name,
            messages=messages,
            stream=False,
            temperature=0,
            timeout=600,
        )
        self.assertNotIn("num_ctx", mock_completion.call_args.kwargs)

    def test_ollama_chat_actually_honors_timeout_real_server(self):
        """
        Regression test for the BUILD_PLAN.md Phase 7 investigation into
        'ollama_chat ignores --timeout': the mocked tests above
        (test_ollama_num_ctx_set_when_missing etc.) only prove aider passes
        timeout=... into the litellm.completion() call -- they mock
        litellm.completion itself, so they can't prove litellm's
        ollama_chat provider actually RESPECTS that value once it gets
        there. Confirmed via litellm issue BerriAI/litellm#8333
        ("ollama_chat/ provider does not honor timeout", closed 2025-06-29)
        that this was a real historical complaint. Re-verified 2026-09-09
        against a real local ollama instance: timeout is honored correctly
        on the current litellm pin. This test proves it with a real
        (unmocked) request rather than just asserting it in a doc comment.

        Skipped automatically if no local ollama server is reachable
        (e.g. in CI, which doesn't run one) -- this is a real-server
        integration check, not something to fake with a mock.
        """
        import socket

        try:
            with socket.create_connection(("localhost", 11434), timeout=1):
                pass
        except OSError:
            self.skipTest("no local ollama server reachable on localhost:11434")

        import subprocess

        try:
            tags = subprocess.run(["ollama", "list"], capture_output=True, text=True, timeout=5)
        except (FileNotFoundError, subprocess.TimeoutExpired):
            self.skipTest("ollama CLI not available to confirm a model is pulled")

        # Use whatever model is actually available locally rather than
        # hardcoding one that may not be pulled on the machine running this.
        available = [
            line.split()[0] for line in tags.stdout.strip().splitlines()[1:] if line.strip()
        ]
        if not available:
            self.skipTest("no ollama models available locally to test against")
        model_name = f"ollama_chat/{available[0]}"

        model = Model(model_name)
        start = time.time()
        with patch("aider.models.request_timeout", 0.01):
            with self.assertRaises(Exception) as ctx:
                model.send_completion(
                    messages=[{"role": "user", "content": "hi"}],
                    functions=None,
                    stream=False,
                    temperature=None,
                )
        elapsed = time.time() - start

        # The real assertion: this must be a real Timeout, and it must
        # have actually cut the request short -- not silently ignored the
        # value and waited for a real response (an absurdly short 0.01s
        # timeout leaves no realistic way for a real generation to
        # complete first, regardless of which model/hardware runs this).
        self.assertIn("timeout", str(ctx.exception).lower())
        self.assertLess(
            elapsed,
            10,
            (
                "timeout does not appear to have been honored -- request ran"
                f" for {elapsed:.1f}s instead of cutting off quickly"
            ),
        )

    def test_is_github_copilot_native(self):
        with (
            patch("aider.models.litellm.get_model_info", return_value={}),
            patch(
                "aider.models.litellm.validate_environment",
                return_value={"keys_in_environment": True, "missing_keys": []},
            ),
        ):
            self.assertTrue(Model("github_copilot/gpt-4o").is_github_copilot_native())
        self.assertFalse(Model("gpt-4o").is_github_copilot_native())
        self.assertFalse(Model("openai/gpt-4o").is_github_copilot_native())
        self.assertFalse(Model("ollama/llama3").is_github_copilot_native())

    def _make_github_copilot_model(self):
        """
        Constructing Model("github_copilot/...") calls BOTH
        litellm.get_model_info() (via ModelInfoManager) AND
        litellm.validate_environment() (via Model.validate_environment,
        since "github_copilot" isn't in fast_validate_environment's
        keymap so it always falls through to the slow litellm-backed
        path) -- both of those specific litellm calls were confirmed
        during Phase 7 scoping to trigger a REAL live GitHub OAuth
        device-flow login for github_copilot/* models, not just look up
        static metadata. Left unmocked, instantiating this model in a
        test hangs waiting for a real interactive device-code approval
        (confirmed the hard way: an earlier version of this test only
        mocked get_model_info and still hung on validate_environment,
        and had to be killed via taskkill). Mock both so Model()
        construction never touches the network or the real
        Authenticator at all.
        """
        with (
            patch("aider.models.litellm.get_model_info", return_value={}),
            patch(
                "aider.models.litellm.validate_environment",
                return_value={"keys_in_environment": True, "missing_keys": []},
            ),
        ):
            return Model("github_copilot/gpt-4o")

    @patch("aider.models.litellm.completion")
    def test_github_copilot_native_gets_required_headers_by_default(self, mock_completion):
        """
        Phase 7 item 1 (BUILD_PLAN.md): litellm's native github_copilot/
        provider (its own OAuth device-flow login, confirmed real and
        working directly against GitHub's API during Phase 7 scoping)
        still requires the same Editor-Version/Copilot-Integration-Id
        headers Copilot's API has always required -- previously these were
        only auto-added for the OLD GITHUB_COPILOT_TOKEN manual-workaround
        path, leaving native-provider users to hand-add them via
        model-settings.yml. Confirms they're now a default for
        github_copilot/ models too, without needing GITHUB_COPILOT_TOKEN
        set at all (litellm's native provider doesn't use that env var).
        """
        self.assertNotIn("GITHUB_COPILOT_TOKEN", os.environ)

        model = self._make_github_copilot_model()
        messages = [{"role": "user", "content": "Hello"}]
        model.send_completion(messages, functions=None, stream=False)

        called_kwargs = mock_completion.call_args.kwargs
        self.assertIn("extra_headers", called_kwargs)
        self.assertEqual(called_kwargs["extra_headers"]["Copilot-Integration-Id"], "vscode-chat")
        self.assertIn("Editor-Version", called_kwargs["extra_headers"])

    @patch("aider.models.litellm.completion")
    def test_github_copilot_native_respects_explicit_extra_headers(self, mock_completion):
        """A user-configured extra_headers (e.g. via model-settings.yml)
        must not be silently overwritten by the new default above."""
        model = self._make_github_copilot_model()
        model.extra_params = {"extra_headers": {"Custom-Header": "custom-value"}}
        messages = [{"role": "user", "content": "Hello"}]
        model.send_completion(messages, functions=None, stream=False)

        called_kwargs = mock_completion.call_args.kwargs
        self.assertEqual(called_kwargs["extra_headers"], {"Custom-Header": "custom-value"})

    @patch("aider.models.litellm.completion")
    def test_non_copilot_model_gets_no_copilot_headers(self, mock_completion):
        model = Model("gpt-4o")
        messages = [{"role": "user", "content": "Hello"}]
        model.send_completion(messages, functions=None, stream=False)

        called_kwargs = mock_completion.call_args.kwargs
        self.assertNotIn("extra_headers", called_kwargs)

    def test_use_temperature_settings(self):
        # Test use_temperature=True (default) uses temperature=0
        model = Model("gpt-4")
        self.assertTrue(model.use_temperature)
        self.assertEqual(model.use_temperature, True)

        # Test use_temperature=False doesn't pass temperature
        model = Model("github/o1-mini")
        self.assertFalse(model.use_temperature)

        # Test use_temperature as float value
        model = Model("gpt-4")
        model.use_temperature = 0.7
        self.assertEqual(model.use_temperature, 0.7)

    @patch("aider.models.litellm.completion")
    def test_request_timeout_default(self, mock_completion):
        # Test default timeout is used when not specified in extra_params
        model = Model("gpt-4")
        messages = [{"role": "user", "content": "Hello"}]
        model.send_completion(messages, functions=None, stream=False)
        mock_completion.assert_called_with(
            model=model.name,
            messages=messages,
            stream=False,
            temperature=0,
            timeout=600,  # Default timeout
        )

    @patch("aider.models.litellm.completion")
    def test_request_timeout_from_extra_params(self, mock_completion):
        # Test timeout from extra_params overrides default
        model = Model("gpt-4")
        model.extra_params = {"timeout": 300}  # 5 minutes
        messages = [{"role": "user", "content": "Hello"}]
        model.send_completion(messages, functions=None, stream=False)
        mock_completion.assert_called_with(
            model=model.name,
            messages=messages,
            stream=False,
            temperature=0,
            timeout=300,  # From extra_params
        )

    @patch("aider.models.litellm.completion")
    def test_use_temperature_in_send_completion(self, mock_completion):
        # Test use_temperature=True sends temperature=0
        model = Model("gpt-4")
        messages = [{"role": "user", "content": "Hello"}]
        model.send_completion(messages, functions=None, stream=False)
        mock_completion.assert_called_with(
            model=model.name,
            messages=messages,
            stream=False,
            temperature=0,
            timeout=600,
        )

        # Test use_temperature=False doesn't send temperature
        model = Model("github/o1-mini")
        messages = [{"role": "user", "content": "Hello"}]
        model.send_completion(messages, functions=None, stream=False)
        self.assertNotIn("temperature", mock_completion.call_args.kwargs)

        # Test use_temperature as float sends that value
        model = Model("gpt-4")
        model.use_temperature = 0.7
        messages = [{"role": "user", "content": "Hello"}]
        model.send_completion(messages, functions=None, stream=False)
        mock_completion.assert_called_with(
            model=model.name,
            messages=messages,
            stream=False,
            temperature=0.7,
            timeout=600,
        )

    def test_gpt_5_5_model_settings(self):
        base_models = [
            "gpt-5.5",
            "gpt-5.5-chat-latest",
            "openai/gpt-5.5",
            "openai/gpt-5.5-chat-latest",
            "azure/gpt-5.5",
            "azure/gpt-5.5-chat-latest",
            "openrouter/openai/gpt-5.5",
            "openrouter/openai/gpt-5.5-chat-latest",
        ]

        for name in base_models:
            with self.subTest(name=name):
                model = Model(name)
                self.assertEqual(model.edit_format, "diff")
                self.assertTrue(model.use_repo_map)
                self.assertFalse(model.use_temperature)
                self.assertIn("reasoning_effort", model.accepts_settings)

        self.assertTrue(Model("gpt-5.5").overeager)

        pro_models = {
            "gpt-5.5-pro": "gpt-5.5",
            "openai/gpt-5.5-pro": "openai/gpt-5.5",
            "azure/gpt-5.5-pro": "azure/gpt-5.5",
            "openrouter/openai/gpt-5.5-pro": "openrouter/openai/gpt-5.5",
        }

        for name, editor_name in pro_models.items():
            with self.subTest(name=name):
                model = Model(name)
                self.assertFalse(model.streaming)
                self.assertEqual(model.edit_format, "diff")
                self.assertTrue(model.use_repo_map)
                self.assertFalse(model.use_temperature)
                self.assertEqual(model.editor_model_name, editor_name)
                self.assertEqual(model.editor_model.name, editor_name)
                self.assertIn("reasoning_effort", model.accepts_settings)


if __name__ == "__main__":
    unittest.main()
