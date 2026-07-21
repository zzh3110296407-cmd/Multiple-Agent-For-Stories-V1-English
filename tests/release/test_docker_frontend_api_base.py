import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


class DockerFrontendApiBaseTests(unittest.TestCase):
    def test_docker_build_uses_origin_root_as_api_base(self) -> None:
        compose = (REPO_ROOT / "docker-compose.yml").read_text(encoding="utf-8")
        dockerfile = (REPO_ROOT / "docker" / "frontend.Dockerfile").read_text(
            encoding="utf-8"
        )

        self.assertIn("VITE_API_BASE_URL: /", compose)
        self.assertNotIn("VITE_API_BASE_URL: /api", compose)
        self.assertIn("ARG VITE_API_BASE_URL=/", dockerfile)
        self.assertNotIn("ARG VITE_API_BASE_URL=/api", dockerfile)


if __name__ == "__main__":
    unittest.main()
