import unittest

from app.backend.services.model_adapters.openai_compatible import NoRedirectHandler


class ModelAdapterRedirectTests(unittest.TestCase):
    def test_redirects_are_not_followed(self) -> None:
        handler = NoRedirectHandler()

        redirected = handler.redirect_request(
            None,
            None,
            302,
            "Found",
            {},
            "https://attacker.example/v1/chat/completions",
        )

        self.assertIsNone(redirected)


if __name__ == "__main__":
    unittest.main()
