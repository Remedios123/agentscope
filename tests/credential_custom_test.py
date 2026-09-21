# -*- coding: utf-8 -*-
"""Tests for the custom OpenAI-compatible credential."""
# pylint: disable=missing-function-docstring
import unittest

from agentscope.credential import CustomCredential, CredentialFactory


class CustomCredentialTest(unittest.TestCase):
    """models_text parsing and factory round-trip."""

    def _credential(self, models_text: str) -> CustomCredential:
        return CustomCredential(
            api_key="sk-test",
            base_url="https://gw.example.com/v1",
            models_text=models_text,
        )

    def test_models_text_parses_to_cards(self) -> None:
        credential = self._credential(
            "ep-abc | TokenHub Main\n\n  ep-def  |  备用模型  \nep-ghi\n",
        )
        cards = credential.list_models_for()
        self.assertEqual(
            [c.name for c in cards],
            ["ep-abc", "ep-def", "ep-ghi"],
        )
        self.assertEqual(
            [c.label for c in cards],
            ["TokenHub Main", "备用模型", "ep-ghi"],
        )
        for card in cards:
            self.assertEqual(card.status, "active")
            self.assertEqual(card.context_size, 128000)
            self.assertEqual(card.output_size, 16384)
            # Parameter schema mirrors the OpenAI chat parameters so the
            # popover renders real, model-appropriate controls.
            self.assertIn("temperature", card.parameter_schema["properties"])

    def test_blank_models_text_yields_no_cards(self) -> None:
        self.assertEqual(self._credential("").list_models_for(), [])
        self.assertEqual(self._credential("\n \n").list_models_for(), [])

    def test_label_only_lines_are_skipped(self) -> None:
        # A line without a model id cannot address a model.
        cards = self._credential("ep-abc\n| orphan\n").list_models_for()
        self.assertEqual([c.name for c in cards], ["ep-abc"])

    def test_context_size_advertises_on_cards(self) -> None:
        credential = CustomCredential(
            api_key="sk-test",
            base_url="https://gw.example.com/v1",
            context_size=32000,
            models_text="m1",
        )
        card = credential.list_models_for()[0]
        self.assertEqual(card.context_size, 32000)
        self.assertEqual(card.output_size, 16384)

    def test_factory_round_trip(self) -> None:
        data = {
            "type": "custom_credential",
            "name": "TokenHub",
            "api_key": "sk-test",
            "base_url": "https://gw.example.com/v1",
            "models_text": "ep-abc | TokenHub",
        }
        credential = CredentialFactory.from_dict(data)
        self.assertIsInstance(credential, CustomCredential)
        self.assertEqual(credential.list_models_for()[0].name, "ep-abc")
        # The custom type shows up in the schema-driven credential form.
        types = [
            s["properties"]["type"]["const"]
            for s in CredentialFactory.list_schemas()
        ]
        self.assertIn("custom_credential", types)

    def test_base_instance_hook_defaults_to_none(self) -> None:
        from agentscope.credential import CredentialBase

        credential = CustomCredential(
            api_key="sk-test",
            base_url="https://gw.example.com/v1",
        )
        # The base hook is the fallback signal; custom overrides it.
        self.assertIsNone(CredentialBase.list_models_for(credential))
        self.assertIsNotNone(credential.list_models_for())


if __name__ == "__main__":
    unittest.main()
