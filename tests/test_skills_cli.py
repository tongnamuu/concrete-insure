import asyncio
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest

import pymupdf
import yaml

from insurelens.skills_cli import execute
from insurelens.core import AppError

ROOT = Path(__file__).resolve().parents[1]
SKILLS = ("ocr-prescription", "drug-ingredient-resolver", "pdf-iso32000-annotator")


class SkillsCliTests(unittest.TestCase):
    def cli(self, skill, value, *, ok=True):
        result = subprocess.run([sys.executable, "-m", "insurelens.skills_cli", skill],
            input=json.dumps(value, ensure_ascii=False), text=True, capture_output=True,
            cwd=ROOT, env={**os.environ, "NVIDIA_API_KEY":"", "MFDS_API_KEY":""}, timeout=30)
        self.assertEqual(result.returncode, 0 if ok else 1, result.stderr + result.stdout)
        self.assertNotIn("Traceback", result.stderr)
        return json.loads(result.stdout)

    def test_text_candidates_are_literal_and_unconfirmed(self):
        source = "약품명: 조플루자\n질병코드: J10.1\n개인정보: 예시"
        value = self.cli(SKILLS[0], {"op":"text", "text":source})
        self.assertEqual(value["text"], source)
        self.assertTrue(value["requiresConfirmation"])
        self.assertEqual(value["candidates"], ["조플루자", "J10.1"])

    def test_unknown_fields_wrong_types_and_skills_fail_closed(self):
        self.assertEqual(self.cli(SKILLS[0], {"op":"text", "text":"약품명: 테스트", "cloudConsent":"true"}, ok=False), {"error":"INVALID_REQUEST"})
        self.assertEqual(self.cli(SKILLS[1], {"op":"from-text", "text":"조플루자", "ingredients":"invented"}, ok=False), {"error":"INVALID_REQUEST"})
        self.assertEqual(self.cli("unknown", {}, ok=False), {"error":"UNKNOWN_SKILL"})
        self.assertEqual(self.cli(SKILLS[2], {"op":"index", "pdf":"relative.pdf", "index":"/tmp/test.index"}, ok=False), {"error":"ABSOLUTE_PATH_REQUIRED"})

    def test_curated_reference_quotes_unchanged_and_live_is_explicit(self):
        from insurelens.agents.drug_references import resolve_drug_references
        result = self.cli(SKILLS[1], {"op":"from-text", "text":"조플루자"})
        self.assertEqual(result, resolve_drug_references(query="조플루자"))
        self.assertTrue(result["references"])
        self.assertTrue(all(ref["source"]["url"].startswith("https://") for ref in result["references"]))
        self.assertEqual(self.cli(SKILLS[1], {"op":"lookup", "name":"타미플루"}, ok=False), {"error":"MFDS_KEY_REQUIRED"})

    def test_pdf_roundtrip_text_preserved_and_tampering_rejected(self):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            original, index, output = root/"policy.pdf", root/"index.gz", root/"marked.pdf"
            document = pymupdf.open()
            page = document.new_page()
            page.insert_text((50,70), "약품명: 조플루자", fontname="korea")
            document.save(original)
            before = original.read_bytes()
            paths = {"pdf":str(original), "index":str(index)}
            self.assertEqual(self.cli(SKILLS[2], {"op":"index", **paths})["pages"], 1)
            found = self.cli(SKILLS[2], {"op":"search", **paths, "terms":["조플루자"]})
            self.assertEqual(found["hits"][0]["matchedText"], "조플루자")
            prescription = self.cli(SKILLS[0], {"op":"file", "path":str(original)})
            self.assertIn("조플루자", prescription["candidates"])
            result = self.cli(SKILLS[2], {"op":"annotate", **paths, "output":str(output), "hits":found["hits"]})
            self.assertGreater(result["count"], 0)
            with pymupdf.open(original) as first, pymupdf.open(output) as marked:
                self.assertEqual(first[0].get_text(), marked[0].get_text())
                marked_page = marked[0]
                self.assertEqual(next(marked_page.annots()).type[1], "Highlight")
            forged = copy.deepcopy(found["hits"])
            forged[0]["quote"] = "보험금을 받을 수 있습니다"
            self.assertIn("error", self.cli(SKILLS[2], {"op":"annotate", **paths, "output":str(root/"forged.pdf"), "hits":forged}, ok=False))
            self.assertFalse((root/"forged.pdf").exists())
            self.assertEqual(self.cli(SKILLS[2], {"op":"index", "pdf":str(original), "index":str(original)}, ok=False), {"error":"PATH_COLLISION"})
            self.assertEqual(original.read_bytes(), before)

    def test_image_requires_consent_even_with_configured_provider(self):
        class Fake:
            enabled = True
            ocr_enabled = True
            calls = 0
            async def ocr(self, data, mime=None):
                self.calls += 1
                return {"text":"약품명: 조플루자", "requiresConfirmation":True}
            async def chat(self, messages):
                return '{"terms":["조플루자"]}'
        provider = Fake()
        with TemporaryDirectory() as folder:
            image = Path(folder)/"image.png"
            image.write_bytes(b"image supplied to fake provider")
            with self.assertRaises(AppError):
                asyncio.run(execute(SKILLS[0], {"op":"file", "path":str(image)}, nim=provider))
            self.assertEqual(provider.calls, 0)
            result = asyncio.run(execute(SKILLS[0], {"op":"file", "path":str(image), "cloudConsent":True}, nim=provider))
            self.assertEqual(provider.calls, 1)
            self.assertTrue(result["requiresConfirmation"])
            self.assertEqual(result["candidates"], ["조플루자"])

    def test_discoverable_skill_frontmatter_matches_cli_names(self):
        for skill in SKILLS:
            raw = (ROOT/"skills"/skill/"SKILL.md").read_text()
            meta = yaml.safe_load(raw.split("---", 2)[1])
            self.assertEqual(meta["name"], skill)
            self.assertTrue(meta["description"])


if __name__ == "__main__":
    unittest.main()
