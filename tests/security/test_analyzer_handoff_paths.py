import tempfile
import unittest
from pathlib import Path

from app.backend.services.analyzer_handoff_import_service import (
    AnalyzerHandoffImportService,
)


class AnalyzerHandoffPathTests(unittest.TestCase):
    def test_rejects_output_directory_outside_allowed_roots(self) -> None:
        with tempfile.TemporaryDirectory() as allowed, tempfile.TemporaryDirectory() as outside:
            service = AnalyzerHandoffImportService(allowed_roots=[Path(allowed)])

            result = service.import_output(outside)

        self.assertEqual(result.import_status, "blocked")
        self.assertEqual(result.files_read, [])
        self.assertEqual(result.issues[0].code, "output_dir_outside_allowed_roots")

    def test_relative_output_directory_is_resolved_under_first_allowed_root(self) -> None:
        with tempfile.TemporaryDirectory() as allowed:
            service = AnalyzerHandoffImportService(allowed_roots=[Path(allowed)])

            result = service.import_output("run-001")

        self.assertEqual(result.import_status, "missing_validated_handoff")
        self.assertEqual(Path(result.output_dir), Path(allowed).resolve() / "run-001")

    def test_rejects_symlink_escape_when_supported(self) -> None:
        with tempfile.TemporaryDirectory() as allowed, tempfile.TemporaryDirectory() as outside:
            link = Path(allowed) / "escaped"
            try:
                link.symlink_to(Path(outside), target_is_directory=True)
            except OSError:
                self.skipTest("Directory symlinks are not available on this Windows setup.")

            service = AnalyzerHandoffImportService(allowed_roots=[Path(allowed)])
            result = service.import_output(link)

        self.assertEqual(result.import_status, "blocked")
        self.assertEqual(result.files_read, [])
        self.assertEqual(result.issues[0].code, "output_dir_outside_allowed_roots")


if __name__ == "__main__":
    unittest.main()
